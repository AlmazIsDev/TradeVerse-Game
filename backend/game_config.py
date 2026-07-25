"""Единая конфигурация игрового баланса аренды и IT-студии.

Все числовые параметры этих двух систем живут здесь — чтобы поменять
баланс, не нужно искать константы по разным модулям.
"""

# ── Аренда недвижимости/авто (см. assets.py) ─────────────────────────────────
RENTAL_CONFIG = {
    "rate": 0.052,                # базовый коэффициент цены аренды
    "diminish": 0.6,               # степень убывающей отдачи за час (<1 — длинные сроки дешевле за день)
    "min_price": 1500.0,           # нижний порог стоимости аренды за срок
    "durations_hours": [24, 48, 72, 144, 288, 336, 384, 720],  # 1,2,3,6,12,14,16 дней, 1 месяц
    "max_hours": 720,
    "min_wait_hours": 1,           # мин. время появления арендатора
    "max_wait_hours": 48,          # макс. время появления арендатора
}

# ── IT-студия: тиры, атака/защита, материалы, опыт (см. cityroof.py) ─────────
ITSTUDIO_CONFIG = {
    # slug каталога (assets.py) = "itstudio_" + ключ тира ниже
    "tiers": {
        "basic": {
            "order": 1, "material": "basic_components",
            "materialName": "Простые комплектующие", "materialUnitCost": 150,
            "successBase": 0.55, "defenseBase": 0.50,
        },
        "medium": {
            "order": 2, "material": "server_hardware",
            "materialName": "Серверное оборудование", "materialUnitCost": 500,
            "successBase": 0.62, "defenseBase": 0.56,
        },
        "advanced": {
            "order": 3, "material": "specialized_chips",
            "materialName": "Специализированные микросхемы", "materialUnitCost": 1500,
            "successBase": 0.70, "defenseBase": 0.64,
        },
        "premium": {
            "order": 4, "material": "rare_components",
            "materialName": "Редкие компоненты", "materialUnitCost": 5000,
            "successBase": 0.99, "defenseBase": 0.95,
            # Премиум-студия — «имба»: операция выполняется за 5–45 минут (а не часы),
            # атака ВСЕГДА успешна и полностью сносит защиту цели (взлом «под ноль»),
            # защита ставит усиленный длительный щит. Переопределяет общие значения.
            "min_minutes": 5.0, "max_minutes": 45.0,
            "full_break": True,                 # снос всей защиты за одну операцию
            "success_cap": 0.99,                # пробивает даже щит цели
            "shield_bonus_on_success": 0.40,    # усиленный щит
            "shield_duration_hours": 48.0,      # держится дольше
        },
    },
    # Стоимость операции ($): база + доплата за текущий уровень защиты цели
    "cost_base": 8000.0,
    "cost_per_protection": 4000.0,
    # Материалы (своего тира студии), расходуемые за одну операцию
    "materials_per_attack": 3,
    "materials_per_defense": 2,
    # Время выполнения операции (реальные часы)
    "min_hours": 1.0,
    "max_hours": 3.0,
    # Взвешенный случайный выбор снижения защиты при успешной атаке
    "reduction_weights": [(1, 38), (2, 30), (3, 18), (4, 9), (5, 5)],
    # Щит защиты: штраф атакующему, бонус защитнику при успехе, срок действия
    "shield_penalty": 0.25,
    "shield_bonus_on_success": 0.20,
    "shield_duration_hours": 24.0,
    # Опыт и уровни студии
    "xp_per_success_attack": 10,
    "xp_per_success_defense": 8,
    "xp_per_fail": 2,
    "xp_per_level": 120,           # сколько XP нужно на каждый следующий уровень (линейно)
    "max_level": 10,
    "level_success_bonus": 0.015,  # +1.5% к шансу успеха за уровень
    "level_success_cap": 0.15,     # максимум +15% от уровня
}
