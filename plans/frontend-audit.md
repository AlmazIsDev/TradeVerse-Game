# Аудит фронтенда TradeVerse: баги и расхождения стилей

Дата: 2026-11-01. Охват: `frontend/src` — компоненты, CSS, утилиты, i18n, `index.html`.

Базовая архитектура стилей: [`index.css`](../frontend/src/index.css:42) объявляет слой токенов
`--color-*`, `--hairline*`, `--fill-*`, `--spacing-*`, `--radius-*`, `--shadow-*`, `--ease-*`, `--dur-*`
и три темы: light (по умолчанию), `[data-theme="dark"]`, `[data-theme="tradeverse"]`.
Тема применяется к `<html>`: boot-скрипт в [`index.html`](../frontend/index.html:13) и рантайм в
[`theme.js`](../frontend/src/utils/theme.js:108). **Всё, что использует `var()` без объявленного токена,
живёт на фолбэке и не реагирует на смену темы.** Ниже — систематизация таких мест.

---

## 1. Критичные баги (сломано поведение)

### 1.1 Туториал перезапускается по стрелке и не перерисовывает эффект — устаревший обработчик

[`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:200)

```js
useEffect(() => {
  const onKey = (e) => { ... next() ... back() }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}, [index, isChoice, isLast, onClose, steps.length])
```

- В зависимостях **нет `step` / `step.check`**, но `next()` читает `step.check` из замыкания.
  Переход с шага без `check` на шаг с `check` (например, 19.8 → 19.9) оставляет в замыкании старый
  `step` — проверка не выполнится, шаг пролистывается стрелкой вправо без валидации.
  Обход: пользователь жмёт «Проверить» мышью, и всё работает — разъезжается только клавиатура.
- `next`/`back` не мемоизированы, поэтому линтер `react-hooks/exhaustive-deps` также будет ругаться.

### 1.2 Автопереход шага (`step.on`) не подписан на смену индекса

[`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:211)

```js
useEffect(() => {
  if (!step.on) return undefined
  const onEvt = (e) => { if (e.detail?.type === step.on) setIndex(...) }
  window.addEventListener('tv:tour', onEvt)
  return () => window.removeEventListener('tv:tour', onEvt)
}, [step.on, steps.length])
```

Два шага подряд с `on: 'buy-open'` / `on: 'buy-done'` тут не встречаются, но проблема появится при
любых двух соседних интерактивных шагах с одинаковым `on`: эффект не перезапустится (зависимости те же),
подписка останется на старом шаге. Также событие `tv:tour` **не проверяет, что оно относится к текущему
индексу** — одно и то же событие может перелистнуть несколько шагов, если сработает несколько раз
до размонтирования. Нужен `index` в зависимостях и/или `once`-семантика.

### 1.3 Авто-проверка шага не защищена от гонки и от повторного входа

[`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:221)

```js
useEffect(() => { if (step.auto && step.check) next() }, [index])
```

- `next` не в зависимостях (lint), эффект срабатывает на любой смене `index`, включая переход **назад**:
  шаг 9 с `auto: true` при клике «Назад» с шага 10 снова вызывает проверку и снова прыгает вперёд —
  вернуться назад через авто-шаг невозможно.
- Нет отмены/защиты от двойного вызова при StrictMode: в dev-режиме (React 18) эффект вызывается дважды,
  что даёт дублирующий сетевой запрос и лишний `setIndex`.

### 1.4 `onTabChange` вызывается без проверки на `undefined`

[`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:149)

```js
useEffect(() => { onTabChange(step.tab) }, [step.tab, onTabChange])
```

`onTabChange` в пропсах необязателен по типу, и при рендере оверлея в тестах/сторибуках/лендинге это
`TypeError: onTabChange is not a function`. В проекте есть паттерн безопасного вызова —
[`InventoryTab.jsx`](../frontend/src/components/InventoryTab.jsx:157) использует `onTabChange?.(...)`.
Здесь он не соблюдён.

### 1.5 Шаг 7 тура (mining) не достижим: `tour-buy` живёт на другом шаге-`tab`

