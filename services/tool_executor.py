"""CHAT3 Phase 4 — Tool call parser + executor (C2/C4/C5).

Parser: TOOL_CALL lines (case-insensitive keyword, C5). Param values use a
quote/comma-aware splitter: commas inside single/double quotes (PromQL,
labels) never split params; a bare `service`/`window`/… value with no `=`
binds to the next positional slot.

Executor: read-only tools auto-run (write tools NEVER run — caller gates
them into a confirmation chip, M2). Every attempt is wrapped in
asyncio.wait_for (sync executors included — C2) and budget.record_call()
runs on ALL attempts — success or failure (C2).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Tuple

from services.tool_adapters import AdapterCtx, run_adapter
from services.tool_registry import TOOL_TIMEOUT_S, get_tool

logger = logging.getLogger(__name__)

_TOOL_RE = re.compile(r"^\s*TOOL_CALL\s*:\s*(\S+)\s*(.*?)\s*$",
                      re.IGNORECASE | re.MULTILINE)

# Params where commas are DATA (PromQL/labels, free text) — unknown `k=v`
# tokens while filling one of these are continuations, not named params (C5).
_COMMA_DATA_PARAMS = frozenset({"promql", "query", "note", "message"})


def _split_top_level(raw: str) -> List[str]:
    """Split on commas OUTSIDE quotes AND outside {}[]() groups (C5).
    PromQL label matchers {a=\"1\",b=\"2\"} and function args ceil(m[5m])
    keep their commas — they are DATA, not param separators."""
    parts: List[str] = []
    buf: List[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for ch in raw:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\" and quote is not None:
            buf.append(ch)
            escaped = True
        elif ch in ("'", '"'):
            buf.append(ch)
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
        elif quote is not None:
            buf.append(ch)
        elif ch in ("{", "[", "("):
            depth += 1
            buf.append(ch)
        elif ch in ("}", "]", ")"):
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _partition_top_level(raw: str) -> tuple:
    """Split raw into (first_chunk, sep, rest) on the first top-level comma."""
    quote: str | None = None
    escaped = False
    depth = 0
    for i, ch in enumerate(raw):
        if escaped:
            escaped = False
        elif ch == "\\" and quote is not None:
            escaped = True
        elif ch in ("'", '"'):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
        elif quote is not None:
            pass
        elif ch in ("{", "[", "("):
            depth += 1
        elif ch in ("}", "]", ")"):
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return raw[:i].strip(), ",", raw[i + 1:]
    return raw.strip(), "", ""


def _looks_kv(token: str, slots: set) -> bool:
    """True if token is `knownkey = value` — `=` inside braces is data (C5).
    A token counts as k=v only when the `=` precedes any `{[(` group open
    AND the key (stripped, lowercased) is a declared slot."""
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(token):
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in ("{", "[", "("):
            depth += 1
        elif ch in ("}", "]", ")"):
            depth = max(0, depth - 1)
        elif ch == "=" and depth == 0:
            return token[:i].strip().lower() in slots
    return False


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _unescape(value: str) -> str:
    """Minimal unescape — only quote/backslash escapes (never unicode_escape:
    PromQL regex backslashes must survive verbatim)."""
    return (value.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\"))


def parse_tool_calls(reply: str) -> List[Dict[str, Any]]:
    """Parse TOOL_CALL lines → [{name, params}]. Unknown-safe: malformed
    lines and unknown tool names are SKIPPED (never raise, never invent).

    Namespace is injected ONLY for tools declaring needs_namespace (C5) —
    callers pass it in params already; here we never add it.
    """
    calls: List[Dict[str, Any]] = []
    if not reply:
        return calls
    for m in _TOOL_RE.finditer(reply):
        raw_name = (m.group(1) or "").strip()
        tool = get_tool(raw_name)  # case-insensitive (C5)
        if tool is None:
            logger.warning(f"[ToolExec] unknown tool skipped: {raw_name!r}")
            continue
        slots: List[str] = list(tool.get("params") or [])
        params: Dict[str, Any] = {}
        positional = 0
        # First positional slot is the "bare/value" slot; once a multi-chunk
        # comma-data param starts filling, later `x=y`-looking chunks whose key
        # is NOT a declared slot are continuations of it (C5: commas in PromQL
        # label matchers like {job="a",le="1"} must not corrupt params).
        comma_slot: str | None = None
        # Bare leading value containing braces/parens/commas is the whole
        # first-slot value (C5: bare PromQL `up{a="1",b="2"}` is ONE value).
        # Only k=v-mixed tails split on top-level commas afterwards.
        raw_params = (m.group(2) or "").strip()
        # Bare leading value = whole first-slot value. "Bare" test: chunk
        # before the first top-level comma has no `=` OUTSIDE braces — an `=`
        # inside {labels} does NOT make it a k=v token (C5). `key = value`
        # with spaces around `=` still counts as k=v.
        tokens = _split_top_level(raw_params)
        first = tokens[0] if tokens else ""
        if raw_params and slots and not _looks_kv(first, set(slots)):
            head, _, rest = _partition_top_level(raw_params)
            params[slots[0]] = _unescape(_strip_quotes(head))
            if slots[0] in _COMMA_DATA_PARAMS:
                comma_slot = slots[0]
            positional = 1
            tokens = _split_top_level(rest) if rest.strip() else []
        for token in tokens:
            if "=" in token:
                key, _, val = token.partition("=")
                key = key.strip().lower()
                if key in slots and key not in params:
                    params[key] = _unescape(_strip_quotes(val.strip()))
                    if key in _COMMA_DATA_PARAMS:
                        comma_slot = key
                    if slots and slots[positional:positional + 1] == [key]:
                        positional += 1
                elif comma_slot is not None and comma_slot in params:
                    # continuation of a comma-data param (C5)
                    params[comma_slot] = params[comma_slot] + "," + _unescape(token.strip())
                # unknown keys (outside comma-data) dropped — hallucinated
                # params never propagate.
            else:
                # bare value → next unfilled positional slot (C5)
                while positional < len(slots) and slots[positional] in params:
                    positional += 1
                if positional < len(slots):
                    params[slots[positional]] = _unescape(_strip_quotes(token))
                    if slots[positional] in _COMMA_DATA_PARAMS:
                        comma_slot = slots[positional]
                    positional += 1
        calls.append({"name": tool["name"], "params": params})
    return calls


class ToolBudget:
    """Per-turn + per-session call budget.

    record_call() MUST run on every attempt (C2) — success or failure —
    otherwise failures bypass the budget and retry loops can fan out.
    """

    def __init__(self, max_per_turn: int = 5, session_count: int = 0,
                 session_max: int = 25):
        self.max_per_turn = max_per_turn
        self.turn_used = 0
        self.session_count = session_count
        self.session_max = session_max

    def allow(self) -> bool:
        return (self.turn_used < self.max_per_turn
                and self.session_count < self.session_max)

    def record_call(self) -> None:
        self.turn_used += 1
        self.session_count += 1


async def _run_one(name: str, params: dict, ctx: AdapterCtx,
                   timeout_s: float) -> Tuple[bool, str]:
    res = run_adapter(name, params, ctx)
    if asyncio.iscoroutine(res):
        res = await asyncio.wait_for(res, timeout=timeout_s)  # C2: sync+async wrapped
    return res


async def execute_tool_calls(
    calls: List[Dict[str, Any]],
    ctx: AdapterCtx,
    budget: ToolBudget,
    *,
    timeout_s: float = TOOL_TIMEOUT_S,
) -> Tuple[List[Dict[str, Any]], ToolBudget]:
    """Execute parsed calls sequentially (deterministic order).

    - Write tools (read_only=False) are NEVER executed here → returned as
      {"name","params","needs_confirmation":True} entries (M2 chip path).
    - budget.record_call() runs on ALL attempts (C2).
    - Adapter failure → {"ok": False, ...} entry, execution CONTINUES
      (non-fatal: one tool failing never kills the turn).
    """
    results: List[Dict[str, Any]] = []
    for call in calls or []:
        name = call.get("name", "")
        params = dict(call.get("params") or {})
        tool = get_tool(name)
        if tool is None:
            continue
        if not tool.get("read_only", True):
            results.append({"name": name, "params": params,
                            "ok": False, "needs_confirmation": True,
                            "result": f"{name} needs confirmation before running"})
            continue
        if not budget.allow():
            results.append({"name": name, "params": params, "ok": False,
                            "result": "tool budget exhausted — remaining tools skipped"})
            break
        try:
            ok, text = await _run_one(name, params, ctx, timeout_s)
        except asyncio.TimeoutError:
            ok, text = False, f"{name} timed out after {timeout_s}s"
        except Exception as e:  # never let one tool kill the turn
            logger.warning(f"[ToolExec] {name} raised: {e}")
            ok, text = False, f"{name} failed: {e}"
        finally:
            budget.record_call()  # C2: ALL attempts count
        results.append({"name": name, "params": params, "ok": ok,
                        "result": text})
    return results, budget


def format_tool_results(results: List[Dict[str, Any]]) -> str:
    """Compact deterministic block for the reply-LLM context."""
    if not results:
        return ""
    lines = ["[TOOL RESULTS]"]
    for r in results:
        status = "ok" if r.get("ok") else "failed"
        if r.get("needs_confirmation"):
            status = "needs_confirmation"
        lines.append(f"- {r.get('name')} [{status}]: {(r.get('result') or '')[:600]}")
    return "\n".join(lines)
