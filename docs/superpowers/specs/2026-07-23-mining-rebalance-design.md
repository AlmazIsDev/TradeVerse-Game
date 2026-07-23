# Mining Rebalance: Share-of-Network Economy + Full Component Roles

**Date:** 2026-07-23
**Scope:** Coin-choice balance, component realism, soft reset of existing farms
**Files:** `backend/mining.py` · `backend/main.py` · `backend/shop.py` (specs only if needed) · `frontend/src/components/MiningTab.jsx`

---

## Problem

1. **Coin choice is not a real choice.** `_coin_profitability()` (mining.py) is `sqrt(price) × momentum`. Revenue scales monotonically with price and has no dependency on the player's own hashrate, so the most expensive coin (RUBY, 340) is always optimal for every farm, weak or strong. `choose_best_coin()` (used by the AI manager and `/market`) just picks the max of this — it never considers what the farm can actually do.
2. **Half the shop catalog is decorative.** `cpu.cores`, `ram.gb`, `ssd.gb`, `ups.backup`, `network.speed` are required or optional purchases that currently do nothing in `_compute()`. Only GPU hashrate/power, cooling, fans, motherboard/case/rack slots affect the simulation.
3. **Only ~5 concurrent players exist.** Any design that derives coin difficulty primarily from live aggregate player hashrate won't move — there isn't enough population to create real network contention.

## Design

### 1. Share-of-network revenue model (replaces `_coin_profitability`)

Real mining: your share of a block reward is `your_hashrate / network_hashrate`. We simulate the network's hashrate as **synthetic difficulty derived from price**, plus a small live contribution from actual players (flavor, not the mechanism):

```python
DIFF_EXP = 1.5        # difficulty grows faster than price → self-balances
DIFF_SCALE = <tuned>  # see calibration note below
EMISSION = <tuned>    # coin-units/hour equivalent at share=1.0
LIVE_WEIGHT = 0.05    # live player hashrate counts as ~5% of an equal amount of synthetic difficulty — flavor, not the driver

def _coin_difficulty(coin, live_hashrate_on_coin: float) -> float:
    base = (coin["price"] ** DIFF_EXP) * DIFF_SCALE
    return base + live_hashrate_on_coin * LIVE_WEIGHT

def _farm_share(my_hashrate: float, difficulty: float) -> float:
    return my_hashrate / (difficulty + my_hashrate)   # saturating curve, never > 1

revenue_per_h = _farm_share(hashrate, difficulty) * EMISSION * price   # REPLACES hashrate*HASH_YIELD*prof entirely
```

`share` already embeds `hashrate` (it's the numerator), so this line **replaces** the old `hashrate * HASH_YIELD * prof` revenue calc wholesale — it does not additionally multiply by hashrate again. `HASH_YIELD` and `_coin_profitability` are removed.

**Qualitative crossover (this is the mechanism being verified, not a promise of exact numbers):** for a weak farm, `difficulty` for an expensive coin dwarfs `hashrate`, so `share ≈ hashrate/difficulty` (small, shrinks fast as price rises since difficulty grows as `price^1.5`); a cheap coin has low difficulty, so the same hashrate captures a much bigger share of a smaller reward — the product can win out. For a strong farm, `hashrate` can approach or exceed even an expensive coin's difficulty, `share → close to 1`, and the high price then dominates. The crossover point is therefore a function of the farm's own hashrate, not a global ranking.

**Calibration note (implementation-time task, not deferred to "later"):** `DIFF_SCALE` and `EMISSION` must be picked together so that a mid-tier farm's profit (revenue − electricity, using the existing `ELEC_SCALE`/`BASE_POWER_W` constants) stays in the same rough order of magnitude as today's numbers. Procedure: pick `DIFF_SCALE` so a starter farm (~500 hashrate) is share-competitive on the cheapest coins (MEME/DUSK/PIX, price < $1), then pick `EMISSION` so that farm's revenue on its best coin roughly matches what it earns today, then verify via the self-check (see Testing) that a top-tier farm (~50,000+ hashrate, full ASIC rack) is still best served by an expensive coin (RUBY/GLD). This is a numeric-fitting pass done while writing the code, exactly like the existing self-check already asserts concrete numbers for `_capacity`/`_psu_max`.

Revenue per hour: `share × EMISSION × price` (still expressed as USD-equivalent → converted to coin qty exactly as today via `_mined_qty`).

**Why this fixes the imbalance:** difficulty grows as `price^1.5`, faster than price itself. For a weak farm, a high-price coin's share is tiny (denominator dominated by difficulty) — revenue is worse than a cheap coin where difficulty is low enough that hashrate matters. For a strong farm, hashrate can overcome even the high difficulty of an expensive coin, making it the best choice again. The crossover point depends on the farm's own hashrate — there is no longer a single "always best" coin.

`choose_best_coin()` and `GET /api/mining/market` change from ranking by `_coin_profitability(coin)` to ranking by **this farm's projected revenue** (`_farm_share(farm_hashrate, difficulty) × EMISSION × price`), i.e. the ranking becomes farm-specific, not global. `/market` takes the requesting user's best-equipped active farm's hashrate as input (0 if none, in which case fall back to price-only ranking as today, since there's nothing to rank against yet).

