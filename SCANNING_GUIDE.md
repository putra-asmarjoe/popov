# SCANNING_GUIDE.md
# Instructions for Claude Code: Scan a Service Project and Generate a Knowledge Base

> **Audience:** Claude Code running inside a service project terminal.
> Read this file first, then autonomously explore the entire project using tools
> (Read, LS, Glob, Bash) — do not wait for the user to paste anything.

---

## Purpose of the Output

The generated output serves as a **grounding document / knowledge base** for an
**Incident Response Agent** (built with LangGraph). The agent reads these files to:

- Understand **what the service does from a business perspective** — not just technically
- Assess **user/business impact** when a specific endpoint fails
- Decide whether to auto-remediate or escalate to a human
- Know who to contact during an incident

This is not standard technical documentation. It is a **business mind-map + AI decision
instructions**. It must answer: *"If this endpoint errors, who is affected and what are
the business consequences?"*

The output is also read by **Observability Agents** (Metrics Agent, Trace Agent,
Correlation Agent), which need:
- Accurate **PromQL queries** to monitor this service in Prometheus
- The **label and metric names** used by this service (for precise queries)
- **Thresholds** to interpret whether a metric value is normal or anomalous

---

## EXECUTION PROTOCOL (follow this order — do not skip steps)

### PHASE 1 — Orientation: Understand the Root Project

```bash
ls -la
cat package.json
cat .env.example 2>/dev/null || cat .env.sample 2>/dev/null || echo "no .env.example"
cat README.md 2>/dev/null || echo "no README"
```

---

### PHASE 2 — Structure Mapping: Find Key Files

```bash
# 2-level folder structure (excluding noise)
find . -maxdepth 2 -not -path '*/node_modules/*' -not -path '*/.git/*' \
       -not -path '*/.next/*' -not -path '*/dist/*' -not -path '*/build/*' | sort

# Main entrypoint
ls index.js app.js server.js src/index.js src/app.js src/server.js src/main.js main.js 2>/dev/null

# Route/controller files
find . -not -path '*/node_modules/*' \
       \( -path '*/routes/*' -o -path '*/controllers/*' -o -path '*/router/*' \) \
       -name "*.js" | sort

# DB/external service connection files
find . -not -path '*/node_modules/*' \
       \( -path '*/config/*' -o -path '*/db/*' -o -path '*/database/*' \
          -o -path '*/connections/*' -o -path '*/services/*' \) \
       -name "*.js" | sort

# Model/schema files
find . -not -path '*/node_modules/*' \
       \( -path '*/models/*' -o -path '*/schemas/*' -o -path '*/entities/*' \) \
       -name "*.js" | sort

# Middleware and job/worker files
find . -not -path '*/node_modules/*' \
       \( -path '*/middleware/*' -o -path '*/middlewares/*' \
          -o -path '*/jobs/*' -o -path '*/workers/*' -o -path '*/queues/*' \) \
       -name "*.js" | sort
```

---

### PHASE 3 — Technical Reading: Read Key File Contents

> ⚠️ **This phase is different from Phase 2.**
> Phase 2 only lists files. Phase 3 opens and reads each one.
> Do not skip this phase even if files were found in Phase 2 —
> analysis cannot proceed without reading the contents.

```bash
cat src/index.js   # adjust to Phase 2 results

# DB connection file
grep -rl "mongoose\|createConnection\|pg.Pool\|mysql.createConnection\|redis.createClient" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | head -5
# then: cat <found files>

# Error handling patterns
grep -rn "throw new\|catch.*err\|console.error\|logger.error\|winston\|pino" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | head -40

# External API / payment / third-party integrations
grep -rn "axios\|fetch\|got\|request\|midtrans\|stripe\|xendit\|twilio\|sendgrid" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | head -20

# Timeout and retry patterns
grep -rn "timeout\|retry\|ETIMEDOUT\|ECONNREFUSED\|ENOTFOUND" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | head -20
```

---

### PHASE 3B — Business Logic Reading: Most Critical Phase

> **Why this phase matters:** Technical documentation can be inferred from
> package.json. But to produce a grounding document useful to an AI agent,
> Claude must understand *what happens from a business perspective* in each
> code flow — not just function names and dependencies.
>
> ⚠️ **This phase has 5 sub-steps. Each must be completed and checked off
> separately. Do not combine them into a single task.**

**[ ] 3B.1 — Read ALL route files one by one**

```bash
cat <path/to/each/route.js>
```

For each route file, answer:
- What HTTP methods + paths are defined?
- What middleware is applied? (auth? rate limit? validator?)
- Which controller/handler is called per endpoint?

---

**[ ] 3B.2 — Read each controller/handler**

```bash
cat <path/to/controller.js>
```

Extract the **step-by-step business flow** for each key endpoint:

```
Example expected output:

POST /api/orders/checkout
  Step 1: Validate payload → if failed: 400 Bad Request
  Step 2: Check stock via inventory-service HTTP → if failed: order not created
  Step 3: Save order to MongoDB status "pending" → if failed: rollback
  Step 4: Charge Midtrans → if timeout: order stuck "pending"
  Step 5: Update status "confirmed" → if failed: data inconsistency (paid but still pending)
  Step 6: Publish event to RabbitMQ → if failed: notification not sent
```

---

**[ ] 3B.3 — Read model/schema files**

```bash
cat <path/to/each/model.js>
```

Extract:
- MongoDB collection name (from `mongoose.model(...)`)
- `required` fields → potential validation error sources
- Status/state fields that change → identify state machines and stuck risks

---

**[ ] 3B.4 — Read service/integration files**

```bash
cat <path/to/services/*.js>
```

For each file, extract:
- Which service/API is called?
- Is there a retry? How many times? What timeout (ms)?
- Is there a fallback on failure, or does it throw immediately?

---

**[ ] 3B.5 — Read auth/validator middleware**

```bash
cat <path/to/middleware/auth.js>
cat <path/to/middleware/validator.js>
```

Extract:
- Which endpoints require authentication vs. are public?
- What error is returned for invalid/expired tokens?
- Is there rate limiting? What are the limits?

---

### PHASE 3C — Service Connectivity Mapping (K8s Multi-Service)

