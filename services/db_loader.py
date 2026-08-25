import logging
from typing import List, Dict, Any, Optional
from config.settings import settings
from services.mongodb_client import query_collection, DBConnectionError
from services.mysql_client import query_mysql_table
from services.log_query import (
    resolve_error_query,
    resolve_sort_field,
    apply_time_window_to_query,
    detect_schema,
)

logger = logging.getLogger(__name__)


async def resolve_db_config(
    service_name: str,
    workspace_id: Optional[str] = None,
) -> tuple[Optional[Dict[str, Any]], str]:
    """
    Fix #43+#45: resolusi db_config bertingkat, dipakai db_loader & health_checker.
    Chain:
      1. workspace_service_registry[workspace_id]          [Fix #41]
      2. registry-any (Telegram tanpa konteks ws)          [Fix #43]
      3. library dbConfig (service_store)                  [Fix #38]
    (global JSON service_db_configs.json DIHAPUS dari chain — file `{}`, legacy)
    Return (config|None, source). None = tidak ada di semua lapis.
    """
    # Lapis 1 — registry workspace (varian dash/underscore, Fix #48b)
    if workspace_id:
        try:
            from services.workspace_service_registry import get_by_service
            sid = service_name.strip().lower()
            for v in {sid, sid.replace("-", "_"), sid.replace("_", "-")}:
                reg = await get_by_service(workspace_id, v)
                if reg and reg.get("db_config"):
                    break
            if reg and reg.get("db_config"):
                rc = reg["db_config"]
                return {
                    "type": rc.get("type", "mongodb"),
                    "uri": rc.get("uri"),
                    "db": rc.get("db"),
                    **({"collection": rc.get("collection")} if rc.get("collection") else {}),
                }, "registry"
        except Exception as e:
            logger.warning(f"[{service_name}] registry lookup failed: {e}")

    # Lapis 2b — tanpa konteks ws (Telegram): cari service_id di registry workspace manapun
    if not workspace_id:
        try:
            from services.workspace_service_registry import _collection
            base_sid = service_name.lower()
            variants = {base_sid, base_sid.replace("-", "_"), base_sid.replace("_", "-")}
            reg_any = await _collection().find_one(
                {"service_id": {"$in": list(variants)}, "enabled": {"$ne": False}, "db_config": {"$exists": True, "$ne": None}}
            )
            if reg_any and reg_any.get("db_config"):
                rc = reg_any["db_config"]
                return {
                    "type": rc.get("type", "mongodb"),
                    "uri": rc.get("uri"),
                    "db": rc.get("db"),
                    **({"collection": rc.get("collection")} if rc.get("collection") else {}),
                }, "registry-any"
        except Exception as e:
            logger.warning(f"[{service_name}] global registry lookup failed: {e}")

    # Lapis 3 — library dbConfig (varian dash/underscore, Fix #48b)
    try:
        from services.service_store import get_db_config_for_service
        for v in {service_name.lower(), service_name.lower().replace("-", "_"), service_name.lower().replace("_", "-")}:
            lib_cfg = await get_db_config_for_service(v)
            if lib_cfg:
                break
        if lib_cfg:
            return lib_cfg, "library"
    except Exception as e:
        logger.warning(f"[{service_name}] library dbConfig lookup failed: {e}")

    return None, "none"


async def fetch_logs_for_service(
    service_name: str,
    target_name: Optional[str] = None,
    query: Optional[dict] = None,
    limit: int = 20,
    raw: bool = False,
    collection_override: Optional[str] = None,
    sort_field: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Unified log fetcher: Mengambil log dari MongoDB atau MySQL berdasarkan konfigurasi per-service.
    raw=True → tanpa filter level error (data mentah, semua record terbaru).
    collection_override → nama collection/table eksplisit dari intent (diutamakan).

    Fix #41: resolusi db_config bertingkat:
      1. global JSON eksplisit (service_db_configs.json)
      2. workspace_service_registry[workspace_id][service_id]
      3. library dbConfig (service_store, Fix #38)
      4. default (.env + logs_<svc>)
    workspace_id dari state bila ada (chat web/tiket); Telegram → skip lapis 2.
    """
    # Fix #43: resolusi terpusat (JSON → registry(ws) → library) + gagal jelas
    # bila tidak ada lapis manapun — JANGAN diam-diam query DB default yang salah target.
    db_config, source = await resolve_db_config(service_name, workspace_id)
    if not db_config or not (db_config.get("uri") and db_config.get("db")):
        raise ValueError(
            f"Service '{service_name}' belum memiliki konfigurasi database. "
            f"Daftarkan service + koneksi log-nya di Workspace Settings → Service."
        )
    logger.info(f"[{service_name}] db_config resolved dari lapis '{source}'")

    db_type = str(db_config.get("type", "mongodb")).lower()

    logger.info(f"Fetching logs for service='{service_name}' using DB engine='{db_type}'")

    if db_type == "mysql":
        host = db_config.get("host") or settings.mysql_host
        port = int(db_config.get("port") or settings.mysql_port)
        user = db_config.get("user") or settings.mysql_user
        password = db_config.get("password") or settings.mysql_password
        db_name = db_config.get("db") or settings.mysql_db
        table = collection_override or db_config.get("table") or target_name or f"logs_{service_name}"

        return await query_mysql_table(
            host=host,
            port=port,
            user=user,
            password=password,
            db=db_name,
            table=table,
            query_filter=query,
            limit=limit,
            raw=raw,
        )
    else:
        # Default MongoDB
        uri = db_config.get("uri") or settings.mongodb_uri
        db_name = db_config.get("db") or settings.mongodb_db
        collection = collection_override or db_config.get("collection") or target_name or f"logs_{service_name}"

        if query is None and not raw:
            query = await resolve_error_query(service_name, db_config, collection)
        elif query is None:
            query = {}

        if sort_field is None:
            sort_field = await resolve_sort_field(db_config, collection)

        # Time-window: hanya ambil data maksimal LOG_TIME_WINDOW_HOURS jam terakhir,
        # supaya error lama (berhari-hari lalu) tidak dilaporkan sebagai insiden baru.
        time_window_hours = settings.log_time_window_hours
        ts_type = "unknown"
        if time_window_hours > 0:
            try:
                schema = await detect_schema(uri, db_name, collection)
                ts_type = schema.get("ts_value_type", "unknown")
            except DBConnectionError:
                raise
            except Exception as e:
                logger.error(f"[{service_name}] Gagal deteksi tipe timestamp: {e}")
            logger.info(
                f"[{service_name}] Menerapkan time-window {time_window_hours}h "
                f"pada '{collection}' (sort='{sort_field}', ts_type='{ts_type}')"
            )

        query = await apply_time_window_to_query(
            query,
            sort_field,
            time_window_hours,
            ts_type,
        )

        return await query_collection(
            collection_name=collection,
            query=query,
            limit=limit,
            uri=uri,
            db_name=db_name,
            sort_field=sort_field,
            service_name=service_name,
        )
