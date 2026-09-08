// Каталог из админ-редактора цен (PriceEditorTab) — подмешивается в магазин,
// чтобы покупатель видел все позиции, цены на которые настраивает админ.
//
// Бэкенд (см. backend/shop.py) эти id пока НЕ знает: покупка/продажа
// отключены до того, как бэкенд будет дописан. Карточки помечаются флагом
// `fromAdmin: true`, и в UI кнопка «Купить» превращается в «Скоро».
//
// В ADMIN_SHOP_CATALOG попадают: gpu, cpu, case, supplies, а также дома
// (realestate, category='house') — последние помечены `fromAdmin: true`,
// покупка пока недоступна, но витрина нужна, чтобы игрок видел все доступные
// дома и их цены прямо в магазине (а не только на вкладке «Рынок»).
//
// Хешрейт для GPU извлекается из суффикса имени (Q320→320, D1060→1060, …).
// Для CPU берётся multiplier как множитель, для case — maxGpus → slots.

import {
  GPU_PRODUCTS, CPU_PRODUCTS, CASE_PRODUCTS,
  SUPPLIES_PRODUCTS,
  REAL_ESTATE_PRODUCTS, BUSINESS_PRODUCTS,
} from './shopCatalog'

// ── GPU: 90 моделей, 3 бренда × 4 линейки × 6 тиров ──────────────────────────
function _gpuHashrate(name) {
  // Ищем хвост вида "Q320", "T540", "SP380", "IF1000", "G1060" и т.п.
  // Достаём число после последней буквы (1–4 цифры).
  const m = name.match(/([A-Z]+)(\d{2,4})$/)
  if (!m) return 0
  // Для линеек типа "IF" (Inferno) буква перед числом = 'F' — берём просто число.
  // Для "G" в Genesis — то же самое.
  const n = parseInt(m[2], 10)
  return n
}

function _gpuPower(name) {
  // Грубая оценка: 120 + hashrate*0.05 (как в backend/shop.py:85).
  const h = _gpuHashrate(name)
  return Math.round(120 + h * 0.05)
}

// Цвет карточки для админских GPU — единый заливной (брендонезависимо),
// реальные тиры покажутся, когда бэкенд начнёт отдавать эти позиции.

export const ADMIN_GPU_CATALOG = GPU_PRODUCTS.map((p) => {
  const hashrate = _gpuHashrate(p.name)
  const power = _gpuPower(p.name)
  return {
    id: `admin-gpu-${p.id}`,
    category: 'gpu',
    name: p.name,
    brand: p.company,
    line: p.line,
    fromAdmin: true,
    color: '#818cf8', // брендонезависимо, общий цвет gpu
    specs: { hashrate, power },
    // Базовая цена по той же формуле, что в backend/shop.py:PRICE_PER_HASH=6.
    // Множитель категории и economy_mult применит сервер при реальной покупке.
    price: hashrate * 6,
  }
})

// ── CPU: 90 моделей, 3 бренда × 4 линейки × 6 тиров ──────────────────────────
// В админ-справочнике CPU_PRODUCTS уже есть maxGpus (слоты под GPU) и multiplier.
// Считаем «ядра» = maxGpus, чтобы specLine('cpu', …) выводил осмысленное.
function _cpuPower(multiplier) {
  return Math.round(45 + (multiplier || 1) * 25)
}

export const ADMIN_CPU_CATALOG = CPU_PRODUCTS.map(p => ({
  id: `admin-cpu-${p.id}`,
  category: 'cpu',
  name: p.name,
  brand: p.company,
  line: p.line,
  fromAdmin: true,
  color: '#a855f7',
  specs: {
    cores: p.maxGpus || 1,        // для specLine('cpu', …) → "X cores"
    power: _cpuPower(p.multiplier),
  },
  // Базовая цена: линейно по ядрам (как backend/shop.py для CPU).
  price: Math.round((p.maxGpus || 1) * 700 * (p.multiplier || 1)),
}))

// ── CASE: 90 моделей, 3 бренда × 4 линейки × 6 тиров ─────────────────────────
export const ADMIN_CASE_CATALOG = CASE_PRODUCTS.map(p => ({
  id: `admin-case-${p.id}`,
  category: 'case',
  name: p.name,
  brand: p.company,
  line: p.line,
  fromAdmin: true,
  color: '#94a3b8',
  specs: { slots: p.maxGpus || 1 },
  // Базовая цена корпуса: slots × 500 (как backend/shop.py для case).
  price: Math.round((p.maxGpus || 1) * 500),
}))

