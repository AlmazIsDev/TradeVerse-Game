"""Чистая логика банка: лимит кредита, валидация займов и ставок.

Запуск: python backend/test_bank_credit.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from pydantic import ValidationError

import bank_credit
from bank_p2p import OfferCreate, MAX_P2P_AMOUNT

assert bank_credit.LOAN_MAX_AMOUNT == 1_000_000_000.0
assert bank_credit.LOAN_MAX_CAPITAL_MULT == 5.0

capital = 100_000.0
limit = min(bank_credit.LOAN_MAX_AMOUNT, capital * bank_credit.LOAN_MAX_CAPITAL_MULT)
assert limit == 500_000.0, limit

rich = 500_000_000.0
assert min(bank_credit.LOAN_MAX_AMOUNT, rich * bank_credit.LOAN_MAX_CAPITAL_MULT) == 1_000_000_000.0

ok = OfferCreate(side="lend", amount=1000, term_days=14, daily_rate=0.01)
assert ok.amount == 1000.0 and ok.term_days == 14
assert OfferCreate(side="lend", amount=1000, term_days=7, daily_rate=0.01).term_days == 7
assert OfferCreate(side="lend", amount=1000, term_days=21, daily_rate=0.01).term_days == 21


def rejects(**kwargs):
    try:
        OfferCreate(**{"side": "lend", "amount": 1000, "term_days": 30, "daily_rate": 0.01, **kwargs})
    except ValidationError:
        return True
    return False


assert rejects(side="steal")
assert rejects(amount=0)
assert rejects(amount=MAX_P2P_AMOUNT + 1)
assert rejects(term_days=6)
assert rejects(term_days=22)
assert rejects(daily_rate=-0.01)
assert rejects(daily_rate=0.51)

print("bank credit logic OK")
