import asyncio
import logging
import os
import bcrypt
from database import get_db, get_stocks_collection, get_app_config_collection

logger = logging.getLogger("tradeverse.init")

# Пароль администратора берётся из окружения. Значение по умолчанию оставлено
# только для локальной разработки — обязательно переопределите ADMIN_PASSWORD
# перед развёртыванием в production.
_DEFAULT_ADMIN_PASSWORD = "9HfrvyIVe5LDkQ63TRFEOZNP8SsJab4h"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)


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
        hashed = bcrypt.hashpw(ADMIN_PASSWORD.encode("utf-8"), salt).decode("utf-8")
        await db.users.insert_one({
            "username": "admin",
            "hashed_password": hashed,
            "role": "admin",
            "balance": 1000.0,
            "card_number": None,
            "card_visible": True,
        })
        if ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD:
            logger.warning(
                "Создан admin с паролем по умолчанию. Задайте ADMIN_PASSWORD "
                "в окружении и смените пароль перед production-развёртыванием."
            )
        else:
            logger.info("Создан admin-пользователь с паролем из ADMIN_PASSWORD.")
    else:
        logger.info("Admin-пользователь уже существует.")

    # Seed default stocks if none exist
    stocks_count = await db.stocks.count_documents({})
    if stocks_count == 0:
        default_stocks = [
            {"symbol": "AAPL", "name": "Apple Inc.", "price": 195.50, "change": 2.30, "changePercent": 1.19, "currency": "USD"},
            {"symbol": "GOOGL", "name": "Alphabet Inc.", "price": 141.80, "change": -1.20, "changePercent": -0.84, "currency": "USD"},
            {"symbol": "MSFT", "name": "Microsoft Corp.", "price": 378.90, "change": 4.50, "changePercent": 1.20, "currency": "USD"},
            {"symbol": "AMZN", "name": "Amazon.com Inc.", "price": 178.25, "change": 1.80, "changePercent": 1.02, "currency": "USD"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "price": 248.50, "change": -3.20, "changePercent": -1.27, "currency": "USD"},
            {"symbol": "NVDA", "name": "NVIDIA Corp.", "price": 875.30, "change": 15.60, "changePercent": 1.81, "currency": "USD"},
        ]
        for stock in default_stocks:
            await db.stocks.insert_one(stock)
        logger.info("Seeded %d default stocks", len(default_stocks))

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
    logger.info("Default config seeded")

    logger.info("Database initialization complete!")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(init())
