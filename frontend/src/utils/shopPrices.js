const STORAGE_KEY = 'tradeverse_shop_prices'

/**
 * Загрузить все цены из localStorage
 * @returns {Object} маппинг productId -> price
 */
export function loadShopPrices() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return {}
}

/**
 * Получить цену товара по ID
 * @param {number} productId - ID товара
 * @param {number|null} defaultPrice - цена по умолчанию из массива товаров
 * @returns {number|null} цена товара
 */
export function getShopPrice(productId, defaultPrice) {
  const prices = loadShopPrices()
  const storedPrice = prices[productId]
  if (storedPrice !== undefined && storedPrice !== null) {
    return storedPrice
  }
  return defaultPrice
}

/**
 * Применить сохранённые цены к массиву товаров
 * @param {Array} products - массив товаров с полем id и price
 * @returns {Array} массив товаров с применёнными ценами
 */
export function applyShopPrices(products) {
  const prices = loadShopPrices()
  return products.map(p => ({
    ...p,
    price: (prices[p.id] !== undefined && prices[p.id] !== null) ? prices[p.id] : p.price,
  }))
}
