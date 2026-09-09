"""Генерирует Python-данные каталога (realestate + business) для backend/assets.py.

Согласовано с frontend/src/utils/adminCatalog.js:
  * Цены realestate: плавная лестница по rarity + бонус за rooms.
  * Доход/час realestate: baseIncome[rarity] * (1 + max(0, rooms-1) * 0.018).
  * Цены business: лестница по category (retail/service/office/tech).
  * Сотрудники business: 2 + (id % 5) * 2.
"""
from textwrap import dedent

# 81 дом (имя, rarity, rooms, basement). Источник: shopCatalog.REAL_ESTATE_PRODUCTS.
HOUSES = [
    # common (20)
    (1, 'Sunny Cottage',     'common', 1, 1),  (2, 'Green Nest',         'common', 1, 1),
    (3, 'Little Oak',        'common', 1, 1),  (4, 'Rose House',         'common', 1, 2),
    (5, 'Maple Home',        'common', 2, 2),  (6, 'Silver Cottage',     'common', 2, 2),
    (7, 'Forest View',       'common', 2, 2),  (8, 'Pine Residence',     'common', 2, 3),
    (9, 'Golden Nest',       'common', 2, 3),  (10, 'Blue Horizon',      'common', 2, 3),
    (11, 'Stone Cottage',    'common', 2, 3),  (12, 'Autumn House',      'common', 2, 4),
    (13, 'Meadow Home',      'common', 3, 4),  (14, 'Oak Residence',     'common', 3, 4),
    (15, 'Cherry Cottage',   'common', 3, 4),  (16, 'Birch House',       'common', 3, 4),
    (17, 'Morning Villa',    'common', 3, 5),  (18, 'Hill Cottage',      'common', 3, 5),
    (19, 'River House',      'common', 3, 5),  (20, 'Sunset Home',       'common', 3, 5),
    # uncommon (20)
    (21, 'Crystal Garden',   'uncommon', 4, 6),  (22, 'Lake Breeze',     'uncommon', 4, 6),
    (23, 'Amber Villa',      'uncommon', 4, 6),  (24, 'Willow Manor',    'uncommon', 4, 6),
    (25, 'Mountain Rest',    'uncommon', 4, 7),  (26, 'Emerald Home',    'uncommon', 4, 7),
    (27, 'Harmony House',    'uncommon', 4, 7),  (28, 'Royal Cottage',   'uncommon', 5, 7),
    (29, 'Garden Estate',    'uncommon', 5, 8),  (30, 'Windy Hill',      'uncommon', 5, 8),
    (31, 'Golden Villa',     'uncommon', 5, 8),  (32, 'Ocean View',      'uncommon', 5, 8),
    (33, 'Snow Peak',        'uncommon', 5, 9),  (34, 'Silver Lake',     'uncommon', 5, 9),
    (35, 'Crystal Peak',     'uncommon', 5, 9),  (36, 'Rose Manor',      'uncommon', 5, 10),
    (37, 'Royal Garden',     'uncommon', 6, 10), (38, 'Moonlight Villa', 'uncommon', 6, 10),
    (39, 'Green Palace',     'uncommon', 6, 10), (40, 'Diamond Cottage', 'uncommon', 6, 10),
    # rare (17)
    (41, 'Imperial Home',    'rare', 6, 11),   (42, 'Ruby Manor',      'rare', 6, 11),
    (43, 'Forest Palace',    'rare', 6, 11),   (44, 'Sunrise Estate',  'rare', 6, 12),
    (45, 'North Residence',  'rare', 7, 12),   (46, 'Sky House',       'rare', 7, 12),
    (47, 'Aurora Villa',     'rare', 7, 13),   (48, 'Prestige Manor',  'rare', 7, 13),
    (49, "King's Home",      'rare', 7, 13),   (50, 'Elite Residence', 'rare', 7, 14),
    (51, 'Majestic Villa',   'rare', 8, 14),   (52, 'Royal Heights',   'rare', 8, 14),
    (53, 'Silver Crown',     'rare', 8, 15),   (54, 'Golden Ridge',    'rare', 8, 15),
    (55, 'Crimson Estate',   'rare', 8, 15),   (56, 'Azure Palace',    'rare', 8, 16),
    (57, 'Ivory Manor',      'rare', 8, 16),
    # epic (13)
    (58, 'Stormwatch Villa', 'epic', 9, 16),   (59, 'Dragonspire House', 'epic', 9, 17),
    (60, 'Obsidian Hall',    'epic', 9, 17),   (61, 'Titan Crest',     'epic', 9, 18),
    (62, 'Eclipse Estate',   'epic', 9, 18),   (63, 'Starforge Manor', 'epic', 9, 18),
    (64, 'Celestial Home',   'epic', 10, 19),  (65, 'Nightfall Villa', 'epic', 10, 19),
    (66, 'Thunder Peak',     'epic', 10, 20),  (67, 'Phoenix Residence','epic', 10, 20),
    (68, 'Ironwind Estate',  'epic', 10, 20),  (69, 'Lunar Fortress',  'epic', 10, 21),
    (70, 'Solar Mansion',    'epic', 10, 21),
    # legendary (11)
    (71, 'Astral Palace',    'legendary', 11, 21),  (72, 'Void Castle',    'legendary', 11, 22),
    (73, 'Infinity House',   'legendary', 11, 22),  (74, 'Nebula Citadel', 'legendary', 11, 22),
    (75, 'Quantum Villa',    'legendary', 12, 23),  (76, 'Godfall Residence','legendary', 12, 23),
    (77, 'Eternal Palace',   'legendary', 12, 24),  (78, 'Supreme Nexus',  'legendary', 12, 24),
    (79, 'Hyperion Tower Home','legendary', 12, 24), (80, 'Omega Estate',   'legendary', 12, 24),
    (81, 'Final Crown House','legendary', 12, 24),
]

