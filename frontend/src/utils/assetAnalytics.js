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

  // Диапазон цены за период + позиция текущей цены внутри него (0..100).
  // Считается ДО рекомендации: без этого сигнал был чисто трендовым и на самом
  // пике советовал «Покупать» тем громче, чем сильнее актив уже вырос.
  const price = asset.price || 0
  let periodLow = null, periodHigh = null, rangePos = null
  if (line.length) {
    periodLow = Math.min(...line.map(p => p.p))
    periodHigh = Math.max(...line.map(p => p.p))
    if (periodHigh > periodLow) {
      rangePos = clamp(Math.round(((price - periodLow) / (periodHigh - periodLow)) * 100), 0, 100)
    }
  }

  // Просадка от исторического максимума — насколько актив «на дне».
  const ath = asset.ath ?? asset.stats?.ath ?? null
  const drawdown = ath && ath > 0 && price > 0
    ? Math.round(((price - ath) / ath) * 1000) / 10
    : null

  // Растянутость: +1 — цена у максимума диапазона, −1 — у минимума.
  const stretch = rangePos == null ? 0 : (rangePos - 50) / 50

  // Возврат к среднему. Чем сильнее разгон и волатильность, тем больнее откат
  // от верхней границы — и тем привлекательнее вход у нижней.
  const reversion = -stretch * Math.min(40, Math.abs(momentum) * 0.4 + volatility * 1.2)

  // Итоговый сигнал: тренд, скорректированный на то, дорого ли сейчас.
  const signal = momentum * 0.55 + reversion

  // Вероятность роста.
  const probUp = clamp(Math.round(50 + signal * 1.2), 5, 95)

  // Ожидаемая доходность (проекция следующего периода), гасится волатильностью.
  const expectedReturn = Math.round((signal * 0.6 - volatility * 0.05) * 10) / 10

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

  // Перегрев: цена у верха диапазона после сильного роста. Покупать здесь —
  // покупать чужую прибыль, поэтому такой сигнал никогда не даёт «buy».
  const overheated = rangePos != null && rangePos >= 85 && momentum > 15
  const oversold = rangePos != null && rangePos <= 15 && momentum < -15

  // Рекомендация.
  let recommendation = 'hold'
  if (overheated) recommendation = momentum > 60 ? 'sell' : 'hold'
  else if (oversold) recommendation = 'buy'
  else if (probUp >= 62 && expectedReturn > 0) recommendation = 'buy'
  else if (probUp <= 40 || expectedReturn < -3) recommendation = 'sell'

  // Ликвидность: доля дневного оборота от капитализации. Низкая ликвидность
  // означает, что крупную позицию будет трудно продать без обвала цены.
  const turnover = cap > 0 ? (vol24 / cap) * 100 : null
  const liquidity = turnover == null ? null
    : turnover >= 5 ? 'high' : turnover >= 1 ? 'medium' : 'low'

  // Сила тренда: насколько согласованы разные горизонты (все вверх / все вниз).
  const horizons = [c24, c7, c1m].filter(v => v != null)
  const agree = horizons.filter(v => (v >= 0) === (momentum >= 0)).length
  const trendStrength = horizons.length
    ? Math.round((agree / horizons.length) * 100)
    : 50

  // Соотношение риск/доходность — сколько ожидаемой доходности на единицу риска.
  const riskReward = volatility > 0
    ? Math.round((expectedReturn / volatility) * 100) / 100
    : 0

  return {
    volatility, momentum, probUp, expectedReturn,
    risk, popularity, recommendation, dividendYield,
    c24, c7, c1m, c1y, up: momentum >= 0,
    periodLow, periodHigh, rangePos, drawdown,
    turnover: turnover == null ? null : Math.round(turnover * 100) / 100,
    liquidity, trendStrength, riskReward,
    overheated, oversold,
  }
}

export default computeAnalytics

/** Самопроверка: node src/utils/assetAnalytics.js */
export function demo() {
  const rising = Array.from({ length: 40 }, (_, i) => ({ t: i, p: 800 + i * 5 }))
  const peak = computeAnalytics(
    { price: 1000, symbol: 'RUBY', stats: { changes: { '24h': 131, '7d': 131, '1m': 152 } } },
    { line: rising }, 'crypto',
  )
  // Главный регресс: на верхней границе диапазона после +131% нельзя советовать покупку.
  console.assert(peak.rangePos >= 85, 'цена должна быть у верха диапазона')
  console.assert(peak.overheated, 'сильный рост на пике = перегрев')
  console.assert(peak.recommendation !== 'buy', 'на пике не должно быть «Покупать»')

  const falling = Array.from({ length: 40 }, (_, i) => ({ t: i, p: 1000 - i * 5 }))
  const bottom = computeAnalytics(
    { price: 805, symbol: 'RUBY', stats: { changes: { '24h': -30, '7d': -35, '1m': -40 } } },
    { line: falling }, 'crypto',
  )
  console.assert(bottom.rangePos <= 15, 'цена должна быть у низа диапазона')
  console.assert(bottom.recommendation === 'buy', 'на дне после распродажи ожидаем «Покупать»')

  // Без истории аналитика не должна падать.
  const bare = computeAnalytics({ price: 10, symbol: 'X' }, {}, 'stock')
  console.assert(bare.rangePos === null && bare.recommendation, 'работает без истории цен')

  console.log('assetAnalytics OK', {
    peak: peak.recommendation, bottom: bottom.recommendation, bare: bare.recommendation,
  })
}

if (typeof process !== 'undefined' && process.argv?.[1]?.includes('assetAnalytics')) demo()
