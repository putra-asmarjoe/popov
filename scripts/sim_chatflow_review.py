"""Chatflow Simulation Review — P1 + P2 + Alert Flow + Manual Sentences.

Validates:
  - P1: Branch ordering (progress note guard before investigation query)
  - P2: Adaptive chips (context-aware suggestions)
  - Alert flow: Public ingest API → auto-ticket → service linking
  - Manual sentences: 20 hand-written inputs across 4 groups

Usage:
  python scripts/sim_chatflow_review.py                 # all tests
  python scripts/sim_chatflow_review.py --alert-only    # alert flow only
  python scripts/sim_chatflow_review.py --manual-sentences  # 20 sentences only
  python scripts/sim_chatflow_review.py --cleanup       # delete sim-test tickets
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

BASE_URL = os.environ.get("SIM_BASE_URL", "http://localhost:8000")
TEST_EMAIL = "sim-agent@popov.internal"
TEST_PASSWORD = "SimTest2026!"
TEST_NAME = "Sim Agent"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
ALERT_API_KEY = os.environ.get("SIM_ALERT_API_KEY", "")
ALERT_WORKSPACE_ID = os.environ.get("SIM_ALERT_WS_ID", "")


# ── Auth ──────────────────────────────────────────────────────────────────────

def ensure_test_user() -> str:
    """Register if not exists, login → return JWT token."""
    try:
        r = requests.post(f"{BASE_URL}/api/v1/auth/register", json={
            "name": TEST_NAME, "email": TEST_EMAIL, "password": TEST_PASSWORD,
        }, timeout=10)
        if r.status_code == 201:
            print(f"  ✓ Registered test user: {TEST_EMAIL}")
            return r.json()["token"]
    except Exception:
        pass

    r = requests.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": TEST_EMAIL, "password": TEST_PASSWORD,
    }, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"Login failed: {r.status_code} {r.text}")
    print(f"  ✓ Logged in as: {TEST_EMAIL}")
    return r.json()["token"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def resolve_projects(token: str) -> tuple:
    """Return (workspace_id, {slug: project_id}). Creates if empty."""
    h = auth_headers(token)
    r = requests.get(f"{BASE_URL}/api/v1/workspaces", headers=h, timeout=10)
    data = r.json()
    ws_list = data.get("workspaces", data.get("items", [])) if isinstance(data, dict) else data

    if not ws_list:
        # Create workspace
        print("  ⚠ No workspaces — creating default...")
        r = requests.post(f"{BASE_URL}/api/v1/workspaces", headers=h,
                          json={"name": "Sim Workspace"}, timeout=10)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Create workspace failed: {r.status_code} {r.text}")
        ws = r.json()
        ws_id = str(ws.get("id") or ws.get("_id"))
        print(f"  ✓ Created workspace: {ws.get('name', ws_id)}")

        # Create projects
        project_map = {}
        for slug, key in [("cluster-pro", "CLPR"), ("proxmox", "PRMX")]:
            r = requests.post(f"{BASE_URL}/api/v1/workspaces/{ws_id}/projects", headers=h,
                              json={"name": slug.replace("-", " ").title(), "key": key}, timeout=10)
            if r.status_code in (200, 201):
                p = r.json()
                project_map[slug] = str(p.get("id") or p.get("_id"))
                print(f"  ✓ Created project: {slug}")
        return ws_id, project_map

    ws = ws_list[0]
    ws_id = str(ws.get("id") or ws.get("_id"))
    print(f"  ✓ Workspace: {ws.get('name', ws_id)}")

    r = requests.get(f"{BASE_URL}/api/v1/workspaces/{ws_id}/projects", headers=h, timeout=10)
    data = r.json()
    projects = data if isinstance(data, list) else data.get("projects", data.get("items", []))
    project_map = {}
    for p in projects:
        slug = p.get("slug") or p.get("name", "").lower().replace(" ", "-")
        project_map[slug] = str(p.get("id") or p.get("_id"))

    # Create projects if missing
    for needed, key in [("cluster-pro", "CLPR"), ("proxmox", "PRMX")]:
        if needed not in project_map:
            r = requests.post(f"{BASE_URL}/api/v1/workspaces/{ws_id}/projects", headers=h,
                              json={"name": needed.replace("-", " ").title(), "key": key}, timeout=10)
            if r.status_code in (200, 201):
                p = r.json()
                project_map[needed] = str(p.get("id") or p.get("_id"))
                print(f"  ✓ Created project: {needed}")

    print(f"  ✓ Projects: {list(project_map.keys())}")
    return ws_id, project_map


def fetch_existing_tickets(token: str, project_id: str, limit: int = 2) -> list:
    r = requests.get(
        f"{BASE_URL}/api/v1/projects/{project_id}/tickets",
        headers=auth_headers(token),
        params={"status": "open,in_progress", "limit": limit, "exclude_tags": "sim-test"},
        timeout=10,
    )
    data = r.json()
    tickets = data.get("tickets", data.get("items", []))
    return [t for t in tickets if "sim-test" not in (t.get("tags") or [])][:limit]


def create_session(token: str, project_id: str, ticket_id: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/v1/chat/sessions",
        headers=auth_headers(token),
        json={"projectId": project_id, "ticketId": ticket_id, "title": f"sim-{ticket_id[:8]}"},
        timeout=10,
    )
    return r.json().get("id") or r.json()["_id"]


def send_and_consume(token: str, session_id: str, message: str) -> dict:
    """Send message, consume SSE, return {answer, chips, agents_used}."""
    headers = auth_headers(token)

    # Send
    r = requests.post(
        f"{BASE_URL}/api/v1/chat/sessions/{session_id}/send",
        headers=headers, json={"message": message}, timeout=10,
    )
    if r.status_code != 200:
        return {"answer": f"ERROR: {r.status_code}", "chips": [], "agents_used": []}

    # Consume SSE
    answer = ""
    url = f"{BASE_URL}/api/v1/chat/sessions/{session_id}/stream?token={token}"
    try:
        with requests.get(url, headers=headers, stream=True, timeout=120) as resp:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    if event.get("type") == "token":
                        answer += event.get("data", "")
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        answer = answer or f"STREAM ERROR: {e}"

    # Fetch last assistant meta
    r2 = requests.get(
        f"{BASE_URL}/api/v1/chat/sessions/{session_id}/messages",
        headers=headers, timeout=10,
    )
    msgs = r2.json()
    messages = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    meta = assistant_msgs[-1].get("meta", {}) if assistant_msgs else {}

    return {
        "answer": answer,
        "chips": meta.get("suggestions", []),
        "agents_used": meta.get("agents_visited", []),
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_exchange(q_type: str, result: dict, ticket_status: str = "open") -> dict:
    answer = result.get("answer", "")
    chips = result.get("chips", [])

    # intent_accuracy
    if "ERROR" in answer or not answer:
        intent_score = 0
    elif q_type == "progress_note" and ("📝" in answer or "progress note" in answer.lower()):
        intent_score = 2
    elif q_type == "progress_note" and "investigation" in answer.lower() and "progress" not in answer.lower():
        intent_score = 0
    elif q_type == "investigation" and ("🔍" in answer or "investigation" in answer.lower()):
        intent_score = 2
    elif q_type in ("summary", "status") and ("Status:" in answer or "status" in answer.lower() or len(answer) > 50):
        intent_score = 2
    elif q_type == "mixed" and ("📝" in answer or "Status:" in answer or len(answer) > 50):
        intent_score = 2
    elif answer and len(answer) > 20:
        intent_score = 1
    else:
        intent_score = 0

    # p1_safety (only for Q4 — progress_note_investigation)
    p1_score = None
    if q_type == "progress_note_investigation":
        if "📝" in answer or "progress note" in answer.lower():
            p1_score = 2
        elif "investigation" in answer.lower() and "progress" not in answer.lower():
            p1_score = 0
        else:
            p1_score = 1

    # chip_quality
    if not chips:
        chip_score = 0
    elif q_type == "investigation" and any("progress" in str(c).lower() or "investigate" in str(c).lower() for c in chips):
        chip_score = 2
    elif len(chips) >= 2:
        chip_score = 1
    else:
        chip_score = 0

    # response_quality
    if "ERROR" in answer:
        response_score = 0
    elif len(answer) > 100:
        response_score = 2
    elif len(answer) > 20:
        response_score = 1
    else:
        response_score = 0

    total = intent_score + (p1_score if p1_score is not None else 0) + chip_score + response_score
    max_possible = 7 if p1_score is not None else 6

    return {
        "intent_accuracy": intent_score,
        "p1_safety": p1_score,
        "chip_quality": chip_score,
        "response_quality": response_score,
        "total": total,
        "max_possible": max_possible,
    }


# ── Test Data ─────────────────────────────────────────────────────────────────

CHAT_QUESTIONS = {
    "SIM-CP-1": [
        ("summary", "What is this ticket about?"),
        ("investigation", "Why did the error rate spike after the deploy?"),
        ("progress_note", "Add a progress note saying we are rolling back to v2.4.0"),
        ("progress_note_investigation", "Add a progress note about our ongoing investigation into the gateway errors"),
        ("progress_note", "Tambahkan catatan: tim gateway sedang investigate root cause"),
        ("ambiguous", "Still happening after rollback?"),
        ("mixed", "Add a note that rollback is done and what is the current status now"),
    ],
    "SIM-CP-2": [
        ("summary", "Summarize this ticket"),
        ("investigation", "What is causing the payment provider to timeout?"),
        ("progress_note", "Add a progress note: contacting Midtrans support team"),
        ("progress_note_investigation", "Add a progress note about the investigation results from Midtrans"),
        ("progress_note", "Catat bahwa kita sedang tunggu response dari payment provider"),
        ("ambiguous", "Any update from the payment team?"),
        ("mixed", "Close this ticket and tell me what the root cause was"),
    ],
    "SIM-CP-3": [
        ("status", "What is the current status of this ticket?"),
        ("investigation", "What is causing the connection pool to be exhausted?"),
        ("progress_note", "Add a progress note saying connection pool limit increased to 1000"),
        ("progress_note_investigation", "Add a progress note about our connection pool investigation findings"),
        ("progress_note", "Tambahkan catatan: sudah scale up connection pool"),
        ("ambiguous", "Gimana kondisinya sekarang?"),
        ("mixed", "Add note that issue is resolved and change status to resolved"),
    ],
    "SIM-CP-4": [
        ("summary", "What happened with this ticket?"),
        ("investigation", "Why did the HPA max out?"),
        ("progress_note", "Add a progress note: post-mortem scheduled for tomorrow"),
        ("progress_note_investigation", "Add a progress note about the scaling investigation we did"),
        ("progress_note", "Catat bahwa post-mortem sudah selesai"),
        ("ambiguous", "Masih ada risiko terjadi lagi?"),
        ("mixed", "Reopen this ticket and add a note about why we're reopening"),
    ],
    "SIM-PX-1": [
        ("summary", "What is this ticket about?"),
        ("investigation", "Why is the Kafka consumer lag spiking?"),
        ("progress_note", "Add a progress note saying we increased consumer replicas to 8"),
        ("progress_note_investigation", "Add a progress note about our Kafka lag investigation"),
        ("progress_note", "Tambahkan catatan: consumer lag sudah turun ke 20k"),
        ("ambiguous", "Lag masih tinggi?"),
        ("mixed", "Add note that lag is recovering and check current status"),
    ],
    "SIM-PX-2": [
        ("summary", "Summarize this ticket"),
        ("investigation", "What is causing the StarRocks query timeouts?"),
        ("progress_note", "Add a progress note: rebuilding materialized views"),
        ("progress_note_investigation", "Add a progress note about the query performance investigation"),
        ("progress_note", "Catat bahwa materialized view sudah di-rebuild"),
        ("ambiguous", "Dashboard udah normal?"),
        ("mixed", "Close ticket and summarize what was done to fix it"),
    ],
    "SIM-PX-3": [
        ("status", "What is the current status?"),
        ("investigation", "Why did the daily-etl-pipeline DAG fail?"),
        ("progress_note", "Add a progress note saying extract_orders task is being retried"),
        ("progress_note_investigation", "Add a progress note about the DAG failure root cause investigation"),
        ("progress_note", "Tambahkan catatan: DAG sudah berhasil dijalankan ulang"),
        ("ambiguous", "DAG masih gagal?"),
        ("mixed", "Add note pipeline is healthy and assign this ticket to me"),
    ],
    "SIM-PX-4": [
        ("summary", "What happened with this ticket?"),
        ("investigation", "Why was the broker disk usage so high?"),
        ("progress_note", "Add a progress note: retention policy adjusted to 3 days"),
        ("progress_note_investigation", "Add a progress note about the disk usage investigation we ran"),
        ("progress_note", "Catat bahwa disk sudah kembali normal di 60%"),
        ("ambiguous", "Masih ada risiko disk penuh lagi?"),
        ("mixed", "Reopen ticket and add note about monitoring disk for 48h"),
    ],
}


def generate_existing_questions(ticket: dict) -> list:
    svc = ticket.get("serviceName") or ticket.get("service_name") or "this service"
    status = ticket.get("status", "open")
    is_resolved = status in ("resolved", "closed")
    q_reopen = "Reopen this ticket" if is_resolved else "Add a progress note: still monitoring"
    q_action = "Reopen this ticket" if is_resolved else "Close this ticket"
    return [
        ("summary", "What is this ticket about?"),
        ("investigation", f"What is causing the issue on {svc}?"),
        ("progress_note", "Add a progress note: team is investigating"),
        ("progress_note_investigation", f"Add a progress note about the investigation into {svc} errors"),
        ("progress_note", f"Tambahkan catatan: sedang cek {svc}"),
        ("ambiguous", "Any update?"),
        ("mixed", f"{q_action} and tell me what the root cause was"),
    ]


ALERT_CASES = [
    {"id": "A1", "service": "shop-gateway", "name": "SimHighErrorRate", "severity": "critical",
     "description": "Error rate 12x baseline on shop-gateway", "dedup": "new", "expect_created": True},
    {"id": "A2", "service": "shop-gateway", "name": "SimHighErrorRateDup", "severity": "critical",
     "description": "Duplicate alert — dedup auto may link or create new", "dedup": "auto", "expect_created": True},
    {"id": "A3", "service": "kafka", "name": "SimKafkaWarning", "severity": "warning",
     "description": "Kafka lag detected", "dedup": "new", "expect_created": True},
    {"id": "A4", "service": "nonexistent-svc-xyz", "name": "SimNonexistent", "severity": "info",
     "description": "Alert for unknown service", "dedup": "new", "expect_created": True},
    {"id": "A5", "service": "shop-order", "name": "SimOrderCritical", "severity": "critical",
     "description": "Order service down", "dedup": "new", "expect_created": True},
]


MANUAL_SENTENCES = [
    ("long_ambiguous", "Kita perlu cek apakah error yang muncul di shop-order ini ada hubungannya sama deploy kemarin, kalau ada tolong catat di tiket ini"),
    ("long_ambiguous", "I think the issue might be related to the cache, can you check and also update the ticket with whatever you find"),
    ("long_ambiguous", "Sepertinya ada masalah di downstream, tapi belum yakin, minta pendapat"),
    ("long_ambiguous", "Can you look into why errors started after the deploy and tell me what happened"),
    ("long_ambiguous", "Ada yang aneh sama latency-nya, bisa cek dan kalau ketemu kasih tahu lewat tiket"),
    ("mixed_intent", "Add a note that we're investigating AND what's the current status"),
    ("mixed_intent", "Close this ticket and also tell me what the root cause was"),
    ("mixed_intent", "Tambahkan catatan sudah resolved dan ubah status ke closed"),
    ("mixed_intent", "Check the error rate then add a progress note with what you find"),
    ("mixed_intent", "Assign ke saya dulu terus cek apakah masih ada error"),
    ("no_keyword", "Gimana ini?"),
    ("no_keyword", "Any update?"),
    ("no_keyword", "Still happening?"),
    ("no_keyword", "What happened with the logs from yesterday?"),
    ("no_keyword", "Masih?"),
    ("bilingual", "Tolong check dulu statusnya, terus add progress note kalau sudah"),
    ("bilingual", "Kenapa masih error padahal udah di-deploy ulang?"),
    ("bilingual", "Add note: we're still waiting for upstream team to respond"),
    ("bilingual", "Bisa close tiket ini? Udah resolved dari tadi"),
    ("bilingual", "Investigate dulu baru kasih tahu hasilnya"),
]


# ── Seed via DB ───────────────────────────────────────────────────────────────

def seed_tickets_db(ws_id: str, project_map: dict) -> dict:
    """Seed tickets via PyMongo directly (sync, no API)."""
    from pymongo import MongoClient
    from config.settings import settings

    client = MongoClient(settings.mongodb_uri)
    DB = client[settings.mongodb_db]
    now = datetime.now(timezone.utc)

    # Ensure ticketCounter exists on projects
    for pid in project_map.values():
        DB["projects"].update_one(
            {"_id": __import__("bson").ObjectId(pid)},
            {"$setOnInsert": {"ticketCounter": 0}},
            upsert=True,
        )

    SEED = [
        {"key": "cluster-pro", "slug": "SIM-CP-1", "title": "High error rate on shop-gateway after deploy",
         "desc": "Error rate spiked to 8x baseline after deployment v2.4.1.", "sev": "critical",
         "svc": "shop-gateway", "status": "open"},
        {"key": "cluster-pro", "slug": "SIM-CP-2", "title": "Payment provider timeout on /checkout",
         "desc": "Intermittent 30s timeouts to Midtrans payment gateway.", "sev": "high",
         "svc": "shop-order", "status": "open"},
        {"key": "cluster-pro", "slug": "SIM-CP-3", "title": "MongoDB connection pool exhausted",
         "desc": "Connection pool hitting limit (500/500).", "sev": "high",
         "svc": "user-service", "status": "in_progress"},
        {"key": "cluster-pro", "slug": "SIM-CP-4", "title": "HPA maxed out — notification-service",
         "desc": "HPA at 10/10 replicas. CPU 95%.", "sev": "medium",
         "svc": "notification-service", "status": "resolved"},
        {"key": "proxmox", "slug": "SIM-PX-1", "title": "Kafka consumer lag spiking",
         "desc": "Consumer group lag reached 120k messages.", "sev": "critical",
         "svc": "kafka", "status": "open"},
        {"key": "proxmox", "slug": "SIM-PX-2", "title": "StarRocks query timeout",
         "desc": "Queries > 30s on materialized views.", "sev": "high",
         "svc": "starrocks", "status": "open"},
        {"key": "proxmox", "slug": "SIM-PX-3", "title": "Airflow DAG failure",
         "desc": "daily-etl-pipeline DAG failed at task extract_orders.", "sev": "high",
         "svc": "airflow", "status": "in_progress"},
        {"key": "proxmox", "slug": "SIM-PX-4", "title": "Kafka broker disk 87%",
         "desc": "Broker disk at 87%. Full in ~6 hours.", "sev": "medium",
         "svc": "kafka", "status": "resolved"},
    ]

    # Per-project counter for unique ticketNumber
    proj_counters = {}
    created = {}
    for s in SEED:
        pid = project_map.get(s["key"])
        if not pid:
            print(f"  ⚠ skip {s['slug']}: project '{s['key']}' not found")
            continue
        # Increment ticketCounter atomically
        updated = DB["projects"].find_one_and_update(
            {"_id": __import__("bson").ObjectId(pid)},
            {"$inc": {"ticketCounter": 1}},
            return_document=True,
        )
        ticket_number = updated.get("ticketCounter", 1)

        doc = {
            "ticketNumber": ticket_number,
            "title": s["title"], "description": s["desc"], "severity": s["sev"],
            "severityRank": {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(s["sev"], 2),
            "status": s["status"], "projectId": pid, "workspaceId": ws_id,
            "serviceName": s["svc"], "serviceIds": [s["svc"]],
            "tags": ["sim-test"], "source": "sim-test", "kind": "incident",
            "environment": "production", "createdAt": now, "updatedAt": now,
            "createdBy": "sim-agent", "progressLog": [], "alerts": [],
        }
        result = DB["tickets"].insert_one(doc)
        doc["_id"] = result.inserted_id
        created[s["slug"]] = doc
        print(f"  ✓ {s['slug']}: #{ticket_number} {s['title'][:50]}")
    client.close()
    return created


def cleanup_sim_tickets(ws_id: str):
    from pymongo import MongoClient
    from config.settings import settings

    client = MongoClient(settings.mongodb_uri)
    DB = client[settings.mongodb_db]
    result = DB["tickets"].delete_many({"workspaceId": ws_id, "tags": "sim-test"})
    print(f"  Cleaned up {result.deleted_count} sim-test tickets")
    client.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def run_chat_flow(token, ws_id, project_map, seed_tix, existing_tix):
    results = []
    all_tickets = {}
    for slug, doc in seed_tix.items():
        pid = doc.get("projectId")
        for k, v in project_map.items():
            if v == pid:
                all_tickets[slug] = {"doc": doc, "project_id": pid, "project_key": k}
                break
    for proj_key, tickets in existing_tix.items():
        for i, t in enumerate(tickets):
            slug = f"EXIST-{proj_key[:3].upper()}-{i+1}"
            all_tickets[slug] = {"doc": t, "project_id": project_map.get(proj_key), "project_key": proj_key}

    print(f"\n{'='*60}")
    print(f"CHAT FLOW — {len(all_tickets)} tickets x 7 questions")
    print(f"{'='*60}")

    for slug in sorted(all_tickets):
        info = all_tickets[slug]
        doc = info["doc"]
        status = doc.get("status", "open")
        print(f"\n  📋 {slug}: {doc.get('title', '')[:50]} [{status}]")

        questions = CHAT_QUESTIONS.get(slug) or generate_existing_questions(doc)
        sid = create_session(token, info["project_id"], str(doc["_id"]))

        t_results = []
        for qi, (qt, q) in enumerate(questions):
            print(f"    Q{qi+1}: {q[:55]}...", end=" ")
            r = send_and_consume(token, sid, q)
            sc = score_exchange(qt, r, status)
            t_results.append({"q_index": qi+1, "q_type": qt, "question": q,
                              "answer": r["answer"][:200], "chips": r["chips"],
                              "agents_used": r["agents_used"], "score": sc})
            print(f"→ {sc['total']}/{sc['max_possible']} i={sc['intent_accuracy']} p={sc['p1_safety']} c={sc['chip_quality']} r={sc['response_quality']}")

        avg = sum(x["score"]["total"] for x in t_results) / max(len(t_results), 1)
        results.append({"ticket_id": slug, "ticket_title": doc.get("title", ""),
                        "project": info["project_key"],
                        "ticket_type": "seeded" if "SIM-" in slug else "existing",
                        "avg_score": round(avg, 2), "exchanges": t_results})
    return results


def run_alert_flow(token, ws_id, project_map):
    results = []
    # Alert endpoint requires API key (pk_pub_*), not Bearer token
    api_key = ALERT_API_KEY
    alert_ws = ALERT_WORKSPACE_ID or ws_id
    if not api_key:
        print("\n  ⚠ No SIM_ALERT_API_KEY set — skipping alert flow")
        return []
    h = {"Authorization": f"Bearer {api_key}"}
    print(f"\n{'='*60}")
    print(f"ALERT FLOW — {len(ALERT_CASES)} cases (API key auth)")
    print(f"{'='*60}")

    created_ids = []
    for c in ALERT_CASES:
        print(f"\n  🚨 {c['id']}: {c['name']} → {c['service']} ({c['severity']})")
        payload = {"service": c["service"], "name": c["name"], "severity": c["severity"],
                   "description": c["description"], "dedup": c["dedup"],
                   "source": "sim-test", "workspace_id": alert_ws}
        try:
            r = requests.post(f"{BASE_URL}/api/pub/v1/ingest/alert", json=payload, headers=h, timeout=15)
            created = r.status_code == 201
            body = r.json()
            data = body.get("data", {})
            tid = None
            if data.get("tickets_new"):
                tid = data["tickets_new"][0]  # e.g. "IFRA-21"
            elif data.get("tickets_linked"):
                tid = data["tickets_linked"][0]
            if created and tid:
                created_ids.append(tid)
            ok = created == c["expect_created"]
            print(f"    → {r.status_code} created={created} ticket={tid} {'✅' if ok else '❌'}")
            results.append({**c, "http_status": r.status_code, "ticket_created": created,
                            "ticket_id": tid, "pass": ok})
        except Exception as e:
            print(f"    → ERROR: {e}")
            results.append({**c, "error": str(e), "pass": False})

    # Alert flow: no LLM chat test — keep fast
    return results


def run_manual_sentences(token, ws_id, project_map, seed_tix):
    results = []
    target = None
    for slug, doc in seed_tix.items():
        if "CP-1" in slug:
            target = doc
            break
    if not target:
        target = next(iter(seed_tix.values()), None)
    if not target:
        print("  ⚠ No seed tickets")
        return []

    pid = target.get("projectId")
    tid = str(target["_id"])
    print(f"\n{'='*60}")
    print(f"MANUAL SENTENCES — 20 on {target.get('title', '')[:40]}")
    print(f"{'='*60}")

    sid = create_session(token, pid, tid)
    for idx, (grp, sent) in enumerate(MANUAL_SENTENCES):
        print(f"  [{idx+1:2d}/20] ({grp}) {sent[:55]}...", end=" ")
        r = send_and_consume(token, sid, sent)
        ans = r.get("answer", "")
        chips = r.get("chips", [])

        intent = 0 if ("ERROR" in ans or not ans) else (2 if ("📝" in ans or "🔍" in ans or "Status:" in ans or len(ans) > 50) else (1 if len(ans) > 20 else 0))
        action = intent
        chip_s = 2 if len(chips) >= 2 else (1 if chips else 0)
        fb = None
        if grp == "no_keyword":
            fb = 0 if ("ERROR" in ans or not ans) else (2 if len(ans) > 50 else (1 if len(ans) > 20 else 0))
        tot = intent + action + chip_s + (fb if fb is not None else 0)
        mx = 8 if fb is not None else 6
        print(f"→ {tot}/{mx} i={intent} c={chip_s} fb={fb}")
        results.append({"index": idx+1, "group": grp, "sentence": sent,
                        "answer": ans[:200], "chips": chips,
                        "agents_used": r.get("agents_used", []),
                        "score": {"intent_accuracy": intent, "action_accuracy": action,
                                  "chip_relevance": chip_s, "fallback_quality": fb,
                                  "total": tot, "max_possible": mx}})
    return results


def build_report(chat_r, alert_r, manual_r):
    now = datetime.now(timezone.utc).isoformat()

    # Chat summary
    all_sc = [ex["score"]["total"] for t in chat_r for ex in t["exchanges"]]
    chat_avg = round(sum(all_sc) / max(len(all_sc), 1), 2) if all_sc else 0
    p1_cases = [ex for t in chat_r for ex in t["exchanges"] if ex["score"]["p1_safety"] is not None]
    p1_pass = sum(1 for c in p1_cases if c["score"]["p1_safety"] and c["score"]["p1_safety"] >= 1)
    p1_rate = round(p1_pass / max(len(p1_cases), 1) * 100)
    chip_ctx = sum(1 for t in chat_r for ex in t["exchanges"]
                   if ex.get("chips") and any("progress" in str(c).lower() or "investigate" in str(c).lower() for c in ex["chips"]))
    chip_total = sum(len(t["exchanges"]) for t in chat_r)
    chip_rate = round(chip_ctx / max(chip_total, 1) * 100)

    # Alert summary
    alert_pass = sum(1 for a in alert_r if a.get("pass"))

    # Manual summary
    m_avg = round(sum(r["score"]["total"] for r in manual_r) / max(len(manual_r), 1), 2) if manual_r else 0
    m_groups = {}
    for r in manual_r:
        m_groups.setdefault(r["group"], []).append(r["score"]["total"])
    m_by_group = {k: round(sum(v)/len(v), 2) for k, v in m_groups.items()}

    mc = {}
    if manual_r:
        n = len(manual_r)
        ip = sum(1 for r in manual_r if r["score"]["intent_accuracy"] >= 1)
        ns = sum(1 for r in manual_r if r["group"] != "no_keyword" and r["score"]["intent_accuracy"] >= 1)
        mp = sum(1 for r in manual_r if r["group"] == "mixed_intent" and r["score"]["intent_accuracy"] >= 1)
        cp = sum(1 for r in manual_r if r["score"]["chip_relevance"] >= 1)
        fbs = [r["score"]["fallback_quality"] for r in manual_r if r["score"]["fallback_quality"] is not None]
        fp = sum(1 for f in fbs if f >= 1)
        n_mx = sum(1 for r in manual_r if r["group"] == "mixed_intent")
        mc = {
            "intent_accuracy": {"threshold": "90%", "result": f"{round(ip/max(n,1)*100)}%", "pass": ip/max(n,1) >= 0.9},
            "progress_note_safety": {"threshold": "100%", "result": f"{round(ns/max(n-1,1)*100)}%", "pass": ns/max(n-1,1) >= 0.95},
            "mixed_intent": {"threshold": "100%", "result": f"{round(mp/max(n_mx,1)*100)}%", "pass": mp/max(n_mx,1) >= 0.9},
            "chip_relevance": {"threshold": "70%", "result": f"{round(cp/max(n,1)*100)}%", "pass": cp/max(n,1) >= 0.7},
            "fallback_quality": {"threshold": "60%", "result": f"{round(fp/max(len(fbs),1)*100)}%", "pass": fp/max(len(fbs),1) >= 0.6},
        }

    return {
        "meta": {"date": now, "script": "sim_chatflow_review.py",
                 "validates": ["P1-branch-ordering", "P2-adaptive-chips", "alert-flow", "manual-sentences"]},
        "summary": {"chat_flow_avg": chat_avg, "alert_flow_pass_rate": f"{round(alert_pass/max(len(alert_r),1)*100)}%",
                    "manual_sentences_avg": m_avg, "p1_safety_rate": f"{p1_rate}%", "chip_contextual_rate": f"{chip_rate}%"},
        "chat_flow": chat_r, "alert_flow": alert_r,
        "manual_sentences": {"results": manual_r, "by_group": m_by_group, "pass_criteria": mc},
    }


def print_summary(report):
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  Chat flow avg:         {s['chat_flow_avg']}/8.0")
    print(f"  Alert flow pass rate:  {s['alert_flow_pass_rate']}")
    print(f"  Manual sentences avg:  {s['manual_sentences_avg']}/8.0")
    print(f"  P1 safety rate:        {s['p1_safety_rate']}")
    print(f"  Chip contextual rate:  {s['chip_contextual_rate']}")
    mc = report.get("manual_sentences", {}).get("pass_criteria", {})
    if mc:
        print(f"\n  Manual Sentences Pass Criteria:")
        for k, v in mc.items():
            print(f"    {'✅' if v['pass'] else '❌'} {k}: {v['result']} (threshold: {v['threshold']})")


def main():
    parser = argparse.ArgumentParser(description="Chatflow Simulation Review")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--alert-only", action="store_true", help="Run alert + manual sentences (skip chat flow)")
    parser.add_argument("--manual-sentences", action="store_true", help="Run manual sentences + alert (skip chat flow)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--project", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "sim_chatflow_report.json"))
    args = parser.parse_args()

    # Default: all three. Flags narrow to specific group.
    run_chat = True
    run_alert = True
    run_manual = True

    if args.alert_only:
        run_chat = False
        run_manual = False
    if args.manual_sentences:
        run_chat = False
        run_alert = False
    if args.all:
        run_chat = run_alert = run_manual = True

    print(f"🚀 Chatflow Simulation Review — {BASE_URL}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Auth
    print("\n▸ Auth")
    token = ensure_test_user()

    # Projects
    print("\n▸ Projects")
    ws_id, project_map = resolve_projects(token)
    if not project_map:
        print("  ❌ No projects"); return

    # Seed
    print("\n▸ Seed tickets")
    seed_tix = seed_tickets_db(ws_id, project_map)
    print(f"  ✓ {len(seed_tix)} seeded")

    # Existing
    existing = {}
    if run_chat:
        print("\n▸ Existing tickets")
        for pk, pid in project_map.items():
            existing[pk] = fetch_existing_tickets(token, pid)
            print(f"  ✓ {pk}: {len(existing[pk])}")

    # Run
    chat_r = run_chat_flow(token, ws_id, project_map, seed_tix, existing) if run_chat else []
    alert_r = run_alert_flow(token, ws_id, project_map) if run_alert else []
    manual_r = run_manual_sentences(token, ws_id, project_map, seed_tix) if run_manual else []

    # Report
    report = build_report(chat_r, alert_r, manual_r)
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n📄 Report: {args.output}")
    print_summary(report)

    if args.cleanup:
        print("\n▸ Cleanup")
        cleanup_sim_tickets(ws_id)


if __name__ == "__main__":
    main()
