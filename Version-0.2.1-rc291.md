# Popov v0.2.1-rc291 — Release Candidate

This release transforms Popov from an incident-focused assistant into a full operations companion: natural conversations flow seamlessly through ticket sessions, Kubernetes insights arrive without leaving chat, the system learns your preferences over time, and every response speaks your language. Plus a complete dashboard analytics suite, a public API for external systems, and smarter service resolution across the entire platform.

## What's in this release

### Conversational Chat System (CHAT3)
- Three depth modes: quick answers, medium analysis, and thinking mode for deep investigation
- Chat agent handles natural questions in ticket sessions without forcing users into keyword-shaped sentences
- Post-tool synthesis: after metrics or data queries, a final LLM pass composes a grounded answer from the raw results
- Context-aware chips that adapt based on what you just asked or did
- Thinking steps visualization shows the investigation progress in real-time

### Kubernetes & Pod Intelligence
- Direct pod health checks from chat: "check pod status kuponku-users" returns restart counts, OOM kills, and readiness
- PromQL range queries via natural language: "error rate lovvit-landing-platform last 6 hours" translates automatically
- K8s inventory across all connected clusters: "show available pods" queries every linked stack
- Deployment ranking: "which pod has the most replicas" uses Prometheus metrics, not ticket counts
- Pod restart RCA now includes K8s events (BackOff, OOMKilled) in the correlation analysis

### User Profile System
- Passive learning from your interactions: services queried, active hours, chips clicked
- Explicit preferences: verbosity, tone, format, investigation depth — set once, respected always
- Personalized responses that adapt to your communication style over time
- Batch inference suggests preference updates after 20 interactions — approve or reject via UI

### Multi-Language Support
- Every deterministic response path now bilingual (English/Indonesian)
- Diagnostic sessions, knowledge listings, incident fallbacks — all locale-aware
- Locale resolved from user preference → conversation history → workspace default
- Technical blocks (kubectl diagnostics) stay English regardless of locale

### Dashboard Analytics
- Five new widgets: stat cards, ticket trend chart, severity donut, top services, top alert types
- Days filter connected to all cards, alerts, and open tickets
- View-based preferences: classic and warroom modes remember your widget layout
- Severity colors aligned across dashboard and ticket list

### Source Registry & Public API
- See where Popov receives data from: Sources tab shows all alert and deploy integrations
- Public API for external systems: `POST /api/pub/v1/ingest/alert` triggers the same funnel as watchdog
- Source inventory from chat: "what sources are sending signals?" returns a full report
- Claude (Anthropic) added as BYOK provider via OpenAI-compatible layer

### Smart Service Resolution
- Canonical service names: devops suffixes (-apps, prod-) automatically normalized to library IDs
- Alias learning: when you manually link a ticket to a service, Popov remembers the pattern
- Multi-service ticket linking: connect a ticket to multiple services from the UI
- Strategy 3 dead code fix: word-overlap matching now actually works

### Knowledge Management
- Knowledge queries in ticket sessions now routed to project inventory instead of redirect
- Connection queries ("what services are connected?") answered deterministically
- Knowledge listing hardcoded strings eliminated — all responses follow user locale
- Public API docs cleaned up with clearer endpoint descriptions

### Platform Improvements
- Dashboard analytics with real-time severity distribution and MTTR calculations
- Ticket trend visualization with configurable time windows
- Open+New badge on stat cards for quick status
- Pagination footer always visible for transparency
- Onboarding checklist for new workspaces

### Agent Intelligence
- Triage multi-signal fusion: deploy events + error spikes correlated with time-decay
- Focus hints bypass confidence narrowing when verification steps are needed
- Investigation planner now includes K8s events when restart signals detected
- Pod health incident guard prevents false-positive hijacking of "replica set" queries

### Reliability & Observability
- LangGraph schema filter fix: pending_offer and force_full_fanout now declared in state
- Telemetry instrumentation for every routing gate decision
- Conversation state persistence across turns in project and ticket sessions
- Request logs capture synthesis usage and agent routing decisions

## What's Fixed
- Chat pipeline crash when correlation result is a dict instead of string
- Pod health queries in ticket sessions routed to ticket_agent instead of metrics
- "Assign me to this ticket" bug when sender identity missing from LLM prompt
- Deployment ranking fabricating ticket counts as replica counts
- Knowledge chip in ticket sessions triggering redirect instead of inventory
- Diagnostic session buttons always Indonesian even for English users
- Error rate regex missing parenthetical suffix (5m) in metrics output
- Alert card leaking across projects when project has no observability stack
- Onboarding Sources tab empty without guidance for first-time visitors
- Docker build failing when COPYing runtime output folders

## Platform
- Multi-workspace, multi-project ticketing with full status chain
- Real-time cross-process updates via MongoDB relay
- BYOK LLM (OpenAI / OpenRouter / Gemini / OpenCode / Claude), keys encrypted at rest
- Full EN↔ID i18n across all user-facing strings
- Watchdog: poll (5m) + Alertmanager webhook push
- Telegram: interactive buttons, diagnostic sessions, feedback loop

## Deployment
```bash
# Build
docker build \
  --build-arg VITE_API_BASE_URL=/api/v1 \
  -t putraasmarjoe/popov-agent:0.2.1-rc291 \
  -f deploy/Dockerfile .

# Push
docker push putraasmarjoe/popov-agent:0.2.1-rc291
```

See `deploy/README.md` for full Kubernetes deployment instructions.
