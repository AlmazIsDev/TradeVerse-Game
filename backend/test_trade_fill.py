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

print("OK")