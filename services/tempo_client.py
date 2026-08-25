import logging
from typing import Optional, List, Dict, Any
import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


def _get_timeout() -> float:
    return float(settings.observability_timeout_ms) / 1000.0


def _effective_url(override: Optional[str]) -> Optional[str]:
    """URL efektif Tempo per-stack (Fase D): HANYA override observ_config (DB).
    None/kosong → disabled (tanpa fallback env)."""
    url = (override or "").strip()
    return url.rstrip("/") if url else None


async def get_trace(trace_id: str, tempo_url_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Query detail trace dari Grafana Tempo berdasarkan trace_id (GET /api/traces/{trace_id}).
    tempo_url_override: URL stack milik workspace/project (observ_config) — None = .env.
    """
    base = _effective_url(tempo_url_override)
    if not base or not trace_id:
        return None

    url = f"{base}/api/traces/{trace_id}"

    try:
        async with httpx.AsyncClient(timeout=_get_timeout()) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                logger.info(f"Trace ID '{trace_id}' not found in Tempo.")
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Tempo get_trace failed for trace_id='{trace_id}': {e}")
        return None


async def search_traces(service_name: str, limit: int = 5, tempo_url_override: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search traces di Tempo berdasarkan service_name (GET /api/search).
    tempo_url_override: URL stack per-project (Fase D) — None = .env fallback.
    """
    base = _effective_url(tempo_url_override)
    if not base or not service_name:
        return []

    url = f"{base}/api/search"
    params = {"tags": f'service.name="{service_name}"', "limit": limit}

    try:
        async with httpx.AsyncClient(timeout=_get_timeout()) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("traces", [])
    except Exception as e:
        logger.error(f"Tempo search_traces failed for service='{service_name}': {e}")
        return []