"""Центральный рынок — лоты игроков (p2p торговля).

Игра уже имеет витрины (shop.py — железо, assets.py — активы), но игроки не
могут торговать между собой. Этот роутер добавляет лоты: игрок выставляет
принадлежащее ему имущество, другой игрок покупает.

Два вида лотов:
  - kind="asset"    — экземпляр из user_assets (дом/бизнес/авто/завод…).
                      Экземпляр уникален, qty всегда 1; при покупке право
                      собственности переносится на покупателя.
  - kind="hardware" — железо из user_hardware (один документ = одна единица).
                      Лот продаёт qty одинаковых свободных (farmId=None)
                      экземпляров одного itemId; при покупке первые qty
                      свободных документов переходят покупателю.

Деньги всегда идут через ledger (CAT_MARKET), цена задаётся продавцом —
сервер не считает её (это p2p-цена, а не витринная), но валидирует её
диапазон и владение товаром. Режим «свободный предмет» фронтенда не
поддерживается намеренно: продавать можно только то, чем владеешь.

Коллекция: market_lots (индекс в main.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator

from admin_perms import get_current_user, require_allowed
from database import get_db
from ledger import INCOME, EXPENSE, CAT_MARKET, adjust_balance, record_transaction
from notifications import push_notification

router = APIRouter(prefix="/api/market/lots", tags=["central-market"])

MAX_LOT_QTY = 1000
MIN_UNIT_PRICE = 0.01
MAX_UNIT_PRICE = 100_000_000.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid(s: str) -> ObjectId:
    if not ObjectId.is_valid(s):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный идентификатор")
    return ObjectId(s)


async def _rollback_debit(db, user_id: str, total: float) -> None:
    """Списание при откате сделки. В отличие от adjust_balance не требует
    достаточного остатка: откат обязан исполниться — иначе при нехватке
    средств у продавца сделка «напечатает» деньги (adjust_balance просто
    no-op'ается и возвращает None). Уводит баланс в минус, если продавец
    успел потратить выручку.
    """
    result = await db.users.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$inc": {"balance": -total}},
        return_document=True,
    )
    if result:
        try:
            from ws import push_to_user
            await push_to_user(user_id, {"type": "balance",
                                         "balance": round(float(result.get("balance", 0.0)), 2)})
        except Exception:
            pass


# ── Schemas ──────────────────────────────────────────────────────────────────


class LotCreate(BaseModel):
    kind: str                 # "asset" | "hardware"
    itemId: str               # _id актива или itemId железа
    qty: int = 1
    pricePerItem: float

    @field_validator("kind")
    @classmethod
    def kind_ok(cls, v):
        if v not in ("asset", "hardware"):
            raise ValueError("kind должен быть asset или hardware")
        return v

    @field_validator("pricePerItem")
    @classmethod
    def price_ok(cls, v):
        if not (MIN_UNIT_PRICE <= float(v) <= MAX_UNIT_PRICE):
            raise ValueError(f"Цена за штуку должна быть от {MIN_UNIT_PRICE} до {MAX_UNIT_PRICE}")
        return round(float(v), 2)


class LotUpdate(BaseModel):
    qty: Optional[int] = None
    pricePerItem: Optional[float] = None


class LotBuy(BaseModel):
    qty: int = 1


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _available_hw_qty(db, seller_id: str, item_id: str) -> int:
    """Сколько свободных (не установленных на ферму) единиц железа у продавца."""
    return await db.user_hardware.count_documents(
        {"userId": seller_id, "itemId": item_id, "farmId": None}
    )


async def _serialize_lots(db, lots: list[dict]) -> list[dict]:
    """Лоты + живые имена продавцов из db.users (не храним username в лоте)."""
    seller_ids = {l["sellerId"] for l in lots if ObjectId.is_valid(l.get("sellerId", ""))}
    users = {}
    if seller_ids:
        async for u in db.users.find(
            {"_id": {"$in": [ObjectId(s) for s in seller_ids]}}, {"username": 1}
        ):
            users[str(u["_id"])] = u.get("username", "—")
    out = []
    for l in lots:
        out.append({
            "id": str(l["_id"]),
            "kind": l.get("kind"),
            "itemId": l.get("itemId"),
            "name": l.get("name"),
            "qty": l.get("qty", 1),
            "pricePerItem": l.get("pricePerItem"),
            "sellerId": l.get("sellerId"),
            "seller": users.get(l.get("sellerId"), "—"),
            "createdAt": l.get("created_at").isoformat() if isinstance(l.get("created_at"), datetime) else None,
        })
    return out


def _transferable_asset(asset: dict) -> bool:
    """Актив можно выставить: личный, без активной аренды (не «сдан в аренду»)."""
    rental = asset.get("rental")
    return not asset.get("companyId") and not (rental and rental.get("status") == "rented")


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("")
async def list_lots(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _current_user: dict = Depends(get_current_user),
):
    """Активные лоты (новые сверху)."""
    lots = [l async for l in db.market_lots.find({"status": "active"}).sort("created_at", -1)]
    return {"lots": await _serialize_lots(db, lots)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lot(
    payload: LotCreate,
    current_user: dict = Depends(require_allowed("centralmarket")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Выставить лот. Владение и количество проверяются на сервере."""
    user_id = str(current_user["_id"])
    qty = max(1, int(payload.qty))
    if qty > MAX_LOT_QTY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Максимум {MAX_LOT_QTY} за лот")

    if payload.kind == "asset":
        if qty != 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Актив продаётся поштучно (qty=1)")
        asset = await db.user_assets.find_one({"_id": _oid(payload.itemId), "userId": user_id})
        if not asset:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден среди ваших")
        if not _transferable_asset(asset):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Актив сейчас нельзя выставить (в аренде или принадлежит компании)")
        if await db.market_lots.find_one({"itemId": payload.itemId, "status": "active"}):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Этот актив уже выставлен на рынок")
        name = asset.get("name") or asset.get("slug")
    else:
        avail = await _available_hw_qty(db, user_id, payload.itemId)
        if avail <= 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Железо не найдено в свободном инвентаре")
        qty = min(qty, avail)
        doc = await db.user_hardware.find_one({"userId": user_id, "itemId": payload.itemId})
        name = (doc or {}).get("name") or payload.itemId

    doc = {
        "sellerId": user_id, "kind": payload.kind, "itemId": payload.itemId,
        "name": name, "qty": qty, "pricePerItem": payload.pricePerItem,
        "status": "active", "created_at": _now(),
    }
    result = await db.market_lots.insert_one(doc)
    doc["_id"] = result.inserted_id
    return {"lot": (await _serialize_lots(db, [doc]))[0]}


@router.patch("/{lot_id}")
async def update_lot(
    lot_id: str,
    payload: LotUpdate,
    current_user: dict = Depends(require_allowed("centralmarket")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Изменить свой лот (количество/цена). Количество перепроверяется по инвентарю."""
    user_id = str(current_user["_id"])
    lot = await db.market_lots.find_one({"_id": _oid(lot_id), "sellerId": user_id,
                                         "status": "active"})
    if not lot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лот не найден")
    set_fields: dict = {}
    if payload.pricePerItem is not None:
        if not (MIN_UNIT_PRICE <= payload.pricePerItem <= MAX_UNIT_PRICE):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недопустимая цена")
        set_fields["pricePerItem"] = round(float(payload.pricePerItem), 2)
    if payload.qty is not None:
        qty = max(1, int(payload.qty))
        if lot.get("kind") == "asset" and qty != 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Актив продаётся поштучно (qty=1)")
        if lot.get("kind") == "hardware":
            avail = await _available_hw_qty(db, user_id, lot["itemId"])
            qty = min(qty, avail)
            if qty <= 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Свободного железа нет")
        set_fields["qty"] = qty
    if set_fields:
        await db.market_lots.update_one({"_id": lot["_id"]}, {"$set": set_fields})
    updated = await db.market_lots.find_one({"_id": lot["_id"]})
    return {"lot": (await _serialize_lots(db, [updated]))[0]}


@router.delete("/{lot_id}")
async def cancel_lot(
    lot_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Снять свой лот с продажи."""
    user_id = str(current_user["_id"])
    result = await db.market_lots.update_one(
        {"_id": _oid(lot_id), "sellerId": user_id, "status": "active"},
        {"$set": {"status": "cancelled"}},
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лот не найден")
    return {"ok": True}


@router.post("/{lot_id}/buy")
async def buy_lot(
    lot_id: str,
    payload: LotBuy,
    current_user: dict = Depends(require_allowed("centralmarket")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Купить из лота qty штук. Атомарно по лоту; деньги — только через ledger.

    Актив: право собственности переносится целиком. Железо: первые qty свободных
    единиц переходят покупателю, лот уменьшается (или закрывается).
    """
    user_id = str(current_user["_id"])
    qty = max(1, int(payload.qty))

    # Атомарная «броня» количества: уменьшаем qty лота до покупки. Кто первый
    # уменьшил — тот и купил; второй увидит нехватку или уже закрытый лот.
    lot = await db.market_lots.find_one({"_id": _oid(lot_id), "status": "active"})
    if not lot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лот не найден или уже продан")
    if lot.get("sellerId") == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя купить свой лот")
    if qty > lot.get("qty", 0):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"В лоте только {lot.get('qty')} шт.")

    remaining = lot["qty"] - qty
    lot_status = "sold" if remaining <= 0 else "active"
    set_fields = {"status": lot_status, "qty": remaining}
    if lot_status == "sold":
        set_fields.update({"buyerId": user_id, "sold_at": _now()})
    matched = await db.market_lots.update_one(
        {"_id": lot["_id"], "status": "active", "qty": lot["qty"]},
        {"$set": set_fields},
    )
    if matched.modified_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Лот уже изменён другим покупателем")

    total = round(qty * float(lot["pricePerItem"]), 2)

    # Продавец мог быть удалён после создания лота — проверяем до брони, чтобы
    # не оказаться с деньгами покупателя и без получателя выручки.
    seller_id = lot["sellerId"]
    seller = await db.users.find_one({"_id": ObjectId(seller_id)}, {"balance": 1})
    if not seller:
        await db.market_lots.update_one({"_id": lot["_id"]},
                                        {"$set": {"status": "cancelled"}})
        raise HTTPException(status.HTTP_409_CONFLICT, "Продавец больше недоступен")

    # Деньги: у покупателя должно хватить средств, иначе лот возвращается.
    buyer_balance = await adjust_balance(db, user_id, -total)
    if buyer_balance is None:
        if lot_status == "sold":
            # remaining == 0 → статус sold, параллельно докупить было нельзя:
            # честно разворачиваем и бронь, и пометку покупателя.
            await db.market_lots.update_one(
                {"_id": lot["_id"], "status": "sold", "buyerId": user_id},
                {"$set": {"status": "active"}, "$inc": {"qty": qty},
                 "$unset": {"buyerId": "", "sold_at": ""}},
            )
        else:
            # $inc, а не $set: не затираем бронь, сделанную параллельным покупателем.
            await db.market_lots.update_one(
                {"_id": lot["_id"], "status": "active"},
                {"$inc": {"qty": qty}},
            )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    seller_balance = await adjust_balance(db, seller_id, total)

    if lot["kind"] == "asset":
        # Повторная проверка передаваемости в момент продажи (при создании лота
        # актив мог уйти в компанию или в аренду) — иначе покупатель «вырвет»
        # его у компании/арендатора.
        asset = await db.user_assets.find_one_and_update(
            {"_id": _oid(lot["itemId"]), "userId": seller_id,
             "companyId": None, "rental.status": {"$ne": "rented"}},
            {"$set": {"userId": user_id, "companyId": None, "rental": None,
                      "last_collected": _now()},
             "$unset": {"listingId": ""}},
        )
        if not asset:
            # Товар исчез (продан/арендован в обход лота) — возвращаем деньги.
            await adjust_balance(db, user_id, total)
            await _rollback_debit(db, seller_id, total)
            await db.market_lots.update_one({"_id": lot["_id"]},
                                            {"$set": {"status": "cancelled"}})
            raise HTTPException(status.HTTP_409_CONFLICT, "Актив больше недоступен")

        # Актив уходит покупателю вместе с привязанным состоянием: майнинг-фермы
        # подвала (привязаны по houseId) и поля (user_fields по assetId). Без
        # этого продавец продолжал бы получать доход с проданного подвала/поля,
        # а вместимость подвала дублировалась бы покупателю.
        await db.mining_farms.update_many(
            {"houseId": asset["_id"], "userId": seller_id},
            {"$set": {"userId": user_id}},
        )
        await db.user_fields.update_many(
            {"assetId": str(asset["_id"]), "userId": seller_id},
            {"$set": {"userId": user_id}},
        )

        from ws import push_to_user
        try:
            await push_to_user(user_id, {"type": "asset_update", "assetId": str(asset["_id"])})
        except Exception:
            pass
    else:
        free = [h async for h in db.user_hardware.find(
            {"userId": seller_id, "itemId": lot["itemId"], "farmId": None}
        ).limit(qty)]
        if len(free) < qty:
            # Железа стало меньше, чем обещал лот — возврат средств и откат лота.
            await adjust_balance(db, user_id, total)
            await _rollback_debit(db, seller_id, total)
            await db.market_lots.update_one({"_id": lot["_id"]},
                                            {"$set": {"status": "cancelled"}})
            raise HTTPException(status.HTTP_409_CONFLICT, "Железо больше недоступно")
        moved = await db.user_hardware.update_many(
            # farmId: None в фильтре — между выборкой и апдейтом единицу могли
            # поставить на ферму; без условия вырвали бы её оттуда.
            {"_id": {"$in": [h["_id"] for h in free]},
             "userId": seller_id, "farmId": None},
            {"$set": {"userId": user_id, "farmId": None, "purchased_at": _now()}},
        )
        if moved.modified_count < qty:
            # Часть единиц ушла на ферму — откатываем перенос и сделку целиком.
            # Единицы взаимозаменяемы (один itemId), поэтому возвращаем ровно
            # столько, сколько реально переехало.
            if moved.modified_count:
                await db.user_hardware.update_many(
                    {"_id": {"$in": [h["_id"] for h in free]},
                     "userId": user_id},
                    {"$set": {"userId": seller_id, "farmId": None,
                              "purchased_at": _now()}},
                )
            await adjust_balance(db, user_id, total)
            await _rollback_debit(db, seller_id, total)
            await db.market_lots.update_one({"_id": lot["_id"]},
                                            {"$set": {"status": "cancelled"}})
            raise HTTPException(status.HTTP_409_CONFLICT, "Железо больше недоступно")

    buyer_after = buyer_balance
    name = lot.get("name") or "лот"
    await record_transaction(
        db, user_id, EXPENSE, total, CAT_MARKET,
        f"Покупка на Центральном рынке: {name}" + (f" ×{qty}" if qty > 1 else ""),
        balance_after=buyer_after, meta={"lotId": lot_id, "kind": lot["kind"]},
    )
    await record_transaction(
        db, seller_id, INCOME, total, CAT_MARKET,
        f"Продажа на Центральном рынке: {name}" + (f" ×{qty}" if qty > 1 else ""),
        balance_after=seller_balance,
        meta={"lotId": lot_id, "kind": lot["kind"]},
    )
    try:
        await push_notification(
            db, seller_id, "market", "Лот продан",
            f"Лот «{name}» куплен" + (f" (×{qty})" if qty > 1 else "") +
            f". Выручка: {total:.2f}$",
        )
    except Exception:
        pass
    try:
        from ws import push_to_user
        await push_to_user(seller_id, {"type": "market_sold", "lotId": lot_id})
    except Exception:
        pass

    return {"ok": True, "qty": qty, "total": total, "balance": buyer_after}
