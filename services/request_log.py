"""
Request audit logging: catat setiap request yang masuk ke pipeline ke MongoDB.
Collection: request_logs (db popovagent_db).

Setiap request dicatat saat masuk (status: processing) dan diperbarui saat
pipeline selesai (status: success / failed) beserta jejak agent, balasan, dan waktu.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from config.settings import settings
from services.mongodb_client import get_db

logger = logging.getLogger(__name__)

REQUEST_LOG_COLLECTION = "request_logs"
WATCHDOG_ALERT_COLLECTION = "watchdog_alerts"


def generate_request_id() -> str:
    """Generate unique request id."""
    return uuid.uuid4().hex[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: Any, max_len: int = 200) -> Any:
    """Truncate string dalam dokumen agar snapshot tetap ringkas."""
    if isinstance(value, str):
        return value[:max_len]
    if isinstance(value, list):
        return [_truncate(v, max_len) for v in value]
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    return value


def _snapshot_documents(raw_documents: list, max_docs: int = 5) -> list:
    """Buat snapshot data mentah yang ringkas utk keperluan follow-up."""
    try:
        snapshot = []
        for doc in raw_documents[:max_docs]:
            item = {k: _truncate(v) for k, v in doc.items() if k != "_id"}
            snapshot.append(item)
        return snapshot
    except Exception as e:
        logger.error(f"Failed to snapshot raw documents: {e}")
        return []


async def ensure_indexes() -> None:
    """Buat index untuk collection request_logs, watchdog_alerts, incident_episodes, diagnostic_sessions."""
    try:
        db = get_db()
        collection = db[REQUEST_LOG_COLLECTION]
        await collection.create_index("request_id", unique=True)
        await collection.create_index([("incoming_date", -1)])
        await collection.create_index("channel")
        # FASE 6B: index untuk audit routing_strategy
        try:
            await collection.create_index([("routing_strategy", 1)])
        except Exception:
            pass
        # follow-up chat lookup by session (sender.session_id)
        try:
            await collection.create_index("sender.session_id")
        except Exception:
            pass
        logger.info(f"Indexes ensured on '{REQUEST_LOG_COLLECTION}'")

        watchdog = db[WATCHDOG_ALERT_COLLECTION]
        await watchdog.create_index("alert_id", unique=True)
        await watchdog.create_index([("sent_at", -1)])
        # Fix #84: dedup broadcast lintas-target via content_fp + window
        try:
            await watchdog.create_index([("content_fp", 1), ("sent_at", -1)])
        except Exception:
            pass
        logger.info(f"Indexes ensured on '{WATCHDOG_ALERT_COLLECTION}'")

        # Second Brain — Fase 1
        try:
            episodes = db["incident_episodes"]
            await episodes.create_index([("episode_id", 1)], unique=True)
            await episodes.create_index([("service_name", 1), ("timestamp", -1)])
            await episodes.create_index([("feedback", 1)])
            await episodes.create_index([("created_at", -1)])
            # MT isolation (MT-5): compound index workspace-scoped query
            try:
                await episodes.create_index([("workspace_id", 1), ("service_name", 1), ("timestamp", -1)])
            except Exception:
                pass
            logger.info("Indexes ensured on 'incident_episodes'")
        except Exception as e2:
            logger.error(f"Failed to ensure incident_episodes indexes: {e2}")

        # MT isolation (MT-2/MT-6): compound index request_logs & watchdog_alerts
        try:
            await collection.create_index([("workspace_id", 1), ("incoming_date", -1)])
            await watchdog.create_index([("workspace_id", 1), ("observ_id", 1), ("sent_at", -1)])
        except Exception as e3:
            logger.warning(f"MT compound indexes not ensured: {e3}")

        # Fase 6C: Diagnostic sessions TTL
        try:
            diag = db["diagnostic_sessions"]
            await diag.create_index([("expires_at", 1)], expireAfterSeconds=0)
            await diag.create_index([("chat_id", 1), ("status", 1)])
            logger.info("Indexes ensured on 'diagnostic_sessions' (TTL)")
        except Exception as e2:
            logger.error(f"Failed to ensure diagnostic_sessions indexes: {e2}")
    except Exception as e:
        logger.error(f"Failed to ensure indexes: {e}")


async def create_request_log(
    channel: str,
    message_raw: str,
    sender: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Optional[str]:
    """
    Insert dokumen awal request log (status: processing).
    Return request_id, atau None jika gagal (tidak merusak pipeline).
    """
    request_id = request_id or generate_request_id()
    document = {
        "request_id": request_id,
        "channel": channel,
        "incoming_date": _now_iso(),
        "sender": sender or {},
        "message": message_raw,
        "service_name": None,
        "collection_name": None,
        "agents_visited": [],
        "reply": None,
        "status": "processing",
        "error": None,
        "replied_date": None,
    }
    try:
        db = get_db()
        await db[REQUEST_LOG_COLLECTION].insert_one(document)
        logger.info(f"[{request_id}] Request log created (channel={channel})")
        return request_id
    except Exception as e:
        logger.error(f"[{request_id}] Failed to create request log: {e}")
        return None


async def update_request_log(
    request_id: Optional[str],
    state: Dict[str, Any],
    status: str,
    error: Optional[str] = None,
    reply: Optional[Dict[str, Any]] = None,
    raw_documents: Optional[list] = None,
    investigation_state: Optional[dict] = None,
    agent_traces: Optional[list] = None,
) -> None:
    """
    Update dokumen request log setelah pipeline selesai.
    status: "success" | "failed".
    raw_documents: snapshot data mentah (dipotong) agar bisa dipakai utk follow-up.
    investigation_state (CHATFLOW V2.1 Tahap 3): ringkasan investigasi utk follow_up_agent.
    agent_traces (Per-Agent Tracing Fase 1): [{agent, order, duration_ms, summary}] per node.
    Gagal logging tidak boleh melempar exception ke pipeline.
    """
    if not request_id:
        return

    update = {
        "service_name": state.get("service_name") or None,
        "collection_name": state.get("collection_name") or None,
        "workspace_id": state.get("workspace_id") or None,   # MT isolation (MT-2)
        "agents_visited": state.get("agents_visited") or [],
        "status": status,
        "error": error or state.get("error") or None,
        "replied_date": _now_iso(),
    }
    if raw_documents:
        update["raw_documents_snapshot"] = _snapshot_documents(raw_documents)
    if investigation_state is not None:
        update["investigation_state"] = investigation_state
    if agent_traces is not None:
        update["agent_traces"] = agent_traces
        update["agent_sequence"] = [t.get("agent") for t in agent_traces if isinstance(t, dict)]
    if reply:
        update["reply"] = reply

    try:
        db = get_db()
        await db[REQUEST_LOG_COLLECTION].update_one(
            {"request_id": request_id},
            {"$set": update},
        )
        logger.info(f"[{request_id}] Request log updated → status={status}")
    except Exception as e:
        logger.error(f"[{request_id}] Failed to update request log: {e}")


async def get_incident_history(
    service_name: str,
    hours: int = 24,
    limit: int = 5,
) -> list:
    """
    Ambil riwayat request/insiden terakhir untuk service tertentu dari request_logs
    (Use Case A — Incident History Memory).

    Digunakan oleh response_agent sebagai konteks tambahan agar agent bisa
    mengenali pola: "service ini sudah error N kali dalam window waktu X".
    Return list ringkasan, atau [] jika gagal (tidak merusak pipeline).
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        db = get_db()
        cursor = (
            db[REQUEST_LOG_COLLECTION]
            .find({"service_name": service_name, "incoming_date": {"$gte": since}})
            .sort("incoming_date", -1)
            .limit(limit)
        )
        docs = []
        async for d in cursor:
            docs.append(
                {
                    "incoming_date": d.get("incoming_date"),
                    "channel": d.get("channel"),
                    "message": (d.get("message") or "")[:200],
                    "status": d.get("status"),
                    "error": (d.get("error") or "")[:200],
                    "agents_visited": d.get("agents_visited") or [],
                }
            )
        logger.info(
            f"[incident-history] service='{service_name}' window={hours}h → {len(docs)} prior requests"
        )
        return docs
    except Exception as e:
        logger.error(f"Failed to fetch incident history for '{service_name}': {e}")
        return []


