import operator
from typing import TypedDict, Optional, List, Dict, Any, Annotated


def _merge_raw_documents(a: List[Any], b: Any) -> List[Any]:
    """Reducer untuk raw_documents agar fan-out paralel (mongo+span) tidak conflict.
    LangGraph parallel bisa kirim tuple(list1, list2) sebagai single update.
    """
    if isinstance(b, tuple):
        res = list(a)
        for item in b:
            if isinstance(item, list):
                res.extend(item)
            elif item is not None:
                res.append(item)
        return res
    if isinstance(b, list):
        return a + b
    if b is None:
        return a
    return a + [b]


class AgentState(TypedDict):
    # Input dari API
    intent: str                        # e.g. "error pada <nama-service>"
    service_name: str                  # e.g. "<nama_service>"
    collection_name: str               # resolved oleh supervisor

    # Audit / Request log
    request_id: Optional[str]          # unique id per request
    incoming_date: Optional[str]       # ISO timestamp saat request masuk
    sender: Optional[dict]             # {channel, id, username, name, chat_id, ip}
    message_raw: str                   # teks asli request/intent
    agents_visited: Annotated[List[str], operator.add]  # urutan agent yang dieksekusi (reducer concat untuk fan-out)

    # Hasil MongoDB / Database agent
    raw_documents: Annotated[List[Any], _merge_raw_documents]  # Annotated agar span+mongo paralel tidak conflict (handle tuple dari fan-out)
    query_used: dict                   # query yang dipakai (untuk debug)
    mongo_summary: Optional[str]       # ringkasan log database untuk LLM
    mongo_available: Optional[bool]    # status konektivitas database

    # Hasil Observability (Metrics, Trace, Correlation)
    metrics_data: Optional[dict]       # raw data dari Prometheus
    metrics_summary: Optional[str]     # ringkasan metrics untuk LLM
    metrics_available: Optional[bool]  # status konektivitas Prometheus
    trace_data: Optional[dict]         # raw trace dari Tempo
    trace_summary: Optional[str]       # ringkasan trace untuk LLM
    trace_available: Optional[bool]    # status konektivitas Tempo
    trace_id: Annotated[Optional[str], lambda a, b: b if b is not None else a]  # trace_id dari span/trace (Annotated agar fan-out 4 tidak conflict)
    preset_trace_ids: Optional[List[str]]  # trace_id dari alert watchdog (Cek Detail) — lookup spesifik
    preset_service_name: Optional[str]  # service dari tombol Cek Detail (observability alert)
    resolved_service_name: Optional[str]  # Fix #189: service asli dari alert label bila placeholder ("unknown")
    ticket_question_forced: Optional[bool]  # Fix #197 (Lapis 5): lane arbiter memaksa pertanyaan → summary
    correlation_result: Optional[dict] # hasil analisis root cause
    root_cause_assessment: Optional[str] # "service-fault" | "downstream" | "unknown"

    # Hasil Health Check agent
    health_target: Optional[str]       # e.g. "mongodb", "mysql", "all", "service:<name>"
    health_result: Optional[dict]      # hasil tes koneksi & latency

    # Hasil Telegram agent
    formatted_message: str             # pesan yang sudah di-format LLM
    telegram_sent: bool
    telegram_error: Optional[str]
    # FE-5: True bila dipicu dari chat web — response_agent hanya format, TIDAK kirim ke Telegram
    suppress_telegram: Optional[bool]

    # Supervisor routing
    next_agent: Annotated[Optional[str], lambda a, b: b if b is not None else a]  # Annotated agar fan-out paralel (4 nodes) tidak conflict
    error: Optional[str]

    # Follow-up resolution (Phase 1)
    is_follow_up: bool
    follow_up_context: Optional[dict]   # {prev_message, prev_reply, prev_raw_snapshot, prev_service, prev_date}
    reply_to_agent: Optional[bool]      # true bila pesan = balasan/mention jawaban agent sebelumnya

    # Data retrieval (Phase 1b) — ambil data mentah (bukan analisis error)
    data_mode: Optional[bool]
    data_limit: Optional[int]

    # Span detail (span_agent) — lookup traceId di app_logs_db (centralized OTel logging)
    span_data: Optional[dict]          # {"spans": [...], "http_logs": [...]}
    span_summary: Optional[str]        # ringkasan trace untuk LLM
    span_available: Optional[bool]     # status ketersediaan data trace di app_logs_db
    span_mode: Optional[bool]          # true bila jalur detail traceId (span_agent)

    # Second Brain — episodic memory
    episode_id: Optional[str]          # EP-YYYY-MM-DD-XXXX, diisi correlation_agent (Fase 1 Writer)
    second_brain_context: Optional[dict]  # hasil READ Fase 2 (Hybrid Search + boost) — None jika cold start / gagal

    # Triage — Fase 3 (silent, <30s)
    triage_result: Optional[dict]      # {hypothesis, confidence, severity, deploy_detected, deploy_info, focus_hints, skip_hints, second_brain_context, verification_note (GAP-6), minutes_since_deploy (GAP-6)}

    # Planner — Fase 4B + Gap 3 (selective fan-out, audit + loop)
    planned_nodes: Optional[List[str]]  # ["mongo_agent","trace_agent"] — diisi planner_node (Gap 3 Fase 1)
    planner_reason: Optional[str]       # Gap 3: alasan keputusan planner (audit log)
    service_type: Optional[str]         # Gap 3 Fase 5: api|worker|database|gateway dari registry (diisi triage)
    # Fix #189 (TASK-005B) — offer "investigate lebih dalam" diterima user → supervisor
    # memaksa full fan-out collector (bypass narrow by confidence/service_type di plan()).
    # WAJIB dideklarasi: LangGraph 0.6.11 (_get_updates) MEMBUANG key di luar schema saat
    # node return — tanpa error/warning. Bukti: tests/test_wiring_repro_task005.py.
    force_full_fanout: Optional[bool]   # True dari supervisor (offer session); dibaca investigation_planner.plan()

    # Fase 6B — LLM fallback routing
    routing_flag: Optional[str]        # None | "low_confidence_routing"
    routing_strategy: Optional[str]    # "strategy_1" .. "strategy_4" | "llm_fallback" | "triage"

    # Fase 6C — Diagnostic session
    session_id: Optional[str]          # DS-{episode_id}
    diagnostic_context: Optional[dict]  # jawaban user untuk sesi diagnostik

    # Ticket Agent — pengelolaan tiket via chat (lane baru, bukan analisis insiden)
    ticket_action: Optional[str]       # close/reopen/change_status/set_severity/add_label/assign/add_progress
    ticket_result: Optional[dict]      # hasil eksekusi: {ok, action, ticket_id, ticket_number, status}
    # Fix #189 (TASK-005B) — offer tiket yang DITERIMA user, dibawa supervisor → ticket_agent
    # untuk eksekusi deterministik tanpa LLM parse (jalur state.get("pending_offer")).
    # WAJIB dideklarasi: LangGraph 0.6.11 (_get_updates) MEMBUANG key di luar schema saat
    # node return — tanpa error/warning. Bukti: tests/test_wiring_repro_task005.py.
    pending_offer: Optional[dict]      # {"action": ..., "params": {...}} — diisi supervisor; dibaca ticket_agent

    # FE-7 — Knowledge kontekstual
    workspace_id: Optional[str]        # workspace pemilik konteks (chat/tiket web); None = global
    observ_id: Optional[str]           # MT (SCALE plan): id observability stack sumber; None = legacy/global
    knowledge_context: Optional[str]   # blok markdown dari knowledge_agent (universal + workspace)
    project_id: Optional[str]          # FE-8: project pemilik services (untuk match knowledge per-service)

    # Fix #49 — konteks tiket untuk chat yang terikat tiket (1 sesi = 1 tiket).
    # Diisi api/chat.py dari dokumen tiket; dipakai correlation utk grounding jawaban
    # ke subject tiket (title/description/serviceName/alert) walau data pipeline tipis.
    ticket_context: Optional[dict]     # {ticketNumber,title,description,serviceName,environment,severity,kind,source,tags,status}

    # Multi-turn — riwayat percakapan sesi (dari chat_messages) utk jawaban LLM.
    # Diisi api/chat.py; dipakai ticket summary, telegram format, correlation (2-3 turn).
    conversation_history: Optional[list]  # [{role: user|assistant, content}]

    # STACK2 Fase 1: Pod Health & PromQL Range
    metrics_mode: Optional[str]           # "pod_health" | "promql_range" | None
    metrics_window: Optional[str]         # e.g. "30m", "1h", "6h", "24h", "7d"
    metrics_promql: Optional[str]         # translated PromQL (from promql_translator)
    metrics_description: Optional[str]    # human-readable description of the query
    metrics_confidence: Optional[float]   # translator confidence (0.0-1.0)
    # STACK2 Fase 2: K8s Events Integration
    k8s_intent: Optional[str]            # "events" | "pod_status" | "node_pressure" | "all" | None
    k8s_mode: Optional[str]              # "deployment_ranking" | "deployment_overview" | None
    k8s_summary: Optional[str]           # formatted K8s summary for response_agent
    k8s_available: Optional[bool]        # True if K8s stack is configured and reachable
    k8s_raw: Optional[dict]              # raw K8s API data (events, pod_status, node_pressure)
    k8s_node: Optional[str]              # specific node name for node_pressure queries
    k8s_namespace: Optional[str]         # override namespace (default: from observ_config)

    # Pod logs (Fix #296)
    pod_logs: Optional[Dict[str, str]]          # {pod_name: log_text, "pod__previous_crash": ...}
    pod_logs_available: Optional[bool]
    pods_resolved: Optional[List[str]]
    pod_logs_note: Optional[str]

    # DB config presence flag (set by triage, consumed by planner + correlation)
    service_has_db_config: Optional[bool]

    # Fix #40 — notifikasi multi-bot: channel asal pesan masuk (mention/callback/webhook).
    # Diisi listener/webhook; response_agent membalas via channel ini saja.
    origin_notif_id: Optional[str]

    # Chat by Project — lane project_agent (read-only fase 1).
    # chat_depth: "low" (ringan, default) | "medium" (+saran investigasi) | "thinking"
    #   (pipeline insiden penuh — routing diputuskan supervisor, bukan agent ini).
    # project_result: hasil gather deterministik utk meta FE
    #   {type, ticket_refs?: [{ticketNumber,ticketId}], suggestions?: [str]}
    chat_depth: Optional[str]
    project_result: Optional[dict]

    # Chat suggestions (chips follow-up) — diisi agent terminal (ticket_agent/
    # response_agent/project_agent) utk meta FE; bilingual, deterministik
    # (services/offer_planner.build_chat_suggestions).
    chat_suggestions: Optional[list]

    # CHAT3 P1 (§4A.5) — context pill metadata utk FE ContextPill (web chat).
    # Diisi response_agent (web-only, channel metadata — bukan teks/Telegram):
    # {"type":"context","service":str,"ticket_id":str|None,"resolved_ref":None}.
    # WAJIB dideklarasi: LangGraph 0.6.11 (_get_updates) MEMBUANG key di luar schema
    # saat node return — tanpa error/warning (TASK-005 lesson,
    # tests/test_wiring_repro_task005.py). Dicopy ke SSE meta di api/chat.py
    # (_run_pipeline, di sebelah copy chat_suggestions→suggestions).
    context_pill: Optional[dict]

    # CHATFLOW V2.1 (Tahap 1) — transparansi & investigasi otonom.
    # Diisi correlation_agent setelah RCA (tanpa LLM tambahan).
    investigation_confidence: float   # 0.0 – 1.0, default 0.0
    data_gaps: List[Dict[str, Any]]              # structured: [{node, description, reason, suggested_action, priority}]
    gap_nodes: list[str]              # nama node graph yang di-skip (utk router Tahap 4)
    suggested_next: list[str]         # aksi investigasi spesifik (maks 3)
    internal_loop_count: int          # jumlah kali autonomous loop berjalan, default 0

    # P5.1 telemetry — routing gate instrumentation (CHAT4 §4.1).
    # WAJIB dideklarasi: LangGraph 0.6.11 (_get_updates) MEMBUANG key di luar schema saat
    # node return — tanpa error/warning. Bukti: tests/test_wiring_repro_task005.py.
    matched_gate: Optional[str]        # P5.1 telemetry — gate yang match di supervisor
    gate_type: Optional[str]           # P5.1 telemetry — hard_command|legacy_intent|service_match|classifier|fallback
    chat_agent_used: Optional[bool]    # P5.1 telemetry — True iff next_agent == chat_agent
    tools_used: Optional[List[str]]    # P5.1/R3 telemetry — nama tool yang dieksekusi per turn (chat_agent)
    synthesis_used: Optional[bool]     # P5.5/R4 telemetry — True iff synthesis pass composed the final reply (chat_agent)
    promise_without_call_fallback: Optional[bool]  # Fix #297: True iff promise guard activated (LLM promised but no TOOL_CALL)
    prefetched_tools: Optional[List[str]]  # Fix #298/A telemetry — tools deterministically pre-fetched before the Plan LLM (chat_agent)
    rephrased_after_no_data: Optional[bool]  # Fix #298/C telemetry — similar intent re-sent after a no-data turn (whack-a-mole alarm)