> In a microservice environment, errors in one service often originate from
> an upstream caller or a downstream dependency. The AI agent needs this
> connection map to answer: *"Error in service A — is A broken, or is B
> (which A calls) down?"*
>
> ⚠️ **5 sub-steps — each must be completed separately.**

**[ ] 3C.1 — Scan all references to other services in the code**

```bash
grep -rn "http://\|https://\|process.env\." \
     --include="*.js" . 2>/dev/null | grep -v node_modules \
     | grep -i "service\|svc\|internal\|host\|url\|endpoint\|base" | head -40

grep -rn "process\.env\." --include="*.js" . 2>/dev/null \
     | grep -v node_modules \
     | grep -iE "(url|host|endpoint|service|svc|addr|base)" | head -30

grep -rn "baseURL\|baseUrl\|create({" --include="*.js" . 2>/dev/null \
     | grep -v node_modules | head -20
```

**[ ] 3C.2 — Read config and environment files**

```bash
find . -path '*/config/*' -name "*.js" -not -path '*/node_modules/*' | xargs cat 2>/dev/null

grep -rl "axios.create\|got.extend\|new HttpService\|createClient\|grpc" \
     --include="*.js" . 2>/dev/null | grep -v node_modules
# then: cat <found files>

grep -iE "^[A-Z_]*(URL|HOST|ENDPOINT|SERVICE|SVC|ADDR|BASE|PORT)[A-Z_]*=" \
     .env.example 2>/dev/null || \
grep -iE "^[A-Z_]*(URL|HOST|ENDPOINT|SERVICE|SVC|ADDR|BASE|PORT)[A-Z_]*=" \
     .env.sample 2>/dev/null
```

**[ ] 3C.3 — Find and read K8s manifests / Docker config**

```bash
find . -not -path '*/node_modules/*' \
     \( -name "*.yaml" -o -name "*.yml" \) | grep -v ".github" | sort

find . -not -path '*/node_modules/*' \
     \( -name "*.yaml" -o -name "*.yml" \) | grep -v ".github" | xargs cat 2>/dev/null

cat docker-compose.yml 2>/dev/null || cat docker-compose.yaml 2>/dev/null || \
cat docker-compose.dev.yml 2>/dev/null || echo "no docker-compose"
```

**[ ] 3C.4 — Identify message queue patterns (publisher & consumer)**

```bash
grep -rn "publish\|emit\|send\|produce\|enqueue" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | grep -v "console\." | head -20

grep -rn "subscribe\|consume\|on(\|listen\|worker\|queue\.process" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | head -20

grep -rn "topic\|queue\|exchange\|channel\|routing.key\|subject" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | head -20

grep -rn "Listener\|Consumer\|\.subscribe\|\.consume" \
     --include="*.js" . 2>/dev/null | grep -v node_modules | wc -l
```

> ⚠️ **This result directly determines `auto_remediation_allowed` in FILE 1:**
>
> If this service is a **queue consumer** (listener/consumer/subscribe found):
> - `scale_up` → **MUST** be in `requires_human_approval`, **FORBIDDEN** in `auto_remediation_allowed`
> - Reason: scaling up a consumer means one event may be processed by 2 pods simultaneously → double processing → data duplication
>
> If this service is **pure HTTP** (no listener/consumer at all):
> - `scale_up` → **MAY** be in `auto_remediation_allowed`

**[ ] 3C.5 — Summarize data flow direction before writing output**

Before writing output, mentally fill in this table:

```
INCOMING (who calls this service):
  - From which service? → via which protocol? (HTTP/gRPC/event)
  - Which endpoint/topic is called?
  - What data comes in?

INTERNAL PROCESSING (what this service does):
  - Read/write to which database?
  - Read/write to which cache?

OUTGOING (who this service calls):
  - To which service? → via which protocol?
  - Which endpoint/topic is called?
  - What data goes out?
  - If failed: is there a fallback or is it blocking?

EXTERNAL (third-party outside the cluster):
  - Payment gateway, SMS, email, cloud storage, etc.
```

---

### PHASE 3D — Observability Mapping: Prometheus & OpenTelemetry

> The Metrics Agent and Trace Agent query Prometheus and Grafana Tempo during
> incidents. Accurate queries require knowing the metric names, label selectors,
> and trace attributes specific to this service — not generic queries that may
> not match.
>
> ⚠️ **4 sub-steps — each must be completed separately.**
>
> If the service does not use OpenTelemetry or Prometheus, skip this phase
> and mark `observability_instrumented: false` in FILE 1 output.

**[ ] 3D.1 — Detect OpenTelemetry instrumentation**

```bash
grep -i "opentelemetry\|otel\|jaeger\|zipkin\|tempo" package.json 2>/dev/null

find . -not -path '*/node_modules/*' \
       \( -name "instrumentation*" -o -name "tracing*" -o -name "telemetry*" \) \
       | grep -v node_modules | sort

find . -not -path '*/node_modules/*' \
       \( -name "instrumentation.ts" -o -name "instrumentation.js" \
          -o -name "tracing.ts" -o -name "tracing.js" \) | xargs cat 2>/dev/null

grep -rn "OTEL_SERVICE_NAME\|serviceName\|service.name\|resource.*service" \
     --include="*.js" --include="*.ts" --include="*.env*" . 2>/dev/null \
     | grep -v node_modules | head -10
```

Extract:
- OTel service name (may differ from package.json name)
- Whether all HTTP requests are auto-traced
- Any custom spans or attributes set
- Which exporter is used (OTLP/gRPC, OTLP/HTTP, Jaeger, Zipkin)

---

**[ ] 3D.2 — Detect Prometheus metrics**

```bash
grep -i "prom-client\|prometheus\|metrics\|@opentelemetry/exporter-prometheus" package.json 2>/dev/null

find . -not -path '*/node_modules/*' \
       \( -name "metrics*" -o -name "monitoring*" -o -name "prometheus*" \) \
       | grep -v node_modules | sort | xargs cat 2>/dev/null

grep -rn "new Counter\|new Histogram\|new Gauge\|createCounter\|createHistogram\|register\." \
     --include="*.js" --include="*.ts" . 2>/dev/null | grep -v node_modules | head -20

grep -rn "\.inc()\|\.observe(\|\.set(\|\.labels(" \
     --include="*.js" --include="*.ts" . 2>/dev/null | grep -v node_modules | head -20
```

