"""Кликер: токен CLICKS, бизнесы и множитель клика."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from bson import ObjectId
from auth import get_current_user
from assets import CATALOG as ASSET_CATALOG
from shop import CATALOG as HARDWARE_CATALOG
from database import get_db, upsert_config
from admin_perms import require_admin
from ledger import EXPENSE, CAT_SYSTEM, adjust_balance, record_transaction

MAX_CLICK_BATCH = 100
DEFAULT_CONFIG = {"clicksPrice": 0.01, "multiplierBaseCost": 1000, "multiplierCostStep": 1500}
CASE_CONFIG = {"basic": {"name": "Эконом кейс", "price": 100000}, "middle": {"name": "Средний кейс", "price": 800000}, "premium": {"name": "Премиум кейс", "price": 3500000}}
COMPONENT_CASES = {"random_component": {"name": "Случайное комплектующее", "price": 500000, "category": None}, "gpu": {"name": "GPU кейс", "price": 1500000, "category": "gpu"}, "cpu": {"name": "CPU кейс", "price": 900000, "category": "cpu"}, "ram": {"name": "RAM кейс", "price": 300000, "category": "ram"}, "psu": {"name": "PSU кейс", "price": 350000, "category": "psu"}, "motherboard": {"name": "Motherboard кейс", "price": 700000, "category": "motherboard"}, "ssd": {"name": "Storage кейс", "price": 250000, "category": "ssd"}, "cooling": {"name": "Cooling кейс", "price": 400000, "category": "cooling"}, "rack": {"name": "Rack кейс", "price": 1200000, "category": "rack"}}
UPGRADES = [("shawarma", "Шаурмечная", "Пассивно производит CLICKS", 100, 1), ("coffee", "Кофейня", "Кофе для бодрых кликов", 500, 5), ("carwash", "Автомойка", "Каждая машина приносит токены", 1500, 15), ("arcade", "Игровой клуб", "Игровые автоматы работают сами", 4000, 45), ("delivery", "Служба доставки", "Курьеры доставляют CLICKS", 10000, 120), ("factory", "Мини-фабрика", "Автоматическое производство", 25000, 300), ("media", "Медиахолдинг", "Реклама генерирует токены", 60000, 750), ("bank", "Микробанк", "Проценты с кликовых вкладов", 150000, 1800), ("space", "Космопорт", "Межпланетные перевозки", 400000, 4500), ("empire", "Империя", "Глобальная сеть бизнеса", 1000000, 12000)]
UPGRADE_MAP = {item[0]: item for item in UPGRADES}
router = APIRouter(prefix="/api/clicker", tags=["clicker"])
admin_router = APIRouter(prefix="/api/admin/clicker", tags=["clicker-admin"])


def build_case_pool(category, catalog): return [item for item in catalog if category is None or item.get("category") == category]
def reward_asset_catalog(reward_type, catalog): return next((item for item in catalog if item.get("type") == {"car": "car", "house": "realestate", "business": "business"}.get(reward_type)), None)
def clicker_event(state): return {"type": "clicker_balance", "clicks": int(state.get("clicks", 0)), "clickPower": int(state.get("clickPower", 1))}
def crypto_reward(coin, amount): return {"type": "crypto", "title": coin["name"], "symbol": coin["symbol"], "amount": amount}
def _percentages(items):
    total = sum(weight for _, weight in items)
    return [{"type": key, "chance": round(weight / total * 100, 2)} for key, weight in items]
def case_odds(case_id):
    return {"basic": _percentages([("crypto", 4), ("coolant", 1), ("sunny_cottage", 1)]), "middle": _percentages([("car", 1), ("house", 1), ("crypto", 1)]), "premium": _percentages([("business", 1), ("crypto", 1)])}.get(case_id, [])
def component_case_odds(category, catalog):
    pool = build_case_pool(category, catalog); chance = round(100 / len(pool), 2) if pool else 0
    return [{"type": "component", "itemId": item["id"], "name": item["name"], "chance": chance} for item in pool]
def _case_pool(category): return build_case_pool(category, HARDWARE_CATALOG)
def _reward_pool(reward_type): return [item for item in ASSET_CATALOG if item.get("type") == {"car": "car", "house": "realestate", "business": "business"}.get(reward_type)]
def _asset_reward_doc(user_id, item):
    now = datetime.now(timezone.utc)
    return {"userId": user_id, "slug": item["slug"], "type": item["type"], "name": item["name"], "category": item.get("category"), "rarity": item.get("rarity"), "rooms": item.get("rooms"), "basement": item.get("basement"), "employees": item.get("employees", 0), "price": float(item.get("price", 0)), "price_mult": 1.0, "income_per_hour": item.get("income_per_hour", 0), "upkeep_per_hour": item.get("upkeep_per_hour", 0), "level": 1, "mining": False, "meta": item.get("meta", {}), "companyId": None, "rental": None, "purchased_at": now, "last_collected": now, "source": "clicker_case"}
def _hardware_reward_doc(user_id, item): return {"userId": user_id, "itemId": item["id"], "category": item["category"], "name": item["name"], "specs": item.get("specs", {}), "farmId": None, "purchase_price": float(item.get("base_price", 0)), "source": "clicker_case"}
async def config(db):
    doc = await db.app_config.find_one({"key": "clicker"}); return {**DEFAULT_CONFIG, **(doc or {})}
async def _wallet_clicks(db, user_id):
    holding = await db.crypto_holdings.find_one({"userId": user_id, "symbol": "CLICKS"}, {"quantity": 1}); return int(float((holding or {}).get("quantity", 0) or 0))
async def _spend_clicks(db, user_id, amount): return await db.crypto_holdings.find_one_and_update({"userId": user_id, "symbol": "CLICKS", "quantity": {"$gte": amount}}, {"$inc": {"quantity": -amount}}, return_document=True)
def view(doc, cfg, wallet_clicks=None):
    doc = doc or {}; mult = int(doc.get("multiplier", 1) or 1)
    upgrades = {key: {"name": name, "description": description, "level": int(doc.get(key, 0) or 0), "cost": cost * (int(doc.get(key, 0) or 0) + 1), "income": income * int(doc.get(key, 0) or 0)} for key, name, description, cost, income in UPGRADES}
    return {"clicks": int(wallet_clicks if wallet_clicks is not None else doc.get("clicks", 0) or 0), "clickPower": mult, "passiveIncome": sum(x["income"] for x in upgrades.values()), "clicksPrice": float(cfg["clicksPrice"]), "multiplierLevel": max(0, mult - 1), "multiplierCost": float(cfg["multiplierBaseCost"]) + max(0, mult - 1) * float(cfg["multiplierCostStep"]), "upgrades": upgrades}
async def _ensure_crypto_holding(db, user_id, amount): await db.crypto_holdings.update_one({"userId": user_id, "symbol": "CLICKS"}, {"$inc": {"quantity": amount}, "$setOnInsert": {"userId": user_id, "symbol": "CLICKS", "avg_price": 0.01}}, upsert=True)
async def _push_clicker_state(user_id, state):
    from ws import push_to_user
    await push_to_user(user_id, clicker_event(state))
async def _collect_passive(db, user_id):
    doc = await db.clicker_progress.find_one({"userId": user_id})
    if not doc: return
    now = datetime.now(timezone.utc); updated = doc.get("updatedAt") or doc.get("createdAt") or now
    if updated.tzinfo is None: updated = updated.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, min((now - updated).total_seconds(), 86400.0)); income = sum(int(doc.get(key, 0) or 0) * income for key, _, _, _, income in UPGRADES); amount = int(elapsed * income)
    if amount > 0: await db.clicker_progress.update_one({"userId": user_id}, {"$inc": {"clicks": amount}, "$set": {"updatedAt": now}}); await _ensure_crypto_holding(db, user_id, amount)
    else: await db.clicker_progress.update_one({"userId": user_id}, {"$set": {"updatedAt": now}})
collect_passive_clicks = _collect_passive

@router.get("")
async def get_clicker(current_user=Depends(get_current_user), db=Depends(get_db)):
    uid = str(current_user["_id"]); await _collect_passive(db, uid); return view(await db.clicker_progress.find_one({"userId": uid}), await config(db), await _wallet_clicks(db, uid))
class ClickPayload(BaseModel): count: int = Field(default=1, ge=1, le=MAX_CLICK_BATCH)
@router.post("/click")
async def click(payload: ClickPayload = ClickPayload(), current_user=Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    uid = str(current_user["_id"]); await _collect_passive(db, uid); old = await db.clicker_progress.find_one({"userId": uid}, {"multiplier": 1}) or {}; amount = payload.count * int(old.get("multiplier", 1) or 1)
    await db.clicker_progress.update_one({"userId": uid}, {"$inc": {"clicks": amount}, "$set": {"updatedAt": datetime.now(timezone.utc)}, "$setOnInsert": {"userId": uid, "multiplier": 1}}, upsert=True); await _ensure_crypto_holding(db, uid, amount)
    state = view(await db.clicker_progress.find_one({"userId": uid}), await config(db), await _wallet_clicks(db, uid)); await _push_clicker_state(uid, state); return state

@router.post("/multiplier")
async def multiplier(current_user=Depends(get_current_user), db=Depends(get_db)):
    uid = str(current_user["_id"]); cfg = await config(db); doc = await db.clicker_progress.find_one({"userId": uid}) or {}; cost = float(cfg["multiplierBaseCost"]) + max(0, int(doc.get("multiplier", 1) or 1) - 1) * float(cfg["multiplierCostStep"]); balance = await adjust_balance(db, uid, -cost)
    if balance is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств")
    result = await db.clicker_progress.find_one_and_update({"userId": uid}, {"$inc": {"multiplier": 1}, "$setOnInsert": {"userId": uid}}, upsert=True, return_document=True); await record_transaction(db, uid, EXPENSE, cost, CAT_SYSTEM, "Улучшение множителя CLICKS", balance_after=balance)
    state = {**view(result, cfg, await _wallet_clicks(db, uid)), "balance": balance}; await _push_clicker_state(uid, state); return state

@router.post("/upgrade/{upgrade_id}")
async def upgrade(upgrade_id, current_user=Depends(get_current_user), db=Depends(get_db)):
    if upgrade_id not in UPGRADE_MAP: raise HTTPException(status.HTTP_404_NOT_FOUND, "Улучшение не найдено")
    uid = str(current_user["_id"]); await _collect_passive(db, uid); cfg = await config(db); doc = await db.clicker_progress.find_one({"userId": uid}) or {}; _, _, _, base, _ = UPGRADE_MAP[upgrade_id]; cost = base * (int(doc.get(upgrade_id, 0) or 0) + 1)
    if await _spend_clicks(db, uid, cost) is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно CLICKS")
    result = await db.clicker_progress.find_one_and_update({"userId": uid}, {"$inc": {upgrade_id: 1}}, return_document=True); state = view(result, cfg, await _wallet_clicks(db, uid)); await _push_clicker_state(uid, state); return state

class CasePurchase(BaseModel): case_id: str
@router.get("/component-cases")
async def component_cases(current_user=Depends(get_current_user)): return [{"id": k, **v, "odds": component_case_odds(v["category"], _case_pool(v["category"]))} for k, v in COMPONENT_CASES.items()]
@router.get("/cases")
async def cases(current_user=Depends(get_current_user)): return [{"id": k, **v, "odds": case_odds(k)} for k, v in CASE_CONFIG.items()]

async def _grant_asset_reward(db, user_id, reward_type):
    item = reward_asset_catalog(reward_type, ASSET_CATALOG)
    if item is None: raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Для награды нет доступного актива")
    result = await db.user_assets.insert_one(_asset_reward_doc(user_id, item)); return {"type": reward_type, "title": item["name"], "slug": item["slug"], "assetId": str(result.inserted_id)}
@router.post("/cases/open")
async def open_case(payload: CasePurchase, current_user=Depends(get_current_user), db=Depends(get_db)):
    import random
    uid = str(current_user["_id"]); case = COMPONENT_CASES.get(payload.case_id)
    if case:
        pool = _case_pool(case["category"])
        if not pool: raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Для этого кейса нет доступных комплектующих")
        if await _spend_clicks(db, uid, case["price"]) is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно CLICKS")
        item = random.choice(pool)
        try:
            await db.user_hardware.insert_one(_hardware_reward_doc(uid, item))
        except Exception:
            await _ensure_crypto_holding(db, uid, case["price"])
            raise
        reward = {"type": "component", "title": item["name"], "itemId": item["id"]}
    else:
        if payload.case_id not in CASE_CONFIG: raise HTTPException(status.HTTP_404_NOT_FOUND, "Кейс не найден")
        price = CASE_CONFIG[payload.case_id]["price"]; roll = random.choices(["crypto", "coolant", "sunny_cottage"], weights=[4, 1, 1])[0] if payload.case_id == "basic" else random.choice(["car", "house", "crypto"] if payload.case_id == "middle" else ["business", "crypto"])
        if await _spend_clicks(db, uid, price) is None: raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно CLICKS")
        if roll == "crypto":
            from crypto import DEFAULT_COINS
            coin = random.choice([c for c in DEFAULT_COINS if c["symbol"] != "CLICKS"]); amount = random.randint(1, 3 if payload.case_id == "basic" else 10); await db.crypto_holdings.update_one({"userId": uid, "symbol": coin["symbol"]}, {"$inc": {"quantity": amount}, "$setOnInsert": {"userId": uid, "symbol": coin["symbol"], "avg_price": 0}}, upsert=True); reward = crypto_reward(coin, amount)
        elif roll == "coolant":
            await db.user_hardware.insert_one({"userId": uid, "itemId": "coolant", "name": "Охлаждающая жидкость", "category": "cooling", "farmId": None, "quantity": 1, "source": "clicker_case"})
            reward = {"type": "coolant", "title": "Охлаждающая жидкость", "amount": 1}
        else: reward = await _grant_asset_reward(db, uid, "house" if roll == "sunny_cottage" else roll)
        await record_transaction(db, uid, EXPENSE, price, CAT_SYSTEM, f"Открытие кейса: {CASE_CONFIG[payload.case_id]['name']}", meta={"case": payload.case_id})
    state = {"case": payload.case_id, "reward": reward, **view(await db.clicker_progress.find_one({"userId": uid}), await config(db), await _wallet_clicks(db, uid))}; await _push_clicker_state(uid, state); return state

@router.get("/leaderboard")
async def leaderboard(db=Depends(get_db)):
    docs = [d async for d in db.clicker_progress.find().sort("clicks", -1).limit(20)]; ids = [ObjectId(d["userId"]) for d in docs if ObjectId.is_valid(d.get("userId", ""))]; users = {str(u["_id"]): u async for u in db.users.find({"_id": {"$in": ids}}, {"username": 1, "avatar": 1})}; return [{"userId": d.get("userId"), "username": users.get(d.get("userId"), {}).get("username", "—"), "avatar": users.get(d.get("userId"), {}).get("avatar"), "clicks": int(d.get("clicks", 0))} for d in docs]
@admin_router.get("")
async def admin_get(current_user=Depends(require_admin("economy_view")), db=Depends(get_db)): return await config(db)
class ConfigPatch(BaseModel): clicksPrice: float = Field(gt=0); multiplierBaseCost: float = Field(gt=0); multiplierCostStep: float = Field(gt=0)
@admin_router.patch("")
async def admin_patch(payload: ConfigPatch, current_user=Depends(require_admin("economy_edit")), db=Depends(get_db)): await upsert_config(db, "clicker", payload.model_dump()); return payload.model_dump()
