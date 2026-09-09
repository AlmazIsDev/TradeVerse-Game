import asyncio
import sys
sys.path.insert(0, 'backend')
import logging
logging.disable(logging.CRITICAL)
from unittest.mock import AsyncMock
import assets

# Симулируем /api/assets/market?type=realestate
async def test_market_endpoint():
    # Это то, что делает _ensure_asset_market и _drift_asset_market
    # Заменим db на мок
    db = AsyncMock()

    # Имитируем find({}) — пустой asset_market
    class FakeCursor:
        def __init__(self, items): self.items = items
        def __aiter__(self): return self
        async def __anext__(self):
            if not self.items: raise StopAsyncIteration
            return self.items.pop(0)
        async def to_list(self, length=None): return self.items

    db.asset_market.find.return_value = FakeCursor([])
    db.asset_market_meta.find_one.return_value = None
    db.user_assets.find.return_value = FakeCursor([])
    db.transactions.count_documents.return_value = 0
    db.users.find.return_value = FakeCursor([])
    db.asset_market_meta.update_one.return_value = None

    # _ensure_asset_market вставит записи для всех slug'ов
    async def fake_update_one(filter, update, **kwargs):
        return None
    db.asset_market.update_one = fake_update_one

    # Запустим endpoint
    from fastapi import Request
    from auth import get_current_user

    # Просто запустим части логики:
    await assets._ensure_asset_market(db)
    print('ensure ok')

    await assets._drift_asset_market(db)
    print('drift ok')

    mults = await assets._mult_map(db)
    print('mults count:', len(mults))

    # Теперь сэмулируем ответ
    type_filter = 'realestate'
    items = assets.CATALOG
    items = [c for c in items if c['type'] == type_filter]
    out = []
    for c in items:
        mult = mults.get(c['slug'], 1.0)
        price = round(c['price'] * mult, 2)
        out.append({
            'slug': c['slug'], 'type': c['type'], 'name': c['name'],
            'category': c.get('category'), 'rarity': c.get('rarity'),
            'rooms': c.get('rooms'), 'employees': c.get('employees', 0),
            'price': price, 'basePrice': c['price'],
            'incomePerHour': c.get('income_per_hour', 0),
            'upkeepPerHour': c.get('upkeep_per_hour', 0),
        })
    print('Realestate out:', len(out))
    print('First admin-re-1:', next(x for x in out if x['slug'] == 'admin-re-1'))
    print('Last admin-re-81:', next(x for x in out if x['slug'] == 'admin-re-81'))

asyncio.run(test_market_endpoint())