[`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:79) указывает `tab: 'realestate'`,
`target: 'tour-buy'`. Целевой атрибут ставится в
[`MarketTab.jsx`](../frontend/src/components/MarketTab.jsx:530). Между тем эффект измерения
([`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:152)) выполняется в `useLayoutEffect`
синхронно после коммита, а `setActiveTab` из эффекта `onTabChange` применяется **после** — то есть
в момент замера вкладка ещё старая, `document.querySelector('[data-tour="tour-buy"]')` вернёт `null`,
`rect` останется `null`, и шаг 7 покажет карточку по центру вместо подсветки кнопки.
Нужен повторный замер (например, через `requestAnimationFrame` / `MutationObserver` / сброс `rect`
при смене `tab` и замер после монтирования целевой вкладки).

### 1.6 `TutorialModal.jsx` в списке открытых вкладок отсутствует на диске

Файл `frontend/src/components/TutorialModal.jsx` не существует (чтение падает с `ENOENT`), и при этом
на него **нет ни одного импорта** в `frontend/src` — функция размножена по `TutorialTab.jsx` и
`TourOverlay.jsx`. Содержимое файла, если он был, потеряно. Нужно либо восстановить, либо явно
зафиксировать, что модалка не нужна (иначе это «висящий» референс в IDE, ведущий к чтению
несуществующих правок).

### 1.7 `PlayerBusinessesTab`: количество не сбрасывается и не имеет верхней защиты

[`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:37)

- `value={qtys[key] ?? 1}` хранит **строку** из `e.target.value`; при вводе `''` (очистка поля) в state
  лежит `''`, а `Number('')` → `0` → срабатывает `qty < 1` и показывается ошибка вместо мягкого
  восстановления значения. Аналогично `Number('1e5')` и `Number('3.9')` — второй обрезается `Math.floor`,
  а первый проходит проверку `qty > it.availableQty`, но `max` в `<input>` не мешает вводу.
- После успешной покупки `qtys` не сбрасывается на `1`, и следующая покупка уходит с тем же количеством —
  при уменьшившемся `availableQty` игрок получает ошибку «количество вне диапазона».
- `qtys` растёт по ключу `unitId:itemId` и не чистится при reload: после `load()` остаются значения для
  исчезнувших позиций (утечка небольшого state, не критично, но мешает отладке).

### 1.8 `GpuShopEditor`: удаление цены не удаляет черновик, а «сохранение» всегда шлёт число

[`GpuShopEditor.jsx`](../frontend/src/components/GpuShopEditor.jsx:48)

```js
const raw = clear ? '' : String(drafts[it.id] ?? '').trim()
const price = raw === '' ? null : Number(raw)
```

`input type="number"` с `min="0"` позволяет вписать `0`, но валидация `price <= 0` режет 0 — это ок.
Проблема в другом: `Number('  ')` → `0` (пробел уже срезан `trim`, но `Number('1e3')` → `1000`
проходит). Не баг сам по себе, но валидация не отсекает экспоненциальную запись и `Infinity`
(`Number('1e999')` → `Infinity`, и `!Number.isFinite` его поймает — тут ок).

Реальный баг: после `saveItem(it, true)` (`clear`) вызывается `load()`, и в `drafts` возвращается `''`.
Это корректно. Но при ошибке сервера `setViolations` заполняется **и в `saveItem` не сбрасывается** —
старые нарушения публикации продолжают висеть под таблицей после успешного сохранения цены
([`GpuShopEditor.jsx`](../frontend/src/components/GpuShopEditor.jsx:70) сбрасывает их только в `togglePublish`).
Пользователь видит «Нарушения» там, где их уже нет.

### 1.9 `SupportPage`: карточка обращения обрезает текст, но `ticketPreview` может вернуть `undefined`

[`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:30)

```js
if (ticket.type === 'loss') return `${ticket.lost_item} — ${ticket.method}`
if (ticket.type === 'suggestion') return ticket.suggestion
return ticket.description
```

Если сервер вернул неизвестный `type` (а бэкенд `support.py` уже расширялся — в открытых вкладках он есть),
функция упадёт в `ticket.description` и отрисует пустой `<p>`. Как минимум нужен фолбэк `?? '—'`.
Тот же риск в [`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:106): `typeLabel` возвращает
`undefined` для неизвестного типа, и React отрисует пустой заголовок карточки.

Плюс: `new Date(selected.created_at).toLocaleString('ru-RU')` жёстко локализован на русский
([`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:213)) — расходится с языком интерфейса
(в проекте 4 локали: ru/en/es/ja).

