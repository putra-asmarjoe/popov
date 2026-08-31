"""Fix #118 — soft-delete chat session.

Coverage:
- soft_delete_session: set deletedAt + deletedBy + cascade ke messages.
- list/get memfilter deletedAt: None.
- Endpoint DELETE /chat/sessions/{id}: owner-only, tolak tiket, tolak stream aktif,
  idempotent (404 kedua).

Mock: `services.mongodb_client.get_db` → FakeDB (in-memory dict per collection)
sehingga test tidak butuh MongoDB hidup.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest


def run(coro):
    return asyncio.run(coro)


# ── Fake DB ──────────────────────────────────────────────────────────────────


class FakeCollection:
    def __init__(self):
        self.docs: Dict[str, Dict[str, Any]] = {}

    def __setitem__(self, key, value):
        self.docs[key] = value

    async def insert_one(self, doc):
        from bson import ObjectId
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self.docs[str(doc["_id"])] = doc
        from pymongo.results import InsertOneResult
        return InsertOneResult(doc["_id"], acknowledged=True)

    async def find_one(self, query, projection=None):
        for d in self.docs.values():
            if _match(d, query):
                return _project(d, projection)
        return None

    async def find_one_and_update(self, query, update, return_document=False):
        for d in self.docs.values():
            if _match(d, query):
                _apply_update(d, update)
                return d
        return None

    async def update_one(self, query, update):
        from pymongo.results import UpdateResult
        for d in self.docs.values():
            if _match(d, query):
                _apply_update(d, update)
                return UpdateResult(raw_result={"n": 1, "nModified": 1}, acknowledged=True)
        return UpdateResult(raw_result={"n": 0, "nModified": 0}, acknowledged=True)

    async def update_many(self, query, update):
        from pymongo.results import UpdateResult
        n = 0
        for d in self.docs.values():
            if _match(d, query):
                _apply_update(d, update)
                n += 1
        return UpdateResult(raw_result={"n": n, "nModified": n}, acknowledged=True)

    def find(self, query, projection=None):
        results = [_project(d, projection) for d in self.docs.values() if _match(d, query)]
        return _AsyncIter(results)


class _AsyncIter:
    def __init__(self, items):
        self._items = items

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._items = self._items[:n]
        return self

    async def __aiter__(self):
        for d in self._items:
            yield d


def _match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        elif doc.get(k) != v:
            return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    out = {}
    for k in projection.keys():
        if k.startswith("$"):
            continue
        if k in doc:
            out[k] = doc[k]
    return out


def _apply_update(doc, update):
    for op, fields in update.items():
        if op == "$set":
            doc.update(fields)
        elif op == "$push":
            for k, v in fields.items():
                doc.setdefault(k, []).append(v)
        elif op == "$pull":
            for k, v in fields.items():
                if k in doc and v in doc[k]:
                    doc[k].remove(v)


class FakeDB:
    def __init__(self):
        self._collections: Dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("services.chat_store.get_db", lambda: db)
    return db


# ── Tests store ──────────────────────────────────────────────────────────────


def test_soft_delete_marks_session_and_messages(fake_db):
    from bson import ObjectId
    from services import chat_store

    # Setup: sesi + 2 pesan
    sess = {
        "_id": ObjectId(),
        "userId": "u1",
        "projectId": "p1",
        "ticketId": None,
        "title": "Test session",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
    }
    fake_db["chat_sessions"].docs[str(sess["_id"])] = sess
    fake_db["chat_messages"].docs["m1"] = {"_id": "m1", "sessionId": str(sess["_id"]), "role": "user", "content": "hi", "createdAt": "t1"}
    fake_db["chat_messages"].docs["m2"] = {"_id": "m2", "sessionId": str(sess["_id"]), "role": "assistant", "content": "hello", "createdAt": "t2"}

    result = run(chat_store.soft_delete_session(str(sess["_id"]), "u1"))
    assert result is not None
    assert result["deleted"] == str(sess["_id"])
    assert result["messagesArchived"] == 2

    # Session ter-soft-delete → get/list exclude
    got = run(chat_store.get_session(str(sess["_id"])))
    assert got is None
    listed = run(chat_store.list_sessions("u1"))
    assert listed == []
    msgs = run(chat_store.get_messages(str(sess["_id"])))
    assert msgs == []


def test_soft_delete_idempotent(fake_db):
    from bson import ObjectId
    from services import chat_store

    sess = {
        "_id": ObjectId(),
        "userId": "u1",
        "projectId": "p1",
        "ticketId": None,
        "title": "Test",
        "createdAt": "t0",
        "updatedAt": "t0",
    }
    fake_db["chat_sessions"].docs[str(sess["_id"])] = sess

    r1 = run(chat_store.soft_delete_session(str(sess["_id"]), "u1"))
    assert r1 is not None
    r2 = run(chat_store.soft_delete_session(str(sess["_id"]), "u1"))
    assert r2 is None  # already archived


def test_list_sessions_excludes_archived(fake_db):
    from bson import ObjectId
    from services import chat_store

    a = {"_id": ObjectId(), "userId": "u1", "title": "A", "createdAt": "t0", "updatedAt": "t0"}
    b = {"_id": ObjectId(), "userId": "u1", "title": "B", "createdAt": "t0", "updatedAt": "t0", "deletedAt": "2026-01-02T00:00:00+00:00"}
    fake_db["chat_sessions"][str(a["_id"])] = a
    fake_db["chat_sessions"][str(b["_id"])] = b

    listed = run(chat_store.list_sessions("u1"))
    assert len(listed) == 1
    assert listed[0]["title"] == "A"


# ── Tests endpoint ───────────────────────────────────────────────────────────


def test_endpoint_requires_owner(fake_db, monkeypatch):
    from bson import ObjectId
    from fastapi import HTTPException
    from api.chat import delete_chat_session

    sess = {
        "_id": ObjectId(),
        "userId": "u_owner",
        "projectId": "p1",
        "ticketId": None,
        "title": "Owned by u_owner",
        "createdAt": "t0",
        "updatedAt": "t0",
    }
    fake_db["chat_sessions"].docs[str(sess["_id"])] = sess

    # monkeypatch is_active → False agar tak reach 409
    monkeypatch.setattr("api.chat.is_active", lambda sid: False)
    monkeypatch.setattr("api.chat.unregister", lambda sid: None)

    with pytest.raises(HTTPException) as exc:
        run(delete_chat_session(str(sess["_id"]), current_user={"_id": "u_other"}))
    assert exc.value.status_code == 403


def test_endpoint_rejects_ticket_bound(fake_db, monkeypatch):
    from bson import ObjectId
    from fastapi import HTTPException
    from api.chat import delete_chat_session

    sess = {
        "_id": ObjectId(),
        "userId": "u1",
        "projectId": "p1",
        "ticketId": "t1",
        "title": "Ticket-bound",
        "createdAt": "t0",
        "updatedAt": "t0",
    }
    fake_db["chat_sessions"].docs[str(sess["_id"])] = sess

    monkeypatch.setattr("api.chat.is_active", lambda sid: False)

    with pytest.raises(HTTPException) as exc:
        run(delete_chat_session(str(sess["_id"]), current_user={"_id": "u1"}))
    assert exc.value.status_code == 409
    assert "tiket" in str(exc.value.detail).lower()


def test_endpoint_rejects_active_stream(fake_db, monkeypatch):
    from bson import ObjectId
    from fastapi import HTTPException
    from api.chat import delete_chat_session

    sess = {
        "_id": ObjectId(),
        "userId": "u1",
        "projectId": "p1",
        "ticketId": None,
        "title": "Running",
        "createdAt": "t0",
        "updatedAt": "t0",
    }
    fake_db["chat_sessions"].docs[str(sess["_id"])] = sess

    monkeypatch.setattr("api.chat.is_active", lambda sid: True)

    with pytest.raises(HTTPException) as exc:
        run(delete_chat_session(str(sess["_id"]), current_user={"_id": "u1"}))
    assert exc.value.status_code == 409
    assert "berjalan" in str(exc.value.detail).lower()


def test_endpoint_success(fake_db, monkeypatch):
    from bson import ObjectId
    from api.chat import delete_chat_session

    sess = {
        "_id": ObjectId(),
        "userId": "u1",
        "projectId": "p1",
        "ticketId": None,
        "title": "Del me",
        "createdAt": "t0",
        "updatedAt": "t0",
    }
    fake_db["chat_sessions"].docs[str(sess["_id"])] = sess
    fake_db["chat_messages"].docs["m1"] = {"_id": "m1", "sessionId": str(sess["_id"]), "role": "user", "content": "x"}

    monkeypatch.setattr("api.chat.is_active", lambda sid: False)
    monkeypatch.setattr("api.chat.unregister", lambda sid: None)

    result = run(delete_chat_session(str(sess["_id"]), current_user={"_id": "u1"}))
    assert result["deleted"] == str(sess["_id"])
    assert result["messagesArchived"] == 1
    assert result["title"] == "Del me"
    assert "archivedAt" in result

    # Session arsip
    assert fake_db["chat_sessions"].docs[str(sess["_id"])]["deletedAt"] is not None
    assert fake_db["chat_sessions"].docs[str(sess["_id"])]["deletedBy"] == "u1"
    # Pesan ter-cascade
    assert fake_db["chat_messages"].docs["m1"]["deletedAt"] is not None
