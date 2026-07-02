from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        from pydantic_core import core_schema
        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


class UserDocument(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    username: str
    hashed_password: str
    balance: float = 1000.0
    card_number: Optional[str] = None
    card_visible: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ── Stock ────────────────────────────────────────────────────────────────────


class StockDocument(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    symbol: str
    name: str
    price: float
    change: float
    changePercent: float
    currency: str = "USD"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ── Transaction ──────────────────────────────────────────────────────────────


class TransactionDocument(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    userId: str
    type: str  # "buy" | "sell"
    symbol: str
    amount: float
    price: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ── App Config ───────────────────────────────────────────────────────────────


class AppConfigDocument(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    key: str
    value: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ── Analytics ────────────────────────────────────────────────────────────────


class AnalyticsDocument(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    userId: str
    eventType: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ── Leaderboard ──────────────────────────────────────────────────────────────


class LeaderboardDocument(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    userId: str
    username: str
    avatar: Optional[str] = None
    profit: float = 0.0
    rank: int = 0

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
