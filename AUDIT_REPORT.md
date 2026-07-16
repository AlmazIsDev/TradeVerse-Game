# TradeVerse — Аудит проекта (Senior Full-Stack + QA + UX + Security)

Дата: 2026-07-16. Метод: чтение кода (backend ~9.1k LOC Python/FastAPI, frontend React/Vite).

---

## BACKEND — экономика, безопасность, API

### CRITICAL

**B1. Бесконечная эмиссия денег через кастомные акции**
- LOCATION: `stocks.py` `issue_stock` (L572–625), `trade_stock` sell (L482–509); `POST /api/v2/stocks/issue`, `/trade`
- PROBLEM: Founder получает 20% (`FOUNDER_SHARE_PCT`) totalShares бесплатно (только $5000 fee). Продажа акций кредитует продавца `adjust_balance(cost)` без контрагента — деньги печатаются из воздуха. Issue дорогой акции → бесплатные founder-акции → продажа за напечатанный кэш.
- IMPACT: Практически бесконечные деньги за $5000. Ломает экономику и лидерборд.
- FIX: Founder-акции не должны свободно продаваться за напечатанный кэш. Пул ликвидности с ограниченным кэшем / брать полную стоимость founder-акций при issue / lock founder-акций. Ограничить market cap (`price × totalShares`).

**B2. Безрисковый арбитраж на своём же price-impact (крипта)**
- LOCATION: `crypto.py` `trade_crypto` (L402–443), `_apply_trade_impact` (L257–291); `POST /api/crypto/trade`
- PROBLEM: Buy исполняется по текущей цене, ПОТОМ impact поднимает цену (до +12% `IMPACT_CAP`). Sell читает новую завышенную цену и печатает кэш ДО применения своего down-impact. Комиссии нет. Цикл buy→sell = безрисковая прибыль.
- IMPACT: Бесконечные деньги циклом; больше капитал → больше % за цикл.
- FIX: Применять impact ДО расчёта цены сделки (покупка в растущую цену, продажа в падающую), либо средняя/пост-impact цена. Добавить комиссию/спред.

### HIGH

**B3. Тот же self-impact арбитраж для акций** — `stocks.py` `trade_stock` (L448–509). Buy по старой цене, потом bump вверх; sell по завышенной, кэш печатается. Комиссии нет. Системные акции ещё и качаются ботами. FIX: impact до цены, комиссия/спред, sell из ограниченного пула.

**B4. Округление до нуля печатает бесплатные монеты** — `crypto.py` buy (L399–419). `total=round(qty*price,2)`; для дорогих монет маленький qty даёт `total=0.0`, `adjust_balance(-0.0)` проходит, а монеты начисляются. Копим бесплатно → продаём. FIX: reject `total<=0`, min-notional, округление вверх до центов.

**B5. Двойная выплата зарплат (гонка)** — `company.py` `collect_profit` (L693–749); `POST /api/company/collect`. Non-atomic read-modify-write `last_tick`: два параллельных запроса читают тот же `last_tick`, оба платят всем сотрудникам. `budget` пишется `$set` из stale-значения → теряет параллельные deposit/withdraw. FIX: атомарный conditional update по `last_tick`; `$inc` для budget.

**B6. Двойной доход с активов компании** — `assets.py` `_load_owned` (L735–741) vs `company_income_per_hour`. `_load_owned` не исключает `companyId`, поэтому после transfer-to-company личный `/collect` всё ещё платит владельцу, И компания зарабатывает тот же актив. FIX: требовать `companyId: None`.

**B7. TOCTOU двойной сбор пассивного дохода** — `assets.py` `_collect_asset_income` (L785–796). Read `_accrued` → set `last_collected`→ credit не атомарны. Параллельные `/collect` дублируют доход. FIX: `find_one_and_update({_id,last_collected:seen},...)`, платить только при match.

### MEDIUM

**B8. Двойная награда за закрытие сезона (гонка)** — `cityroof.py` `_ensure_season` (L297–346) из `GET /api/cityroof/map`. Проверка смены недели и запись `state.week` не атомарны → параллельные `/map` начисляют победителю `WINNER_REWARD_WC` (500 WC) несколько раз. FIX: атомарный `find_one_and_update` по week.

**B9. Асимметрия buy/sell по market multiplier** — `assets.py` `sell_asset`/`_current_value` (L320–324) vs `buy_asset` (L664). Buy по `base*mult`, sell игнорирует mult. При `mult→0.5` купил за 0.5×base, продал за 0.7×base = +40%. FIX: применять mult и к sell.

