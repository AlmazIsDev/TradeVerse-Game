"""Realtime через WebSocket.

Клиент подключается к /ws?token=<JWT>. Сервер шлёт события конкретному игроку
(уведомления, заявки в компанию, изменение баланса) и широковещательно
(рынок, лидерборд). Polling на фронтенде остаётся резервным механизмом.
"""
import asyncio
import logging

from bson import ObjectId

from database import get_db


async def _clicker_snapshot(user_id: str):
    from clicker import collect_passive_clicks

    db = get_db()
    await collect_passive_clicks(db, user_id)
    progress = await db.clicker_progress.find_one({"userId": user_id}, {"multiplier": 1}) or {}
    holding = await db.crypto_holdings.find_one({"userId": user_id, "symbol": "CLICKS"}, {"quantity": 1}) or {}
    return {"type": "clicker_balance", "clicks": int(float(holding.get("quantity", 0) or 0)),
            "clickPower": int(progress.get("multiplier", 1) or 1)}


MAX_WS_RECEIVE_WAIT_S = 1


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
        logger.warning("ws push failed: %s", exc, exc_info=True)


async def broadcast(message: dict):
    try:
        await manager.broadcast(message)
    except Exception as exc:
        logger.warning("ws broadcast failed: %s", exc, exc_info=True)


async def push_to_admins(db, message: dict):
    """Отправить событие только пользователям с ролью admin (не всем игрокам).

    JWT не содержит роль (только sub), поэтому список админов ищем в БД на
    момент отправки — это дешевле, чем помечать соединения ролью при коннекте
    и держать её в синхронизации.
    """
    try:
        async for admin in db.users.find({"role": "admin"}, {"_id": 1}):
            await push_to_user(str(admin["_id"]), message)
    except Exception as exc:
        logger.warning("ws push_to_admins failed: %s", exc, exc_info=True)


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
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=MAX_WS_RECEIVE_WAIT_S)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json(await _clicker_snapshot(user_id))
                except Exception:
                    manager.disconnect(user_id, websocket)
                    break
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
