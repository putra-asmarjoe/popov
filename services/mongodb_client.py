from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import (
    ConnectionFailure,
    NetworkTimeout,
    AutoReconnect,
    ServerSelectionTimeoutError,
)
from config.settings import settings
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_mongo_clients: Dict[str, AsyncIOMotorClient] = {}


class DBConnectionError(Exception):
    """Koneksi ke MongoDB gagal (timeout, server tidak terjangkau, dll)."""

    def __init__(self, message: str, service_name: Optional[str] = None):
        self.service_name = service_name
        super().__init__(message)


# Tuple error yang menandakan masalah KONEKSI (bukan kesalahan query/skema).
CONNECTION_ERRORS = (ConnectionFailure, NetworkTimeout, AutoReconnect, ServerSelectionTimeoutError)


def _is_connection_error(exc: Exception) -> bool:
    """True bila exception merupakan kegagalan koneksi, bukan query/skema."""
    return isinstance(exc, CONNECTION_ERRORS)


def get_client_for_uri(uri: str) -> AsyncIOMotorClient:
    """Mendapatkan atau membuat AsyncIOMotorClient berdasarkan URI."""
    global _mongo_clients
    if uri not in _mongo_clients:
        logger.info(f"Initializing AsyncIOMotorClient for URI: {uri}")
        _mongo_clients[uri] = AsyncIOMotorClient(uri)
    return _mongo_clients[uri]


def get_client() -> AsyncIOMotorClient:
    return get_client_for_uri(settings.mongodb_uri)


def get_db(db_name: Optional[str] = None, uri: Optional[str] = None):
    target_uri = uri or settings.mongodb_uri
    target_db = db_name or settings.mongodb_db
    return get_client_for_uri(target_uri)[target_db]


async def query_collection(
    collection_name: str,
    query: dict,
    limit: int = 20,
    uri: Optional[str] = None,
    db_name: Optional[str] = None,
    sort_field: Optional[str] = "timestamp",
    service_name: Optional[str] = None,
) -> list:
    """Query a MongoDB collection and return documents as plain dicts.

    - Kegagalan KONEKSI → raise DBConnectionError (jangan disembunyikan jadi []).
    - Kesalahan non-koneksi (query/skema) → log + return [].
    """
    try:
        db = get_db(db_name=db_name, uri=uri)
        collection = db[collection_name]
        cursor = collection.find(query).sort(sort_field, -1).limit(limit)
        docs = []
        async for doc in cursor:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])   # serialize ObjectId
            docs.append(doc)
        logger.info(f"Queried MongoDB '{db.name}.{collection_name}' → {len(docs)} docs")
        return docs
    except DBConnectionError:
        raise
    except Exception as e:
        if _is_connection_error(e):
            raise DBConnectionError(
                f"Gagal koneksi ke MongoDB '{collection_name}': {e}",
                service_name=service_name,
            ) from e
        logger.error(f"MongoDB query failed for '{collection_name}': {e}")
        return []


async def close():
    global _mongo_clients
    for uri, client in _mongo_clients.items():
        client.close()
    _mongo_clients.clear()