**B10. Небезопасный дефолт JWT_SECRET** — `auth.py` L27–40. Без env — публичный хардкод-секрет, только warning. Можно подделать JWT. FIX: падать при старте если секрет не задан/дефолтный в prod.

**B11. Admin stock create/update без валидации** — `main.py` `create_or_update_stock` (L380–391). `model_dump()` без bounds на price, без init `free_shares`. FIX: валидация bounds, init полей.

**B12. Crypto transfer без компенсации при сбое** — `crypto.py` `transfer_crypto` (L449–525). Sender debit атомарен, но при сбое credit получателя монеты теряются (нет rollback, в отличие от `economy.py`). Avg-price recompute не атомарен. FIX: компенсация при сбое; `$inc`.

**B13. Смешение $inc/$set для budget** — `company.py` (см. B5). Параллельный withdraw ($inc вниз) + collect ($set) восстанавливает снятое → двойное снятие. FIX: только `$inc`.

### LOW
- **B14** Публичные read-эндпоинты без auth (`/api/stocks`, `/api/leaderboard`, `/api/config/{key}`) — `/config` может раскрывать конфиг. FIX: auth где нужно.
- **B15** Non-atomic install/uninstall железа (`mining.py` L366–443) — дюп/потеря компонентов при гонке. FIX: conditional update по слоту.
- **B16** `pay_dividend` (`stocks.py` L628–673) — вош между альтами, нет cap на holders (perf). FIX: cap/пагинация.
- **B17** Scheduler стартует в каждом worker (`main.py` lifespan L129) — при `--workers N` пассивный доход/майнинг начисляется N раз. FIX: единый leader-процесс/лок.
- **B18** `buy_materials` (`assets.py` L1051) `$set` boost — гонка теряет оплаченный boost. FIX: атомарно.
- **B19** `_format_transaction` (`main.py` L767–776) прямой доступ к ключам → 500 на кривых строках. FIX: `.get`.
- **B20** cityroof `submit_guess` capture (L1015–1051) non-atomic → окно двойной capture-income. FIX: CAS по ownerId.

**Проверено и безопасно:** `ledger.adjust_balance` (атомарный conditional `$inc`, нет отрицательных балансов), ротация refresh-токенов (`find_one_and_delete`), WarCoin spends (`_spend_wc`), holdings debit на sell/transfer (conditional), admin-роуты (`require_admin` перечитывает роль из БД), server-side re-pricing shop/asset/rent, валидаторы reject negative/zero.

---

## FRONTEND — контракт, производительность, UX

### HIGH

**F1. Мёртвый endpoint `/api/shop/purchase(es)` (404)** — `api.js:569-580`, `BuyModal.jsx:31`. `purchaseItem`/`fetchMyPurchases` бьют в несуществующие пути (бэкенд: `/api/shop/buy`). Замаскировано тем, что 6 shop-компонентов не отрисовываются (F2). FIX: перевести на `buyHardware`/`buyAsset` или удалить.

**F2. Мёртвые компоненты — 6 `*Shop` экранов + `BuyModal`** — `BusinessShop/CaseShop/CpuShop/GpuShop/RealEstateShop/SuppliesShop.jsx`, `BuyModal.jsx`. Нигде не рендерятся; используются только их `*_PRODUCTS` константы (в `PriceEditorTab`). ~1500 строк мёртвого кода с битым путём. FIX: вынести таблицы в `utils/shopPrices`, удалить оболочки.

### MEDIUM

**F3. `Sidebar` грузит `sidebar_menu` config, но не использует** — `Sidebar.jsx:24`. `menuConfig`/`loading` не читаются, меню захардкожено. Лишний запрос, admin-правки меню не действуют. FIX: либо драйвить меню из конфига, либо убрать fetch.

**F4. Таб `mybusiness` недостижим из сайдбара** — `Sidebar.jsx:26-38` vs `Dashboard.jsx:147`. Dashboard обрабатывает `mybusiness`, но пункта в меню нет. Целая фича мертва. FIX: добавить пункт меню.

**F5. Крипто `price_tick` обнуляет % изменения на AssetDetail** — `AssetDetail.jsx:78-80`. Читает `changePercent`, а крипта шлёт `change24h` → бейдж мигает «—» при каждой сделке. FIX: `data.changePercent ?? data.change24h`.

