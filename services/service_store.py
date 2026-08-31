"""
Service store — FE-8 Services Layer.
Collections (popovagent_db):
- service_library:         entitas service milik satu user (ownerId). service_id
                           WAJIB match service monitoring global (config JSON).
- project_service_refs:    link project → service library (tanpa salinan).
- service_knowledge_refs:  link service → knowledge library (1:N, single-source).

Kepemilikan ketat: hanya owner yang mutasi item library; link ke project butuh
owner + admin workspace; member workspace boleh baca via project.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

LIBRARY_COLLECTION = "service_library"
PROJECT_REFS_COLLECTION = "project_service_refs"
KNOWLEDGE_REFS_COLLECTION = "service_knowledge_refs"

SERVICE_ID_MAX_LEN = 64

# Fix #54: cache konteks knowledge service-per-project (build_service_context_for_agent).
# Mirip workspace_knowledge: TTL 30s + invalidate saat mutasi refs/links/hapus.
_SVC_CTX_CACHE: Dict[Tuple[str, str], Tuple[float, Tuple[bool, str]]] = {}
_SVC_CTX_TTL = 30.0


def invalidate_svc_context(project_id: Optional[str] = None) -> None:
    """Invalidate cache konteks knowledge service (project-scoped bila ada id)."""
    global _SVC_CTX_CACHE
    if project_id is None:
        _SVC_CTX_CACHE.clear()
    else:
        for k in [k for k in _SVC_CTX_CACHE if k[0] == project_id]:
            _SVC_CTX_CACHE.pop(k, None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oid(raw: str) -> Optional[ObjectId]:
    try:
        return ObjectId(raw)
    except Exception:
        return None


async def ensure_service_indexes() -> None:
    db = get_db()
    await db[LIBRARY_COLLECTION].create_index([("ownerId", 1), ("updatedAt", -1)])
    await db[LIBRARY_COLLECTION].create_index([("ownerId", 1), ("serviceId", 1)], unique=True)
    await db[PROJECT_REFS_COLLECTION].create_index(
        [("projectId", 1), ("libraryServiceId", 1)], unique=True
    )
    await db[PROJECT_REFS_COLLECTION].create_index("libraryServiceId")
    await db[KNOWLEDGE_REFS_COLLECTION].create_index(
        [("serviceLibraryId", 1), ("knowledgeLibraryId", 1)], unique=True
    )
    logger.info("Service layer indexes ensured")


# ── Registry global (sumber validasi) ─────────────────────────────────────────

async def global_service_ids() -> List[str]:
    """Daftar service_id terdaftar — MURNI DB (agent_docs via list_all_services).
    Fix #45: JSON legacy service_collection_map.json/db_configs TIDAK lagi dibaca."""
    try:
        from services.doc_loader import list_all_services
        return sorted((await list_all_services()).keys())
    except Exception as e:
        logger.warning(f"global_service_ids failed: {e}")
        return []


async def is_globally_registered(service_id: str) -> bool:
    return service_id in await global_service_ids()


async def _public_item(doc: Dict[str, Any], project_count: int = 0, knowledge_count: int = 0) -> Dict[str, Any]:
    # db_config: URI di-mask kredensialnya sebelum keluar API
    raw_db = doc.get("dbConfig") or None
    db_public = None
    if raw_db:
        try:
            from services.config_manager import mask_uri
            masked_uri = mask_uri(str(raw_db.get("uri") or ""))
        except Exception:
            masked_uri = str(raw_db.get("uri") or "")
        db_public = {
            "type": raw_db.get("type"),
            "db": raw_db.get("db"),
            "collection": raw_db.get("collection"),
            "uri": masked_uri,
            "has_uri": bool(raw_db.get("uri")),
        }
    return {
        "id": str(doc["_id"]),
        "ownerId": doc.get("ownerId", ""),
        "serviceId": doc.get("serviceId", ""),
        "label": doc.get("label") or "",
        "description": doc.get("description") or "",
        "dbConfig": db_public,
        "globallyRegistered": await is_globally_registered(doc.get("serviceId", "")),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "projectCount": project_count,
        "knowledgeCount": knowledge_count,
    }


