"""Справочник игровых ресурсов/предметов (RESOURCES).

Единое место, где описаны все базовые «сырьевые» предметы игры — еда,
металлы, руды, древесина и др. Это НЕ магазин и НЕ инвентарь: предметы
пока никуда не покупаются и не покупаются в shop.py, и не лежат в
user_hardware. Словарь нужен как общий источник правды для будущей логики:

  * источники (source) — шахты, поля, лесопилки будут выдавать конкретные
    предметы из этого списка, а не абстрактные «metal/food/wood»;
  * заводы (factory) — будут потреблять предметы как input и выпускать
    продукцию (см. ITSTUDIO_CONFIG в game_config.py как шаблон рецептов);
  * центральный рынок и склады — смогут ссылаться на эти предметы по id;
  * экономика (econ.py) — сможет брать base_price для расчёта пассивного
    дохода источников без дублирования цифр.

Структура записи:
    {
        "id":           slug, уникальный (snake_case, без кириллицы),
        "name":         человекочитаемое имя для UI,
        "description":  краткое описание для тултипов/карточек,
        "category":     одна из RESOURCE_CATEGORIES,
        "base_price":   базовая цена за 1 ед. в игре (см. DEFAULT_PRICES),
        "unit":         единица измерения для текста (кг, шт., блок, ...),
    }

Цена за единицу согласована по порядкам с инфраструктурными ценами из
econ.py (infra_metal_price=60, infra_food_price=15, infra_wood_price=40):
    камень/картофель  ~ 5–10   — сырьё, дешёвая еда
    медь/морковь       ~ 12–20  — простые ресурсы
    дерево/серебро     ~ 40–60  — обработанный/ценный средний уровень
    золото/бронза      ~ 80–120 — уже «индустриальные»
    металл/алмаз       ~ 200+   — редкие/высокотехнологичные

Эта лестница не обязательна, но помогает держать баланс, когда источники
начнут реально выдавать деньги. Меняем цену — правим здесь в одном месте.
"""
from __future__ import annotations

# ── Категории ────────────────────────────────────────────────────────────────
# Каждая запись несёт свою категорию; она нужна для фильтров в UI и для
# будущей группировки «что производит источник», «что ест завод».
CAT_AGRICULTURE = "agriculture"      # растения, урожай
CAT_MINERAL     = "mineral"          # камни, необработанные руды
CAT_METAL       = "metal"            # металл и сплавы
CAT_GEM         = "gem"              # самоцветы/редкие кристаллы
CAT_WOOD        = "wood"             # древесина, пиломатериалы

RESOURCE_CATEGORIES: tuple[str, ...] = (
    CAT_AGRICULTURE,
    CAT_MINERAL,
    CAT_METAL,
    CAT_GEM,
    CAT_WOOD,
)

# ── Справочник предметов ─────────────────────────────────────────────────────
# Порядок в списке — это порядок отображения в UI (еда → руды → металлы →
# самоцветы → древесина). Меняем порядок при добавлении новых, не ломая
# существующие id.
RESOURCES: list[dict] = [
    # ── Сельское хозяйство (поле) ───────────────────────────────────────────
    {
        "id": "wheat",
        "name": "Пшеница",
        "description": "Основная зерновая культура. Используется для выпечки хлеба и корма.",
        "category": CAT_AGRICULTURE,
        "base_price": 8.0,
        "unit": "кг",
    },
    {
        "id": "carrot",
        "name": "Морковь",
        "description": "Корнеплод. Быстрый урожай, часто идёт на корм и консервацию.",
        "category": CAT_AGRICULTURE,
        "base_price": 6.0,
        "unit": "кг",
    },
    {
        "id": "potato",
        "name": "Картофель",
        "description": "Универсальный корнеплод. Основа рациона колонии и дешёвый корм.",
        "category": CAT_AGRICULTURE,
        "base_price": 5.0,
        "unit": "кг",
    },
    {
        "id": "sunflower",
        "name": "Подсолнух",
        "description": "Масличная культура. Семена идут на масло и масложорку для двигателей.",
        "category": CAT_AGRICULTURE,
        "base_price": 14.0,
        "unit": "кг",
    },
    {
        "id": "bread",
        "name": "Хлеб",
        "description": "Выпекается в пекарне из пшеницы. Корм для работников источников — повышает их эффективность.",
        "category": CAT_AGRICULTURE,
        "base_price": 30.0,
        "unit": "кг",
    },

    # ── Минералы (шахта, сырьё) ────────────────────────────────────────────
    {
        "id": "stone",
        "name": "Камень",
        "description": "Обычный строительный камень. Базовый материал для фундаментов и дорог.",
        "category": CAT_MINERAL,
        "base_price": 5.0,
        "unit": "блок",
    },

    # ── Металлы (шахта + металлургия) ───────────────────────────────────────
    {
        "id": "copper",
        "name": "Медь",
        "description": "Мягкая руда. Применяется в проводке, трубках и первичных сплавах.",
        "category": CAT_METAL,
        "base_price": 12.0,
        "unit": "кг",
    },
    {
        "id": "silver",
        "name": "Серебро",
        "description": "Ценный металл с отличной проводимостью. Денежный эквивалент и электротехника.",
        "category": CAT_METAL,
        "base_price": 45.0,
        "unit": "кг",
    },
    {
        "id": "bronze",
        "name": "Бронза",
        "description": "Сплав меди с оловом. Крепче медь, идёт в корпуса и детали машин.",
        "category": CAT_METAL,
        "base_price": 85.0,
        "unit": "кг",
    },
    {
        "id": "metal",
        "name": "Металл",
        "description": "Универсальный металлорежущий сплав. Ключевое сырьё для заводов и станков.",
        "category": CAT_METAL,
        "base_price": 60.0,
        "unit": "кг",
    },
    {
        "id": "gold",
        "name": "Золото",
        "description": "Редкий благородный металл. Запас, ювелирное дело и высокопрочные контакты.",
        "category": CAT_METAL,
        "base_price": 110.0,
        "unit": "кг",
    },

    # ── Самоцветы (глубокая шахта) ──────────────────────────────────────────
    {
        "id": "diamond",
        "name": "Алмаз",
        "description": "Хрупкий и невероятно твёрдый кристалл. Резец, ювелирная промышленность, теплоотвод.",
        "category": CAT_GEM,
        "base_price": 220.0,
        "unit": "шт.",
    },

    # ── Древесина (лесопилка) ───────────────────────────────────────────────
    {
        "id": "wood",
        "name": "Древесина",
        "description": "Сырой лесной материал. Брёвна и необрезные доски, не готовы к сборке.",
        "category": CAT_WOOD,
        "base_price": 40.0,
        "unit": "блок",
    },
    {
        "id": "processed_wood",
        "name": "Обработанная древесина",
        "description": "Колёсцованные, высушенные и обрезанные доски. Идёт в мебель и корпуса зданий.",
        "category": CAT_WOOD,
        "base_price": 75.0,
        "unit": "блок",
    },
]

