"""P2P-займы между игроками: объявления, принятие, суточные проценты, возврат по сроку,
заморозка и изъятие имущества с аукциона.

Объявление создаёт заимодавец или заёмщик (side=lend|borrow), задаёт сумму,
срок от недели до трёх недель и процент в сутки. Встречная сторона принимает
одной кнопкой. Ежедневно scheduler вызывает accrue_p2p_loans: проценты списываются
с заёмщика и зачисляются заимодавцу.

Просрочка (срок вышел, денег нет) → займ `frozen`, всё имущество заёмщика заморожено.
Если через 24 ч долг не погашен — одна единица имущества (самая дорогая) изымается
и выставляется на аукцион во вкладке банка «Изъятое имущество». Выручка идёт заимодавцу
в счёт долга; если её не хватило, на следующем тике изымается ещё одна единица.
Излишек сверх долга возвращается заёмщику. Заём закрывается, когда долг покрыт.
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
from ledger import EXPENSE, INCOME, adjust_balance, record_transaction
from state_bank import credit_state

router = APIRouter(prefix="/api/bank/p2p", tags=["bank-p2p"])

CAT_P2P = "p2p_loan"
MAX_P2P_AMOUNT = 1_000_000_000.0
MIN_P2P_TERM_DAYS = 7
MAX_P2P_TERM_DAYS = 21
MAX_P2P_DAILY_RATE = 0.5

# Изъятие и аукцион
BANK_USER_ID = "__bank__"          # владелец изъятых активов до продажи
SEIZE_GRACE = timedelta(hours=24)  # сколько ждать после заморозки / предыдущего изъятия
AUCTION_DURATION = timedelta(hours=24)
AUCTION_REPRICE = 0.8              # без ставок стартовая цена снижается на 20%
AUCTION_MIN_RATIO = 0.1            # но не ниже 10% рыночной стоимости
BID_STEP = 1.01                    # следующая ставка минимум на 1% выше


class OfferCreate(BaseModel):
    side: str            # lend | borrow
    amount: float
    term_days: int
    daily_rate: float    # доля в сутки, например 0.01 = 1%

    @field_validator("side")
    @classmethod
    def side_valid(cls, v):
        if v not in ("lend", "borrow"):
            raise ValueError("side: lend или borrow")
        return v

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v <= 0 or v > MAX_P2P_AMOUNT:
            raise ValueError("Сумма вне допустимого диапазона")
        return round(float(v), 2)

    @field_validator("term_days")
    @classmethod
    def term_ok(cls, v):
        if v < MIN_P2P_TERM_DAYS or v > MAX_P2P_TERM_DAYS:
            raise ValueError(f"Срок от {MIN_P2P_TERM_DAYS} до {MAX_P2P_TERM_DAYS} суток")
        return v

    @field_validator("daily_rate")
    @classmethod
    def rate_ok(cls, v):
        if v < 0 or v > MAX_P2P_DAILY_RATE:
            raise ValueError("Процент в сутки от 0 до 50%")
        return float(v)


class BidIn(BaseModel):
    amount: float


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _total_due(loan: dict) -> float:
    """Сколько ещё должен заёмщик: основной долг + проценты - уже покрыто аукционом."""
    return round(loan["amount"] + loan.get("owed", 0.0) - loan.get("recovered", 0.0), 2)


def _asset_base_value(asset: dict) -> float:
    return float(asset.get("price", 0)) * (1 + 0.35 * (asset.get("level", 1) - 1))


def _serialize(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "side": doc["side"],
        "ownerId": doc["ownerId"],
        "ownerName": doc.get("ownerName"),
        "amount": doc["amount"],
        "termDays": doc["termDays"],
        "dailyRate": doc["dailyRate"],
        "status": doc["status"],
        "lenderId": doc.get("lenderId"),
        "borrowerId": doc.get("borrowerId"),
        "startedAt": doc["startedAt"].isoformat() if doc.get("startedAt") else None,
        "dueAt": doc["dueAt"].isoformat() if doc.get("dueAt") else None,
        "frozenAt": doc["frozenAt"].isoformat() if doc.get("frozenAt") else None,
        "owed": doc.get("owed", 0.0),
        "recovered": doc.get("recovered", 0.0),
        "dueTotal": _total_due(doc) if doc.get("amount") is not None else None,
    }


def _serialize_auction(doc: dict, me: str) -> dict:
    has_bids = bool(doc.get("topBidderId"))
    current = float(doc["currentPrice"])
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "slug": doc.get("slug"),
        "level": doc.get("level", 1),
        "startPrice": doc.get("startPrice"),
        "currentPrice": current,
        "hasBids": has_bids,
        "topBidderName": doc.get("topBidderName"),
        "isMine": doc.get("topBidderId") == me,
        "isBorrower": doc.get("borrowerId") == me,
        "minNextBid": round(current * BID_STEP, 2) if has_bids else current,
        "endsAt": _aware(doc["endsAt"]).isoformat(),
        "loanId": doc.get("loanId"),
    }


@router.get("/offers")
async def list_offers(
    _user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    docs = await db.bank_p2p.find({"status": "open"}).sort("_id", -1).to_list(length=200)
    return {"offers": [_serialize(d) for d in docs]}


@router.get("/loans")
async def my_loans(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    uid = str(current_user["_id"])
    docs = await db.bank_p2p.find({
        "status": {"$in": ["active", "frozen"]},
        "$or": [{"lenderId": uid}, {"borrowerId": uid}],
    }).to_list(length=200)
    loans = []
    for d in docs:
        item = _serialize(d)
        item["myRole"] = "borrower" if d.get("borrowerId") == uid else "lender"
        loans.append(item)
    return {"loans": loans}


@router.get("/auctions")
async def list_auctions(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Открытые аукционы изъятого имущества (вкладка банка «Изъятое имущество»)."""
    me = str(current_user["_id"])
    docs = await db.bank_auctions.find({"status": "open"}).sort("_id", -1).to_list(length=200)
    return {"auctions": [_serialize_auction(d, me) for d in docs]}


