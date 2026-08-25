import time
import asyncio
import copy
import re
import logging
from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
import aiomysql

from config.settings import settings

logger = logging.getLogger(__name__)

_URI_CREDS_RE = re.compile(r"://[^/@]+@")
_SENSITIVE_KEYS = ("uri", "password", "passwd", "secret", "token", "apikey")


def _host_from_uri(uri: str) -> str:
    """Ambil host:port dari URI tanpa kredensial. 'mongodb://u:p@host:27017' → 'host:27017'."""
    if not uri:
        return ""
    stripped = _URI_CREDS_RE.sub("://", uri)  # buang userinfo (user:password@)
    m = re.search(r"://([^/]+)", stripped)
    return m.group(1) if m else stripped


def sanitize_health_result(result):
    """
    Salin hasil health check lalu redaksi kredensial agar aman utk ditampilkan ke user / di-log.
    - uri (connection string, bisa berisi user:password) → diganti field 'host' (tanpa kredensial)
    - key sensitif lain (password/token/secret) dihapus
    Rekursif utk menangani check_all_health (summary + services).
    """
    if isinstance(result, dict):
        out = copy.deepcopy(result)
        if "uri" in out:
            out["host"] = _host_from_uri(out.pop("uri"))
        for key in list(out.keys()):
            if key.lower() in _SENSITIVE_KEYS or any(s in key.lower() for s in _SENSITIVE_KEYS):
                out.pop(key, None)
            elif isinstance(out[key], (dict, list)):
                out[key] = sanitize_health_result(out[key])
        return out
    if isinstance(result, list):
        return [sanitize_health_result(item) for item in result]
    return copy.deepcopy(result)


async def check_mongodb_health(
    uri: Optional[str] = None,
    db_name: Optional[str] = None,
    timeout_seconds: float = 3.0,
) -> Dict[str, Any]:
    """Menguji koneksi fisik & latency ke MongoDB server."""
    target_uri = uri or settings.mongodb_uri
    target_db = db_name or settings.mongodb_db
    timeout_ms = int(timeout_seconds * 1000)

    start_time = time.perf_counter()
    client = None
    try:
        client = AsyncIOMotorClient(target_uri, serverSelectionTimeoutMS=timeout_ms)
        # Eksekusi command ping
        await client.admin.command("ping")
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        client.close()
        return {
            "status": "connected",
            "engine": "mongodb",
            "uri": target_uri,
            "db": target_db,
            "latency_ms": round(elapsed_ms, 2),
            "error": None,
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if client:
            client.close()
        logger.warning(f"MongoDB health check failed for {target_uri}: {e}")
        return {
            "status": "disconnected",
            "engine": "mongodb",
            "uri": target_uri,
            "db": target_db,
            "latency_ms": round(elapsed_ms, 2),
            "error": str(e),
        }


async def check_mysql_health(
    host: Optional[str] = None,
    port: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    db: Optional[str] = None,
    timeout_seconds: float = 3.0,
) -> Dict[str, Any]:
    """Menguji koneksi fisik & latency ke MySQL server."""
    target_host = host or settings.mysql_host
    target_port = port or settings.mysql_port
    target_user = user or settings.mysql_user
    target_pwd = password or settings.mysql_password
    target_db = db or settings.mysql_db

    start_time = time.perf_counter()
    try:
        conn = await asyncio.wait_for(
            aiomysql.connect(
                host=target_host,
                port=target_port,
                user=target_user,
                password=target_pwd,
                db=target_db,
                connect_timeout=timeout_seconds,
            ),
            timeout=timeout_seconds + 1.0,
        )
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT 1")
        conn.close()
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return {
            "status": "connected",
            "engine": "mysql",
            "host": f"{target_host}:{target_port}",
            "db": target_db,
            "latency_ms": round(elapsed_ms, 2),
            "error": None,
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(f"MySQL health check failed for {target_host}:{target_port}/{target_db}: {e}")
        return {
            "status": "disconnected",
            "engine": "mysql",
            "host": f"{target_host}:{target_port}",
            "db": target_db,
            "latency_ms": round(elapsed_ms, 2),
            "error": str(e),
        }


async def check_service_health(service_name: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Menguji kesehatan database khusus milik service tertentu.
    Fix #43: resolusi via chain (JSON → registry(ws) → library) — bukan settings langsung.
    Tanpa konfigurasi → status error jelas (bukan diam-diam ping DB default)."""
    from services.db_loader import resolve_db_config

    db_config, source = await resolve_db_config(service_name, workspace_id)
    if not db_config or not (db_config.get("uri") and db_config.get("db")):
        return {
            "status": "error",
            "error": (
                f"Service '{service_name}' belum memiliki konfigurasi database. "
                f"Daftarkan service + koneksi log-nya di Workspace Settings → Service."
            ),
            "service_name": service_name,
        }
    logger.info(f"[HealthChecker] {service_name} db_config dari lapis '{source}'")

    engine = str(db_config.get("type", "mongodb")).lower()

    if engine == "mysql":
        res = await check_mysql_health(
            host=db_config.get("host"),
            port=db_config.get("port"),
            user=db_config.get("user"),
            password=db_config.get("password"),
            db=db_config.get("db"),
        )
    else:
        res = await check_mongodb_health(
            uri=db_config.get("uri"),
            db_name=db_config.get("db"),
        )

    res["service_name"] = service_name
    return res


async def check_all_health() -> Dict[str, Any]:
    """Menguji seluruh koneksi DB (MongoDB default, MySQL default, dan per-service DBs)."""
    mongo_default = await check_mongodb_health()
    mysql_default = await check_mysql_health()

    service_results = {}
    # Fix #45: service list MURNI dari DB (list_all_services), bukan JSON legacy.
    from services.doc_loader import list_all_services
    svc_map = await list_all_services()
    for svc in svc_map:
        service_results[svc] = await check_service_health(svc)

    return {
        "summary": {
            "mongodb_default": mongo_default,
            "mysql_default": mysql_default,
        },
        "services": service_results,
    }
