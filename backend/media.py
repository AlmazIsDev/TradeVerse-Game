"""СМИ: разоблачения компаний и игроков.

Владелец актива «Медиахолдинг» заказывает разоблачение против компании-конкурента
ИЛИ конкретного игрока. Взнос списывается сразу и «сгорает». Новость не выходит
мгновенно — она ГОТОВИТСЯ от PREP_MIN до PREP_MAX (30 мин – 2 ч), после чего
планировщик (``sweep_pending_exposes``) разыгрывает исход:

- Успех  → доход всех бизнесов ВЛАДЕЛЬЦА-цели падает на hitPct (15–80%, растёт со
           взносом) на EXPOSE_HOURS часов; если у цели есть биржевая акция — её
           цена единоразово проседает на STOCK_HIT.
- Провал → доход бизнесов цели, наоборот, временно РАСТЁТ (эффект Стрейзанда):
           +EXPOSE_BACKFIRE на EXPOSE_HOURS часов.

Дебафф/бафф хранится в коллекции ``company_debuffs`` как множитель ``factor`` с
``expires_at`` (создаётся только при разыгрывании исхода — до этого эффекта нет).
Активные множители читаются лениво (как materials_boost у активов). Взнос НЕ
переходит цели — он «сгорает», поэтому механику нельзя использовать как скрытый
перевод денег.
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
EXPOSE_HOURS = 12                 # длительность эффекта после выхода новости
EXPOSE_BACKFIRE = 0.15            # провал: +15% доходу цели (эффект Стрейзанда)
STOCK_HIT = 0.15                  # успех: −15% к цене акции компании-цели

# Сила удара (снижение дохода при успехе) растёт со взносом: 15% → 80%.
EXPOSE_HIT_MIN = 0.15
EXPOSE_HIT_MAX = 0.80
EXPOSE_HIT_SCALE = 3_000_000.0    # взнос, при котором удар приближается к максимуму

# Подготовка новости: от 30 минут до 2 часов до выхода.
PREP_MIN_MINUTES = 30
PREP_MAX_MINUTES = 120

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


def _hit_pct(budget: float) -> float:
    """Сила удара по доходу (15–80%), линейно растёт со взносом."""
    extra = (EXPOSE_HIT_MAX - EXPOSE_HIT_MIN) * min(1.0, budget / EXPOSE_HIT_SCALE)
    return round(min(EXPOSE_HIT_MAX, EXPOSE_HIT_MIN + extra), 4)


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
    targetType: str = "company"       # 'company' | 'player'
    targetId: str
    budget: float

    @field_validator("targetType")
    @classmethod
    def type_ok(cls, v):
        v = (v or "company").strip().lower()
        if v not in ("company", "player"):
            raise ValueError("Некорректный тип цели")
        return v

    @field_validator("targetId")
    @classmethod
    def target_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Не указана цель разоблачения")
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
        "hitMinPct": EXPOSE_HIT_MIN,
        "hitMaxPct": EXPOSE_HIT_MAX,
        "hitScale": EXPOSE_HIT_SCALE,
        "backfirePct": EXPOSE_BACKFIRE,
        "stockHitPct": STOCK_HIT,
        "prepMinMinutes": PREP_MIN_MINUTES,
        "prepMaxMinutes": PREP_MAX_MINUTES,
        "chanceBase": CHANCE_BASE,
        "chanceMax": CHANCE_MAX,
        "chanceScale": CHANCE_SCALE,
    }


@router.get("/targets")
async def expose_targets(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Цели разоблачения: компании и игроки (кроме себя).

    Игроки-цели ограничены теми, у кого есть хотя бы один бизнес (иначе бить
    нечем — разоблачение снижает доход именно бизнесов)."""
    uid = str(current_user["_id"])

    companies = []
    async for c in db.companies.find({"ownerId": {"$ne": uid}}).limit(100):
        owner = await db.users.find_one({"_id": ObjectId(c["ownerId"])}, {"username": 1}) \
            if ObjectId.is_valid(c["ownerId"]) else None
        companies.append({
            "id": str(c["_id"]),
            "name": c["name"],
            "ownerName": owner.get("username") if owner else "—",
            "logo": c.get("logo", ""),
        })
    companies.sort(key=lambda x: x["name"].lower())

    # Игроки, владеющие бизнесами (личными) — потенциальные цели.
    biz_owner_ids = await db.user_assets.distinct("userId", {"type": "business"})
    player_ids = [oid for oid in biz_owner_ids if oid and oid != uid]
    players = []
    if player_ids:
        obj_ids = [ObjectId(p) for p in player_ids if ObjectId.is_valid(p)]
        async for u in db.users.find({"_id": {"$in": obj_ids}}, {"username": 1, "avatar": 1}):
            players.append({
                "id": str(u["_id"]),
                "name": u.get("username", "—"),
                "avatar": u.get("avatar"),
            })
        players.sort(key=lambda x: (x["name"] or "").lower())

    return {"companies": companies, "players": players}


