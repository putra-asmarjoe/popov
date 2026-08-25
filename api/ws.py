"""
WebSocket router — FE-4 Realtime.
/api/v1/ws/{project_id}?token=  → join channel "project:{id}" + "user:{userId}".
Auth via query token (browser WebSocket tidak bisa set header).
"""
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from services.event_bus import bus
from services.user_store import decode_token, get_user
from services.workspace_store import (
    find_project_by_id,
    find_workspace_by_id,
    get_membership,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/{project_id}")
async def project_websocket(websocket: WebSocket, project_id: str, token: str = Query(default="")):
    """Satu koneksi menerima event tiket project + notifikasi user."""
    user = None
    try:
        payload = decode_token(token)
        if payload:
            user = await get_user(payload.get("sub", ""))
    except Exception as e:
        logger.warning(f"WS auth decode failed: {e}")

    authorized = False
    if user is not None:
        project = await find_project_by_id(project_id)
        if project is not None:
            ws = await find_workspace_by_id(project.get("workspaceId", ""))
            if ws is not None and get_membership(ws, str(user["_id"])):
                authorized = True

    if not authorized:
        await websocket.accept()
        await websocket.send_json({"type": "error", "payload": "unauthorized"})
        await websocket.close(code=4401)
        return

    # Accept SEKALI, lalu join dua channel: event tiket project + notifikasi user
    await websocket.accept()
    project_channel = f"project:{project_id}"
    user_channel = f"user:{str(user['_id'])}"
    bus.connect(project_channel, websocket)
    bus.connect(user_channel, websocket)
    await websocket.send_json({"type": "connected", "payload": {"projectId": project_id}})

    try:
        while True:
            # Client hanya kirim ping — abaikan selebihnya
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WS error: {e}")
    finally:
        bus.disconnect(project_channel, websocket)
        bus.disconnect(user_channel, websocket)
