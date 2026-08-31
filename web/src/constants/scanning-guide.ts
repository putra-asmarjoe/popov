export const SCANNING_GUIDE = `# SCANNING_GUIDE.md — Scan Project → Upload to Popov
> For coding agents. Run autonomously. Stop only at STEP 3 and STEP 4.

---

## STEP 1 — Scan the project

Read the codebase and extract facts. Do not guess — only write what you find.

Scan for these signals (use whatever tools work: grep, find, cat, read files directly):

**Identity**
- Service name, version, description — from \`package.json\` / \`pyproject.toml\`
- Language + framework (express / fastify / nestjs / fastapi / flask / django)
- Owner / team — from \`CODEOWNERS\`, \`README\`, \`package.json author\`

**Dependencies** — from \`package.json\` or \`requirements.txt\`
- DB driver: mongoose / prisma / typeorm / sequelize / sqlalchemy / pg / mysql2
- Cache: ioredis / redis
- Queue: bull / bullmq / amqplib / kafkajs / celery
- HTTP client: axios / got / httpx / requests
- Auth: jsonwebtoken / passport / express-jwt
- Rate limiter: express-rate-limit / rate-limiter-flexible
- Circuit breaker: opossum / cockatiel
- Retry: axios-retry / p-retry
- Observability: prom-client / @opentelemetry/sdk-node / winston / pino

**Routes & endpoints** — from route/controller/handler files
- HTTP method + path for every endpoint
- Which endpoints require auth

**Queue** — from worker/queue/consumer files
- Queue names, job names, concurrency, cron patterns
- Role: consumer / publisher / both
- AMQP: exchange names, routing keys
- Kafka: topic names, consumer group ID

**Outbound connections** — from HTTP client config files
- Base URLs (which external services are called)
- Timeout values (ms) per service
- Retry count and strategy (exponential / fixed)
- Circuit breaker settings (errorThreshold, resetTimeout)

**Data models** — from schema/model/entity files
- Model names, field names and types, indexes
- DB name (from env or connection string config)
- Joi/Zod validation shapes if present

**Error handling** — from error class files and try/catch blocks
- Custom error class names + HTTP status codes
- Which specific error types are caught (MongooseServerSelectionError, AxiosError, etc.)

**Observability**
- OTEL_SERVICE_NAME value
- Prometheus metric names (Counter, Histogram, Gauge)
- Log level config
- Health check path (/health / /ping / /ready)
- All env var keys from \`.env.example\` / \`.env.sample\`

---


## STEP 1.5 — Collect missing metadata *(before writing any file)*

Check if these two values were found during scanning:
- \`owner_team\` — from \`CODEOWNERS\`, \`README\`, \`package.json author\`, or any team/contact config
- \`escalation_primary\` — from \`README\`, \`.env.example\`, or any on-call/contact reference

If **not found**, ask the user — one question at a time, wait for answer before asking next:

\`\`\`
What is the team name responsible for <SERVICE_ID>?
\`\`\`
\`\`\`
Who is the primary on-call contact for <SERVICE_ID>?
\`\`\`

Store the answers. Use them in FILE 1 (\`owner_team\`) and Step 4 upload meta (\`escalation_primary\`).
Do not ask if already found in code — use the found value directly.

---
## STEP 2 — Write knowledge files

Check first:
\`\`\`bash
[ -d "./popov-knowledge-docs" ] && echo "EXISTS" || mkdir -p ./popov-knowledge-docs/{general,services,playbooks,schemas,connections,observability}
\`\`\`
If exists → ask user: re-scan and overwrite / use existing / abort.

**Format rules — critical for LLM embedding:**
- \`key: value\` pairs only. No markdown, no prose, no headers inside files.
- One logical fact per line. Inline related attributes on one line.
- Omit any field you didn't find. Never fabricate. Use \`[?]\` only if the value must exist but wasn't found in code.
- No filler words. Every token must be a fact, value, or decision signal.
- Only create a file if actual data was found for it.
- If one folder has 2 distinct data types (e.g. Mongoose models + Prisma schema), write 2 files with different names.

---

### FILE 1 — \`general/general_<SERVICE_ID>.md\`

\`\`\`
service_id: <id>  version: <v>
purpose: <one clause — what business problem this service solves>
lang: <nodejs|python>  variant: <typescript|javascript>  framework: <framework>
db: <db>  db_name: <name>  orm: <orm>
cache: <redis|none>  queue: <queue>  queue_role: <consumer|publisher|both|none>
payment: <midtrans|stripe|xendit|none>
auth: <jwt|passport|apikey|oauth2|none>  rate_limit: <N req/Xms|none>
retry: <true|false>  circuit_breaker: <true|false>
logging: <winston|pino|none>  log_level: <level>  health_path: <path|none>
otel_service_name: <name>  instrumented: <true|false>
owner_team: <team>
callers: <who calls this service>
calls: <what this service calls — services, dbs, caches>
\`\`\`

---

### FILE 2 — \`services/service_<SERVICE_ID>.md\`

\`\`\`
service_id: <id>

endpoints:
  <METHOD> <path>  auth:<yes|no>  rate_limited:<yes|no>  fn:<what it does>  fail:<impact if down>

critical_flows:
  <flow_name>: <step1>→<step2>→<step3>
    fail_<step>: <impact>

state_machine: <state1→state2→state3>
stuck_risk: fail at <step> leaves record in <state>
irreversible: <operation|none>
idempotent: <yes|no>  idempotency_key: <field|none>
\`\`\`

> Only include endpoints actually found. Omit state_machine block if none exists.

---

### FILE 3 — \`playbooks/playbook_<SERVICE_ID>.md\`
*Create only if custom error classes or specific catch patterns found.*

\`\`\`
service_id: <id>

errors:
  <ErrorClass>  cat:<EXPECTED|DOWNSTREAM|SERVICE-FAULT>  sev:<INFO|WARNING|CRITICAL>  action:<action>  restart:<YES|NO>

constraints:
  no_restart_if: DOWNSTREAM
  no_auto_action_if: data_inconsistency_risk
  no_scale_up_if: queue_consumer
  safe_to_restart_if: SERVICE-FAULT
\`\`\`

---

### FILE 4 — \`schemas/schema_<SERVICE_ID>.md\`
*Create only if model/schema/entity files found. Split into 2 files if 2 ORM sources exist.*

\`\`\`
service_id: <id>  db: <db>  db_name: <name>

model: <ModelName>  collection: <collection>
fields:
  <field>:<type>  <field>:<type>  <field>:ref:<OtherModel>
indexes: <field:1,unique>
queries:
  <query_name>: {<field>:<op>} sort:{<field>:<dir>} limit:<n>
\`\`\`

---

### FILE 5 — \`connections/connections_<SERVICE_ID>.md\`
*Create only if outbound calls or known inbound callers exist.*

\`\`\`
service_id: <id>

upstream:
  <caller>  proto:HTTP  endpoint:<METHOD /path>  impact_if_down:<impact>

downstream:
  <service>  proto:HTTP  base_url:<url>  timeout:<ms>  retry:<n>  fallback:<yes|no>  impact_if_down:<impact>
  mongodb    proto:TCP   timeout:<ms|none>  fallback:no  impact_if_down:all_writes_fail
  redis      proto:TCP   timeout:<ms|none>  fallback:<yes|no>  impact_if_down:<impact>

third_party:
  <name>  purpose:<payment|sms|email>  base_url:<url>  timeout:<ms>  rate_limit:<N/min|[?]>  retry:<n>  impact_if_down:<impact>

resilience:
  circuit_breaker:<yes|no>  library:<opossum|none>  error_threshold:<n%>  reset_timeout:<ms>
  retry_strategy:<exponential|fixed|none>  max_retries:<n>  retry_delay:<ms>
  timeout_chain: <svc_a:Xms>→<svc_b:Xms>→<total:Xms>

spof: <dependency with no fallback>
\`\`\`

---

### FILE 6 — \`observability/observability_<SERVICE_ID>.md\`

\`\`\`
service_id: <id>  otel_service_name: <name>  instrumented: <true|false>
logging: <lib>  log_level: <level>  health_path: <path|none>

promql:
  error_rate:   rate(http_server_requests_seconds_count{service="<name>",http_status_code=~"5.."}[5m])
  request_rate: rate(http_server_requests_seconds_count{service="<name>"}[5m])
  latency_p99:  histogram_quantile(0.99,rate(http_server_requests_seconds_bucket{service="<name>"}[5m]))
  pod_memory:   container_memory_usage_bytes{pod=~"<id>.*"}
  pod_cpu:      rate(container_cpu_usage_seconds_total{pod=~"<id>.*"}[5m])

custom_metrics:
  <metric_name>  type:<counter|histogram|gauge>  labels:<l1,l2>

baselines:
  error_rate:<1%  latency_p99:<500ms  memory_warning:80%
\`\`\`

> If not instrumented: write file with \`instrumented:false\`, omit promql block.

---

## STEP 3 — Confirm before upload *(STOP — wait for user)*

Display:
\`\`\`
SERVICE: <id>  LANG: <lang>/<variant>  FRAMEWORK: <fw>  DB: <db>  QUEUE: <queue>

Files to upload:
  general/general_<id>.md          → name: <id>_general
  services/service_<id>.md         → name: <id>_services
  playbooks/playbook_<id>.md       → name: <id>_playbooks      (if created)
  schemas/schema_<id>.md           → name: <id>_schemas        (if created)
  schemas/schema_<type>_<id>.md    → name: <id>_schemas_<type> (if split)
  connections/connections_<id>.md  → name: <id>_connections    (if created)
  observability/observability_<id>.md → name: <id>_observability

Total: <N> files
Upload now? (yes / no)
\`\`\`

---

## STEP 4 — Upload to Popov API

### 4.0 — Collect credentials *(STOP — ask user)*
\`\`\`
POPOV_HOST         e.g. http://localhost:8000
POPOV_TOKEN        e.g. pk_pub_...
POPOV_WORKSPACE_ID e.g. 6a93bb0d...
SERVICE_ID         confirm: <name from package.json>
\`\`\`

---

### 4.1 — Build manifest then upload

Build \`/tmp/popov_manifest.txt\` — one line per file that was actually created:
\`\`\`
# format: <name> <folder> <filepath> <criticality>
<SERVICE_ID>_general        general        ./popov-knowledge-docs/general/general_<id>.md          medium
<SERVICE_ID>_services       services       ./popov-knowledge-docs/services/service_<id>.md          high
<SERVICE_ID>_playbooks      playbooks      ./popov-knowledge-docs/playbooks/playbook_<id>.md        high
<SERVICE_ID>_schemas        schemas        ./popov-knowledge-docs/schemas/schema_<id>.md            medium
<SERVICE_ID>_connections    connections    ./popov-knowledge-docs/connections/connections_<id>.md   high
<SERVICE_ID>_observability  observability  ./popov-knowledge-docs/observability/observability_<id>.md medium
\`\`\`
For split files, add separate lines with distinct names:
\`\`\`
<SERVICE_ID>_schemas_mongoose  schemas  ./popov-knowledge-docs/schemas/schema_mongoose_<id>.md  medium
<SERVICE_ID>_schemas_prisma    schemas  ./popov-knowledge-docs/schemas/schema_prisma_<id>.md    medium
\`\`\`

Upload loop:
\`\`\`bash
# detect json escaper once
if command -v python3 &>/dev/null; then
  JSON_ESCAPE() { python3 -c "import json,sys; print(json.dumps(open(sys.argv[1]).read()))" "$1"; }
elif command -v jq &>/dev/null; then
  JSON_ESCAPE() { jq -Rs . < "$1"; }
fi

while IFS=' ' read -r NAME FOLDER FILEPATH CRIT; do
  [ -f "$FILEPATH" ] || { echo "SKIP $NAME"; continue; }
  CONTENT=$(JSON_ESCAPE "$FILEPATH")
  HTTP=$(curl -s -o /tmp/popov_resp.json -w "%{http_code}" -X POST \\
    -H "Content-Type: application/json" \\
    -H "Authorization: Bearer $POPOV_TOKEN" \\
    -d '{"name":"'"$NAME"'","service":"'"$SERVICE_ID"'","folder":"'"$FOLDER"'","workspace_id":"'"$POPOV_WORKSPACE_ID"'","content":'"$CONTENT"',"meta":{"service_id":"'"$SERVICE_ID"'","criticality":"'"$CRIT"'","owner_team":"'"$OWNER_TEAM"'","thresholds":{"error_rate_warning":0.05,"error_rate_critical":0.10,"response_time_warning":2000,"response_time_critical":5000},"escalation":{"primary":"'"$ESCALATION_PRIMARY"'","slack_channel":"#'"$SERVICE_ID"'-alerts"}}}' \\
    $POPOV_HOST/api/pub/v1/ingest/knowledge/service)
  EMBEDDED=$(python3 -c "import json; d=json.load(open('/tmp/popov_resp.json')); print(d.get('data',{}).get('embedded','?'))" 2>/dev/null)
  [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ] \\
    && echo "✓ $NAME  HTTP $HTTP  embedded:$EMBEDDED" \\
    || { echo "✗ $NAME  HTTP $HTTP"; cat /tmp/popov_resp.json; echo; echo "STOPPED — fix error above"; break; }
done < /tmp/popov_manifest.txt
\`\`\`

**\`name\` param is the API dedup key.** Same \`name\` = update existing entry. Different files in same folder must have different \`name\` values.

---

## Rules

- No fabricated data. Found data only.
- \`owner_team\` and \`escalation_primary\`: ask user if not in code, never guess.
- File not created = not in manifest = not uploaded. Keep manifest in sync.
- On any curl failure: show full response, stop, ask user.`
