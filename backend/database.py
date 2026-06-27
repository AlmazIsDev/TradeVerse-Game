import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")

DATABASE_NAME = "tradeverse"

client = AsyncIOMotorClient(MONGODB_URL)
db = client[DATABASE_NAME]


def get_db():
    return db