### 1.10 `SupportPage`: список не обновляется при повторном входе во вкладку

[`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:80) — `useEffect(..., [])` без повторной
загрузки: если админ ответил на обращение, пока вкладка открыта/после возврата со вкладки «Поддержка»,
пользователь не увидит `reply` без перезагрузки страницы. Аналогично
[`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:31) и
[`GpuShopEditor.jsx`](../frontend/src/components/GpuShopEditor.jsx:46) — только разовая загрузка.

### 1.11 `SupportPage`: двойная отправка и неописанное состояние `submitting`

Кнопка дизейблится по `submitting` ([`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:196)),
но внутри `submitTicket` проверка `if (!isFormValid(form) || submitting) return` читает `submitting`
из замыкания, которое **не обновлено** в момент второго клика в том же тике (React batch). Двойной
`Enter` в поле формы может отправить два тикета. Гонку закрывает только `disabled`, чего для `Enter`
в `<input>` может не хватить.

### 1.12 `TourOverlay`: `useEffect` с `step.auto` не имеет зависимостей `next` и может «прыгать» при смене `scriptKey`

Смена `scriptKey` в `choose()` переводит на `index = 0` другой сценарий. Если у первого шага нового
сценария случайно окажется `auto: true`, произойдёт немедленный прыжок. Сейчас такого нет, но
инвариант «индекс сбрасывается при смене сценария» ничем не защищён — стоит добавить
`useEffect(() => setIndex(0), [scriptKey])` либо явный guard.

---

## 2. Расхождения стилей (тема не применяется / цвета не совпадают с дизайн-системой)

Систематическая проблема: часть CSS-файлов написана **до** Apple-редизайна и опирается на переменные,
которых в [`index.css`](../frontend/src/index.css:42) нет. Поиск показывает, что следующие имена
**не объявлены нигде** в `frontend/src` (0 совпадений в объявлениях):

| Переменная | Где используется | Что происходит |
|---|---|---|
| `--border` | `support.css`, `settings.css` | берётся фолбэк `#444` / `rgba(127,127,127,.3)` — одинаково тёмный во **всех** темах |
| `--surface` | [`support.css`](../frontend/src/support.css:78) | фолбэк `rgba(255,255,255,.04)` — в светлой теме карточка почти прозрачная на белом |
| `--surface-solid` | [`support.css`](../frontend/src/support.css:140) | фолбэк `#1e1e24` — **модалка поддержки всегда тёмная**, даже в light |
| `--input-bg` | [`support.css`](../frontend/src/support.css:173) | фолбэк `rgba(255,255,255,.05)` — поля ввода невидимы в светлой теме |
| `--accent` | [`support.css`](../frontend/src/support.css:45) | фолбэк `#3b82f6` (Tailwind blue) вместо `--color-accent` `#0071e3`; **пользовательский акцент из настроек не применяется** |
| `--surface-1` / `--surface-2` | [`settings.css`](../frontend/src/settings.css:15) | фолбэк `#1b1f2a` — выпадающий список стран **тёмный в светлой теме** |
| `--border-color` | [`App.css`](../frontend/src/App.css:4858) | фолбэк `#333` — в light тема линия темнее, чем задумано |
| `--card-bg` / `--text` | [`tour.css`](../frontend/src/tour.css:49) | фолбэк `#1b1f2a` / `#e6e9f2` — **карточка тура всегда тёмная** |
| `--color-text-dim` | [`economy.css`](../frontend/src/economy.css:3458) | фолбэк `#9ca3af` — в light читаемо, но цвет не из палитры (должен быть `--color-text-tertiary`) |
| `--color-surface-2` | [`settings.css`](../frontend/src/settings.css:170) | фолбэк `rgba(128,128,128,.12)` — случайный серый вместо `--color-bg-tertiary` |

### 2.1 `support.css` целиком написан «под тёмную тему»

[`support.css`](../frontend/src/support.css:1) — самый проблемный файл (см. таблицу выше).
Дополнительно:
- [`support.css`](../frontend/src/support.css:46) `color: #fff` на кнопке с фолбэком `--accent: #3b82f6`;
  при светлом пользовательском акценте (жёлтый/салатовый) белый текст не читается — токен
  `--on-accent` в проекте существует именно для этого ([`index.css`](../frontend/src/index.css:83)).
- [`support.css`](../frontend/src/support.css:43) `border-radius: 8px` вместо шкалы
  `--radius-sm/md/lg` (10/14/20px).
- Статусы ([`support.css`](../frontend/src/support.css:5)) используют Tailwind-цвета
  (`#facc15`, `#f87171`, `#4ade80`) вместо `--color-warning` / `--color-danger` / `--color-success`
  — в теме `tradeverse` эти цвета другие (`#f59e0b`, `#ef4444`, `#22c55e`).
- Нет `padding`/`min-height` для кнопки закрытия `support-icon-btn` — тач-таргет меньше 44px
  на мобильных (сравните с `tour.css`, где это учтено).

### 2.2 `tour.css` — жёстко тёмные цвета и жёлтая подсветка «не из темы»

[`tour.css`](../frontend/src/tour.css:47):
- `background: var(--card-bg, #1b1f2a)` и `color: var(--text, #e6e9f2)` — переменные не объявлены,
  карточка тура **всегда тёмная** в светлой теме. Должно быть `--color-bg-elevated` / `--color-text-primary`.
- `border: 1px solid rgba(255,255,255,.12)`, `shadow rgba(0,0,0,.5)` — в light это «плавающая» тёмная
  плашка без контура, выбивающаяся из Apple-стиля.
- `.tour-progress > span` и `.tour-primary` — `#4f8cff`, не `--color-accent`. При смене акцента
  в настройках прогресс-бар и главная кнопка тура остаются голубыми.
- `.tour-hole` / `.tour-pulse` — `#facc15` (Tailwind amber-400) вместо `--color-warning` (`#ff9500`
  в light, `#ff9f0a` в dark, `#f59e0b` в tradeverse). Жёлтая рамка на белом фоне читается плохо.
- Затемнение `.tour-blocker--dim` `rgba(0,0,0,.72)` не адаптируется: в light-теме это слишком
  контрастный «чёрный экран», обычно для light берут `0.45–0.55`.
- `z-index: 1000` в [`tour.css`](../frontend/src/tour.css:6) совпадает с `z-index: 1000`
  в [`support.css`](../frontend/src/support.css:126) — при одновременном показе поддержки и тура
  порядок зависит от порядка в DOM, а не от смысла. Должна быть единая шкала слоёв.

### 2.3 `economy.css` — блок GPU-магазина написан под тёмную тему

[`economy.css`](../frontend/src/economy.css:3452):
- `.gpu-shop-card { border: 1px solid rgba(255,255,255,.08) }` — в светлой теме граница **невидима**
  (белое на белом). Нужен `--hairline`.
- `.gpu-shop-own { background: rgba(99,102,241,.2) }` — indigo, который остался от старой темы
  (`tradeverse` accent). В Apple light должен быть `--accent-soft`.
- `.gpu-shop-open/.gpu-shop-closed/.gpu-shop-error` — `#22c55e` / `#ef4444` вместо
  `--color-success` / `--color-danger`; в light-tema официальные `#34c759` / `#ff3b30`.
- `.gpu-shop-violations { background: rgba(239,68,68,.1); color: #fca5a5 }` — светло-красный текст
  на белом даёт контраст ~1.8:1, **не проходит WCAG AA**.
- `.gpu-shop-editor { max-width: 720px }` на таблице из 5 колонок с инпутами — на ширине 375px
  таблица вылезает за модалку без `overflow-x: auto` (в `PlayerBusinessesTab` та же таблица без
  горизонтального скролла на мобильных).

### 2.4 Дублирование дизайна: `.gpu-shop-*` живёт вне своей таблицы стилей

Стили витрины/редактора GPU-магазина лежат в конце [`economy.css`](../frontend/src/economy.css:3452),
хотя компонент относится к вкладке «Бизнесы игроков» и грузится в `PlayerBusinessesTab` /
`GpuShopEditor`. Аналогично [`tutorial.css`](../frontend/src/tutorial.css:1) сам объявляет свои
переменные (`--tut-*`), что дублирует токены. Это не баг, но затрудняет поиск «где описан компонент».

### 2.5 `settings.css`: смешение двух стилевых эпох в одном файле

[`settings.css`](../frontend/src/settings.css:3) — блок «country select» (строки 2–30) написан в старой
тёмной стилистике (`--surface-2`, `--border`, `--surface-1`), а остальной файл (с 32-й строки) —
на новых токенах. Комментарий на [`settings.css`](../frontend/src/settings.css:32) прямо утверждает,
что файл использует общие токены — это уже не так для первой секции.
- [`settings.css`](../frontend/src/settings.css:73) `border-color: rgba(0,113,227,.25)` — захардкоженный
  системный синий вместо `--color-accent`, ломается при пользовательском акценте.
- [`settings.css`](../frontend/src/settings.css:102) и [`settings.css`](../frontend/src/settings.css:188) —
  `rgba(0,113,227,...)` в градиентах иконок/аватара вместо `color-mix(in srgb, var(--color-accent) ...)`.
- [`settings.css`](../frontend/src/settings.css:153) `.status-badge-beta { background: #f59e0b }` —
  в light-теме warning официально `#ff9500`.
- [`settings.css`](../frontend/src/settings.css:279) тень тумблера — `bg: #fff` без токена, в теме
  `tradeverse` белый кружок не отделяется от дорожки.
- **`--switch-off` объявлен только для `dark` и `tradeverse`** ([`index.css`](../frontend/src/index.css:160)
  и [`index.css`](../frontend/src/index.css:207)), в light его нет — тумблер падает на фолбэк
  `rgba(0,0,0,.14)` и визуально отличается от iOS-эталона. Нужен токен в `:root`.

### 2.6 `index.css`/`theme.js`: акцент применяется к `--color-accent`, но не к хардкодам

[`theme.js`](../frontend/src/utils/theme.js:75) экспортирует `applyAccentVars`, который переопределяет
`--color-accent*`, `--accent-soft*`, `--on-accent`. Любой CSS, который писал `#0071e3` / `#4f8cff` /
`#3b82f6` напрямую, акцент не учитывает — см. п. 2.1, 2.2, 2.5. Это самая заметная «несогласованность
стилей» для конечного пользователя: он меняет акцент в настройках, а тур, поддержка и настройки
остаются синими.

### 2.7 `index.css`: скроллбары не адаптируются к тёмной теме

[`index.css`](../frontend/src/index.css:262) — `scrollbar-color: rgba(0,0,0,.18)` жёстко зашит.
В `data-theme="dark"` и `tradeverse` скроллбар остаётся **тёмным на тёмном** и почти невидим.
Претензии к токенам: нужен `--scrollbar-thumb: rgba(255,255,255,.18)` в тёмных темах.

### 2.8 `index.css`: `::selection` использует акцентный цвет с плохим контрастом

[`index.css`](../frontend/src/index.css:281) — `color: var(--color-accent-active)` на
`background: var(--accent-soft-hover)`. В light-теме это тёмно-синий на светло-синем (контраст ~3.5:1 —
на грани), а в dark-теме на `rgba(10,132,255,.26)` даёт синий на синем. Стандартный паттерн —
`background: var(--accent-soft-hover); color: var(--color-text-primary)`.

---

## 3. Мелкие замечания и общее качество

- **CSS-переменные-«призраки»** (п. 2) стоит либо объявить в `:root` как алиасы
  (`--border: var(--color-border)` и т.п.), либо заменить во всех файлах. Первый вариант быстрее и
  чинит сразу `support.css` + `settings.css`; второй — правильнее.
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:135) `CARD_WIDTH`/`CARD_GAP` объявлены,
  но `CARD_GAP` **не используется** — мёртвая константа.
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:52) и весь `SCRIPTS` — строки
  **не локализованы**, тогда как `ru/en/es/ja` есть в проекте. Тур полностью на русском для любого языка.
  То же у `TourOverlay.jsx` `aria-label="Обучение"` и `title/text` шагов.
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:257) `{index + 1} / {steps.length}` —
  жёсткий счётчик проходится по `steps`, но при `back()` с проверкой `step.check` нет — назад по
  шагам с валидацией ТЗ запрещает? В коде `back()` ничего не проверяет — если проверка обязательна,
  это дыра.
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:33) `MINING_ROLES` использует `cooling`,
  а туториал шаг 19.9 говорит «Корпус/стойка, вентиляторы и ИБП — по желанию», но `rolesFilled`
  требует `cooling` — расхождение **текста туториала и проверки** (в `hasAllRoles` тоже `cooling`
  обязателен, а текст щадящий). Пользователь, собравший ферму без вентиляторов, получит «Шаг ещё не выполнен».
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:17) `rolesFilled` — кейс `psus[0]`
  проверяется, но `cooling` как массив (`--fan`) уже не покрыт; стоит перечитаеть `backend/mining.py`
  `REQUIRED_ROLES` (сейчас список захардкожен в JSX — при изменении бэкенда фронт молча рассинхронизируется).