// ── SUPPLIES: расходники (есть в админке, но бэкенд их не отдаёт) ────────────
export const ADMIN_SUPPLIES_CATALOG = [
  {
    id: 'admin-supply-cooling-fluid',
    category: 'supplies',
    name: 'Охлаждающая жидкость',
    kind: 'cooling',
    fromAdmin: true,
    color: '#f97316',
    specs: { kind: 'cooling' },
    price: 240, // оценка; админ правит в редакторе цен
  },
  {
    id: 'admin-supply-gpu-chip',
    category: 'supplies',
    name: 'Чип для улучшения видеокарты',
    kind: 'upgrade',
    fromAdmin: true,
    color: '#f97316',
    specs: { kind: 'upgrade' },
    price: 5000,
  },
]

// ── REAL ESTATE: дома из админ-справочника (PriceEditorTab) ───────────────────
// 81 модель, сгруппированы по rarity (common/uncommon/rare/epic/legendary).
// Поля slug бэкенду пока не нужны — карточки показываются как витрина с
// пометкой «Скоро». Базовые цены рассчитываются по формуле ниже; админ может
// переопределить их через редактор цен, и они подтянутся в MarketTab.
//
// Шкала цен: лестница по rarity, согласованная с backend/assets.py:125 (CATALOG):
//   common    ->  5 000    (Студия)
//   uncommon  -> 45 000    (Таунхаус)
//   rare      ->160 000    (Вилла у моря)
//   epic      ->480 000    (Пентхаус)
//   legendary ->1 500 000  (Замок)
//
// Внутри каждой rarity цены распределяются ПЛАВНОЙ ЛЕСТНИЦЕЙ: i-й объект в
// группе стоит в 1+step раз дороже базы группы, (i+1)-й — в 1+2·step, и т.д.
// Без этой лестницы у 20 объектов одной rarity была бы одна и та же цена
// (или хаотичный разброс), что плохо читается на витрине.
//
// Шаг рассчитан так, чтобы потолок самой дорогой карточки в группе был
// примерно равен базе следующей rarity (без перехлёста через границу).
const RARITY_PRICE_BASE = {
  common: 5000,
  uncommon: 45000,
  rare: 160000,
  epic: 480000,
  legendary: 1500000,
}
// Шаг внутри rarity (доля от базы группы, на которую растёт цена между
// соседними объектами). Для 20 объектов common потолок = 5000 * 1.855
// = 9 275, что заметно ниже базы uncommon (45 000) — граница не «слипается».
const RARITY_INNER_STEP = 0.045
// Бонус площади: 1..12 комнат -> 1.00..1.12.
const ROOMS_BONUS_PER = 0.01

// Ранг rarity для сортировки (common < uncommon < rare < epic < legendary).
const RARITY_RANK = { common: 0, uncommon: 1, rare: 2, epic: 3, legendary: 4 }

