"""Схема исполнения сделок: середина прохода, round-trip убыточен.

Запуск: python backend/test_trade_fill.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from stocks import _quote_stock

P = 756.48
QTY = 10_000_000
TOTAL = 1_000_000_000
stock = {"price": P, "free_shares": TOTAL,
         "config": {"total_shares": TOTAL, "volatility_k": 0.1}}

q = _quote_stock(stock, "buy", QTY)
delta = P * 0.1 * QTY / TOTAL
assert abs(q["fillPrice"] - (P + delta / 2)) < 0.01, q
assert abs(q["nextPrice"] - (P + delta)) < 0.01, q

# round-trip buy→sell по сдвинутому рынку — убыточен (комиссия с обеих сторон)
s = _quote_stock(dict(stock, price=q["nextPrice"]), "sell", QTY)
assert s["total"] < q["cost"], (s["total"], q["cost"])

from crypto import _project_fill

coin = {"price": P, "market_price": P, "demand": 1.0,
        "supply": TOTAL, "volume24h": TOTAL}
fill, demand = _project_fill(coin, "buy", QTY * P)
# объём >> суточного объёма → сдвиг упирается в IMPACT_CAP=0.12
expected_new = P * 1.12
assert abs(demand - 1.12) < 1e-6, demand
assert abs(fill - (P + expected_new) / 2) < 1e-4, (fill, expected_new)

import asyncio
import crypto


class _Assets:
    async def find_one(self, query):
        return {"_id": "coin", "symbol": "TVX", "price": 100.0,
                "market_price": 100.0, "demand": 1.0, "volume24h": 1_000_000.0}

    async def update_one(self, query, update):
        return None


class _Db:
    crypto_assets = _Assets()


async def _bot_trade_does_not_write_history():
    calls = []
    original = crypto.MarketDataService.record_snapshot
    crypto.MarketDataService.record_snapshot = staticmethod(
        lambda *args, **kwargs: calls.append((args, kwargs))
    )
    try:
        await crypto._apply_trade_impact(
            _Db(), "TVX", "buy", 1000.0, record_history=False,
        )
    finally:
        crypto.MarketDataService.record_snapshot = original
    assert not calls


asyncio.run(_bot_trade_does_not_write_history())
print("OK")