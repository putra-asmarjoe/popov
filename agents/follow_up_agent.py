import logging
from state.schema import AgentState
from services.request_log import get_latest_request
from agents.supervisor import is_data_request

logger = logging.getLogger(__name__)

# CHATFLOW V2.1 (Tahap 3C): auto-route ke lane yang belum dijalankan (lanes_skipped)
LANE_KEYWORDS = {
    "metrics_agent": ["error rate", "cpu", "memory", "hpa", "metrics"],
    "health_agent":  ["koneksi", "ping", "connection", "health", "database"],
    "trace_agent":   ["trace", "distributed", "request path"],
    "span_agent":    ["span", "detail span", "central log"],
}


async def follow_up_agent(state: AgentState) -> dict:
    """
    Resolve pertanyaan lanjutan (Phase 1):
    ambil riwayat request terakhir milik sender yang sama dari request_logs,
    lalu serahkan konteksnya ke response_agent untuk dijawab.
    """
    agents_visited = state.get("agents_visited", []) + ["follow_up_agent"]
    intent = state.get("intent", "")
    sender = state.get("sender")
    service_name = state.get("service_name") or None
    request_id = state.get("request_id")

    logger.info(f"FollowUpAgent resolving intent='{intent}', sender={sender}")

    # Jika follow-up ternyata adalah permintaan data/table baru (mis. "cek di table incominglogs"),
    # jangan jawab dari snapshot lama — query DB baru via data_agent.
    if is_data_request(intent):
        # service dari intent saat ini, atau warisi dari prev bila intent tidak menyebut service
        prev_for_data = await get_latest_request(
            sender=sender,
            exclude_request_id=request_id,
            service_name=service_name,
            statuses=["success", "failed"],
        )
        target_service = service_name or (prev_for_data.get("service_name") if prev_for_data else None)
        if target_service:
            # biarkan data_agent yang resolve collection eksplisit via extract_collection_name
            target_collection = state.get("collection_name") or (prev_for_data.get("collection_name") if prev_for_data else None) or ""
            logger.info(
                f"FollowUpAgent: data request terdeteksi di follow-up → fallback ke data_agent "
                f"service='{target_service}'"
            )
            return {
                "service_name": target_service,
                "collection_name": target_collection,
                "is_follow_up": False,
                "follow_up_context": None,
                "next_agent": "data_agent",
                "agents_visited": agents_visited,
            }

    prev = await get_latest_request(
        sender=sender,
        exclude_request_id=request_id,
        service_name=service_name,
        statuses=["success", "failed"],
    )

    # CHATFLOW V2.1 (Tahap 3C): auto-route ke lane yang belum dijalankan.
    # Bila user menanyakan topik yang ada di lanes_skipped investigasi sebelumnya,
    # langsung route ke lane tsb tanpa menunggu supervisor (early return).
    inv_state = (prev or {}).get("investigation_state") or {}
    skipped = inv_state.get("lanes_skipped") or []
    if skipped:
        intent_lower = (state.get("intent") or "").lower()
        for lane, keywords in LANE_KEYWORDS.items():
            if lane in skipped and any(kw in intent_lower for kw in keywords):
                logger.info(
                    f"FollowUpAgent: auto-route ke {lane} (skipped di investigasi sebelumnya) "
                    f"intent='{intent}'"
                )
                return {
                    "service_name": state.get("service_name") or inv_state.get("service_name"),
                    "is_follow_up": False,
                    "follow_up_context": None,
                    "next_agent": lane,
                    "agents_visited": agents_visited,
                }

    # Tidak ada riwayat ATAU riwayat tanpa snapshot data mentah →
    # jangan menjawab dari konteks; lakukan pekerjaan yang diminta dari awal.
    if not prev or not prev.get("raw_documents_snapshot"):
        # Target service: dari intent, atau warisi dari riwayat sebelumnya
        # (relevan saat user reply-to jawaban agent tanpa menyebut service).
        target_service = service_name or (prev.get("service_name") if prev else None)
        if target_service:
            target_collection = (
                state.get("collection_name")
                or (prev.get("collection_name") if prev else None)
                or ""
            )
            # Intent ambil data mentah → eksekusi via data_agent, bukan mongo_agent
            next_agent = "data_agent" if is_data_request(intent) else "mongo_agent"
            logger.info(
                f"FollowUpAgent: riwayat tanpa snapshot → fallback eksekusi normal "
                f"({next_agent}) untuk service '{target_service}'"
            )
            return {
                "service_name": target_service,
                "collection_name": target_collection,
                "is_follow_up": False,
                "follow_up_context": None,
                "next_agent": next_agent,
                "agents_visited": agents_visited,
            }
        logger.info("FollowUpAgent: no previous request found")
        return {
            "follow_up_context": {"not_found": True},
            "next_agent": "response_agent",
            "agents_visited": agents_visited,
        }

    context = {
        "prev_message": prev.get("message"),
        "prev_reply": (prev.get("reply") or {}).get("text"),
        "prev_raw_snapshot": prev.get("raw_documents_snapshot") or [],
        "prev_service": prev.get("service_name"),
        "prev_date": prev.get("incoming_date"),
        "prev_status": prev.get("status"),
    }
    # CHATFLOW V2.1 (Tahap 3B): inject investigation_state ke context follow-up
    investigation_context = _build_investigation_context(inv_state)
    if investigation_context:
        context["investigation_state"] = inv_state
        context["investigation_context"] = investigation_context
    logger.info(
        f"FollowUpAgent found previous request_id={prev.get('request_id')} at {prev.get('incoming_date')}"
    )

    return {
        "follow_up_context": context,
        "next_agent": "response_agent",
        "agents_visited": agents_visited,
    }


def _build_investigation_context(inv_state: dict) -> str:
    """Bangun teks konteks investigasi sebelumnya (bilingual) utk prompt follow-up."""
    if not inv_state:
        return ""
    hypothesis = inv_state.get("hypothesis", "unknown")
    confidence = inv_state.get("confidence", 0.0)
    executed = inv_state.get("lanes_executed") or []
    skipped = inv_state.get("lanes_skipped") or []
    corr_summary = inv_state.get("correlation_summary") or ""
    suggested = inv_state.get("suggested_next") or []
    loop_count = inv_state.get("loop_count", 0)

    parts = []
    loop_note = f" (autonomous loop {loop_count}x)" if loop_count > 0 else ""
    parts.append(
        f"[Previous investigation{loop_note}]\n"
        f"Hypothesis: {hypothesis} (confidence: {int(confidence * 100)}%)\n"
        f"Lanes executed: {', '.join(executed) or 'none'}\n"
        f"Lanes skipped: {', '.join(skipped) or 'all done'}\n"
        f"Summary: {corr_summary}"
    )
    if suggested:
        parts.append(
            "Previously suggested actions:\n" + "\n".join(f"• {s}" for s in suggested)
        )
    return "\n\n".join(parts)
