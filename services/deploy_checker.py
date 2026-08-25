"""
Deploy Checker via Loki — Fase 3 (read-only k8s events, namespace=default)

Query Loki: {job="integrations/kubernetes/events"} via /loki/api/v1/query_range
Verified: curl http://localhost:3100/ready → ready
          curl http://localhost:3100/loki/api/v1/labels → job, namespace, ...
          curl -G http://localhost:3100/loki/api/v1/query_range --data-urlencode 'query={job="integrations/kubernetes/events"}' → streams[].values[][1] JSON {kind, reason, name, msg, ...}

Degraded gracefully: Loki down / 404 / timeout → deploy_detected False.
"""
from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[-\s]+", "_", text)
    return text


async def check_deploy_via_loki(
    service: str,
    minutes: int = 60,
    loki_url_override: Optional[str] = None,
    namespace_override: Optional[str] = None,
    timeout_ms_override: Optional[int] = None,
) -> Tuple[bool, Optional[dict]]:
    """
    Cek apakah ada deploy/event k8s untuk service dalam `minutes` terakhir via Loki.
    Fix #45: URL/namespace/timeout per-stack (observ_config target) — HANYA dari DB;
    None = loki disabled (graceful). Return (deploy_detected, deploy_info).
    """
    loki_base = (loki_url_override or "").strip().rstrip("/")
    if not loki_base:
        return False, None
    if not service:
        return False, None

    loki_url = loki_base.rstrip("/")
    namespace = (namespace_override or settings.loki_namespace or "default").strip()
    timeout = (timeout_ms_override or settings.loki_timeout_ms or 2500) / 1000.0

    # Build Loki query_range params: start/end in nanoseconds
    end_ns = int(time.time() * 1e9)
    start_ns = int((time.time() - minutes * 60) * 1e9)
    query = '{job="integrations/kubernetes/events"}'

    url = f"{loki_url}/loki/api/v1/query_range"
    params = {
        "query": query,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": "100",
        "direction": "backward",
    }

    try:
        # quick ready check (optional, non-blocking)
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(f"{loki_url}/ready")
                if r.status_code != 200:
                    logger.warning(f"[DeployChecker] Loki not ready {r.status_code}")
                    return False, None
        except Exception as e:
            logger.warning(f"[DeployChecker] Loki ready check failed: {e}")
            return False, None

        async with httpx.AsyncClient(timeout=timeout + 2) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "success":
            logger.warning(f"[DeployChecker] Loki query status not success: {data}")
            return False, None

        results = data.get("data", {}).get("result", [])
        norm_service = _normalize(service)
        service_variants = {service.lower(), service.lower().replace("_", "-"), service.lower().replace("-", "_"), norm_service}

        for stream in results:
            stream_ns = stream.get("stream", {}).get("namespace", "")
            # Filter namespace (Loki stream label)
            if namespace and stream_ns and stream_ns != namespace:
                # allow monitoring namespace? but spec says default → only default
                continue
            values = stream.get("values", [])
            for ts_ns_str, line in values:
                try:
                    ts_ns = int(ts_ns_str)
                except Exception:
                    ts_ns = 0
                # skip if outside window (Loki already filtered, but double check)
                if ts_ns < start_ns:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    # line may be plain string
                    evt = {"msg": line, "name": line}

                kind = str(evt.get("kind") or evt.get("Kind") or "")
                reason = str(evt.get("reason") or evt.get("Reason") or "")
                name = str(evt.get("name") or evt.get("Name") or evt.get("msg") or "")
                msg = str(evt.get("msg") or "")

                # Only consider deployment-related kinds
                if kind not in ("Deployment", "ReplicaSet", "Pod", "StatefulSet", "DaemonSet"):
                    # Pod Scheduled is frequent but not deploy — allow only if name matches service closely
                    if kind == "Pod" and reason == "Scheduled":
                        pass  # allow pod scheduled as deploy signal if name contains service
                    elif kind not in ("Deployment", "ReplicaSet"):
                        continue

                # Reason filter for deploy
                deploy_reasons = {"SuccessfulCreate", "ScalingReplicaSet", "Scheduled", "Created", "Pulling", "Started", "SuccessfulDelete"}
                # For Pod Scheduled, we already pass; for others check reason
                if reason and reason not in deploy_reasons and kind != "Pod":
                    # allow any reason if kind is Deployment/ReplicaSet and name matches?
                    if kind in ("Deployment", "ReplicaSet") and reason not in deploy_reasons:
                        # still check name contains service
                        pass
                    else:
                        continue

                # Service name match (normalized)
                haystack = f"{name} {msg}".lower()
                # also check object name variants
                matched = any(v in haystack or v.replace("-", "_") in _normalize(haystack) or _normalize(haystack).find(_normalize(v)) != -1 for v in service_variants)
                # Also check if haystack contains normalized service
                if not matched:
                    # try direct substring after normalize
                    if norm_service not in _normalize(haystack):
                        continue

                # Found deploy event within window
                deployed_at = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).isoformat()
                deploy_info = {
                    "deployed_at": deployed_at,
                    "kind": kind,
                    "reason": reason,
                    "name": name,
                    "namespace": stream_ns or namespace,
                    "msg": msg[:200],
                    "source": "loki",
                }
                logger.info(f"[DeployChecker] deploy detected for {service} → {deploy_info}")
                return True, deploy_info

        return False, None

    except httpx.HTTPStatusError as e:
        logger.warning(f"[DeployChecker] Loki HTTP {e.response.status_code}: {e.response.text[:200]}")
        return False, None
    except Exception as e:
        logger.warning(f"[DeployChecker] failed for {service}: {e}")
        return False, None
