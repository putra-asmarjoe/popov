"""
Notifications router — FE-4.
- GET  /notifications?unreadOnly=&limit=  → list + jumlah unread
- POST /notifications/read {ids?: []}     → tandai terbaca (kosong = semua)
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.deps import get_current_user
from services.notification_store import list_for_user, mark_read, unread_count

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


class MarkReadRequest(BaseModel):
    ids: Optional[List[str]] = None


@router.get("")
async def my_notifications(
    unreadOnly: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    docs = await list_for_user(user_id, unread_only=unreadOnly, limit=limit)
    return {
        "notifications": [
            {
                "id": str(d["_id"]),
                "type": d.get("type", ""),
                "title": d.get("title", ""),
                "payload": d.get("payload", {}),
                "readAt": d.get("readAt"),
                "createdAt": d.get("createdAt"),
            }
            for d in docs
        ],
        "unread": await unread_count(user_id),
    }


@router.post("/read")
async def read_notifications(
    body: MarkReadRequest,
    current_user: dict = Depends(get_current_user),
):
    updated = await mark_read(str(current_user["_id"]), body.ids)
    return {"updated": updated}
