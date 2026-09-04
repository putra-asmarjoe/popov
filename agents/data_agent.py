import difflib
import logging
from state.schema import AgentState
from services.db_loader import fetch_logs_for_service
from services.mongodb_client import get_db, DBConnectionError
from config.settings import settings
from agents.supervisor import extract_data_count, extract_collection_name

logger = logging.getLogger(__name__)


async def _resolve_collection(db_config: dict, explicit, fallback: str) -> str:
    """
    Pilih nama collection terbaik:
    explicit (fuzzy-match ke collection yg ada) > db_config.collection > fallback.
    Menghindari kegagalan akibat typo nama collection (mis. 'axiologs' → 'axioslogs').
    """
    if explicit:
        db_type = str(db_config.get("type", "mongodb")).lower()
        if db_type == "mongodb":
            uri = db_config.get("uri") or settings.mongodb_uri
            db_name = db_config.get("db") or settings.mongodb_db
            try:
                db = get_db(db_name=db_name, uri=uri)
                existing = await db.list_collection_names()
                if not existing:
                    return explicit
                if explicit in existing:
                    return explicit
                match = difflib.get_close_matches(explicit, existing, n=1, cutoff=0.6)
                if match:
                    logger.info(
                        f"DataAgent: collection '{explicit}' → fuzzy match '{match[0]}'"
                    )
                    return match[0]
                logger.warning(
                    f"DataAgent: collection '{explicit}' tidak ditemukan di db '{db_name}', "
                    f"fallback ke '{db_config.get('collection') or fallback}'"
                )
                return db_config.get("collection") or fallback
            except Exception as e:
                logger.error(f"DataAgent: gagal list collections utk '{explicit}': {e}")
                return explicit
        # MySQL: pakai nama table seadanya
        return explicit
    return db_config.get("collection") or fallback


_ERROR_LOOKUP_WORDS = (
    "error", "gagal", "bermasalah", "down", "timeout", "crash", "5xx", "500",
    "exception", "failed", "failure", "panic",
)


def _wants_errors(intent: str) -> bool:
    """True bila user minta data log yang ERROR saja (bukan semua records).
    "kapan terakhir error", "cek error di table", "tampilkan yang error"."""
    low = intent.lower()
    return any(w in low for w in _ERROR_LOOKUP_WORDS)


async def data_agent(state: AgentState) -> dict:
    """
    Ambil data mentah untuk permintaan seperti "berikan 1 data terakhir dari
    service X collection Y".
    Fix (CPRO-29): user minta "cek error / kapan terakhir error" → filter ERROR
    (schema-aware, resolve_error_query) bukan 5 records terakhir apapun. Query
    mentah tanpa window 6 jam (error lama yang diminta user tidak terpotong).
    """
    service_name = state.get("service_name", "")
    collection_name = state.get("collection_name", "")
    intent = state.get("intent", "")
    agents_visited = state.get("agents_visited", []) + ["data_agent"]

    if not service_name and not collection_name:
        return {
            "error": "service_name / collection_name tidak ditemukan di state",
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    limit = extract_data_count(intent)
    explicit_collection = extract_collection_name(intent) or collection_name
    # Fix #43: resolusi chain (JSON→registry→library), bukan settings langsung
    from services.db_loader import resolve_db_config
    db_config, _src = await resolve_db_config(service_name, state.get("workspace_id"))
    resolved_collection = await _resolve_collection(
        db_config or {}, explicit_collection, collection_name
    )

    # Filter error bila user minta data ERROR (schema-aware, tanpa window insiden).
    wants_error = _wants_errors(intent)
    query: dict = {}
    time_window_hours: float = 0.0  # query mentah = tanpa window 6 jam
    if wants_error:
        try:
            from services.log_query import resolve_error_query
            query = await resolve_error_query(
                service_name, db_config or {}, resolved_collection
            )
            logger.info(
                f"DataAgent filter error utk '{intent[:60]}' → query={query}"
            )
        except Exception as e:
            logger.warning(f"DataAgent resolve_error_query gagal (query tetap kosong): {e}")
            query = {}

    logger.info(
        f"DataAgent fetching last {limit} records from '{resolved_collection}' "
        f"(service='{service_name}', filter_error={wants_error})"
    )

    try:
        docs = await fetch_logs_for_service(
            service_name=service_name,
            target_name=collection_name,
            query=query,
            limit=limit,
            raw=True,
            collection_override=resolved_collection,
            workspace_id=state.get("workspace_id"),
            time_window_hours=time_window_hours,
        )
    except DBConnectionError as e:
        logger.error(f"DataAgent connection failed: {e}")
        return {
            "raw_documents": [],
            "data_mode": True,
            "data_limit": limit,
            "collection_name": resolved_collection,
            "query_used": {},
            "error": (
                f"Gagal koneksi ke database untuk service '{service_name}': {e}. "
                f"Data tidak dapat diambil saat ini."
            ),
            "next_agent": "end",
            "agents_visited": agents_visited,
        }
    except Exception as e:
        logger.error(f"DataAgent query failed: {e}")
        return {
            "error": f"Database query error: {str(e)}",
            "next_agent": "end",
            "agents_visited": agents_visited,
        }

    logger.info(f"DataAgent fetched {len(docs)} records")
    return {
        "raw_documents": docs,
        "data_mode": True,
        "data_limit": limit,
        "collection_name": resolved_collection,
        "query_used": {},
        "next_agent": "response_agent",
        "agents_visited": agents_visited,
    }