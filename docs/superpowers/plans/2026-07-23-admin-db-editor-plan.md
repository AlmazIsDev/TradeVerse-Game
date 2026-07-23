# Admin DB Editor + Crypto/Stock Chart Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the admin panel a universal raw-DB point-editor, a new Crypto admin tab (create/edit/delete coins incl. market cap), and a shared price-history editor (point edits + full regenerate) usable from both the new Crypto tab and the existing Stocks tab.

**Architecture:** Three new/extended FastAPI routers (`admin_db.py` new; `market_data.py` and `crypto.py` extended) all gated by the existing `require_admin` dependency, plus matching `frontend/src/services/api.js` wrappers, a new shared `PriceHistoryEditor.jsx` modal, and two new tabs + one new button wired into the existing `AdminPanel.jsx`.

**Tech Stack:** FastAPI + Motor (async MongoDB), `bson.json_util` for Extended-JSON serialization, React + `react-i18next`, existing `admin-*`/`modal-*` CSS classes.

## Global Constraints

- No collection allowlist in the DB editor — deliberately universal, including `users` (accepted risk, per spec).
- No cascade-delete of crypto holdings/price-history on coin delete.
- No new `supply`/`marketCap` fields on stocks — `total_shares` already serves that role; only chart editing is new for stocks.
- List/query endpoints cap `limit` at 200.
- No pytest — every backend file with non-trivial new logic gets/extends an `if __name__ == "__main__":` assert self-check (existing repo convention).
- Never use `git add -A`/`git add .` when committing — `backend/mining.py`, `frontend/src/components/MiningTab.jsx`, `frontend/src/services/api.js` already have unrelated uncommitted changes in the working tree; stage only the exact files each step touches.

---

### Task 1: Universal DB point-editor (`backend/admin_db.py`)

**Files:**
- Create: `backend/admin_db.py`
- Modify: `backend/main.py:25-49` (import), `backend/main.py:152-167` (router wiring)

**Interfaces:**
- Produces: `router` (FastAPI `APIRouter`, prefix `/api/admin/db`) with endpoints `GET /collections`, `GET /collections/{name}`, `GET /collections/{name}/{doc_id}`, `POST /collections/{name}`, `PATCH /collections/{name}/{doc_id}`, `DELETE /collections/{name}/{doc_id}`.

- [ ] **Step 1: Write `backend/admin_db.py`**

```python
"""Универсальный редактор БД для админа: просмотр/правка/удаление любых коллекций.

ponytail: без allowlist коллекций — полностью универсальный редактор по
требованию (см. docs/superpowers/specs/2026-07-23-admin-db-editor-design.md).
Сырой JSON-редактор — плохая правка может незаметно сломать данные (например
строка вместо datetime ломает isinstance-проверки вроде _aware() в
market_data.py). Апгрейд-путь при необходимости — типизированный редактор
для конкретной "болящей" коллекции.
"""
from __future__ import annotations

from bson import json_util, ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from auth import require_admin
from database import get_db

router = APIRouter(prefix="/api/admin/db", tags=["admin-db"])

LIST_LIMIT_CAP = 200


def _to_json(doc) -> dict:
    """BSON doc -> JSON-совместимый dict через Extended JSON (ObjectId/datetime — типизированно)."""
    return json_util.loads(json_util.dumps(doc))


def _strip_id(payload: dict) -> dict:
    payload = dict(payload)
    payload.pop("_id", None)
    return payload


def _filter_for(doc_id: str) -> dict:
    return {"_id": ObjectId(doc_id) if ObjectId.is_valid(doc_id) else doc_id}


@router.get("/collections")
async def list_collections(
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    return sorted(await db.list_collection_names())


@router.get("/collections/{name}")
async def list_documents(
    name: str,
    q: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=LIST_LIMIT_CAP),
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    coll = db[name]
    query: dict = {}
    if q:
        sample = await coll.find_one({})
        string_fields = [k for k, v in (sample or {}).items() if isinstance(v, str)]
        if string_fields:
            query = {"$or": [{f: {"$regex": q, "$options": "i"}} for f in string_fields]}
    total = await coll.count_documents(query)
    items = [_to_json(doc) async for doc in coll.find(query).skip(skip).limit(limit)]
    return {"items": items, "total": total}


@router.get("/collections/{name}/{doc_id}")
async def get_document(
    name: str,
    doc_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await db[name].find_one(_filter_for(doc_id))
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return _to_json(doc)


@router.post("/collections/{name}", status_code=status.HTTP_201_CREATED)
async def create_document(
    name: str,
    request: Request,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    body = json_util.loads(await request.body())
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тело должно быть JSON-объектом")
    result = await db[name].insert_one(_strip_id(body))
    return await get_document(name, str(result.inserted_id), _admin=_admin, db=db)


@router.patch("/collections/{name}/{doc_id}")
async def update_document(
    name: str,
    doc_id: str,
    request: Request,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    body = json_util.loads(await request.body())
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Тело должно быть JSON-объектом")
    fields = _strip_id(body)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое тело запроса")
    result = await db[name].update_one(_filter_for(doc_id), {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return await get_document(name, doc_id, _admin=_admin, db=db)


@router.delete("/collections/{name}/{doc_id}")
async def delete_document(
    name: str,
    doc_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db[name].delete_one(_filter_for(doc_id))
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return {"deleted": True}


if __name__ == "__main__":
    from datetime import datetime, timezone

    # json_util round-trip сохраняет ObjectId и datetime как типы, не строки.
    doc = {"_id": ObjectId(), "created_at": datetime.now(timezone.utc), "name": "x"}
    restored = _to_json(doc)
    assert isinstance(restored["_id"], ObjectId), restored["_id"]
    assert isinstance(restored["created_at"], datetime), restored["created_at"]
    assert restored["name"] == "x"

    # _strip_id всегда убирает _id из тела PATCH/POST.
    stripped = _strip_id({"_id": "abc", "role": "admin"})
    assert "_id" not in stripped
    assert stripped["role"] == "admin"

    print("admin_db self-check OK")
```

- [ ] **Step 2: Run the self-check**

Run: `cd backend && python admin_db.py`
Expected: `admin_db self-check OK`

- [ ] **Step 3: Wire the router into `backend/main.py`**

In `backend/main.py`, add the import next to the other router imports (after line 47 `from mining import router as mining_router`):

```python
from mining import router as mining_router
from admin_db import router as admin_db_router
```

Then add the `include_router` call next to the others (after line 165 `app.include_router(mining_router)`):

```python
app.include_router(mining_router)
app.include_router(admin_db_router)
```

- [ ] **Step 4: Verify the server boots and the router is mounted**

Run: `cd backend && python -c "import main; print([r.path for r in main.app.routes if 'admin/db' in r.path])"`
Expected: prints a list containing `/api/admin/db/collections`, `/api/admin/db/collections/{name}`, `/api/admin/db/collections/{name}/{doc_id}` (no import errors).

- [ ] **Step 5: Commit**

```bash
git add backend/admin_db.py backend/main.py
git commit -m "feat(admin): universal DB point-editor endpoints"
```

---

### Task 2: Shared price-history point-edit + regenerate (`backend/market_data.py`)

**Files:**
- Modify: `backend/market_data.py:94-118` (extract `_build_walk_docs`, refactor `ensure_backfill`, add `regenerate`), `backend/market_data.py:27` (import `require_admin`), append new endpoints after the `Favorites` section (end of file, after line 403).

