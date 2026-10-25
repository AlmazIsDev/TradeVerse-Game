from market_data import _build_walk_docs


docs = _build_walk_docs("crypto", "TEST", 100.0, 0.06)
prices = [doc["price"] for doc in docs]
assert len(docs) == 509
assert min(prices) >= 15.0
assert max(prices) <= 600.0
print("volatility history OK")
