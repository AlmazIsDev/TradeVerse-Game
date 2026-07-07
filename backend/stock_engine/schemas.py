"""
StockEngine Pydantic Schemas
=============================
Схемы запросов/ответов для API акций.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Stock Schemas ──────────────────────────────────────────────────────────────


class StockCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, examples=["AAPL"])
    name: str = Field(..., min_length=1, max_length=100, examples=["Apple Inc."])
    price: float = Field(..., gt=0, examples=[10.0])
    total_shares: int = Field(default=1_000_000_000, gt=0)
    free_shares: int = Field(default=1_000_000_000, gt=0)
    currency: str = Field(default="USD", max_length=3)
    config_overrides: Optional[dict] = Field(
        default=None,
        description="Переопределения параметров модели для этой акции",
    )

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        return v.upper()


class StockResponse(BaseModel):
    id: str
    symbol: str
    name: str
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    currency: str = "USD"
    total_shares: Optional[int] = None
    free_shares: Optional[int] = None
    market_cap: Optional[float] = None
    volatility_k: Optional[float] = None
    updated_at: Optional[str] = None
    last_event: Optional[str] = None
    chart: Optional[list] = None

    class Config:
        populate_by_name = True
        extra = "allow"


# ── Order Schemas ──────────────────────────────────────────────────────────────


class StockOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    action: str = Field(..., pattern="^(buy|sell)$")
    quantity: int = Field(..., gt=0, le=10_000_000)

    @field_validator("symbol")
    @classmethod
    def symbol_uppercase(cls, v: str) -> str:
        return v.upper()


class StockOrderResponse(BaseModel):
    id: str
    symbol: str
    action: str
    quantity: int
    price_per_share: Optional[float] = None
    total_cost: Optional[float] = None
    timestamp: Optional[str] = None
    new_stock_price: Optional[float] = None
    event_applied: Optional[str] = None
    is_bot: Optional[bool] = None

    class Config:
        populate_by_name = True


# ── Portfolio Schemas ──────────────────────────────────────────────────────────


class PortfolioItem(BaseModel):
    symbol: str
    name: str
    quantity: int
    average_buy_price: float
    current_price: float
    total_value: float
    profit_loss: float
    profit_loss_percent: float

    class Config:
        populate_by_name = True


class PortfolioResponse(BaseModel):
    user_id: str
    total_value: float
    total_invested: float
    total_profit_loss: float
    items: list[PortfolioItem]

    class Config:
        populate_by_name = True


# ── Event Log Schemas ──────────────────────────────────────────────────────────


class StockEventResponse(BaseModel):
    id: str
    symbol: str
    event_type: str
    event_label: str
    multiplier: float
    price_before: float
    price_after: float
    timestamp: str

    class Config:
        populate_by_name = True


# ── Price History ──────────────────────────────────────────────────────────────


class PriceHistoryPoint(BaseModel):
    price: float
    timestamp: str
    event: Optional[str] = None


class PriceHistoryResponse(BaseModel):
    symbol: str
    points: list[PriceHistoryPoint]