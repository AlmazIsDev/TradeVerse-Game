import asyncio
import os
import secrets

import bcrypt
from database import get_db, get_stocks_collection, get_app_config_collection, delete_stock_by_symbol
from ledger import adjust_balance


async def init():
    db = get_db()

    # Create indexes
    await db.users.create_index("username", unique=True)
    await db.stocks.create_index("symbol", unique=True)
    await db.app_config.create_index("key", unique=True)

    # Create default admin user
    existing_admin = await db.users.find_one({"username": "admin"})
    if not existing_admin:
        admin_password = os.getenv("ADMIN_PASSWORD")
        generated = admin_password is None
        if generated:
            admin_password = secrets.token_urlsafe(18)
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(admin_password.encode("utf-8"), salt).decode("utf-8")
        await db.users.insert_one({
            "username": "admin",
            "hashed_password": hashed,
            "role": "admin",
        })
        if generated:
            print(f"Default admin user created (admin / {admin_password}) — ADMIN_PASSWORD not set, generated a random one. Save it now, it won't be shown again.")
        else:
            print("Default admin user created (admin / <ADMIN_PASSWORD from .env>)")
    else:
        print("Admin user already exists")

    # Seed default stocks if none exist
    stocks_count = await db.stocks.count_documents({})
    if stocks_count == 0:
        default_stocks = [
            {"symbol": "AAPL", "name": "Apple Inc.", "price": 195.50, "change": 2.30, "changePercent": 1.19, "currency": "USD"},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "price": 141.80, "change": -1.20, "changePercent": -0.84, "currency": "USD"},
            {"symbol": "MSFT", "name": "Microsoft Corp.", "price": 378.90, "change": 4.50, "changePercent": 1.20, "currency": "USD"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "price": 248.50, "change": -3.20, "changePercent": -1.27, "currency": "USD"},
            {"symbol": "NVDA", "name": "NVIDIA Corp.", "price": 875.30, "change": 15.60, "changePercent": 1.81, "currency": "USD"},
        ]
        for stock in default_stocks:
            await db.stocks.insert_one(stock)
        print(f"Seeded {len(default_stocks)} default stocks")

    # Одноразовая миграция: системных акций должно быть ровно 5 (см. default_stocks
    # выше). Более старая версия init_db на каждом старте апсертила ~20 «мировых»
    # компаний — эти лишние тикеры могли осесть в уже существующих базах. Удаляем
    # всё системное (issuer пуст), чего нет в каноническом списке, с возвратом денег.
    canonical_symbols = {"AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"}
    stale_cursor = db.stocks.find({"symbol": {"$nin": list(canonical_symbols)}, "issuer": {"$in": [None, ""]}})
    stale_symbols = [s["symbol"] async for s in stale_cursor]
    for symbol in stale_symbols:
        async for holding in db.stock_holdings.find({"symbol": symbol, "quantity": {"$gt": 0}}):
            invested = holding.get("invested", 0)
            if invested > 0:
                await adjust_balance(db, holding["userId"], invested)
        await db.stock_holdings.delete_many({"symbol": symbol})
        await delete_stock_by_symbol(db, symbol)
    if stale_symbols:
        print(f"Migration: removed {len(stale_symbols)} stale system stocks ({', '.join(stale_symbols)}), holders refunded")

    # Одноразовая миграция: слаг "itstudio" (старая единая IT-студия) заменён
    # на 4 тира (itstudio_basic/medium/advanced/premium, см. assets.py CATALOG)
    # — существующие экземпляры переносим в базовый тир и инициализируем поля
    # прокачки/материалов, которых раньше не было.
    migrated = await db.user_assets.update_many(
        {"slug": "itstudio"},
        {"$set": {"slug": "itstudio_basic", "studioXp": 0, "itstudioMaterials": {}}},
    )
    if migrated.modified_count:
        print(f"Migration: {migrated.modified_count} IT-студия → itstudio_basic (новые тиры)")
    await db.user_assets.update_many(
        {
            "slug": {"$in": ["itstudio_basic", "itstudio_medium", "itstudio_advanced", "itstudio_premium"]},
            "studioXp": {"$exists": False},
        },
        {"$set": {"studioXp": 0, "itstudioMaterials": {}}},
    )

    # Seed default config
    default_config = [
        {"key": "sidebar_menu", "value": '{"items":["account","bank","shop","events","crypto","stocks","realestate","myhomes","mybusiness","mycompany","leaderboard"]}'},
        {"key": "header_title", "value": "TradeVerse"},
        {"key": "app_version", "value": "1.0.0"},
    ]
    for cfg in default_config:
        existing = await db.app_config.find_one({"key": cfg["key"]})
        if not existing:
            await db.app_config.insert_one(cfg)
    print("Default config seeded")

    print("Database initialization complete!")


if __name__ == "__main__":
    asyncio.run(init())
