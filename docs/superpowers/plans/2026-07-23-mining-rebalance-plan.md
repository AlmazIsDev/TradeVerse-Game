# Mining Rebalance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the price-only coin-profitability formula with a farm-hashrate-aware "share of synthetic difficulty" model, give every previously-decorative hardware component (CPU/RAM/SSD/network/UPS) a real multiplier on mining output, and soft-reset existing farms so players re-assemble under the new rules without losing hardware or historical stats.

**Architecture:** All new economy math lives in `backend/mining.py` as small pure functions (no DB access) so they're unit-testable via the file's existing `if __name__ == "__main__":` self-check convention. `_compute()` (already pure) is rewritten to call them. Endpoints and `tick_all()` (which do touch the DB) are updated to pass farm-hardware profiles into the pure functions instead of duplicating logic. A one-time migration function runs from FastAPI's `lifespan()`, gated by the existing `app_config` key/value pattern already used by `shop.py`.

**Tech Stack:** FastAPI + Motor (async MongoDB), Pydantic, React (frontend), i18next.

## Global Constraints

- No pytest suite exists in `backend/` — the established test convention is the `if __name__ == "__main__":` self-check block at the bottom of each module, run via `python <module>.py`. Follow this convention; do not introduce pytest.
- Only ~5 concurrent players exist — live player hashrate must stay a minor ("flavor") signal (`LIVE_WEIGHT = 0.05`), never the primary driver of difficulty.
- Approved design spec (source of truth for formulas/constants): `docs/superpowers/specs/2026-07-23-mining-rebalance-design.md`.
- Preserve all existing behavior not explicitly changed by this plan (repair/manager/overclock/temperature/wear logic, batch-install endpoint added in the prior session).
- `backend/mining.py` currently has **uncommitted** working-tree changes (the `install-batch` endpoint from a prior task). Task 1's first step is committing that work separately so it doesn't get tangled with this rewrite's diff.

---

### Task 0: Commit the pending batch-install feature separately

**Files:**
- No new files — this only commits already-written, uncommitted changes.

**Interfaces:** None — this task produces no new symbols.

- [ ] **Step 1: Commit the existing uncommitted batch-install changes**

```bash
git add backend/mining.py frontend/src/services/api.js frontend/src/components/MiningTab.jsx
git commit -m "feat(mining): add install-batch endpoint for bulk component installs"
```

- [ ] **Step 2: Verify a clean baseline before starting the rebalance**

Run: `git status`
Expected: `nothing to commit, working tree clean` (or only files unrelated to mining).

---

### Task 1: Core economy math — synthetic difficulty, share, component efficiency, coin choice

**Files:**
- Modify: `backend/mining.py`

**Interfaces:**
- Produces: `_clamp_eff(ratio: float) -> float`, `_gpu_efficiency(cores: float, gpu_count: int) -> float`, `_ram_efficiency(ram_gb: float, gpu_count: int, price: float) -> float`, `_ssd_efficiency(ssd_gb: float, gpu_count: int) -> float`, `_net_efficiency(net_speed: float, gpu_count: int) -> float`, `_farm_hashrate(farm: dict) -> float`, `_farm_hw_profile(farm: dict) -> dict` (keys: `hashrate`, `gpu_count`, `cores`, `ram_gb`, `ssd_gb`, `net_speed`, `ups_backup`), `_coin_difficulty(price: float, live_hashrate_on_coin: float = 0.0) -> float`, `_farm_share(hashrate: float, difficulty: float) -> float`, `_coin_revenue_per_h(coin: Optional[dict], profile: dict, live_hashrate_on_coin: float = 0.0) -> float`, rewritten `choose_best_coin(market: dict, profile: Optional[dict] = None, live_hashrate_by_coin: Optional[dict] = None) -> Optional[str]`.
- Consumes: nothing new — only stdlib `random` (added import) and existing module-level constants.
- Removed: `_coin_profitability()` and `HASH_YIELD` constant (no longer used anywhere after this task).

