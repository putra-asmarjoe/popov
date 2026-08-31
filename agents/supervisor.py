# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import re
import logging
from typing import Optional, Dict, Any

from state.schema import AgentState
from services.doc_loader import list_all_services
from services.ticket_intent import is_ticket_intent
from services.knowledge_listing import is_knowledge_query
from services.offer_planner import classify_answer
from services.offer_session import get_active_offer, accept_offer, cancel_offer, set_awaiting
from services.prompt_loader import render as render_prompt
from agents.span_agent import extract_trace_id, is_recent_error_request, is_central_log_request

logger = logging.getLogger(__name__)

STRATEGY5_THRESHOLD = 0.5

# LLM untuk Strategy 5 fallback — reuse factory (openai/openrouter/google/opencode)
try:
    from langchain_core.messages import SystemMessage, HumanMessage
    from services.llm_factory import get_chat_llm
    _has_llm = True
except Exception:
    _has_llm = False

def _get_llm():
    return get_chat_llm(temperature=0.2)


async def _llm_classify_intent(intent: str, available_services: list[str]) -> Optional[dict]:
    """FASE 6B Strategy 5: LLM classifier ringan untuk intent ambigu. Return None jika gagal."""
    if not _has_llm or not intent:
        return None
    try:
        llm = _get_llm()
        service_list = "\n".join(f"- {s}" for s in available_services)
        prompt = render_prompt("supervisor_classify", service_list=service_list, intent=intent)
        from langchain_core.messages import SystemMessage, HumanMessage
        import asyncio
        try:
            resp = await asyncio.wait_for(llm.ainvoke([SystemMessage(content="You are a classifier. Reply with JSON only."), HumanMessage(content=prompt)]), timeout=4.0)
            txt = resp.content.strip() if hasattr(resp, "content") else str(resp)
            # bersihkan markdown fence jika ada
            if "```" in txt:
                txt = txt.split("```")[1]
                if txt.strip().startswith("json"):
                    txt = txt.strip()[4:]
            result = json.loads(txt.strip())
            if result.get("service_name") not in available_services:
                # biarkan null, jangan paksa
                if result.get("service_name") not in (None, "null"):
                    logger.warning(f"[Supervisor] LLM service {result.get('service_name')} not in list, set None")
                    result["service_name"] = None
            return result
        except asyncio.TimeoutError:
            logger.warning("[Supervisor] Strategy 5 LLM timeout")
            return None
    except Exception as e:
        logger.warning(f"[Supervisor] Strategy 5 failed: {e}")
        return None

FOLLOW_UP_INTENT_KEYWORDS = [
    "detail", "minta penjelasan", "penjelasan", "jelaskan", "maksud",
]

SPAN_INTENT_KEYWORDS = [
    "detail trace", "trace id", "traceid", "telusur trace", "cek trace",
    "detail span", "rincian trace", "lihat trace", "trace_id",
]

DATA_INTENT_KEYWORDS = [
    "data terakhir", "data terbaru", "berikan data", "tampilkan data",
    "ambil data", "tunjukkan data", "list data", "data dari", "data mentah",
    "last data", "last record", "record terakhir", "data request",
    "lihat data", "liat data", "cek data", "tampilkan", "show",
    "table", "tabel",
]
DATA_COUNT_RE = re.compile(r"(\d+)\s*(?:data|record|row)", re.IGNORECASE)
# Pola collection eksplisit: "collection X" / "table Y" (nama SETELAH kata),
# atau "X collection" / "Y table" (nama SEBELUM kata — Fix #141).
COLLECTION_RE = re.compile(r"(?:collection|table|tabel)\s+([\w\-.]+)", re.IGNORECASE)
COLLECTION_SUFFIX_RE = re.compile(r"([\w\-.]+)\s+(?:collection|table|tabel)", re.IGNORECASE)

# Chat by Project — pertanyaan level project (tanpa menyebut service spesifik).
# Aktif HANYA bila state punya project_id & BUKAN sesi terikat tiket.
PROJECT_QUERY_KW = [
    "tiket", "ticket", "total", "berapa", "jenis", "masuk",
    "terjadi", "jam terakhir", "menit terakhir", "hari ini",
    "aktivitas", "alert", "knowledge", "dokumen", "playbook",
]


