"""Аукцион имущества между игроками: выставление, ставки, автозавершение.

Ставка списывается сразу (как в bank_p2p), предыдущему лидеру возвращается.
При закрытии бизнес переходит победителю, продавец получает выручку за
вычетом комиссии. Выставленный бизнес помечен onAuction и не может быть
выставлен повторно; сделки с ним до закрытия отсекаются проверкой в _resolve.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, field_validator
from pymongo import ReturnDocument

from admin_perms import get_current_user, require_allowed
from database import get_db
from game_config import PLAYER_AUCTION_CONFIG as CFG
from ledger import CAT_MARKET, EXPENSE, INCOME, adjust_balance, record_transaction
from notifications import push_notification

router = APIRouter(prefix="/api/auctions", tags=["player-auctions"])

DURATION = timedelta(minutes=CFG["duration_minutes"])
BID_STEP = CFG["bid_step"]
REPRICE = CFG["reprice"]
MIN_RATIO = CFG["min_ratio"]
FEE_PCT = CFG["fee_pct"]
MAX_PRICE = CFG["max_price"]
MAX_OPEN_PER_USER = CFG["max_open_per_user"]


class ListingCreate(BaseModel):
    assetId: str
    startPrice: float

    @field_validator("startPrice")
    @classmethod
    def price_ok(cls, v):
        if v is None or v <= 0 or v > MAX_PRICE:
            raise ValueError("Стартовая цена вне допустимого диапазона")
        return round(float(v), 2)


class BidIn(BaseModel):
    amount: float


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Аукцион не найден")
    return ObjectId(value)


def _serialize(doc: dict, me: str) -> dict:
    current = float(doc["currentPrice"])
    has_bids = bool(doc.get("topBidderId"))
    return {
        "id": str(doc["_id"]),
        "assetId": doc["assetId"],
        "name": doc.get("name"),
        "slug": doc.get("slug"),
        "level": doc.get("level", 1),
        "startPrice": doc["startPrice"],
        "currentPrice": current,
        "minNextBid": round(current * BID_STEP, 2) if has_bids else current,
        "hasBids": has_bids,
        "topBidderName": doc.get("topBidderName"),
        "sellerId": doc["sellerId"],
        "sellerName": doc.get("sellerName"),
        "isSeller": doc["sellerId"] == me,
        "isMine": doc.get("topBidderId") == me,
        "endsAt": _aware(doc["endsAt"]).isoformat(),
        "status": doc["status"],
    }


async def _refund_bidder(db: AsyncIOMotorDatabase, auction: dict, reason: str) -> None:
    bidder = auction.get("topBidderId")
    if not bidder:
        return
    refund = float(auction["currentPrice"])
    bal = await adjust_balance(db, bidder, refund)
    if bal is None:
        return
    await record_transaction(db, bidder, INCOME, refund, CAT_MARKET,
                             "Возврат ставки на аукционе бизнеса", balance_after=bal,
                             meta={"auctionId": str(auction["_id"]), "reason": reason})
    await push_notification(db, bidder, "market", "Аукцион бизнеса закрыт",
                            f"Ставка {refund:,.2f} возвращена: {reason}",
                            {"auctionId": str(auction["_id"])})


async def _release_asset(db: AsyncIOMotorDatabase, auction: dict) -> None:
    await db.user_assets.update_one(
        {"_id": ObjectId(auction["assetId"]), "userId": auction["sellerId"]},
        {"$unset": {"onAuction": ""}},
    )


async def _cancel(db: AsyncIOMotorDatabase, auction: dict, reason: str) -> None:
    closed = await db.player_auctions.update_one(
        {"_id": auction["_id"], "status": "open"},
        {"$set": {"status": "cancelled", "cancelReason": reason}},
    )
    if closed.modified_count != 1:
        return
    await _refund_bidder(db, auction, reason)
    await _release_asset(db, auction)
    await push_notification(db, auction["sellerId"], "market", "Аукцион бизнеса отменён",
                            reason, {"auctionId": str(auction["_id"])})


async def _reprice(db: AsyncIOMotorDatabase, auction: dict, now: datetime) -> None:
    current = float(auction["currentPrice"])
    floor = float(auction.get("minPrice", 0))
    new_price = max(round(current * REPRICE, 2), floor)
    await db.player_auctions.update_one(
        {"_id": auction["_id"], "status": "open", "topBidderId": None},
        {"$set": {"currentPrice": new_price, "endsAt": now + DURATION}},
    )


async def _settle(db: AsyncIOMotorDatabase, auction: dict, now: datetime) -> None:
    seller = auction["sellerId"]
    winner = auction["topBidderId"]
    asset_oid = ObjectId(auction["assetId"])
    asset = await db.user_assets.find_one({"_id": asset_oid})
    if (not asset or asset.get("userId") != seller or asset.get("companyId")
            or not asset.get("onAuction") or asset.get("rental")):
        await _cancel(db, auction, "Бизнес больше недоступен для продажи")
        return

    price = float(auction["currentPrice"])
    fee = round(price * FEE_PCT, 2)
    payout = round(price - fee, 2)

    moved = await db.user_assets.update_one(
        {"_id": asset_oid, "userId": seller, "onAuction": True},
        {"$set": {"userId": winner, "last_collected": now},
         "$unset": {"onAuction": ""}},
    )
    if moved.modified_count != 1:
        await _cancel(db, auction, "Бизнес больше недоступен для продажи")
        return

    closed = await db.player_auctions.update_one(
        {"_id": auction["_id"], "status": "open"},
        {"$set": {"status": "sold", "soldTo": winner, "soldFor": price, "fee": fee}},
    )
    if closed.modified_count != 1:
        return

    bal = await adjust_balance(db, seller, payout)
    if bal is not None:
        await record_transaction(db, seller, INCOME, payout, CAT_MARKET,
                                 f"Продажа бизнеса на аукционе: {auction.get('name')}",
                                 balance_after=bal,
                                 meta={"auctionId": str(auction["_id"]), "fee": fee})
    await push_notification(db, seller, "market", "Бизнес продан на аукционе",
                            f"Выручка {payout:,.2f} (комиссия {fee:,.2f})",
                            {"auctionId": str(auction["_id"])})
    await push_notification(db, winner, "market", "Вы выиграли аукцион",
                            f"Бизнес «{auction.get('name')}» перешёл к вам",
                            {"auctionId": str(auction["_id"])})


async def _resolve(db: AsyncIOMotorDatabase, auction: dict, now: datetime) -> None:
    if not auction.get("topBidderId"):
        asset = await db.user_assets.find_one({"_id": ObjectId(auction["assetId"])}, {"userId": 1, "onAuction": 1})
        if not asset or asset.get("userId") != auction["sellerId"]:
            await _cancel(db, auction, "Бизнес больше недоступен для продажи")
            return
        await _reprice(db, auction, now)
        return
    await _settle(db, auction, now)


async def process_player_auctions(db: AsyncIOMotorDatabase) -> None:
    """Закрывает просроченные аукционы; вызывается из scheduler._tick."""
    now = _now()
    async for auction in db.player_auctions.find({"status": "open", "endsAt": {"$lte": now}}):
        await _resolve(db, auction, now)


@router.get("")
async def list_auctions(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    me = str(current_user["_id"])
    docs = await db.player_auctions.find({"status": "open"}).sort("_id", -1).to_list(length=200)
    return {"auctions": [_serialize(d, me) for d in docs]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_auction(
    payload: ListingCreate,
    current_user: dict = Depends(require_allowed("assets_sell")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    me = str(current_user["_id"])
    asset_oid = _oid(payload.assetId)
    asset = await db.user_assets.find_one({"_id": asset_oid, "userId": me})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    open_count = await db.player_auctions.count_documents({"sellerId": me, "status": "open"})
    if open_count >= MAX_OPEN_PER_USER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Не более {MAX_OPEN_PER_USER} открытых аукционов")

    locked = await db.user_assets.update_one(
        {"_id": asset_oid, "userId": me, "companyId": None, "frozen": {"$ne": True},
         "rental": None, "onAuction": {"$ne": True}},
        {"$set": {"onAuction": True}},
    )
    if locked.modified_count != 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Бизнес нельзя выставить: в компании, в аренде, заморожен или уже на аукционе")

    seller = await db.users.find_one({"_id": ObjectId(me)}, {"username": 1})
    now = _now()
    doc = {
        "assetId": str(asset_oid),
        "name": asset.get("name") or asset.get("slug"),
        "slug": asset.get("slug"),
        "level": asset.get("level", 1),
        "sellerId": me,
        "sellerName": (seller or {}).get("username"),
        "startPrice": payload.startPrice,
        "minPrice": round(payload.startPrice * MIN_RATIO, 2),
        "currentPrice": payload.startPrice,
        "topBidderId": None,
        "topBidderName": None,
        "startedAt": now,
        "endsAt": now + DURATION,
        "status": "open",
    }
    try:
        result = await db.player_auctions.insert_one(doc)
    except Exception:
        await db.user_assets.update_one({"_id": asset_oid}, {"$unset": {"onAuction": ""}})
        raise
    doc["_id"] = result.inserted_id
    return _serialize(doc, me)


@router.post("/{auction_id}/bid")
async def bid_auction(
    auction_id: str,
    payload: BidIn,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    me = str(current_user["_id"])
    oid = _oid(auction_id)
    now = _now()
    auction = await db.player_auctions.find_one({"_id": oid, "status": "open"})
    if not auction:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Аукцион не найден или уже завершён")
    if auction["sellerId"] == me:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя ставить на собственный аукцион")
    if _aware(auction["endsAt"]) <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Аукцион завершён")
    if auction.get("topBidderId") == me:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ваша ставка уже лидирует")

    amount = round(float(payload.amount), 2)
    current = float(auction["currentPrice"])
    prev_bidder = auction.get("topBidderId")
    min_bid = round(current * BID_STEP, 2) if prev_bidder else current
    if amount < min_bid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Минимальная ставка {min_bid:,.2f}")
    if amount > MAX_PRICE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ставка выше допустимого максимума")

    me_doc = await db.users.find_one({"_id": ObjectId(me)}, {"username": 1})
    my_name = (me_doc or {}).get("username")

    before = await db.player_auctions.find_one_and_update(
        {"_id": oid, "status": "open", "currentPrice": current, "topBidderId": prev_bidder},
        {"$set": {"currentPrice": amount, "topBidderId": me, "topBidderName": my_name}},
        return_document=ReturnDocument.BEFORE,
    )
    if not before:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ставка устарела, обновите аукцион")

    new_balance = await adjust_balance(db, me, -amount)
    if new_balance is None:
        await db.player_auctions.update_one(
            {"_id": oid, "topBidderId": me},
            {"$set": {"currentPrice": current, "topBidderId": prev_bidder,
                      "topBidderName": before.get("topBidderName")}},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")

    await record_transaction(db, me, EXPENSE, amount, CAT_MARKET, "Ставка на аукционе бизнеса",
                             balance_after=new_balance, meta={"auctionId": auction_id})

    if prev_bidder:
        refund = current
        prev_balance = await adjust_balance(db, prev_bidder, refund)
        if prev_balance is not None:
            await record_transaction(db, prev_bidder, INCOME, refund, CAT_MARKET,
                                     "Возврат ставки на аукционе бизнеса", balance_after=prev_balance,
                                     meta={"auctionId": auction_id})
        await push_notification(db, prev_bidder, "market", "Ставку перебили",
                                f"На аукционе «{auction.get('name')}» ставка {amount:,.2f}",
                                {"auctionId": auction_id})

    return {"balance": new_balance, "currentPrice": amount}


@router.post("/{auction_id}/cancel")
async def cancel_auction(
    auction_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    me = str(current_user["_id"])
    oid = _oid(auction_id)
    closed = await db.player_auctions.update_one(
        {"_id": oid, "status": "open", "sellerId": me, "topBidderId": None},
        {"$set": {"status": "cancelled", "cancelReason": "Отменено продавцом"}},
    )
    if closed.modified_count != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Отменить можно только свой аукцион без ставок")
    auction = await db.player_auctions.find_one({"_id": oid})
    await _release_asset(db, auction)
    return {"ok": True}
