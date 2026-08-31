"""
Public Endpoint Registry — Modular, configurable list of public endpoints.

Defines which endpoints are accessible via public API keys (pk_pub_*).
To add a new public endpoint:
    1. Add entry to PUBLIC_ENDPOINTS dict below
    2. Create the endpoint in api/ingest.py (or appropriate router)
    3. That's it — no middleware changes needed

Format: "METHOD /path" → config dict
"""
from typing import Any, Dict, Optional

# ── Public Endpoint Registry ─────────────────────────────────────────────────
# Add new public endpoints here. Keys are "METHOD /full/path".

PUBLIC_ENDPOINTS: Dict[str, Dict[str, Any]] = {
    # Knowledge Ingest (Fix #170: supports meta field)
    "POST /api/pub/v1/ingest/knowledge": {
        "scopes": ["knowledge:write"],
        "rate_limit": 200,
        "description": "Ingest knowledge from external systems (n8n, CI/CD, etc.)",
    },
    # Knowledge Read — public API
    "GET /api/pub/v1/ingest/knowledge/{item_id}": {
        "scopes": ["knowledge:read"],
        "rate_limit": 200,
        "description": "Read knowledge item by ID",
    },
    # Knowledge Update — public API
    "PATCH /api/pub/v1/ingest/knowledge/{item_id}": {
        "scopes": ["knowledge:write"],
        "rate_limit": 200,
        "description": "Update knowledge item by ID",
    },
    # Public: Inject knowledge into service
    "POST /api/pub/v1/ingest/knowledge/service": {
        "scopes": ["knowledge:write"],
        "rate_limit": 200,
        "description": "Inject knowledge directly into service knowledge base",
    },
    # Deploy Event (Gap 4) — CI/CD signal for non-K8s deploy detection
    "POST /api/pub/v1/deploy-event": {
        "scopes": ["deploy:write"],
        "rate_limit": 200,
        "description": "Ingest deploy events from CI/CD pipelines (GitHub Actions, GitLab CI)",
    },
    # Future endpoints — uncomment to enable:
    # "POST /api/pub/v1/ingest/alert": {
    #     "scopes": ["alerts:write"],
    #     "rate_limit": 500,
    #     "description": "Ingest alerts from Alertmanager/n8n",
    # },
    # "GET /api/pub/v1/tickets": {
    #     "scopes": ["tickets:read"],
    #     "rate_limit": 100,
    #     "description": "List tickets",
    # },
}


def is_public_endpoint(method: str, path: str) -> bool:
    """Check if endpoint is in the public registry (supports path params)."""
    return get_public_endpoint_config(method, path) is not None


def get_public_endpoint_config(method: str, path: str) -> Optional[Dict[str, Any]]:
    """Get config for a public endpoint, matching path parameters."""
    exact = PUBLIC_ENDPOINTS.get(f"{method} {path}")
    if exact:
        return exact
    # Match path params: /api/v1/ingest/knowledge/{id} → /api/v1/ingest/knowledge/xxx
    for key, config in PUBLIC_ENDPOINTS.items():
        reg_method, reg_path = key.split(" ", 1)
        if reg_method != method:
            continue
        reg_parts = reg_path.strip("/").split("/")
        path_parts = path.strip("/").split("/")
        if len(reg_parts) != len(path_parts):
            continue
        match = True
        for rp, pp in zip(reg_parts, path_parts):
            if rp.startswith("{") and rp.endswith("}"):
                continue  # path param — skip
            if rp != pp:
                match = False
                break
        if match:
            return config
    return None


def list_public_endpoints() -> list:
    """List all registered public endpoints."""
    return [
        {
            "method": k.split(" ")[0],
            "path": k.split(" ")[1],
            "scopes": v["scopes"],
            "rate_limit": v["rate_limit"],
            "description": v["description"],
        }
        for k, v in PUBLIC_ENDPOINTS.items()
    ]
