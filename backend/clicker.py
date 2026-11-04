"""Кликер: токен CLICKS, бизнесы и множитель клика."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from bson import ObjectId
from auth import get_current_user
from database import get_db, upsert_config
from admin_perms import require_admin
from ledger import INCOME, EXPENSE, CAT_SYSTEM, adjust_balance, record_transaction

router = APIRouter(prefix="/api/clicker", tags=["clicker"])
admin_router = APIRouter(prefix="/api/admin/clicker", tags=["clicker-admin"])
DEFAULT_CONFIG = {"clicksPrice": 0.01, "multiplierBaseCost": 1000, "multiplierCostStep": 1500}
CASE_CONFIG = {"basic": {"name": "Эконом кейс", "price": 100000}, "middle": {"name": "Средний кейс", "price": 800000}, "premium": {"name": "Премиум кейс", "price": 3500000}}
COMPONENT_CASES = {"random_component": {"name": "Случайное комплектующее", "price": 500000, "category": None}, "gpu": {"name": "GPU кейс", "price": 1500000, "category": "gpu"}, "cpu": {"name": "CPU кейс", "price": 900000, "category": "cpu"}, "ram": {"name": "RAM кейс", "price": 300000, "category": "ram"}, "psu": {"name": "PSU кейс", "price": 350000, "category": "psu"}, "motherboard": {"name": "Motherboard кейс", "price": 700000, "category": "motherboard"}, "ssd": {"name": "Storage кейс", "price": 250000, "category": "ssd"}, "cooling": {"name": "Cooling кейс", "price": 400000, "category": "cooling"}, "rack": {"name": "Rack кейс", "price": 1200000, "category": "rack"}}
UPGRADES = [
    ("shawarma", "Шаурмечная", "Пассивно производит CLICKS", 100, 1),
    ("coffee", "Кофейня", "Кофе для бодрых кликов", 500, 5),
    ("carwash", "Автомойка", "Каждая машина приносит токены", 1500, 15),
    ("arcade", "Игровой клуб", "Игровые автоматы работают сами", 4000, 45),
    ("delivery", "Служба доставки", "Курьеры доставляют CLICKS", 10000, 120),
    ("factory", "Мини-фабрика", "Автоматическое производство", 25000, 300),
    ("media", "Медиахолдинг", "Реклама генерирует токены", 60000, 750),
    ("bank", "Микробанк", "Проценты с кликовых вкладов", 150000, 1800),
    ("space", "Космопорт", "Межпланетные перевозки", 400000, 4500),
    ("empire", "Империя", "Глобальная сеть бизнеса", 1000000, 12000),
]
UPGRADE_MAP = {item[0]: item for item in UPGRADES}

async def config(db):
    doc = await db.app_config.find_one({"key": "clicker"})
    return {**DEFAULT_CONFIG, **(doc or {})}

async def _wallet_clicks(db, user_id: str) -> int:
    holding = await db.crypto_holdings.find_one({"userId": user_id, "symbol": "CLICKS"}, {"quantity": 1})
    return int(float((holding or {}).get("quantity", 0) or 0))

async def _spend_clicks(db, user_id: str, amount: int):
    return await db.crypto_holdings.find_one_and_update(
        {"userId": user_id, "symbol": "CLICKS", "quantity": {"$gte": amount}},
        {"$inc": {"quantity": -amount}}, return_document=True,
    )

def view(doc, cfg, wallet_clicks=None):
    doc = doc or {}; mult = int(doc.get("multiplier", 1) or 1)
    upgrades = {}
    for key, name, description, cost, income in UPGRADES:
        level = int(doc.get(key, 0) or 0)
        upgrades[key] = {"name": name, "description": description, "level": level, "cost": cost * (level + 1), "income": income * level}
    return {"clicks": int(wallet_clicks if wallet_clicks is not None else doc.get("clicks", 0) or 0), "clickPower": mult, "passiveIncome": sum(x["income"] for x in upgrades.values()), "clicksPrice": float(cfg["clicksPrice"]), "multiplierLevel": max(0, mult - 1), "multiplierCost": float(cfg["multiplierBaseCost"]) + max(0, mult - 1) * float(cfg["multiplierCostStep"]), "upgrades": upgrades}

async def _ensure_crypto_holding(db, user_id: str, amount: float):
    await db.crypto_holdings.update_one(
        {"userId": user_id, "symbol": "CLICKS"},
        {"$inc": {"quantity": amount}, "$setOnInsert": {"userId": user_id, "symbol": "CLICKS", "avg_price": 0.01}},
        upsert=True,
    )


async def _collect_passive(db, user_id: str) -> None:
    doc = await db.clicker_progress.find_one({"userId": user_id})
    if not doc:
        return
    now = datetime.now(timezone.utc)
    updated = doc.get("updatedAt") or doc.get("createdAt") or now
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, min((now - updated).total_seconds(), 86400.0))
    income = sum(int(doc.get(key, 0) or 0) * income for key, _, _, _, income in UPGRADES)
    if elapsed > 0 and income > 0:
        amount = int(elapsed * income)
        if amount > 0:
            await db.clicker_progress.update_one({"userId": user_id}, {"$inc": {"clicks": amount}, "$set": {"updatedAt": now}})
            await _ensure_crypto_holding(db, user_id, amount)
            return
    await db.clicker_progress.update_one({"userId": user_id}, {"$set": {"updatedAt": now}})


collect_passive_clicks = _collect_passive


@router.get("")
async def get_clicker(current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    uid = str(current_user["_id"])
    await _collect_passive(db, uid)
    return view(await db.clicker_progress.find_one({"userId": uid}), await config(db), await _wallet_clicks(db, uid))

@router.post("/click")
async def click(current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    uid = str(current_user["_id"])
    await _collect_passive(db, uid)
    old = await db.clicker_progress.find_one({"userId": uid}) or {}; power = int(old.get("multiplier", 1) or 1)
    doc = await db.clicker_progress.find_one_and_update({"userId": uid}, {"$inc": {"clicks": power}, "$set": {"updatedAt": datetime.now(timezone.utc)}, "$setOnInsert": {"userId": uid, "multiplier": 1}}, upsert=True, return_document=True)
    await _ensure_crypto_holding(db, uid, power)
    return view(doc, await config(db), await _wallet_clicks(db, uid))

@router.post("/multiplier")
async def multiplier(current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    uid = str(current_user["_id"]); cfg = await config(db); doc = await db.clicker_progress.find_one({"userId": uid}) or {}; level = max(0, int(doc.get("multiplier", 1) or 1) - 1); cost = float(cfg["multiplierBaseCost"]) + level * float(cfg["multiplierCostStep"])
    balance = await adjust_balance(db, uid, -cost)
    if balance is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    result = await db.clicker_progress.find_one_and_update({"userId": uid}, {"$inc": {"multiplier": 1}, "$setOnInsert": {"userId": uid}}, upsert=True, return_document=True)
    await record_transaction(db, uid, EXPENSE, cost, CAT_SYSTEM, "Улучшение множителя CLICKS", balance_after=balance)
    return {**view(result, cfg), "balance": balance}

@router.post("/upgrade/{upgrade_id}")
async def upgrade(upgrade_id: str, current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    if upgrade_id not in UPGRADE_MAP: raise HTTPException(status.HTTP_404_NOT_FOUND, "Улучшение не найдено")
    uid = str(current_user["_id"]); await _collect_passive(db, uid); cfg = await config(db); doc = await db.clicker_progress.find_one({"userId": uid}) or {}; _, _, _, base, _ = UPGRADE_MAP[upgrade_id]; level = int(doc.get(upgrade_id, 0) or 0); cost = base * (level + 1)
    result = await _spend_clicks(db, uid, cost)
    if result is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно CLICKS")
    result = await db.clicker_progress.find_one_and_update({"userId": uid}, {"$inc": {upgrade_id: 1}}, return_document=True)
    return view(result, cfg)

class CasePurchase(BaseModel):
    case_id: str


@router.get("/component-cases")
async def component_cases(current_user=Depends(get_current_user)):
    return [{"id": key, **value} for key, value in COMPONENT_CASES.items()]


@router.get("/cases")
async def cases(current_user=Depends(get_current_user)):
    return [{"id": key, **value} for key, value in CASE_CONFIG.items()]


@router.post("/cases/open")
async def open_case(payload: CasePurchase, current_user=Depends(get_current_user), db: AsyncIOMotorDatabase=Depends(get_db)):
    import random
    if payload.case_id in COMPONENT_CASES:
        price = COMPONENT_CASES[payload.case_id]["price"]
        spent = await _spend_clicks(db, str(current_user["_id"]), price)
        if spent is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно CLICKS")
        from shop import CATALOG
        category = COMPONENT_CASES[payload.case_id]["category"]
        pool = [item for item in CATALOG if category is None or item.get("category") == category]
        if not pool: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для этого кейса нет доступных комплектующих")
        item = random.choice(pool)
        await db.user_hardware.insert_one({"userId": str(current_user["_id"]), "itemId": item["id"], "category": item["category"], "name": item["name"], "specs": item.get("specs", {}), "farmId": None, "purchase_price": 0})
        return {"case": payload.case_id, "reward": {"type": "component", "title": item["name"], "itemId": item["id"]}, **view(spent, await config(db))}
    if payload.case_id not in CASE_CONFIG:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кейс не найден")
    uid = str(current_user["_id"]); price = CASE_CONFIG[payload.case_id]["price"]
    spent = await _spend_clicks(db, uid, price)
    if spent is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно CLICKS")
    if payload.case_id == "basic":
        roll = random.choices(["crypto", "coolant", "sunny_cottage"], weights=[4, 1, 1])[0]
    elif payload.case_id == "middle":
        roll = random.choice(["car", "house", "bitcoin"])
    else:
        roll = random.choice(["business", "crypto"])
    reward = {"type": roll, "title": {"crypto": "Случайная криптовалюта", "coolant": "Охлаждающая жидкость", "sunny_cottage": "Коттедж «Солнечный»", "car": "Случайный автомобиль", "house": "Случайный дом", "bitcoin": "Bitcoin", "business": "Случайный бизнес"}[roll]}
    if roll == "crypto":
        symbol = random.choice(["WVC", "TVX", "NEON", "GLD", "MEME"]); amount = random.randint(1, 3 if payload.case_id == "basic" else 10)
        await db.crypto_holdings.update_one({"userId": uid, "symbol": symbol}, {"$inc": {"quantity": amount}, "$setOnInsert": {"userId": uid, "symbol": symbol, "avg_price": 0}}, upsert=True); reward.update(symbol=symbol, amount=amount)
    elif roll == "coolant":
        await db.user_hardware.insert_one({"userId": uid, "itemId": "coolant", "name": "Охлаждающая жидкость", "category": "cooling", "farmId": None, "quantity": 1}); reward["amount"] = 1
    elif roll == "sunny_cottage":
        reward.update(slug="sunny_cottage", amount=1)
    await record_transaction(db, uid, EXPENSE, price, CAT_SYSTEM, f"Открытие кейса: {CASE_CONFIG[payload.case_id]['name']}", meta={"case": payload.case_id})
    return {"case": payload.case_id, "reward": reward, **view(spent, await config(db), await _wallet_clicks(db, uid))}

# CLICKS продаётся только через стандартный раздел криптовалют.

@router.get("/leaderboard")
async def leaderboard(db: AsyncIOMotorDatabase=Depends(get_db)):
    rows=[]
    async for doc in db.clicker_progress.find().sort("clicks", -1).limit(20):
        user = await db.users.find_one({"_id": ObjectId(doc["userId"])}, {"username": 1})
        rows.append({"username": (user or {}).get("username", "—"), "clicks": int(doc.get("clicks", 0))})
    return rows

@admin_router.get("")
async def admin_get(current_user=Depends(require_admin("economy_view")), db: AsyncIOMotorDatabase=Depends(get_db)): return await config(db)
class ConfigPatch(BaseModel): clicksPrice: float = Field(gt=0); multiplierBaseCost: float = Field(gt=0); multiplierCostStep: float = Field(gt=0)
@admin_router.patch("")
async def admin_patch(payload: ConfigPatch, current_user=Depends(require_admin("economy_edit")), db: AsyncIOMotorDatabase=Depends(get_db)):
    await upsert_config(db, "clicker", payload.model_dump()); return payload.model_dump()