Extract:
- Does the service expose a `/metrics` endpoint?
- What custom metrics are defined? (name and type: counter/histogram/gauge)
- What labels are used? (service, endpoint, status_code, method, etc.)

---

**[ ] 3D.3 — Identify metric labels and naming conventions**

```bash
grep -rn "labels:\|labelNames:\|{service:\|{method:\|{status:" \
     --include="*.js" --include="*.ts" . 2>/dev/null | grep -v node_modules | head -20

grep -rn "http.method\|http.status_code\|http.route\|http.target\|rpc.method" \
     --include="*.js" --include="*.ts" . 2>/dev/null | grep -v node_modules | head -10

grep -rn "metricName\|metric_name\|prefix\|namespace" \
     --include="*.js" --include="*.ts" . 2>/dev/null | grep -v node_modules | head -10
```

---

**[ ] 3D.4 — Determine the correct PromQL queries for this service**

Based on 3D.1–3D.3, determine the queries the Metrics Agent will use.
Priority: use metric names and labels that actually exist in this codebase.
If not found: use generic query templates with a note.

**With OTel auto-instrumentation (most common):**
```
error_rate:   rate(http_server_requests_seconds_count{service="<otel_service_name>",http_status_code=~"5.."}[5m])
request_rate: rate(http_server_requests_seconds_count{service="<otel_service_name>"}[5m])
latency_p99:  histogram_quantile(0.99, rate(http_server_requests_seconds_bucket{service="<otel_service_name>"}[5m]))
```

**With manual prom-client (use metric name from 3D.2):**
```
error_rate:   rate(<custom_metric_name>_total{status=~"5.."}[5m])
request_rate: rate(<custom_metric_name>_total[5m])
latency_p99:  histogram_quantile(0.99, rate(<custom_metric_name>_duration_seconds_bucket[5m]))
```

**No instrumentation:**
```
memory: container_memory_usage_bytes{pod=~"<service_id>.*"}
cpu:    rate(container_cpu_usage_seconds_total{pod=~"<service_id>.*"}[5m])
```

---

### PHASE 4 — Analysis: Answer All Questions Before Writing Output

**About the Service (Technical):**
- [ ] Service name from `package.json → name`
- [ ] Framework: express / fastify / koa / hapi
- [ ] Port and environment variables
- [ ] Logging library: winston / pino / morgan / console.log

**About Database & Dependencies:**
- [ ] Primary database and collection names (from model files)
- [ ] Is Redis used? For what? (cache / session / queue)
- [ ] Message queue? (bull/rabbitmq/kafka) — consumer or publisher?
- [ ] Payment gateway? (midtrans/stripe/xendit) → auto-escalate to `critical`
- [ ] Other third-parties? (twilio/firebase/aws/sendgrid)
- [ ] Internal services called via HTTP? (from axios/fetch)

**About Business Logic (required):**
- [ ] How many domains/resources does this service handle? (user, order, payment, etc.)
- [ ] For each key endpoint: what is the full business flow? (step 1 → step N)
- [ ] Which flows have the most failure points?
- [ ] Is there a state machine? (status changes from A → B → C)
  → If yes: errors mid-flow may leave data stuck in a particular state
- [ ] Are there irreversible operations? (e.g. charge payment gateway, send SMS/email)
- [ ] Who are the "users" of each endpoint? (end user / internal service / admin)
- [ ] If this service goes down for 5 minutes, which business processes stop?

**About Observability (from Phase 3D):**
- [ ] Does the service use OpenTelemetry? (auto/manual/none)
- [ ] OTel service name (`OTEL_SERVICE_NAME`) — may differ from package.json name
- [ ] Does the service expose `/metrics` for Prometheus?
- [ ] What custom metrics are defined? (name, type, labels)
- [ ] Correct label selectors for Prometheus queries?
- [ ] If no instrumentation: mark `observability_instrumented: false`

**About Service Connectivity (from Phase 3C — required):**
- [ ] Which internal services call this service? (upstream)
- [ ] Which internal services does this service call? (downstream)
- [ ] Which third-parties / external services are called?
- [ ] Communication protocols? (REST HTTP / gRPC / message queue / event)
- [ ] Is this service a publisher, consumer, or both in the message queue?
- [ ] Which topics/queues/exchanges are used?
- [ ] If a downstream connection fails — is there a fallback or does it error to the user?
- [ ] K8s service name / internal hostname for each connection?
- [ ] Is there a **single point of failure** (no fallback)?

**About Error Patterns:**
- [ ] Specific error messages thrown in the code? (from try-catch)
- [ ] Timeout values configured for external calls?
- [ ] Any errors already handled gracefully (no action needed)?
- [ ] Any errors that could cause data inconsistency?

> ⚠️ **REQUIRED: Classify every error into one of these 3 categories BEFORE writing output.**
> Wrong classification = wrong agent action.
>
> | Category | Characteristics | Agent Action | Severity |
> |---|---|---|---|
> | `EXPECTED` | Normal business rule: rate limit, not found, validation error, blacklist | No action | INFO |
> | `DOWNSTREAM` | Error from dependency: ECONNREFUSED, ETIMEDOUT, MongooseServerSelectionError, AMQPConnectionError | Check dependency pod — **DO NOT restart this service's pod** | WARNING / CRITICAL |
> | `SERVICE-FAULT` | Bug in this service: OOMKilled, unhandled exception, memory leak | restart_pod allowed | WARNING / CRITICAL |
>
> **Most commonly violated rules:**
> - `MongooseServerSelectionError` → always `DOWNSTREAM`, restarting this pod **does not help**
> - `ECONNREFUSED` → always `DOWNSTREAM`, check the target pod
> - `ETIMEDOUT` → always `DOWNSTREAM`, check latency/status of the target pod
> - `Request limit exceeded` → always `EXPECTED`, no action needed

---

### PHASE 5 — Criticality Determination and Final Analysis

> ⚠️ **This phase is analysis, not file writing.**
> Complete all analysis here first. Do not start writing files until
> Phase 5 is done and all Phase 4 questions are answered.
> File generation happens in Phase 6.

| Level | Criteria |
|---|---|
| `critical` | Payment involved, auth service, downtime blocks all users, or data loss risk |
| `high` | Core business flow, many dependent services, or state machine with important data |
| `medium` | Supporting service, has fallback, limited impact on some users |
| `low` | Background jobs, reporting, notifications, optional features |