- [ ] **Step 1: Add the self-check assertions first (they will fail — the functions don't exist yet)**

At the very end of `backend/mining.py`, inside the existing `if __name__ == "__main__":` block, immediately before the final `print("mining self-check OK")` line, insert:

```python
    # ── Rebalance: выбор монеты зависит от фермы, а не только от цены ──
    _market = {
        "CHEAP": {"symbol": "CHEAP", "price": 0.85, "change24h": 0.0},
        "MID": {"symbol": "MID", "price": 12.4, "change24h": 0.0},
        "EXPENSIVE": {"symbol": "EXPENSIVE", "price": 340.0, "change24h": 0.0},
    }
    _weak = {"hashrate": 180.0, "gpu_count": 1, "cores": 4, "ram_gb": 8, "ssd_gb": 256, "net_speed": 1000, "ups_backup": 0}
    _strong = {"hashrate": 1_045_000.0, "gpu_count": 19, "cores": 32, "ram_gb": 128, "ssd_gb": 4096, "net_speed": 40000, "ups_backup": 0}
    _weak_best = choose_best_coin(_market, _weak)
    assert _weak_best != "EXPENSIVE", "слабая ферма не должна выбирать самую дорогую монету"
    assert _weak_best == "CHEAP", f"ожидали CHEAP, получили {_weak_best}"
    _strong_best = choose_best_coin(_market, _strong)
    assert _strong_best == "EXPENSIVE", f"сильная ферма должна тянуться к дорогим монетам, получили {_strong_best}"
    # Без профиля (нет собранной фермы) — откат на сортировку по цене.
    assert choose_best_coin(_market, None) == "EXPENSIVE"

    # ── Эффективность компонентов: клэмп на границах [EFF_FLOOR, 1.0] ──
    assert _gpu_efficiency(8, 8) == 1.0                  # 8 ядер кормят 8 GPU — полная эффективность
    assert round(_gpu_efficiency(8, 19), 2) == 0.42       # тех же 8 ядер на 19 GPU — throttling
    assert _gpu_efficiency(1, 100) == EFF_FLOOR           # экстремальный недостаток ядер — пол, не ноль
    assert _ram_efficiency(32, 8, 0.85) > 0.99            # дешёвая монета — 32ГБ хватает почти полностью
    assert _ram_efficiency(32, 8, 340.0) == 0.5           # дорогая монета — тот же объём вдвое хуже
    assert _ram_efficiency(64, 8, 340.0) == 1.0           # апгрейд до 64ГБ полностью закрывает требование
    assert _ssd_efficiency(512, 8) == 1.0 and _ssd_efficiency(1, 8) == EFF_FLOOR
    assert _net_efficiency(10000, 19) == 1.0 and _net_efficiency(1, 100) == EFF_FLOOR

    # ── Синтетическая сложность растёт быстрее цены (DIFF_EXP > 1) ──
    assert _coin_difficulty(340.0) > _coin_difficulty(0.85) * 100   # дороже монета — непропорционально сложнее
    assert _farm_share(0.0, 100.0) == 0.0
    assert 0.0 < _farm_share(100.0, 100.0) < 1.0
```

- [ ] **Step 2: Run the self-check to confirm it fails**

Run: `cd backend && python mining.py`
Expected: `NameError: name 'choose_best_coin' is not defined` is NOT what happens (that function already exists) — instead expect a `NameError` or `AssertionError` referencing `_gpu_efficiency`/`_ram_efficiency`/`_coin_difficulty` (whichever the interpreter reaches first), confirming these new functions don't exist yet.

- [ ] **Step 3: Add `import random` and the new constants**

Replace:
```python
import math
from datetime import datetime, timezone
```
with:
```python
import math
import random
from datetime import datetime, timezone
```

Replace:
```python
HASH_YIELD = 0.001          # доход за единицу хешрейта × профитность монеты
ELEC_SCALE = 0.15           # масштаб счёта за электричество
```
with:
```python
ELEC_SCALE = 0.15           # масштаб счёта за электричество
```

Replace:
```python
MINING_MIN_ELAPSED_H = 300 / 3600.0   # тик добычи не чаще, чем раз в 5 минут
MAX_ACCRUAL_H = 6.0                    # cap накопления оффлайн
FEE = 0.01
```
with:
```python
MINING_MIN_ELAPSED_H = 300 / 3600.0   # тик добычи не чаще, чем раз в 5 минут
MAX_ACCRUAL_H = 6.0                    # cap накопления оффлайн
FEE = 0.01

# ── Экономика "доля от синтетической сложности сети" (см. design-спеку) ──
DIFF_EXP = 1.5              # сложность монеты растёт быстрее цены — самобалансировка выбора
DIFF_SCALE = 600.0          # откалибровано по каталогу: стартовая ферма (~500 хешрейта) конкурентна на монетах < $1
EMISSION = 14.0             # монето-USD-эквивалент/час при share=1.0; откалибровано под сегодняшний базовый доход
LIVE_WEIGHT = 0.05          # вклад живых игроков в сложность — второстепенный сигнал (~5 игроков), не механизм

# ── Эффективность компонентов (все клэмпятся в [EFF_FLOOR, 1.0]) ──
GPUS_PER_CORE = 1.0         # CPU: сколько GPU полноценно «кормит» одно ядро
RAM_PER_GPU = 4.0           # RAM: базовая потребность (ГБ) на один GPU
RAM_PRICE_REF = 340.0       # RAM: цена самой дорогой монеты каталога — якорь роста требований (memory-hard proxy)
SSD_PER_GPU = 50.0          # SSD: базовая потребность (ГБ) на один GPU (нода + DAG-кэш)
NET_PER_GPU = 100.0         # Network: базовая потребность (Мбит/с) на один GPU (пул/стейл-шары)
EFF_FLOOR = 0.15            # компоненты не гасят добычу до нуля — минимум 15% пропускной способности

# ── ИБП (см. tick_all: шанс просадки питания за тик) ──
BROWNOUT_CHANCE = 0.05      # шанс просадки питания за тик
UPS_WEAR_PENALTY = 5.0      # доп. износ (%) при незащищённой просадке
```

- [ ] **Step 4: Remove `_coin_profitability` and add the new pure functions in its place**

Replace:
```python
def _coin_profitability(coin: Optional[dict]) -> float:
    if not coin or coin.get("price", 0) <= 0:
        return 0.0
    price = float(coin["price"])
    momentum = 1 + max(-0.5, min(0.5, coin.get("change24h", 0.0) / 100.0))
    return math.sqrt(price) * momentum * (1 - FEE)
```
with:
```python
def _clamp_eff(ratio: float) -> float:
    return max(EFF_FLOOR, min(1.0, ratio))


def _gpu_efficiency(cores: float, gpu_count: int) -> float:
    """CPU координирует GPU (PCIe/драйверы) — нехватка ядер душит хешрейт."""
    if gpu_count <= 0:
        return 1.0
    return _clamp_eff(cores * GPUS_PER_CORE / gpu_count)


def _ram_efficiency(ram_gb: float, gpu_count: int, price: float) -> float:
    """DAG должен помещаться в память; чем дороже монета — тем «тяжелее»
    алгоритм (proxy на memory-hardness). Единственная coin-зависимая
    эффективность — поэтому встроена в _coin_revenue_per_h (см. ниже),
    а не только в _compute, иначе выбор монеты и её реальная выплата разойдутся."""
    if gpu_count <= 0:
        return 1.0
    price_factor = min(1.0, max(0.0, price) / RAM_PRICE_REF)
    needed = gpu_count * RAM_PER_GPU * (1 + price_factor)
    return _clamp_eff(ram_gb / needed) if needed > 0 else 1.0


def _ssd_efficiency(ssd_gb: float, gpu_count: int) -> float:
    """Хранилище ноды/DAG-кэша — мало места означает постоянную пересинхронизацию."""
    if gpu_count <= 0:
        return 1.0
    return _clamp_eff(ssd_gb / (SSD_PER_GPU * gpu_count))


def _net_efficiency(net_speed: float, gpu_count: int) -> float:
    """Пропускная способность до пула — мало значит устаревшие/отклонённые шары."""
    if gpu_count <= 0:
        return 1.0
    return _clamp_eff(net_speed / (NET_PER_GPU * gpu_count))


def _farm_hashrate(farm: dict) -> float:
    """Эффективный хешрейт с учётом разгона и износа (вынесено из _compute
    для переиспользования при выборе монеты — см. _farm_hw_profile)."""
    comp = farm.get("components", {})
    gpus = comp.get("gpus", [])
    overclock = farm.get("overclock", 1.0)
    condition = farm.get("condition", 100.0)
    cond_factor = 0.5 + 0.5 * (condition / 100.0)
    base_hash = sum(g.get("specs", {}).get("hashrate", 0) for g in gpus)
    return round(base_hash * overclock * cond_factor, 1)


def _farm_hw_profile(farm: dict) -> dict:
    """Сводка параметров фермы для выбора монеты и расчёта эффективности."""
    comp = farm.get("components", {})
    return {
        "hashrate": _farm_hashrate(farm),
        "gpu_count": len(comp.get("gpus", [])),
        "cores": comp.get("cpu", {}).get("specs", {}).get("cores", 0),
        "ram_gb": comp.get("ram", {}).get("specs", {}).get("gb", 0),
        "ssd_gb": comp.get("ssd", {}).get("specs", {}).get("gb", 0),
        "net_speed": comp.get("network", {}).get("specs", {}).get("speed", 0),
        "ups_backup": comp.get("ups", {}).get("specs", {}).get("backup", 0),
    }


def _coin_difficulty(price: float, live_hashrate_on_coin: float = 0.0) -> float:
    """Синтетическая сложность = функция ЦЕНЫ монеты (не реального пула игроков —
    их слишком мало, см. design-спеку), плюс небольшой вклад живых майнеров."""
    base = (max(0.0, price) ** DIFF_EXP) * DIFF_SCALE
    return base + live_hashrate_on_coin * LIVE_WEIGHT


def _farm_share(hashrate: float, difficulty: float) -> float:
    """Доля фермы в «сети» — насыщающаяся кривая, никогда не превышает 1."""
    if hashrate <= 0:
        return 0.0
    return hashrate / (difficulty + hashrate)


def _coin_revenue_per_h(coin: Optional[dict], profile: dict, live_hashrate_on_coin: float = 0.0) -> float:
    """Выручка/час монеты для данного профиля фермы. ram_eff встроен сюда
    (не только в _compute), чтобы choose_best_coin ранжировал монеты по
    ТОЙ ЖЕ формуле, что и реальная выплата — иначе ИИ мог бы выбрать монету,
    которая ранжируется выше, но платит хуже после ram_eff."""
    if not coin or coin.get("price", 0) <= 0:
        return 0.0
    hashrate = profile.get("hashrate", 0.0)
    if hashrate <= 0:
        return 0.0
    price = float(coin["price"])
    difficulty = _coin_difficulty(price, live_hashrate_on_coin)
    share = _farm_share(hashrate, difficulty)
    ram_eff = _ram_efficiency(profile.get("ram_gb", 0), profile.get("gpu_count", 0), price)
    return share * EMISSION * price * ram_eff
```

- [ ] **Step 5: Rewrite `choose_best_coin`**

Replace:
```python
def choose_best_coin(market: dict) -> Optional[str]:
    """ИИ-выбор самой прибыльной монеты: курс × момент − комиссия."""
    best, best_p = None, -1.0
    for sym, c in market.items():
        p = _coin_profitability(c)
        if p > best_p:
            best, best_p = sym, p
    return best
```
with:
```python
def choose_best_coin(market: dict, profile: Optional[dict] = None,
                      live_hashrate_by_coin: Optional[dict] = None) -> Optional[str]:
    """Выбор монеты, дающей максимум ожидаемой выручки ИМЕННО этой ферме
    (не глобальный рейтинг — см. design-спеку). Без профиля (нет собранной
    фермы, ничего не с чем ранжировать) — откат на сортировку по цене."""
    if not profile or profile.get("hashrate", 0) <= 0:
        best, best_price = None, -1.0
        for sym, c in market.items():
            price = float(c.get("price", 0))
            if price > best_price:
                best, best_price = sym, price
        return best
    live = live_hashrate_by_coin or {}
    best, best_rev = None, -1.0
    for sym, c in market.items():
        rev = _coin_revenue_per_h(c, profile, live.get(sym, 0.0))
        if rev > best_rev:
            best, best_rev = sym, rev
    return best
```

- [ ] **Step 6: Run the self-check to confirm it passes**

Run: `cd backend && python mining.py`
Expected: `mining self-check OK` printed, no `AssertionError`/`NameError`.

- [ ] **Step 7: Commit**

```bash
git add backend/mining.py
git commit -m "feat(mining): synthetic difficulty share model replaces flat coin profitability"
```

---

### Task 2: Wire component efficiency and the new revenue model into `_compute()`

**Files:**
- Modify: `backend/mining.py`

**Interfaces:**
- Consumes: everything produced in Task 1 (`_farm_hashrate`, `_farm_hw_profile`, `_gpu_efficiency`, `_ram_efficiency`, `_ssd_efficiency`, `_net_efficiency`, `_coin_revenue_per_h`).
- Produces: `_compute(farm, market, energy_cost, economy_mult=1.0, city=None, live_hashrate_on_coin=0.0) -> dict` — same return keys as before, PLUS `"upsProtected": bool` and `"efficiency": {"gpu": float, "ram": float, "ssd": float, "network": float}`.

- [ ] **Step 1: Add self-check assertions for `_compute` (will fail — new keys don't exist yet)**

In `backend/mining.py`, inside the `if __name__ == "__main__":` block, immediately before `print("mining self-check OK")`, add:

```python
    # ── _compute expone efficiency/upsProtected и использует новую формулу дохода ──
    _test_farm = {
        "components": {
            "motherboard": {"specs": {"gpuSlots": 8, "power": 60}},
            "cpu": {"specs": {"cores": 8, "power": 109}},
            "ram": {"specs": {"gb": 32, "power": 5}},
            "ssd": {"specs": {"gb": 512, "power": 6}},
            "cooling": {"specs": {"cooling": 1600, "power": 40}},
            "gpus": [{"specs": {"hashrate": 1887, "power": 214}}] * 8,
            "fans": [], "psus": [{"specs": {"power": 3000}}],
        },
        "overclock": 1.0, "condition": 100.0, "coin": "ORB",
        "manager": {"type": "player", "level": 0},
    }
    _test_market = {"ORB": {"symbol": "ORB", "price": 12.4, "change24h": 0.0}}
    _test_stats = _compute(_test_farm, _test_market, energy_cost=0.12, economy_mult=1.0)
    assert "efficiency" in _test_stats and set(_test_stats["efficiency"]) == {"gpu", "ram", "ssd", "network"}
    assert _test_stats["efficiency"]["gpu"] == 1.0        # 8 ядер / 8 GPU
    assert _test_stats["upsProtected"] is False            # нет установленного ИБП → backup=0
    assert _test_stats["revenuePerHour"] > 0
    assert _test_stats["gpuCount"] == 8
```

- [ ] **Step 2: Run the self-check to confirm it fails**

Run: `cd backend && python mining.py`
Expected: `KeyError: 'efficiency'` or `AssertionError` (the `_compute` return dict doesn't have these keys yet).

- [ ] **Step 3: Rewrite `_compute`**

Replace the entire existing function:
```python
def _compute(farm: dict, market: dict, energy_cost: float, economy_mult: float = 1.0,
             city: Optional[dict] = None) -> dict:
    # city — бонусы зданий «Крыши города»: yield (+% к добыче), energy (−% к счёту за свет).
    city = city or {}
    yield_bonus = float(city.get("yield", 0.0))
    energy_discount = min(0.5, float(city.get("energy", 0.0)))
    comp = farm.get("components", {})
    gpus = comp.get("gpus", [])
    fans = comp.get("fans", [])
    overclock = farm.get("overclock", 1.0)
    condition = farm.get("condition", 100.0)
    cond_factor = 0.5 + 0.5 * (condition / 100.0)

    base_hash = sum(g.get("specs", {}).get("hashrate", 0) for g in gpus)
    hashrate = round(base_hash * overclock * cond_factor, 1)
    gpu_power = sum(g.get("specs", {}).get("power", 0) for g in gpus) * overclock
    cpu_power = comp.get("cpu", {}).get("specs", {}).get("power", 0)
    mb_power = comp.get("motherboard", {}).get("specs", {}).get("power", 0)
    total_power = round(gpu_power + cpu_power + mb_power + BASE_POWER_W, 1)

    cooling_cap = comp.get("cooling", {}).get("specs", {}).get("cooling", 0) + sum(f.get("specs", {}).get("cooling", 0) for f in fans)
    manager = farm.get("manager") or {"type": "player", "level": 0}
    ai_level = manager.get("level", 0) if manager.get("type") == "ai" else 0
    cool_bonus = min(0.5, ai_level * 0.06)
    temperature = round(TEMP_AMBIENT + (total_power / max(1, cooling_cap)) * TEMP_FACTOR * (1 - cool_bonus), 1)

    coin_sym = farm.get("coin")
    coin = market.get(coin_sym) if coin_sym else None
    prof = _coin_profitability(coin)
    revenue_per_h = round(hashrate * HASH_YIELD * prof * economy_mult * (1 + yield_bonus), 2)

    electricity_per_h = round(total_power * energy_cost * ELEC_SCALE * (1 - energy_discount), 2)
    salary_per_h = round(MANAGER_SALARY_PER_H * ai_level, 2) if manager.get("type") == "ai" else 0.0

    overclock_excess = max(0.0, overclock - 1.0)
    temp_wear = max(0.0, (temperature - 60) / 100.0)
    wear_per_h = round(0.3 + overclock_excess * 2 + temp_wear * 3, 4)

    profit_per_h = round(revenue_per_h - electricity_per_h - salary_per_h, 2)
    return {
        "hashrate": hashrate, "power": total_power, "temperature": temperature,
        "coolingCapacity": cooling_cap, "condition": round(condition, 1),
        "revenuePerHour": revenue_per_h, "electricityPerHour": electricity_per_h,
        "salaryPerHour": salary_per_h, "profitPerHour": profit_per_h,
        "wearPerHour": wear_per_h, "gpuCount": len(gpus),
        "overheating": temperature >= OVERHEAT_TEMP,
    }
```
with:
```python
def _compute(farm: dict, market: dict, energy_cost: float, economy_mult: float = 1.0,
             city: Optional[dict] = None, live_hashrate_on_coin: float = 0.0) -> dict:
    # city — бонусы зданий «Крыши города»: yield (+% к добыче), energy (−% к счёту за свет).
    city = city or {}
    yield_bonus = float(city.get("yield", 0.0))
    energy_discount = min(0.5, float(city.get("energy", 0.0)))
    comp = farm.get("components", {})
    gpus = comp.get("gpus", [])
    fans = comp.get("fans", [])
    overclock = farm.get("overclock", 1.0)
    condition = farm.get("condition", 100.0)

    hashrate = _farm_hashrate(farm)
    gpu_power = sum(g.get("specs", {}).get("power", 0) for g in gpus) * overclock
    cpu_power = comp.get("cpu", {}).get("specs", {}).get("power", 0)
    mb_power = comp.get("motherboard", {}).get("specs", {}).get("power", 0)
    total_power = round(gpu_power + cpu_power + mb_power + BASE_POWER_W, 1)

    cooling_cap = comp.get("cooling", {}).get("specs", {}).get("cooling", 0) + sum(f.get("specs", {}).get("cooling", 0) for f in fans)
    manager = farm.get("manager") or {"type": "player", "level": 0}
    ai_level = manager.get("level", 0) if manager.get("type") == "ai" else 0
    cool_bonus = min(0.5, ai_level * 0.06)
    temperature = round(TEMP_AMBIENT + (total_power / max(1, cooling_cap)) * TEMP_FACTOR * (1 - cool_bonus), 1)

    profile = _farm_hw_profile(farm)
    gpu_count = profile["gpu_count"]
    gpu_eff = _gpu_efficiency(profile["cores"], gpu_count)
    ssd_eff = _ssd_efficiency(profile["ssd_gb"], gpu_count)
    net_eff = _net_efficiency(profile["net_speed"], gpu_count)

    coin_sym = farm.get("coin")
    coin = market.get(coin_sym) if coin_sym else None
    ram_eff = _ram_efficiency(profile["ram_gb"], gpu_count, float(coin["price"])) if coin else 1.0
    base_revenue = _coin_revenue_per_h(coin, profile, live_hashrate_on_coin)
    revenue_per_h = round(base_revenue * gpu_eff * ssd_eff * net_eff * economy_mult * (1 + yield_bonus), 2)

    electricity_per_h = round(total_power * energy_cost * ELEC_SCALE * (1 - energy_discount), 2)
    salary_per_h = round(MANAGER_SALARY_PER_H * ai_level, 2) if manager.get("type") == "ai" else 0.0

    overclock_excess = max(0.0, overclock - 1.0)
    temp_wear = max(0.0, (temperature - 60) / 100.0)
    wear_per_h = round(0.3 + overclock_excess * 2 + temp_wear * 3, 4)

    profit_per_h = round(revenue_per_h - electricity_per_h - salary_per_h, 2)
    return {
        "hashrate": hashrate, "power": total_power, "temperature": temperature,
        "coolingCapacity": cooling_cap, "condition": round(condition, 1),
        "revenuePerHour": revenue_per_h, "electricityPerHour": electricity_per_h,
        "salaryPerHour": salary_per_h, "profitPerHour": profit_per_h,
        "wearPerHour": wear_per_h, "gpuCount": gpu_count,
        "overheating": temperature >= OVERHEAT_TEMP,
        "upsProtected": profile["ups_backup"] >= total_power,
        "efficiency": {"gpu": round(gpu_eff, 3), "ram": round(ram_eff, 3),
                       "ssd": round(ssd_eff, 3), "network": round(net_eff, 3)},
    }
```

- [ ] **Step 4: Run the self-check to confirm it passes**

Run: `cd backend && python mining.py`
Expected: `mining self-check OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/mining.py
git commit -m "feat(mining): _compute uses share-of-difficulty revenue and component efficiency"
```

---

### Task 3: Farm-aware coin ranking in `/market`, `start_mining`, and `tick_all`

**Files:**
- Modify: `backend/mining.py`

**Interfaces:**
- Consumes: `choose_best_coin`, `_coin_revenue_per_h`, `_farm_hw_profile`, `_farm_hashrate` from Tasks 1–2.
- Produces: `_best_farm_profile(db, user_id: str) -> Optional[dict]`.
- Changes existing endpoint behavior: `GET /api/mining/market` now ranks by the requesting user's best assembled farm; `POST /api/mining/farms/{id}/start` and `tick_all()` pass a farm profile into `choose_best_coin`.

This task touches async DB-calling code with no standalone unit test harness available (no pytest in this repo) — verification is manual (Step 5 below), consistent with how the rest of `mining.py`'s endpoints are already tested (no automated endpoint tests exist today).

- [ ] **Step 1: Add `_best_farm_profile` and rewrite `GET /market`**

Replace:
```python
@router.get("/market")
async def mining_market(_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Монеты для выбора добычи + рекомендация ИИ (самая прибыльная)."""
    market = await _coin_market(db)
    coins = sorted(market.values(), key=lambda c: _coin_profitability(c), reverse=True)
    return {"coins": coins, "best": choose_best_coin(market)}
```
with:
```python
async def _best_farm_profile(db, user_id: str) -> Optional[dict]:
    """Профиль лучшей ПОЛНОСТЬЮ СОБРАННОЙ фермы игрока (не обязательно
    запущенной — чтобы можно было посмотреть рейтинг монет ДО старта добычи)."""
    best = None
    async for farm in db.mining_farms.find({"userId": user_id}):
        if _missing_required(farm):
            continue
        profile = _farm_hw_profile(farm)
        if best is None or profile["hashrate"] > best["hashrate"]:
            best = profile
    return best


@router.get("/market")
async def mining_market(current_user: dict = Depends(get_current_user), db: AsyncIOMotorDatabase = Depends(get_db)):
    """Монеты для выбора добычи + рекомендация ИИ, ранжированные под хешрейт
    лучшей собранной фермы игрока (без собранной фермы — по цене, как раньше)."""
    market = await _coin_market(db)
    profile = await _best_farm_profile(db, str(current_user["_id"]))
    best = choose_best_coin(market, profile)
    if profile:
        coins = sorted(market.values(), key=lambda c: _coin_revenue_per_h(c, profile), reverse=True)
    else:
        coins = sorted(market.values(), key=lambda c: c.get("price", 0), reverse=True)
    return {"coins": coins, "best": best}
```

- [ ] **Step 2: Update `start_mining`'s AI coin choice**

Replace:
```python
    coin = farm.get("coin")
    manager = farm.get("manager") or {}
    if not coin:
        if manager.get("type") == "ai":
            coin = choose_best_coin(market)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите криптовалюту для добычи")
```
with:
```python
    coin = farm.get("coin")
    manager = farm.get("manager") or {}
    if not coin:
        if manager.get("type") == "ai":
            coin = choose_best_coin(market, _farm_hw_profile(farm))
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите криптовалюту для добычи")
```

- [ ] **Step 3: Update `tick_all`'s AI coin choice, add live-hashrate aggregation, and the UPS brownout mechanic**

Replace:
```python
    async for farm in db.mining_farms.find({"status": "mining"}):
        last = _aware(farm.get("last_tick"))
        elapsed_h = min(MAX_ACCRUAL_H, (now - last).total_seconds() / 3600.0) if isinstance(last, datetime) else 0.0
        if elapsed_h < MINING_MIN_ELAPSED_H:
            continue

        user_id = farm["userId"]
        manager = farm.get("manager") or {"type": "player", "level": 0}
        ai = manager.get("type") == "ai"
        ai_level = manager.get("level", 0) if ai else 0

        # ИИ автоматически выбирает самую прибыльную монету.
        if ai:
            best = choose_best_coin(market)
            if best and best != farm.get("coin"):
                farm["coin"] = best

        city = await _city_bonus(db, user_id)
        stats = _compute(farm, market, ec, em, city)
        revenue = round(stats["revenuePerHour"] * elapsed_h, 2)
        electricity = round(stats["electricityPerHour"] * elapsed_h, 2)
        salary = round(stats["salaryPerHour"] * elapsed_h, 2)
        wear = stats["wearPerHour"] * elapsed_h
        new_condition = max(0.0, farm.get("condition", 100.0) - wear)
```
with:
```python
    # Живой вклад игроков в сложность (второстепенный сигнал, см. LIVE_WEIGHT):
    # суммарный хешрейт активных ферм по монетам, O(активных ферм) за тик.
    active_farms = await db.mining_farms.find({"status": "mining"}).to_list(length=None)
    live_hashrate_by_coin: dict = {}
    for farm in active_farms:
        sym = farm.get("coin")
        if sym:
            live_hashrate_by_coin[sym] = live_hashrate_by_coin.get(sym, 0.0) + _farm_hashrate(farm)

    for farm in active_farms:
        last = _aware(farm.get("last_tick"))
        elapsed_h = min(MAX_ACCRUAL_H, (now - last).total_seconds() / 3600.0) if isinstance(last, datetime) else 0.0
        if elapsed_h < MINING_MIN_ELAPSED_H:
            continue

        user_id = farm["userId"]
        manager = farm.get("manager") or {"type": "player", "level": 0}
        ai = manager.get("type") == "ai"
        ai_level = manager.get("level", 0) if ai else 0
        own_hashrate = _farm_hashrate(farm)

        # ИИ автоматически выбирает монету, максимизирующую ЕГО СОБСТВЕННУЮ выручку.
        if ai:
            profile = _farm_hw_profile(farm)
            live_excl_self = {sym: h - (own_hashrate if sym == farm.get("coin") else 0.0)
                               for sym, h in live_hashrate_by_coin.items()}
            best = choose_best_coin(market, profile, live_excl_self)
            if best and best != farm.get("coin"):
                farm["coin"] = best

        coin_sym_for_live = farm.get("coin")
        live_on_coin = max(0.0, live_hashrate_by_coin.get(coin_sym_for_live, 0.0) - own_hashrate) if coin_sym_for_live else 0.0

        city = await _city_bonus(db, user_id)
        stats = _compute(farm, market, ec, em, city, live_hashrate_on_coin=live_on_coin)

        # ИБП: шанс просадки питания за тик; без достаточного резерва — тик
        # без выручки и доп. износ (UPS — gate, не постоянный множитель).
        extra_wear = 0.0
        if random.random() < BROWNOUT_CHANCE and not stats.get("upsProtected", False):
            stats = dict(stats)
            stats["revenuePerHour"] = 0.0
            stats["profitPerHour"] = round(-stats["electricityPerHour"] - stats["salaryPerHour"], 2)
            extra_wear = UPS_WEAR_PENALTY

        revenue = round(stats["revenuePerHour"] * elapsed_h, 2)
        electricity = round(stats["electricityPerHour"] * elapsed_h, 2)
        salary = round(stats["salaryPerHour"] * elapsed_h, 2)
        wear = stats["wearPerHour"] * elapsed_h + extra_wear
        new_condition = max(0.0, farm.get("condition", 100.0) - wear)
```

Everything below this block (`repair_cost = 0.0` onward, through the end of `tick_all`) is unchanged — it already reads `stats["profitPerHour"]` and `farm.get("coin")`, which remain valid.

- [ ] **Step 4: Run the module self-check (regression check — this task didn't change pure functions, but confirms nothing broke)**

Run: `cd backend && python mining.py`
Expected: `mining self-check OK`.

- [ ] **Step 5: Manual verification (no automated endpoint tests exist in this repo)**

Start the backend (`cd backend && uvicorn main:app --reload` or the project's existing run command) and, using an authenticated session:
1. `GET /api/mining/market` with no farms — coins should come back sorted by price descending (fallback), `best` = the highest-priced coin.
2. Build a small farm (few weak GPUs) and call `GET /api/mining/market` again — `best` should now be a cheap coin, not the most expensive one.
3. Confirm `POST /farms/{id}/start` with an AI manager and no coin selected picks a coin consistent with the farm's hashrate (same one `/market`'s `best` shows).

- [ ] **Step 6: Commit**

```bash
git add backend/mining.py
git commit -m "feat(mining): farm-aware coin ranking, live-hashrate signal, UPS brownout mechanic"
```

---

### Task 4: Soft-reset migration for existing farms

**Files:**
- Modify: `backend/mining.py`
- Modify: `backend/main.py`

**Interfaces:**
- Produces (in `mining.py`): `MIGRATION_KEY = "mining_rebalance_v1"`, `_reset_farm_fields() -> dict` (pure), `async def soft_reset_farms(db: AsyncIOMotorDatabase) -> None`.
- Consumes: `find_config_by_key`, `upsert_config` from `backend/database.py` (already used identically by `shop.py`).

- [ ] **Step 1: Add the pure-function self-check assertion (will fail — function doesn't exist yet)**

In `backend/mining.py`, inside `if __name__ == "__main__":`, immediately before `print("mining self-check OK")`, add:

```python
    # ── Мягкий сброс: чистая функция полей сброса не трогает исторические итоги ──
    _reset = _reset_farm_fields()
    assert _reset["components"] == {"gpus": [], "fans": []}
    assert _reset["status"] == "idle" and _reset["coin"] is None
    assert _reset["condition"] == 100.0
    assert "total_earned" not in _reset and "total_spent" not in _reset
    assert "total_mined_usd" not in _reset and "total_mined_coins" not in _reset
```

- [ ] **Step 2: Run the self-check to confirm it fails**

Run: `cd backend && python mining.py`
Expected: `NameError: name '_reset_farm_fields' is not defined`.

- [ ] **Step 3: Import `find_config_by_key`/`upsert_config` at module level**

Replace:
```python
from auth import get_current_user, require_admin
from database import get_db
from ledger import INCOME, EXPENSE, CAT_MINING, adjust_balance, record_transaction
```
with:
```python
from auth import get_current_user, require_admin
from database import get_db, find_config_by_key, upsert_config
from ledger import INCOME, EXPENSE, CAT_MINING, adjust_balance, record_transaction
```

- [ ] **Step 4: Add `MIGRATION_KEY`, `_reset_farm_fields`, and `soft_reset_farms`**

Add this new section directly above the `# ── Фоновый тик добычи ...` comment (i.e., right after the `manage_manager` endpoint and before `tick_all`):

```python
# ── Миграция: мягкий сброс старых ферм под новую экономику ─────────────────

MIGRATION_KEY = "mining_rebalance_v1"


def _reset_farm_fields() -> dict:
    """Поля сброса фермы (чистая функция — тестируется без БД). Возвращает
    ферму в состояние «только что создана»: оборудование снято, статус idle,
    монета/износ/электричество сброшены. НЕ включает total_earned/total_spent/
    total_mined_* — исторические итоги сохраняются."""
    return {
        "components": {"gpus": [], "fans": []},
        "status": "idle",
        "coin": None,
        "condition": 100.0,
        "overclock": 1.0,
        "electricity_owed": 0.0,
    }


async def soft_reset_farms(db: AsyncIOMotorDatabase) -> None:
    """Одноразовая миграция на новую экономику майнинга: всё купленное
    железо возвращается в инвентарь, фермы сбрасываются к пустому состоянию.
    Идемпотентна (гейт через app_config, тот же паттерн, что и SHOP_CONFIG_KEY
    в shop.py) — повторный запуск при следующих рестартах ничего не делает."""
    if await find_config_by_key(db, MIGRATION_KEY):
        return
    await db.mining_farms.update_many({}, {"$set": _reset_farm_fields()})
    await db.user_hardware.update_many({"farmId": {"$ne": None}}, {"$set": {"farmId": None}})
    await upsert_config(db, MIGRATION_KEY, "1")
```

- [ ] **Step 5: Run the self-check to confirm it passes**

Run: `cd backend && python mining.py`
Expected: `mining self-check OK`.

- [ ] **Step 6: Wire the migration into `main.py`'s `lifespan()`**

In `backend/main.py`, replace:
```python
    await init_db()
    start_scheduler()   # единый фоновый планировщик всех систем
    yield
    await stop_scheduler()
```
with:
```python
    await init_db()
    await mining_module.soft_reset_farms(db)
    start_scheduler()   # единый фоновый планировщик всех систем
    yield
    await stop_scheduler()
```

(`mining_module` is already imported at the top of `main.py` as `import mining as mining_module` — no new import needed.)

- [ ] **Step 7: Manual verification**

Start the backend once against a dev database that has at least one existing farm with installed components. Confirm on startup:
1. The farm's `components` are all empty, `status` is `idle`, `coin` is `null`.
2. The hardware that was installed on that farm now shows up in `GET /api/mining/parts` (i.e., `user_hardware.farmId` was cleared).
3. `total_earned`/`total_spent`/`total_mined_usd`/`total_mined_coins` on the farm are unchanged from before the restart.
4. Restart the backend a second time — nothing changes further (idempotent; `app_config` has `key: "mining_rebalance_v1"`).

- [ ] **Step 8: Commit**

```bash
git add backend/mining.py backend/main.py
git commit -m "feat(mining): soft-reset migration returns hardware to inventory under new economy"
```

---

### Task 5: Frontend — surface component efficiency and UPS status

**Files:**
- Modify: `frontend/src/components/MiningTab.jsx`
- Modify: `frontend/src/economy.css`
- Modify: `frontend/src/i18n/locales/ru.json`
- Modify: `frontend/src/i18n/locales/en.json`

**Interfaces:**
- Consumes: `farm.stats.efficiency` (`{gpu, ram, ssd, network}`, each `0..1`) and `farm.stats.upsProtected` (`bool`), both now returned by `GET /farms`/`_serialize_with_stats` because `_compute`'s return dict (Task 2) flows straight through unchanged serialization code.
- Consumes: `farm.components.ups` (already existing field) to decide whether to show the UPS badge at all.

- [ ] **Step 1: Add translation keys**

In `frontend/src/i18n/locales/ru.json`, inside the `"mining"` object, add a new `"eff"` object and two UPS-status keys. Insert immediately after the `"desc": { ... }` block (i.e., after its closing `},` and before `"removeOne"`):

```json
    "eff": {
      "gpu": "CPU→GPU",
      "ram": "RAM",
      "ssd": "SSD",
      "network": "Сеть"
    },
    "upsStatus": "ИБП",
    "upsOk": "защищено",
    "upsWeak": "недостаточно",
```

Also update the existing decorative `"desc"` strings for `ram`/`ssd`/`psu`/`ups`/`network` (they described no-op components before this rebalance and are now misleading) — replace:
```json
      "ram": "Уменьшает простои фермы.",
      "ssd": "Ускоряет переключение алгоритмов.",
      "psu": "Влияет на стабильность работы.",
```
with:
```json
      "ram": "Должна вмещать DAG-файл — чем дороже монета, тем больше нужно.",
      "ssd": "Хранит ноду и DAG-кэш — нехватка означает пересинхронизацию.",
      "psu": "Обеспечивает пиковую мощность всех видеокарт.",
```
and replace:
```json
      "ups": "Защищает от отключения электричества.",
      "network": "Обеспечивает стабильное подключение к пулу."
```
with:
```json
      "ups": "При просадке питания спасает добычу этого тика — только если резерва хватает на всю мощность фермы.",
      "network": "Мало пропускной способности на пуле — устаревшие/отклонённые шары."
```

In `frontend/src/i18n/locales/en.json`, apply the mirrored change. Insert after the `"desc": { ... }` block:

```json
    "eff": {
      "gpu": "CPU→GPU",
      "ram": "RAM",
      "ssd": "SSD",
      "network": "Network"
    },
    "upsStatus": "UPS",
    "upsOk": "protected",
    "upsWeak": "insufficient",
```

Replace:
```json
      "ram": "Reduces farm downtime.",
      "ssd": "Speeds up algorithm switching.",
      "psu": "Affects operational stability.",
```
with:
```json
      "ram": "Must fit the DAG file — pricier coins need more.",
      "ssd": "Stores the node and DAG cache — too little means constant re-sync.",
      "psu": "Must cover the peak draw of every installed GPU.",
```
and replace:
```json
      "ups": "Protects against power outages.",
      "network": "Keeps a stable connection to the pool."
```
with:
```json
      "ups": "Saves that tick's yield during a power brownout — only if its reserve covers the farm's full draw.",
      "network": "Too little bandwidth to the pool means stale/rejected shares."
```

- [ ] **Step 2: Add the efficiency/UPS badge row to `MiningTab.jsx`**

Replace:
```jsx
        {/* Мониторинг — только для собранной фермы (иначе показатели не считаются). */}
        {assembled ? (
          <div className="mining-stat-cards">
            <div className="msc"><Activity size={16} /><span>{t('mining.hashrate')}</span><b>{formatCompact(s.hashrate)} H/s</b></div>
            <div className="msc"><Zap size={16} /><span>{t('mining.power')}</span><b>{formatCompact(s.power)} W</b></div>
            <div className="msc"><Thermometer size={16} /><span>{t('mining.temp')}</span><b className={tempClass(s.temperature)}>{s.temperature ?? '—'}°C</b></div>
            <div className="msc"><Gauge size={16} /><span>{t('mining.condition')}</span><b>{farm.condition}%</b></div>
            <div className="msc"><TrendingUp size={16} /><span>{t('mining.incomeHr')}</span><b className="up">${formatMoney(s.revenuePerHour)}</b></div>
            <div className="msc"><Zap size={16} /><span>{t('mining.elecHr')}</span><b className="down">${formatMoney(s.electricityPerHour)}</b></div>
            <div className="msc"><TrendingUp size={16} /><span>{t('mining.profitHr')}</span><b className={s.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(s.profitPerHour)}</b></div>
            <div className="msc"><HardDrive size={16} /><span>{t('mining.earned')}</span><b>${formatCompact(farm.totalEarned)}</b></div>
          </div>
        ) : (
```
with:
```jsx
        {/* Мониторинг — только для собранной фермы (иначе показатели не считаются). */}
        {assembled ? (
          <>
          <div className="mining-stat-cards">
            <div className="msc"><Activity size={16} /><span>{t('mining.hashrate')}</span><b>{formatCompact(s.hashrate)} H/s</b></div>
            <div className="msc"><Zap size={16} /><span>{t('mining.power')}</span><b>{formatCompact(s.power)} W</b></div>
            <div className="msc"><Thermometer size={16} /><span>{t('mining.temp')}</span><b className={tempClass(s.temperature)}>{s.temperature ?? '—'}°C</b></div>
            <div className="msc"><Gauge size={16} /><span>{t('mining.condition')}</span><b>{farm.condition}%</b></div>
            <div className="msc"><TrendingUp size={16} /><span>{t('mining.incomeHr')}</span><b className="up">${formatMoney(s.revenuePerHour)}</b></div>
            <div className="msc"><Zap size={16} /><span>{t('mining.elecHr')}</span><b className="down">${formatMoney(s.electricityPerHour)}</b></div>
            <div className="msc"><TrendingUp size={16} /><span>{t('mining.profitHr')}</span><b className={s.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(s.profitPerHour)}</b></div>
            <div className="msc"><HardDrive size={16} /><span>{t('mining.earned')}</span><b>${formatCompact(farm.totalEarned)}</b></div>
          </div>
          <div className="mining-eff-row">
            {['gpu', 'ram', 'ssd', 'network'].map(k => (
              <span key={k} className={`mining-eff-badge ${(s.efficiency?.[k] ?? 1) < 0.5 ? 'low' : ''}`}>
                {t(`mining.eff.${k}`)}: {Math.round((s.efficiency?.[k] ?? 1) * 100)}%
              </span>
            ))}
            {farm.components?.ups && (
              <span className={`mining-eff-badge ${s.upsProtected ? 'ok' : 'warn'}`}>
                {t('mining.upsStatus')}: {s.upsProtected ? t('mining.upsOk') : t('mining.upsWeak')}
              </span>
            )}
          </div>
          </>
        ) : (
```

- [ ] **Step 3: Add CSS for the new badge row**

In `frontend/src/economy.css`, immediately after the existing `.msc b.ok { ... } .msc b.warn { ... } .msc b.crit { ... }` line (the one right after `.msc b.up`/`.msc b.down`), add:

```css
.mining-eff-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 var(--spacing-md); }
.mining-eff-badge { font-size: 11px; padding: 4px 10px; border-radius: 999px; background: var(--color-bg-tertiary); border: 1px solid var(--hairline); color: var(--color-text-secondary); }
.mining-eff-badge.low { color: var(--color-danger); border-color: rgba(255, 59, 48, 0.35); }
.mining-eff-badge.ok { color: var(--color-success); border-color: rgba(52, 199, 89, 0.35); }
.mining-eff-badge.warn { color: #ff9f0a; border-color: rgba(255, 159, 10, 0.35); }
```

- [ ] **Step 4: Manual verification in the browser**

Run the frontend dev server (existing project command, e.g. `npm run dev` in `frontend/`), log in, open the Mining tab with an assembled farm:
1. Confirm four efficiency badges (CPU→GPU / RAM / SSD / Network) render with percentages.
2. Remove enough RAM (uninstall it, or check with low RAM vs. many GPUs) to see the RAM badge drop below 50% and turn into the "low" (red) style.
3. Install a UPS with less backup than the farm's total power draw — confirm the badge shows the "insufficient" (warn/orange) state; install a UPS with backup ≥ total power — confirm it flips to "protected" (green).
4. Switch the UI language toggle (ru/en) and confirm all new strings translate (no raw `mining.eff.gpu`-style keys visible).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MiningTab.jsx frontend/src/economy.css frontend/src/i18n/locales/ru.json frontend/src/i18n/locales/en.json
git commit -m "feat(mining): surface component efficiency and UPS protection status in the UI"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-23-mining-rebalance-design.md`):
- §1 Share-of-network revenue model → Task 1 (`_coin_difficulty`, `_farm_share`, `_coin_revenue_per_h`, `choose_best_coin`) + Task 3 (live-hashrate aggregation in `tick_all`, farm-aware `/market`). ✅
- §2 Every component gets a real multiplier → Task 1 (`_gpu_efficiency`/`_ram_efficiency`/`_ssd_efficiency`/`_net_efficiency`) + Task 2 (wired into `_compute`) + Task 3 (UPS brownout gate in `tick_all`) + Task 5 (exposed in UI). ✅
- §3 Soft reset of existing farms → Task 4. ✅
- Non-goals (halving, pools, algorithm-family tags) → intentionally not implemented anywhere in this plan. ✅
- Testing (weak/strong farm coin choice, efficiency clamping, migration purity) → Task 1 Step 1 and Task 4 Step 1 self-check assertions. ✅

**Placeholder scan:** No `TBD`/`TODO`/"add appropriate handling" phrases in any step; every code block is complete and copy-pasteable; every step that changes code shows the full before/after.

**Type/signature consistency check:**
- `_compute(farm, market, energy_cost, economy_mult=1.0, city=None, live_hashrate_on_coin=0.0)` — same signature used in Task 2 (definition), Task 3 Step 3 (`tick_all` call site with `live_hashrate_on_coin=live_on_coin`), and unchanged elsewhere (`/farms`, `start_mining`, `_serialize_with_stats`, admin endpoints all still call it positionally/by the pre-existing keyword args, which remain valid since the new parameter has a default).
- `choose_best_coin(market, profile=None, live_hashrate_by_coin=None)` — matches call sites in Task 1 self-check, Task 3 `/market`, `start_mining`, and `tick_all`.
- `_farm_hw_profile(farm)` keys (`hashrate`, `gpu_count`, `cores`, `ram_gb`, `ssd_gb`, `net_speed`, `ups_backup`) — same keys read in `_compute` (Task 2), `_coin_revenue_per_h` (Task 1), and the Task 1/2 self-check dicts.
- `soft_reset_farms`/`_reset_farm_fields` names match between Task 4's definition and its self-check/`main.py` call site.

No gaps found.