- [`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:142) закрытие модалки по клику на фон +
  `onSubmit` на `<form>`: `Enter` в поле `select` сабмитит форму при частично заполненных полях —
  `isFormValid` спасает, но UX без явного фокуса кнопки.
- [`GpuShopEditor.jsx`](../frontend/src/components/GpuShopEditor.jsx:129) `setDrafts({ ...drafts, ... })`
  вместо функционального апдейта — при быстром вводе в два инпута подряд возможно затирание значения.
  То же в [`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:98).
- [`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:38) `qty > it.availableQty`
  без проверки `qty` на целое до `Math.floor` — `1.9` станет `1` молча; лучше округлять явно и
  показывать подсказку.
- [`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:50) `await load()` в `finally`
  — если `buy` упал, список всё равно перезагружается (хорошо), но `busyKey` сбрасывается **до**
  перезагрузки (строки 49–50), из-за чего кнопка успевает мигнуть доступной. Перенести `setBusyKey(null)`
  после `await load()`.
- [`GpuShopEditor.jsx`](../frontend/src/components/GpuShopEditor.jsx:118) и
  [`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:82) используют fallback
  `t('gpuShop.items.${it.id}', it.id)` — ключи `gpuShop.items.*` нужно сверить с выдачей бэкенда
  (`production.py`): если сервер добавит новый `id`, пользователь увидит сырой id (это допустимо,
  но стоит зафиксировать в комментарии к API).
- **`index.html`**: `hreflang` объявляет `ru/en/uk` ([`index.html`](../frontend/index.html:57)), а
  фронтенд-локали — `ru/en/es/ja` (`frontend/src/i18n/locales`). SEO-разметка рассинхронизирована
  с реальными локалями: `uk` не существует, `es`/`ja` не заявлены. Также `lang="ru"` на `<html>`
  не обновляется при смене языка (если i18n не дёргает `document.documentElement.lang`).
- **`index.html`**: `og:image` заявлен 1254×1254 при `twitter:card=summary_large_image` — Twitter ждёт
  2:1; картинка будет обрезана.

---

## 4. Приоритезация исправлений

| Приоритет | Что | Файлы |
|---|---|---|
| P0 | Объявить алиасы-токены (`--border`, `--surface*`, `--accent`, `--input-bg`, `--card-bg`, `--text`, `--color-text-dim`, `--switch-off` в light) | [`index.css`](../frontend/src/index.css:42) |
| P0 | Карточка тура и модалка поддержки в светлой теме | [`tour.css`](../frontend/src/tour.css:47), [`support.css`](../frontend/src/support.css:130) |
| P0 | `onTabChange?.(...)` + перезамер `rect` при смене вкладки в туре | [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:149) |
| P1 | Зависимости эффектов тура (`step`, `index`), защита автоперехода и `back()` | [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:200) |
| P1 | Привести `support.css`/`tour.css`/`gpu-shop` к токенам (accent, radius, semantic colors, `--on-accent`) | 3 файла |
| P1 | Скроллбары и `::selection` в тёмных темах | [`index.css`](../frontend/src/index.css:262) |
| P2 | `PlayerBusinessesTab` / `GpuShopEditor`: функциональные апдейты state, сброс qty, сброс violations | 2 файла |
| P2 | `SupportPage`: фолбэки `typeLabel`/`preview`, локаль даты, авто-refresh | [`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:30) |
| P2 | Мобильная прокрутка таблиц GPU-магазина | [`economy.css`](../frontend/src/economy.css:3456) |
| P3 | Локализация тура (ru/en/es/ja), hreflang, `lang` на `<html>`, `og:image` | [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:52), [`index.html`](../frontend/index.html:57) |
| P3 | Согласовать `MINING_ROLES` с `backend/mining.py` `REQUIRED_ROLES` | [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:7) |

