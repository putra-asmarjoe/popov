import logging
from state.schema import AgentState
from services.request_log import get_latest_request
from agents.supervisor import is_data_request

logger = logging.getLogger(__name__)


async def follow_up_agent(state: AgentState) -> dict:
    """
    Resolve pertanyaan lanjutan (Phase 1):
    ambil riwayat request terakhir milik sender yang sama dari request_logs,
    lalu serahkan konteksnya ke telegram_agent untuk dijawab.
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
            "next_agent": "telegram_agent",
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
    logger.info(
        f"FollowUpAgent found previous request_id={prev.get('request_id')} at {prev.get('incoming_date')}"
    )

    return {
        "follow_up_context": context,
        "next_agent": "telegram_agent",
        "agents_visited": agents_visited,
    }
