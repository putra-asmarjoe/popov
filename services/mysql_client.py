import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import aiomysql

logger = logging.getLogger(__name__)

_mysql_pools: Dict[str, aiomysql.Pool] = {}


async def get_mysql_pool(
    host: str = "localhost",
    port: int = 3306,
    user: str = "root",
    password: str = "",
    db: str = "popovagent_db",
) -> aiomysql.Pool:
    """Mendapatkan atau membuat connection pool MySQL secara asinkron."""
    key = f"{host}:{port}:{user}:{db}"
    if key not in _mysql_pools or _mysql_pools[key]._closed:
        logger.info(f"Initializing MySQL connection pool to {host}:{port}/{db}")
        pool = await aiomysql.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            db=db,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=aiomysql.DictCursor,
            minsize=1,
            maxsize=10,
        )
        _mysql_pools[key] = pool
    return _mysql_pools[key]


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Konversi objek row MySQL (termasuk datetime/date) ke bentuk JSON-serializable dict."""
    cleaned = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            cleaned[k] = v.isoformat()
        else:
            cleaned[k] = v
    return cleaned


async def query_mysql_table(
    host: str,
    port: int,
    user: str,
    password: str,
    db: str,
    table: str,
    query_filter: Optional[Dict[str, Any]] = None,
    limit: int = 20,
    raw: bool = False,
) -> List[Dict[str, Any]]:
    """
    Query tabel MySQL.
    raw=False (default): ambil log dengan level error/critical.
    raw=True: ambil semua record terbaru (untuk permintaan data mentah).
    """
    try:
        pool = await get_mysql_pool(host=host, port=port, user=user, password=password, db=db)
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if raw:
                    sql = f"SELECT * FROM `{table}` ORDER BY id DESC LIMIT %s"
                else:
                    # Query default: ambil log dengan level error/critical
                    sql = f"SELECT * FROM `{table}` WHERE LOWER(level) IN ('error', 'critical') ORDER BY id DESC LIMIT %s"

                try:
                    await cursor.execute(sql, (limit,))
                except Exception:
                    # Fallback tanpa WHERE level jika kolom level tidak ada atau nama kolom berbeda
                    sql_fallback = f"SELECT * FROM `{table}` ORDER BY 1 DESC LIMIT %s"
                    await cursor.execute(sql_fallback, (limit,))

                rows = await cursor.fetchall()
                results = [_serialize_row(row) for row in rows]
                logger.info(f"Queried MySQL table '{db}.{table}' → {len(results)} rows")
                return results
    except Exception as e:
        logger.error(f"MySQL query failed for table '{db}.{table}': {e}")
        return []


async def close_mysql_pools():
    """Tutup semua connection pool MySQL."""
    global _mysql_pools
    for key, pool in _mysql_pools.items():
        pool.close()
        await pool.wait_closed()
    _mysql_pools.clear()
