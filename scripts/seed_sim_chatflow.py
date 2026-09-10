"""Seed tiket khusus simulasi chatflow testing.

Membuat 8 tiket baru (4 cluster-pro, 4 proxmox) dengan tag 'sim-test'
untuk dijadikan target chat dalam sim_chatflow_review.py.

Jalan dari project root: python scripts/seed_sim_chatflow.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mongodb_client import get_db
from datetime import datetime, timezone

DB = None

SEED_TICKETS = [
    # ── cluster-pro ──
    {
        "project_key": "cluster-pro",
        "title": "High error rate on shop-gateway after deploy",
        "description": "Error rate spiked to 8x baseline immediately after deployment v2.4.1. Service: shop-gateway. Tags: watchdog, deploy.",
        "severity": "critical",
        "service_name": "shop-gateway",
        "status": "open",
        "tags": ["watchdog", "deploy", "sim-test"],
        "slug": "SIM-CP-1",
    },
    {
        "project_key": "cluster-pro",
        "title": "Payment provider timeout on /checkout",
        "description": "Intermittent 30s timeouts to Midtrans payment gateway. Affecting ~15% of checkout requests. Service: shop-order.",
        "severity": "high",
        "service_name": "shop-order",
        "status": "open",
        "tags": ["payment", "timeout", "sim-test"],
        "slug": "SIM-CP-2",
    },
    {
        "project_key": "cluster-pro",
        "title": "MongoDB connection pool exhausted — user-service",
        "description": "Connection pool hitting limit (500/500). New requests queuing. Service: user-service.",
        "severity": "high",
        "service_name": "user-service",
        "status": "in_progress",
        "tags": ["mongodb", "connection-pool", "sim-test"],
        "slug": "SIM-CP-3",
    },
    {
        "project_key": "cluster-pro",
        "title": "HPA maxed out — notification-service under traffic spike",
        "description": "HPA at 10/10 replicas. CPU 95%. Response time degrading. Service: notification-service.",
        "severity": "medium",
        "service_name": "notification-service",
        "status": "resolved",
        "tags": ["hpa", "scaling", "sim-test"],
        "slug": "SIM-CP-4",
    },
    # ── proxmox ──
    {
        "project_key": "proxmox",
        "title": "Kafka consumer lag spiking — order-events topic",
        "description": "Consumer group order-processor lag reached 120k messages. Throughput dropped from 10k/s to 2k/s. Service: kafka.",
        "severity": "critical",
        "service_name": "kafka",
        "status": "open",
        "tags": ["kafka", "consumer-lag", "sim-test"],
        "slug": "SIM-PX-1",
    },
    {
        "project_key": "proxmox",
        "title": "StarRocks query timeout on analytics dashboard",
        "description": "Queries > 30s on materialized views. FE query timeout errors. Service: starrocks.",
        "severity": "high",
        "service_name": "starrocks",
        "status": "open",
        "tags": ["starrocks", "timeout", "sim-test"],
        "slug": "SIM-PX-2",
    },
    {
        "project_key": "proxmox",
        "title": "Airflow DAG failure — daily-etl-pipeline",
        "description": "daily-etl-pipeline DAG failed at task extract_orders. 3 consecutive failures. Service: airflow.",
        "severity": "high",
        "service_name": "airflow",
        "status": "in_progress",
        "tags": ["airflow", "dag-failure", "sim-test"],
        "slug": "SIM-PX-3",
    },
    {
        "project_key": "proxmox",
        "title": "Kafka broker disk usage 87% — data retention risk",
        "description": "Broker disk at 87%. At current rate, full in ~6 hours. Retention policy may need adjustment. Service: kafka.",
        "severity": "medium",
        "service_name": "kafka",
        "status": "resolved",
        "tags": ["kafka", "disk", "sim-test"],
        "slug": "SIM-PX-4",
    },
]


async def seed(workspace_id: str, project_map: dict) -> dict:
    """Seed tickets → return {slug: ticket_doc} mapping."""
    global DB
    DB = get_db()
    now = datetime.now(timezone.utc)
    created = {}

    for t in SEED_TICKETS:
        proj_key = t["project_key"]
        project_id = project_map.get(proj_key)
        if not project_id:
            print(f"  ⚠ skip {t['slug']}: project '{proj_key}' not found")
            continue

        doc = {
            "title": t["title"],
            "description": t["description"],
            "severity": t["severity"],
            "status": t["status"],
            "projectId": project_id,
            "workspaceId": workspace_id,
            "serviceName": t["service_name"],
            "serviceIds": [t["service_name"]],
            "tags": t["tags"],
            "source": "sim-test",
            "kind": "incident",
            "environment": "production",
            "createdAt": now,
            "updatedAt": now,
            "createdBy": "sim-agent",
            "progressLog": [],
            "alerts": [],
        }

        result = await DB["tickets"].insert_one(doc)
        doc["_id"] = result.inserted_id
        created[t["slug"]] = doc
        print(f"  ✓ {t['slug']}: {t['title'][:50]}")

    return created


async def cleanup(workspace_id: str):
    """Delete all tickets with tag 'sim-test'."""
    global DB
    DB = get_db()
    result = await DB["tickets"].delete_many({
        "workspaceId": workspace_id,
        "tags": "sim-test",
    })
    print(f"  Cleaned up {result.deleted_count} sim-test tickets")


if __name__ == "__main__":
    print("Seed script — run from main script (sim_chatflow_review.py)")
    print("Or import and call seed(workspace_id, project_map)")
