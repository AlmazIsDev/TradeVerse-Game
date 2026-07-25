# Admin Panel: DB Point-Editor + Crypto/Stock Chart Editing

**Date:** 2026-07-23
**Scope:** New admin-only raw DB editor tab; new Crypto admin tab (didn't exist); shared price-history point-edit/regenerate for crypto and stocks
**Files:** `backend/admin_db.py` (new) · `backend/crypto.py` · `backend/market_data.py` · `backend/main.py` (router wiring) · `frontend/src/components/AdminPanel.jsx` · `frontend/src/components/PriceHistoryEditor.jsx` (new) · `frontend/src/services/api.js`

---

## Problem

Admin can already edit stocks, users, transactions, shop prices, config and economy params, but three things are missing:

1. No way to fix an arbitrary bad document in the database without a Mongo shell — every fix needs a matching bespoke admin endpoint + UI.
2. No admin tab for crypto at all. Coins are only edited by seeding `DEFAULT_COINS` or by the CoinGecko live-refresh path; there's no way to hand-tune a coin's price, market cap, or description.
3. No way to edit or regenerate a symbol's price chart (`db.price_history`) for either crypto or stocks — history is either backfilled once (`MarketDataService.ensure_backfill`) or accumulated live; there's no correction path.

Stocks already have `total_shares` (`StockConfigUpdate`, `PATCH /api/v2/stocks/{symbol}/config`), which functions as supply — market cap is already `price × total_shares` (`market_data.py:323`). No schema change needed there; only the chart-editing gap applies to stocks.

## Design

### 1. Universal DB point-editor

New router `backend/admin_db.py`, mounted in `main.py` like the other routers (`app.include_router(admin_db_router)`). Every endpoint behind `require_admin` (same dependency used everywhere else, `auth.py:188`).

```
GET    /api/admin/db/collections                       -> list[str]  (db.list_collection_names())
GET    /api/admin/db/collections/{name}?q=&skip=&limit= -> {items, total}  (limit capped at 200)
GET    /api/admin/db/collections/{name}/{doc_id}        -> single doc
POST   /api/admin/db/collections/{name}                 -> insert, body = raw doc (no _id)
PATCH  /api/admin/db/collections/{name}/{doc_id}         -> $set merge, body = partial doc
DELETE /api/admin/db/collections/{name}/{doc_id}
```

No collection allowlist — deliberately universal per requirements, including `users`.

Serialization uses `bson.json_util.dumps`/`loads` (already available transitively via `pymongo`/`motor`) — MongoDB Extended JSON, so `ObjectId` round-trips as `{"$oid": "..."}` and `datetime` as `{"$date": ...}`. Endpoints read/write the raw request body as bytes and run it through `json_util.loads`, rather than a Pydantic model, since the whole point is arbitrary shape. `_id` is always excluded from the PATCH body's `$set` (dropped if present) so it can't be mutated in place.

`q` on the list endpoint does a simple substring match across all string-valued top-level fields (client sends a plain search string, server builds `{"$or": [{"field": {"$regex": q, "$options": "i"}} for field in known-string-fields-of-first-doc]}` — cheap, no text index needed at this scale).

`ponytail:` fully-universal raw JSON editing means a bad edit can corrupt data invisibly (e.g. writing a plaintext string into `hashed_password` silently breaks that user's login; turning a `datetime` field into a plain string can break code that does `isinstance(x, datetime)` checks, like `_aware()` in `market_data.py`). This is the accepted trade-off for a truly universal tool — the upgrade path if it bites someone is a schema-aware editor for the specific collection that keeps breaking.

**Frontend:** new "Database" tab in `AdminPanel.jsx`'s `sections` array. Collection dropdown (populated from `/collections`) → paginated list (each row: `_id` + one-line JSON preview) → click opens a modal (`modal-overlay`/`modal-content`, existing classes) with a `<textarea>` holding pretty-printed JSON. Save = PATCH, a "+ New document" button opens the same modal empty for POST, a trash icon per row for DELETE. No JSON-editor dependency — plain textarea, admin is expected to type valid JSON (invalid JSON just shows a parse error inline, doesn't submit).

### 2. Crypto admin tab (new)

Admin endpoints added to `crypto.py`, same `require_admin` inline pattern already used in `stocks.py:663-667`:

```
PATCH  /api/crypto/admin/{symbol}   body: {name?, price?, marketCap?, volatility?, color?, description?}
POST   /api/crypto/admin            body: {symbol, name, price, volatility?, color?, supply?, description?}
DELETE /api/crypto/admin/{symbol}
```

- If `marketCap` is given: `supply = marketCap / current_or_new_price` (rounded), persisted on the doc alongside a persisted `marketCap` field (currently only computed on the fly for sim coins in `market_asset`; this makes it a real stored field admin can set directly, matching what live/CoinGecko coins already carry after `refresh_crypto`).
- If `price` is given (with or without `marketCap`): also set `base_price = price`. `_walk_price` (`crypto.py:134`) anchors its `[0.3x, 3x]` corridor to `base_price` — without re-anchoring, an admin-set price near the edge of the old corridor would get clamped almost immediately by the next sim tick.
- `POST` seeds a new coin the same way `ensure_coins_seeded` does (sets `base_price`, `ath`/`atl` = price, `volume24h` estimate) and calls `MarketDataService.ensure_backfill` for its initial chart.
- `DELETE` removes the `crypto_assets` doc only. `ponytail:` leaves orphaned `crypto_holdings`/`price_history` rows for that symbol — acceptable for an admin tool deleting a coin nobody should be holding; upgrade path is a cascade delete if this becomes a real workflow.

**Frontend:** new "Crypto" entry in `sections`, list/edit UI mirroring the existing Stocks tab's `admin-list` + inline-edit-row pattern (reuse the same CSS classes) — symbol, name, price, market cap, volatility, color swatch, description. Each row gets a "Chart" button opening `PriceHistoryEditor` (see below).

### 3. Price-history point-edit + regenerate (shared: crypto & stocks)

Added to `market_data.py`, admin-only, next to the existing `MarketDataService`:

```
GET    /api/admin/price-history?market=&symbol=          -> [{id, ts, price}, ...] full ordered list
POST   /api/admin/price-history                          body: {market, symbol, price, ts}
PATCH  /api/admin/price-history/{id}                     body: {price?, ts?}
DELETE /api/admin/price-history/{id}
POST   /api/admin/price-history/regenerate                body: {market, symbol, price?, volatility?}
```

`regenerate` needs a "force" version of the backfill walk. `MarketDataService.ensure_backfill` currently early-returns if any history exists for the symbol — refactor: extract the two `walk_back(...)` calls and doc-assembly into a new `_build_walk_docs(market, symbol, current_price, volatility)` helper (pure, returns the doc list); `ensure_backfill` keeps its existing early-return guard and calls the helper; the new `regenerate` static method skips the guard, does `delete_many({market, symbol})` then `insert_many(_build_walk_docs(...))`. `price`/`volatility` default to the asset's current stored values if omitted.

**Frontend:** one shared `PriceHistoryEditor.jsx` modal component — table of `{time, price}` rows with inline edit/delete, an "Add point" row, and a "Regenerate" action (optional price/volatility override fields, confirms before wiping existing history). Used from both the new Crypto tab and the existing Stocks tab (adds a single "Chart" button next to the existing Edit/Config/Delete icons there — no other change to the Stocks tab).

## Non-goals / explicitly deferred

- No collection allowlist / field-level redaction in the DB editor — full universality was explicitly requested.
- No cascade-delete of holdings/history when a crypto asset is deleted.
- No new `supply`/`marketCap` fields on stocks — `total_shares` already serves that role.
- No pagination/virtualization for very large collections beyond a hard `limit` cap (200) — fine at this app's data scale.

## Testing

- `backend/admin_db.py`: `if __name__ == "__main__":` self-check asserting `json_util` round-trip for a doc containing an `ObjectId` and a `datetime` field, and that `_id` is stripped from a PATCH `$set` payload.
- `market_data.py`: extend existing self-check (or add one) asserting `_build_walk_docs` produces a bounded (`[price*0.15, price*6]`), time-ordered series, and that `ensure_backfill` still no-ops when history exists while `regenerate` always rebuilds.
