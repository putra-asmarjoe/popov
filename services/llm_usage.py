"""
LLM Usage Tracker — mencatat pemakaian token per panggilan LLM.

Tidak ada pencatatan token sebelumnya; ini menambahkan lapisan pencatatan
terpusat. Mengidentifikasi agent dari modul pemanggil (inspect stack), lalu
menyimpan ke collection `llm_usage` (popovagent_db) + log app.log.

Non-blocking & non-fatal: kegagalan pencatatan TIDAK boleh mengganggu pipeline.
"""
from __future__ import annotations

import inspect
import logging
import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

COLLECTION = "llm_usage"


def _extract_usage(resp: Any) -> Dict[str, Any]:
    """Ambil {prompt_tokens, completion_tokens, total_tokens} dari response LLM
    (langchain AIMessage.usage_metadata atau response_metadata.token_usage)."""
    um = getattr(resp, "usage_metadata", None)
    if isinstance(um, dict):
        return {
            "prompt_tokens": um.get("input_tokens") or um.get("prompt_tokens"),
            "completion_tokens": um.get("output_tokens") or um.get("completion_tokens"),
            "total_tokens": um.get("total_tokens"),
        }
    rm = getattr(resp, "response_metadata", None) or {}
    tu = rm.get("token_usage") or rm.get("usage")
    if isinstance(tu, dict):
        return {
            "prompt_tokens": tu.get("prompt_tokens"),
            "completion_tokens": tu.get("completion_tokens"),
            "total_tokens": tu.get("total_tokens"),
        }
    return {}


# Frame yang bukan "agent" (framework/runtime/langchain) — dilewati saat deteksi modul pemanggil.
_SKIP_MODULES = (
    "services.llm_usage", "services.llm_factory", "uvicorn", "starlette", "fastapi",
    "asyncio", "langchain", "langchain_openai", "openai", "pydantic", "anyio",
    "concurrent", "multiprocessing", "threading",
)


def _caller_agent() -> str:
    """Nama modul pemanggil (mis. 'agents.correlation_agent').

    Prefer frame modul project (agents./services./api.), skip framework/runtime.
    """
    project_hit = None
    try:
        frame = inspect.currentframe()
        while frame is not None:
            mod = frame.f_globals.get("__name__", "")
            if not mod:
                frame = frame.f_back
                continue
            if mod.startswith(("agents.", "services.", "api.")):
                if not mod.startswith(("services.llm_usage", "services.llm_factory")):
                    project_hit = mod
                    break
            frame = frame.f_back
        if project_hit:
            return project_hit
    except Exception:
        pass
    # fallback: frame pertama di luar denylist
    try:
        frame = inspect.currentframe()
        while frame is not None:
            mod = frame.f_globals.get("__name__", "")
            if mod and not mod.startswith(_SKIP_MODULES):
                return mod
            frame = frame.f_back
    except Exception:
        pass
    return "unknown"


async def record_usage(
    provider: str,
    model: str,
    resp: Any,
    latency_ms: int,
    agent: Optional[str] = None,
    status: str = "ok",
    error: Optional[str] = None,
) -> None:
    """Simpan 1 baris usage. Non-fatal. status: ok | error | timeout."""
    usage = _extract_usage(resp) if status == "ok" else {}
    doc = {
        "provider": provider or "",
        "model": model or "",
        "agent": agent or _caller_agent(),
        "status": status,
        "error": error,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "latency_ms": latency_ms,
        "timestamp": datetime.now(timezone.utc),
    }
    try:
        from services.mongodb_client import get_db

        await get_db()[COLLECTION].insert_one(doc)
    except Exception as e:
        logger.warning(f"[LLMUsage] insert failed ({doc.get('agent')}): {e}")
    logger.info(
        f"[LLMUsage] agent={doc['agent']} model={model} status={status} "
        f"prompt={doc['prompt_tokens']} completion={doc['completion_tokens']} "
        f"total={doc['total_tokens']} latency={latency_ms}ms "
        f"error={error or '-'}"
    )


