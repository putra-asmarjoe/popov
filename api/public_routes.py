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
    # Alert Ingest — external app triggers alert + ticket (watchdog funnel)
    "POST /api/pub/v1/ingest/alert": {
        "scopes": ["alerts:write"],
        "rate_limit": 200,
        "description": "Use this endpoint from any external tool (Sentry, cron jobs, uptime monitors, custom scripts) to trigger an alert and open a ticket. Popov runs the same funnel as watchdog/webhook: saves the alert, links or creates a ticket (dedup=auto|new), and sends notifications (Telegram/email/bell). The `source` label is recorded — you can see every sender under Workspace Settings → Sources.",
    },
    # Deploy Event (Gap 4) — CI/CD signal for non-K8s deploy detection
    "POST /api/pub/v1/deploy-event": {
        "scopes": ["deploy:write"],
        "rate_limit": 200,
        "description": "Ingest deploy events from CI/CD pipelines (GitHub Actions, GitLab CI)",
    },
    # Knowledge Ingest (Fix #170: supports meta field)
    "POST /api/pub/v1/ingest/knowledge": {
        "scopes": ["knowledge:write"],
        "rate_limit": 200,
        "description": "Create a WORKSPACE knowledge item — stored in the knowledge library and linked to the target workspace (visible workspace-wide). Used by external systems (n8n, CI/CD, custom scripts) to push documentation; knowledge feeds the agent's RAG during investigations. For service-specific knowledge, use POST /ingest/knowledge/service instead.",
    },
    # Public: Inject knowledge into service
    "POST /api/pub/v1/ingest/knowledge/service": {
        "scopes": ["knowledge:write"],
        "rate_limit": 200,
        "description": "Inject a knowledge item directly into a specific service's knowledge base (must include the `service` slug). Used by external systems (n8n, CI/CD) AND by the \"Upload knowledge via AI agent\" flow in Workspace Settings → Services: the agent scans your code (ScanningGuide.md) and uploads docs using the POPOV_HOST / POPOV_TOKEN / POPOV_WORKSPACE_ID / SERVICE_ID env vars shown there — knowledge feeds the agent's RAG for that service during investigations.",
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
    # Future endpoints — uncomment to enable:
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


# ── Public Endpoint Specs (curated docs for Management → API Docs) ───────────
# Source of truth for the internal API documentation page (admin only).
# Keyed by "METHOD /path" — must match PUBLIC_ENDPOINTS.
# Add a spec whenever you add a public endpoint so docs stay in sync.

PUBLIC_ENDPOINT_SPECS: Dict[str, Dict[str, Any]] = {
    "POST /api/pub/v1/ingest/knowledge": {
        "summary": "Create knowledge item",
        "params": [
            {"name": "name", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Knowledge document name (auto-slugified)"},
            {"name": "folder", "in": "body", "type": "string", "required": False, "default": "general",
             "description": "Category: general, services, playbooks, schemas, connections, observability, or custom"},
            {"name": "content", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Markdown content. Max length follows embedding config (default 8000 chars)."},
            {"name": "workspace_id", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Required for API key auth — target workspace to link the item into"},
            {"name": "meta", "in": "body", "type": "object", "required": False, "default": None,
             "description": "Optional structured metadata (JSON object)"},
        ],
        "example_request": {
            "name": "app_core_api",
            "folder": "general",
            "content": "# App Core API\n\nBase URL: https://api.app.id\nAuth: JWT Bearer",
            "workspace_id": "ws_XXXXXXXX",
        },
        "example_response": {
            "success": True,
            "message": "Knowledge 'app_core_api' has been added successfully",
            "data": {"id": "66f1...", "name": "app_core_api", "folder": "general", "embedded": True},
        },
    },
    "POST /api/pub/v1/ingest/knowledge/service": {
        "summary": "Inject knowledge into a service knowledge base",
        "params": [
            {"name": "name", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Knowledge document name (auto-slugified)"},
            {"name": "folder", "in": "body", "type": "string", "required": False, "default": "general",
             "description": "Category for the knowledge item"},
            {"name": "service", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Service slug — must exist in service library (hyphen/underscore lookup is flexible)"},
            {"name": "workspace_id", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Required for API key auth — workspace used for ownership/auto-registration"},
            {"name": "content", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Markdown content. Max length follows embedding config (default 8000 chars)."},
            {"name": "meta", "in": "body", "type": "object", "required": False, "default": None,
             "description": "Optional structured metadata (JSON object)"},
        ],
        "example_request": {
            "name": "app_core_api",
            "folder": "general",
            "service": "app-core-api",
            "workspace_id": "ws_XXXXXXXX",
            "content": "# App Core API\n\nOwned by service app-core-api",
        },
        "example_response": {
            "success": True,
            "message": "Knowledge 'app_core_api' has been injected into service app-core-api",
            "data": {"id": "66f1...", "name": "app_core_api", "folder": "general",
                     "serviceId": "65c1...", "workspace_id": "ws_XXXXXXXX", "embedded": True,
                     "linked": True, "action": "created"},
        },
    },
    "GET /api/pub/v1/ingest/knowledge/{item_id}": {
        "summary": "Read knowledge item by ID",
        "params": [
            {"name": "item_id", "in": "path", "type": "string", "required": True, "default": None,
             "description": "Knowledge item ID (MongoDB ObjectId)"},
        ],
        "example_response": {
            "success": True,
            "data": {"id": "66f1...", "name": "app_core_api", "folder": "general",
                     "content": "# App Core API\n\nBase URL: https://api.app.id"},
        },
    },
    "PATCH /api/pub/v1/ingest/knowledge/{item_id}": {
        "summary": "Update knowledge item by ID",
        "params": [
            {"name": "item_id", "in": "path", "type": "string", "required": True, "default": None,
             "description": "Knowledge item ID (MongoDB ObjectId)"},
            {"name": "name", "in": "body", "type": "string", "required": False, "default": None,
             "description": "New document name (auto-slugified)"},
            {"name": "folder", "in": "body", "type": "string", "required": False, "default": None,
             "description": "New category"},
            {"name": "content", "in": "body", "type": "string", "required": False, "default": None,
             "description": "New markdown content — triggers re-embedding when changed"},
            {"name": "meta", "in": "body", "type": "object", "required": False, "default": None,
             "description": "Replace structured metadata (JSON object)"},
        ],
        "example_request": {
            "content": "# App Core API v2\n\nNew endpoint: /v2/orders",
        },
        "example_response": {
            "success": True,
            "message": "Knowledge 'app_core_api' has been updated successfully",
            "data": {"id": "66f1...", "name": "app_core_api", "folder": "general",
                     "content": "# App Core API v2\n\nNew endpoint: /v2/orders"},
        },
    },
    "POST /api/pub/v1/deploy-event": {
        "summary": "Ingest deploy event from CI/CD",
        "params": [
            {"name": "service_name", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Service that was deployed (1-64 chars)"},
            {"name": "version", "in": "body", "type": "string", "required": False, "default": None,
             "description": "Version / commit / tag (max 128 chars)"},
            {"name": "deployed_at", "in": "body", "type": "string (datetime)", "required": False, "default": "now (UTC)",
             "description": "Deploy timestamp in ISO 8601. Defaults to the current time (UTC)."},
            {"name": "project_id", "in": "body", "type": "string", "required": False, "default": None,
             "description": "Optional project id to associate the deploy with"},
            {"name": "source", "in": "body", "type": "string", "required": False, "default": "api",
             "description": "Label of the CI/CD pipeline — e.g. \"github_actions\", \"gitlab_ci\", \"api\". Every source is recorded and appears under Workspace Settings → Sources."},
        ],
        "example_request": {
            "service_name": "app-core-api",
            "version": "v1.4.2",
            "deployed_at": "2026-09-03T09:30:00Z",
            "source": "github_actions",
        },
        "example_response": {
            "ok": True,
            "event_id": "66f1...",
            "message": "Deploy event recorded",
            "service_name": "app-core-api",
            "version": "v1.4.2",
        },
    },
    "POST /api/pub/v1/ingest/alert": {
        "summary": "Trigger alert + ticket from an external application",
        "params": [
            {"name": "service", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Service slug that is having a problem (must match a registered service)"},
            {"name": "name", "in": "body", "type": "string", "required": False, "default": "ExternalAlert",
             "description": "Alert name / short title (used in ticket title and dedup fingerprint)"},
            {"name": "severity", "in": "body", "type": "string", "required": False, "default": "warning",
             "description": "critical | warning | info | error. Mapped to the watchdog severity scale."},
            {"name": "description", "in": "body", "type": "string", "required": False, "default": None,
             "description": "Alert detail (markdown ok, max 8000 chars) — becomes the ticket description"},
            {"name": "details", "in": "body", "type": "object", "required": False, "default": None,
             "description": "Optional structured metadata (JSON object)"},
            {"name": "workspace_id", "in": "body", "type": "string", "required": True, "default": None,
             "description": "Required for API key auth — target workspace for the ticket"},
            {"name": "dedup", "in": "body", "type": "string", "required": False, "default": "auto",
             "description": "auto = link to an active ticket with the same content if one exists; new = always create a new ticket"},
            {"name": "source", "in": "body", "type": "string", "required": False, "default": "external",
             "description": "Label identifying the external caller — e.g. \"sentry\", \"github_actions\", \"rollbar\", \"cron-monitor\". Every source is recorded and appears under Workspace Settings → Sources."},
            {"name": "started_at", "in": "body", "type": "string (datetime)", "required": False, "default": "now (UTC)",
             "description": "When the problem started, ISO 8601"},
        ],
        "example_request": {
            "service": "app-core-api",
            "name": "HighErrorRate",
            "severity": "critical",
            "description": "Error rate > 5% in the last 10 minutes",
            "workspace_id": "ws_XXXXXXXX",
            "dedup": "auto",
            "source": "sentry",
        },
        "example_response": {
            "success": True,
            "message": "Alert ingested — check ticket & notification",
            "data": {
                "service": "app-core-api",
                "alert_id": "66f1...",
                "dedup": "auto",
                "skipped": None,
                "tickets_created": 1,
                "tickets_new": ["CORE-12"],
                "tickets_linked": [],
                "notifications_sent": 2,
            },
        },
    },
}


def list_public_endpoints() -> list:
    """List all registered public endpoints (with curated docs spec)."""
    return [
        {
            "method": k.split(" ")[0],
            "path": k.split(" ")[1],
            "scopes": v["scopes"],
            "rate_limit": v["rate_limit"],
            "description": v["description"],
            "spec": PUBLIC_ENDPOINT_SPECS.get(k, {}),
        }
        for k, v in PUBLIC_ENDPOINTS.items()
    ]
