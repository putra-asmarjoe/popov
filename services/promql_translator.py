"""
STACK2 F1-T6: Natural language to PromQL translator.

Translates human descriptions to PromQL using pattern matching + LLM fallback.
Deterministic first (zero-cost), LLM only when pattern fails.

Architect review (STACK2-F1-REVIEW): translator is called by supervisor (spec K9).
All LLM paths are async (no run_until_complete). Server-side validator applied
before returning to caller.

Fix #255.1: Builders use .format() instead of f-string to avoid {{window}} bug.
"""

from typing import Optional, Tuple
from services.prompt_loader import render as render_prompt

import re
import logging

logger = logging.getLogger(__name__)

# ── Security: PromQL Validator (O5) ──────────────────────────────────────────

# Blocked patterns (cluster-level / system-level queries)
_BLOCKED_PROMQL_PATTERNS = [
    r"\balertmanager\b",
    r"\bdown\b.*\balertmanager\b",
]


def validate_promql(promql: str, window: str) -> Tuple[bool, str]:
    """
    Server-side PromQL validation.
    Returns (is_valid, reason_if_invalid).

    Validates:
    - Non-empty query
    - Window in allowed set (clamp if outside)
    - No blocked patterns (cluster-level, system-level)
    """
    if not promql or not promql.strip():
        return False, "empty PromQL"

    # Check for blocked patterns
    for pat in _BLOCKED_PROMQL_PATTERNS:
        if re.search(pat, promql, re.IGNORECASE):
            return False, f"blocked pattern detected: {pat}"

    return True, ""


# ── Window Clamping ───────────────────────────────────────────────────────────

# Allowed window values for PromQL range selector
_ALLOWED_WINDOWS = {"30m", "1h", "6h", "24h", "7d"}

# Nearest-match clamp map for windows outside the allowed set
_WINDOW_CLAMP = {
    "5m": "30m", "10m": "30m", "15m": "30m", "20m": "30m", "25m": "30m", "30m": "30m",
    "45m": "1h", "1h": "1h",
    "2h": "6h", "3h": "6h", "4h": "6h", "6h": "6h",
    "8h": "24h", "12h": "24h", "24h": "24h",
    "2d": "7d", "3d": "7d", "7d": "7d", "14d": "7d", "30d": "7d",
}


def clamp_window(window: str) -> str:
    """
    Clamp a window string to the nearest allowed value.
    '45m' → '1h', '2d' → '7d', '5w' → '7d', '1h' → '1h'.
    Returns clamped window string.
    """
    if window in _ALLOWED_WINDOWS:
        return window
    if window in _WINDOW_CLAMP:
        return _WINDOW_CLAMP[window]
    # Unknown format: try to parse and clamp by magnitude
    m = re.match(r"(\d+)([mhdw])", window)
    if m:
        num, unit = int(m.group(1)), m.group(2)
        if unit == "m":
            return "30m" if num <= 45 else "1h"
        if unit == "h":
            return "6h" if num <= 6 else "24h"
        if unit == "d":
            return "7d"
        if unit == "w":
            return "7d"
    return "1h"  # ultimate fallback


# ── Window Parsing from Natural Language ──────────────────────────────────────

_WINDOW_PATTERNS = [
    # EN patterns
    (r"(\d+)\s*minutes?\b", "m"),
    (r"(\d+)\s*hours?\b", "h"),
    (r"(\d+)\s*days?\b", "d"),
    (r"(\d+)\s*weeks?\b", "w"),
    # ID patterns
    (r"(\d+)\s*menit\b", "m"),
    (r"(\d+)\s*jam\b", "h"),
    (r"(\d+)\s*hari\b", "d"),
    (r"(\d+)\s*minggu\b", "w"),
    # Shorthand
    (r"(\d+)m\b", "m"),
    (r"(\d+)h\b", "h"),
    (r"(\d+)d\b", "d"),
    (r"(\d+)w\b", "w"),
]


def parse_window_from_text(text: str, default: str = "1h") -> str:
    """
    Extract time window from natural language text.
    Examples: "6 jam terakhir" → "6h", "24 jam" → "24h", "seminggu" → "7d"
    Always returns a clamped, allowed window value.
    """
    text_lower = text.lower()

    # Special cases
    if "seminggu" in text_lower or "se minggu" in text_lower or "weekly" in text_lower:
        return "7d"
    if "sehari" in text_lower or "se hari" in text_lower or "daily" in text_lower:
        return "24h"

    for pattern, suffix in _WINDOW_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            num = int(m.group(1))
            raw_window = f"{num}{suffix}"
            return clamp_window(raw_window)

    return default