**F6. Глобальные WS-бродкасты вызывают рефетч юзера у всех** — `Dashboard.jsx:50-75`. Любое не-`balance` сообщение → `fetchCurrentUser()`. `market_update`/`price_tick`/`leaderboard_update` шлются всем/на каждую сделку → N-кратный fan-out. FIX: синхронизировать только user-scoped типы.

**F7. CityRoofTab перерисовывает всю карту раз в секунду** — `CityRoofTab.jsx:80-84`. `setClockTick` каждую секунду ре-рендерит весь таб ради таймера. FIX: изолированный `<Countdown/>` leaf.

**F8. Слайдер оверклока майнинга — API-запрос + полный reload на каждый кадр перетаскивания** — `MiningTab.jsx:235`. `onChange` шлёт POST+`load()`. FIX: локальный стейт + коммит на `onMouseUp`/debounce.

**F9. `CryptoTab.load()` ставит loading=true на каждый reload → мигание скелетона** — `CryptoTab.jsx:79-94`. После каждой сделки весь таб уходит в скелетон. FIX: флаг `silent` (как в StocksTab/MarketTab).

### LOW
- **F10** `NotificationCenter` (46) — `setTimeout` попапа не чистится при unmount; попапы по `Date.now()` могут дублироваться. FIX: ref+cleanup, дедуп по имени.
- **F11** Дубль `fetchCurrentUser` на маунте (Dashboard + Header + WS sync) — 2-3× запросов. FIX: грузить в Dashboard, отдавать в Header пропсами.
- **F12** Мёртвый `usePriceAnimation` + модульный `Map` в `CryptoTab.jsx:16-41`. FIX: удалить.
- **F13** Company deposit/withdraw без клиентской проверки границ (`MyCompanyTab.jsx:410`). FIX: валидировать против balance/budget.
- **F14** Проглоченные ошибки на sync-путях (`MyCompanyTab:47`, `CryptoTab:89`, `CityRoofTab:71`, `Header`) — сеть-блип показывает онбординг вместо ошибки. FIX: отличать 404 от прочих.
- **F15** Инлайн-хексы вместо токенов (`StocksTab:195`, `CryptoTab:235` `#0071e3`; `BuyModal:94` `#ef4444`); дублированный `RARITY_GRAD` в MarketTab/MyAssetsTab. FIX: токены + общий `utils/assetVisuals`.
- **F16** Мёртвый API-surface: `fetchStock`, `fetchStockV2`, `fetchStockOrders`, `fetchStockEvents`, `fetchMyPurchases`, `fetchSeasons`, `fetchInventory`, `fetchMyJobs`, `fetchMyInvites` — 0 вызовов. FIX: удалить/подключить.
- **F17** Неиспользуемые backend-роуты: `/api/company/history`, `/api/shop/config`, `/api/cityroof/admin/season/close`, `/api/v2/stocks/orders`, `/api/v2/stocks/events`. FIX: подключить/документировать.
- **F18** `useApi` (hooks/useApi.js) без вызовов (только `useApiOnMount`). FIX: удалить/применить.
- **F19** Двухколоночные `.crypto-layout`/`.ad-layout` — риск overflow на узких экранах (не подтверждено без прогона брейкпоинтов). FIX: проверить `@media`-коллапс.

**Проверено и корректно:** формы балансов (`balance`) сходятся для stock/crypto/asset/transfer/company; имена и поля WS-событий `mining`/`asset_update`/`cityroof_*`/`market_update`/`leaderboard_update`/`notification` совпадают с хендлерами (кроме крипто `price_tick` на AssetDetail — F5); формы transaction/notification/analytics/leaderboard совпадают; refresh-lock токена, WS-реконнект и cleanup эффектов корректны.

---

## Сводка
- **Найдено:** 20 backend + 19 frontend = **39** проблем.
- **Critical:** 2 (B1, B2). **High:** 5 backend (B3–B7) + 2 frontend (F1, F2). **Medium:** ~13. **Low:** ~17.
- Приоритет фикса: экономические эксплойты B1–B9 (печать денег, двойные выплаты), затем контракт F1/F5, затем perf F7–F9.

---

## ИСПРАВЛЕНО (в этой сессии)

