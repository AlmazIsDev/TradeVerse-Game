"""СМИ: разоблачения компаний.

Владелец актива «Медиахолдинг» может заказать разоблачение против компании
конкурента. За взнос (сгорает) с шансом, растущим от суммы взноса:

- Успех  → доход всех бизнесов ВЛАДЕЛЬЦА компании-цели падает на EXPOSE_HIT
           на EXPOSE_HOURS часов; если у компании есть биржевая акция — её цена
           единоразово проседает на STOCK_HIT.
- Провал → взнос сгорел, а доход бизнесов цели, наоборот, временно РАСТЁТ
           (эффект Стрейзанда): +EXPOSE_BACKFIRE на EXPOSE_HOURS часов.

Дебафф/бафф хранится в коллекции ``company_debuffs`` как множитель ``factor`` с
``expires_at``. Активные множители читаются лениво (как materials_boost у активов),
без фоновой очистки. Взнос НЕ переходит цели — он списывается и «сгорает», поэтому
механику нельзя использовать как скрытый перевод денег.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from auth import get_current_user
from database import get_db
from ledger import EXPENSE, CAT_BUSINESS, adjust_balance, record_transaction
from notifications import push_notification

router = APIRouter(prefix="/api/media", tags=["media"])

MEDIA_SLUG = "media_holding"

# Экономика разоблачения
EXPOSE_MIN_BUDGET = 5000.0        # минимальный взнос
EXPOSE_COOLDOWN_H = 24            # КД на пару заказчик→цель
EXPOSE_HOURS = 12                 # длительность эффекта
EXPOSE_HIT = 0.30                 # успех: −30% к доходу бизнесов владельца цели
EXPOSE_BACKFIRE = 0.15            # провал: +15% доходу цели (эффект Стрейзанда)
STOCK_HIT = 0.15                  # успех: −15% к цене акции компании-цели

# Шанс успеха растёт со взносом: base при минимуме → cap при SCALE и выше.
CHANCE_BASE = 0.40
CHANCE_MAX = 0.85
CHANCE_SCALE = 500000.0           # взнос, при котором достигается близкий к cap шанс


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _success_chance(budget: float) -> float:
    """Линейный рост шанса от взноса, ограниченный [CHANCE_BASE, CHANCE_MAX]."""
    extra = (CHANCE_MAX - CHANCE_BASE) * min(1.0, budget / CHANCE_SCALE)
    return round(min(CHANCE_MAX, CHANCE_BASE + extra), 4)


# ── Активные множители дохода (дебафф/бафф от СМИ) ────────────────────────────


async def active_owner_income_factor(db: AsyncIOMotorDatabase, owner_id: str) -> float:
    """Произведение активных множителей дохода для бизнесов данного владельца.

    1.0 — нет активных эффектов. <1.0 — репутационный кризис (успешное
    разоблачение), >1.0 — отскок (провал разоблачения). Истёкшие записи
    игнорируются (ленивая проверка по expires_at)."""
    factor = 1.0
    now = _now()
    async for d in db.company_debuffs.find({"ownerId": str(owner_id)}):
        expires = d.get("expires_at")
        if isinstance(expires, datetime):
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now < expires:
                factor *= float(d.get("factor", 1.0))
    return round(factor, 4)


async def has_media_holding(db: AsyncIOMotorDatabase, user_id: str) -> bool:
    return await db.user_assets.find_one(
        {"userId": str(user_id), "slug": MEDIA_SLUG}
    ) is not None


# ── Schemas ──────────────────────────────────────────────────────────────────


class ExposeBody(BaseModel):
    targetCompanyId: str
    budget: float

    @field_validator("targetCompanyId")
    @classmethod
    def target_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Не указана компания-цель")
        return v

    @field_validator("budget")
    @classmethod
    def budget_ok(cls, v):
        if v is None or v < EXPOSE_MIN_BUDGET:
            raise ValueError(f"Минимальный взнос — ${EXPOSE_MIN_BUDGET:,.0f}")
        if v > 100_000_000:
            raise ValueError("Слишком большой взнос")
        return round(float(v), 2)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status")
async def media_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Есть ли у игрока Медиахолдинг + параметры механики для UI."""
    return {
        "hasMedia": await has_media_holding(db, str(current_user["_id"])),
        "minBudget": EXPOSE_MIN_BUDGET,
        "cooldownHours": EXPOSE_COOLDOWN_H,
        "effectHours": EXPOSE_HOURS,
        "hitPct": EXPOSE_HIT,
        "backfirePct": EXPOSE_BACKFIRE,
        "stockHitPct": STOCK_HIT,
        "chanceBase": CHANCE_BASE,
        "chanceMax": CHANCE_MAX,
        "chanceScale": CHANCE_SCALE,
    }