---

## 5. Статус исправлений (2026-11-01)

### Стили

- [`index.css`](../frontend/src/index.css:42) — объявлены алиасы для всех «призрачных» переменных
  (`--border`, `--border-color`, `--surface`, `--surface-solid`, `--surface-1/2`, `--input-bg`,
  `--card-bg`, `--text`, `--accent`, `--color-surface-2`, `--color-text-dim`). Добавлена шкала
  слоёв `--z-*`, `--switch-off` в light-теме, `--scrollbar-thumb[-hover]` во всех темах,
  `--color-warning-soft` и `--tour-dim`.
- [`index.css`](../frontend/src/index.css:261) — скроллбары и `::selection` через токены
  (были невидимы в `dark`, выделение было синим на синем).
- [`tour.css`](../frontend/src/tour.css:1) — полностью на токенах: карточка следует теме,
  акцент вместо `#4f8cff`, подсветка `--color-warning`, `--on-accent` на кнопке,
  адаптивное затемнение, `z-index` из общей шкалы.
- [`support.css`](../frontend/src/support.css:1) — модалка/карточки/инпуты следуют теме,
  semantic-цвета статусов, шкала радиусов, тач-таргет 36px, мобильные стили.
- [`economy.css`](../frontend/src/economy.css:3452) — GPU-магазин на токенах: видимая граница
  в светлой теме, `--accent-soft` вместо indigo, читаемый контраст ошибок, скролл таблиц.
