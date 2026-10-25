export const VOLATILITY_PERIODS = {
  hour: 3600,
  day: 86400,
  week: 604800,
  month: 2592000,
}

export function convertVolatility(value, period) {
  const sourceSeconds = VOLATILITY_PERIODS[period]
  const hourly = Number(value) * Math.sqrt(VOLATILITY_PERIODS.hour / sourceSeconds)
  return Object.fromEntries(
    Object.entries(VOLATILITY_PERIODS).map(([key, seconds]) => [
      key,
      hourly * Math.sqrt(seconds / VOLATILITY_PERIODS.hour),
    ]),
  )
}
