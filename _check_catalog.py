"""Проверка каталога после миграции."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'backend'))
os.environ.setdefault('JWT_SECRET', 'test')

from assets import MARKET_CATALOG, HIDDEN_CATALOG, CATALOG_BY_SLUG

m = MARKET_CATALOG
h = HIDDEN_CATALOG
all_in_buy = CATALOG_BY_SLUG

print('=== MARKET_CATALOG (MarketTab) ===')
print(f'  Total: {len(m)}')
print(f'  Houses (realestate): {sum(1 for c in m if c["type"]=="realestate")}')
print(f'  Businesses: {sum(1 for c in m if c["type"]=="business")}')
print(f'  Cars: {sum(1 for c in m if c["type"]=="car")}')
print()
print('=== HIDDEN_CATALOG (только для покупки) ===')
print(f'  Total: {len(h)}')
for c in h:
    print(f'    {c["slug"]} ({c["type"]})')
print()
print('=== CATALOG_BY_SLUG (всё, что можно купить) ===')
print(f'  Slugs: {len(all_in_buy)}')
print(f'  - admin-re-*: {sum(1 for s in all_in_buy if s.startswith("admin-re-"))}')
print(f'  - admin-biz-*: {sum(1 for s in all_in_buy if s.startswith("admin-biz-"))}')
print(f'  - itstudio_*: {sum(1 for s in all_in_buy if s.startswith("itstudio_"))}')
print(f'  - media_holding: {sum(1 for s in all_in_buy if s=="media_holding")}')
print(f'  - cars: {sum(1 for s in all_in_buy if s in {"citycar","sedan","sport","super"})}')
print(f'  - OLD slug (should be 0): {sum(1 for s in all_in_buy if s in {"studio","flat2","townhouse","villa","penthouse","castle","shawarma","coffee","carwash","factory"})}')
print()
out = []
for c in m:
    out.append({'slug': c['slug'], 'type': c['type'], 'name': c['name'], 'price': c['price']})
out.sort(key=lambda x: x['price'])
print('=== Симуляция /api/assets/market (первые 5 и последние 5) ===')
for o in out[:5]:
    print(f"  {o['slug']:30s} {o['name']:25s} ${o['price']:>12,.0f}")
print('  ...')
for o in out[-5:]:
    print(f"  {o['slug']:30s} {o['name']:25s} ${o['price']:>12,.0f}")
print()
print(f'  Всего в ответе: {len(out)}')