- [`settings.css`](../frontend/src/settings.css:1) — блок country-select переведён на токены,
  убраны `rgba(0,113,227,…)` и белый текст на светлом акценте.

### Баги

- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:157) — `onTabChange?.()`,
  замер `rect` и `tour-pulse` ждут монтирования целевого узла (шаг 7 больше не «слепой»).
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:216) — корректные зависимости
  эффектов, `next`/`back` мемоизированы, возврат «Назад» на авто-шаг не прыгает вперёд,
  состояние сбрасывается при смене сценария.
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:11) — `MINING_ROLES`
  синхронизирован с `REQUIRED_ROLES` (`cooling`, `network`) плюс обязательный БП;
  удалена мёртвая константа `CARD_GAP`.
- [`SupportPage.jsx`](../frontend/src/components/SupportPage.jsx:29) — фолбэки полей и типа,
  дата в локали интерфейса, защита от двойной отправки через ref.
- [`PlayerBusinessesTab.jsx`](../frontend/src/components/PlayerBusinessesTab.jsx:34) — пустое
  количество = 1, сброс после покупки, порядок `load()`/`busyKey`, функциональные `setState`.
- [`GpuShopEditor.jsx`](../frontend/src/components/GpuShopEditor.jsx:57) — сброс `violations`
  после успешного сохранения, функциональные `setState`.