**Signals from package.json that raise criticality:**
- `midtrans-client`, `stripe`, `xendit` → must be `critical`
- `jsonwebtoken`, `passport`, `bcrypt` → likely `critical`
- `bull`/`bullmq` → check if job is critical; if yes → `high`
- `mongoose` without Redis → more vulnerable, consider raising one level

**Signals from business logic (Phase 3B) that raise criticality:**
- Irreversible operations (charge, send email/SMS) → raise one level
- State machine with stuck risk → raise one level
- Endpoint called by another critical service → raise one level

**Default thresholds:**

| Criticality | warning | critical | time_window |
|---|---|---|---|
| critical | 2 | 5 | 15 min |
| high | 5 | 20 | 30 min |
| medium | 10 | 50 | 60 min |
| low | 20 | 100 | 60 min |

---

### PHASE 6 — File Generation: Write 5 Output Files

> ⚠️ **Do not start this phase until Phase 5 is complete.**
> You must have determined: service_id, criticality, all dependencies,
> all upstream/downstream connections, and all error patterns.
> Generate the 5 files below in order.

---

## OUTPUT FORMAT: 5 Files to Generate

> Save in `./incident-agent-docs/` inside the scanned project root.
> The user will move these to the `docs/` folder in the incident-agent project.
>
> Output folder structure:
> ```
> incident-agent-docs/
> ├── services/<service_id>.md               ← FILE 1: service doc + business logic
> ├── schemas/logs_<service_id>.md           ← FILE 2: MongoDB schema
> ├── playbooks/<service_id>_incidents.md    ← FILE 3: incident playbook
> ├── connections/<service_id>_connectivity.md ← FILE 4: K8s connectivity map
> └── observability/<service_id>_observability.md ← FILE 5: metrics & tracing
> ```

---

### FILE 1: `incident-agent-docs/services/<service_id>.md`

```markdown
---
id: <package.json name, replace - with _>
name: "<human readable name>"
owner_team: "[NEEDS MANUAL INPUT]"
criticality: <Phase 5 result>
status: active

collections:
  primary: logs_<service_id>
  secondary: []

thresholds:
  error_count_warning: <from Phase 5 table>
  error_count_critical: <from Phase 5 table>
  time_window_minutes: <from Phase 5 table>

auto_remediation_allowed:
  - restart_pod
  # ⚠️ STRICT RULE — read before adding more items:
  # DO NOT add scale_up if this service is a RabbitMQ/queue consumer
  # (detected in Phase 3C.4). Scaling up a consumer means one event can be
  # processed by 2 pods simultaneously → double processing → data corruption.
  # scale_up is only allowed here if the service is pure HTTP with no queue consumer.

requires_human_approval:
  - rollback_deployment
  - scale_up    # ← always here if there is a queue consumer (Phase 3C.4 result)
  - scale_down
  - modify_config
  # add irreversible operations found in Phase 3B

escalation:
  primary: "[NEEDS MANUAL INPUT]"
  secondary: "[NEEDS MANUAL INPUT]"
  slack_channel: "[NEEDS MANUAL INPUT]"

# ── Observability (from Phase 3D) ─────────────────────────────────────────────
observability_instrumented: true   # false if no OTel/Prometheus
otel_service_name: "<name in OTEL_SERVICE_NAME — may differ from id above>"

# PromQL queries for Metrics Agent — use labels that actually exist in the code
# If observability_instrumented = false: fill only pod-level metrics (memory/cpu)
prometheus_queries:
  error_rate: 'rate(http_server_requests_seconds_count{service="<otel_service_name>",http_status_code=~"5.."}[5m])'
  request_rate: 'rate(http_server_requests_seconds_count{service="<otel_service_name>"}[5m])'
  latency_p99: 'histogram_quantile(0.99, rate(http_server_requests_seconds_bucket{service="<otel_service_name>"}[5m]))'
  memory: 'container_memory_usage_bytes{pod=~"<service_id>.*"}'
  cpu: 'rate(container_cpu_usage_seconds_total{pod=~"<service_id>.*"}[5m])'
  # Add custom metrics from Phase 3D.2 if any:
  # <metric_name>: '<promql_query>'

# Baseline values for metric interpretation (fill if known, omit if unknown)
metric_baselines:
  error_rate_normal_pct: <normal percentage, e.g. 0.5>   # % error rate under normal conditions
  latency_p99_normal_ms: <normal value, e.g. 500>        # ms p99 latency under normal conditions
  # If unknown: delete both lines — Metrics Agent will skip interpretation and report raw values
---

## Description

<2–3 paragraphs:
1. What this service does — from routes + description + Phase 3B business logic
2. Who calls it and what it calls, and in what business context
3. Justification for the chosen criticality level based on concrete code findings>

## Architecture

<ASCII diagram showing:
- Who calls this service (upstream) at the top
- This service in the middle
- Database/cache/queue below
- External APIs / other services called on the right>

## Business Logic Map

> This is the core of the grounding document. The AI agent reads this
> to understand the business consequences of every error.

<For each main domain/resource handled by this service, write:>

### Domain: <DomainName> (e.g. Order, Payment, User)

**Main flow: <flow name>**
```
Step 1: <technical action> → <business purpose>
Step 2: <technical action> → <business purpose>
Step N: <technical action> → <business purpose>

If error at Step 2: <specific business consequence>
If error at Step 4: <specific business consequence>
```

**State machine (if applicable):**
```
[pending] → [confirmed] → [processing] → [completed]
                ↓
            [failed]