# ── Deterministic Pattern Matching ────────────────────────────────────────────
# CRITICAL: builders MUST use .format(), NOT f-string.
# f-string f'rate(...[{window}])' produces literal {window} in output.
# .format() substitutes {window} at call time with the actual value.

METRIC_PATTERNS = [
    # Error rate patterns — WAJIB: error_rate hanya 'rate'; 'count/total' → error_count
    # (Fix #256: sebelumnya regex error_rate mencuri kata 'count' → 'error count' jadi ratio)
    (r"(?:error|exception|5[0-9]{2}|5xx)\s*rate\b", "error_rate",
     lambda svc: 'rate(http_requests_total{{service="{0}",code=~"5.."}}[{1}]) / rate(http_requests_total{{service="{0}"}}[{1}])'.format(svc, "{window}")),
    (r"(?:error|exception)\s*(?:count|total|number)", "error_count",
     lambda svc: 'increase(http_requests_total{{service="{0}",code=~"5.."}}[{1}])'.format(svc, "{window}")),
    # Request rate patterns
    (r"(?:request|req|traffic|throughput)\s*(?:rate|per|qps|rps)", "request_rate",
     lambda svc: 'rate(http_requests_total{{service="{0}"}}[{1}])'.format(svc, "{window}")),
    (r"(?:request|req)\s*(?:count|total|number)", "request_total",
     lambda svc: 'increase(http_requests_total{{service="{0}"}}[{1}])'.format(svc, "{window}")),
    # Latency patterns — spesifik (p95/p50) WAJIB sebelum generik latency (Fix #256:
    # sebelumnya 'p95 latency' match generik latency (p99) karena urutan salah)
    (r"(?:p95|95th)", "p95_latency",
     lambda svc: 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{{service="{0}"}}[{1}]))'.format(svc, "{window}")),
    (r"(?:p50|median|50th)", "p50_latency",
     lambda svc: 'histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{{service="{0}"}}[{1}]))'.format(svc, "{window}")),
    (r"(?:latency|response\s*time|duration|slow|p99)", "latency",
     lambda svc: 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{0}"}}[{1}]))'.format(svc, "{window}")),
    # CPU/Memory patterns
    (r"(?:cpu|processor)\s*(?:usage|utilization|load)", "cpu_usage",
     lambda svc: 'rate(container_cpu_usage_seconds_total{{pod=~"{0}.*"}}[{1}])'.format(svc, "{window}")),
    (r"(?:memory|mem|ram)\s*(?:usage|utilization|consumption)", "memory_usage",
     lambda svc: 'container_memory_working_set_bytes{{pod=~"{0}.*"}}'.format(svc)),
    (r"(?:memory|mem)\s*(?:limit|quota)", "memory_limit",
     lambda svc: 'container_memory_working_set_bytes{{pod=~"{0}.*"}} / container_spec_memory_limit_bytes{{pod=~"{0}.*"}} * 100'.format(svc)),
    # Pod health patterns
    (r"(?:pod|container)\s*(?:restart|crash|oom)", "pod_restart",
     lambda svc: 'rate(kube_pod_container_status_restarts_total{{pod=~"{0}.*"}}[{1}])'.format(svc, "{window}")),
    (r"(?:ready|available)\s*(?:pod|replica)", "ready_pods",
     lambda svc: 'kube_deployment_status_replicas_available{{deployment=~"{0}.*"}}'.format(svc)),
    # Queue patterns
    (r"(?:queue|pending|backlog)\s*(?:size|length|count)", "queue_size",
     lambda svc: 'rabbitmq_queue_messages{{queue=~"{0}.*"}}'.format(svc)),
]

# Map common metric shorthand to base metric names
METRIC_ALIASES = {
    "error": "http_requests_total",
    "request": "http_requests_total",
    "latency": "http_request_duration_seconds",
    "duration": "http_request_duration_seconds",
    "cpu": "container_cpu_usage_seconds_total",
    "memory": "container_memory_working_set_bytes",
    "mem": "container_memory_working_set_bytes",
    "restart": "kube_pod_container_status_restarts_total",
    "pod": "kube_pod_status_phase",
}


def _pattern_match(description: str, service_name: str, window: str) -> Optional[dict]:
    """
    Try deterministic pattern matching. Returns dict with promql, description,
    confidence, or None if no pattern matches.
    """
    desc_lower = description.lower()

    for pattern, metric_type, builder in METRIC_PATTERNS:
        if re.search(pattern, desc_lower):
            # Builder outputs template with literal {window}; substitute now
            promql = builder(service_name).replace("{window}", window)
            return {
                "promql": promql,
                "description": f"{metric_type} for {service_name}",
                "confidence": 0.85,
            }
    return None