export const ADMIN_REAL_ESTATE_CATALOG = (() => {
  // Сортируем по (rarity_rank, id), чтобы лестница строилась предсказуемо.
  const sorted = [...REAL_ESTATE_PRODUCTS].sort((a, b) => {
    const r = (RARITY_RANK[a.rarity] || 0) - (RARITY_RANK[b.rarity] || 0)
    return r !== 0 ? r : a.id - b.id
  })
  // Считаем позицию внутри каждой rarity-группы.
  const posInGroup = new Map()
  const groupSize = new Map()
  for (const p of sorted) {
    const r = p.rarity || 'common'
    groupSize.set(r, (groupSize.get(r) || 0) + 1)
  }
  const seen = new Map()
  for (const p of sorted) {
    const r = p.rarity || 'common'
    const i = seen.get(r) || 0
    posInGroup.set(p.id, i)
    seen.set(r, i + 1)
  }

// Доход/час и число жильцов для дома: выводим из rarity и размера.
// Логика согласована с MarketTab/PriceEditorTab, чтобы цифры на витрине
// магазина не расходились с тем, что показывают в разделе «Рынок».
function _houseIncome(rarity, rooms) {
  // Базы дохода/час по rarity (общая шкала для всех домов).
  const baseIncome = { common: 25, uncommon: 110, rare: 420, epic: 1300, legendary: 4200 }
  const base = baseIncome[rarity] || baseIncome.common
  // Поправка за размер: 1..12 комнат -> 1.0..1.2.
  const roomsBonus = 1 + Math.max(0, (rooms || 1) - 1) * 0.018
  return Math.round(base * roomsBonus)
}
function _houseResidents(rooms) {
  // 1 комната -> 2 жильца, далее +1 за каждую дополнительную комнату.
  return Math.max(2, (rooms || 1) + 1)
}

  return sorted.map(p => {
    const rarity = p.rarity || 'common'
    const base = RARITY_PRICE_BASE[rarity]
    const i = posInGroup.get(p.id) || 0
    const size = groupSize.get(rarity) || 1
    // Множитель внутри группы: i=0 -> 1.0, последний -> 1 + step*(size-1).
    // Пример: 20 объектов common -> потолок = 5000 * 1.855 = 9 275.
    const innerMultiplier = 1 + RARITY_INNER_STEP * i
    // Поправка за размер: 1..12 комнат -> 1.00..1.12.
    const roomsBonus = 1 + Math.max(0, (p.rooms || 1) - 1) * ROOMS_BONUS_PER
    const price = Math.round(base * innerMultiplier * roomsBonus)
    const income = _houseIncome(rarity, p.rooms)
    const residents = _houseResidents(p.rooms)
    return {
      id: `admin-re-${p.id}`,
      // category='house' — для фильтр-пилюли в ShopTab. 'realestate' оставлен
      // как type для совместимости с MarketTab/PriceEditorTab.
      category: 'house',
      type: 'realestate',
      slug: `admin-re-${p.id}`,
      name: p.name,
      rarity,
      fromAdmin: true,
      color: '#22c55e',
      rooms: p.rooms,
      basement: p.basement,
      income,
      residents,
      specs: { rooms: p.rooms, basement: p.basement, income, residents },
      price,
    }
  })
})()

// ── BUSINESS: бизнесы из админ-справочника (PriceEditorTab) ───────────────────
// 12 моделей, сгруппированы по category (retail/tech/service/office).
// Эти позиции тоже витрина: покупка/продажа отключены до того, как бэкенд будет
// дописан. Базовые цены — оценка по category; админ может их переопределить.
// Базы цен по тематике бизнеса. Шкала согласована с лестницей домов:
//   retail  ->  6 000  (самые доступные точки: ларёк, мини-маркет)
//   service -> 18 000  (ремонт, оверклок-лаборатория)
//   office  -> 28 000  (бэк-офис, крипто-офис)
//   tech    -> 50 000  (GPU-маркет, премиальные магазины)
// Тех-бизнесы самые дорогие, но всё равно дешевле самой простой недвижимости
// (Студия 5 000) лишь на нижней границе, что оставляет иерархию
// «недвижимость > бизнесы» с небольшим перехлёстом (квартира дешевле, чем
// большой GPU-магазин — нормальная рыночная ситуация).
const CATEGORY_PRICE_BASE = {
  retail: 6000,
  service: 18000,
  office: 28000,
  tech: 50000,
}
const CATEGORY_RANK = { retail: 0, service: 1, office: 2, tech: 3 }
const CATEGORY_EMOJI = {
  retail: '🛍️',
  service: '🛠️',
  tech: '💻',
  office: '🏢',
}
// Внутри одной тематики 3 объекта идут с шагом 10%: 1.0, 1.1, 1.2.
const BIZ_INNER_STEP = 0.10

export const ADMIN_BUSINESS_CATALOG = (() => {
  const sorted = [...BUSINESS_PRODUCTS].sort((a, b) => {
    const r = (CATEGORY_RANK[a.category] || 0) - (CATEGORY_RANK[b.category] || 0)
    return r !== 0 ? r : a.id - b.id
  })
  const posInGroup = new Map()
  const groupSize = new Map()
  for (const p of sorted) {
    const c = p.category || 'retail'
    groupSize.set(c, (groupSize.get(c) || 0) + 1)
  }
  const seen = new Map()
  for (const p of sorted) {
    const c = p.category || 'retail'
    posInGroup.set(p.id, seen.get(c) || 0)
    seen.set(c, (seen.get(c) || 0) + 1)
  }

  return sorted.map(p => {
    const category = p.category || 'retail'
    const base = CATEGORY_PRICE_BASE[category] || 20000
    const i = posInGroup.get(p.id) || 0
    const size = groupSize.get(category) || 1
    const innerMultiplier = 1 + BIZ_INNER_STEP * i
    const price = Math.round(base * innerMultiplier)
    return {
      id: `admin-biz-${p.id}`,
      category: 'business',
      type: 'business',
      slug: `admin-biz-${p.id}`,
      name: p.name,
      category_business: category,
      rarity: 'common',
      fromAdmin: true,
      color: '#a855f7',
      emoji: CATEGORY_EMOJI[category] || '🏢',
      specs: { category, employees: 2 + (p.id % 5) * 2 },
      employees: 2 + (p.id % 5) * 2,
      price,
    }
  })
})()

