#!/usr/bin/env python3
"""
Backfill Fix #246: canonicalize serviceName/serviceIds tiket lama ke serviceId
library kanonik (strip suffix devops "-apps"/prefix "prod-", normalisasi dash).

Tiket yang punya serviceName/serviceIds non-kanonik (mis. "lovvit-release-coupon-apps"
padahal library "lovvit-release-coupon") → di-update ke bentuk kanonik agar routing
chat tiket / incident_router / filter ?service= konsisten.

Idempotent: nilai yang sudah kanonik / tak dikenal library TIDAK disentuh.
Alias raw→canonical dicatat (service_aliases) — auto-resolve alert serupa ke depan.

Usage:
  python scripts/backfill_ticket_canonical_service.py --dry-run
  python scripts/backfill_ticket_canonical_service.py
"""
import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from services.mongodb_client import get_db  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="tampilkan saja, tanpa update")
    args = parser.parse_args()

    db = get_db()
    from services.service_name_utils import canonical_service
    from services.ticket_store import library_service_ids, _record_service_alias

    libs = await library_service_ids()
    if not libs:
        print("service_library kosong — tidak bisa canonicalize")
        return

    candidates = await db["tickets"].find({
        "$or": [
            {"serviceName": {"$ne": None, "$exists": True, "$ne": ""}},
            {"serviceIds": {"$exists": True, "$ne": []}},
        ]
    }).to_list(1000)

    updated = skipped = 0
    for t in candidates:
        tnum = t.get("ticketNumber", "?")
        old_name = (t.get("serviceName") or "").strip() or None
        old_ids = [s for s in (t.get("serviceIds") or []) if s]
        if not old_ids and old_name:
            old_ids = [old_name]

        canon_name = canonical_service(old_name, libs) if old_name else None
        canon_ids = []
        changed_ids = False
        for s in old_ids:
            c = canonical_service(s, libs)
            resolved = c if c and c != s else s
            if resolved not in canon_ids:  # dedup (raw + kanonik bisa sama)
                canon_ids.append(resolved)
            if c and c != s:
                changed_ids = True
                # belajar alias dari data lama (raw yang ternyata = kanonik)
                await _record_service_alias(s, c)

        name_changed = canon_name is not None and canon_name != old_name
        if not (name_changed or changed_ids):
            skipped += 1
            continue

        updates = {}
        if name_changed:
            updates["serviceName"] = canon_name
        if changed_ids:
            updates["serviceIds"] = canon_ids
        print(f"  {t.get('key','?')}-{tnum}: serviceName {old_name!r}→{canon_name!r} "
              f"serviceIds {old_ids}→{canon_ids}")
        if not args.dry_run:
            await db["tickets"].update_one({"_id": t["_id"]}, {"$set": updates})
        updated += 1

    print(f"\nDone: {updated} updated, {skipped} skipped (sudah kanonik/tak dikenal)"
          + (" [DRY-RUN]" if args.dry_run else ""))


if __name__ == "__main__":
    asyncio.run(main())