# 12 бизнесов (id, name, category).
BUSINESSES = [
    (1, 'Pixel Store',     'retail'),
    (2, 'GPU Market',      'tech'),
    (3, 'CoreTech Shop',   'tech'),
    (4, 'Neon Hardware',   'tech'),
    (5, 'Quantum GPUs',    'tech'),
    (6, 'Street Kiosk',    'retail'),
    (7, 'Mini Market',     'retail'),
    (8, 'Urban Shop',      'retail'),
    (9, 'Fashion Store',   'retail'),
    (10, 'Tech Repair',    'service'),
    (11, 'Overclock Lab',  'service'),
    (12, 'Crypto Office',  'office'),
]

RARITY_PRICE_BASE = {'common': 5000, 'uncommon': 45000, 'rare': 160000, 'epic': 480000, 'legendary': 1500000}
RARITY_RANK = {'common': 0, 'uncommon': 1, 'rare': 2, 'epic': 3, 'legendary': 4}
RARITY_INNER_STEP = 0.045
ROOMS_BONUS_PER = 0.01
baseIncome = {'common': 25, 'uncommon': 110, 'rare': 420, 'epic': 1300, 'legendary': 4200}

CATEGORY_PRICE_BASE = {'retail': 6000, 'service': 18000, 'office': 28000, 'tech': 50000}
CATEGORY_RANK = {'retail': 0, 'service': 1, 'office': 2, 'tech': 3}
BIZ_INNER_STEP = 0.10


def _house_income(rarity, rooms):
    base = baseIncome.get(rarity, 25)
    return round(base * (1 + max(0, (rooms or 1) - 1) * 0.018))


def gen_houses():
    sorted_h = sorted(HOUSES, key=lambda x: (RARITY_RANK[x[2]], x[0]))
    pos = {}
    for pid, _, rarity, _, _ in sorted_h:
        pos[(rarity, pid)] = len([1 for p in sorted_h if p[2] == rarity and p[0] <= pid])
    out = []
    for pid, name, rarity, rooms, basement in sorted_h:
        i = pos[(rarity, pid)] - 1
        size = sum(1 for p in sorted_h if p[2] == rarity)
        base = RARITY_PRICE_BASE[rarity]
        inner = 1 + RARITY_INNER_STEP * i
        rooms_bonus = 1 + max(0, rooms - 1) * ROOMS_BONUS_PER
        price = round(base * inner * rooms_bonus)
        income = _house_income(rarity, rooms)
        upkeep = max(1, round(income * 0.18))
        out.append((f'admin-re-{pid}', name, rarity, rooms, basement, price, income, upkeep))
    return out


def gen_businesses():
    sorted_b = sorted(BUSINESSES, key=lambda x: (CATEGORY_RANK[x[2]], x[0]))
    pos = {}
    for pid, _, cat in sorted_b:
        pos[(cat, pid)] = len([1 for p in sorted_b if p[2] == cat and p[0] <= pid])
    out = []
    for pid, name, cat in sorted_b:
        i = pos[(cat, pid)] - 1
        size = sum(1 for p in sorted_b if p[2] == cat)
        base = CATEGORY_PRICE_BASE[cat]
        inner = 1 + BIZ_INNER_STEP * i
        price = round(base * inner)
        employees = 2 + (pid % 5) * 2
        # income/upkeep пропорционально цене, чтобы разные тематики давали
        # разный часовой доход. tech — больше, retail — меньше.
        income_per_hour = {
            'retail': 60, 'service': 150, 'office': 250, 'tech': 400,
        }[cat]
        # Масштабируем по позиции (i=0..size-1) и базе: последний в группе
        # приносит на ~20% больше.
        income = round(income_per_hour * (1 + 0.10 * i))
        upkeep = max(1, round(income * 0.32))
        out.append((f'admin-biz-{pid}', name, cat, price, employees, income, upkeep))
    return out


def main():
    print("HOUSES:")
    for h in gen_houses():
        print(f'  {{"slug": "{h[0]}", "type": TYPE_REALESTATE, "name": "{h[1]}", '
              f'"rarity": "{h[2]}", "price": {h[5]}, "income_per_hour": {h[6]}, '
              f'"upkeep_per_hour": {h[7]}, "rooms": {h[3]}, "basement": {h[4]}, '
              f'"meta": {{"tax": {max(1, round(h[6] * 0.2))}}}}},')
    print()
    print("BUSINESSES:")
    for b in gen_businesses():
        print(f'  {{"slug": "{b[0]}", "type": TYPE_BUSINESS, "name": "{b[1]}", '
              f'"category": "{b[2]}", "rarity": "common", "price": {b[3]}, '
              f'"income_per_hour": {b[5]}, "upkeep_per_hour": {b[6]}, "employees": {b[4]}}},')


if __name__ == "__main__":
    main()