Stuck risk: if payment succeeds but status update fails,
order stays "pending" even though it was paid → user complaint
```

**Irreversible operations in this domain:**
- <List of operations that cannot be rolled back>

## Critical Dependencies

<For each dependency from package.json + Phase 3 grep results:
- **DependencyName** (type: database/cache/queue/payment-gateway/internal-service)
  - Used for: <its specific function in this business>
  - Impact if down: <concrete business consequence, not just technical>>

## Key Endpoints

<From Phase 3B.1 and 3B.2. Format:
`METHOD /path` — <business function, not just technical>
- Auth required: yes/no
- Called by: end user / internal service / admin
- Error consequence: <business impact if this endpoint fails>>

## Common Error Patterns

<From Phase 3 grep results + Phase 3B flow analysis:>

### N. `ErrorMessageOrErrorName`
- **Meaning:** technical explanation
- **Occurs in flow:** Step N of <flow name>
- **Business impact:** <who is affected and what concretely — e.g. "user cannot checkout">
- **Can data be inconsistent?** yes/no — <explanation if yes>
- **Category:** [EXPECTED / DOWNSTREAM / SERVICE-FAULT]

## Agent Decision Guide

> Explicit instructions for the AI agent. Format MUST be "If...then..."
> Each guide must include: condition → action → notification content → who to contact

**Based on error count:**

If error count < {error_count_warning} within {time_window_minutes} minutes:
→ Send INFO notification only, no action

If error count between {warning} and {critical}:
→ Send WARNING notification to {escalation.primary}
→ Monitor for the next X minutes

If error count >= {error_count_critical}:
→ Send CRITICAL notification to {escalation.primary} AND {escalation.secondary}
→ Execute: <action from auto_remediation_allowed>

**Based on error type (business logic aware):**

> ⚠️ MANDATORY RULES BEFORE WRITING PER-ERROR GUIDES:
>
> RULE A — Classify each error into one of 3 categories first, then write the action:
>
> [EXPECTED]      = normal business rule, NOT an incident
>                   e.g. "rate limit exceeded", "user not found", "validation error"
>                   → action: INFO only, no action
>
> [DOWNSTREAM]    = error from a dependency (DB down, API timeout, etc.)
>                   → action: DO NOT restart this service's pod, check downstream first
>
> [SERVICE-FAULT] = error in this service's own logic (bug, OOM, etc.)
>                   → action: restart_pod is allowed
>
> RULE B — For [DOWNSTREAM] errors (MongooseServerSelectionError, ECONNREFUSED, ETIMEDOUT):
> DO NOT instruct restarting this service's pod.
> Restart does not help if the problem is in the dependency.
> Instruct: check the relevant dependency pod first.
>
> RULE C — Valid severity values ONLY: INFO | WARNING | CRITICAL
> DO NOT use: HIGH, LOW, MEDIUM, ERROR, FATAL, or any other label.

<For each error pattern found, write a guide in this format:>

If error `<error name>` is detected [EXPECTED/DOWNSTREAM/SERVICE-FAULT]:
→ <action: based on category above>
→ Severity: INFO / WARNING / CRITICAL (choose one)
→ Notification must mention: <important business fields>
→ Reason: <why this action was chosen>

If error indicating data inconsistency is detected:
→ DO NOT take any automated action
→ IMMEDIATELY escalate to {escalation.primary} with label "DATA INCONSISTENCY RISK"
→ Include: <relevant transaction identifier fields>

## Sample MongoDB Log

<Realistic JSON reflecting:
- The logging library used (winston/pino/console)
- Domain-specific business fields from the model (order_id, user_id, etc.)
- Actual error messages that exist in the code (from grep try-catch)>

```json
{
  "_id": "ObjectId",
  "level": "error",
  "service": "<service_id>",
  "message": "<actual error message from code>",
  "timestamp": "ISODate",
  "trace_id": "string",
  "<business field from model>": "<example value>",
  "endpoint": "METHOD /path",
  "metadata": {
    "<additional context field>": "<value>"
  }
}
```
```

---

### FILE 2: `incident-agent-docs/schemas/logs_<service_id>.md`

```markdown
---
collection: logs_<service_id>
service_id: <service_id>
database: incidents_db
estimated_size: "[NEEDS MANUAL INPUT]"
retention_days: 90
indexes:
  - field: timestamp, order: desc
  - field: level
  - field: trace_id
---

## Collection Description

Stores logs from <service name>. Written by <logging library>.
Logs cover: <which business domains are logged — e.g. order events, auth attempts, etc.>

## Document Schema

<Standard fields + business-specific fields from models found in Phase 3B.3>

```
{
  _id:              ObjectId   — auto-generated
  level:            string     — "info" | "warn" | "error" | "critical"
  service:          string     — always "<service_id>"
  message:          string     — main error message
  timestamp:        ISODate    — log time (UTC)
  trace_id:         string     — correlation ID
  endpoint:         string     — "METHOD /path"
  <business field 1>: <type>  — <description from model>
  <business field 2>: <type>  — <description from model>
  metadata:         object     — additional context, varies per error type
}
```

## Useful Queries for the Agent

**Latest errors:**
```json
{ "level": { "$in": ["error", "critical"] } }
```
sort: `{ "timestamp": -1 }`, limit: 20

**Detect potential data inconsistency (adapt to the state machine found):**
```json
{
  "message": { "$regex": "<pattern indicating stuck state>", "$options": "i" },
  "level": "error"
}
```

**Errors by specific endpoint:**
```json
{
  "endpoint": "POST /<critical endpoint path>",
  "level": "error"
}
```

**Errors related to <main business domain>:**
```json
{ "<business_id_field>": { "$exists": true }, "level": "error" }
```
```

---

### FILE 3: `incident-agent-docs/playbooks/<service_id>_incidents.md`

```markdown
---
id: <service_id>_incidents
title: "Incident Guide: <Service Name>"
applies_to_services: [<service_id>]
severity_default: warning
tags: [<business domains from Phase 3B — e.g. order, payment, auth>]
---

## Incident Map

> ⚠️ MANDATORY RULES for this table:
>
> **Category** column must be one of:
>   - `EXPECTED`      → normal business rule, NOT an incident (rate limit, validation, not found)
>   - `DOWNSTREAM`    → error from dependency (DB, API timeout, ECONNREFUSED)
>   - `SERVICE-FAULT` → bug or issue in this service itself
>
> **Severity** column ONLY: `INFO` | `WARNING` | `CRITICAL`
>   DO NOT use: HIGH, LOW, MEDIUM, ERROR, or other labels
>
> **Agent Action** must follow the category:
>   - EXPECTED      → "No action — expected behavior"
>   - DOWNSTREAM    → "Check pod <downstream>, DO NOT restart this service's pod"
>   - SERVICE-FAULT → "restart_pod allowed"

<Fill from Phase 3B analysis — one row per error type found>

| Error | Category | Occurs in Flow | Severity | Business Impact | Agent Action | Owner |
|---|---|---|---|---|---|---|
| `<error message>` | EXPECTED/DOWNSTREAM/SERVICE-FAULT | <flow name/step> | INFO/WARNING/CRITICAL | <concrete impact> | <action per category> | <who> |

## Escalation Procedure

<When to escalate, who to contact, and what information must be included>

Escalate to {escalation.primary} if:
- <condition 1>
- <condition 2>

Also escalate to {escalation.secondary} if:
- <more serious condition>

Information REQUIRED in every escalation:
- <important business fields, e.g. order_id, transaction_id, user_id>
- Error count and time window
- Business step where the error occurred

## What the Agent MUST NOT Do

<Minimum 3 items, specific to the business domain from Phase 3B>

- DO NOT perform direct database operations on the <critical collection name> collection
- DO NOT restart the pod if the error indicates <specific condition — e.g. data inconsistency>
- DO NOT ignore errors at step <N> of <flow name> — always escalate
- <Add based on irreversible operations found in Phase 3B>

## Telegram Message Template

```
{emoji} *[{SEVERITY}]* Incident in `{service_id}`