def is_data_request(intent: str) -> bool:
    """Deteksi intent pengambilan data mentah (bukan analisis error).

    True bila:
    - match keyword data (DATA_INTENT_KEYWORDS), ATAU
    - pola "N data/record/row", ATAU
    - intent menyebut collection/table eksplisit ("collection X", "table Y", "cek
      pengecekan pada Z collection") — KECUALI intent jelas insiden (mengandung
      "error"/"gagal"/"trace" yang menunjuk ke analisis error, bukan query mentah).
    Fix #141: "lakukan pengecekan pada received_release_logs collection" sebelumnya
    tidak match keyword data → jatuh ke insiden (preset service) padahal user minta
    query collection langsung.
    """
    if any(kw in intent for kw in DATA_INTENT_KEYWORDS):
        return True
    if DATA_COUNT_RE.search(intent):
        return True
    low = intent.lower()
    # kata pengecekan/inspeksi + collection eksplisit → data request
    check_verb = any(v in low for v in ("pengecekan", "periksa", "inspeksi", "lihat", "cek "))
    if not check_verb:
        return False
    has_explicit_collection = bool(
        re.search(r"(?:collection|table|tabel)\s+[\w\-.]+", low)
        or re.search(r"->\s*[\w\-.]+", low)
        or re.search(r"(?:collection|table|tabel)\b", low)
    )
    if not has_explicit_collection:
        return False
    # jangan hijack intent insiden yang menyebut collection (mis. "cek error pada X collection")
    if any(k in low for k in ("error", "gagal", "trace", "5xx", "500", "bermasalah", "down")):
        return False
    return True


def extract_data_count(intent: str, default: int = 5) -> int:
    """Ambil jumlah data yang diminta: '1 data' → 1; default 5; clamp 1..50."""
    match = DATA_COUNT_RE.search(intent)
    limit = int(match.group(1)) if match else default
    return min(max(limit, 1), 50)


def _collection_candidates(service_map: Dict[str, str]) -> list[str]:
    """
    Kandidat nama collection dari service_map (DB-driven: agent_docs + library +
    registry) — TANPA hardcode. Tiap collection menghasilkan 2 varian:
    nilai utuh ("logs_order_service") + tanpa prefix "logs_"
    ("order_service") karena user sering menulis tanpa prefix.
    """
    cands: set[str] = set()
    for col in (service_map or {}).values():
        if not col:
            continue
        c_low = col.lower()
        cands.add(c_low)
        stripped = re.sub(r"^logs_", "", c_low)
        if stripped:
            cands.add(stripped)
    return sorted(cands, key=len, reverse=True)


def extract_collection_name(intent: str, known_collections: Optional[list[str]] = None):
    """Ekstrak nama collection eksplisit dari intent: 'collection couponrequestlogs',
    'lakukan pengecekan pada received_release_logs collection' (Fix #141: nama di depan)."""
    # 1) pola eksplisit: "table X", "collection Y", "tabel Z" (nama setelah kata),
    #    lalu "X collection" / "Y table" (nama sebelum kata — Fix #141).
    m = COLLECTION_RE.search(intent)
    if m:
        explicit = m.group(1)
    else:
        m2 = COLLECTION_SUFFIX_RE.search(intent)
        explicit = m2.group(1) if m2 else None

    # 2) pola panah: "... -> incominglogs" (user sering tulis "DB -> table")
    arrow = re.search(r"->\s*([\w\-.]+)", intent)
    if arrow:
        arrow_target = arrow.group(1)
        # jika explicit adalah nama DB (mengandung 'db') dan arrow menunjuk koleksi, pakai arrow
        if explicit and "db" in explicit.lower():
            return arrow_target
        if arrow_target:
            # prioritaskan arrow bila explicit tidak ada atau arrow lebih spesifik
            # contoh: "table <db-name> -> incominglogs" → incominglogs
            if not explicit or "db" in explicit.lower():
                return arrow_target
            # bila keduanya ada dan explicit bukan DB, tetap kembalikan explicit dulu
            # tapi simpan arrow sebagai fallback di caller

    if explicit:
        return explicit

    if arrow:
        return arrow.group(1)

    # 3) fallback: kandidat dari service_map (DB-driven) yang disebut langsung di intent
    lower = intent.lower()
    for kc in known_collections or []:
        if kc and kc in lower:
            return kc

    return None


def _normalize(text: str) -> str:
    """Normalisasi string: lowercase dan ubah '-' atau spasi menjadi '_'."""
    text = text.lower().strip()
    text = re.sub(r"[-\s]+", "_", text)
    return text