### SEO / i18n

- [`index.html`](../frontend/index.html:56) — `hreflang` и `inLanguage` приведены к реальным
  локалям (`ru/en/es/ja`), исправлены `og:locale:alternate`, добавлен `og:image:type`
  и комментарий про обрезку квадратного превью.
- [`i18n/index.js`](../frontend/src/i18n/index.js:43) — `<html lang>` обновляется при смене
  языка (было статично `ru`).
- [`TourOverlay.jsx`](../frontend/src/components/TourOverlay.jsx:56) — весь тур переведён на ключи
  `tour.*`; тексты добавлены в `ru/en/es/ja` (122 ключа, полнота проверена скриптом).

### Осталось открытым

- Квадратный [`og-image.png`](../frontend/public/og-image.png) (1254×1254) обрезается соцсетями
  под `summary_large_image`. Метаданные теперь честные, но для корректного превью нужен
  отдельный файл 1.91:1 (1200×630) — это вопрос контента, а не кода.
- `frontend/src/components/TutorialModal.jsx` отсутствует на диске и нигде не импортируется.
  Если файл нужен — восстановить из истории; мёртвых ссылок в коде сейчас нет.
- Предсуществующие ошибки линтера в `AdminPanel.jsx`, `MarketTab.jsx`, `AuctionTab.jsx`
  (условные хуки, необъявленные зависимости) к этому аудиту не относятся и не трогались.