def _public_project_ref(doc: Dict[str, Any], item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "projectId": doc.get("projectId", ""),
        "libraryServiceId": doc.get("libraryServiceId", ""),
        "serviceId": (item or {}).get("serviceId", "?"),
        "label": (item or {}).get("label", ""),
        "description": (item or {}).get("description", ""),
        "ownerId": (item or {}).get("ownerId", ""),  # FE-8.1: kelola hanya oleh pemilik
        "addedBy": doc.get("addedBy", ""),
        "addedAt": doc.get("addedAt"),
    }


def _public_knowledge_ref(doc: Dict[str, Any], item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "serviceLibraryId": doc.get("serviceLibraryId", ""),
        "knowledgeLibraryId": doc.get("knowledgeLibraryId", ""),
        "name": (item or {}).get("name", "?"),
        "folder": (item or {}).get("folder", "?"),
        "ownerId": (item or {}).get("ownerId", ""),  # FE-8.1: UI tampilkan edit utk owner saja
        "addedBy": doc.get("addedBy", ""),
        "addedAt": doc.get("addedAt"),
    }


# ── Library (milik owner tunggal) ─────────────────────────────────────────────

def _validate_db_config(db_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validasi & normalisasi koneksi log database per-service (Fix #38).
    Hanya type/uri/db/collection yang diterima; uri wajib http(s)/mongodb/mysql scheme bila ada."""
    if not db_config:
        return None
    allowed = {k: v for k, v in (db_config or {}).items() if k in ("type", "uri", "db", "collection") and v}
    if not allowed:
        return None
    t = (allowed.get("type") or "mongodb").lower()
    if t not in ("mongodb", "mysql"):
        raise ValueError("db_config.type harus mongodb atau mysql")
    allowed["type"] = t
    if len(allowed) < 3:  # minimal type+2 field lain agar berguna
        raise ValueError("db_config butuh minimal type, uri, dan db/collection")
    return allowed


async def create_item(
    owner_id: str,
    service_id: str,
    label: str = "",
    description: str = "",
    db_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    service_id = (service_id or "").strip().lower()
    if not service_id or len(service_id) > SERVICE_ID_MAX_LEN or not all(
        c.isalnum() or c in "_-" for c in service_id
    ):
        raise ValueError("service_id tidak valid (huruf kecil/angka/-/_, maks 64)")
    # Fix #38: registry global TIDAK lagi wajib — service bebas dibuat (analogi deployment K8s).
    # is_globally_registered tetap tersedia untuk badge UI.
    validated_db = _validate_db_config(db_config)

    db = get_db()
    doc = {
        "ownerId": owner_id,
        "serviceId": service_id,
        "label": (label or "").strip(),
        "description": (description or "").strip(),
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }
    if validated_db:
        doc["dbConfig"] = validated_db
    try:
        result = await db[LIBRARY_COLLECTION].insert_one(doc)
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise ValueError(f"Service '{service_id}' sudah ada di library Anda")
        raise
    doc["_id"] = result.inserted_id
    logger.info(f"Service library item created '{service_id}' by {owner_id}")
    return doc


async def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    oid = _oid(item_id)
    if oid is None:
        return None
    return await get_db()[LIBRARY_COLLECTION].find_one({"_id": oid})


async def list_items_for_owner(owner_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    items = [doc async for doc in db[LIBRARY_COLLECTION].find({"ownerId": owner_id}).sort("updatedAt", -1)]
    ids = [str(i["_id"]) for i in items]
    proj_counts = await _count_by(PROJECT_REFS_COLLECTION, "libraryServiceId", ids)
    know_counts = await _count_by(KNOWLEDGE_REFS_COLLECTION, "serviceLibraryId", ids)
    return [
        await _public_item(i, proj_counts.get(str(i["_id"]), 0), know_counts.get(str(i["_id"]), 0))
        for i in items
    ]


async def _count_by(collection: str, field: str, ids: List[str]) -> Dict[str, int]:
    if not ids:
        return {}
    counts = {i: 0 for i in ids}
    async for row in get_db()[collection].aggregate([
        {"$match": {field: {"$in": ids}}},
        {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = row["n"]
    return counts


async def update_item(item_id: str, owner_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update label/description/db_config. service_id IMMUTABLE. Hanya owner."""
    doc = await get_item(item_id)
    if doc is None or doc.get("ownerId") != owner_id:
        return None
    set_fields: Dict[str, Any] = {"updatedAt": _now_iso()}
    if updates.get("label") is not None:
        set_fields["label"] = str(updates["label"]).strip()
    if updates.get("description") is not None:
        set_fields["description"] = str(updates["description"]).strip()
    if "db_config" in updates:
        validated = _validate_db_config(updates.get("db_config"))
        # db_config kosong {} berarti hapus koneksi
        if validated:
            set_fields["dbConfig"] = validated
        else:
            set_fields["dbConfig"] = None
    await get_db()[LIBRARY_COLLECTION].update_one({"_id": doc["_id"]}, {"$set": set_fields})
    return await get_item(item_id)


# ── Fase D pattern: resolusi DB config untuk agent (Fix #38) ─────────────────

async def all_service_ids() -> List[str]:
    """Semua service_id unik dari library user — kandidat routing supervisor."""
    ids: List[str] = []
    async for row in get_db()[LIBRARY_COLLECTION].aggregate([
        {"$group": {"_id": "$serviceId"}},
        {"$sort": {"_id": 1}},
    ]):
        sid = row["_id"]
        if sid:
            ids.append(str(sid))
    return ids


async def get_db_config_for_service(service_id: str) -> Optional[Dict[str, Any]]:
    """
    Cari db_config (koneksi log transaksi) dari service library yang cocok.
    Dipakai db_loader bila service TIDAK terdaftar di service_db_configs.json.
    Return dict {type,uri,db,collection} atau None.
    """
    if not service_id:
        return None
    doc = await get_db()[LIBRARY_COLLECTION].find_one(
        {"serviceId": service_id.lower(), "dbConfig": {"$exists": True, "$ne": None}},
        sort=[("updatedAt", -1)],
    )
    cfg = (doc or {}).get("dbConfig")
    return cfg or None


async def service_ids_for_project(project_id: str) -> List[str]:
    """
    Fix #43: service_id yang TER-LINK ke sebuah project (FE-8 project refs).
    Dipakai supervisor untuk project-gated recognition — service di luar daftar
    ini tidak dikenali bila request berasal dari project.
    """
    if not project_id:
        return []
    refs = await list_refs_for_project(project_id)
    return sorted({r["serviceId"] for r in refs if r.get("serviceId")})


async def delete_item(item_id: str, owner_id: str) -> bool:
    """Cascade: hapus project refs + knowledge refs. WAJIB lewat confirm UI."""
    doc = await get_item(item_id)
    if doc is None or doc.get("ownerId") != owner_id:
        return False
    db = get_db()
    r1 = await db[PROJECT_REFS_COLLECTION].delete_many({"libraryServiceId": item_id})
    r2 = await db[KNOWLEDGE_REFS_COLLECTION].delete_many({"serviceLibraryId": item_id})
    await db[LIBRARY_COLLECTION].delete_one({"_id": doc["_id"]})
    invalidate_svc_context()
    logger.info(
        f"Service library deleted '{doc.get('serviceId')}' by {owner_id} "
        f"(project refs: {r1.deleted_count}, knowledge links: {r2.deleted_count})"
    )
    return True


# ── Usage & links project ─────────────────────────────────────────────────────

async def list_usage(item_id: str) -> List[Dict[str, Any]]:
    """Project pemakai sebuah service library (untuk warning cascade)."""
    db = get_db()
    refs = [doc async for doc in db[PROJECT_REFS_COLLECTION].find({"libraryServiceId": item_id})]
    if not refs:
        return []
    oids = [o for o in (_oid(r["projectId"]) for r in refs) if o]
    projects = await db["projects"].find({"_id": {"$in": oids}}, {"name": 1}).to_list(len(oids))
    name_by_id = {str(p["_id"]): p.get("name", "?") for p in projects}
    return [{"projectId": r["projectId"], "name": name_by_id.get(r["projectId"], "?")} for r in refs]


async def add_project_ref(project_id: str, item_id: str, user_id: str) -> Dict[str, Any]:
    try:
        result = await get_db()[PROJECT_REFS_COLLECTION].insert_one({
            "projectId": project_id,
            "libraryServiceId": item_id,
            "addedBy": user_id,
            "addedAt": _now_iso(),
        })
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise ValueError("Service ini sudah ter-link ke project")
        raise
    invalidate_svc_context(project_id)
    return await get_db()[PROJECT_REFS_COLLECTION].find_one({"_id": result.inserted_id})


async def list_refs_for_project(project_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    refs = [d async for d in db[PROJECT_REFS_COLLECTION].find({"projectId": project_id}).sort("addedAt", 1)]
    if not refs:
        return []
    oids = [o for o in (_oid(r["libraryServiceId"]) for r in refs) if o]
    items = await db[LIBRARY_COLLECTION].find({"_id": {"$in": oids}}).to_list(len(oids))
    by_id = {str(i["_id"]): i for i in items}
    return [_public_project_ref(r, by_id.get(r["libraryServiceId"])) for r in refs]


async def remove_project_ref(project_id: str, ref_id: str) -> bool:
    oid = _oid(ref_id)
    if oid is None:
        return False
    result = await get_db()[PROJECT_REFS_COLLECTION].delete_one({"_id": oid, "projectId": project_id})
    if result.deleted_count:
        invalidate_svc_context(project_id)
    return result.deleted_count > 0


async def detach_project_refs(project_id: str) -> int:
    """Lepas SEMUA service dari sebuah project (soft-delete project — FE-8.4).

    Library service & knowledge links antar library TIDAK disentuh.
    Return jumlah link yang dilepas.
    """
    result = await get_db()[PROJECT_REFS_COLLECTION].delete_many({"projectId": project_id})
    from services.workspace_knowledge import invalidate_cache
    invalidate_cache()
    invalidate_svc_context(project_id)
    if result.deleted_count:
        logger.info(f"Detached {result.deleted_count} service refs dari project {project_id}")
    return result.deleted_count


async def list_refs_for_workspace_grouped(ws_id: str) -> List[Dict[str, Any]]:
    """Semua project milik workspace — grouped, TERMASUK project tanpa service.

    Return [{projectId, projectName, services: [ref…]}] untuk halaman settings
    (FE-8.1: pengelolaan service dipindah dari ProjectPage ke workspace settings).
    Project tanpa link tetap muncul (services: []) supaya admin punya tombol
    "Tambah service" — tanpa itu tidak ada jalur melink service pertama.
    """
    db = get_db()
    projects = await db["projects"].find(
        {"workspaceId": ws_id, "deletedAt": None}
    ).sort("createdAt", 1).to_list(100)
    pid_by_oid = {str(p["_id"]): p for p in projects}
    refs = [d async for d in db[PROJECT_REFS_COLLECTION].find(
        {"projectId": {"$in": list(pid_by_oid.keys())}}
    ).sort("addedAt", 1)]

    oids = [o for o in (_oid(r["libraryServiceId"]) for r in refs) if o]
    items = await db[LIBRARY_COLLECTION].find({"_id": {"$in": oids}}).to_list(len(oids))
    item_by_id = {str(i["_id"]): i for i in items}

    # FE-8.2: sertakan knowledge ter-link per service (agar UI bisa tampil langsung)
    all_svc_ids = [r["libraryServiceId"] for r in refs]
    klinks = [d async for d in db[KNOWLEDGE_REFS_COLLECTION].find(
        {"serviceLibraryId": {"$in": all_svc_ids}}
    ).sort("addedAt", 1)]
    kb_oids = [o for o in (_oid(k["knowledgeLibraryId"]) for k in klinks) if o]
    kb_docs = await db["knowledge_library"].find(
        {"_id": {"$in": kb_oids}}, {"name": 1, "folder": 1, "ownerId": 1}
    ).to_list(len(kb_oids))
    kb_by_id = {str(d["_id"]): d for d in kb_docs}
    knowledge_by_svc: Dict[str, List[Dict[str, Any]]] = {}
    for k in klinks:
        kb = kb_by_id.get(k["knowledgeLibraryId"])
        if kb is None:
            continue
        knowledge_by_svc.setdefault(k["serviceLibraryId"], []).append({
            "refId": str(k["_id"]),
            "knowledgeLibraryId": k["knowledgeLibraryId"],
            "name": kb.get("name", "?"),
            "folder": kb.get("folder", "?"),
            "ownerId": kb.get("ownerId", ""),
        })

    # FIX: resolve knowledge for workspace_service_registry services
    # that are NOT linked via project_service_refs (direct knowledge
    # added via ServiceKnowledgeDialog must appear in hierarchy).
    from services.workspace_service_registry import WS_SERVICE_REGISTRY_COLLECTION
    registry_docs = await db[WS_SERVICE_REGISTRY_COLLECTION].find(
        {"workspace_id": ws_id}
    ).to_list(500)
    covered_sids = set()
    for r in refs:
        lib_item = item_by_id.get(r["libraryServiceId"])
        if lib_item:
            covered_sids.add(lib_item.get("serviceId", ""))
    uncovered_items = []
    sys_owner_id = f"system:{ws_id}"
    all_related_libs = []

    for rd in registry_docs:
        sid = rd.get("service_id", "")
        if sid and sid not in covered_sids:
            alt_sids = list({sid, sid.replace("-", "_"), sid.replace("_", "-")})
            libs = await db[LIBRARY_COLLECTION].find({
                "$or": [
                    {"serviceId": {"$in": alt_sids}},
                    {"ownerId": sys_owner_id, "serviceId": {"$in": alt_sids}},
                ]
            }).to_list(50)
            for lib in libs:
                str_id = str(lib["_id"])
                if not any(u["_id"] == lib["_id"] for u in uncovered_items):
                    uncovered_items.append(lib)
                item_by_id[str_id] = lib

    if uncovered_items:
        extra_ids = [str(i["_id"]) for i in uncovered_items]
        alt_names = set()
        for i in uncovered_items:
            sname = i.get("serviceId", "")
            alt_names.update([sname, sname.replace("-", "_"), sname.replace("_", "-")])
        
        all_related_libs = await db[LIBRARY_COLLECTION].find({
            "$or": [
                {"serviceId": {"$in": list(alt_names)}},
                {"ownerId": sys_owner_id}
            ]
        }).to_list(100)
        all_related_ids = list({str(l["_id"]) for l in all_related_libs} | set(extra_ids))

        extra_klinks = [d async for d in db[KNOWLEDGE_REFS_COLLECTION].find(
            {"serviceLibraryId": {"$in": all_related_ids}}
        ).sort("addedAt", 1)]
        extra_kb_oids = [o for o in (_oid(k["knowledgeLibraryId"]) for k in extra_klinks) if o]
        if extra_kb_oids:
            extra_kb_docs = await db["knowledge_library"].find(
                {"_id": {"$in": extra_kb_oids}}, {"name": 1, "folder": 1, "ownerId": 1}
            ).to_list(len(extra_kb_oids))
            extra_kb_by_id = {str(d["_id"]): d for d in extra_kb_docs}
            for k in extra_klinks:
                kb = extra_kb_by_id.get(k["knowledgeLibraryId"])
                if kb is None:
                    continue
                knowledge_by_svc.setdefault(k["serviceLibraryId"], []).append({
                    "refId": str(k["_id"]),
                    "knowledgeLibraryId": k["knowledgeLibraryId"],
                    "name": kb.get("name", "?"),
                    "folder": kb.get("folder", "?"),
                    "ownerId": kb.get("ownerId", ""),
                })

    grouped: Dict[str, Dict[str, Any]] = {
        pid: {"projectId": pid, "projectName": p.get("name", "?"), "services": []}
        for pid, p in pid_by_oid.items()
    }
    for r in refs:
        g = grouped.get(r["projectId"])
        if g is None:
            continue
        pub = _public_project_ref(r, item_by_id.get(r["libraryServiceId"]))
        pub["knowledge"] = knowledge_by_svc.get(r["libraryServiceId"], [])
        g["services"].append(pub)
    # Add registry-only services (not linked to any project) under a
    # synthetic "__registry__" group so hierarchy can resolve their knowledge.
    if uncovered_items:
        unlinked_svcs = []
        seen_unlinked_sids = set()
        for lib in uncovered_items:
            sid = lib.get("serviceId", "")
            norm_sid = sid.replace("_", "-")
            if norm_sid in seen_unlinked_sids:
                continue
            seen_unlinked_sids.add(norm_sid)

            str_id = str(lib["_id"])
            synthetic_ref = {
                "_id": lib["_id"],
                "libraryServiceId": str_id,
                "projectId": "__registry__",
                "addedBy": lib.get("ownerId", ""),
                "addedAt": lib.get("createdAt"),
            }
            pub = _public_project_ref(synthetic_ref, lib)
            
            # Combine knowledge from this lib AND any related lib_id sharing the same normalized serviceId
            alt_names = {sid, sid.replace("-", "_"), sid.replace("_", "-")}
            combined_kbs = []
            seen_kb_ids = set()
            for rel_lib in all_related_libs:
                if rel_lib.get("serviceId") in alt_names:
                    rel_id = str(rel_lib["_id"])
                    for kb_item in knowledge_by_svc.get(rel_id, []):
                        if kb_item["knowledgeLibraryId"] not in seen_kb_ids:
                            seen_kb_ids.add(kb_item["knowledgeLibraryId"])
                            combined_kbs.append(kb_item)

            pub["knowledge"] = combined_kbs
            unlinked_svcs.append(pub)
        grouped["__registry__"] = {
            "projectId": "__registry__",
            "projectName": "Registry",
            "services": unlinked_svcs,
        }
    return list(grouped.values())


# ── Links knowledge (1 service : N knowledge) ─────────────────────────────────

async def link_knowledge(service_item_id: str, knowledge_item_id: str, user_id: str) -> Dict[str, Any]:
    """Link knowledge ke service. Caller WAJIB verifikasi owner kedua-duanya."""
    try:
        result = await get_db()[KNOWLEDGE_REFS_COLLECTION].insert_one({
            "serviceLibraryId": service_item_id,
            "knowledgeLibraryId": knowledge_item_id,
            "addedBy": user_id,
            "addedAt": _now_iso(),
        })
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise ValueError("Knowledge ini sudah ter-link ke service")
        raise
    invalidate_svc_context()
    return await get_db()[KNOWLEDGE_REFS_COLLECTION].find_one({"_id": result.inserted_id})


async def list_knowledge_links(service_item_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    refs = [d async for d in db[KNOWLEDGE_REFS_COLLECTION].find({"serviceLibraryId": service_item_id})]
    if not refs:
        return []
    oids = [o for o in (_oid(r["knowledgeLibraryId"]) for r in refs) if o]
    items = await db["knowledge_library"].find(
        {"_id": {"$in": oids}}, {"name": 1, "folder": 1, "ownerId": 1}
    ).to_list(len(oids))
    by_id = {str(i["_id"]): i for i in items}
    return [_public_knowledge_ref(r, by_id.get(r["knowledgeLibraryId"])) for r in refs]


async def unlink_knowledge(service_item_id: str, ref_id: str) -> bool:
    oid = _oid(ref_id)
    if oid is None:
        return False
    result = await get_db()[KNOWLEDGE_REFS_COLLECTION].delete_one({
        "_id": oid, "serviceLibraryId": service_item_id,
    })
    if result.deleted_count:
        invalidate_svc_context()
    return result.deleted_count > 0


# ── Konsumsi agent: konteks per-service untuk sebuah project ─────────────────

async def build_service_context_for_agent(project_id: str, service_name: str) -> tuple[bool, str]:
    """Cari service MILIK PROJECT yang match `service_name` hasil routing.

    Returns (matched, markdown). matched=True bila project punya service tsb;
    markdown berisi gabungan knowledge ter-link (bisa '' bila belum ada knowledge).
    Fix #54: hasil di-cache TTL 30s per (project, service) — agent TIDAK buka DB
    per call; invalidate_svc_context() dipanggil saat mutasi refs/links/hapus.
    """
    cache_key = (project_id or "", service_name)
    now = time.monotonic()
    hit = _SVC_CTX_CACHE.get(cache_key)
    if hit and now - hit[0] < _SVC_CTX_TTL:
        return hit[1]

    refs = await list_refs_for_project(project_id)
    target_ref = next((r for r in refs if r["serviceId"] == service_name), None)
    if target_ref is None:
        _SVC_CTX_CACHE[cache_key] = (now, (False, ""))
        return False, ""

    links = await list_knowledge_links(target_ref["libraryServiceId"])
    if not links:
        _SVC_CTX_CACHE[cache_key] = (now, (True, ""))
        return True, ""

    db = get_db()
    oids = [o for o in (_oid(l["knowledgeLibraryId"]) for l in links) if o]
    docs = await db["knowledge_library"].find({"_id": {"$in": oids}}).to_list(len(oids))
    parts = [f"## Knowledge Service '{service_name}'", ""]
    for d in docs[:6]:
        body = (d.get("content") or "").strip()[:settings.embedding_max_chars]
        if not body:
            continue
        parts.append(f"### {d.get('name')} ({d.get('folder')})")
        parts.append(body)
        parts.append("")
    md = "\n".join(parts).strip()
    logger.info(f"[ServiceStore] service context matched project={project_id} svc={service_name} docs={len(docs)}")
    _SVC_CTX_CACHE[cache_key] = (now, (True, md))
    return True, md
