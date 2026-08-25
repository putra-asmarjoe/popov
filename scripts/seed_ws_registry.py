"""
Seed `workspace_service_registry` dari sumber MURNI DB (agent_docs) + optional db_config.

Jalankan: ./venv/bin/python scripts/seed_ws_registry.py <workspace_id> [--delete]
          ./venv/bin/python scripts/seed_ws_registry.py <workspace_id> --db-config service_db_configs.backup.json

Idempotent: service_id yang sudah ada di registry workspace di-skip.
--db-config <file.json>: lampirkan koneksi DB (db_config) ke service yang cocok —
  dipakai utk migrasi config legacy `service_db_configs.backup.json` → DB (Fix #46).

Legacy: TIDAK lagi membaca `service_collection_map.json`/`service_db_configs.json`
(file sudah dihapus — sumber service = agent_docs).
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(ws_id: str, delete_first: bool = False, db_config_file: Optional[str] = None) -> None:
    from services.mongodb_client import get_db
    from services.workspace_service_registry import (
        WS_SERVICE_REGISTRY_COLLECTION,
        create_item,
    )
    from services.doc_loader import list_all_services

    svc_map = await list_all_services()  # agent_docs (DB)

    # db_config optional dari file legacy (migrasi one-shot)
    extra_db: dict = {}
    if db_config_file:
        p = Path(db_config_file)
        if not p.exists():
            print(f"[seed] ⚠️  db-config file tidak ditemukan: {p}")
        else:
            extra_db = json.loads(p.read_text(encoding="utf-8")) or {}
            print(f"[seed] load {len(extra_db)} db_config dari {p.name}")

    coll = get_db()[WS_SERVICE_REGISTRY_COLLECTION]
    if delete_first:
        r = await coll.delete_many({"workspace_id": ws_id})
        print(f"[seed] deleted existing {r.deleted_count} rows for ws={ws_id}")

    created = skipped = 0
    for sid, collection in sorted(svc_map.items()):
        exists = await coll.find_one({"workspace_id": ws_id, "service_id": sid})
        if exists:
            skipped += 1
            continue
        db_config = None
        cfg = extra_db.get(sid) or {}
        if cfg.get("uri") and cfg.get("db"):
            db_config = {
                "type": cfg.get("type", "mongodb"),
                "uri": cfg["uri"],
                "db": cfg["db"],
                **({"collection": cfg.get("collection", collection)} if (cfg.get("collection") or collection) else {}),
            }
        try:
            await create_item(
                workspace_id=ws_id,
                service_id=sid,
                label=sid.replace("_", " ").title(),
                db_config=db_config,
            )
            created += 1
            if db_config:
                print(f"[seed] created {sid} (+db_config: {db_config['db']})")
            else:
                print(f"[seed] created {sid} (tanpa db_config)")
        except ValueError as e:
            print(f"[seed] skip {sid}: {e}")
            skipped += 1
    print(f"[seed] done ws={ws_id}: created={created}, skipped={skipped}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/seed_ws_registry.py <workspace_id> [--delete] [--db-config <file.json>]")
        sys.exit(1)
    ws = sys.argv[1]
    del_flag = "--delete" in sys.argv
    cfg_file = None
    if "--db-config" in sys.argv:
        cfg_file = sys.argv[sys.argv.index("--db-config") + 1]
    asyncio.run(main(ws, del_flag, cfg_file))