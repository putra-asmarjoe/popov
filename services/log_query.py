import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from config.settings import settings
from services.mongodb_client import get_db, DBConnectionError, _is_connection_error

logger = logging.getLogger(__name__)

# Fallback bila skema collection tidak dikenal & tidak ada error_filter eksplisit.
DEFAULT_QUERY = {"level": {"$in": ["error", "critical", "ERROR", "CRITICAL"]}}

# Field error yang dicoba dideteksi, urut prioritas.
_ERROR_FIELD_PRIORITY = ("level", "error", "severity", "status")

# Field timestamp untuk sorting "terbaru", urut prioritas (kebanyakan collection
# tidak punya 'timestamp', cth. axioslogs pakai createdAt/requestTimestamp).
_SORT_FIELD_PRIORITY = ("createdAt", "requestTimestamp", "timestamp", "created_at", "ts")

# Cache skema per (uri, db, collection) → hindari probe berulang per request.
_schema_cache: Dict[str, Dict[str, str]] = {}


def _detect_ts_value_type(value) -> str:
    """
    Deteksi format nilai timestamp dari satu sampel dokumen.
    Return 'ms' (epoch miliseconds), 's' (epoch seconds), 'iso' (string ISO8601),
    'date' (BSON Date / datetime object), atau 'unknown'.
    """
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "unknown"
    if isinstance(value, datetime):
        return "date"
    if isinstance(value, (int, float)):
        return "ms" if abs(value) > 1_000_000_000_000 else "s"
    if isinstance(value, str):
        s = value.strip()
        if "T" in s or s.startswith("20") or s.startswith("19"):
            return "iso"
        if s.isdigit():
            return "ms" if len(s) >= 13 else "s"
    return "unknown"


def _cache_key(uri: str, db_name: str, collection: str) -> str:
    return f"{uri}|{db_name}|{collection}"


async def detect_schema(uri: str, db_name: str, collection: str) -> Dict[str, str]:
    """
    Deteksi field yang tersedia di sebuah collection (dengan cache).
    Mengambil satu dokumen sampel untuk membaca kunci-kuncinya.

    Returns dict berisi:
      - error_field:  field berpotensi error yang ditemukan, atau ""
      - sort_field:   field timestamp untuk sorting "terbaru", atau ""
      - ts_value_type: tipe nilai sort_field ('ms'/'s'/'iso'/'unknown') utk filter waktu
    """
    key = _cache_key(uri, db_name, collection)
    if key in _schema_cache:
        return _schema_cache[key]

    schema = {"error_field": "", "sort_field": "", "ts_value_type": "unknown"}
    try:
        db = get_db(db_name=db_name, uri=uri)
        coll = db[collection]
        sample = await coll.find_one({}, {"_id": 0})
        if sample and isinstance(sample, dict):
            keys = set(sample.keys())
            for field in _ERROR_FIELD_PRIORITY:
                if field in keys:
                    schema["error_field"] = field
                    break
            for field in _SORT_FIELD_PRIORITY:
                if field in keys:
                    schema["sort_field"] = field
                    schema["ts_value_type"] = _detect_ts_value_type(sample.get(field))
                    break
            logger.info(
                f"Schema detect '{db_name}.{collection}': "
                f"error_field='{schema['error_field'] or '-'}', "
                f"sort_field='{schema['sort_field'] or '-'}' "
                f"(ts_type='{schema['ts_value_type']}')"
            )
        else:
            logger.warning(f"Schema detect '{db_name}.{collection}': collection kosong/tidak ditemukan")
    except DBConnectionError:
        raise
    except Exception as e:
        if _is_connection_error(e):
            raise DBConnectionError(
                f"Gagal koneksi saat mendeteksi skema '{collection}': {e}",
            ) from e
        logger.error(f"Schema detect gagal untuk '{collection}': {e}")

    _schema_cache[key] = schema
    return schema