// Сводный каталог, который подмешивается в магазин.
// Дома НЕ входят сюда: для категории 'house' ShopTab грузит реальный каталог
// с бэкенда (GET /api/assets/market?type=realestate) — это 6 типов
// (studio/flat2/townhouse/villa/penthouse/castle), которые покупаются
// через POST /api/assets/buy. 81-домовая витрина остаётся в
// ADMIN_MARKET_CATALOG для вкладки «Рынок».
export const ADMIN_SHOP_CATALOG = [
  ...ADMIN_GPU_CATALOG,
  ...ADMIN_CPU_CATALOG,
  ...ADMIN_CASE_CATALOG,
  ...ADMIN_SUPPLIES_CATALOG,
]

// Сводный каталог для вкладки «Рынок» (недвижимость + бизнесы). Транспорт
// сюда намеренно НЕ входит — см. задачу: «удалить оттуда транспорт».
export const ADMIN_MARKET_CATALOG = [
  ...ADMIN_REAL_ESTATE_CATALOG,
  ...ADMIN_BUSINESS_CATALOG,
]

// ── Дефолтные цены для редактора цен (PriceEditorTab) ────────────────────────
// Словарь {productId: price} по всем категориям. Используется как стартовое
// значение для полей ввода: при первом открытии админ-редактора (или после
// полного сброса) поля уже заполнены согласованными с экономикой цифрами.
//
// Бэкенд /api/admin/shop-prices хранит только ИЗМЕНЁННЫЕ админом цены; если
// для какого-то id записи нет, PriceEditorTab.jsx подмешивает значение из
// ADMIN_DEFAULT_PRICES, чтобы поле не пустовало.
//
// Источники цен:
//   gpu      -> _gpuPower формула (price = hashrate * 6)
//   cpu      -> maxGpus * 700 * multiplier
//   case     -> maxGpus * 500
//   supplies -> hard-coded (240, 5000)
//   realestate -> ADMIN_REAL_ESTATE_CATALOG (плавная лестница по rarity)
//   business    -> ADMIN_BUSINESS_CATALOG (лестница по category)


function _gpuPrice(p) {
  return _gpuHashrate(p.name) * 6
}
function _cpuPrice(p) {
  return Math.round((p.maxGpus || 1) * 700 * (p.multiplier || 1))
}
function _casePrice(p) {
  return Math.round((p.maxGpus || 1) * 500)
}

export const ADMIN_DEFAULT_PRICES = (() => {
  const out = {}

  // GPU: ключи = productId (число), 1..90
  for (const p of GPU_PRODUCTS) out[p.id] = _gpuPrice(p)
  // CPU: ключи = productId (число), 1..90
  for (const p of CPU_PRODUCTS) out[p.id] = _cpuPrice(p)
  // Case: ключи = productId (число), 1..90
  for (const p of CASE_PRODUCTS) out[p.id] = _casePrice(p)
  // Supplies: ключи = productId (число), 1..2
  for (const p of SUPPLIES_PRODUCTS) {
    if (p.category === 'cooling') out[p.id] = 240
    else if (p.category === 'upgrade') out[p.id] = 5000
    else out[p.id] = 0
  }
  // Real estate: ключи = productId (число), 1..81; значения берём
  // из ADMIN_REAL_ESTATE_CATALOG, у которой id вида `admin-re-<productId>`.
  for (const item of ADMIN_REAL_ESTATE_CATALOG) {
    const m = item.id.match(/^admin-re-(\d+)$/)
    if (m) out[parseInt(m[1], 10)] = item.price
  }
  // Business: ключи = productId (число), 1..12.
  for (const item of ADMIN_BUSINESS_CATALOG) {
    const m = item.id.match(/^admin-biz-(\d+)$/)
    if (m) out[parseInt(m[1], 10)] = item.price
  }
  return out
})()

