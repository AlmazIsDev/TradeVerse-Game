// Изображения активов рынка (backend/assets.py CATALOG) — по одной картинке на
// slug. Файлы лежат рядом, в assets/market/, и подтягиваются сборщиком: Vite сам
// проставит хеш и положит их в dist, поэтому путь нельзя собирать строкой.
const FILES = import.meta.glob('../assets/market/*.{jpg,png,webp}', {
  eager: true,
  query: '?url',
  import: 'default',
})

const BY_SLUG = Object.fromEntries(
  Object.entries(FILES).map(([path, url]) => [path.split('/').pop().replace(/\.\w+$/, ''), url]),
)

// Запасной вариант для активов, у которых своей картинки нет (например, новый
// slug в каталоге появился раньше, чем изображение) — берём любую картинку того
// же типа, а если и её нет, карточка покажет эмодзи (см. ASSET_EMOJI).
const TYPE_FALLBACK = { realestate: 'flat2', business: 'coffee', car: 'sedan' }

export function assetImage(slug, type) {
  return BY_SLUG[slug] || BY_SLUG[TYPE_FALLBACK[type]] || null
}

export default assetImage
