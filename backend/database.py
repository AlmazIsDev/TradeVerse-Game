import os
from datetime import datetime
from typing import Any, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

DATABASE_NAME = "tradeverse"

client = AsyncIOMotorClient(MONGODB_URL)
db: AsyncIOMotorDatabase = client[DATABASE_NAME]


def get_db() -> AsyncIOMotorDatabase:
    return db


# ── Collection helpers ───────────────────────────────────────────────────────


def get_stocks_collection(db: AsyncIOMotorDatabase):
    return db.stocks


def get_transactions_collection(db: AsyncIOMotorDatabase):
    return db.transactions


def get_app_config_collection(db: AsyncIOMotorDatabase):
    return db.app_config


def get_analytics_collection(db: AsyncIOMotorDatabase):
    return db.analytics


def get_leaderboard_collection(db: AsyncIOMotorDatabase):
    return db.leaderboard


# ── Stock operations ─────────────────────────────────────────────────────────


async def find_all_stocks(db: AsyncIOMotorDatabase) -> list[dict]:
    stocks = []
    cursor = db.stocks.find({}).sort("symbol", 1)
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        stocks.append(doc)
    return stocks


async def find_stock_by_symbol(
    db: AsyncIOMotorDatabase, symbol: str
) -> Optional[dict]:
    doc = await db.stocks.find_one({"symbol": symbol.upper()})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def upsert_stock(db: AsyncIOMotorDatabase, stock_data: dict) -> dict:
    stock_data["symbol"] = stock_data["symbol"].upper()
    stock_data["updated_at"] = datetime.utcnow()
    result = await db.stocks.update_one(
        {"symbol": stock_data["symbol"]},
        {"$set": stock_data},
        upsert=True,
    )
    return await find_stock_by_symbol(db, stock_data["symbol"])


# ── Transaction operations ───────────────────────────────────────────────────


async def find_transactions_by_user(
    db: AsyncIOMotorDatabase, user_id: str | None, limit: int = 50
) -> list[dict]:
    transactions = []
    query = {} if not user_id else {"userId": user_id}
    cursor = (
        db.transactions.find(query)
        .sort("timestamp", -1)
        .limit(limit)
    )
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        transactions.append(doc)
    return transactions


async def find_all_transactions(db: AsyncIOMotorDatabase, limit: int = 200) -> list[dict]:
    transactions = []
    cursor = db.transactions.find({}).sort("timestamp", -1).limit(limit)
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        transactions.append(doc)
    return transactions


async def delete_transaction(db: AsyncIOMotorDatabase, tx_id: str) -> bool:
    from bson import ObjectId
    result = await db.transactions.delete_one({"_id": ObjectId(tx_id)})
    return result.deleted_count > 0


async def delete_stock_by_symbol(db: AsyncIOMotorDatabase, symbol: str) -> bool:
    result = await db.stocks.delete_one({"symbol": symbol.upper()})
    return result.deleted_count > 0


async def find_all_users(db: AsyncIOMotorDatabase) -> list[dict]:
    users = []
    cursor = db.users.find({}).sort("username", 1)
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        doc.pop("hashed_password", None)
        doc["role"] = doc.get("role", "user")
        users.append(doc)
    return users


# ── App Config operations ────────────────────────────────────────────────────


async def find_config_by_key(db: AsyncIOMotorDatabase, key: str) -> Optional[dict]:
    doc = await db.app_config.find_one({"key": key})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc


async def upsert_config(db: AsyncIOMotorDatabase, key: str, value: str) -> dict:
    await db.app_config.update_one(
        {"key": key},
        {"$set": {"key": key, "value": value, "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    return await find_config_by_key(db, key)


# ── Analytics operations ─────────────────────────────────────────────────────


async def insert_analytics_event(db: AsyncIOMotorDatabase, event: dict) -> str:
    event["timestamp"] = datetime.utcnow()
    result = await db.analytics.insert_one(event)
    return str(result.inserted_id)


# ── Leaderboard operations ───────────────────────────────────────────────────


async def find_leaderboard(
    db: AsyncIOMotorDatabase, limit: int = 20
) -> list[dict]:
    entries = []
    cursor = (
        db.leaderboard.find({}).sort("profit", -1).limit(limit)
    )
    rank = 1
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        doc["rank"] = rank
        rank += 1
        entries.append(doc)
    return entries
