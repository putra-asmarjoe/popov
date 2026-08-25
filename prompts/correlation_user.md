{{historical_block}}### GROUNDING DOC (Architecture & Decision Rules)
{{doc_context}}
{{knowledge_section}}
{{conversation_section}}
---
{{ticket_section}}
### 1. DATABASE LOGS SUMMARY
{{mongo_summary}}

---
### 2. METRICS & ALERTS SUMMARY
{{metrics_summary}}

---
### 2b. TRACE SUMMARY (Tempo — Aggregate Per Service)
Source: Tempo HTTP API (distributed trace aggregate).
{{trace_summary}}

---
{{span_section}}

---
{{health_section}}

---
Perform a complete correlation analysis. Format your answer exactly:

ROOT_CAUSE_ASSESSMENT: [service-fault / downstream / unknown]
SEVERITY: [INFO / WARNING / CRITICAL]

ANALYSIS SUMMARY:
<correlation between logs, metrics, and traces>

RECOMMENDED ACTIONS:
<safe remediation steps>

Reply in the same language the user used in their latest message.