@router.get("/feed")
async def media_feed(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Публичная лента разоблачений (готовится / успех / провал)."""
    out = []
    async for e in db.media_events.find({}).sort("created_at", -1).limit(30):
        out.append({
            "id": str(e["_id"]),
            "targetName": e.get("targetName") or e.get("targetCompanyName"),
            "targetType": e.get("targetType", "company"),
            "outcome": e.get("outcome"),
            "resolveAt": e["resolve_at"].isoformat() if isinstance(e.get("resolve_at"), datetime) else None,
            "createdAt": e["created_at"].isoformat() if isinstance(e.get("created_at"), datetime) else None,
        })
    return out


@router.post("/expose")
async def expose_company(
    payload: ExposeBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Заказать разоблачение против компании или игрока (новость готовится 30 мин–2 ч)."""
    uid = str(current_user["_id"])

    if not await has_media_holding(db, uid):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Нужен актив «Медиахолдинг», чтобы заказывать разоблачения")

    # Разрешаем цель в единый вид: владелец (по нему бьётся дебафф), необязательная
    # компания (для удара по акции), отображаемое имя.
    target_company_id: Optional[str] = None
    if payload.targetType == "company":
        if not ObjectId.is_valid(payload.targetId):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID компании")
        company = await db.companies.find_one({"_id": ObjectId(payload.targetId)})
        if not company:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
        target_owner_id = company["ownerId"]
        target_company_id = str(company["_id"])
        target_name = company["name"]
    else:  # player
        if not ObjectId.is_valid(payload.targetId):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный ID игрока")
        target_user = await db.users.find_one({"_id": ObjectId(payload.targetId)}, {"username": 1})
        if not target_user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Игрок не найден")
        target_owner_id = str(target_user["_id"])
        target_name = target_user.get("username", "—")
        # Если у игрока есть компания с акцией — по ней тоже можно ударить.
        own_company = await db.companies.find_one({"ownerId": target_owner_id})
        if own_company:
            target_company_id = str(own_company["_id"])

    if target_owner_id == uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя разоблачать самого себя")

    # Кулдаун на пару заказчик→владелец-цели (покрывает и компанию, и игрока).
    since = _now() - timedelta(hours=EXPOSE_COOLDOWN_H)
    recent = await db.media_events.find_one({
        "orderedBy": uid, "targetOwnerId": target_owner_id,
        "created_at": {"$gte": since},
    })
    if recent:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Разоблачение против этой цели уже заказано недавно")

    # Взнос списывается и «сгорает» (не переходит цели)
    new_balance = await adjust_balance(db, uid, -payload.budget)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для взноса")
    await record_transaction(
        db, uid, EXPENSE, payload.budget, CAT_BUSINESS,
        f"Разоблачение: «{target_name}»", balance_after=new_balance,
        meta={"targetType": payload.targetType, "targetId": payload.targetId, "kind": "media_expose"},
    )

    chance = _success_chance(payload.budget)
    hit_pct = _hit_pct(payload.budget)
    prep_minutes = random.randint(PREP_MIN_MINUTES, PREP_MAX_MINUTES)
    resolve_at = _now() + timedelta(minutes=prep_minutes)

    await db.media_events.insert_one({
        "orderedBy": uid,
        "targetType": payload.targetType,
        "targetOwnerId": target_owner_id,
        "targetCompanyId": target_company_id,
        "targetName": target_name,
        "budget": payload.budget,
        "chance": chance,
        "hitPct": hit_pct,
        "outcome": "pending",
        "created_at": _now(),
        "resolve_at": resolve_at,
    })

    # Уведомляем заказчика: новость готовится.
    await push_notification(
        db, uid, "media", "Разоблачение заказано",
        f"Материал о «{target_name}» готовится и выйдет примерно через {prep_minutes} мин.",
        data={"targetName": target_name},
    )

    return {
        "status": "pending",
        "chance": chance,
        "hitPct": hit_pct,
        "prepMinutes": prep_minutes,
        "effectHours": EXPOSE_HOURS,
        "balance": new_balance,
    }


async def _resolve_expose(db: AsyncIOMotorDatabase, ev: dict):
    """Разыгрывает исход одного готового разоблачения (успех/провал) и применяет эффект."""
    target_owner_id = ev.get("targetOwnerId")
    target_company_id = ev.get("targetCompanyId")
    target_name = ev.get("targetName", "—")
    hit_pct = float(ev.get("hitPct", EXPOSE_HIT_MIN))
    chance = float(ev.get("chance", CHANCE_BASE))

    success = random.random() < chance
    expires = _now() + timedelta(hours=EXPOSE_HOURS)

    if success:
        factor = round(1.0 - hit_pct, 4)
        outcome = "success"
    else:
        factor = round(1.0 + EXPOSE_BACKFIRE, 4)
        outcome = "fail"

    await db.company_debuffs.insert_one({
        "companyId": target_company_id,
        "ownerId": target_owner_id,
        "factor": factor,
        "outcome": outcome,
        "created_at": _now(),
        "expires_at": expires,
    })

    if success and target_company_id:
        await _hit_company_stock(db, target_company_id)

    await db.media_events.update_one(
        {"_id": ev["_id"]},
        {"$set": {"outcome": outcome, "resolved_at": _now()}},
    )

    if outcome == "success":
        await push_notification(
            db, target_owner_id, "media", "Репутационный кризис",
            f"СМИ выпустили разоблачение о «{target_name}». Доход ваших бизнесов "
            f"снижен на {int(hit_pct * 100)}% на {EXPOSE_HOURS} ч.",
            data={"targetName": target_name},
        )
    else:
        await push_notification(
            db, target_owner_id, "media", "Провальное разоблачение",
            f"Разоблачение о «{target_name}» провалилось — интерес вырос: "
            f"доход бизнесов +{int(EXPOSE_BACKFIRE * 100)}% на {EXPOSE_HOURS} ч.",
            data={"targetName": target_name},
        )
    # Уведомляем заказчика об исходе.
    ordered_by = ev.get("orderedBy")
    if ordered_by:
        if outcome == "success":
            await push_notification(
                db, ordered_by, "media", "Разоблачение вышло",
                f"Материал о «{target_name}» удался: доход цели снижен на {int(hit_pct * 100)}%.",
                data={"targetName": target_name},
            )
        else:
            await push_notification(
                db, ordered_by, "media", "Разоблачение провалилось",
                f"Материал о «{target_name}» не сработал — взнос потрачен впустую.",
                data={"targetName": target_name},
            )


async def sweep_pending_exposes(db: AsyncIOMotorDatabase):
    """Планировщик: разыгрывает исход у всех «созревших» разоблачений (resolve_at ≤ now)."""
    now = _now()
    async for ev in db.media_events.find({"outcome": "pending", "resolve_at": {"$lte": now}}):
        try:
            await _resolve_expose(db, ev)
        except Exception:
            # Не блокируем остальные — помечаем как провал, чтобы не зависало в pending.
            try:
                await db.media_events.update_one(
                    {"_id": ev["_id"]},
                    {"$set": {"outcome": "fail", "resolved_at": now}},
                )
            except Exception:
                pass


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
