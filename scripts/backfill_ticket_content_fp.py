"""Backfill contentFp untuk tiket watchdog LAMA (sebelum Fix #86).

Tiket lama tidak punya field `contentFp` → query dedup window
(find_linkable_ticket_by_fingerprint) tidak pernah match, dan alert berikutnya
akan melahirkan TIKET DUPLIKAT. Script ini mengisi contentFp dari title:
    "[ALERT] {service}: {alert_name}"  →  md5(f"{service}|{alert_name}")

Idempotent — tiket yang sudah punya contentFp dilewati.
Jalankan: ./venv/bin/python scripts/backfill_ticket_content_fp.py [--dry-run]
"""
import asyncio
import hashlib
import re
import sys

TITLE_RE = re.compile(r"^\[ALERT\]\s*(?P<svc>.+?)\s*:\s*(?P<name>.+)$")


def content_fp(service: str, alert_name: str) -> str:
    return hashlib.md5(f"{service}|{alert_name}".encode()).hexdigest()


async def main(dry_run: bool) -> None:
    from services.mongodb_client import get_db

    db = get_db()
    query = {"source": "watchdog", "contentFp": {"$in": [None, ""]}, "fingerprint": {"$ne": None}}
    cursor = db["tickets"].find(query)
    patched = skipped = 0
    async for t in cursor:
        m = TITLE_RE.match(t.get("title") or "")
        if not m:
            print(f"  SKIP #{t.get('ticketNumber')} (format title bukan ALERT): {t.get('title')!r}")
            skipped += 1
            continue
        # Kanonik = hitung ulang dari title — HARUS identik dgn auto_ticket
        # (base_fp = md5(f"{service}|{alert_name}")). Fingerprint lama TIDAK dipakai
        # karena dihitung dari payload berbeda-beda antar versi kode.
        fp = content_fp(m.group("svc").strip(), m.group("name").strip())
        label = "DRY" if dry_run else "SET"
        print(f"  {label} #{t.get('ticketNumber')} [{m.group('svc')}] {m.group('name')} -> {fp}")
        if not dry_run:
            await db["tickets"].update_one(
                {"_id": t["_id"]}, {"$set": {"contentFp": fp}}
            )
        patched += 1
    print(f"Selesai: {patched} tiket {'(dry-run)' if dry_run else 'dipatch'}, {skipped} dilewati")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