*Affected flow:* <business flow name>
*Error:* `{error_message}`
*Count:* {count} errors in {window} minutes

*Business context:*
- {business_field_1}: {value}
- {business_field_2}: {value}

*Action taken:* {action_taken}
*Recommendation:* {recommendation}

*Escalation:* {escalation.primary}
```
```

---

### FILE 4: `incident-agent-docs/connections/<service_id>_connectivity.md`

> This file is the **service connectivity map** in the K8s cluster. The AI agent
> reads this first during an incident to determine whether the root cause is in
> this service, its upstream, or its downstream.

```markdown
---
id: <service_id>_connectivity
service_id: <service_id>
service_name: "<human readable name>"
k8s_service_name: "<K8s service name, e.g. order-service or order-svc>"
k8s_namespace: "<namespace — e.g. production, default>"
protocol: http   # http | grpc | mixed
last_updated: "<date this document was generated>"
---

## Data Flow Overview

<ASCII diagram showing the COMPLETE data flow to and from this service.
Must be readable at a glance in 10 seconds.>

```
                    [upstream-service-1]
                           │ HTTP POST /api/orders
                           ▼
[external-client] ──► [THIS SERVICE: <service_id>]
                           │              │
                    ┌──────┘              └──────────────┐
                    ▼                                     ▼
             [MongoDB]                          [downstream-service-1]
             [Redis]                            via HTTP GET /api/users
                                                         │
                                                         ▼
                                               [payment-gateway.com]
                                               via HTTPS POST /charge
```

## Upstream — Who Calls This Service

<For each upstream, write one block:>

### <upstream-service-name>

| Field | Detail |
|---|---|
| Service ID | `<upstream_service_id>` |
| K8s hostname | `<k8s-svc-name>.<namespace>.svc.cluster.local` |
| Protocol | HTTP / gRPC / Event |
| Endpoint called | `METHOD /path` |
| Data sent | <payload summary> |
| Frequency | <estimate: per user request / per minute / batch> |
| If this service is down | <what happens upstream — what error do they get> |

### [Unknown — can be called from anywhere]
> Use this if the service is a public-facing API.
> Means it can be called from the frontend, mobile app, or any service.

---

## Downstream — Services Called by This Service

<For each downstream, write one block. This is most important for
root cause analysis — errors here often appear as errors in this service.>

### <downstream-service-name>

| Field | Detail |
|---|---|
| Service ID | `<downstream_service_id>` |
| K8s hostname | `<k8s-svc-name>.<namespace>.svc.cluster.local` |
| Protocol | HTTP / gRPC / Event |
| Endpoint called | `METHOD /path` |
| Used for | <business function — e.g. "validate stock before checkout"> |
| Timeout configured | <value in ms if found in code, or NOT FOUND> |
| Retry? | yes (N times) / no |
| Fallback if failed? | yes — <what the fallback is> / no — error propagates to user |
| If DOWN, impact | <consequence to this service's business flow> |
| Error in log | `<error message visible in this service's log when downstream is down>` |

---

## External / Third-Party — Outside the K8s Cluster

### <third-party-name> (e.g. Midtrans, Twilio, AWS S3)

| Field | Detail |
|---|---|
| Type | payment-gateway / sms-provider / email / cloud-storage / cdn / other |
| URL / endpoint | `<base URL from code or .env>` |
| Used for | <business function> |
| Timeout | <value in ms or NOT FOUND> |
| Retry? | yes (N times) / no |
| Fallback if failed? | yes — <what> / no — operation fails |
| Status page | `<provider status page URL if known>` |
| If DOWN, impact | <concrete business consequence> |

---

## Message Queue / Events

<Fill this section only if the service uses a message queue. Skip if not.>

### As Publisher (sending events)

| Topic / Queue / Exchange | Sent when | Expected consumer | If publish fails |
|---|---|---|---|
| `<topic-name>` | <business condition> | `<consumer-service-id>` | <consequence> |

### As Consumer (receiving events)

| Topic / Queue / Exchange | Received from | Action taken | If processing fails |
|---|---|---|---|
| `<topic-name>` | `<publisher-service-id>` | <business action> | <dead letter / retry / drop> |

---

## Database & Storage

| Dependency | Type | Host / K8s Service | Database / Collection | Access |
|---|---|---|---|---|
| `<name>` | MongoDB / Redis / PostgreSQL / S3 / etc. | `<hostname>` | `<db/collection name>` | read-write / read-only |

---

## Dependency Graph (Text)

```
<service_id> DEPENDS ON:
  ├── [CRITICAL] <downstream-service-1>   → HTTP, no fallback → if down: user cannot <action>
  ├── [CRITICAL] <primary-database>       → MongoDB, no fallback → if down: all operations fail
  ├── [DEGRADED] <cache-service>          → Redis, has DB fallback → if down: latency 3x higher
  └── [CRITICAL] <payment-gateway>        → HTTPS external, no fallback → if down: checkout fails

<service_id> IS USED BY:
  ├── <upstream-service-1>               → calls endpoint POST /<path>
  └── <upstream-service-2>               → calls endpoint GET /<path>

<service_id> PUBLISHES EVENTS TO:
  └── <consumer-service>                 → via topic <topic-name>

<service_id> CONSUMES EVENTS FROM:
  └── <publisher-service>                → via topic <topic-name>
```

