import asyncio
import bcrypt
from database import get_db, get_stocks_collection, get_app_config_collection


async def init():
    db = get_db()

    # Create indexes
    await db.users.create_index("username", unique=True)
    await db.stocks.create_index("symbol", unique=True)
    await db.app_config.create_index("key", unique=True)

    # Create default admin user
    existing_admin = await db.users.find_one({"username": "admin"})
    if not existing_admin:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(b"9HfrvyIVe5LDkQ63TRFEOZNP8SsJab4h", salt).decode("utf-8")
        await db.users.insert_one({
            "username": "admin",
            "hashed_password": hashed,
            "role": "admin",
        })
        print("Default admin user created (admin / 9HfrvyIVe5LDkQ63TRFEOZNP8SsJab4h)")
    else:
        print("Admin user already exists")

<<<<<<< HEAD
    # Seed default stocks if none exist
    stocks_count = await db.stocks.count_documents({})
    if stocks_count == 0:
        default_stocks = [
            {"symbol": "AAPL", "name": "Apple Inc.", "price": 195.50, "change": 2.30, "changePercent": 1.19, "currency": "USD", "total_shares": 1_000_000_000, "free_shares": 1_000_000_000},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "price": 141.80, "change": -1.20, "changePercent": -0.84, "currency": "USD", "total_shares": 1_000_000_000, "free_shares": 1_000_000_000},
            {"symbol": "MSFT", "name": "Microsoft Corp.", "price": 378.90, "change": 4.50, "changePercent": 1.20, "currency": "USD", "total_shares": 1_000_000_000, "free_shares": 1_000_000_000},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "price": 178.25, "change": 1.80, "changePercent": 1.02, "currency": "USD", "total_shares": 1_000_000_000, "free_shares": 1_000_000_000},
            {"symbol": "TSLA", "name": "Tesla Inc.", "price": 248.50, "change": -3.20, "changePercent": -1.27, "currency": "USD", "total_shares": 1_000_000_000, "free_shares": 1_000_000_000},
            {"symbol": "NVDA", "name": "NVIDIA Corp.", "price": 875.30, "change": 15.60, "changePercent": 1.81, "currency": "USD", "total_shares": 1_000_000_000, "free_shares": 1_000_000_000},
        ]
        for stock in default_stocks:
            await db.stocks.insert_one(stock)
        print(f"Seeded {len(default_stocks)} default stocks")
=======
    # Реальные мировые компании — гарантируем их наличие, чтобы страница акций
    # НИКОГДА не была пустой (даже если внешний API котировок недоступен). Цены —
    # разумная стартовая точка; фоновый Scheduler обновит их реальными данными.
    world_stocks = [
        {"symbol": "AAPL", "name": "Apple Inc.", "price": 195.50},
        {"symbol": "MSFT", "name": "Microsoft Corp.", "price": 378.90},
        {"symbol": "GOOGL", "name": "Alphabet Inc.", "price": 141.80},
        {"symbol": "AMZN", "name": "Amazon.com Inc.", "price": 178.25},
        {"symbol": "NVDA", "name": "NVIDIA Corp.", "price": 875.30},
        {"symbol": "META", "name": "Meta Platforms Inc.", "price": 485.60},
        {"symbol": "TSLA", "name": "Tesla Inc.", "price": 248.50},
        {"symbol": "NFLX", "name": "Netflix Inc.", "price": 612.40},
        {"symbol": "AMD", "name": "Advanced Micro Devices", "price": 168.20},
        {"symbol": "INTC", "name": "Intel Corp.", "price": 43.10},
        {"symbol": "ORCL", "name": "Oracle Corp.", "price": 125.70},
        {"symbol": "ADBE", "name": "Adobe Inc.", "price": 560.30},
        {"symbol": "CRM", "name": "Salesforce Inc.", "price": 298.40},
        {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "price": 198.90},
        {"symbol": "V", "name": "Visa Inc.", "price": 275.10},
        {"symbol": "WMT", "name": "Walmart Inc.", "price": 68.50},
        {"symbol": "DIS", "name": "The Walt Disney Company", "price": 102.30},
        {"symbol": "KO", "name": "The Coca-Cola Company", "price": 62.80},
        {"symbol": "PEP", "name": "PepsiCo Inc.", "price": 171.40},
        {"symbol": "BABA", "name": "Alibaba Group", "price": 78.60},
    ]
    added = 0
    for stock in world_stocks:
        res = await db.stocks.update_one(
            {"symbol": stock["symbol"]},
            {"$setOnInsert": {
                "symbol": stock["symbol"], "name": stock["name"],
                "price": stock["price"], "change": 0.0, "changePercent": 0.0,
                "currency": "USD",
            }},
            upsert=True,
        )
        if res.upserted_id is not None:
            added += 1
    print(f"World stocks ensured (added {added})")
>>>>>>> origin/Marlow

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
