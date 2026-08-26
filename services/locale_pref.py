"""
Locale resolver untuk notifikasi backend — ikut preferensi OWNER workspace.

Bahasa disimpan per-USER di users.locale_preference ("en"|"id", Fix #91).
Workspace tidak punya setting bahasa sendiri, jadi pesan yang dikirim atas nama
se workspace (broadcast Telegram alert watchdog) memakai bahasa owner-nya.
Fallback "en" untuk semua kondisi abnormal — pesan alert TIDAK BOLEH gagal
hanya karena resolusi locale bermasalah.
"""

import logging

logger = logging.getLogger(__name__)

VALID_LOCALES = {"en", "id"}
DEFAULT_LOCALE = "en"


async def get_workspace_locale(workspace_id) -> str:
    """Resolve locale workspace via owner → users.locale_preference. Selalu return valid."""
    try:
        if not workspace_id:
            return DEFAULT_LOCALE
        from services.mongodb_client import get_db

        ws = await get_db()["workspaces"].find_one(
            {"_id": workspace_id}, {"ownerId": 1}
        )
        if not ws:
            # workspace_id bisa berupa string ObjectId dari state lama — coba konversi
            try:
                from bson import ObjectId

                ws = await get_db()["workspaces"].find_one(
                    {"_id": ObjectId(str(workspace_id))}, {"ownerId": 1}
                )
            except Exception:
                return DEFAULT_LOCALE
        if not ws:
            return DEFAULT_LOCALE

        owner = await get_db()["users"].find_one(
            {"_id": ws.get("ownerId")}, {"locale_preference": 1}
        )
        locale = (owner or {}).get("locale_preference")
        return locale if locale in VALID_LOCALES else DEFAULT_LOCALE
    except Exception as e:
        logger.warning(f"[locale-pref] resolve gagal (non-fatal): {e}")
        return DEFAULT_LOCALE
