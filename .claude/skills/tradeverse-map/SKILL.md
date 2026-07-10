---
name: tradeverse-map
description: Orientation map of the TradeVerse codebase (FastAPI + Motor/MongoDB backend, React 18 + Vite frontend — an economic-war browser game). Lists every backend router and frontend component with what it owns, the core cross-cutting patterns (ledger, econ coefficients, scheduler, WebSocket realtime, activeTab routing), and known dead/legacy code. Use this skill immediately at the start of ANY task in the TradeVerse project — bug fixes, new features, "where is X", "how does Y work", "add a field to Z" — instead of exploring blindly with grep/glob first. Always consult this before searching the codebase for functionality in this repo.
---

# TradeVerse Project Map

TradeVerse is an economic-war browser game. Backend: FastAPI + Motor (async MongoDB driver), JWT auth, Pydantic v2. Frontend: React 18 + Vite, no router — a single `activeTab` state switch. i18n: RU/EN only (`react-i18next`).

This map exists so a session can go straight to the right file instead of re-discovering the architecture from scratch. It's maintained by hand — if you make a structural change (new router, new tab, a file's purpose changes), update the relevant section below in the same session.

## Standing project constraint

> Не создавай временных решений, заглушек или hardcode там, где должна быть полноценная логика. Все изменения должны быть интегрированы в существующую архитектуру.

Every module below already follows this: money always flows through `ledger.py`, coefficients always come from `econ.py`, background work always runs through the single `scheduler.py` loop. New work should plug into these, not bypass them.

## Backend — `backend/*.py`

One `APIRouter` per feature, each included in `main.py` (see include order there if load-order ever matters). Every router file has a module docstring — `head -20 backend/<file>.py` for the full rationale.

| File | Router prefix | Owns |
|---|---|---|
| `main.py` | — | App wiring: `include_router` calls, `register_user`/`login_user`/`get_me`, lifespan (starts `scheduler.py`), leaderboard aggregation |
| `auth.py` | — | JWT issue/verify, `get_current_user` dependency (always re-fetches the user fresh from Mongo by JWT `sub` — never trusts stale claims) |
| `database.py` | — | Motor client/db singleton, `.env` loading |
| `models.py` | — | Pydantic `UserDocument` (Mongo shape) |
| `schemas.py` | — | Request/response Pydantic schemas + validators (username, password, avatar data-URL regex) |
| `ledger.py` | — | **Single source of truth for money.** `record_transaction`/`adjust_balance` — every economic module routes through this, giving one unified transaction history |
| `econ.py` | `/api/admin/economy` | `get_econ(db)` — the one place that reads tunable economy coefficients (rent %, income multipliers, WarCoin rates); everything else (assets, mining, company, crypto) reads coefficients through this, never hardcodes them. Also the admin analytics endpoint |
| `market_events.py` | `/api/admin/economy` | World economic events — temporarily shift industry target prices/coefficients; feed into `assets.py`'s market drift and rent/income calcs |
| `scheduler.py` | — | **Single background asyncio loop** (not one loop per subsystem) — ticks: real market refresh, asset market drift + events, rent payouts, mining, etc. |
| `economy.py` | `/api` | Player-to-player transfers, transaction history/analytics |
| `assets.py` | `/api/assets` | Real estate / business / car catalog, purchase, upgrade, rent. Rent formula is rarity-tiered (`RARITY_RENT_PCT`/`RARITY_RENT_FLOOR`) — NOT a flat rate; see `_rent_daily_rate`/`_current_value` |
| `company.py` | `/api/company` | Player companies: create, invite (consent-based), salaries, budget, disband, leave. `_serialize()` batch-fetches live username/avatar from `db.users` so member info never goes stale |
| `cityroof.py` | `/api/cityroof` | Weekly PvP map event — capture businesses via a guess-the-secret mini-game, costs WarCoin |
| `crypto.py` | `/api/crypto` | Crypto account, market (throttled random-walk pricing), wallet, trades |
| `stocks.py` | `/api/v2/stocks` | Stock exchange v2 — price reacts to trade volume (`ΔP = Price × K × Qty/TotalShares`), portfolio, orders |
| `market_data.py` | `/api` | `MarketDataService` — real price history for stocks/crypto (`price_history` collection), one-time backfill then incremental. Powers `PriceChart`/`AssetDetail` on the frontend |
| `providers.py` | — | External real-market data providers: CoinGecko (crypto, no key needed) + Finnhub/TwelveData (stocks, pick one via `.env`) |
| `shop.py` | `/api/shop` | Hardware shop (GPUs etc.) — prices always computed server-side from specs × economy multiplier, never static/null |
| `mining.py` | `/api/mining` | Mining farms — real crypto rates (via `market_data`/`crypto`), hardware wear, electricity cost (via `econ`), AI managers, auto-coin selection |
| `notifications.py` | `/api/notifications` | `push_notification(...)` — unified notification mechanism, used by company invites, rent payouts, cityroof, etc. |
| `ws.py` | — | WebSocket realtime at `/ws?token=<JWT>`. Pushes balance/notification/market/leaderboard events; frontend polling is the fallback if WS is unavailable |
| `user_profile.py` | `/api/user` | Nickname change, password change, avatar upload/delete (Settings page backend). Avatar stored as a base64 data URL directly on the user doc — no file storage infra in this project |
| `init_db.py` / `check_schema.py` | — | One-off dev scripts, not part of the running app |

## Frontend — `frontend/src/`

No react-router. `App.jsx` owns auth/`user` state (+ `handleUserUpdate`, which merges patches into both React state and `localStorage`) and renders `Dashboard.jsx` once logged in.

