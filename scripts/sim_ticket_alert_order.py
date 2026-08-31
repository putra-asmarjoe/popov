"""
Simulasi: 2 tiket (A & B) → alert baru attach ke A → urutan berubah.

Jalankan: cd /development/ProjectFolder/Aptanalovvit2/Source/popov-agent && ./venv/bin/python scripts/sim_ticket_alert_order.py
"""
import asyncio
import hashlib
import time
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "popovagent_db"

WORKSPACE_ID = "6a89b406fc0d7edfec910950"
PROJECT_ID = "6a89b406fc0d7edfec910951"
SERVICE = "kuponku_core_api"
ALERT_NAME = "HighErrorRate"


async def main():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    # Cleanup test data
    await db.tickets.delete_many({"source": "sim_test"})
    await db.ticket_alerts.delete_many({"source": "sim_test"})
    print("=== Cleanup done ===\n")

    now = datetime.now(timezone.utc)

    # ── Step 1: Buat Tiket A (2 menit lalu) ──────────────────────────────
    tA_created = now.replace(minute=now.minute - 2)
    docA = {
        "ticketNumber": 1001,
        "title": "Tiket A — alert pertama HighErrorRate",
        "description": "Simulasi tiket A",
        "workspaceId": WORKSPACE_ID,
        "projectId": PROJECT_ID,
        "kind": "infrastructure",
        "severity": "high",
        "severityRank": 1,
        "serviceName": SERVICE,
        "environment": "production",
        "status": "open",
        "source": "sim_test",
        "fingerprint": f"{WORKSPACE_ID}:{PROJECT_ID}:fpA",
        "contentFp": hashlib.md5(f"{SERVICE}|{ALERT_NAME}".encode()).hexdigest(),
        "alertsCount": 1,
        "lastAlertAt": tA_created.isoformat(),
        "progressLog": [],
        "createdAt": tA_created.isoformat(),
        "updatedAt": tA_created.isoformat(),
    }
    resA = await db.tickets.insert_one(docA)
    idA = resA.inserted_id
    print(f"Tiket A created: {idA}")
    print(f"  createdAt:  {docA['createdAt']}")
    print(f"  updatedAt:  {docA['updatedAt']}")

    # ── Step 2: Buat Tiket B (1 menit lalu) ──────────────────────────────
    tB_created = now.replace(minute=now.minute - 1)
    docB = {
        "ticketNumber": 1002,
        "title": "Tiket B — alert berbeda",
        "description": "Simulasi tiket B",
        "workspaceId": WORKSPACE_ID,
        "projectId": PROJECT_ID,
        "kind": "infrastructure",
        "severity": "medium",
        "severityRank": 2,
        "serviceName": "kuponku_users",
        "environment": "production",
        "status": "open",
        "source": "sim_test",
        "fingerprint": f"{WORKSPACE_ID}:{PROJECT_ID}:fpB",
        "contentFp": hashlib.md5(f"kuponku_users|LowMemory".encode()).hexdigest(),
        "alertsCount": 1,
        "lastAlertAt": tB_created.isoformat(),
        "progressLog": [],
        "createdAt": tB_created.isoformat(),
        "updatedAt": tB_created.isoformat(),
    }
    resB = await db.tickets.insert_one(docB)
    idB = resB.inserted_id
    print(f"\nTiket B created: {idB}")
    print(f"  createdAt:  {docB['createdAt']}")
    print(f"  updatedAt:  {docB['updatedAt']}")

    # ── Step 3: Cek urutan SEBELUM ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("URUTAN SEBELUM alert baru attach ke Tiket A")
    print("=" * 60)
    cursor = db.tickets.find({"source": "sim_test"}).sort("updatedAt", -1)
    tickets_before = await cursor.to_list(10)
    for i, t in enumerate(tickets_before, 1):
        print(f"  #{i}: {t['title']}")
        print(f"       updatedAt: {t['updatedAt']}")
        print(f"       alertsCount: {t['alertsCount']}")

    # ── Step 4: Simulasi alert baru attach ke Tiket A ────────────────────
    # Content fingerprint SAMA → dedup → link ke Tiket A
    t_alert = now.isoformat()
    alert_doc = {
        "alertId": "alt-sim00001",
        "ticketId": str(idA),
        "workspaceId": WORKSPACE_ID,
        "projectId": PROJECT_ID,
        "serviceName": SERVICE,
        "contentFp": docA["contentFp"],
        "name": ALERT_NAME,
        "severity": "warning",
        "source": "sim_test",
        "traceIds": ["trace_sim_abc123"],
        "occurredAt": t_alert,
        "createdAt": t_alert,
    }
    await db.ticket_alerts.insert_one(alert_doc)
    print(f"\nAlert alt-sim00001 created → linked to Tiket A")

    # Update Tiket A (seperti attach_alert_to_ticket)
    update_result = await db.tickets.find_one_and_update(
        {"_id": idA},
        {
            "$inc": {"alertsCount": 1},
            "$set": {"lastAlertAt": t_alert, "updatedAt": t_alert},
        },
        return_document=True,
    )
    print(f"Tiket A updatedAt updated to: {t_alert}")
    print(f"Tiket A alertsCount: {update_result['alertsCount']}")

    # ── Step 5: Cek urutan SESUDAH ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("URUTAN SESUDAH alert baru attach ke Tiket A")
    print("=" * 60)
    cursor = db.tickets.find({"source": "sim_test"}).sort("updatedAt", -1)
    tickets_after = await cursor.to_list(10)
    for i, t in enumerate(tickets_after, 1):
        print(f"  #{i}: {t['title']}")
        print(f"       updatedAt: {t['updatedAt']}")
        print(f"       alertsCount: {t['alertsCount']}")

    # ── Step 6: Verifikasi ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VERIFIKASI")
    print("=" * 60)
    top = tickets_after[0]
    if str(top["_id"]) == str(idA):
        print("  ✅ Tiket A SEKARANG di posisi #1 (paling baru)")
        print(f"     → updatedAt {top['updatedAt']}")
        print(f"     → alertsCount {top['alertsCount']}")
        print("  ✅ ALERT ATTACH BERHASIL MEMINDAHKAN POSISI TIKET")
    else:
        print("  ❌ urutan tidak berubah")

    # Cleanup
    await db.tickets.delete_many({"source": "sim_test"})
    await db.ticket_alerts.delete_many({"source": "sim_test"})
    print("\n=== Cleanup done ===")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