---

## Root Cause Diagnosis Guide for the Agent

> When an error occurs in this service, use this sequence to determine
> whether the problem is in this service or a dependency.

### Step 1 — Check if the error originates from downstream

**If** the log contains any of these keywords, the problem likely lies in a downstream:
```
ECONNREFUSED → <downstream_service_id> is unreachable
ETIMEDOUT    → <downstream_service_id> or <payment_gateway> is slow/down
503          → <downstream_service_id> is overloaded
ENOTFOUND    → DNS issue — K8s service discovery is broken
```

**Action:** Before restarting this service's pod, first check the status of
`<downstream_service_id>` and `<database>`.

### Step 2 — Distinguish: error in this service vs. propagated from downstream?

| If log shows | Likely root cause | Check first |
|---|---|---|
| `ECONNREFUSED` to `<downstream-hostname>` | `<downstream-service>` is down | Check `<downstream-service>` pod |
| `MongooseServerSelectionError` | MongoDB unreachable | Check MongoDB pod / connection |
| `ETIMEDOUT` to `<payment-gateway-url>` | Payment provider down | Check `<status-page-url>` |
| Business logic error (validation, not found) | Bug in this service | Read the stack trace |

### Step 3 — Determine if this is a cascading failure

**If** this service is erroring AND at the same time `<downstream-service>` is also erroring:
→ Likely a **cascading failure** — `<downstream-service>` is the root cause
→ Focus fixes on `<downstream-service>` first
→ This service will recover on its own once `<downstream-service>` is healthy

**If** this service is erroring but `<downstream-service>` is healthy:
→ Problem is in this service itself
→ Check: memory, CPU, code bug, or configuration change

---

## Operational Notes

<Fill if there are specific findings from the code — e.g.:>
- No circuit breaker — if `<downstream>` is slow, requests will queue up
- Timeout to `<payment-gateway>` is configured at X ms — verify it is sufficient
- `[NEEDS MANUAL INPUT]` — K8s service name and namespace need to be confirmed
```

---

### FILE 5: `incident-agent-docs/observability/<service_id>_observability.md`

> This file is read exclusively by the **Metrics Agent** and **Trace Agent** during
> incidents. It contains queries calibrated for this service — not generic queries.
> If Phase 3D shows the service has no instrumentation, this file is still created
> but with `observability_instrumented: false` and only pod-level metrics.

```markdown
---
id: <service_id>_observability
service_id: <service_id>
otel_service_name: "<name in OTEL_SERVICE_NAME>"
observability_instrumented: true/false
metrics_endpoint: "<url>/metrics or N/A"
last_validated: "<date — needs revalidation if metrics change>"
---

## Observability Status

| Component | Status | Notes |
|---|---|---|
| OpenTelemetry | active/inactive | <library used or "not found"> |
| Prometheus metrics | active/inactive | <has /metrics endpoint or not> |
| Custom metrics | yes/no | <custom metric names if any> |
| Trace sampling | <value or "unknown"> | <sampling rate if configured> |

## PromQL Queries (calibrated for this service)

> Use these queries directly — already adjusted for the labels in this codebase.
> Replace `<window>` with the desired time range (e.g. 5m, 15m, 1h).

**Error rate:**
```promql
<query from Phase 3D.4>
```

**Request rate (total):**
```promql
<query from Phase 3D.4>
```

**Latency p99:**
```promql
<query from Phase 3D.4>
```

**Pod memory usage:**
```promql
<query from Phase 3D.4>
```

**Pod CPU usage:**
```promql
<query from Phase 3D.4>
```

<If there are custom metrics from Phase 3D.2, add them here:>

**<custom metric name>:**
```promql
<query>
```

## Metric Interpretation

> Use this table to determine whether a value from Prometheus is normal,
> needs monitoring, or indicates an incident.

| Metric | Normal | Warning | Critical |
|---|---|---|---|
| Error rate | < <value>% | <value>% – <value>% | > <value>% |
| Latency p99 | < <value>ms | <value>ms – <value>ms | > <value>ms |
| Memory | < <value>% of limit | <value>% – <value>% | > <value>% |
| CPU | < <value>% | <value>% – <value>% | > <value>% |

> If normal values are unknown: fill the Normal column with "NEEDS MANUAL INPUT"
> and the Metrics Agent will skip interpretation and report raw numbers only.

## Trace Attributes for Tempo Search

> Use these attributes when the Trace Agent searches in Grafana Tempo.

```
service.name = "<otel_service_name>"
# Custom attributes set in code (from Phase 3D.1):
<attribute_name> = "<example value>"
```

## Calibration Notes

<Fill if there are specifics to note when querying:>
- Which labels are mandatory in every query to avoid false positives
- Which metrics are not yet configured and need to be added to the code
- [NEEDS MANUAL INPUT] — validate queries with the platform/ops team
```

---

## Writing Rules

1. **Do not fabricate** — if not found in the code, write `[NEEDS MANUAL INPUT: reason]`
2. **Business Logic Map is required** — this is what distinguishes a grounding document from ordinary documentation
3. **"Agent Decision Guide" must use "If...then..." format** — no ambiguity allowed
4. **Every error must have a "Business Impact"** — not just a technical explanation
5. **Irreversible operations must appear in `requires_human_approval`** and "What MUST NOT Be Done"
6. **FILE 4 connectivity is required** — without it the AI agent cannot distinguish root cause from cascading failure
7. **In FILE 4, every dependency must be labeled CRITICAL or DEGRADED** in the Dependency Graph
8. **FILE 5 observability is required** — even if the service has no instrumentation (fill `observability_instrumented: false`).
   The Metrics Agent reads FILE 5 to know which queries to use — without it, it will use generic queries that may not match.
9. **PromQL queries in FILE 5 must be calibrated** — not generic copy-paste. Verify correct labels from Phase 3D.
10. **After all 5 files are done**, write the following summary:

```
=== SCANNING SUMMARY ===

Service ID    : <service_id>
Criticality   : <level>
Justification : <one-sentence reason>