def _fuzzy_suggest_service(
    intent: str,
    allowed_services: list[str],
    ticket_service_name: Optional[str] = None,
    cutoff: float = 0.6,
) -> Optional[str]:
    """
    Fix #50: fuzzy-suggest service saat user typo.
    Prioritas: (1) serviceName milik tiket aktif bila mirip, (2) difflib close match
    terhadap token intent vs nama service. Return canonical service_id atau None.
    """
    import difflib

    norm_intent = _normalize(intent)
    # Fix #50b: tokenisasi PER KATA + skor AKUMULASI (bukan first-tie),
    # agar kata umum ("service") tidak menentukan pemenang sendirian.
    words = [w for w in re.findall(r"[a-z0-9]+", norm_intent) if len(w) >= 3]

    # 1) serviceName tiket aktif — bila kata intent mengarah ke sana
    if ticket_service_name:
        tsid = ticket_service_name.strip().lower()
        ts_norm = _normalize(tsid)
        if any(ts_norm in w or w in ts_norm for w in words):
            return tsid

    # 2) akumulasi skor per-kandidat
    best: tuple[float, str] | None = None
    for svc in allowed_services:
        sv = _normalize(svc)
        total = 0.0
        for w in words:
            r = difflib.SequenceMatcher(None, w, sv).ratio()
            if w in sv:
                r = max(r, 0.8)      # kata terkandung di nama service
            elif sv in w:
                r = max(r, 0.85)     # nama service terkandung di kata (typo menempel)
            total += r
        if total == 0.0:
            continue
        # normalisasi ringan: tidak boleh menang hanya karena satu kata generik
        if best is None or total > best[0]:
            best = (total, svc)

    if best and best[0] >= 1.2:
        return best[1]
    return None


async def _list_project_refs(project_id: str) -> list[dict]:
    """Helper Fix #43: refs service milik project (untuk pesan error gate)."""
    try:
        from services.service_store import list_refs_for_project
        return await list_refs_for_project(project_id)
    except Exception as e:
        logger.warning(f"_list_project_refs failed: {e}")
        return []


def _ticket_redirect(state: dict, agents_visited: list) -> dict:
    """Guard out-of-konteks: chat tiket + pesan tanpa lane/service → arahkan kembali ke tiket.
    Deterministik (tanpa LLM) — dijamin tidak menjawab chit-chat/umum. Return reply normal."""
    tc = state.get("ticket_context") or {}
    num = tc.get("ticketNumber") or "?"
    title = tc.get("title") or ""
    head = f"⚠️ Saya fokus membantu tiket yang sedang dibuka (nomor {num}." + (f" — {title}" if title else "") + ")"
    return {
        "next_agent": "response_agent",
        "formatted_message": (
            f"{head}\nPertanyaan itu di luar konteks tiket ini. Mau saya bantu:\n"
            "  • Menutup / membuka kembali tiket\n"
            "  • Mengubah status / severity / label\n"
            "  • Menambah catatan progress · Assign tiket\n"
            "  • Merangkum kondisi tiket ini"
        ),
        "agents_visited": agents_visited,
        "routing_strategy": None,
        "routing_flag": None,
        "error": None,
    }


