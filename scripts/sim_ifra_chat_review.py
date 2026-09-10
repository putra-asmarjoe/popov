"""Simulasi percakapan chat tiket MAIN INFRA — review relevansi jawaban & chip.
Meniru api/chat._run_pipeline (graph astream) tanpa SSE/persist, utk beberapa
tiket & pertanyaan EN. Output: transcript + skor draft per exchange.
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")

from services.mongodb_client import get_db
from services.llm_factory import load_llm_config_from_db
from services.request_log import generate_request_id
from services.ticket_store import get_ticket
from services.conversation import build_conversation_history
from graph.workflow import app as langgraph_app

USER_ID = "6a93bb0c0cc5b73252711262"
WS_ID = "6a93bb0d0cc5b73252711263"

SCENARIOS = {
    "IFRA-2": [  # open critical - High error rate after deploy
        "What is this ticket about?",
        "How many times has this error alert fired?",
        "Can you summarize the alerts linked to this ticket?",
        "Is this related to a deployment regression?",
        "Who can I assign this ticket to?",
        "What should be checked first to fix this?",
        "Add a progress note saying we are checking the gateway logs",
        "What is the current status of this ticket?",
    ],
    "IFRA-3": [  # in_progress high - MongoDB connection pool exhausted
        "Summarize this ticket",
        "What was the root cause here?",
        "When did this ticket move to in_progress?",
        "Is the MongoDB connection pool healthy now?",
        "What services are affected by this issue?",
        "What is the current status?",
        "Show me the progress log entries",
        "What alerts are linked to this ticket?",
    ],
    "IFRA-4": [  # open high - Payment provider timeout
        "Ticket detail",
        "Why is the payment provider timing out?",
        "What severity is this ticket and why?",
        "Can you check if there are similar incidents for this service?",
        "What does PaymentProviderTimeout mean?",
        "Assign this ticket to Joe",
        "Change severity to critical please",
        "Summarize this ticket",
    ],
    "IFRA-5": [  # open high - HPA maxed out under traffic
        "What is this ticket about?",
        "Why is HPA maxed out?",
        "What services are affected?",
        "Can you check the current traffic patterns?",
        "What should we do to fix this?",
        "Add a progress note about scaling investigation",
        "What is the current status?",
        "Show me the linked alerts",
    ],
    "IFRA-6": [  # open high - 5xx spike on /checkout
        "Summarize this ticket",
        "What is causing the 5xx errors?",
        "Which endpoint is affected?",
        "Can you check the error logs?",
        "Is this related to the recent deploy?",
        "What should be checked first?",
        "Add a progress note",
        "What is the current status?",
    ],
    "IFRA-7": [  # needs_review medium - Slow catalog read latency
        "Ticket detail",
        "Why is catalog read latency slow?",
        "What was done to fix this?",
        "Is this ticket ready for review?",
        "Can you check the current latency metrics?",
        "What services are affected?",
        "Show me the progress log",
        "What is the current status?",
    ],
    "IFRA-8": [  # resolved low - Notification queue backpressure
        "Summarize this ticket",
        "What was the root cause?",
        "When was this ticket resolved?",
        "Is the notification queue healthy now?",
        "What was the fix applied?",
        "Show me the resolution notes",
        "What alerts were linked?",
        "What is the current status?",
    ],
}


async def run_pipeline(session_id, message, ticket, history_messages):
    from services.request_log import create_request_log
    request_id = generate_request_id()
    sender = {"channel": "chat", "name": "web", "session_id": session_id, "user_id": USER_ID}
    # create_request_log ringan
    try:
        await create_request_log(channel="chat", message_raw=message, sender=sender, request_id=request_id)
    except Exception:
        pass
    preset_service_name = (ticket.get("serviceName") or "").strip() or None
    ticket_context = {
        "ticket_id": str(ticket["_id"]),
        "ticketNumber": ticket.get("ticketNumber"),
        "title": ticket.get("title"),
        "description": (ticket.get("description") or "")[:2000],
        "serviceName": ticket.get("serviceName"),
        "environment": ticket.get("environment"),
        "severity": ticket.get("severity"),
        "kind": ticket.get("kind"),
        "source": ticket.get("source"),
        "tags": ticket.get("tags"),
        "status": ticket.get("status"),
        "projectId": str(ticket["projectId"]),
    }
    state = {
        "intent": message, "service_name": "", "collection_name": "",
        "request_id": request_id, "message_raw": message, "sender": sender,
        "agents_visited": [], "is_follow_up": False, "follow_up_context": None,
        "reply_to_agent": False, "data_mode": False, "data_limit": None,
        "raw_documents": [], "query_used": {}, "formatted_message": "",
        "telegram_sent": False, "telegram_error": None, "suppress_telegram": True,
        "workspace_id": WS_ID, "project_id": str(ticket["projectId"]),
        "knowledge_context": None, "preset_service_name": preset_service_name,
        "preset_trace_ids": [], "ticket_context": ticket_context,
        "chat_depth": "low", "conversation_history": history_messages,
        "next_agent": "supervisor", "error": None,
        "investigation_confidence": 0.0, "data_gaps": [], "gap_nodes": [],
        "suggested_next": [], "internal_loop_count": 0,
    }
    merged = {}
    try:
        stream = langgraph_app.astream(state, stream_mode="updates")
        async for update in stream:
            for node_name, delta in (update or {}).items():
                if isinstance(delta, dict):
                    merged.update(delta)
    except Exception as e:
        merged["error"] = f"{type(e).__name__}: {e}"
    answer = (merged.get("formatted_message") or merged.get("correlation_result") or "").strip()
    if merged.get("error") and not answer:
        answer = f"[ERROR] {merged['error']}"
    return answer, merged


async def main():
    # Load LLM config from DB first (BYOK)
    await load_llm_config_from_db()
    
    db = get_db()
    proj = await db["projects"].find_one({"slug": "main-infra"})
    if not proj:
        print("ERROR: main-infra project not found. Run seed_demo_main_infra.py first.")
        return
    pid = str(proj["_id"])
    report = {}
    for key, questions in SCENARIOS.items():
        num = int(key.split("-")[1])
        ticket = await get_ticket_for(pid, num)
        if not ticket:
            print(f"WARNING: ticket {key} not found, skipping")
            continue
        session_id = f"sim-{key.lower()}"
        history = []
        transcript = []
        for q in questions:
            ans, merged = await run_pipeline(session_id, q, ticket, list(history))
            suggestions = merged.get("chat_suggestions") or []
            agents = merged.get("agents_visited") or []
            transcript.append({
                "user": q, "answer": ans,
                "suggestions": suggestions, "agents": agents,
                "error": merged.get("error"),
            })
            history.append({"role": "user", "content": q})
            if ans:
                history.append({"role": "assistant", "content": ans})
            print(f"\n=== {key} Q: {q}")
            print(f"  agents: {agents}")
            print(f"  A: {ans[:300]}")
            if suggestions:
                print(f"  chips: {suggestions[:4]}")
        report[key] = transcript
    with open("scratch_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nReport saved to scratch_report.json")


async def get_ticket_for(pid, num):
    db = get_db()
    t = await db["tickets"].find_one({"projectId": pid, "ticketNumber": num})
    return t


if __name__ == "__main__":
    asyncio.run(main())
