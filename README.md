# Popov

![License](https://img.shields.io/badge/license-FSL--1.1--ALv2-blue)
![Python](https://img.shields.io/badge/python-3.9+-green)
![React](https://img.shields.io/badge/react-19-61dafb)
![Status](https://img.shields.io/badge/status-active%20development-orange)
[![Website](https://img.shields.io/badge/website-getpopov.com-0369a1?style=flat&logo=cloudflare)](https://getpopov.com)

Open-source, self-hosted **the intelligence behind operations**.

Popov connects your existing observability stack — Prometheus, Tempo, Loki, and Alertmanager — with knowledge, ticketing, and AI agents to help teams understand, investigate, and resolve operational problems.

Today, Popov focuses on production incidents: automatically triaging signals, investigating with a LangGraph multi-agent pipeline, and delivering a single actionable report with root cause and recommended actions — wherever your team works, via Telegram, email, or the built-in web workspace.

> 🔒 **Your data never leaves your infrastructure.** No telemetry. No phone home. No third-party with access to your production logs.

---

<p align="center">
  <strong>Popov is free, self-hosted, and always will be.</strong><br><br>
  If Popov makes your on-call a little easier,<br>
  consider buying the person behind it a coffee. ☕<br><br>
  <a href="https://getpopov.com">
  <img src="https://img.shields.io/badge/🌐%20Website-getpopov.com-0369a1?style=for-the-badge" alt="Website">
</a>&nbsp;&nbsp;<a href="https://ko-fi.com/popovagent">
    <img src="https://img.shields.io/badge/☕%20Buy%20me%20a%20coffee-Ko--fi-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white" alt="Buy me a coffee on Ko-fi">
  </a>
  &nbsp;&nbsp;
  <a href="https://saweria.co/putraasmarjoe">
    <img src="https://img.shields.io/badge/Donasi-Saweria-orange?style=for-the-badge" alt="Donasi via Saweria">
  </a>
</p>

---

## Why Popov?

Modern production systems generate plenty of signals, but signals aren't the same as understanding.

When an incident happens, engineers still have to jump between alerts, logs, traces, dashboards, documentation, tickets, and chat — then connect the dots under pressure.

Popov is built to do that work with you.

It takes the signals you already have, gathers the relevant context, investigates across your systems, and turns it into one actionable incident report.

**Less signal. More understanding.**

---

## What Popov Does

| | |
|---|---|
| 🚨 **Incident Triage** | Automatically analyze incoming production alerts |
| 🔍 **Investigation** | Correlate metrics, logs, traces, and operational context |
| 🧠 **AI Agents** | LangGraph multi-agent pipeline investigates incidents end-to-end |
| 📋 **Actionable Reports** | Root cause analysis, evidence, and recommended actions |
| 📚 **Knowledge-Aware** | Grounded in your own service docs and past incident history |
| 💬 **Team Notifications** | Delivered via Telegram, email, or the built-in web workspace |
| 🖥️ **War Room** | Incident operations dashboard — tickets, alerts, and timelines in one view |
| ☸️ **Kubernetes Intelligence** | Query pod health, metrics, and events directly from chat |
| 📊 **Dashboard Analytics** | Per-project stats, ticket trends, and severity distribution at a glance |
| 🔒 **Self-Hosted** | Your operational data never leaves your own infrastructure |

---

## Screenshots

<p align="center">
  <img src="screenshots/ss1-v2.png" alt="War Room Overview" width="800" />
  <br><em>War Room — tickets, alerts, stack health, and incident pulse in one view.</em>
</p>

<p align="center">
  <img src="screenshots/ss2.png" alt="Ticket War Room — investigation report" width="800" />
  <br><em>Investigation report — hypothesis, confidence, evidence pillars, and remediation in one view.</em>
</p>

<p align="center">
  <img src="screenshots/ss3.png" alt="Ticket chat with the agent" width="800" />
  <br><em>Agent chat — ask about an incident and get an answer, with full agent trace one click away.</em>
</p>

---

## The Problem

Most teams already have monitoring. What they usually don't have is a bridge between *signals* and *action*:

- Alerts fire in Prometheus/Alertmanager, but someone still has to manually pull logs, metrics, and traces from different tools to figure out what happened.
- The same investigation steps are repeated from scratch every time, even when the incident looks like one the team solved last month.
- Alerts arrive as noise; context arrives too late; incidents get reported long after they're detected.
- Observability data lives in one set of tools while incident tracking lives in another, so nothing links back.

Popov closes that gap: it detects, investigates, explains, tracks, and learns — in one workflow.

---

## What Is Popov?

Popov is a single deployable system made of three cooperating parts:

| Part | What it is |
|---|---|
| **Agent pipeline** | A [LangGraph](https://github.com/langchain-ai/langgraph) multi-agent backend (Python/FastAPI) that routes intents, triages silently, runs selective investigations across logs/metrics/traces/spans, and produces an LLM-written root cause assessment. |
| **Web platform** | A React SPA with workspaces, projects, realtime ticketing, an in-app chat with the agent (SSE streaming), a War Room incident dashboard, dashboard analytics, knowledge libraries, and admin management for stacks, notification channels, LLM keys, and memory. |
| **Watchdog worker** | A dedicated background process that polls your observability targets (or receives Alertmanager webhooks), deduplicates alerts, triages them, opens tickets, and broadcasts to Telegram channels. |

It is not a metrics database or a dashboard replacement — it sits **on top of** the observability stack you already run.

---

## What Popov Helps You Do

- **Detect proactively** — a watchdog polls Prometheus/Alertmanager/Tempo per project (or receives Alertmanager webhook pushes, <5s latency), with content-based fingerprinting to suppress duplicate alerts.
- **Triage before you're paged** — a silent triage stage (<30s) correlates four signals: error rate vs baseline, active alerts, recent deployments, and historical episodes using time-decay multi-signal fusion. If a deploy happened in the last hour, "regression after deploy" becomes the leading hypothesis. Non-Kubernetes stacks (VM/PaaS) get the same hypothesis by reporting deploys through a CI/CD API.
- **Investigate selectively, not blindly** — based on the hypothesis, only the relevant data collectors fan out in parallel: error logs (MongoDB/MySQL per service), Prometheus metrics/HPA, Tempo traces, OpenTelemetry spans from a central log DB, DB health checks. The fan-out adapts to confidence level, service type, and triage skip-hints — narrower when confident, wider when uncertain.
- **Get a root cause, not a data dump** — a single Correlation Agent call synthesizes all pillars plus grounding docs and learned patterns into a severity + root cause (`service-fault` / `downstream` / `unknown`) with remediation suggestions.
- **Keep institutional memory** — every incident becomes an episodic memory entry ("Second Brain") with vector embeddings; future investigations retrieve similar past episodes with their ✅/❌ human feedback. Episodes record real outcomes: time-to-resolution, resolution steps taken, and knowledge docs consulted. A pattern miner clusters recurring episodes into auto-generated Learned Patterns.
- **Continue the conversation** — reports come with dynamic follow-up buttons and a 30-minute diagnostic session (Telegram), and the web chat offers actionable follow-up chips that run a deeper check in one click. Three depth modes are available: quick answers, medium analysis, or thinking mode for deep investigation.
- **Query Kubernetes from chat** — check pod health, restart counts, OOM kills, and readiness; run PromQL range queries in plain language ("error rate lovvit-landing-platform last 6 hours"); list pods across all connected clusters; all directly from the chat interface.
- **Track resolution** — detected alerts can auto-create tickets (1 ticket : N linked alerts, linkable to multiple services) in a realtime ticketing UI with status chain, assignees, progress logs, and 🤖 auto badges. You can also manage tickets by chatting with the agent ("close this ticket", "set severity to low").
- **Confirm the fix worked** — when a ticket moves to in-progress, Popov schedules an automatic re-check ~10 minutes later: error rate and database health, with a ✅/⚠️ confirmation notification.
- **Run a command center, not just a ticket list** — the War Room view turns a project into an incident operations dashboard: open tickets, a live alert feed, stack health, and investigation timelines side by side. Dashboard Analytics adds per-project stat cards, ticket trend charts, severity distribution, top services, and top alert types — with a configurable time range that applies to all widgets at once.
- **See inside the investigation** — click any AI reply to view the full agent trace as a graph: every step in order, how long it took, and a summary of what each produced. Slow steps are highlighted.
- **Know where your data comes from** — the Sources registry shows every integration sending signals to Popov: alert sources, deploy events, and external ingest. You can also ask from chat: "what sources are sending signals?"
- **Adapt to your style** — Popov learns your preferences over time: which services you query most, your preferred response verbosity, tone, and investigation depth. Personalization applies automatically across all future responses.
- **Control costs** — data-collector agents never call an LLM (<500-token summaries); only ~7 well-defined points use the LLM, all tracked per agent/model/token via `llm_usage`.

---

## Data Privacy & Sovereignty

Popov is designed with one principle: **your incident data never leaves your infrastructure.**

- **No telemetry** — Popov does not collect or transmit usage data
- **No phone home** — zero outbound calls to Popov servers
- **No third-party access** — your logs, alerts, and incident history stay on your servers
- **No vendor lock-in** — your data lives in your own MongoDB, your own storage

---

## Key Features

### AI Investigation Pipeline
- Intent supervisor with 4 matching strategies plus an LLM fallback for ambiguous requests
- Silent triage → hypothesis-driven selective fan-out (2–3 collectors instead of everything), adaptive to confidence level, service type, and triage skip-hints
- Multi-signal triage fusion: deploy events and error spikes correlated with time-decay weighting — a spike right after a deploy is weighted higher, a coincidental one is not
- Deploy-aware triage: recent deploys detected via Loki K8s events — or via a CI/CD deploy-event API for non-Kubernetes stacks
- Knowledge Agent with query-aware active retrieval: triage hypothesis + service + focus drive a targeted search (three-layer: deterministic bypass → vector similarity → keyword fallback)
- LLM root cause analysis grounded in your own service docs (RAG) and past episodes
- Episodic memory with hybrid search (metadata + embeddings, local TF fallback), feedback loop, and auto-resolution of stale episodes
- Episode enrichment: resolved tickets feed back real time-to-resolution, resolution steps, and consulted knowledge into memory
- HDBSCAN-based pattern mining → `Learned Patterns` injected into future analyses
- Post-fix verification: automatic re-check of error rate and DB health ~10 minutes after a ticket moves to in-progress, with ✅/⚠️ confirmations
- File-driven prompts (`prompts/*.md`, hot-reloadable via API)

### Incident Management & Collaboration
- Workspaces, projects, members, roles (admin/member) with JWT auth
- Realtime ticketing (WebSocket): full lifecycle `new → open → in_progress → needs_review → resolved → closed`, reopen, assignees, append-only progress log, deep-linkable tickets
- Multi-service ticket linking — a single ticket can be connected to multiple services; filter the ticket list by any linked service
- Auto-tickets from alerts with fingerprint dedup and configurable re-open window
- **War Room** — an incident operations dashboard per project: open tickets, live alert feed, stack health, and episode timelines in one view, with a Classic/War Room toggle
- **Dashboard Analytics** — per-project stat cards, ticket trend chart, severity donut, top services, and top alert types; one time range drives all widgets
- In-app agent chat with streaming SSE responses, multi-turn history, three depth modes (quick / medium / thinking), actionable follow-up chips, and a visual agent trace on every AI reply
- Conversational ticket management: close, reopen, change status/severity, add labels, assign members, and append progress notes — all in natural language from chat
- Two-layer knowledge system: personal library ↔ workspace/project/service links, consumed by the agent as grounding

### Kubernetes & Pod Intelligence
- Pod health checks from chat: restart counts, OOM kills, readiness status
- Natural language PromQL range queries: plain English or Indonesian translates to PromQL automatically
- Pod inventory across all connected clusters from a single query
- Deployment ranking by replica count via Prometheus metrics
- Pod restart root cause analysis includes Kubernetes events (BackOff, OOMKilled)
- Namespace-aware: specify the target namespace directly in your question

### Integrations
- **Telegram**: multi-bot, multi-channel per workspace; interactive buttons; diagnostic sessions; alert broadcasts
- **Email (SMTP)**: second notification channel alongside Telegram — the same alerts delivered to both in one broadcast, with delivery logs and encrypted credentials
- **Alertmanager**: per-tenant webhook ingestion with token auth and 30-min dedup window
- **Observability stacks per project**: register multiple Prometheus/Tempo/Alertmanager/Loki endpoints and bind them to projects (fallback chain: project → workspace default → global env)
- **Sources registry**: every alert source and deploy integration visible in one tab; queryable from chat
- **Public API & API keys**: scoped API keys (web vs public) with per-key rate limiting; `POST /api/pub/v1/ingest/alert` to push alerts from external systems; `POST /api/pub/v1/deploy-event` for CI/CD deploy reporting on non-Kubernetes stacks; public knowledge-ingest endpoint with upsert
- **Bring-your-own-key LLM**: OpenAI, OpenRouter, Google Gemini, OpenCode Zen, or Claude (Anthropic) — keys stored encrypted (Fernet) in the DB, managed from the UI

### Personalization
- Passive learning from your interactions: services queried, active hours, chips clicked
- Explicit preferences: response verbosity, tone, format, investigation depth — set once, respected always
- After 20 interactions, the system suggests preference updates based on observed patterns — approve or dismiss from the UI

### Multilingual Support
- Every response path available in English and Indonesian
- Locale resolved from user preference → conversation history → workspace default
- Technical blocks (kubectl diagnostics) stay in English for accuracy

---

## How It Works

```text
Signal source                     Popov                                   Outcome
─────────────────────────────    ─────────────────────────────────────    ──────────────
Prometheus / Alertmanager   ──►  Watchdog (poll or webhook push)
Tempo / Loki / app logs          │ fingerprint dedup
CI/CD deploy event               ▼
Telegram mention / API call ──►  Supervisor (intent routing)
Web chat                         │
                                 ▼
                                 Triage (silent, <30s)
                                 │  signals: error rate · alerts · deploys · history
                                 │  multi-signal fusion with time-decay weighting
                                 ▼
                                 Investigation Planner (hypothesis → nodes)
                                 │  confidence-aware: narrow when sure, wide when not
                                 ▼
                                 Parallel fan-out (selective):
                                 logs · metrics · traces · spans · health · K8s events
                                 │
                                 ▼
                                 Knowledge lookup (active retrieval: vector + keyword)
                                 │
                                 ▼
                                 Correlation Agent (LLM RCA)
                                 │  + Second Brain read/write (episodic memory)
                                 ▼
                                 Report ──► Telegram / Email / Web chat
                                 │           + follow-up chips + diagnostic session
                                 ▼
                                 Ticket created/linked ──► resolved in web UI
                                 │  + auto re-check ~10 min later (✅/⚠️)
                                 ▼
                                 Episode enriched ──► Pattern Miner ──► Learned Patterns
```

---

## Architecture

```mermaid
flowchart LR
    subgraph YourInfra["Your infrastructure"]
        APPS[Apps & services]
        OBS[Prometheus · Tempo · Loki · Alertmanager]
        LOGDB[(Central OTel log DB)]
        SVCDB[(Per-service log DBs<br/>MongoDB / MySQL)]
    end

    subgraph Popov["Popov (self-hosted)"]
        WD[Watchdog worker<br/>poll · dedup · auto-ticket]
        API[FastAPI backend]
        GRAPH[LangGraph agent pipeline<br/>triage → selective fan-out → correlation]
        SB[(MongoDB<br/>popovagent_db:<br/>tickets · episodes · audit)]
        UI[React web UI<br/>ticketing · chat · war room · analytics]
    end

    LLM[LLM provider<br/>OpenAI / OpenRouter /<br/>Gemini / OpenCode / Claude]
    TG[Telegram bots]
    EM[Email / SMTP]

    APPS --> OBS
    APPS --> LOGDB
    OBS -- "webhook push / poll" --> WD
    WD --> GRAPH
    GRAPH --> SVCDB
    GRAPH --> LOGDB
    GRAPH <--> SB
    GRAPH --> LLM
    API --- GRAPH
    UI --> API
    API <--> TG
    API --> EM
    WD --> TG
```

Two processes run from the same image: `uvicorn main:app` (API + Telegram listeners + web UI) and `watchdog_worker.py` (scheduler + auto-feedback + post-fix verification). The watchdog must run as exactly **one instance**; the API must stay at one replica until the Telegram listener is moved out-of-process (both constraints are documented in the deploy manifests).

---

## Quick Start

Requirements: Python ≥3.9, MongoDB, Node.js (for the web UI). An observability stack (Prometheus/Tempo/Loki/Alertmanager) is optional — Popov degrades gracefully without it.

**One-time setup** (run from the repo root):

```bash
python3 -m venv venv && source venv/bin/activate
python -m pip install --upgrade pip    # editable install needs pip ≥ 21.3
pip install -e ".[dev]"
cd web && npm install && cd ..
```

After setup, pick **one** of the two ways below to run the app.

### Option A — Run together in one terminal (easiest)

```bash
cd web
npm run dev        # API + Web UI  ([API] green · [WEB] yellow)
npm run dev:all    # API + Web UI + Watchdog worker ([WDT] red)
```

### Option B — Run each part separately

```bash
# Terminal 1 — Backend API (from the repo root)
./venv/bin/uvicorn main:app --port 8000

# Terminal 2 — Frontend dev server (from the web/ folder)
cd web && npm run dev
```

### When it's up

- Web UI → http://localhost:5173
- API & docs → http://localhost:8000/docs

### Then:

1. **Open the web UI.** On first launch, a **setup wizard** guides you through configuration — fill in four fields and the server writes the config automatically. JWT secret and encryption key can be auto-generated with one click.
2. **Register an account.** The first user to register automatically becomes the workspace admin.
3. In **Management**, add your LLM provider key (BYOK, encrypted at rest) and optionally an embedding model (or keep the free local TF mode).
4. In **Workspace Settings → Stacks / Notifications**, register your Prometheus/Tempo endpoints and a Telegram bot channel.
5. Trigger a test investigation:

```bash
curl -X POST http://localhost:8000/api/v1/trigger \
  -H "Content-Type: application/json" \
  -d '{"intent": "check errors on my-service"}'

# Interactive API docs
open http://localhost:8000/docs
```

### Do you need the watchdog worker?

`watchdog_worker.py` is a **separate process** — starting the API does *not* start it automatically.

| Without it (still works) | Only with it |
|---|---|
| API & web UI | Proactive alert polling (5m cycle) |
| Ticketing, progress log, linked alerts | Auto-create tickets from alerts |
| In-app agent chat | Telegram & email alert broadcasts |
| Telegram listener (mentions/buttons) | Second Brain auto-feedback (30 min) |
| Alertmanager webhook push (<5s) | Post-fix verification re-checks |

Run it only if you want Popov to *detect* incidents on its own:

```bash
npm run dev:all          # from web/ — together with everything else
# or standalone:
python watchdog_worker.py
```

⚠️ Exactly **one instance** — running two copies duplicates alerts and tickets.

For production, `npm run build` output (`web/dist`) is served by FastAPI itself — no separate frontend process needed.

---

## Configuration

Most runtime configuration is managed through the **UI and stored in MongoDB** (multi-tenant by design):

- **LLM keys & models** → Management → API Keys (encrypted with `DATA_ENCRYPTION_KEY`)
- **Observability stack URLs** → Workspace Settings → Stacks
- **Telegram bot tokens & chats** → Workspace Settings → Notifications
- **Service registry & log DB connections** → Workspace Settings → Services
- **LLM prompts** → editable `prompts/*.md` files, hot-reloaded via `POST /api/v1/prompts/reload`

Only a few things live in `.env` (see `.env.example`):

| Variable | Purpose |
|---|---|
| `MONGODB_URI` / `MONGODB_DB` | Main store: tickets, episodes, audit trails, sessions |
| `DATA_ENCRYPTION_KEY` | **Required.** Fernet master key for encrypting stored API keys |
| `JWT_SECRET` / `JWT_EXPIRY_HOURS` | Web authentication |
| `EMBEDDING_PROVIDER/MODEL/DIM` | Second Brain embeddings (`local` TF cosine by default, zero cost) |
| `OBSERVABILITY_*` | Global watchdog defaults: enabled, interval, alert-noise filters |
| `TICKET_ALERT_DEDUP_HOURS` | Window for linking repeated alerts to an active ticket |
| `LOKI_TIMEOUT_MS` / `LOKI_NAMESPACE` | Deployment detection via Loki K8s events |

Generate the encryption key once and keep it safe — encrypted keys cannot be recovered without it:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Deployment

Docker images and Kubernetes manifests are provided:

```bash
docker build \
  --build-arg VITE_API_BASE_URL=/api/v1 \
  -t <USERNAME>/popov-agent:latest \
  -f deploy/Dockerfile .

kubectl apply -f deploy/
```

See [`deploy/README.md`](deploy/README.md) for the full step-by-step guide (private registry secret, resource sizing, verification). Resource footprint is modest: requests `100m` CPU / `256Mi` RAM, limits `500m` / `512Mi`.

---

## Tech Stack

- **Backend:** Python 3.9+, FastAPI, LangGraph/LangChain, Motor (MongoDB), aiomysql (MySQL), pydantic-settings
- **AI:** pluggable LLM providers via `ChatOpenAI` interface (OpenAI / OpenRouter / Google Gemini / OpenCode Zen / Claude), embeddings (provider or local TF-IDF-style cosine), HDBSCAN clustering
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui, Zustand, TanStack Query, recharts, native WebSocket + SSE
- **Data:** MongoDB (primary store + audit/memory), optional MySQL for service log sources
- **Observability integrations:** Prometheus, Alertmanager, Grafana Tempo, Loki
- **Notifications:** Telegram Bot API, SMTP (email)
- **Deployment:** Docker, Kubernetes manifests (DigitalOcean-tested)

---

## Project Status

> 🚧 **Active development.** Popov powers incident response for its origin team's production services today, but it should be treated as an early-stage open-source project.

**Latest:** v0.2.1-rc293 — Full release notes: [v0.2.1-rc293](https://github.com/putra-asmarjoe/popov/releases/tag/v0.2.1-rc293).

Good fit today: small-to-medium engineering teams that already run Prometheus/Tempo/Loki, want automated triage and investigation, and are comfortable self-hosting and tolerating some churn. An observability stack is optional — Popov degrades gracefully without it. Not yet pitched for large enterprise fleets.

---

## 💡 Motivation

As a programmer and DevOps engineer, I deal with production incidents regularly —
chasing alerts across multiple tools, correlating logs, and managing follow-ups
manually. I needed something that could bring AI-assisted triage, ticketing, and
observability together in one self-hosted platform. Everything I found was either
too complex, too expensive, or required sending data to third-party clouds.

So I built Popov — drawing from years of hands-on experience managing
infrastructure and responding to incidents. It reflects the workflow I actually
wanted: fast, observable, and yours to own completely.

This is my contribution to the community. I hope it saves you the same headaches
it saved me.

If you find Popov useful, please consider giving it a ⭐ — it means a lot and
helps others discover the project.

---

## 🗣️ Discussion & Support

For questions, bug reports, or feature requests, please use:

- **[GitHub Issues](https://github.com/putra-asmarjoe/popov/issues)** — bug reports & feature requests
- **[GitHub Discussions](https://github.com/putra-asmarjoe/popov/discussions)** — general questions & ideas

> Please do not send support requests via email.

---

## License

Copyright © 2026 Putra Asmar Joe. Licensed under the
[Functional Source License, Version 1.1 (FSL-1.1-ALv2)](./LICENSE).

Free to self-host for personal and internal commercial use.
Offering Popov as a managed service to third parties is not permitted.

### ✅ Permitted Use (Free)

| Use Case | Status |
|---|---|
| Download, run, modify, fork | ✅ Free |
| Self-host for personal use | ✅ Free |
| Internal use at your company | ✅ Free |
| Commercial internal use | ✅ Free |
| Deploy for your own organization | ✅ Free |
| Build integrations on top of Popov | ✅ Free |

### ❌ Not Permitted

| Use Case | Status |
|---|---|
| Sell Popov itself | ❌ Not allowed |
| White-label Popov | ❌ Not allowed |
| Offer Popov as a hosted/managed service | ❌ Not allowed |
| Build a competing SaaS based on Popov | ❌ Not allowed |
| Remove Popov branding or license notices | ❌ Not allowed |