async def supervisor_agent(state: AgentState) -> dict:
    """
    Parse intent → resolve service_name / health check → route ke agent yang sesuai.
    FASE 6B: Strategy 5 LLM fallback jika confidence <0.5.
    """
    intent_raw = state.get("intent", "")
    intent = intent_raw.lower().strip()
    logger.info(f"Supervisor processing intent: '{intent}'")
    agents_visited = state.get("agents_visited", []) + ["supervisor"]
    # Fix #123: inisialisasi chat_depth di awal (sebelum semua branch return)
    # agar Strategy 5 (line ~466) tidak gagal "referenced before assignment".
    # State optional — default "low" bila kosong/invalid.
    chat_depth = (state.get("chat_depth") or "low").lower()

    # Gap 5 Fase 3: action chip "investigate:<node>" → direct route ke collector, bypass NLU.
    # span_agent TIDAK di whitelist — route setelah span tanpa konteks putus (ke response_agent).
    intent_raw = state.get("intent", "")
    if intent_raw.startswith("investigate:"):
        node = intent_raw.split(":", 1)[1].strip().lower()
        if node in ("mongo_agent", "metrics_agent", "trace_agent", "health_agent"):
            logger.info(f"[Supervisor] investigate chip → direct route {node}")
            svc = state.get("service_name") or ""
            return {
                "next_agent": node,
                "routing_flag": "direct_fanout",
                "intent": intent_raw,
                "service_name": svc,
                "collection_name": f"logs_{svc}" if svc else "",
                "agents_visited": agents_visited,
                "routing_strategy": None,
                "error": None,
            }

    # ── Offer Session: user menanggapi tawaran agent sebelumnya ──────────────
    # (Tahap 1-3). Keyed sender.session_id (web chat). Proses SEBELUM routing lain
    # agar "ya/tidak/isi-param" ditangkap & dieksekusi, bukan masuk jalur analisis.
    _sender_offer = state.get("sender") or {}
    _session_id = _sender_offer.get("session_id")
    if _session_id:
        _active = await get_active_offer(session_id=_session_id)
        if _active:
            _ans = classify_answer(intent)
            if _ans == "no":
                await cancel_offer(_active["offer_id"])
                logger.info(f"[Offer] declined {_active['offer_id']}")
                return {
                    "next_agent": "response_agent",
                    "formatted_message": "Oke, tawaran dibatalkan.",
                    "agents_visited": agents_visited,
                    "routing_strategy": None, "routing_flag": None, "error": None,
                }
            if _active.get("status") == "awaiting_param":
                # user mengetik nilai param yang ditunggu (mis. isi catatan progress)
                _field = _active.get("awaiting_field")
                _params = dict(_active.get("params") or {})
                if _field == "note":
                    _params["note"] = intent_raw.strip()
                await accept_offer(_active["offer_id"])
                logger.info(f"[Offer] param filled ({_field}) → execute {_active['offer_id']}")
                return {
                    "next_agent": "ticket_agent",
                    "pending_offer": {"action": _active["params"].get("action"), "params": _params},
                    "agents_visited": agents_visited,
                    "routing_strategy": None, "routing_flag": None, "error": None,
                }
            if _ans == "yes":
                await accept_offer(_active["offer_id"])
                logger.info(f"[Offer] accepted {_active['offer_id']} type={_active.get('type')}")
                if _active.get("needs_param"):
                    await set_awaiting(_active["offer_id"], _active["needs_param"])
                    _hint = "catatan progress" if _active["needs_param"] == "note" else _active["needs_param"]
                    return {
                        "next_agent": "response_agent",
                        "formatted_message": (f"Oke! {_active.get('question')}\n"
                                              f"Silakan ketik {_hint}-nya."),
                        "agents_visited": agents_visited,
                        "routing_strategy": None, "routing_flag": None, "error": None,
                    }
                if _active.get("type") == "ticket_action":
                    return {
                        "next_agent": "ticket_agent",
                        "pending_offer": {
                            "action": _active["params"].get("action"),
                            "params": _active.get("params") or {},
                        },
                        "agents_visited": agents_visited,
                        "routing_strategy": None, "routing_flag": None, "error": None,
                    }
                if _active.get("type") == "investigate":
                    _svc = _active["params"].get("service_name")
                    _it = _active["params"].get("intent") or f"cek error pada {_svc}"
                    return {
                        "service_name": _svc or "",
                        "collection_name": f"logs_{_svc}" if _svc else "",
                        "intent": _it,
                        "next_agent": "triage_agent",
                        "agents_visited": agents_visited,
                        "routing_strategy": "triage", "routing_flag": None, "error": None,
                    }
            # else: active tapi bukan ya/tidak → lanjut routing normal (offer tetap aktif)

    # Fix #45: service collection map MURNI dari DB (agent_docs via list_all_services).
    # JSON legacy `service_collection_map.json` TIDAK lagi dibaca (sumber = grounding docs DB).
    service_map = await list_all_services()

    # Fix #38: service bebas dari workspace library (analogi deployment K8s) —
    # jadikan kandidat routing juga; DB-nya di-resolve db_loader via library dbConfig.
    try:
        from services.service_store import all_service_ids as _lib_service_ids
        for sid in await _lib_service_ids():
            if sid not in service_map:
                service_map[sid] = f"logs_{sid}"
    except Exception as e:
        logger.debug(f"Library service candidates unavailable: {e}")

    # Fix #41: registry workspace (migrasi Monitoring Global) — kandidat routing
    # berdasarkan workspace di state; tanpa konteks → skip (legacy chain).
    ws_id = state.get("workspace_id")
    if ws_id:
        try:
            from services.workspace_service_registry import resolve_registry_for_state
            for item in await resolve_registry_for_state(ws_id):
                sid = item.get("service_id")
                if sid and sid not in service_map:
                    service_map[sid] = f"logs_{sid}"
        except Exception as e:
            logger.debug(f"Registry candidates unavailable: {e}")

    # ── Fix #43: PROJECT-GATED recognition ────────────────────────────────────
    # Bila request berasal dari project (chat web/tiket membawa project_id),
    # HANYA service yang ter-link ke project itu yang dikenali. Service di luar
    # daftar → ditolak + daftar service yang tersedia.
    project_id = state.get("project_id")
    if project_id:
        try:
            from services.service_store import service_ids_for_project
            linked = await service_ids_for_project(project_id)
        except Exception as e:
            logger.warning(f"Project-gated lookup failed: {e}")
            linked = []
        gated = {sid: col for sid, col in service_map.items() if sid in linked}
        dropped = sorted(set(service_map) - set(gated))
        service_map = gated
        logger.info(
            f"[ProjectGate] project={project_id} allowed={sorted(gated)} "
            f"(drop {len(dropped)} non-linked)"
        )

    matched_service = None
    matched_strategy = None
    confidence_score = 0.0
    is_preset_service = False
    norm_intent = _normalize(intent)

    # Strategy 1: Substring / Normalized match untuk service
    for service_key in service_map:
        norm_key = _normalize(service_key)
        if norm_key in norm_intent or service_key.lower() in intent:
            matched_service = service_key
            matched_strategy = "strategy_1"
            confidence_score = 0.9
            break

    # Strategy 2: Word overlap matching (e.g. "payment gateway prod" -> "payment_gateway_prod")
    if not matched_service:
        intent_words = set(re.findall(r"\w+", norm_intent))
        best_overlap = 0
        best_key = None
        for service_key in service_map:
            key_words = set(re.findall(r"\w+", _normalize(service_key)))
            overlap = len(intent_words.intersection(key_words))
            if overlap > 0 and overlap >= min(2, len(key_words)) and overlap > best_overlap:
                best_overlap = overlap
                best_key = service_key
        if best_key:
            matched_service = best_key
            matched_strategy = "strategy_2"
            confidence_score = 0.75

    # Strategy 3: Regex extraction fallback untuk service
    if not matched_service:
        patterns = [
            r"(?:service|pada|di|cek|error)\s+([\w-]+)",
            r"([\w-]+)\s+(?:error|bermasalah|down)",
        ]
        for pattern in patterns:
            m = re.search(pattern, intent)
            if m:
                candidate = _normalize(m.group(1))
                for key in service_map:
                    norm_key = _normalize(key)
                    if candidate in norm_key or norm_key in candidate:
                        matched_service = key
                        matched_strategy = "strategy_3"
                        confidence_score = 0.65
                        break
            if matched_service:
                break

    # Strategy 4: Service yang di-preset dari tombol "Cek Detail" (observability alert).
    if not matched_service:
        preset_service = state.get("preset_service_name") or ""
        if preset_service:
            matched_service = preset_service
            logger.info(f"Using preset service_name from button: '{preset_service}'")
            is_preset_service = True
            matched_strategy = "strategy_4"
            confidence_score = 0.85
        else:
            is_preset_service = False
    else:
        # Already matched via 1-3, check if preset also exists (not needed)
        is_preset_service = False

    # FASE 6B Strategy 5: LLM fallback jika confidence < threshold atau no match
    routing_strategy = matched_strategy
    routing_flag = None
    if (not matched_service or confidence_score < STRATEGY5_THRESHOLD) and intent_raw.strip():
        logger.info(f"[Supervisor] Strategy 5 trigger (matched={matched_service}, conf={confidence_score:.2f})")
        # Panggil LLM hanya jika intent cukup panjang (>10 char) untuk hindari spam
        if len(intent_raw.strip()) >= 8:
            llm_res = await _llm_classify_intent(intent_raw, list(service_map.keys()))
            if llm_res and llm_res.get("confidence", 0) >= 0.60:
                llm_service = llm_res.get("service_name")
                llm_conf = llm_res.get("confidence", 0)
                logger.info(f"[Supervisor] Strategy 5 LLM → service={llm_service} conf={llm_conf:.2f} type={llm_res.get('intent_type')}")
                if llm_service and llm_service in service_map:
                    # Fix #125: guard sesi PROJECT — pertanyaan level project (match
                    # PROJECT_QUERY_KW) jangan di-route ke service oleh tebakan LLM.
                    # "Tampilkan tiket yang masih terbuka" → LLM salah asosiasi
                    # service (kuponku_interfaces) → pipeline insiden, padahal
                    # harusnya project_agent. Prioritas: project query > llm fallback.
                    if (
                        state.get("project_id")
                        and not state.get("ticket_context")
                        and any(kw in intent for kw in PROJECT_QUERY_KW)
                    ):
                        logger.info("[Supervisor] Strategy 5 project-query guard → project_agent "
                                    f"(ignore llm_service={llm_service})")
                        return {
                            "service_name": "",
                            "collection_name": "",
                            "next_agent": "project_agent",
                            "agents_visited": agents_visited,
                            "routing_strategy": "project_query",
                            "routing_flag": "llm_guard_project_query",
                            "error": None,
                        }
                    matched_service = llm_service
                    routing_strategy = "llm_fallback"
                    routing_flag = "low_confidence_routing"
                    confidence_score = llm_conf
                elif llm_service is None and llm_res.get("intent_type"):
                    # LLM tidak yakin service, tapi intent_type bisa dipakai? tetap fallback
                    routing_strategy = "llm_fallback"
                    routing_flag = "low_confidence_routing"
                    # Chat by Project: LLM yakin ini pertanyaan level project → route langsung
                    if (
                        llm_res.get("intent_type") == "project"
                        and state.get("project_id")
                        and not state.get("ticket_context")
                        and chat_depth != "thinking"
                    ):
                        logger.info("[Supervisor] Strategy 5 intent_type=project → project_agent")
                        return {
                            "service_name": "",
                            "collection_name": "",
                            "next_agent": "project_agent",
                            "agents_visited": agents_visited,
                            "routing_strategy": "llm_fallback",
                            "routing_flag": "low_confidence_routing",
                            "error": None,
                        }

    # 2. Deteksi intent detail traceId (span_agent) — DULUAN dari follow-up,
    #    karena "detail trace <id>" mengandung kata "detail". Trigger:
    #    (b) intent menyebut traceId eksplisit (regex), ATAU
    #    (c) intent memakai keyword trace ("detail trace", "cek trace", ...),
    #    ATAU (d) intent meminta error span terbaru ("cek error terakhir di span").
    #    NOTE FASE 4A: preset_trace_ids dari tombol Cek Detail JANGAN trigger span mandiri —
    #    preset hanya untuk fan-out incident (span masuk ke correlation), bukan span standalone.
    #    Jadi has_trace_id hanya dari intent, bukan preset.
    preset_trace_ids = state.get("preset_trace_ids") or []
    has_trace_id = bool(extract_trace_id(intent))
    has_span_keyword = any(kw in intent for kw in SPAN_INTENT_KEYWORDS)
    has_recent_span_error = is_recent_error_request(intent)
    has_central_log = is_central_log_request(intent)
    if has_trace_id or has_span_keyword or has_recent_span_error or has_central_log:
        logger.info(
            f"Span detail intent detected: '{intent}' "
            f"(trace_id_in_intent={has_trace_id}, preset_trace_ids={len(preset_trace_ids)}, "
            f"keyword={has_span_keyword}, recent_error={has_recent_span_error}, central_log={has_central_log})"
        )
        return {
            "service_name": matched_service or "",
            "collection_name": service_map.get(matched_service, "") if matched_service else "",
            "is_follow_up": False,
            "span_mode": True,
            "next_agent": "span_agent",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy,
            "routing_flag": routing_flag,
            "error": None,
        }

    # 1b. Deteksi pengelolaan tiket (Ticket Agent) — lane terpisah dari analisis.
    #     Gate murah (rule) mensyaratkan ticket_context ada (chat di detail tiket).
    #     Diletakkan SETELAH span agar "detail trace" tetap ke span, dan SEBELUM
    #     follow-up/data/health agar aksi tiket ("tutup/assign/label/severity") tidak
    #     di-hijack lane lain. Parsing aksi detail dilakukan LLM di ticket_agent.
    if is_ticket_intent(intent, state):
        logger.info(f"Ticket intent detected: '{intent}'")
        return {
            "service_name": matched_service or "",
            "collection_name": service_map.get(matched_service, "") if matched_service else "",
            "is_follow_up": False,
            "next_agent": "ticket_agent",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy,
            "routing_flag": routing_flag,
            "error": None,
        }

    # 1c. Knowledge/doc query ("dokumen/knowledge apa pada service X") → inventory deterministik.
    #     Diletakkan SEBELUM follow-up/data/health/insiden agar tidak jatuh ke analisis error.
    if matched_service and is_knowledge_query(intent):
        logger.info(f"Knowledge query detected for service='{matched_service}': '{intent}'")
        try:
            from services.knowledge_listing import build_service_knowledge_inventory
            _want_detail = any(k in intent for k in ("detail", "isi", "baca", "rinci", "lengkap"))
            inventory = await build_service_knowledge_inventory(
                matched_service, state.get("workspace_id"), state.get("project_id"), detail=_want_detail
            )
        except Exception as e:
            logger.warning(f"Knowledge inventory failed: {e}")
            inventory = f"⚠️ Gagal mengambil knowledge service `{matched_service}`: {str(e)[:200]}"
        return {
            "service_name": matched_service,
            "collection_name": service_map.get(matched_service, ""),
            "formatted_message": inventory,
            "next_agent": "response_agent",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy,
            "routing_flag": routing_flag,
            "error": None,
        }

    # 2. Deteksi follow-up question (Phase 1) — diutamakan sebelum health check.
    #    Follow-up = (a) user me-mention/balas jawaban agent sebelumnya, ATAU
    #    (b) intent berdiri sendiri dengan permintaan penjelasan/detail eksplisit.
    #    Selain itu = intent baru → eksekusi normal.
    #    PENGECUALIAN: bila intent jelas meminta data/table/collection baru (mis. "cek di table incominglogs"),
    #    jangan perlakukan sebagai follow-up penjelasan — route ke data_agent agar query DB baru.
    is_reply_to_agent = bool(state.get("reply_to_agent", False))
    has_detail_intent = any(kw in intent for kw in FOLLOW_UP_INTENT_KEYWORDS)
    is_follow_up = is_reply_to_agent or has_detail_intent
    # Override: data request yang eksplisit (table/collection) → bukan follow-up
    if is_follow_up and is_data_request(intent):
        raw_lower = intent.lower()
        # bila user menyebut nama koleksi/table/DB eksplisit, ini query baru
        has_explicit_table = "->" in raw_lower or bool(
            extract_collection_name(raw_lower, _collection_candidates(service_map))
        )
        if has_explicit_table:
            logger.info(
                f"Follow-up overridden → data request (explicit table): '{intent}' "
                f"(reply_to_agent={is_reply_to_agent})"
            )
            is_follow_up = False
    if is_follow_up:
        logger.info(
            f"Follow-up intent detected: '{intent}' "
            f"(reply_to_agent={is_reply_to_agent}, detail_intent={has_detail_intent})"
        )
        return {
            "service_name": matched_service or "",
            "collection_name": service_map.get(matched_service, "") if matched_service else "",
            "is_follow_up": True,
            "next_agent": "follow_up_agent",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy,
            "routing_flag": routing_flag,
            "error": None,
        }

    # 3. Deteksi permintaan data mentah (mis. "berikan 1 data terakhir ...") →
    #    route ke data_agent (bukan mongo_agent yang khusus analisis error).
    #    Guard: sesi project dengan query level project (tiket/aktivitas/alert) → skip, biarkan project query check handle.
    if is_data_request(intent):
        # Project session + project query keywords → bukan data request mentah
        if not (
            state.get("project_id")
            and not state.get("ticket_context")
            and any(kw in intent for kw in PROJECT_QUERY_KW)
        ):
            logger.info(f"Data request intent detected: '{intent}'")
            if not matched_service:
                # Fix #50: fuzzy-suggest sebelum menyerah (typo user → service terdekat)
                suggest = _fuzzy_suggest_service(
                    intent, list(service_map.keys()), (state.get("ticket_context") or {}).get("serviceName")
                )
                if not suggest:
                    logger.warning(f"No service matched for data request intent: '{intent}'")
                    if state.get("ticket_context"):
                        return _ticket_redirect(state, agents_visited)
                    return {
                        "error": f"Tidak bisa mengenali service dari intent: '{intent}'. "
                                 f"Service yang tersedia: {list(service_map.keys())}",
                        "next_agent": "end",
                        "agents_visited": agents_visited,
                        "routing_strategy": routing_strategy,
                        "routing_flag": routing_flag,
                    }
                matched_service = suggest
                logger.info(f"[Supervisor] data-request fuzzy-suggest → '{suggest}' (auto-route)")
                routing_flag = routing_flag or "fuzzy_suggest"
            # Hormati collection eksplisit bila disebut (mis. "collection couponrequestlogs")
            explicit_collection = (
                extract_collection_name(intent, _collection_candidates(service_map))
                or service_map.get(matched_service)
                or f"logs_{matched_service}"
            )
            return {
                "service_name": matched_service,
                "collection_name": explicit_collection,
                "next_agent": "data_agent",
                "agents_visited": agents_visited,
                "routing_strategy": routing_strategy,
                "routing_flag": routing_flag,
                "error": None,
            }
        else:
            logger.info(f"Data request overridden → project query: '{intent}'")

    # 4. Deteksi apakah intent merupakan Pengecekan Koneksi / Health Check
    # Note: norm_intent sudah pakai underscore, jadi keyword harus normalized (tanpa spasi)
    health_keywords = ["koneksi", "ping", "tersambung", "connected", "status_db", "cek_db", "health", "cek_service", "cek_koneksi"]
    # cek dua sumber: norm_intent (underscore) + intent asli (spasi) untuk kompatibilitas
    is_health_check = any(kw in norm_intent for kw in health_keywords) or any(kw in intent for kw in ["status db", "cek db", "cek service", "cek koneksi"])
    # Guard: jangan anggap health bila intent jelas minta error/log/metrics
    if is_health_check and any(kw in intent for kw in ["error", "log", "trace", "metrics", "gagal", "bermasalah"]):
        # "cek service X error" → incident, bukan health
        is_health_check = False

    if is_health_check:
        logger.info(f"Health check intent detected: '{intent}'")
        # Fix #43: project-gated — bila dari project dan service tak ter-link → tolak
        if project_id and not matched_service and "mongodb" not in norm_intent and "mysql" not in norm_intent:
            linked = sorted({r.get("serviceId", "") for r in (await _list_project_refs(project_id))} - {""})
            return {
                "error": (
                    f"Service tidak dikenali untuk project ini. "
                    f"Service terdaftar: {linked if linked else '(belum ada — link service lewat halaman project)'}."
                ),
                "next_agent": "end",
                "agents_visited": agents_visited,
                "routing_strategy": routing_strategy,
                "routing_flag": routing_flag,
            }
        if "mongodb" in norm_intent or "mongo" in norm_intent:
            health_target = "mongodb"
        elif "mysql" in norm_intent:
            health_target = "mysql"
        elif "semua" in norm_intent or "all" in norm_intent:
            health_target = "all"
        elif matched_service:
            health_target = f"service:{matched_service}"
        else:
            health_target = "mongodb"

        return {
            "service_name": matched_service or "",
            "collection_name": service_map.get(matched_service, "") if matched_service else "",
            "health_target": health_target,
            "next_agent": "health_agent",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy,
            "routing_flag": routing_flag,
            "error": None,
        }

    # ── Chat by Project: pertanyaan level project (tanpa service eksplisit) ───
    # Fix #123: chat_depth sudah di-inisialisasi di awal function; reassign dihapus.
    # chat_depth "thinking" tidak blok project query — fallback di bawah juga handle.
    if (
        project_id
        and not state.get("ticket_context")
        and not matched_service
        and any(kw in intent for kw in PROJECT_QUERY_KW)
    ):
        logger.info(f"Project query detected (depth={chat_depth}): '{intent}'")
        return {
            "service_name": "",
            "collection_name": "",
            "next_agent": "project_agent",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy or "project_query",
            "routing_flag": routing_flag,
            "error": None,
        }

    # Jika bukan health check dan service tidak teridentifikasi
    if not matched_service:
        logger.warning(f"No service matched for intent: '{intent}'")
        # Chat by Project: fallback ramah — jangan error telanjang daftar service.
        # Bila pertanyaan terlihat seperti project query (atau ambigu di sesi project),
        # biarkan project_agent yang menjawab dgn data project. Termasuk mode thinking
        # tanpa subject: tanpa service eksplisit pipeline insiden tak punya target —
        # insight terbaik yang mungkin = fakta database project (Fix G3 gap-scan).
        if (
            state.get("project_id")
            and not state.get("ticket_context")
        ):
            logger.info(f"[Supervisor] no-match dalam sesi project → project_agent (fallback ramah): '{intent}'")
            return {
                "service_name": "",
                "collection_name": "",
                "next_agent": "project_agent",
                "agents_visited": agents_visited,
                "routing_strategy": routing_strategy or "project_query",
                "routing_flag": routing_flag or "low_confidence_routing",
                "error": None,
            }
        # Fix #50: fuzzy-suggest — typo user dicocokkan ke service terdekat (project-gated)
        suggest = _fuzzy_suggest_service(
            intent, list(service_map.keys()), (state.get("ticket_context") or {}).get("serviceName")
        )
        if state.get("ticket_context"):
            return _ticket_redirect(state, agents_visited)
        if suggest:
            logger.info(f"[Supervisor] fuzzy-suggest '{intent}' → '{suggest}' (auto-route)")
            return {
                "service_name": suggest,
                "collection_name": service_map.get(suggest, f"logs_{suggest}"),
                "next_agent": "triage_agent",
                "agents_visited": agents_visited,
                "routing_strategy": "fuzzy_suggest",
                "routing_flag": routing_flag or "low_confidence_routing",
                "error": None,
            }
        return {
            "error": f"Tidak bisa mengenali service dari intent: '{intent}'. "
                     f"Service yang tersedia: {list(service_map.keys())}",
            "next_agent": "end",
            "agents_visited": agents_visited,
            "routing_strategy": routing_strategy,
            "routing_flag": routing_flag,
        }

    collection = service_map.get(matched_service) or f"logs_{matched_service}"
    logger.info(f"Matched service='{matched_service}' → collection='{collection}' (strategy={routing_strategy} flag={routing_flag})")

    # Fase 4B: incident via triage dulu (silent) → planner selective fan-out
    # Supervisor return triage_agent, triage_agent akan set next_agent=mongo_agent
    return {
        "service_name": matched_service,
        "collection_name": collection,
        "next_agent": "triage_agent",
        "agents_visited": agents_visited,
        "routing_strategy": routing_strategy,
        "routing_flag": routing_flag,
        "error": None,
    }