**`Dashboard.jsx`** owns `activeTab` and a `renderContent()` switch — this is the routing table:

| tab id | Component | Notes |
|---|---|---|
| `account` | `AccountTab.jsx` | Home/overview, weekly analytics |
| `bank` | `BankTab.jsx` | Deposits/loans |
| `shop` | `ShopTab.jsx` | Hardware shop — fetches `/api/shop` catalog directly, renders its own cards (does **not** use the `*Shop.jsx` family below) |
| `cityroof` | `CityRoofTab.jsx` | Weekly PvP map event UI |
| `crypto` | `CryptoTab.jsx` | Crypto trading |
| `stocks` | `StocksTab.jsx` | Stock exchange v2 |
| `mining` | `MiningTab.jsx` | Mining farms |
| `realestate` | `MarketTab.jsx` | Asset market (realestate/business/car) — fetches `/api/assets/market` directly, own rendering |
| `myhomes` | `MyAssetsTab.jsx` (`defaultType="realestate"`) | Owned assets: collect rent, upgrade, sell, transfer to company, tune car |
| `mybusiness` | `MyAssetsTab.jsx` (`defaultType="business"`) | Same component, business filter. **Not linked from the sidebar's `menuItems`** (pre-existing gap — `mycompany` is the only business-adjacent sidebar link) |
| `mycompany` | `MyCompanyTab.jsx` | Company management: members, invites, salaries, leave/disband |
| `leaderboard` | `LeaderboardTab.jsx` | Net-worth ranking |
| `settings` | `SettingsPage.jsx` | Profile/password/avatar/language — full page, not a modal |

Other always-mounted pieces: `Sidebar.jsx` (nav + `sidebar-footer` settings link), `Header.jsx` (balance, username/avatar button → opens Settings), `NotificationCenter.jsx` (invite/notification popups, driven by the `tv:realtime` WS event bridged in `Dashboard.jsx`), `AdminPanel.jsx` (admin-only FAB modal, hosts `EconomyAdmin.jsx` + `PriceEditorTab.jsx` as sub-sections).

**Detail/shared components:** `AssetDetail.jsx` + `PriceChart.jsx` (asset detail page with canvas price chart), `TransactionsPanel.jsx` (also exports the shared `formatMoney` helper used everywhere), `ProfileCard.jsx`, `ConfirmDialog.jsx` (reusable confirm modal — `open/title/message/confirmLabel/danger/busy/onConfirm/onCancel`), `AuthPage.jsx` (login/register), `AnalyticsChart.jsx`, `BuyModal.jsx`, `ShopCard.jsx`.

**Known dead/legacy code — do not assume these are live UI:** `RealEstateShop.jsx`, `BusinessShop.jsx`, `CaseShop.jsx`, `CpuShop.jsx`, `GpuShop.jsx`, `SuppliesShop.jsx`, and `utils/shopPrices.js` are an older, unmounted component tree — nothing in `Dashboard.jsx` renders them. They survive only because `PriceEditorTab.jsx` imports their exported `*_PRODUCTS` constants (e.g. `GPU_PRODUCTS`) as static catalog data for the admin price editor. The live shop/market UIs are `ShopTab.jsx` and `MarketTab.jsx`, which fetch from the backend directly.

**Infra:**
- `services/api.js` — single API client (fetch wrapper, JWT header, `ApiError`), every backend call goes through here
- `hooks/useApi.js` / `useApiOnMount` — data-fetching hook used by most tabs
- `hooks/useWebSocket.js` — WS connection hook (Dashboard currently wires its own socket manually rather than this hook — check before assuming it's used)
- `utils/assetAnalytics.js` — deterministic client-side analytics for crypto/stocks (no randomness, so numbers don't jitter on re-render)
- `utils/hwName.js` — builds localized hardware product names from `category + specs` client-side (GPU brand names are left untranslated on purpose)
- `i18n/index.js` + `i18n/locales/{ru,en}.json` — RU/EN only (Ukrainian was removed); language persists to `localStorage['language']`
- CSS: `index.css` (design tokens: `--color-*`, `--radius-*`, `--shadow-*`, dark theme), `App.css` (shell/layout/auth), `economy.css` (tab content, cards, leaderboard, company), `settings.css` (Settings page)

## Common task → where to look

| Task involves... | Start here |
|---|---|
| Rent/income numbers for a property/business/car | `backend/assets.py` (`_rent_daily_rate`, `RARITY_RENT_PCT`) |
| A global economy multiplier or admin-tunable coefficient | `backend/econ.py` |
| Anything touching player balance | `backend/ledger.py` (never write balance directly elsewhere) |
| A new background/periodic job | `backend/scheduler.py` — add a tick, don't spawn a new loop |
| Company members, invites, salaries | `backend/company.py` + `frontend/.../MyCompanyTab.jsx` |
| Avatar/nickname/password | `backend/user_profile.py` + `frontend/.../SettingsPage.jsx` |
| A new sidebar tab | `Sidebar.jsx` (`menuItems` + `ICON_MAP`) + `Dashboard.jsx` (`renderContent` switch) |
| A new translated string | Add the key to **both** `i18n/locales/ru.json` and `en.json` |
| Realtime push to the client | `backend/ws.py` → frontend `tv:realtime` window event (see `Dashboard.jsx`'s WS effect) |
| Hardware/shop pricing | `backend/shop.py` (server computes price, never static) |
| Stock/crypto price history/charts | `backend/market_data.py` + `frontend/.../PriceChart.jsx`/`AssetDetail.jsx` |

## Keeping this map current

This file is plain markdown, updated by hand. When a session adds a router, a tab, or changes a file's role in a way that would mislead the next session, edit the relevant table row above before finishing.