CONNECTIONS FOUND:
  Upstream    : <list of services that call this one>
  Downstream  : <list of services called, with CRITICAL/DEGRADED labels>
  External    : <list of third-parties>
  Queue       : <publishes to / consumes from>

SINGLE POINTS OF FAILURE:
  <list of dependencies without fallback — these are the most dangerous>

FIELDS NEEDING MANUAL INPUT:
  - owner_team
  - escalation.primary, escalation.secondary, slack_channel
  - k8s_service_name, k8s_namespace (confirm with ops team)
  - <other fields that cannot be found from code>

ADD TO incident-agent config/settings.py:
  "<service_id>": "logs_<service_id>",

OBSERVABILITY STATUS:
  OTel instrumented: yes/no
  OTel service name: <name>
  Prometheus metrics: present/not present
  Queries calibrated: yes/no (if no: using generic defaults)

FILES GENERATED:
  incident-agent-docs/services/<service_id>.md
  incident-agent-docs/schemas/logs_<service_id>.md
  incident-agent-docs/playbooks/<service_id>_incidents.md
  incident-agent-docs/connections/<service_id>_connectivity.md
  incident-agent-docs/observability/<service_id>_observability.md
```

---

## Pre-Submission Checklist

**Scanning — verify each phase is complete before proceeding:**
- [ ] PHASE 1 ✓ — ls, package.json, .env.example, README all read
- [ ] PHASE 2 ✓ — all route, controller, model, middleware, job files listed
- [ ] PHASE 3 ✓ — entrypoint, DB connection, error handler, external API contents all read
- [ ] PHASE 3B.1 ✓ — all route files read
- [ ] PHASE 3B.2 ✓ — all controllers read, step-by-step business flows extracted
- [ ] PHASE 3B.3 ✓ — all models read, state machines identified
- [ ] PHASE 3B.4 ✓ — all service/integration files read, retry & fallback documented
- [ ] PHASE 3B.5 ✓ — auth & validator middleware read
- [ ] PHASE 3C.1 ✓ — all URLs & env vars to other services grepped
- [ ] PHASE 3C.2 ✓ — config files & axios instances read
- [ ] PHASE 3C.3 ✓ — K8s YAML & docker-compose read (if present)
- [ ] PHASE 3C.4 ✓ — queue publishers & consumers identified
- [ ] PHASE 3C.5 ✓ — INCOMING/INTERNAL/OUTGOING/EXTERNAL table filled
- [ ] PHASE 3D.1 ✓ — OTel instrumentation detected (present/absent, which library)
- [ ] PHASE 3D.2 ✓ — Prometheus metrics detected (custom metrics, labels)
- [ ] PHASE 3D.3 ✓ — label naming convention identified
- [ ] PHASE 3D.4 ✓ — PromQL queries determined (calibrated or generic with note)
- [ ] PHASE 4 ✓ — all analysis questions answered (including observability)
- [ ] PHASE 5 ✓ — criticality determined with justification
- [ ] PHASE 6 begins only after all phases above are complete

**FILE 1 — Service Doc:**
- [ ] `id` uses underscores, not dashes
- [ ] Business Logic Map has step-by-step flows, not just endpoint names
- [ ] State machine documented if found (including stuck risk)
- [ ] Every error pattern has a concrete "Business Impact"
- [ ] Irreversible operations are in `requires_human_approval`
- [ ] "Agent Decision Guide" uses "If...then..." format with concrete actions
- [ ] ✅ GUARDRAIL: `scale_up` is NOT in `auto_remediation_allowed` if the service has a queue consumer
- [ ] ✅ GUARDRAIL: Every error is classified [EXPECTED] / [DOWNSTREAM] / [SERVICE-FAULT]
- [ ] ✅ GUARDRAIL: [DOWNSTREAM] errors (MongooseServerSelectionError, ECONNREFUSED, ETIMEDOUT) do NOT instruct restarting this service's pod
- [ ] ✅ GUARDRAIL: [EXPECTED] errors (rate limit, validation, not found) are INFO only — no action
- [ ] ✅ GUARDRAIL: All severities use only INFO / WARNING / CRITICAL

**FILE 2 — Schema:**
- [ ] `collections.primary` = `collection` in FILE 2
- [ ] Sample log uses error messages that actually exist in the code
- [ ] Business-specific fields from models are included in the schema

**FILE 3 — Playbook:**
- [ ] Incident Map table has "Category" and "Occurs in Flow" columns
- [ ] Category column values: EXPECTED / DOWNSTREAM / SERVICE-FAULT (no others)
- [ ] Severity column values ONLY: INFO / WARNING / CRITICAL — no HIGH, LOW, MEDIUM, ERROR
- [ ] EXPECTED errors (rate limit, validation, blacklist) → Agent Action: "No action"
- [ ] DOWNSTREAM errors → Agent Action: "Check pod <name>, DO NOT restart this service's pod"
- [ ] "What the Agent MUST NOT Do" has at least 3 specific items

**FILE 4 — Connectivity:**
- [ ] ASCII data flow diagram shows upstream + downstream + external
- [ ] Every downstream has a CRITICAL / DEGRADED label
- [ ] Single points of failure are identified
- [ ] "Root Cause Diagnosis Guide" uses concrete service names
- [ ] "Distinguish: error in this service vs. propagation" table is filled

**FILE 5 — Observability:**
- [ ] `observability_instrumented` is filled: true if OTel/Prometheus is present, false otherwise
- [ ] `otel_service_name` is filled (check OTEL_SERVICE_NAME in code/env — may differ from id)
- [ ] PromQL queries calibrated from labels that actually exist in the code (Phase 3D.3)
- [ ] If generic queries are used: explicit note that manual validation is needed
- [ ] Metric interpretation table is filled (or labeled NEEDS MANUAL INPUT)
- [ ] Trace attributes for Tempo search are filled
- [ ] ✅ GUARDRAIL: Do not fill metric baselines with values not evidenced in the code

**Summary:**
- [ ] All empty fields are marked `[NEEDS MANUAL INPUT]`
- [ ] `id` is consistent across all five files
- [ ] Scanning summary is written in the format above
- [ ] `service_collection_map.json` config entry is present — `id` is consistent across all files
- [ ] FILE 5 observability exists and `otel_service_name` is consistent with FILE 1
- [ ] Summary includes OBSERVABILITY STATUS (OTel instrumented, queries calibrated)