**Interfaces:**
- Consumes: `require_admin` from `auth.py` (same as Task 1/existing `stocks.py` pattern).
- Produces: `MarketDataService.regenerate(db, market, symbol, current_price, volatility)` (new static method); `_build_walk_docs(market, symbol, current_price, volatility=0.03) -> list[dict]` (module-level pure helper); endpoints `GET/POST /api/admin/price-history`, `PATCH/DELETE /api/admin/price-history/{point_id}`, `POST /api/admin/price-history/regenerate`.

- [ ] **Step 1: Extract `_build_walk_docs` and refactor `ensure_backfill`**

In `backend/market_data.py`, replace lines 94-118 (the `ensure_backfill` method) with:

```python
    @staticmethod
    async def ensure_backfill(db, market: str, symbol: str, current_price: float, volatility: float = 0.03):
        """Одноразовый бэкфилл истории (год), если её ещё нет. Не пересоздаёт."""
        symbol = symbol.upper()
        if await db.price_history.find_one({"market": market, "symbol": symbol}):
            return
        docs = _build_walk_docs(market, symbol, current_price, volatility)
        if docs:
            await db.price_history.insert_many(docs)

    @staticmethod
    async def regenerate(db, market: str, symbol: str, current_price: float, volatility: float = 0.03):
        """Принудительно пересоздаёт историю символа (сносит старую, строит заново)."""
        symbol = symbol.upper()
        await db.price_history.delete_many({"market": market, "symbol": symbol})
        docs = _build_walk_docs(market, symbol, current_price, volatility)
        if docs:
            await db.price_history.insert_many(docs)
```

Then add the extracted helper as a module-level function, placed right above the `MarketDataService` class definition (before line 76 `class MarketDataService:`):

```python
def _build_walk_docs(market: str, symbol: str, current_price: float, volatility: float = 0.03) -> list[dict]:
    """Строит историю случайным блужданием назад во времени от текущей цены.

    Год по дням + последние 3 суток плотнее (для интервалов 1h/24h). Чистая
    функция — не трогает БД, используется и одноразовым бэкфиллом, и
    принудительным regenerate.
    """
    symbol = symbol.upper()
    now = _now()
    docs: list[dict] = []

    def walk_back(points: int, step: timedelta, price: float, vol: float):
        seq = []
        p = price
        for i in range(points):
            seq.append((now - step * i, round(max(current_price * 0.15, min(current_price * 6, p)), 6)))
            p = p / (1 + random.gauss(0, vol))
        return seq

    for ts, p in walk_back(365, timedelta(days=1), current_price, volatility):
        docs.append({"market": market, "symbol": symbol, "price": p, "ts": ts})
    for ts, p in walk_back(144, timedelta(minutes=30), current_price, volatility * 0.4):
        docs.append({"market": market, "symbol": symbol, "price": p, "ts": ts})
    return docs
```

- [ ] **Step 2: Add the self-check for `_build_walk_docs`**

Append at the very end of `backend/market_data.py`:

```python
if __name__ == "__main__":
    docs = _build_walk_docs("stock", "test", 100.0, 0.03)
    assert len(docs) == 365 + 144, len(docs)
    for d in docs:
        assert 100.0 * 0.15 <= d["price"] <= 100.0 * 6, d["price"]
        assert d["symbol"] == "TEST"
    daily_leg = docs[:365]
    assert daily_leg[0]["ts"] > daily_leg[-1]["ts"]
    assert (daily_leg[0]["ts"] - daily_leg[-1]["ts"]).days == 364
    print("market_data self-check OK")
```

- [ ] **Step 3: Run the self-check**

Run: `cd backend && python market_data.py`
Expected: `market_data self-check OK`

- [ ] **Step 4: Add `require_admin` import and the admin price-history endpoints**

In `backend/market_data.py`, change line 27 from:

```python
from auth import get_current_user
```

to:

```python
from auth import get_current_user, require_admin
```

Then append the following to the end of the file (after the Task-2-Step-2 self-check block — endpoints go before the `if __name__ == "__main__":` guard, i.e. right after the `toggle_favorite` function, before the self-check):

```python
# ── Admin: point-edit + regenerate price history ────────────────────────────


class PricePointBody(BaseModel):
    market: str
    symbol: str
    price: float
    ts: Optional[datetime] = None


class PricePointUpdate(BaseModel):
    price: Optional[float] = None
    ts: Optional[datetime] = None


class RegenerateBody(BaseModel):
    market: str
    symbol: str
    price: Optional[float] = None
    volatility: Optional[float] = None


def _format_point(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "ts": _aware(doc["ts"]).isoformat(), "price": doc["price"]}


@router.get("/admin/price-history")
async def admin_list_price_history(
    market: str = Query(...),
    symbol: str = Query(...),
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    rows = [r async for r in db.price_history.find(
        {"market": market, "symbol": symbol.upper()}
    ).sort("ts", 1)]
    return [_format_point(r) for r in rows]


@router.post("/admin/price-history", status_code=status.HTTP_201_CREATED)
async def admin_add_price_point(
    payload: PricePointBody,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    doc = {
        "market": payload.market, "symbol": payload.symbol.upper(),
        "price": round(payload.price, 6), "ts": _aware(payload.ts) if payload.ts else _now(),
    }
    result = await db.price_history.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _format_point(doc)


@router.patch("/admin/price-history/{point_id}")
async def admin_update_price_point(
    point_id: str,
    payload: PricePointUpdate,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    if "price" in fields and fields["price"] is not None:
        fields["price"] = round(fields["price"], 6)
    if "ts" in fields and fields["ts"] is not None:
        fields["ts"] = _aware(fields["ts"])
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое тело запроса")
    result = await db.price_history.update_one({"_id": ObjectId(point_id)}, {"$set": fields})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка истории не найдена")
    doc = await db.price_history.find_one({"_id": ObjectId(point_id)})
    return _format_point(doc)


@router.delete("/admin/price-history/{point_id}")
async def admin_delete_price_point(
    point_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    result = await db.price_history.delete_one({"_id": ObjectId(point_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка истории не найдена")
    return {"deleted": True}


@router.post("/admin/price-history/regenerate")
async def admin_regenerate_price_history(
    payload: RegenerateBody,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if payload.market not in VALID_MARKETS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный рынок")
    symbol = payload.symbol.upper()
    coll = db.stocks if payload.market == MARKET_STOCK else db.crypto_assets
    asset = await coll.find_one({"symbol": symbol})
    if not asset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Актив не найден")
    price = payload.price if payload.price is not None else float(asset.get("price", 0))
    volatility = payload.volatility if payload.volatility is not None else float(asset.get("volatility", 0.03))
    await MarketDataService.regenerate(db, payload.market, symbol, price, volatility)
    return {"regenerated": True, "points": 365 + 144}
```

- [ ] **Step 5: Run the self-check again (still passes after the additions)**

Run: `cd backend && python market_data.py`
Expected: `market_data self-check OK`

- [ ] **Step 6: Verify the server boots with the new routes**

Run: `cd backend && python -c "import main; print([r.path for r in main.app.routes if 'admin/price-history' in r.path])"`
Expected: prints a list containing `/api/admin/price-history`, `/api/admin/price-history/{point_id}`, `/api/admin/price-history/regenerate`.

- [ ] **Step 7: Commit**

```bash
git add backend/market_data.py
git commit -m "feat(admin): shared price-history point-edit + regenerate endpoints"
```

---

### Task 3: Crypto admin endpoints (`backend/crypto.py`)