**Backend — экономика/безопасность (13):**
- ✅ **B1** (Critical) — founder-акции теперь оплачиваются по цене размещения (`stocks.issue_stock`): money-printer закрыт.
- ✅ **B2** (Critical) — крипта исполняется по пост-impact цене (`_project_fill`/`_apply_trade_impact`): арбитраж на своём движении убран.
- ✅ **B3** (High) — акции исполняются по пост-impact цене (`fill_price` = price±delta).
- ✅ **B4** (High) — reject сделок с `total <= 0` (мин. номинал): бесплатные монеты через округление невозможны.
- ✅ **B5** (High) — `company.collect_profit`: атомарный захват `last_tick` + `$inc` бюджета: двойная зарплата и lost-update устранены.
- ✅ **B6** (High) — личный `/collect` запрещён для активов компании: двойной доход убран.
- ✅ **B7** (High) — `_collect_asset_income`: условный атомарный сброс `last_collected`: TOCTOU-дубли пассивного дохода закрыты.
- ✅ **B8** (Medium) — cityroof `_ensure_season`: атомарный захват перехода недели: двойная награда/сброс закрыты.
- ✅ **B9** (Medium) — sell актива применяет рыночный множитель (симметрия с buy): арбитраж при mult<0.7 убран.
- ✅ **B10** (Medium) — прод-старт падает при дефолтном `JWT_SECRET`.
- ✅ **B12** (Medium) — crypto transfer компенсирует отправителя при сбое зачисления.
- ✅ **B19** (Low) — `_format_transaction` через `.get` (нет 500 на кривых строках).

**Frontend (12):**
- ✅ **F1/F2** (High) — удалены 8 мёртвых компонентов (6 shop + BuyModal + ShopCard, ~1580 строк) и битые `purchaseItem`/`fetchMyPurchases`; каталоги вынесены в `utils/shopCatalog.js`.
- ✅ **F3** (Medium) — убран мёртвый `fetchConfig('sidebar_menu')` из Sidebar.
- ✅ **F4** (Medium) — добавлен пункт меню `mybusiness`.
- ✅ **F5** (Medium) — AssetDetail крипто-тик читает `change24h` (бейдж не мигает «—»).
- ✅ **F6** (Medium) — глобальные WS-бродкасты не вызывают рефетч юзера (`GLOBAL_BROADCAST_TYPES`).
- ✅ **F7** (Medium) — таймер cityroof вынесен в `<BonusCountdown>` (нет 1Hz ре-рендера вкладки).
- ✅ **F8** (Medium) — `<OverclockSlider>` коммитит на отпускании (нет шторма запросов).
- ✅ **F9** (Medium) — CryptoTab `load(silent)` (нет мигания скелетона после сделок).
- ✅ **F10** (Low) — NotificationCenter чистит таймеры + дедуп событий.
- ✅ **F12** (Low) — удалён мёртвый `usePriceAnimation`.
- ✅ **F14** (Low) — CryptoTab не сбрасывает в онбординг при сетевом блипе.

**Улучшение механики:**
- ✅ Торговая комиссия 0.5% на сделки акций и крипты (спред «сгорает») — делает churning невыгодным, углубляет экономику, усиливает анти-арбитраж. Показывается в модалках сделок (`trade.fee`).

## ОСТАЛОСЬ (не критично, на будущее)
- **B11** (Medium) — валидация admin stock create/update (bounds price, init free_shares).
- **B13** (Medium) — уже смягчено фиксом B5 ($inc вместо $set), проверить остаточные пути.
- **B14** (Low) — auth на публичных read-эндпоинтах (`/config/{key}` и др.).
- **B15** (Low) — атомарность install/uninstall железа.
- **B16** (Low) — cap holders в `pay_dividend`.
- **B17** (Low) — scheduler как единый leader-процесс при `--workers > 1`.
- **B18/B20** (Low) — атомарность материалов/capture cityroof.
- **F11/F18** (Low) — централизовать `fetchCurrentUser`, убрать `useApi`.
- **F15** (Low) — вынести инлайн-хексы/`RARITY_GRAD` в токены/util.
- **F16/F17** (Low) — почистить мёртвый API-surface / подключить неиспользуемые роуты.
- **F19** (Low) — проверить `@media`-коллапс trading-лейаутов.

## Что можно улучшить в механиках (будущее)
- Биржевой стакан (order book) вместо mint-on-sell для пользовательских акций — настоящий контрагент.
- Лимитные ордера, стоп-лоссы для трейдинга.
- Динамическая комиссия/налог от объёма (прогрессивная шкала) как денежный сток.
- События-«новости» с адресным влиянием на секторы акций.
- Страхование активов/майнинга от событий; кредиты в банке с процентами (денежный сток).