@router.get("/targets")
async def expose_targets(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Компании, доступные как цель (все, кроме собственной игрока)."""
    uid = str(current_user["_id"])
    out = []
    async for c in db.companies.find({"ownerId": {"$ne": uid}}).limit(100):
        owner = await db.users.find_one({"_id": ObjectId(c["ownerId"])}, {"username": 1}) \
            if ObjectId.is_valid(c["ownerId"]) else None
        out.append({
            "id": str(c["_id"]),
            "name": c["name"],
            "ownerName": owner.get("username") if owner else "—",
            "logo": c.get("logo", ""),
        })
    out.sort(key=lambda x: x["name"].lower())
    return out


@router.get("/feed")
async def media_feed(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Публичная лента разоблачений (успех/провал)."""
    out = []
    async for e in db.media_events.find({}).sort("created_at", -1).limit(30):
        out.append({
            "id": str(e["_id"]),
            "targetCompanyName": e.get("targetCompanyName"),
            "outcome": e.get("outcome"),
            "createdAt": e["created_at"].isoformat() if isinstance(e.get("created_at"), datetime) else None,
        })
    return out


@router.post("/expose")
async def expose_company(
    payload: ExposeBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Заказать разоблачение против компании-цели."""
    uid = str(current_user["_id"])

    if not await has_media_holding(db, uid):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Нужен актив «Медиахолдинг», чтобы заказывать разоблачения")

    if not ObjectId.is_valid(payload.targetCompanyId):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID компании")
    company = await db.companies.find_one({"_id": ObjectId(payload.targetCompanyId)})
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    target_owner_id = company["ownerId"]
    if target_owner_id == uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя разоблачать собственную компанию")

    # Кулдаун на пару заказчик→цель
    since = _now() - timedelta(hours=EXPOSE_COOLDOWN_H)
    recent = await db.media_events.find_one({
        "orderedBy": uid, "targetCompanyId": payload.targetCompanyId,
        "created_at": {"$gte": since},
    })
    if recent:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Разоблачение против этой компании уже заказано недавно")

    # Взнос списывается и «сгорает» (не переходит цели)
    new_balance = await adjust_balance(db, uid, -payload.budget)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для взноса")
    await record_transaction(
        db, uid, EXPENSE, payload.budget, CAT_BUSINESS,
        f"Разоблачение: «{company['name']}»", balance_after=new_balance,
        meta={"targetCompanyId": payload.targetCompanyId, "kind": "media_expose"},
    )

    chance = _success_chance(payload.budget)
    success = random.random() < chance
    expires = _now() + timedelta(hours=EXPOSE_HOURS)

    if success:
        factor = round(1.0 - EXPOSE_HIT, 4)
        outcome = "success"
    else:
        factor = round(1.0 + EXPOSE_BACKFIRE, 4)
        outcome = "fail"

    await db.company_debuffs.insert_one({
        "companyId": payload.targetCompanyId,
        "ownerId": target_owner_id,
        "factor": factor,
        "outcome": outcome,
        "created_at": _now(),
        "expires_at": expires,
    })

    stock_hit = None
    if success:
        stock_hit = await _hit_company_stock(db, payload.targetCompanyId)

    await db.media_events.insert_one({
        "orderedBy": uid,
        "targetCompanyId": payload.targetCompanyId,
        "targetCompanyName": company["name"],
        "budget": payload.budget,
        "chance": chance,
        "outcome": outcome,
        "created_at": _now(),
    })

    # Уведомляем владельца цели
    if outcome == "success":
        await push_notification(
            db, target_owner_id, "media", "Репутационный кризис",
            f"СМИ выпустили разоблачение о «{company['name']}». Доход ваших бизнесов "
            f"снижен на {int(EXPOSE_HIT * 100)}% на {EXPOSE_HOURS} ч.",
            data={"companyId": payload.targetCompanyId},
        )
    else:
        await push_notification(
            db, target_owner_id, "media", "Провальное разоблачение",
            f"Разоблачение о «{company['name']}» провалилось — интерес к вам вырос: "
            f"доход бизнесов +{int(EXPOSE_BACKFIRE * 100)}% на {EXPOSE_HOURS} ч.",
            data={"companyId": payload.targetCompanyId},
        )

    return {
        "outcome": outcome,
        "chance": chance,
        "balance": new_balance,
        "effectHours": EXPOSE_HOURS,
        "stockHit": stock_hit,
    }


async def _hit_company_stock(db: AsyncIOMotorDatabase, company_id: str) -> Optional[dict]:
    """Единоразово роняет цену акции компании (если размещена) на STOCK_HIT."""
    stock = await db.stocks.find_one({"companyId": company_id})
    if not stock:
        return None
    price = float(stock.get("price", 0.0))
    if price <= 0:
        return None
    new_price = round(max(0.01, price * (1.0 - STOCK_HIT)), 2)
    await db.stocks.update_one(
        {"_id": stock["_id"]},
        {"$set": {
            "price": new_price,
            "change": round(new_price - price, 2),
            "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
            "updated_at": _now(),
        }},
    )
    try:
        from market_data import MarketDataService
        await MarketDataService.record_snapshot(db, "stock", stock["symbol"], new_price, force=True)
    except Exception:
        pass
    try:
        from ws import broadcast
        await broadcast({
            "type": "price_tick", "market": "stock", "symbol": stock["symbol"],
            "price": new_price,
            "changePercent": round((new_price - price) / price * 100, 2) if price else 0.0,
        })
    except Exception:
        pass
    return {"symbol": stock["symbol"], "priceBefore": price, "priceAfter": new_price}