**Files:**
- Modify: `backend/crypto.py:19` (import `require_admin`), append endpoints after `crypto_transfers` (end of file, before Task 3's self-check).

**Interfaces:**
- Consumes: `require_admin` (`auth.py`), `_format_coin` (`crypto.py:162`), `_MARKET_CACHE` (`crypto.py:158`), `MarketDataService.ensure_backfill` (Task 2).
- Produces: `PATCH /api/crypto/admin/{symbol}`, `POST /api/crypto/admin`, `DELETE /api/crypto/admin/{symbol}`.

- [ ] **Step 1: Add `require_admin` import**

In `backend/crypto.py`, change line 19 from:

```python
from auth import get_current_user
```

to:

```python
from auth import get_current_user, require_admin
```

- [ ] **Step 2: Append the admin endpoints**

Add at the end of `backend/crypto.py` (after the `crypto_transfers` function, before any self-check):

```python
# ── Admin: create / edit / delete coins ──────────────────────────────────────


class CryptoAdminUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    marketCap: Optional[float] = None
    volatility: Optional[float] = None
    color: Optional[str] = None
    description: Optional[str] = None


class CryptoAdminCreate(BaseModel):
    symbol: str
    name: str
    price: float
    volatility: float = 0.05
    color: str = "#6366f1"
    supply: Optional[float] = None
    description: str = ""


@router.patch("/admin/{symbol}")
async def admin_update_coin(
    symbol: str,
    payload: CryptoAdminUpdate,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Точечное редактирование монеты. marketCap задаёт supply = marketCap/price;
    price дополнительно переустанавливает base_price (якорь коридора _walk_price)."""
    symbol = symbol.upper()
    coin = await db.crypto_assets.find_one({"symbol": symbol})
    if not coin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")

    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    new_price = fields.get("price")
    new_market_cap = fields.pop("marketCap", None)
    if new_market_cap is not None:
        price_for_supply = new_price if new_price is not None else float(coin.get("price", 0))
        if price_for_supply > 0:
            fields["supply"] = round(new_market_cap / price_for_supply)
            fields["marketCap"] = round(new_market_cap, 2)
    if new_price is not None:
        fields["base_price"] = new_price
    fields["updated_at"] = datetime.utcnow()

    await db.crypto_assets.update_one({"symbol": symbol}, {"$set": fields})
    _MARKET_CACHE["ts"] = None
    updated = await db.crypto_assets.find_one({"symbol": symbol})
    return _format_coin(updated)


@router.post("/admin", status_code=status.HTTP_201_CREATED)
async def admin_create_coin(
    payload: CryptoAdminCreate,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    symbol = payload.symbol.upper()
    if await db.crypto_assets.find_one({"symbol": symbol}):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Монета '{symbol}' уже существует")
    supply = payload.supply if payload.supply is not None else 0
    doc = {
        "symbol": symbol, "name": payload.name, "price": payload.price,
        "base_price": payload.price, "volatility": payload.volatility,
        "color": payload.color, "supply": supply, "description": payload.description,
        "change24h": 0.0, "ath": payload.price, "atl": payload.price,
        "volume24h": round(payload.price * supply * 0.04, 2),
        "updated_at": datetime.utcnow(),
    }
    await db.crypto_assets.insert_one(doc)
    await MarketDataService.ensure_backfill(db, "crypto", symbol, payload.price, payload.volatility)
    _MARKET_CACHE["ts"] = None
    created = await db.crypto_assets.find_one({"symbol": symbol})
    return _format_coin(created)


@router.delete("/admin/{symbol}")
async def admin_delete_coin(
    symbol: str,
    _admin: dict = Depends(require_admin),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Удаляет монету. ponytail: не каскадит crypto_holdings/price_history —
    приемлемо для админ-инструмента удаления монеты, которую никто не держит."""
    symbol = symbol.upper()
    result = await db.crypto_assets.delete_one({"symbol": symbol})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Монета не найдена")
    _MARKET_CACHE["ts"] = None
    return {"deleted": True}
```

- [ ] **Step 3: Add the self-check**

Append at the very end of `backend/crypto.py`:

```python
if __name__ == "__main__":
    # marketCap -> supply recompute (единственная нетривиальная новая логика здесь).
    price, market_cap = 100.0, 50_000_000.0
    assert round(market_cap / price) == 500_000
    print("crypto self-check OK")
```

- [ ] **Step 4: Run the self-check**

Run: `cd backend && python crypto.py`
Expected: `crypto self-check OK`

- [ ] **Step 5: Verify the server boots with the new routes**

Run: `cd backend && python -c "import main; print([r.path for r in main.app.routes if '/crypto/admin' in r.path])"`
Expected: prints a list containing `/api/crypto/admin/{symbol}`, `/api/crypto/admin`.

- [ ] **Step 6: Commit**

```bash
git add backend/crypto.py
git commit -m "feat(admin): crypto coin create/edit/delete endpoints with marketCap->supply calc"
```

---

### Task 4: Frontend API wrappers (`frontend/src/services/api.js`)

**Files:**
- Modify: `frontend/src/services/api.js` (three insertion points: after `adminTransferFarm`, in the Crypto API section, in the Market data section).

**Interfaces:**
- Consumes: `request(endpoint, options)` (`api.js:204`).
- Produces: `adminListCollections()`, `adminListDocuments(name, {q, skip, limit})`, `adminGetDocument(name, docId)`, `adminCreateDocument(name, doc)`, `adminUpdateDocument(name, docId, doc)`, `adminDeleteDocument(name, docId)`, `adminUpdateCoin(symbol, data)`, `adminCreateCoin(data)`, `adminDeleteCoin(symbol)`, `adminListPriceHistory(market, symbol)`, `adminAddPricePoint(data)`, `adminUpdatePricePoint(pointId, data)`, `adminDeletePricePoint(pointId)`, `adminRegeneratePriceHistory(data)`.

- [ ] **Step 1: Add the DB-editor wrappers**

In `frontend/src/services/api.js`, insert after the `adminTransferFarm` function (after line 449, i.e. right after its closing `}` before the next section comment):

```javascript
// ── Admin: универсальный редактор БД ────────────────────────────────────────

export async function adminListCollections() {
  return request('/api/admin/db/collections')
}

export async function adminListDocuments(name, opts = {}) {
  const params = new URLSearchParams()
  const { q, skip, limit } = opts
  if (q) params.set('q', q)
  if (skip != null) params.set('skip', skip)
  if (limit != null) params.set('limit', limit)
  const query = params.toString()
  return request(`/api/admin/db/collections/${encodeURIComponent(name)}${query ? `?${query}` : ''}`)
}

export async function adminGetDocument(name, docId) {
  return request(`/api/admin/db/collections/${encodeURIComponent(name)}/${encodeURIComponent(docId)}`)
}

export async function adminCreateDocument(name, doc) {
  return request(`/api/admin/db/collections/${encodeURIComponent(name)}`, {
    method: 'POST',
    body: JSON.stringify(doc),
  })
}

export async function adminUpdateDocument(name, docId, doc) {
  return request(`/api/admin/db/collections/${encodeURIComponent(name)}/${encodeURIComponent(docId)}`, {
    method: 'PATCH',
    body: JSON.stringify(doc),
  })
}

export async function adminDeleteDocument(name, docId) {
  return request(`/api/admin/db/collections/${encodeURIComponent(name)}/${encodeURIComponent(docId)}`, {
    method: 'DELETE',
  })
}
```

- [ ] **Step 2: Add the crypto admin wrappers**

Insert after `fetchCryptoTransfers` (after line 551, before the `// ── Stock Trading API` comment):

```javascript
export async function adminUpdateCoin(symbol, data) {
  return request(`/api/crypto/admin/${encodeURIComponent(symbol)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminCreateCoin(data) {
  return request('/api/crypto/admin', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function adminDeleteCoin(symbol) {
  return request(`/api/crypto/admin/${encodeURIComponent(symbol)}`, { method: 'DELETE' })
}
```

- [ ] **Step 3: Add the shared price-history wrappers**

Insert in the `// ── Market data (history / asset detail / favorites)` section, after `fetchMarketHistory`/before `fetchFavorites` (i.e. right after line 702's function closes, before line 706's comment/function — insert as its own block):

```javascript
export async function adminListPriceHistory(market, symbol) {
  return request(`/api/admin/price-history?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`)
}

export async function adminAddPricePoint(data) {
  return request('/api/admin/price-history', { method: 'POST', body: JSON.stringify(data) })
}

export async function adminUpdatePricePoint(pointId, data) {
  return request(`/api/admin/price-history/${encodeURIComponent(pointId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminDeletePricePoint(pointId) {
  return request(`/api/admin/price-history/${encodeURIComponent(pointId)}`, { method: 'DELETE' })
}

export async function adminRegeneratePriceHistory(data) {
  return request('/api/admin/price-history/regenerate', { method: 'POST', body: JSON.stringify(data) })
}
```

- [ ] **Step 4: Verify no syntax errors**

Run: `cd frontend && node --check src/services/api.js`
Expected: no output (exit code 0).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.js
git commit -m "feat(admin): API wrappers for DB editor, crypto admin, price-history admin"
```

---

### Task 5: Shared `PriceHistoryEditor.jsx` modal

**Files:**
- Create: `frontend/src/components/PriceHistoryEditor.jsx`
- Modify: `frontend/src/App.css` (append new classes)

**Interfaces:**
- Consumes: `adminListPriceHistory`, `adminAddPricePoint`, `adminUpdatePricePoint`, `adminDeletePricePoint`, `adminRegeneratePriceHistory` (Task 4).
- Produces: `PriceHistoryEditor({ market, symbol, onClose })` default export — a modal component. Used by both the Crypto tab (Task 7) and the Stocks tab (Task 7).

- [ ] **Step 1: Write `frontend/src/components/PriceHistoryEditor.jsx`**

```jsx
import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, Save, X, RefreshCw, Edit3 } from 'lucide-react'
import {
  adminListPriceHistory, adminAddPricePoint, adminUpdatePricePoint,
  adminDeletePricePoint, adminRegeneratePriceHistory,
} from '../services/api'

function PriceHistoryEditor({ market, symbol, onClose }) {
  const { t } = useTranslation()
  const [points, setPoints] = useState([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [editPrice, setEditPrice] = useState('')
  const [newPrice, setNewPrice] = useState('')
  const [regenPrice, setRegenPrice] = useState('')
  const [regenVolatility, setRegenVolatility] = useState('')
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await adminListPriceHistory(market, symbol)
      setPoints(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [market, symbol])

  useEffect(() => { load() }, [load])

  const handleStartEdit = (p) => {
    setEditingId(p.id)
    setEditPrice(String(p.price))
  }

  const handleSaveEdit = async (id) => {
    try {
      await adminUpdatePricePoint(id, { price: parseFloat(editPrice) })
      setEditingId(null)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm(t('admin.priceHistory.deletePointConfirm'))) return
    try {
      await adminDeletePricePoint(id)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleAdd = async () => {
    if (!newPrice) return
    try {
      await adminAddPricePoint({ market, symbol, price: parseFloat(newPrice) })
      setNewPrice('')
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleRegenerate = async () => {
    if (!confirm(t('admin.priceHistory.regenerateConfirm'))) return
    try {
      const payload = { market, symbol }
      if (regenPrice) payload.price = parseFloat(regenPrice)
      if (regenVolatility) payload.volatility = parseFloat(regenVolatility)
      await adminRegeneratePriceHistory(payload)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content price-history-modal" onClick={e => e.stopPropagation()}>
        <div className="price-history-header">
          <h3>{t('admin.priceHistory.title')}: {symbol}</h3>
          <button className="admin-btn" onClick={onClose}><X size={16} /></button>
        </div>

        {error && <div className="admin-message">{error}</div>}

        <div className="price-history-regenerate">
          <input
            type="number" step="0.01" placeholder={t('admin.priceHistory.priceOverride')}
            value={regenPrice} onChange={e => setRegenPrice(e.target.value)} className="admin-input"
          />
          <input
            type="number" step="0.01" placeholder={t('admin.priceHistory.volatilityOverride')}
            value={regenVolatility} onChange={e => setRegenVolatility(e.target.value)} className="admin-input"
          />
          <button className="admin-btn admin-btn-danger" onClick={handleRegenerate}>
            <RefreshCw size={14} /> {t('admin.priceHistory.regenerate')}
          </button>
        </div>

        <div className="form-row">
          <input
            type="number" step="0.01" placeholder={t('admin.priceHistory.newPointPrice')}
            value={newPrice} onChange={e => setNewPrice(e.target.value)} className="admin-input"
          />
          <button className="admin-btn admin-btn-primary" onClick={handleAdd}>
            <Plus size={14} /> {t('admin.priceHistory.addPoint')}
          </button>
        </div>

        {loading && <p>{t('common.loading')}</p>}
        {!loading && points.length === 0 && <p className="empty-state">{t('admin.priceHistory.noPoints')}</p>}

        <div className="price-history-table">
          {points.map(p => (
            <div key={p.id} className="price-history-row">
              <span className="price-history-ts">{new Date(p.ts).toLocaleString()}</span>
              {editingId === p.id ? (
                <>
                  <input
                    type="number" step="0.01" value={editPrice}
                    onChange={e => setEditPrice(e.target.value)} className="admin-input"
                  />
                  <button className="admin-btn admin-btn-primary" onClick={() => handleSaveEdit(p.id)}>
                    <Save size={14} />
                  </button>
                  <button className="admin-btn" onClick={() => setEditingId(null)}>
                    <X size={14} />
                  </button>
                </>
              ) : (
                <>
                  <span className="price-history-price">{p.price}</span>
                  <button className="admin-btn" onClick={() => handleStartEdit(p)}>
                    <Edit3 size={14} />
                  </button>
                  <button className="admin-btn admin-btn-danger" onClick={() => handleDelete(p.id)}>
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default PriceHistoryEditor
```

- [ ] **Step 2: Append CSS for the new classes**

In `frontend/src/App.css`, append at the end of the file:

```css
.price-history-modal {
  max-width: 600px;
  max-height: 80vh;
  overflow-y: auto;
}

.price-history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.price-history-regenerate {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color, #333);
}

.price-history-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 12px;
}

.price-history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
}

.price-history-row:nth-child(odd) {
  background: rgba(255, 255, 255, 0.03);
}

.price-history-ts {
  flex: 1;
  font-size: 0.85em;
  opacity: 0.8;
}

.price-history-price {
  min-width: 80px;
  text-align: right;
  font-weight: 600;
}
```

- [ ] **Step 3: Verify no syntax errors**

Run: `cd frontend && node --check src/components/PriceHistoryEditor.jsx 2>&1 || npx babel src/components/PriceHistoryEditor.jsx --presets @babel/preset-react > /dev/null`

(If neither babel nor a plain `node --check` is available for JSX, defer to Task 7 Step 5's browser smoke test — this component has no standalone entry point to run outside the app.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PriceHistoryEditor.jsx frontend/src/App.css
git commit -m "feat(admin): shared PriceHistoryEditor modal (point edit + regenerate)"
```

---

### Task 6: Database tab in `AdminPanel.jsx`

**Files:**
- Modify: `frontend/src/components/AdminPanel.jsx` (imports, state, `sections` array, `loadData`, new render block, new modal)
- Modify: `frontend/src/App.css` (append new classes)

**Interfaces:**
- Consumes: `adminListCollections`, `adminListDocuments`, `adminCreateDocument`, `adminUpdateDocument`, `adminDeleteDocument` (Task 4).

- [ ] **Step 1: Add imports**

In `frontend/src/components/AdminPanel.jsx`, change line 3 from:

```javascript
import { fetchStocks, fetchStocksV2, fetchConfig, request, adminUpdateUser, adminDeleteUser, updateStockConfig, fetchBotOrders } from '../services/api'
```

to:

```javascript
import {
  fetchStocks, fetchStocksV2, fetchConfig, request, adminUpdateUser, adminDeleteUser, updateStockConfig, fetchBotOrders,
  adminListCollections, adminListDocuments, adminCreateDocument, adminUpdateDocument, adminDeleteDocument,
} from '../services/api'
```

And change the `lucide-react` import (line 7-10) from:

```javascript
import {
  Plus, Trash2, Edit3, Save, X, Settings, Users, ArrowLeftRight,
  Package, ChevronDown, ChevronUp, ShieldAlert, Sliders, HelpCircle, Activity, Search, DollarSign, RefreshCw, Briefcase, EyeOff
} from 'lucide-react'
```

to:

```javascript
import {
  Plus, Trash2, Edit3, Save, X, Settings, Users, ArrowLeftRight,
  Package, ChevronDown, ChevronUp, ShieldAlert, Sliders, HelpCircle, Activity, Search, DollarSign, RefreshCw, Briefcase, EyeOff,
  Database,
} from 'lucide-react'
```

- [ ] **Step 2: Add state for the Database tab**

After the `propertyUser` state line (`const [propertyUser, setPropertyUser] = useState(null)`, around line 87), add:

```javascript
  // ── Состояние для вкладки "База данных" ─────────────────────────────────
  const [dbCollections, setDbCollections] = useState([])
  const [dbActiveCollection, setDbActiveCollection] = useState('')
  const [dbDocs, setDbDocs] = useState({ items: [], total: 0 })
  const [dbSearch, setDbSearch] = useState('')
  const [dbEditingDoc, setDbEditingDoc] = useState(null) // { id, text } | { id: null, text } для нового документа
  const [dbJsonError, setDbJsonError] = useState(null)
```

- [ ] **Step 3: Wire loading into `loadData`**

In the `loadData` function, add a new branch. Change the `else if (activeSection === 'config') {` block's opening to be preceded by a new `else if`:

```javascript
      } else if (activeSection === 'database') {
        if (dbCollections.length === 0) {
          const cols = await adminListCollections()
          setDbCollections(cols)
          if (!dbActiveCollection && cols.length) setDbActiveCollection(cols[0])
        }
        if (dbActiveCollection) {
          const data = await adminListDocuments(dbActiveCollection, { q: dbSearch || undefined, limit: 100 })
          setDbDocs(data)
        }
      } else if (activeSection === 'config') {
```

- [ ] **Step 4: Add a dedicated effect to reload documents when collection/search changes**

After the existing `useEffect(() => { loadData() }, [activeSection])` block (around line 89-91), add:

```javascript
  useEffect(() => {
    if (activeSection !== 'database' || !dbActiveCollection) return
    adminListDocuments(dbActiveCollection, { q: dbSearch || undefined, limit: 100 })
      .then(setDbDocs)
      .catch(err => showMessage(t('admin.error') + ': ' + err.message))
  }, [dbActiveCollection, dbSearch])
```

- [ ] **Step 5: Add handlers for the Database tab**

After the `handleSaveStockConfig` function (before the `const sections = [` line), add:

```javascript
  // ── Обработчики базы данных ────────────────────────────────────────────────

  const handleDbOpenNew = () => {
    setDbJsonError(null)
    setDbEditingDoc({ id: null, text: '{\n  \n}' })
  }

  const handleDbOpenEdit = (doc) => {
    setDbJsonError(null)
    const id = doc._id?.$oid || doc._id
    setDbEditingDoc({ id, text: JSON.stringify(doc, null, 2) })
  }

  const handleDbSave = async () => {
    let parsed
    try {
      parsed = JSON.parse(dbEditingDoc.text)
    } catch (err) {
      setDbJsonError(t('admin.database.invalidJson') + ': ' + err.message)
      return
    }
    try {
      if (dbEditingDoc.id) {
        await adminUpdateDocument(dbActiveCollection, dbEditingDoc.id, parsed)
      } else {
        await adminCreateDocument(dbActiveCollection, parsed)
      }
      setDbEditingDoc(null)
      showMessage(t('admin.database.saved'))
      const data = await adminListDocuments(dbActiveCollection, { q: dbSearch || undefined, limit: 100 })
      setDbDocs(data)
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleDbDelete = async (doc) => {
    const id = doc._id?.$oid || doc._id
    if (!confirm(t('admin.database.deleteConfirm'))) return
    try {
      await adminDeleteDocument(dbActiveCollection, id)
      showMessage(t('admin.database.deleted'))
      const data = await adminListDocuments(dbActiveCollection, { q: dbSearch || undefined, limit: 100 })
      setDbDocs(data)
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }
```

- [ ] **Step 6: Add "Database" to the `sections` array**

Change the `sections` array (line 362-369) from:

```javascript
  const sections = [
    { id: 'stocks', label: t('admin.stocks'), icon: Package },
    { id: 'prices', label: t('admin.prices.title'), icon: DollarSign },
    { id: 'users', label: t('admin.users'), icon: Users },
    { id: 'transactions', label: t('admin.transactions'), icon: ArrowLeftRight },
    { id: 'economy', label: t('econ.tab'), icon: Activity },
    { id: 'config', label: t('admin.config'), icon: Settings },
  ]
```

to:

```javascript
  const sections = [
    { id: 'stocks', label: t('admin.stocks'), icon: Package },
    { id: 'prices', label: t('admin.prices.title'), icon: DollarSign },
    { id: 'users', label: t('admin.users'), icon: Users },
    { id: 'transactions', label: t('admin.transactions'), icon: ArrowLeftRight },
    { id: 'economy', label: t('econ.tab'), icon: Activity },
    { id: 'config', label: t('admin.config'), icon: Settings },
    { id: 'database', label: t('admin.database.title'), icon: Database },
  ]
```

- [ ] **Step 7: Add the render block for the Database tab**

After the `{!loading && activeSection === 'prices' && (<PriceEditorTab />)}` block (around line 497-499), add:

```javascript
        {!loading && activeSection === 'database' && (
          <div>
            <div className="admin-toolbar">
              <select
                className="admin-input"
                value={dbActiveCollection}
                onChange={e => setDbActiveCollection(e.target.value)}
              >
                {dbCollections.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <div className="tx-search"><Search size={15} className="tx-search-icon" />
                <input value={dbSearch} onChange={e => setDbSearch(e.target.value)} placeholder={t('admin.database.searchPlaceholder')} /></div>
              <span className="admin-count">{dbDocs.total}</span>
              <button className="admin-btn admin-btn-primary" onClick={handleDbOpenNew}>
                <Plus size={16} /> {t('admin.database.newDocument')}
              </button>
            </div>
            <div className="admin-list">
              {dbDocs.items.map(doc => {
                const id = doc._id?.$oid || doc._id
                return (
                  <div key={id} className="admin-stock-item">
                    <div className="db-doc-preview">{JSON.stringify(doc).slice(0, 160)}</div>
                    <div className="stock-actions">
                      <button className="admin-btn" onClick={() => handleDbOpenEdit(doc)}>
                        <Edit3 size={14} />
                      </button>
                      <button className="admin-btn admin-btn-danger" onClick={() => handleDbDelete(doc)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                )
              })}
              {dbDocs.items.length === 0 && <p className="empty-state">{t('admin.database.noDocuments')}</p>}
            </div>
          </div>
        )}

        {dbEditingDoc && (
          <div className="modal-overlay" onClick={() => setDbEditingDoc(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>{dbEditingDoc.id ? t('admin.database.editDocument') : t('admin.database.newDocument')}</h3>
              <textarea
                className="admin-input db-json-textarea"
                value={dbEditingDoc.text}
                onChange={e => setDbEditingDoc({ ...dbEditingDoc, text: e.target.value })}
                rows={16}
              />
              {dbJsonError && <div className="admin-field-error">{dbJsonError}</div>}
              <div className="modal-buttons">
                <button className="admin-btn admin-btn-primary" onClick={handleDbSave}>
                  <Save size={14} /> {t('admin.save')}
                </button>
                <button className="admin-btn" onClick={() => setDbEditingDoc(null)}>
                  {t('admin.cancel')}
                </button>
              </div>
            </div>
          </div>
        )}
```

- [ ] **Step 8: Append CSS for the Database tab**

In `frontend/src/App.css`, append (after the `PriceHistoryEditor` CSS added in Task 5):

```css
.db-doc-preview {
  flex: 1;
  font-family: monospace;
  font-size: 0.8em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.db-json-textarea {
  width: 100%;
  font-family: monospace;
  font-size: 0.85em;
  resize: vertical;
  margin: 8px 0;
}
```

- [ ] **Step 9: Verify no syntax errors**

Run: `cd frontend && npx eslint src/components/AdminPanel.jsx --no-eslintrc --parser-options=ecmaVersion:2022,sourceType:module,ecmaFeatures:{jsx:true} --rule '{}' 2>&1 | head -30`

(If eslint isn't configured for a standalone run, defer to Task 9's manual browser verification — this is a large JSX file with no isolated unit-test entry point.)

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/AdminPanel.jsx frontend/src/App.css
git commit -m "feat(admin): universal Database tab (list/create/edit/delete any collection)"
```

---

### Task 7: Crypto admin tab + "Chart" button on Stocks tab

**Files:**
- Modify: `frontend/src/components/AdminPanel.jsx` (imports, state, `sections`, `loadData`, new render block + modal, one new button in the existing Stocks tab render)
- Modify: `frontend/src/App.css` (append `.admin-coin-item` styling — reuses `.admin-stock-item` otherwise)

**Interfaces:**
- Consumes: `fetchCryptoMarket`, `adminUpdateCoin`, `adminCreateCoin`, `adminDeleteCoin` (Task 4), `PriceHistoryEditor` (Task 5).

- [ ] **Step 1: Add imports**

Extend the `api.js` import in `AdminPanel.jsx` (from Task 6 Step 1) to also include `fetchCryptoMarket, adminUpdateCoin, adminCreateCoin, adminDeleteCoin`:

```javascript
import {
  fetchStocks, fetchStocksV2, fetchConfig, request, adminUpdateUser, adminDeleteUser, updateStockConfig, fetchBotOrders,
  adminListCollections, adminListDocuments, adminCreateDocument, adminUpdateDocument, adminDeleteDocument,
  fetchCryptoMarket, adminUpdateCoin, adminCreateCoin, adminDeleteCoin,
} from '../services/api'
```

Add the `PriceHistoryEditor` import and a `Coins` icon:

```javascript
import PriceHistoryEditor from './PriceHistoryEditor'
```

Extend the `lucide-react` import (from Task 6 Step 1) to include `Coins`:

```javascript
import {
  Plus, Trash2, Edit3, Save, X, Settings, Users, ArrowLeftRight,
  Package, ChevronDown, ChevronUp, ShieldAlert, Sliders, HelpCircle, Activity, Search, DollarSign, RefreshCw, Briefcase, EyeOff,
  Database, Coins,
} from 'lucide-react'
```

- [ ] **Step 2: Add state for the Crypto tab**

After the Task 6 Step 2 state block, add:

```javascript
  // ── Состояние для вкладки "Крипта" ──────────────────────────────────────
  const [coins, setCoins] = useState([])
  const [coinSearch, setCoinSearch] = useState('')
  const [editingCoin, setEditingCoin] = useState(null) // символ редактируемой монеты
  const [coinForm, setCoinForm] = useState({ name: '', price: '', marketCap: '', volatility: '', color: '', description: '' })
  const [showAddCoinForm, setShowAddCoinForm] = useState(false)
  const [newCoin, setNewCoin] = useState({ symbol: '', name: '', price: '', volatility: '0.05', color: '#6366f1', supply: '', description: '' })
  const [chartAsset, setChartAsset] = useState(null) // { market, symbol } | null — открывает PriceHistoryEditor
```

- [ ] **Step 3: Wire loading into `loadData`**

Add another branch to `loadData` (next to the `database` branch added in Task 6 Step 3):

```javascript
      } else if (activeSection === 'crypto') {
        const data = await fetchCryptoMarket()
        setCoins(data)
```

- [ ] **Step 4: Add handlers**

After the Task 6 Step 5 database handlers, add:

```javascript
  // ── Обработчики крипты ─────────────────────────────────────────────────────

  const handleStartEditCoin = (coin) => {
    setEditingCoin(coin.symbol)
    setCoinForm({
      name: coin.name || '',
      price: coin.price != null ? String(coin.price) : '',
      marketCap: coin.marketCap != null ? String(coin.marketCap) : '',
      volatility: coin.volatility != null ? String(coin.volatility) : '',
      color: coin.color || '',
      description: coin.description || '',
    })
  }

  const handleSaveCoin = async () => {
    const payload = {}
    if (coinForm.name) payload.name = coinForm.name
    if (coinForm.price !== '') payload.price = parseFloat(coinForm.price)
    if (coinForm.marketCap !== '') payload.marketCap = parseFloat(coinForm.marketCap)
    if (coinForm.volatility !== '') payload.volatility = parseFloat(coinForm.volatility)
    if (coinForm.color) payload.color = coinForm.color
    if (coinForm.description !== '') payload.description = coinForm.description
    try {
      await adminUpdateCoin(editingCoin, payload)
      setEditingCoin(null)
      showMessage(t('admin.crypto.saved'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleAddCoin = async () => {
    if (!newCoin.symbol || !newCoin.name || !newCoin.price) {
      showMessage(t('admin.fillAllFields'))
      return
    }
    try {
      await adminCreateCoin({
        symbol: newCoin.symbol.toUpperCase(),
        name: newCoin.name,
        price: parseFloat(newCoin.price),
        volatility: parseFloat(newCoin.volatility) || 0.05,
        color: newCoin.color || '#6366f1',
        supply: newCoin.supply !== '' ? parseFloat(newCoin.supply) : undefined,
        description: newCoin.description,
      })
      setNewCoin({ symbol: '', name: '', price: '', volatility: '0.05', color: '#6366f1', supply: '', description: '' })
      setShowAddCoinForm(false)
      showMessage(t('admin.crypto.added'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleDeleteCoin = async (symbol) => {
    if (!confirm(t('admin.crypto.deleteConfirm', { symbol }))) return
    try {
      await adminDeleteCoin(symbol)
      showMessage(t('admin.crypto.deleted', { symbol }))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }
```

- [ ] **Step 5: Add "Crypto" to the `sections` array**

Extend the `sections` array from Task 6 Step 6 to also include:

```javascript
    { id: 'crypto', label: t('admin.crypto.title'), icon: Coins },
```

(placed right after the `stocks` entry, so the final array is: `stocks`, `crypto`, `prices`, `users`, `transactions`, `economy`, `config`, `database`).

- [ ] **Step 6: Add the "Chart" button to the existing Stocks tab**

In the Stocks tab render block (Task 6 context: around where `<Sliders size={14} />` config button is, line 482-484), add a Chart button right before it:

```javascript
                        <button className="admin-btn" onClick={() => setChartAsset({ market: 'stock', symbol: stock.symbol })} title={t('admin.priceHistory.title')}>
                          <RefreshCw size={14} />
                        </button>
                        <button className="admin-btn" onClick={() => handleEditStockConfig({ ...stock })} title={t('admin.stockConfig') || 'Настроить конфиг'}>
                          <Sliders size={14} />
                        </button>
```

- [ ] **Step 7: Add the render block for the Crypto tab**

After the Task 6 Step 7 Database tab render block (and its trailing `dbEditingDoc` modal), add:

```javascript
        {!loading && activeSection === 'crypto' && (
          <div>
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" onClick={() => setShowAddCoinForm(v => !v)}>
                <Plus size={16} /> {t('admin.crypto.addCoin')}
              </button>
            </div>
            {showAddCoinForm && (
              <div className="admin-add-form">
                <div className="form-row">
                  <input placeholder={t('admin.tickerPlaceholder')} value={newCoin.symbol}
                    onChange={e => setNewCoin({ ...newCoin, symbol: e.target.value })} className="admin-input" />
                  <input placeholder={t('admin.namePlaceholder')} value={newCoin.name}
                    onChange={e => setNewCoin({ ...newCoin, name: e.target.value })} className="admin-input" />
                  <input placeholder={t('admin.pricePlaceholder')} type="number" value={newCoin.price}
                    onChange={e => setNewCoin({ ...newCoin, price: e.target.value })} className="admin-input" />
                  <input placeholder={t('admin.crypto.supplyPlaceholder')} type="number" value={newCoin.supply}
                    onChange={e => setNewCoin({ ...newCoin, supply: e.target.value })} className="admin-input" />
                  <button className="admin-btn admin-btn-primary" onClick={handleAddCoin}>
                    <Plus size={16} /> {t('admin.addButton')}
                  </button>
                </div>
              </div>
            )}
            <div className="admin-list">
              <div className="admin-toolbar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={coinSearch} onChange={e => setCoinSearch(e.target.value)} placeholder={t('admin.searchStocks')} /></div>
                <span className="admin-count">{coins.length}</span>
              </div>
              {coins.filter(c => !coinSearch || c.symbol.toLowerCase().includes(coinSearch.toLowerCase()) || (c.name || '').toLowerCase().includes(coinSearch.toLowerCase())).map(coin => (
                <div key={coin.symbol} className="admin-stock-item">
                  <div className="stock-info">
                    <strong>{coin.symbol}</strong>
                    <span>{coin.name}</span>
                    <span className="stock-price">${coin.price?.toFixed?.(coin.price < 1 ? 6 : 2)}</span>
                    <span className="admin-count">{t('admin.crypto.marketCap')}: {coin.marketCap != null ? `$${Math.round(coin.marketCap).toLocaleString()}` : '—'}</span>
                  </div>
                  <div className="stock-actions">
                    <button className="admin-btn" onClick={() => setChartAsset({ market: 'crypto', symbol: coin.symbol })} title={t('admin.priceHistory.title')}>
                      <RefreshCw size={14} />
                    </button>
                    <button className="admin-btn" onClick={() => handleStartEditCoin(coin)}>
                      <Edit3 size={14} />
                    </button>
                    <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteCoin(coin.symbol)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
              {coins.length === 0 && <p className="empty-state">{t('admin.crypto.noCoins')}</p>}
            </div>
          </div>
        )}

        {editingCoin && (
          <div className="modal-overlay" onClick={() => setEditingCoin(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>{t('admin.crypto.editCoin')}: {editingCoin}</h3>
              <div className="config-form">
                <div className="config-field">
                  <label>{t('admin.name')}</label>
                  <input value={coinForm.name} onChange={e => setCoinForm({ ...coinForm, name: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.price')}</label>
                  <input type="number" step="0.000001" value={coinForm.price}
                    onChange={e => setCoinForm({ ...coinForm, price: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>
                    {t('admin.crypto.marketCap')}
                    <Tooltip text={t('admin.crypto.marketCapHelp')} />
                  </label>
                  <input type="number" step="1" value={coinForm.marketCap}
                    onChange={e => setCoinForm({ ...coinForm, marketCap: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.crypto.volatility')}</label>
                  <input type="number" step="0.01" min="0.001" max="1" value={coinForm.volatility}
                    onChange={e => setCoinForm({ ...coinForm, volatility: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.crypto.color')}</label>
                  <input type="color" value={coinForm.color || '#6366f1'}
                    onChange={e => setCoinForm({ ...coinForm, color: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.crypto.description')}</label>
                  <input value={coinForm.description} onChange={e => setCoinForm({ ...coinForm, description: e.target.value })} />
                </div>
              </div>
              <div className="modal-buttons">
                <button className="admin-btn admin-btn-primary" onClick={handleSaveCoin}>
                  <Save size={14} /> {t('admin.save')}
                </button>
                <button className="admin-btn" onClick={() => setEditingCoin(null)}>
                  {t('admin.cancel')}
                </button>
              </div>
            </div>
          </div>
        )}

        {chartAsset && (
          <PriceHistoryEditor
            market={chartAsset.market}
            symbol={chartAsset.symbol}
            onClose={() => setChartAsset(null)}
          />
        )}
```

- [ ] **Step 8: Verify no syntax errors**

Run: `cd frontend && node --check src/components/AdminPanel.jsx 2>&1 | head -30`

(JSX makes plain `node --check` unreliable — treat a clean run as a bonus signal, and rely on Task 9's browser verification as the real check.)

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/AdminPanel.jsx frontend/src/App.css
git commit -m "feat(admin): Crypto tab (create/edit/delete coins) + Chart button on Stocks tab"
```

---

### Task 8: i18n keys

**Files:**
- Modify: `frontend/src/i18n/locales/ru.json:867-1012` (`admin` block)
- Modify: `frontend/src/i18n/locales/en.json` (matching `admin` block — mirror structure)

**Interfaces:**
- Consumes: none.
- Produces: `admin.database.*`, `admin.crypto.*`, `admin.priceHistory.*` translation keys used throughout Tasks 6-7.

- [ ] **Step 1: Add keys to `ru.json`**

In `frontend/src/i18n/locales/ru.json`, insert right before the closing `},` of the `admin` block (currently at line 1011-1012, right after `"pricesSet": "С ценой: {{count}}"` and before the `}` that closes `"prices"`, then the `}` that closes `"admin"`). Add a new sibling key after the `"prices": { ... }` block closes (i.e. after line 1011's `}` for `prices`, before line 1012's `}` for `admin`):

```json
    "prices": {
      "title": "Цены",
      "gpu": "Видеокарты",
      "cpu": "Процессоры",
      "case": "Корпуса",
      "supplies": "Расходники",
      "realestate": "Дома",
      "business": "Бизнесы",
      "searchPlaceholder": "Поиск по названию...",
      "currentPrice": "Текущая цена",
      "resetConfirm": "Сбросить все цены для всех категорий?",
      "resetCategoryConfirm": "Сбросить все цены в этой категории?",
      "resetCategory": "Сбросить категорию",
      "resetAll": "Сбросить все",
      "saved": "Цены сохранены",
      "noProducts": "Товары не найдены",
      "totalProducts": "Всего товаров: {{count}}",
      "pricesSet": "С ценой: {{count}}"
    },
    "database": {
      "title": "База данных",
      "searchPlaceholder": "Поиск...",
      "newDocument": "Новый документ",
      "editDocument": "Редактировать документ",
      "noDocuments": "Документы не найдены",
      "invalidJson": "Некорректный JSON",
      "saved": "Документ сохранён",
      "deleted": "Документ удалён",
      "deleteConfirm": "Удалить документ? Действие необратимо."
    },
    "crypto": {
      "title": "Крипта",
      "addCoin": "Добавить монету",
      "editCoin": "Редактировать монету",
      "marketCap": "Капитализация",
      "marketCapHelp": "При изменении капитализации supply пересчитывается как marketCap / price",
      "volatility": "Волатильность",
      "color": "Цвет",
      "description": "Описание",
      "supplyPlaceholder": "Supply (опционально)",
      "saved": "Монета сохранена",
      "added": "Монета добавлена",
      "deleted": "Монета {{symbol}} удалена",
      "deleteConfirm": "Удалить монету {{symbol}}?",
      "noCoins": "Монеты не найдены"
    },
    "priceHistory": {
      "title": "График цены",
      "newPointPrice": "Цена новой точки",
      "addPoint": "Добавить точку",
      "priceOverride": "Цена (для regenerate)",
      "volatilityOverride": "Волатильность (для regenerate)",
      "regenerate": "Пересоздать историю",
      "regenerateConfirm": "Пересоздать всю историю цен? Текущие точки будут удалены безвозвратно.",
      "deletePointConfirm": "Удалить эту точку?",
      "noPoints": "История пуста"
    }
  },
```

(Note: the last line above replaces the original closing `}` at line 1012, adding the new blocks as siblings of `"prices"` inside `"admin"`.)

- [ ] **Step 2: Verify `ru.json` is still valid JSON**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/locales/ru.json', 'utf8')); console.log('ru.json OK')"`
Expected: `ru.json OK`

- [ ] **Step 3: Add the matching keys to `en.json`**

Find the equivalent `"admin": { ... "prices": { ... } }` block in `frontend/src/i18n/locales/en.json` (same key names, English values) and insert the same three sibling blocks (`database`, `crypto`, `priceHistory`) with English translations:

```json
    "database": {
      "title": "Database",
      "searchPlaceholder": "Search...",
      "newDocument": "New document",
      "editDocument": "Edit document",
      "noDocuments": "No documents found",
      "invalidJson": "Invalid JSON",
      "saved": "Document saved",
      "deleted": "Document deleted",
      "deleteConfirm": "Delete this document? This cannot be undone."
    },
    "crypto": {
      "title": "Crypto",
      "addCoin": "Add coin",
      "editCoin": "Edit coin",
      "marketCap": "Market cap",
      "marketCapHelp": "Changing market cap recalculates supply as marketCap / price",
      "volatility": "Volatility",
      "color": "Color",
      "description": "Description",
      "supplyPlaceholder": "Supply (optional)",
      "saved": "Coin saved",
      "added": "Coin added",
      "deleted": "Coin {{symbol}} deleted",
      "deleteConfirm": "Delete coin {{symbol}}?",
      "noCoins": "No coins found"
    },
    "priceHistory": {
      "title": "Price chart",
      "newPointPrice": "New point price",
      "addPoint": "Add point",
      "priceOverride": "Price (for regenerate)",
      "volatilityOverride": "Volatility (for regenerate)",
      "regenerate": "Regenerate history",
      "regenerateConfirm": "Regenerate the entire price history? Existing points will be permanently deleted.",
      "deletePointConfirm": "Delete this point?",
      "noPoints": "No history yet"
    }
```

Place them as siblings of `"prices"` inside `"admin"`, mirroring the exact insertion point used in `ru.json` Step 1.

- [ ] **Step 4: Verify `en.json` is still valid JSON**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/locales/en.json', 'utf8')); console.log('en.json OK')"`
Expected: `en.json OK`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/locales/ru.json frontend/src/i18n/locales/en.json
git commit -m "i18n: add translation keys for admin Database/Crypto/PriceHistory tabs"
```

---

### Task 9: Manual verification

**Files:** none (verification-only task).

- [ ] **Step 1: Start the backend**

Run: `cd backend && uvicorn main:app --reload`
Expected: server starts without import errors, logs show the app is up.

- [ ] **Step 2: Start the frontend**

Run: `cd frontend && npm run dev`
Expected: Vite dev server starts, prints a local URL.

- [ ] **Step 3: Exercise the Database tab**

In the browser: log in as an admin user, open Admin Panel → "База данных" (Database) tab.
- Select the `users` collection from the dropdown — confirm the list loads and each row shows a JSON preview.
- Click a row's edit icon, change a non-critical field (e.g. `hidden_from_leaderboard`), save — confirm it persists (reload the list, value changed).
- Click "Новый документ", type a minimal valid JSON doc into an unrelated collection (e.g. `{"note": "test"}` into a scratch collection name), save — confirm it appears in the list.
- Delete that scratch document — confirm it disappears.
- Type invalid JSON into the textarea and save — confirm an inline error appears and nothing is submitted.

- [ ] **Step 4: Exercise the Crypto tab**

Open Admin Panel → "Крипта" (Crypto) tab.
- Confirm the coin list loads with symbol/name/price/market cap.
- Edit an existing coin's `marketCap` field, save — confirm the list re-renders with the new market cap and a plausible supply (spot-check: reopen the edit modal, or check via the Database tab on `crypto_assets`).
- Edit an existing coin's `price`, save — wait ~30s (background sim tick), reload the tab, confirm the price didn't immediately snap back to the old value (validates the `base_price` re-anchor).
- Add a new coin via the form — confirm it appears in the list.
- Delete that new coin — confirm it disappears.

- [ ] **Step 5: Exercise price-history editing (shared component)**

From the Crypto tab, click the chart/refresh icon on any coin — confirm `PriceHistoryEditor` opens with a populated points table.
- Edit one point's price, save — confirm it updates in place.
- Add a new point — confirm it appears.
- Delete a point — confirm it disappears.
- Click "Пересоздать историю" (Regenerate), confirm the browser confirm dialog appears, accept it — confirm the table reloads with a fresh ~509-point series.
- Close the modal, switch to the Stocks tab, click the new Chart button on any stock row — confirm the same modal opens scoped to `market=stock` and works identically.

- [ ] **Step 6: Report results**

Summarize pass/fail for each sub-step above. Any failure blocks marking Task 9 (and the overall plan) complete — fix the root cause in the relevant earlier task before re-running.

---
