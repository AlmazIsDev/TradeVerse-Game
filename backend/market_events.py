"""Мировые экономические события.

Каждое событие временно смещает целевые цены отраслей и коэффициенты доходов.
События влияют на динамический рынок активов (assets._drift_asset_market) и на
доходы/аренду/крипту. Могут запускаться автоматически (редко) или вручную
администратором. Хранятся в коллекции ``market_events`` с историей.
"""
import random
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from auth import require_admin
from database import get_db

router = APIRouter(prefix="/api/admin/economy", tags=["economy-events"])

# effects: сдвиг целевой цены по типу актива ("realestate"/"business"/"car"/"all")
#          или по конкретному slug. income/rental/crypto — временные множители.
EVENT_TYPES = {
    "crisis":            {"name": "Экономический кризис",     "icon": "📉", "effects": {"all": -0.15}, "income": -0.20, "duration_h": 12},
    "construction_boom": {"name": "Строительный бум",         "icon": "🏗️", "effects": {"realestate": 0.20}, "duration_h": 10},
    "tourist_season":    {"name": "Туристический сезон",       "icon": "🏖️", "effects": {"realestate": 0.10, "hotel": 0.25}, "rental": 0.20, "duration_h": 24},
    "fuel_prices":       {"name": "Рост цен на топливо",       "icon": "⛽", "effects": {"car": -0.12, "business": -0.05}, "duration_h": 10},
    "banking_reform":    {"name": "Банковская реформа",        "icon": "🏦", "effects": {}, "income": 0.10, "duration_h": 14},
    "industrial_growth": {"name": "Промышленный рост",         "icon": "🏭", "effects": {"business": 0.15}, "income": 0.08, "duration_h": 12},
    "tech_breakthrough": {"name": "Технологический прорыв",    "icon": "🚀", "effects": {"business": 0.10}, "crypto": 0.06, "duration_h": 12},
    "material_shortage": {"name": "Дефицит материалов",        "icon": "📦", "effects": {"realestate": 0.15, "car": 0.10}, "duration_h": 8},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if isinstance(dt, datetime) and dt.tzinfo is None else dt


async def start_event(db: AsyncIOMotorDatabase, etype: str, source: str = "admin") -> dict:
    spec = EVENT_TYPES.get(etype)
    if not spec:
        raise ValueError(f"Unknown event type: {etype}")
    now = _now()
    doc = {
        "type": etype, "name": spec["name"], "icon": spec.get("icon", "🌐"),
        "effects": spec.get("effects", {}),
        "income": spec.get("income", 0.0), "rental": spec.get("rental", 0.0), "crypto": spec.get("crypto", 0.0),
        "started_at": now, "ends_at": now + timedelta(hours=spec.get("duration_h", 12)),
        "active": True, "source": source,
    }
    result = await db.market_events.insert_one(doc)
    doc["_id"] = result.inserted_id
    # Realtime-оповещение всех клиентов о новом мировом событии.
    try:
        from ws import broadcast
        await broadcast({"type": "event", "name": doc["name"], "icon": doc.get("icon")})
    except Exception:
        pass
    return doc


async def get_active_events(db: AsyncIOMotorDatabase) -> list[dict]:
    """Активные события (просроченные помечаются завершёнными)."""
    now = _now()
    await db.market_events.update_many(
        {"active": True, "ends_at": {"$lte": now}}, {"$set": {"active": False}},
    )
    return [e async for e in db.market_events.find({"active": True})]


async def maybe_autostart(db: AsyncIOMotorDatabase):
    """Изредка запускает случайное событие, если сейчас ни одного нет."""
    if await db.market_events.count_documents({"active": True}) > 0:
        return
    if random.random() < 0.08:
        await start_event(db, random.choice(list(EVENT_TYPES)), source="auto")


async def event_shifts(db: AsyncIOMotorDatabase) -> dict:
    """Сводное влияние активных событий: сдвиги цен + множители доходов."""
    shifts: dict[str, float] = {}
    income, rental, crypto = 1.0, 1.0, 1.0
    for e in await get_active_events(db):
        for key, val in (e.get("effects") or {}).items():
            shifts[key] = shifts.get(key, 0.0) + float(val)
        income *= 1 + e.get("income", 0.0)
        rental *= 1 + e.get("rental", 0.0)
        crypto *= 1 + e.get("crypto", 0.0)
    return {"shifts": shifts, "income": round(income, 4), "rental": round(rental, 4), "crypto": round(crypto, 4)}


def slug_event_shift(shifts: dict, slug: str, atype: str) -> float:
    """Сдвиг цены для конкретного объекта из карты shifts (slug/type/all)."""
    return shifts.get(slug, 0.0) + shifts.get(atype, 0.0) + shifts.get("all", 0.0)


def _serialize(e: dict) -> dict:
    return {
        "id": str(e["_id"]),
        "type": e.get("type"), "name": e.get("name"), "icon": e.get("icon"),
        "effects": e.get("effects", {}),
        "income": e.get("income", 0.0), "rental": e.get("rental", 0.0), "crypto": e.get("crypto", 0.0),
        "source": e.get("source"),
        "active": bool(e.get("active")),
        "startedAt": _aware(e["started_at"]).isoformat() if isinstance(e.get("started_at"), datetime) else None,
        "endsAt": _aware(e["ends_at"]).isoformat() if isinstance(e.get("ends_at"), datetime) else None,
    }


# ── Admin endpoints ──────────────────────────────────────────────────────────


class StartEvent(BaseModel):
    type: str


@router.get("/events")
async def list_events(_admin=Depends(require_admin), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Активные события, история и доступные типы (для админ-панели)."""
    await get_active_events(db)  # авто-завершение просроченных
    active = [_serialize(e) async for e in db.market_events.find({"active": True}).sort("started_at", -1)]
    history = [_serialize(e) async for e in db.market_events.find({"active": False}).sort("ends_at", -1).limit(20)]
    types = [{"type": k, "name": v["name"], "icon": v.get("icon"), "durationH": v.get("duration_h", 12)}
             for k, v in EVENT_TYPES.items()]
    return {"active": active, "history": history, "types": types}


@router.post("/events/start")
async def admin_start_event(
    payload: StartEvent,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.type not in EVENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный тип события")
    doc = await start_event(db, payload.type, source="admin")
    return _serialize(doc)


@router.post("/events/{event_id}/stop")
async def admin_stop_event(
    event_id: str,
    _admin=Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not ObjectId.is_valid(event_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID")
    doc = await db.market_events.find_one({"_id": ObjectId(event_id)})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    await db.market_events.update_one(
        {"_id": ObjectId(event_id)}, {"$set": {"active": False, "ends_at": _now()}},
    )
    # Realtime-оповещение всех клиентов о завершении мирового события.
    try:
        from ws import broadcast
        await broadcast({"type": "event_ended", "name": doc.get("name"), "icon": doc.get("icon")})
    except Exception:
        pass
    return {"ok": True}