async def ensure_llm_usage_indexes() -> None:
    db = None
    try:
        from services.mongodb_client import get_db
        db = get_db()
        coll = db[COLLECTION]
        await coll.create_index([("timestamp", -1)])
        await coll.create_index([("agent", 1), ("timestamp", -1)])
        await coll.create_index([("model", 1), ("timestamp", -1)])
    except Exception as e:
        logger.warning(f"[LLMUsage] ensure indexes failed: {e}")


class TrackingLLM:
    """Proxy ChatOpenAI yang mencatat usage tiap ainvoke, delegasi sisanya.

    Mengapa proxy: semua titik LLM di project via get_chat_llm; membungkus di
    factory = 1 tempat perubahan, otomatis melacak semua agent tanpa edit per-call.
    """

    def __init__(self, llm: Any, provider: str, model: str):
        self._llm = llm
        self._provider = provider
        self._model = model

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        agent = _caller_agent()
        try:
            resp = await self._llm.ainvoke(*args, **kwargs)
        except asyncio.TimeoutError:
            latency = int((time.monotonic() - start) * 1000)
            try:
                await record_usage(self._provider, self._model, None, latency, agent,
                                   status="timeout", error="LLM timeout")
            except Exception as e:
                logger.warning(f"[LLMUsage] record timeout failed: {e}")
            raise
        except asyncio.CancelledError:
            # wait_for membatalkan coroutine ini (timeout eksternal) → lempar
            # CancelledError, bukan TimeoutError di dalam sini. Rekam via
            # create_task (fire-and-forget) karena await setelah cancel tidak aman.
            latency = int((time.monotonic() - start) * 1000)
            try:
                asyncio.create_task(
                    record_usage(self._provider, self._model, None, latency, agent,
                                 status="timeout", error="LLM timeout (cancelled)")
                )
            except Exception as e:
                logger.warning(f"[LLMUsage] record cancelled failed: {e}")
            raise
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            try:
                await record_usage(self._provider, self._model, None, latency, agent,
                                   status="error", error=str(e)[:200])
            except Exception as e2:
                logger.warning(f"[LLMUsage] record error failed: {e2}")
            raise
        latency = int((time.monotonic() - start) * 1000)
        try:
            await record_usage(self._provider, self._model, resp, latency, agent, status="ok")
        except Exception as e:
            logger.warning(f"[LLMUsage] record failed: {e}")
        return resp


async def slowest_failure_since(since_iso: str) -> Optional[Dict[str, Any]]:
    """Diagnosis timeout pipeline (Fix #116): LLM call berstatus timeout/error
    TERLAMBAH sejak `since_iso`. Return {agent, model, latency_ms, error} | None.
    Dipakai chat.py agar pesan timeout menyebut penyebab nyata (LLM lambat),
    bukan fallback generik "coba pertanyaan lebih spesifik"."""
    try:
        from datetime import datetime, timezone
        # timestamp di collection = BSON datetime — konversi dari ISO string
        since_dt = (
            datetime.fromisoformat(since_iso)
            if isinstance(since_iso, str)
            else since_iso
        )
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
        from services.mongodb_client import get_db
        doc = await get_db()[COLLECTION].find_one(
            {
                "timestamp": {"$gte": since_dt},
                "status": {"$in": ["timeout", "error"]},
            },
            sort=[("latency_ms", -1)],
        )
        if not doc:
            return None
        return {
            "agent": str(doc.get("agent") or "").replace("agents.", "").replace("_agent", ""),
            "model": doc.get("model"),
            "latency_ms": doc.get("latency_ms"),
            "error": str(doc.get("error") or "")[:120],
        }
    except Exception as e:
        logger.warning(f"[LLMUsage] slowest_failure_since failed: {e}")
        return None
