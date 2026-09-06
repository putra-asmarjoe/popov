#!/usr/bin/env python3
"""
Backfill: tambah field serviceIds ke tiket existing.

Tiket yang sudah punya serviceName tapi belum punya serviceIds → set
serviceIds=[serviceName]. Idempotent: skip jika serviceIds sudah terisi.

Usage:
  python scripts/backfill_ticket_service_ids.py --dry-run   # lihat dulu
  python scripts/backfill_ticket_service_ids.py              # eksekusi
"""
import argparse
import asyncio
from services.mongodb_client import get_db


async def main(dry_run: bool = False):
    db = get_db()
    # Tiket yang punya serviceName tapi serviceIds tidak ada atau kosong
    query = {
        "serviceName": {"$ne": None, "$exists": True, "$ne": ""},
    }
    count = await db["tickets"].count_documents(query)
    print(f"Kandidat tiket (punya serviceName): {count}")

    cursor = db["tickets"].find(query)
    updated = 0
    skipped = 0
    async for doc in cursor:
        # Skip jika serviceIds sudah terisi
        if doc.get("serviceIds"):
            skipped += 1
            continue
        svc = doc.get("serviceName")
        tid = str(doc["_id"])
        if not svc:
            skipped += 1
            continue
        if dry_run:
            print(f"  [DRY-RUN] {doc.get('key','?')}-{doc.get('ticketNumber')}: serviceIds=[{svc}]")
            updated += 1
            continue
        result = await db["tickets"].update_one(
            {"_id": doc["_id"]},
            {"$set": {"serviceIds": [svc]}},
        )
        if result.modified_count:
            print(f"  ✓ {doc.get('key','?')}-{doc.get('ticketNumber')}: serviceIds=[{svc}]")
            updated += 1

    print(f"\nDone: {updated} updated, {skipped} skipped (sudah ada serviceIds)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill serviceIds ke tiket existing")
    parser.add_argument("--dry-run", action="store_true", help="Tampilkan apa yg diubah tanpa write")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