async def get_latest_request(
    sender: Optional[Dict[str, Any]] = None,
    exclude_request_id: Optional[str] = None,
    service_name: Optional[str] = None,
    statuses: Optional[list] = None,
) -> Optional[dict]:
    """
    Ambil request log TERAKHIR milik sender yang sama (Phase 1 — follow-up).

    Pencocokan sender:
    - telegram → channel + chat_id (atau id)
    - api      → channel + name (dan ip jika ada)

    Return dokumen lengkap (termasuk reply & raw_documents_snapshot),
    atau None jika tidak ada / gagal.
    """
    try:
        query: Dict[str, Any] = {}
        if service_name:
            query["service_name"] = service_name
        if exclude_request_id:
            query["request_id"] = {"$ne": exclude_request_id}
        if statuses:
            query["status"] = {"$in": statuses}

        if sender:
            channel = sender.get("channel")
            if channel == "telegram":
                query["sender.channel"] = "telegram"
                if sender.get("chat_id"):
                    query["sender.chat_id"] = str(sender["chat_id"])
                elif sender.get("id"):
                    query["sender.id"] = sender["id"]
            elif channel == "api":
                query["sender.channel"] = "api"
                if sender.get("name"):
                    query["sender.name"] = sender["name"]
            elif channel == "chat":
                # Fix: follow-up chat scoped per sesi (bukan log global lintas channel)
                query["sender.channel"] = "chat"
                if sender.get("session_id"):
                    query["sender.session_id"] = sender["session_id"]

        db = get_db()
        doc = await db[REQUEST_LOG_COLLECTION].find_one(query, sort=[("incoming_date", -1)])
        if not doc:
            logger.info("[get_latest_request] no previous request found")
            return None
        doc["_id"] = str(doc["_id"])
        logger.info(f"[get_latest_request] found request_id={doc.get('request_id')}")
        return doc
    except Exception as e:
        logger.error(f"Failed to get latest request: {e}")
        return None