@router.post("/offers", status_code=status.HTTP_201_CREATED)
async def create_offer(
    payload: OfferCreate,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = {
        "side": payload.side,
        "ownerId": str(current_user["_id"]),
        "ownerName": current_user.get("username"),
        "amount": payload.amount,
        "termDays": payload.term_days,
        "dailyRate": payload.daily_rate,
        "status": "open",
        "createdAt": _now(),
    }
    result = await db.bank_p2p.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


@router.post("/offers/{offer_id}/accept")
async def accept_offer(
    offer_id: str,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not ObjectId.is_valid(offer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объявление не найдено")
    me = str(current_user["_id"])
    offer = await db.bank_p2p.find_one({"_id": ObjectId(offer_id), "status": "open"})
    if not offer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объявление не найдено или уже закрыто")
    if offer["ownerId"] == me:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя принять собственное объявление")

    lender_id = offer["ownerId"] if offer["side"] == "lend" else me
    borrower_id = me if offer["side"] == "lend" else offer["ownerId"]

    # Заявка закрывается атомарно: второй принявший получит отказ.
    now = _now()
    claimed = await db.bank_p2p.find_one_and_update(
        {"_id": offer["_id"], "status": "open"},
        {"$set": {"status": "active", "lenderId": lender_id, "borrowerId": borrower_id,
                  "startedAt": now,
                  "dueAt": now + timedelta(days=offer["termDays"]),
                  "owed": 0.0, "recovered": 0.0}},
        return_document=True,
    )
    if not claimed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Объявление уже принято")

    new_lender = await adjust_balance(db, lender_id, -claimed["amount"])
    if new_lender is None:
        await _reopen_offer(db, offer["_id"])
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У заимодавца недостаточно средств")
    new_borrower = await adjust_balance(db, borrower_id, claimed["amount"])
    if new_borrower is None:
        await adjust_balance(db, lender_id, claimed["amount"])
        await _reopen_offer(db, offer["_id"])
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не удалось зачислить заём заёмщику")

    await record_transaction(db, lender_id, EXPENSE, claimed["amount"], CAT_P2P,
                             "Выдача займа", balance_after=new_lender,
                             meta={"loanId": str(claimed["_id"])})
    await record_transaction(db, borrower_id, INCOME, claimed["amount"], CAT_P2P,
                             "Получение займа", balance_after=new_borrower,
                             meta={"loanId": str(claimed["_id"])})
    return _serialize(claimed)


async def _reopen_offer(db: AsyncIOMotorDatabase, offer_id) -> None:
    await db.bank_p2p.update_one(
        {"_id": offer_id},
        {"$set": {"status": "open"},
         "$unset": {"lenderId": "", "borrowerId": "", "startedAt": "", "dueAt": ""}},
    )


@router.post("/loans/{loan_id}/repay")
async def repay_p2p_loan(
    loan_id: str,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Досрочное погашение: заёмщик возвращает остаток долга (с учётом уже покрытого аукционом)."""
    if not ObjectId.is_valid(loan_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заём не найден")
    me = str(current_user["_id"])
    loan = await db.bank_p2p.find_one({
        "_id": ObjectId(loan_id), "borrowerId": me,
        "status": {"$in": ["active", "frozen"]},
    })
    if not loan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заём не найден")

    total = _total_due(loan)
    new_balance = await adjust_balance(db, me, -total)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для погашения")
    await adjust_balance(db, loan["lenderId"], total)
    await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$set": {"status": "closed", "owed": 0.0}})
    await _release_loan_assets(db, loan)
    await _unfreeze_if_clear(db, me)
    await record_transaction(db, me, EXPENSE, total, CAT_P2P, "Досрочное погашение займа",
                             balance_after=new_balance, meta={"loanId": loan_id})
    await record_transaction(db, loan["lenderId"], INCOME, total, CAT_P2P,
                             "Досрочное погашение займа", meta={"loanId": loan_id})
    return {"balance": new_balance, "repaid": total}


class DonateIn(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v):
        if v is None or v <= 0 or v > MAX_P2P_AMOUNT:
            raise ValueError("Сумма вне допустимого диапазона")
        return round(float(v), 2)


@router.post("/donate")
async def donate_to_bank(
    payload: DonateIn,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Пожертвование банку государства: списание у игрока, зачисление на счёт банка."""
    from achievements import check_achievements

    me = str(current_user["_id"])
    amount = payload.amount
    new_balance = await adjust_balance(db, me, -amount)
    if new_balance is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для пожертвования")
    await credit_state(db, amount, "donation")
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$inc": {"donated_total": amount, "donation_count": 1}},
    )
    await record_transaction(db, me, EXPENSE, amount, "donation", "Пожертвование банку",
                             balance_after=new_balance)
    try:
        await check_achievements(db, me)
    except Exception:
        pass
    return {"balance": new_balance, "donated": amount}


@router.post("/auctions/{auction_id}/bid")
async def bid_auction(
    auction_id: str,
    payload: BidIn,
    current_user: dict = Depends(require_allowed("transfer")),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Ставка на изъятое имущество. Деньги списываются сразу; предыдущему лидеру возвращаются."""
    if not ObjectId.is_valid(auction_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Аукцион не найден")
    me = str(current_user["_id"])
    now = _now()
    auction = await db.bank_auctions.find_one({"_id": ObjectId(auction_id), "status": "open"})
    if not auction:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Аукцион не найден или уже завершён")
    if auction["borrowerId"] == me:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя участвовать в аукционе собственного долга")
    if _aware(auction["endsAt"]) <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Аукцион завершён")
    if auction.get("topBidderId") == me:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ваша ставка уже лидирует")

    amount = round(float(payload.amount), 2)
    current = float(auction["currentPrice"])
    min_bid = round(current * BID_STEP, 2) if auction.get("topBidderId") else current
    if amount < min_bid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Ставка должна быть не ниже {min_bid:,.2f} $")

    # Атомарно: ставка принимается, только если состояние аукциона не изменилось.
    previous = await db.bank_auctions.find_one_and_update(
        {"_id": auction["_id"], "status": "open",
         "currentPrice": current, "topBidderId": auction.get("topBidderId")},
        {"$set": {"currentPrice": amount, "topBidderId": me,
                  "topBidderName": current_user.get("username")}},
        return_document=ReturnDocument.BEFORE,
    )
    if not previous:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ставка уже изменилась, обновите список")

    new_balance = await adjust_balance(db, me, -amount)
    if new_balance is None:
        await db.bank_auctions.update_one(
            {"_id": auction["_id"]},
            {"$set": {"currentPrice": previous["currentPrice"],
                      "topBidderId": previous.get("topBidderId"),
                      "topBidderName": previous.get("topBidderName")}},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств для ставки")

    prev_bidder = previous.get("topBidderId")
    if prev_bidder:
        prev_refund = float(previous["currentPrice"])
        prev_balance = await adjust_balance(db, prev_bidder, prev_refund)
        if prev_balance is not None:
            await record_transaction(db, prev_bidder, INCOME, prev_refund, CAT_P2P,
                                     "Возврат ставки на аукционе", balance_after=prev_balance,
                                     meta={"auctionId": auction_id})
    await record_transaction(db, me, EXPENSE, amount, CAT_P2P, "Ставка на аукционе",
                             balance_after=new_balance, meta={"auctionId": auction_id})
    return {"balance": new_balance, "currentPrice": amount}


async def _freeze_assets(db: AsyncIOMotorDatabase, user_id: str) -> None:
    await db.user_assets.update_many({"userId": user_id}, {"$set": {"frozen": True}})


async def _unfreeze_if_clear(db: AsyncIOMotorDatabase, user_id: str) -> None:
    still_owing = await db.bank_p2p.count_documents({"borrowerId": user_id, "status": "frozen"})
    if still_owing == 0:
        await db.user_assets.update_many({"userId": user_id}, {"$set": {"frozen": False}})


async def _freeze_loan(db: AsyncIOMotorDatabase, loan: dict, now: datetime) -> None:
    """Просрочка: займ заморожен, имущество заёмщика заморожено, отсчёт 24 ч пошёл."""
    await db.bank_p2p.update_one(
        {"_id": loan["_id"]},
        {"$set": {"status": "frozen", "frozenAt": now, "lastSeizureAt": now}},
    )
    await _freeze_assets(db, loan["borrowerId"])


async def accrue_p2p_loans(db: AsyncIOMotorDatabase) -> None:
    """Суточный проход: проценты по активным займам, просрочка, изъятие и аукционы."""
    now = _now()
    async for loan in db.bank_p2p.find({"status": {"$in": ["active", "frozen"]}}):
        if now >= _aware(loan["dueAt"]):
            await _settle_due(db, loan, now)
            continue
        if loan["status"] != "active":
            continue
        interest = round(loan["amount"] * loan["dailyRate"], 2)
        if interest <= 0:
            continue
        borrower, lender = loan["borrowerId"], loan["lenderId"]
        paid = await adjust_balance(db, borrower, -interest)
        if paid is None:
            # Проценты не списались — копятся в задолженность, заморозка будет по сроку.
            await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$inc": {"owed": interest}})
            continue
        await adjust_balance(db, lender, interest)
        await record_transaction(db, borrower, EXPENSE, interest, CAT_P2P, "Проценты по займу",
                                 balance_after=paid, meta={"loanId": str(loan["_id"])})
        await record_transaction(db, lender, INCOME, interest, CAT_P2P, "Проценты по займу",
                                 meta={"loanId": str(loan["_id"])})
    await _process_seizures(db, now)
    await _process_auctions(db, now)


async def _settle_due(db: AsyncIOMotorDatabase, loan: dict, now: datetime) -> None:
    """Срок вышел: списываем остаток долга; нет денег — заморозка."""
    borrower, lender = loan["borrowerId"], loan["lenderId"]
    total = _total_due(loan)
    if total <= 0:
        await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$set": {"status": "closed", "owed": 0.0}})
        await _release_loan_assets(db, loan)
        await _unfreeze_if_clear(db, borrower)
        return
    paid = await adjust_balance(db, borrower, -total)
    if paid is None:
        if loan["status"] != "frozen":
            await _freeze_loan(db, loan, now)
        return
    await adjust_balance(db, lender, total)
    await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$set": {"status": "closed", "owed": 0.0}})
    await _release_loan_assets(db, loan)
    await _unfreeze_if_clear(db, borrower)
    await record_transaction(db, borrower, EXPENSE, total, CAT_P2P, "Возврат займа",
                             balance_after=paid, meta={"loanId": str(loan["_id"])})
    await record_transaction(db, lender, INCOME, total, CAT_P2P, "Возврат займа",
                             meta={"loanId": str(loan["_id"])})


async def _process_seizures(db: AsyncIOMotorDatabase, now: datetime) -> None:
    """Для просроченных займов, где долг не покрыт и нет открытого аукциона,
    по истечении 24 ч изымается одна единица имущества заёмщика."""
    async for loan in db.bank_p2p.find({"status": "frozen"}):
        if _total_due(loan) <= 0:
            continue
        last = _aware(loan.get("lastSeizureAt") or loan.get("frozenAt"))
        if last is None:
            await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$set": {"lastSeizureAt": now}})
            continue
        if now - last < SEIZE_GRACE:
            continue
        if await db.bank_auctions.count_documents({"loanId": str(loan["_id"]), "status": "open"}):
            continue
        asset = await db.user_assets.find_one(
            {"userId": loan["borrowerId"], "frozen": True, "companyId": None},
            sort=[("price", -1)],
        )
        if not asset:
            continue
        await _seize_asset(db, loan, asset, now)


async def _seize_asset(db: AsyncIOMotorDatabase, loan: dict, asset: dict, now: datetime) -> None:
    base = round(_asset_base_value(asset), 2)
    await db.user_assets.update_one(
        {"_id": asset["_id"]},
        {"$set": {"userId": BANK_USER_ID, "seizedFrom": loan["borrowerId"],
                  "seizedLoanId": str(loan["_id"]), "frozen": False}},
    )
    # Выставленные на рынок лоты этого актива снимаем.
    await db.market_lots.update_many(
        {"kind": "asset", "itemId": str(asset["_id"]), "status": "active"},
        {"$set": {"status": "cancelled"}},
    )
    min_price = round(base * AUCTION_MIN_RATIO, 2)
    await db.bank_auctions.insert_one({
        "assetId": str(asset["_id"]),
        "loanId": str(loan["_id"]),
        "borrowerId": loan["borrowerId"],
        "lenderId": loan["lenderId"],
        "name": asset.get("name") or asset.get("slug"),
        "slug": asset.get("slug"),
        "level": asset.get("level", 1),
        "startPrice": base,
        "minPrice": min_price,
        "currentPrice": base,
        "topBidderId": None,
        "topBidderName": None,
        "status": "open",
        "createdAt": now,
        "endsAt": now + AUCTION_DURATION,
    })
    await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$set": {"lastSeizureAt": now}})


async def _process_auctions(db: AsyncIOMotorDatabase, now: datetime) -> None:
    docs = await db.bank_auctions.find({"status": "open", "endsAt": {"$lte": now}}).to_list(length=500)
    for auction in docs:
        await _resolve_auction(db, auction, now)


async def _resolve_auction(db: AsyncIOMotorDatabase, auction: dict, now: datetime) -> None:
    loan = await db.bank_p2p.find_one({"_id": ObjectId(auction["loanId"])})
    if not loan or loan["status"] != "frozen":
        await _cancel_auction(db, auction)
        return

    if not auction.get("topBidderId"):
        # Без ставок: цена снижается, аукцион продлевается.
        new_price = max(round(float(auction["currentPrice"]) * AUCTION_REPRICE, 2),
                        float(auction.get("minPrice", 0)))
        await db.bank_auctions.update_one(
            {"_id": auction["_id"]},
            {"$set": {"currentPrice": new_price, "endsAt": now + AUCTION_DURATION}},
        )
        return

    bid = float(auction["currentPrice"])
    total = _total_due(loan)
    to_lender = round(min(bid, total), 2)
    excess = round(bid - to_lender, 2)
    borrower, lender = loan["borrowerId"], loan["lenderId"]

    await adjust_balance(db, lender, to_lender)
    await record_transaction(db, lender, INCOME, to_lender, CAT_P2P,
                             "Выручка с аукциона изъятого имущества",
                             meta={"loanId": str(loan["_id"]), "auctionId": str(auction["_id"])})
    if excess > 0:
        bal = await adjust_balance(db, borrower, excess)
        await record_transaction(db, borrower, INCOME, excess, CAT_P2P,
                                 "Остаток от аукциона после погашения долга",
                                 balance_after=bal,
                                 meta={"loanId": str(loan["_id"]), "auctionId": str(auction["_id"])})

    await db.user_assets.update_one(
        {"_id": ObjectId(auction["assetId"])},
        {"$set": {"userId": auction["topBidderId"], "frozen": False},
         "$unset": {"seizedFrom": "", "seizedLoanId": ""}},
    )
    await db.bank_auctions.update_one(
        {"_id": auction["_id"]},
        {"$set": {"status": "sold", "soldTo": auction["topBidderId"], "soldFor": bid}},
    )
    await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$inc": {"recovered": to_lender}})

    remaining = round(total - to_lender, 2)
    if remaining <= 0:
        await db.bank_p2p.update_one({"_id": loan["_id"]}, {"$set": {"status": "closed", "owed": 0.0}})
        await _release_loan_assets(db, loan)
        await _unfreeze_if_clear(db, borrower)
    else:
        # Выручки не хватило: следующая единица изымается на ближайшем суточном тике.
        await db.bank_p2p.update_one({"_id": loan["_id"]},
                                     {"$set": {"lastSeizureAt": now - SEIZE_GRACE}})


async def _cancel_auction(db: AsyncIOMotorDatabase, auction: dict) -> None:
    """Отмена аукциона (долг погашен досрочно): возврат ставки и актива заёмщику."""
    if auction.get("topBidderId"):
        refund = float(auction["currentPrice"])
        bal = await adjust_balance(db, auction["topBidderId"], refund)
        if bal is not None:
            await record_transaction(db, auction["topBidderId"], INCOME, refund, CAT_P2P,
                                     "Возврат ставки на аукционе", balance_after=bal,
                                     meta={"auctionId": str(auction["_id"])})
    await db.bank_auctions.update_one({"_id": auction["_id"], "status": "open"},
                                      {"$set": {"status": "cancelled"}})
    await db.user_assets.update_one(
        {"_id": ObjectId(auction["assetId"]), "userId": BANK_USER_ID},
        {"$set": {"userId": auction["borrowerId"], "frozen": True},
         "$unset": {"seizedFrom": "", "seizedLoanId": ""}},
    )


async def _release_loan_assets(db: AsyncIOMotorDatabase, loan: dict) -> None:
    """Займ закрыт: все открытые аукционы по нему отменяются, активы возвращаются."""
    async for auction in db.bank_auctions.find({"loanId": str(loan["_id"]), "status": "open"}):
        await _cancel_auction(db, auction)