# Быстрый доступ по id — используется везде, где нужен предмет по slug.
RESOURCES_BY_ID: dict[str, dict] = {r["id"]: r for r in RESOURCES}

# Группировка по категориям — удобно для иконки в админке и для меню фабрик.
RESOURCES_BY_CATEGORY: dict[str, list[dict]] = {
    cat: [r for r in RESOURCES if r["category"] == cat]
    for cat in RESOURCE_CATEGORIES
}


# ── Хелперы ──────────────────────────────────────────────────────────────────


def get_resource(resource_id: str) -> dict | None:
    """Возвращает запись справочника по id или None, если такого предмета нет."""
    return RESOURCES_BY_ID.get(str(resource_id or ""))


def price_of(resource_id: str) -> float:
    """Базовая цена за единицу. Возвращает 0.0 для неизвестных id — вызывающий
    код сам решает, что делать с отсутствующим предметом (обычно пропускает)."""
    rec = RESOURCES_BY_ID.get(str(resource_id or ""))
    return float(rec["base_price"]) if rec else 0.0


def all_ids() -> list[str]:
    """Список всех id справочника в каноническом порядке (подряд записей)."""
    return [r["id"] for r in RESOURCES]


# ── Self-check ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Уникальность id и категорий.
    ids = [r["id"] for r in RESOURCES]
    assert len(ids) == len(set(ids)), "дубликаты id в RESOURCES"
    assert set(ids) == set(RESOURCES_BY_ID.keys()), "RESOURCES_BY_ID рассинхронизирован с RESOURCES"

    # Каждая запись валидна.
    for r in RESOURCES:
        assert set(r) == {"id", "name", "description", "category", "base_price", "unit"}, r["id"]
        assert r["id"] and r["id"].islower() and "_" not in r["id"][:1], r["id"]
        assert r["id"] == r["id"].strip(), r["id"]
        assert r["name"] and r["description"] and r["unit"], r["id"]
        assert r["category"] in RESOURCE_CATEGORIES, r["id"]
        assert isinstance(r["base_price"], (int, float)) and r["base_price"] > 0, r["id"]

    # Все запрошенные предметы на месте (включая хлеб пекарни).
    expected = {
        "wheat", "carrot", "potato", "sunflower", "bread",
        "stone",
        "copper", "silver", "bronze", "metal", "gold",
        "diamond",
        "wood", "processed_wood",
    }
    assert set(ids) == expected, f"ожидалось {expected}, получено {set(ids)}"

    # Group-индекс согласован.
    for cat, rows in RESOURCES_BY_CATEGORY.items():
        for r in rows:
            assert r["category"] == cat

    # Хелперы работают как ожидаем.
    assert get_resource("wheat") is RESOURCES_BY_ID["wheat"]
    assert get_resource("nope") is None
    assert price_of("metal") == 60.0
    assert price_of("unknown") == 0.0
    assert len(all_ids()) == 14

    print("resources self-check OK")
