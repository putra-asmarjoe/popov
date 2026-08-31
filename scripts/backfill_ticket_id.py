"""Backfill ticket_id top-level di request_logs (War Room Fix 1).

Sebelum Fix 1, ticket_id hanya ada di nested `investigation_state.ticket_id`
(web chat only). War Room meng-query `request_logs.ticket_id` top-level,
jadi run lama perlu di-backfill. Idempotent — dokumen yang sudah punya
ticket_id top-level dilewati.

Jalankan: ./venv/bin/python scripts/backfill_ticket_id.py [--dry-run]
"""
import asyncio
import sys


async def main(dry_run: bool) -> None:
    from services.mongodb_client import get_db

    db = get_db()
    query = {
        "investigation_state.ticket_id": {"$exists": True, "$ne": ""},
        "ticket_id": {"$in": [None, ""]},
    }
    cursor = db["request_logs"].find(
        query, {"request_id": 1, "investigation_state.ticket_id": 1}
    )
    patched = skipped = 0
    async for log in cursor:
        tid = (log.get("investigation_state") or {}).get("ticket_id", "")
        if not tid:
            skipped += 1
            continue
        label = "DRY" if dry_run else "SET"
        print(f"  {label} {log.get('request_id')} -> ticket_id={tid}")
        if not dry_run:
            await db["request_logs"].update_one(
                {"_id": log["_id"]}, {"$set": {"ticket_id": tid}}
            )
        patched += 1
    print(
        f"Selesai: {patched} request_logs {'(dry-run)' if dry_run else 'dipatch'}, "
        f"{skipped} dilewati"
    )


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))