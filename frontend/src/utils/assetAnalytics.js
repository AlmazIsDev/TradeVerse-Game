// Клиентская аналитика актива (крипта/акции) на основе данных, которые уже
// возвращают эндпоинты /api/market/asset и /api/market/history.
// Никаких случайных значений: всё детерминировано, чтобы показатели были
// стабильны между перерисовками (иначе цифры «прыгали» бы на каждом рендере).

// Простой детерминированный хеш по символу — для «популярности»/«дивидендов».
function symbolHash(symbol = '') {
  let h = 0
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) % 100000
  return h
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

/**
 * @param {object} asset   ответ /market/asset (price, stats.changes, marketCap, volume24h, heldQuantity, changePercent)
 * @param {object} history ответ /market/history ({ line: [{t,p}], candles: [...] })
 * @param {string} market  'crypto' | 'stock'
 */
export function computeAnalytics(asset = {}, history = {}, market = 'crypto') {
  const changes = asset.stats?.changes || {}
  const c24 = changes['24h'] ?? asset.changePercent ?? 0
  const c7 = changes['7d'] ?? 0
  const c1m = changes['1m'] ?? 0
  const c1y = changes['1y'] ?? null

  // Волатильность = стандартное отклонение дневной доходности по линии цены.
  const line = history.line || []
  let volatility = null
  if (line.length > 3) {
    const rets = []
    for (let i = 1; i < line.length; i++) {
      const a = line[i - 1].p, b = line[i].p
      if (a > 0) rets.push((b - a) / a)
    }
    if (rets.length) {
      const mean = rets.reduce((s, x) => s + x, 0) / rets.length
      const variance = rets.reduce((s, x) => s + (x - mean) ** 2, 0) / rets.length
      volatility = Math.sqrt(variance) * 100
    }
  }
  if (volatility == null) volatility = Math.min(30, Math.abs(c24) * 1.5 + 4)
  volatility = Math.round(volatility * 10) / 10

  // Импульс — взвешенное изменение по разным горизонтам.
  const momentum = c24 * 0.5 + c7 * 0.3 + c1m * 0.2

  // Вероятность роста.
  const probUp = clamp(Math.round(50 + momentum * 1.2), 5, 95)

  // Ожидаемая доходность (проекция следующего периода), гасится волатильностью.
  const expectedReturn = Math.round((momentum * 0.6 - volatility * 0.05) * 10) / 10

  // Уровень риска по волатильности.
  const risk = volatility >= 18 ? 'high' : volatility >= 8 ? 'medium' : 'low'

  // Популярность 5..99 — смесь отношения объёма к капитализации и хеша символа.
  const cap = asset.marketCap || 0
  const vol24 = asset.volume24h || 0
  let popularity = cap > 0 ? clamp((vol24 / cap) * 800 + 30, 0, 99) : 50
  const h = symbolHash(asset.symbol)
  popularity = clamp(Math.round(popularity * 0.6 + ((h % 40) + 30) * 0.4), 5, 99)

  // Прогноз дивидендов (только акции): детерминированная доходность 0..5%.
  const dividendYield = market === 'stock'
    ? Math.round(((h % 55) / 10) * 10) / 10   // 0.0 .. 5.4 -> округляем
    : 0

  // Рекомендация.
  let recommendation = 'hold'
  if (probUp >= 62 && expectedReturn > 0) recommendation = 'buy'
  else if (probUp <= 40 || expectedReturn < -3) recommendation = 'sell'

  return {
    volatility, momentum, probUp, expectedReturn,
    risk, popularity, recommendation, dividendYield,
    c24, c7, c1m, c1y, up: momentum >= 0,
  }
}

export default computeAnalytics