def build_error_query(
    error_field: str,
    default_field: str = "level",
) -> dict:
    """Bangun query filter error berdasarkan field yang tersedia di collection."""
    if error_field in ("error", "exception", "message"):
        # Kolom bebas teks error: filter yang tidak kosong / bukan None.
        return {error_field: {"$exists": True, "$ne": None, "$ne": ""}}
    if error_field == "severity":
        return {"severity": {"$in": ["error", "critical", "ERROR", "CRITICAL"]}}
    if error_field == "status":
        return {"status": {"$in": ["error", "critical", "ERROR", "CRITICAL"]}}
    # level (atau fallback generic)
    return {default_field: {"$in": ["error", "critical", "ERROR", "CRITICAL"]}}


async def resolve_error_query(
    service_name: str,
    db_config: dict,
    collection: str,
    default_query: Optional[dict] = None,
) -> dict:
    """
    Tentukan query filter error dengan prioritas:
      1. error_filter eksplisit dari config per-service (db_config/registry/library).
      2. Auto-detect skema collection (field 'level'/'error'/'severity'/'status').
      3. DEFAULT_QUERY fallback.
    Fix #49: db_config boleh None (service tanpa DB config) — perlakukan sebagai kosong,
    bukan crash (None.get → AttributeError).
    """
    db_config = db_config or {}
    explicit = db_config.get("error_filter")
    if explicit and isinstance(explicit, dict):
        logger.info(f"[{service_name}] Pakai error_filter eksplisit: {explicit}")
        return explicit

    db_type = str(db_config.get("type", "mongodb")).lower()
    if db_type == "mongodb":
        uri = db_config.get("uri") or settings.mongodb_uri
        db_name = db_config.get("db") or settings.mongodb_db
        try:
            schema = await detect_schema(uri, db_name, collection)
        except DBConnectionError:
            raise
        if schema.get("error_field"):
            query = build_error_query(schema["error_field"])
            logger.info(f"[{service_name}] Auto-detect error_field='{schema['error_field']}' → {query}")
            return query

    fallback = default_query or DEFAULT_QUERY
    logger.warning(
        f"[{service_name}] Skema collection '{collection}' tidak dikenal, "
        f"fallback ke DEFAULT_QUERY"
    )
    return dict(fallback)


async def resolve_sort_field(
    db_config: dict,
    collection: str,
) -> str:
    """Tentukan field sorting 'terbaru' via auto-detect skema (default 'timestamp').
    Fix #49: db_config boleh None — perlakukan sebagai kosong."""
    db_config = db_config or {}
    db_type = str(db_config.get("type", "mongodb")).lower()
    if db_type == "mongodb":
        uri = db_config.get("uri") or settings.mongodb_uri
        db_name = db_config.get("db") or settings.mongodb_db
        try:
            schema = await detect_schema(uri, db_name, collection)
        except DBConnectionError:
            raise
        if schema.get("sort_field"):
            return schema["sort_field"]
    return "timestamp"


def build_time_filter(sort_field: str, hours: int, ts_value_type: str = "unknown") -> dict:
    """
    Bangun filter waktu untuk query: hanya dokumen dengan sort_field dalam N jam terakhir.
    Format nilai dibandingkan disesuaikan dengan tipe timestamp collection.
    hours <= 0 → filter kosong (semua data).
    """
    if hours <= 0 or not sort_field:
        return {}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    if ts_value_type == "ms":
        cutoff_val = int(cutoff.timestamp() * 1000)
    elif ts_value_type == "s":
        cutoff_val = int(cutoff.timestamp())
    elif ts_value_type == "date":
        cutoff_val = cutoff  # BSON Date — pakai datetime object langsung
    else:
        # iso (atau unknown) → string ISO8601
        cutoff_val = cutoff.isoformat()

    return {sort_field: {"$gte": cutoff_val}}


async def apply_time_window_to_query(
    query: dict,
    sort_field: Optional[str],
    hours: int,
    ts_value_type: str = "unknown",
) -> dict:
    """
    Gabungkan query dengan filter waktu (hanya data N jam terakhir).
    Tidak memodifikasi query asli; return query baru jika perlu.
    """
    if hours <= 0 or not sort_field:
        return dict(query)
    time_filter = build_time_filter(sort_field, hours, ts_value_type)
    if not time_filter:
        return dict(query)
    merged = dict(query or {})
    merged.update(time_filter)
    return merged
