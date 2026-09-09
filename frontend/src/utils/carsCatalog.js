// ─────────────────────────────────────────────────────────────────────────────
// carsCatalog · локальный каталог «Автосалона» (CarsTab).
//
// Содержит три секции:
//   1) cars    — легковые/спорт/премиум авто. Малая грузоподъёмность, низкий
//                расход топлива. Используются как личный транспорт.
//   2) trucks  — фуры (тягачи) разной мощности. Умеют цеплять прицеп.
//                Собственная грузоподъёмность (кабина) обычно небольшая;
//                основной объём груза идёт через прицеп.
//   3) trailers — прицепы разной вместимости. Расход топлива 0 (тянет фура),
//                 но грузоподъёмность сильно варьируется.
//
// Все цены и характеристики — оценка для витрины; бэкенд покупки пока не
// подключён (placeholder, как у домов/бизнесов/заводов/источников на рынке).
//
// Схема объекта:
//   {
//     id, slug, name, category: 'car' | 'truck' | 'trailer',
//     type: 'car' | 'truck' | 'trailer',
//     rarity, color, emoji,
//     price,
//     specs: {
//       fuelPer100km,   // л / 100 км (для трейлера = 0)
//       cargoKg,        // грузоподъёмность, кг
//       maxSpeed,       // км/ч (опционально)
//       // Только для truck: hookable = ['small-trailer', 'medium-trailer', 'large-trailer']
//     },
//   }
// ─────────────────────────────────────────────────────────────────────────────

// Базовая палитра по сегментам.
const CAR_COLOR = '#3b82f6'      // легковые
const TRUCK_COLOR = '#f59e0b'    // фуры
const TRAILER_COLOR = '#94a3b8'  // прицепы

// ── Легковые машины ──────────────────────────────────────────────────────
const CARS = [
  {
    id: 'car-hatchback-1', slug: 'car-hatchback-1', category: 'car', type: 'car',
    name: 'Хэтчбек «Старт»', rarity: 'common', color: CAR_COLOR, emoji: '🚗',
    price: 12000,
    specs: { fuelPer100km: 6.5, cargoKg: 350, maxSpeed: 160 },
  },
  {
    id: 'car-sedan-1', slug: 'car-sedan-1', category: 'car', type: 'car',
    name: 'Седан «Комфорт»', rarity: 'common', color: CAR_COLOR, emoji: '🚙',
    price: 22000,
    specs: { fuelPer100km: 7.2, cargoKg: 450, maxSpeed: 180 },
  },
  {
    id: 'car-suv-1', slug: 'car-suv-1', category: 'car', type: 'car',
    name: 'Кроссовер «Тропик»', rarity: 'uncommon', color: CAR_COLOR, emoji: '🚙',
    price: 38000,
    specs: { fuelPer100km: 8.5, cargoKg: 600, maxSpeed: 190 },
  },
  {
    id: 'car-sport-1', slug: 'car-sport-1', category: 'car', type: 'car',
    name: 'Спорткар «Вихрь»', rarity: 'rare', color: '#ef4444', emoji: '🏎️',
    price: 95000,
    specs: { fuelPer100km: 11.0, cargoKg: 220, maxSpeed: 280 },
  },
  {
    id: 'car-premium-1', slug: 'car-premium-1', category: 'car', type: 'car',
    name: 'Премиум «Империал»', rarity: 'epic', color: '#a855f7', emoji: '🚘',
    price: 220000,
    specs: { fuelPer100km: 9.4, cargoKg: 500, maxSpeed: 250 },
  },
]

// ── Фуры (тягачи) ────────────────────────────────────────────────────────
const TRUCKS = [
  {
    id: 'truck-light-1', slug: 'truck-light-1', category: 'truck', type: 'truck',
    name: 'Фура «Курьер»', rarity: 'common', color: TRUCK_COLOR, emoji: '🚚',
    price: 65000,
    specs: {
      fuelPer100km: 18.0, cargoKg: 1500, maxSpeed: 110,
      hookable: ['trailer-small', 'trailer-medium'],
    },
  },
  {
    id: 'truck-mid-1', slug: 'truck-mid-1', category: 'truck', type: 'truck',
    name: 'Фура «Магистраль»', rarity: 'uncommon', color: TRUCK_COLOR, emoji: '🚛',
    price: 130000,
    specs: {
      fuelPer100km: 26.0, cargoKg: 3000, maxSpeed: 100,
      hookable: ['trailer-small', 'trailer-medium', 'trailer-large'],
    },
  },
  {
    id: 'truck-heavy-1', slug: 'truck-heavy-1', category: 'truck', type: 'truck',
    name: 'Фура «Тяжеловоз»', rarity: 'rare', color: TRUCK_COLOR, emoji: '🚛',
    price: 240000,
    specs: {
      fuelPer100km: 38.0, cargoKg: 6000, maxSpeed: 90,
      hookable: ['trailer-medium', 'trailer-large', 'trailer-jumbo'],
    },
  },
]

// ── Прицепы (груз идёт в прицеп; расход = 0, тянет фура) ────────────────
const TRAILERS = [
  {
    id: 'trailer-small', slug: 'trailer-small', category: 'trailer', type: 'trailer',
    name: 'Прицеп «Малый»', rarity: 'common', color: TRAILER_COLOR, emoji: '🛻',
    price: 9000,
    specs: { fuelPer100km: 0, cargoKg: 2000, maxSpeed: 110 },
  },
  {
    id: 'trailer-medium', slug: 'trailer-medium', category: 'trailer', type: 'trailer',
    name: 'Прицеп «Средний»', rarity: 'uncommon', color: TRAILER_COLOR, emoji: '🛻',
    price: 22000,
    specs: { fuelPer100km: 0, cargoKg: 6000, maxSpeed: 100 },
  },
  {
    id: 'trailer-large', slug: 'trailer-large', category: 'trailer', type: 'trailer',
    name: 'Прицеп «Большой»', rarity: 'rare', color: TRAILER_COLOR, emoji: '🚛',
    price: 55000,
    specs: { fuelPer100km: 0, cargoKg: 15000, maxSpeed: 90 },
  },
  {
    id: 'trailer-jumbo', slug: 'trailer-jumbo', category: 'trailer', type: 'trailer',
    name: 'Прицеп «Джамбо»', rarity: 'epic', color: TRAILER_COLOR, emoji: '🚛',
    price: 130000,
    specs: { fuelPer100km: 0, cargoKg: 30000, maxSpeed: 80 },
  },
]

// Сводный каталог для вкладки «Автосалон». Сортируем по секции и цене, чтобы
// витрина выглядела единообразно.
export const CARS_CATALOG = [...CARS, ...TRUCKS, ...TRAILERS].sort(
  (a, b) => a.price - b.price,
)

// Списки для фильтр-пилюль (порядок именно такой: машины → фуры → прицепы).
export const CAR_SECTIONS = [
  { id: 'all',      label: 'cars.cat_all',      fallback: 'Все' },
  { id: 'car',      label: 'cars.cat_car',      fallback: 'Машины' },
  { id: 'truck',    label: 'cars.cat_truck',    fallback: 'Фуры' },
  { id: 'trailer',  label: 'cars.cat_trailer',  fallback: 'Прицепы' },
]
