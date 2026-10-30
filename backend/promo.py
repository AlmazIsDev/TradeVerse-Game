"""Промокоды: игрок активирует код в настройках и получает бонус на баланс.

Код и сумма задаются в админ-панели (коллекция promo_codes). Деньги — только
через ledger. Одноразовость на игрока обеспечивается уникальным индексом по
(code, user_id) в promo_redemptions, а лимит использований — атомарным $inc
с условием, поэтому параллельные запросы не превысят max_uses.
"""
from __future__ import annotations

import logging
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from admin_perms import require_admin
from assets import _find_catalog, _fallback_catalog, check_type_limit
from auth import get_current_user
from database import get_db
from ledger import INCOME, CAT_SYSTEM, adjust_balance, record_transaction
from schemas import PromoRedeem, PromoAdminUpsert
from timeutil import now_utc, to_aware

logger = logging.getLogger("tradeverse.promo")

router = APIRouter(prefix="/api/user", tags=["promo"])
admin_router = APIRouter(prefix="/api/admin/promo", tags=["promo-admin"])


async def ensure_promo_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.promo_codes.create_index("code", unique=True)
    await db.promo_redemptions.create_index([("code", 1), ("user_id", 1)], unique=True)


@router.post("/promo/redeem")
async def redeem_promo(
    payload: PromoRedeem,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Активировать промокод. Все награды или ни одной: сначала проверяются срок,
    лимиты и каталог, затем выдаётся всё; при сбое использование откатывается."""
    code = payload.code
    promo = await db.promo_codes.find_one({"code": code})
    if not promo or not promo.get("active", True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Промокод не найден или неактивен")

    expires_at = promo.get("expires_at")
    if expires_at is not None and to_aware(expires_at) <= now_utc():
        raise HTTPException(status.HTTP_410_GONE, "Срок действия промокода истёк")

    user_id = str(current_user["_id"])
    business_slug = promo.get("business_slug")
    badge = promo.get("badge")
    amount = float(promo.get("amount") or 0.0)

    # 1) Проверка наград до любых списаний: бизнес должен быть в каталоге и
    #    не превышать лимит владения.
    catalog = None
    if business_slug:
        catalog = _find_catalog(business_slug) or _fallback_catalog(business_slug)
        if not catalog:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Промокод настроен неверно: бизнес не найден")
        try:
            await check_type_limit(db, user_id, catalog["type"])
        except HTTPException:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Промокод не применён: достигнут лимит по бизнесам")

    # 2) Занять слот использования (атомарно по max_uses).
    max_uses = promo.get("max_uses")
    if max_uses is not None:
        claimed = await db.promo_codes.update_one(
            {"_id": promo["_id"], "uses": {"$lt": max_uses}},
            {"$inc": {"uses": 1}},
        )
        if claimed.modified_count == 0:
            raise HTTPException(status.HTTP_410_GONE, "Лимит использования промокода исчерпан")
    else:
        await db.promo_codes.update_one({"_id": promo["_id"]}, {"$inc": {"uses": 1}})

    async def _release_slot():
        await db.promo_codes.update_one({"_id": promo["_id"]}, {"$inc": {"uses": -1}})

    try:
        await db.promo_redemptions.insert_one({
            "code": code, "user_id": user_id, "created_at": now_utc(),
        })
    except DuplicateKeyError:
        await _release_slot()
        raise HTTPException(status.HTTP_409_CONFLICT, "Вы уже активировали этот промокод")

    async def _rollback():
        await db.promo_redemptions.delete_one({"code": code, "user_id": user_id})
        await _release_slot()

    # 3) Выдача наград. При любой ошибке откатываем использование.
    granted_business = None
    try:
        if catalog:
            granted_business = await grant_business_for_promo(db, user_id, catalog, code)
        if badge:
            await db.users.update_one({"_id": current_user["_id"]}, {"$addToSet": {"badges": badge}})
        balance_after = None
        if amount > 0:
            balance_after = await adjust_balance(db, user_id, amount)
            if balance_after is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
            await record_transaction(
                db, user_id, INCOME, amount, CAT_SYSTEM,
                f"Промокод: {code}",
                balance_after=balance_after,
                meta={"promoCode": code},
            )
    except HTTPException:
        if granted_business:
            await db.user_assets.delete_one({"_id": granted_business})
        await _rollback()
        raise
    except Exception:
        logger.exception("promo grant failed: user=%s code=%s", user_id, code)
        if granted_business:
            await db.user_assets.delete_one({"_id": granted_business})
        await _rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось применить промокод")

    if balance_after is None:
        balance_after = (await db.users.find_one({"_id": current_user["_id"]}, {"balance": 1}) or {}).get("balance", 0.0)

    logger.info("promo redeemed: user=%s code=%s amount=%s business=%s badge=%s",
                user_id, code, amount, business_slug, badge)
    return {
        "amount": amount,
        "balance": balance_after,
        "business": catalog["name"] if catalog else None,
        "badge": badge,
    }


async def grant_business_for_promo(db, user_id: str, catalog: dict, code: str):
    """Создаёт актив-бизнес из каталога для промокода. Возвращает _id документа."""
    now = now_utc()
    doc = {
        "userId": user_id,
        "slug": catalog["slug"],
        "type": catalog["type"],
        "name": catalog["name"],
        "category": catalog.get("category"),
        "rarity": catalog.get("rarity"),
        "rooms": catalog.get("rooms"),
        "basement": catalog.get("basement"),
        "employees": catalog.get("employees", 0),
        "price": float(catalog["price"]),
        "price_mult": 1.0,
        "income_per_hour": catalog.get("income_per_hour", 0),
        "upkeep_per_hour": catalog.get("upkeep_per_hour", 0),
        "level": 1,
        "mining": False,
        "meta": {**(catalog.get("meta") or {}), "promoCode": code},
        "companyId": None,
        "rental": None,
        "purchased_at": now,
        "last_collected": now,
    }
    res = await db.user_assets.insert_one(doc)
    return res.inserted_id


def _promo_out(doc: dict) -> dict:
    created = doc.get("created_at")
    expires = doc.get("expires_at")
    return {
        "id": str(doc["_id"]),
        "code": doc["code"],
        "amount": float(doc.get("amount") or 0.0),
        "businessSlug": doc.get("business_slug"),
        "badge": doc.get("badge"),
        "maxUses": doc.get("max_uses"),
        "uses": int(doc.get("uses", 0)),
        "expiresAt": expires.isoformat() if isinstance(expires, datetime) else None,
        "active": bool(doc.get("active", True)),
        "createdAt": created.isoformat() if isinstance(created, datetime) else None,
    }


@admin_router.get("")
async def admin_list_promos(
    _admin=Depends(require_admin("promo_codes")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Все промокоды с числом использований."""
    docs = await db.promo_codes.find({}).sort("created_at", -1).to_list(length=500)
    return {"promos": [_promo_out(d) for d in docs]}


@admin_router.post("")
async def admin_create_promo(
    payload: PromoAdminUpsert,
    _admin=Depends(require_admin("promo_codes")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Создать промокод."""
    if await db.promo_codes.find_one({"code": payload.code}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Промокод с таким кодом уже существует")
    if payload.business_slug and not (_find_catalog(payload.business_slug) or _fallback_catalog(payload.business_slug)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Бизнес не найден в каталоге")
    doc = {
        "code": payload.code,
        "amount": payload.amount,
        "business_slug": payload.business_slug,
        "badge": payload.badge,
        "max_uses": payload.max_uses,
        "expires_at": payload.expires_at,
        "uses": 0,
        "active": payload.active,
        "created_at": now_utc(),
    }
    res = await db.promo_codes.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _promo_out(doc)


@admin_router.patch("/{promo_id}")
async def admin_update_promo(
    promo_id: str,
    payload: PromoAdminUpsert,
    _admin=Depends(require_admin("promo_codes")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Изменить сумму, лимит и активность промокода (код меняется только на свободный)."""
    try:
        oid = ObjectId(promo_id)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный id")
    clash = await db.promo_codes.find_one({"code": payload.code, "_id": {"$ne": oid}})
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Промокод с таким кодом уже существует")
    updated = await db.promo_codes.find_one_and_update(
        {"_id": oid},
        {"$set": {
            "code": payload.code,
            "amount": payload.amount,
            "business_slug": payload.business_slug,
            "badge": payload.badge,
            "max_uses": payload.max_uses,
            "expires_at": payload.expires_at,
            "active": payload.active,
        }},
        return_document=True,
    )
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Промокод не найден")
    return _promo_out(updated)


@admin_router.delete("/{promo_id}")
async def admin_delete_promo(
    promo_id: str,
    _admin=Depends(require_admin("promo_codes")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удалить промокод вместе с историей активаций."""
    try:
        oid = ObjectId(promo_id)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный id")
    doc = await db.promo_codes.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Промокод не найден")
    await db.promo_codes.delete_one({"_id": oid})
    await db.promo_redemptions.delete_many({"code": doc["code"]})
    return {"ok": True}