async def _llm_classify_metric(description: str) -> Optional[dict]:
    """
    Fallback: use LLM to classify which base metric the user is asking about.
    Returns dict with metric_type, metric_name, confidence, or None.
    Async — no run_until_complete (R2 fix).
    """
    try:
        from services.llm_factory import get_chat_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        import json

        llm = get_chat_llm(temperature=0.1)
        prompt = render_prompt(
            "promql_classify",
            description=description,
            available_metrics=", ".join(sorted(set(METRIC_ALIASES.keys()))),
        )
        resp = await llm.ainvoke([
            SystemMessage(content="You are a metric classifier. Reply with JSON only."),
            HumanMessage(content=prompt),
        ])
        txt = resp.content.strip() if hasattr(resp, "content") else str(resp)
        if "```" in txt:
            txt = txt.split("```")[1]
            if txt.strip().startswith("json"):
                txt = txt.strip()[4:]
        result = json.loads(txt.strip())
        metric_name = result.get("metric_name")
        confidence = float(result.get("confidence", 0) or 0)
        if metric_name and confidence >= 0.6:
            return {
                "metric_type": result.get("metric_type", "unknown"),
                "metric_name": metric_name,
                "confidence": confidence,
            }
    except Exception as e:
        logger.warning(f"[PromQL Translator] LLM classify failed: {e}")
    return None


async def translate_to_promql(
    description: str,
    service_name: str,
    window: str = "1h",
) -> dict:
    """
    Translate natural language description to PromQL.

    Uses deterministic pattern matching first, then LLM fallback.
    Applies server-side validation before returning.

    Returns dict with promql, description, confidence, metric_type, match_type, window.
    """
    # Parse window from description if present, then clamp to allowed set
    parsed_window = parse_window_from_text(description, default=window)
    # Use parsed window if user specified one; otherwise keep explicit param
    if window == "1h" and parsed_window != "1h":
        window = parsed_window
    window = clamp_window(window)

    # Step 1: Try deterministic pattern matching
    pattern_result = _pattern_match(description, service_name, window)
    if pattern_result:
        pattern_result["match_type"] = "pattern"
        pattern_result["metric_type"] = "detected"
        pattern_result["window"] = window
        is_valid, reason = validate_promql(pattern_result["promql"], window)
        if not is_valid:
            logger.warning(f"[PromQL Translator] Validation failed: {reason}")
            return {
                "promql": None, "description": description, "confidence": 0.0,
                "metric_type": "unknown", "match_type": "validation_failed",
                "window": window, "validation_error": reason,
            }
        return pattern_result

    # Step 2: LLM fallback (async, R2 fix)
    llm_result = await _llm_classify_metric(description)
    if llm_result:
        metric_name = llm_result.get("metric_name", "unknown")
        base_metric = METRIC_ALIASES.get(metric_name, metric_name)
        if "request" in metric_name or "error" in metric_name:
            promql = 'rate({0}{{service="{1}"}}[{2}])'.format(base_metric, service_name, window)
        elif "duration" in metric_name or "latency" in metric_name:
            promql = 'histogram_quantile(0.99, rate({0}_bucket{{service="{1}"}}[{2}]))'.format(base_metric, service_name, window)
        elif "cpu" in metric_name:
            promql = 'rate({0}{{pod=~"{1}.*"}}[{2}])'.format(base_metric, service_name, window)
        elif "memory" in metric_name:
            promql = '{0}{{pod=~"{1}.*"}}'.format(base_metric, service_name)
        elif "restart" in metric_name:
            promql = 'rate({0}{{pod=~"{1}.*"}}[{2}])'.format(base_metric, service_name, window)
        else:
            promql = '{0}{{service="{1}"}}'.format(base_metric, service_name)

        is_valid, reason = validate_promql(promql, window)
        if not is_valid:
            logger.warning(f"[PromQL Translator] LLM output validation failed: {reason}")
            return {
                "promql": None, "description": description, "confidence": 0.0,
                "metric_type": metric_name, "match_type": "validation_failed",
                "window": window, "validation_error": reason,
            }

        return {
            "promql": promql,
            "description": f"{llm_result.get('metric_type', metric_name)} for {service_name}",
            "confidence": llm_result.get("confidence", 0.6),
            "metric_type": metric_name,
            "match_type": "llm",
            "window": window,
        }

    # Step 3: No match
    return {
        "promql": None, "description": description, "confidence": 0.0,
        "metric_type": "unknown", "match_type": "none", "window": window,
    }
