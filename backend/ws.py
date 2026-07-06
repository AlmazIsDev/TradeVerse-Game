"""Realtime через WebSocket.

Клиент подключается к /ws?token=<JWT>. Сервер шлёт события конкретному игроку
(уведомления, заявки в компанию, изменение баланса) и широковещательно
(рынок, лидерборд). Polling на фронтенде остаётся резервным механизмом.
"""
import logging

from bson import ObjectId
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from auth import decode_access_token

logger = logging.getLogger("tradeverse.ws")
router = APIRouter()


class ConnectionManager:
    """Хранит активные WebSocket-подключения по пользователям."""

    def __init__(self):
        self.active: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: str, ws: WebSocket):
        conns = self.active.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self.active.pop(user_id, None)

    async def send(self, user_id: str, message: dict):
        for ws in list(self.active.get(user_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(user_id, ws)

    async def broadcast(self, message: dict):
        for uid, conns in list(self.active.items()):
            for ws in list(conns):
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(uid, ws)


manager = ConnectionManager()


async def push_to_user(user_id, message: dict):
    """Отправить событие конкретному игроку (safe — не бросает исключений)."""
    try:
        await manager.send(str(user_id), message)
    except Exception as exc:
        logger.debug("ws push failed: %s", exc)


async def broadcast(message: dict):
    try:
        await manager.broadcast(message)
    except Exception as exc:
        logger.debug("ws broadcast failed: %s", exc)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    user_id = None
    if token:
        try:
            payload = decode_access_token(token)
            uid = payload.get("sub")
            if uid and ObjectId.is_valid(uid):
                user_id = uid
        except Exception:
            user_id = None
    if not user_id:
        await websocket.close(code=1008)
        return

    await manager.connect(user_id, websocket)
    try:
        await websocket.send_json({"type": "connected"})
        while True:
            # Держим соединение; клиент шлёт ping-строки.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