Live contribution: `tick_all` already iterates every `status: mining` farm each tick; before computing per-farm stats, aggregate `sum(hashrate)` grouped by `coin` across all active farms into a dict, and pass each farm's `live_hashrate_on_coin` (sum minus its own contribution) into `_coin_difficulty`. This is O(active farms) extra work per tick, negligible at current scale, and gives a genuine (if small) "crowded coin gets worse" signal once there's more than one active farm on it.

### 2. Every component gets a real multiplier

All factors multiply into a single `efficiency` term inside `_compute()`. Each is independent, clamped to `[floor, 1.0]`, and computed from specs already on the item (no new catalog fields):

| Component | Real-world role | Formula sketch |
|---|---|---|
| **CPU** (`cores`) | Coordinates/feeds GPUs (driver overhead, PCIe management) | `gpu_eff = min(1.0, cores * GPUS_PER_CORE / max(1, gpu_count))` — too few cores for the GPU count throttles hashrate |
| **RAM** (`gb`) | DAG file must fit in VRAM+system RAM for memory-hard algorithms; modeled as a per-GPU requirement that scales with coin price (proxy for "memory-hard-ness") | `needed = gpu_count * RAM_PER_GPU * (1 + price_factor)`; `ram_eff = min(1.0, ram_gb / needed)` |
| **SSD** (`gb`) | Stores blockchain node / DAG cache; too small means constant re-sync | `ssd_eff = min(1.0, ssd_gb / (SSD_PER_GPU * gpu_count))` |
| **Network** (`speed`) | Bandwidth to the pool; too little means stale/rejected shares | `net_eff = min(1.0, speed / (NET_PER_GPU * gpu_count))` |
| **UPS** (`backup`) | Backup power during grid drops | in `tick_all`, per active farm per tick: small random "brownout" chance; if `ups.backup < total_power` the tick's revenue is zeroed and wear applied, else the farm rides through unaffected |

`revenue_per_h = _farm_share(hashrate, difficulty) * EMISSION * price * gpu_eff * ram_eff * ssd_eff * net_eff` (existing `cond_factor`/`overclock` stay as-is, already folded into `hashrate` before it reaches this formula, same as today). UPS is a tick-level pass/fail gate, not a continuous multiplier (matches its real role: it doesn't make things faster, it prevents losses during an outage).

All five constants (`GPUS_PER_CORE`, `RAM_PER_GPU`, `SSD_PER_GPU`, `NET_PER_GPU`, brownout chance) live as named constants at the top of `mining.py` next to the existing tuning constants (`HASH_YIELD`, `ELEC_SCALE`, etc.), same pattern already used in the file.

`_serialize`/`_serialize_with_stats` expose the individual `*_eff` factors in `stats` so the frontend can show *why* a farm is underperforming (e.g. "RAM: 60%" as a visible bottleneck), rather than a single opaque number.

### 3. Soft reset of existing farms

One-time migration, gated by a flag in `app_config` (same collection `shop.py`/`econ.py` already use via `find_config_by_key`/`upsert_config`), run once at `lifespan` startup in `main.py`:

- For every doc in `mining_farms`: set every `components.*` entry back to unset/empty, `status: "idle"`, `coin: None`, `condition: 100.0`, clear accrued `electricity_owed`. Do **not** delete the farm itself or touch `total_earned`/`total_spent`/`total_mined_*` (historical record stays).
- For every doc in `user_hardware` referencing those farms: set `farmId: None` — hardware returns to inventory, nothing is deleted or refunded.
- Set the migration flag so this never re-runs on subsequent restarts.

Players keep 100% of their purchased hardware and re-assemble farms under the new rules; no economic loss, no manual admin action needed.

## Non-goals / explicitly deferred

- Block halving / time-decaying emission — not needed at this scale, can layer in later if the constant `EMISSION` needs a time dimension.
- Mining pools (variance reduction) — the share model already gives smooth expected-value revenue every tick (no block-lottery variance to reduce).
- Per-coin algorithm families (GPU-friendly vs ASIC-only vs memory-hard as discrete tags) — folded into the continuous `price_factor` proxy in the RAM formula instead of a separate data model, to avoid new catalog fields for ~5 players.

## Testing

Extend the existing `if __name__ == "__main__":` self-check block in `mining.py` (same pattern as today) with assertions covering:
- A weak farm's best coin is NOT the most expensive one available.
- A strong (high-hashrate) farm's best coin ranking shifts toward the expensive end.
- `gpu_eff`/`ram_eff`/`ssd_eff`/`net_eff` each clamp correctly at the floor and at 1.0.
- Soft-reset migration logic (pure function operating on a farm dict, if extracted) leaves hardware specs intact while zeroing farm-side state.
