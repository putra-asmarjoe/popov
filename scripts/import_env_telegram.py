"""
Fix #39 — Migrasi one-shot: kredensial Telegram .env → channel DB pertama.

Env lama (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) sudah dihapus total dari
config/settings.py. Jalankan script ini SEKALI sebelum upgrade bila .env masih
memuat keduanya — kredensial diubah menjadi channel `notification_targets`
milik workspace yang ditunjuk, sehingga polling & pengiriman lanjut jalan
tanpa bot mati.

Pemakaian:
    python scripts/import_env_telegram.py --workspace-id <ObjectId> \
        [--name "Bot Legacy"] [--project-id <ObjectId>] [--db popovagent_db]

- Token divalidasi getMe dulu (gagal → abort, tidak menulis apa pun).
- Idempotent: token+chat sama yang sudah ada di workspace → skip.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId  # noqa: E402

from config.settings import settings  # noqa: E402
from services.mongodb_client import close as close_mongo, get_db  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import .env Telegram creds → notification channel DB (Fix #39)")
    parser.add_argument("--workspace-id", required=True, help="ObjectId workspace pemilik channel")
    parser.add_argument("--name", default="Telegram Bot (migrated)")
    parser.add_argument("--project-id", default=None, help="Opsional: link channel ke project ini")
    parser.add_argument("--db", default=None, help="Override nama database (default dari settings)")
    args = parser.parse_args()

    token = (getattr(settings, "telegram_bot_token", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    chat = (getattr(settings, "telegram_chat_id", "") or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat:
        print("Tidak ada TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID di env — tidak ada yang perlu dimigrasi.")
        return 0

    from services.notification_store import verify_bot_token
    probe = await verify_bot_token(token)
    if not probe.get("ok"):
        print(f"ABORT: bot_token tidak valid: {probe.get('error')}")
        return 1
    print(f"getMe OK → @{probe.get('username')} (bot_id={probe.get('bot_id')})")

    db = get_db(db_name=args.db)

    ws = await db["workspaces"].find_one({"_id": ObjectId(args.workspace_id)})
    if ws is None:
        print(f"ABORT: workspace '{args.workspace_id}' tidak ditemukan")
        await close_mongo()
        return 1

    existing = await db["notification_targets"].find_one(
        {"workspace_id": args.workspace_id,
         "channel": "telegram",
         "config.telegram.bot_token": token,
         "config.telegram.chat_id": chat}
    )
    if existing:
        print(f"SKIP: channel identik sudah ada → {existing['notif_id']} ({existing.get('name')})")
        await close_mongo()
        return 0

    from services.notification_store import generate_notif_id, record_health

    now = datetime.now(timezone.utc)
    doc = {
        "notif_id": generate_notif_id(),
        "name": args.name,
        "channel": "telegram",
        "workspace_id": args.workspace_id,
        "project_ids": [args.project_id] if args.project_id else [],
        "config": {"telegram": {"bot_token": token, "chat_id": chat}},
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    await db["notification_targets"].insert_one(doc)
    await record_health(doc["notif_id"], True, probe.get("username"))
    print(f"OK: channel dibuat → {doc['notif_id']} ({args.name}) ws={args.workspace_id}")
    print("Hapus TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID dari .env setelah verifikasi bot hidup.")
    await close_mongo()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