async def create_watchdog_alert(
    service_name: str,
    message: str,
    trace_id: Optional[str] = None,
    trace_ids: Optional[list] = None,
    alert_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    observ_id: Optional[str] = None,
    fingerprint: Optional[str] = None,
    content_fp: Optional[str] = None,
) -> Optional[str]:
    """
    Simpan pesan alert watchdog yang dikirim ke Telegram ke collection watchdog_alerts.
    Field trace_id/trace_ids disimpan agar saat tombol "Cek Detail" diklik, listener
    bisa menelusuri trace spesifik yang memicu alert (bukan search random).
    workspace_id/observ_id (MT-2): identitas tenant sumber alert (None = legacy global).
    fingerprint (Layer 2): composite fingerprint utk dedup antar sumber push/poll.
    content_fp (Fix #84): fingerprint KONTEN stabil (tanpa observ_id) utk dedup
    LINTAS-target — target berbeda yang mendeteksi alert sama tidak broadcast dobel.
    Return alert_id, atau None jika gagal (tidak merusak watchdog).
    """
    alert_id = alert_id or generate_request_id()
    document = {
        "alert_id": alert_id,
        "service_name": service_name,
        "message": message,
        "trace_id": trace_id,
        "trace_ids": trace_ids or ([trace_id] if trace_id else []),
        "workspace_id": workspace_id or None,
        "observ_id": observ_id or None,
        "fingerprint": fingerprint or None,
        "content_fp": content_fp or None,
        "sender": {"channel": "watchdog"},
        "sent_at": _now_iso(),
        "status": "notified",
        "reply": None,
    }
    try:
        db = get_db()
        await db[WATCHDOG_ALERT_COLLECTION].insert_one(document)
        logger.info(f"[watchdog-alert] saved alert_id={alert_id} service='{service_name}'")
        return alert_id
    except Exception as e:
        logger.error(f"[watchdog-alert] failed to save alert for '{service_name}': {e}")
        return None


async def get_watchdog_alert(alert_id: str) -> Optional[dict]:
    """Ambil pesan alert watchdog tersimpan berdasarkan alert_id (untuk Cek Detail)."""
    try:
        db = get_db()
        doc = await db[WATCHDOG_ALERT_COLLECTION].find_one({"alert_id": alert_id})
        if not doc:
            logger.info(f"[watchdog-alert] alert_id={alert_id} not found")
            return None
        doc["_id"] = str(doc["_id"])
        return doc
    except Exception as e:
        logger.error(f"Failed to get watchdog alert '{alert_id}': {e}")
        return None


async def list_recent_watchdog_alerts(
    workspace_id: Optional[str],
    *,
    since_hours: float = 3.0,
    limit: int = 20,
) -> list:
    """Alert watchdog terbaru dalam window N jam (read-only, utk chat project).
    Scoped workspace; None workspace → kosong (tanpa fallback global). Urut terbaru."""
    if not workspace_id:
        return []
    since = (datetime.now(timezone.utc) - timedelta(hours=max(0.1, since_hours))).isoformat()
    query: Dict[str, Any] = {"workspace_id": str(workspace_id), "sent_at": {"$gte": since}}
    try:
        cursor = (
            get_db()[WATCHDOG_ALERT_COLLECTION]
            .find(query)
            .sort("sent_at", -1)
            .limit(max(1, min(limit, 50)))
        )
        docs = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            docs.append(doc)
        return docs
    except Exception as e:
        logger.error(f"Failed to list recent watchdog alerts ws={workspace_id}: {e}")
        return []


async def update_watchdog_alert_message(alert_id: str, message: str) -> bool:
    """
    Patch pesan alert tersimpan (Fix #105) — nomor tiket baru diketahui SETELAH
    dokumen alert dibuat, jadi pesan di-update sebelum broadcast agar tombol
    "Cek Detail" menampilkan teks yang sama dgn broadcast.
    """
    try:
        db = get_db()
        result = await db[WATCHDOG_ALERT_COLLECTION].update_one(
            {"alert_id": alert_id}, {"$set": {"message": message}}
        )
        return result.matched_count > 0
    except Exception as e:
        logger.error(f"Failed to update watchdog alert message '{alert_id}': {e}")
        return False
