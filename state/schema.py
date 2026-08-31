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
    triage_result: Optional[dict]      # {hypothesis, confidence, severity, deploy_detected, deploy_info, focus_hints, skip_hints, second_brain_context}

    # Planner — Fase 4B + Gap 3 (selective fan-out, audit + loop)
    planned_nodes: Optional[List[str]]  # ["mongo_agent","trace_agent"] — diisi planner_node (Gap 3 Fase 1)
    planner_reason: Optional[str]       # Gap 3: alasan keputusan planner (audit log)
    service_type: Optional[str]         # Gap 3 Fase 5: api|worker|database|gateway dari registry (diisi triage)

    # Fase 6B — LLM fallback routing
    routing_flag: Optional[str]        # None | "low_confidence_routing"
    routing_strategy: Optional[str]    # "strategy_1" .. "strategy_4" | "llm_fallback" | "triage"

    # Fase 6C — Diagnostic session
    session_id: Optional[str]          # DS-{episode_id}
    diagnostic_context: Optional[dict]  # jawaban user untuk sesi diagnostik

    # Ticket Agent — pengelolaan tiket via chat (lane baru, bukan analisis insiden)
    ticket_action: Optional[str]       # close/reopen/change_status/set_severity/add_label/assign/add_progress
    ticket_result: Optional[dict]      # hasil eksekusi: {ok, action, ticket_id, ticket_number, status}

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

    # CHATFLOW V2.1 (Tahap 1) — transparansi & investigasi otonom.
    # Diisi correlation_agent setelah RCA (tanpa LLM tambahan).
    investigation_confidence: float   # 0.0 – 1.0, default 0.0
    data_gaps: list[str]              # deskripsi human-readable lane yang di-skip
    gap_nodes: list[str]              # nama node graph yang di-skip (utk router Tahap 4)
    suggested_next: list[str]         # aksi investigasi spesifik (maks 3)
    internal_loop_count: int          # jumlah kali autonomous loop berjalan, default 0


