import { convertVolatility, VOLATILITY_PERIODS } from './volatility.js'

const day = convertVolatility(14, 'day')
console.assert(Math.abs(day.hour - 2.857) < 0.001, day)
console.assert(Math.abs(day.day - 14) < 1e-9, day)
console.assert(Math.abs(day.week - 37.04) < 0.01, day)
console.assert(Math.abs(day.month - 76.68) < 0.01, day)

const hourly = convertVolatility(6, 'hour')
console.assert(Math.abs(hourly.day - 29.394) < 0.001, hourly)

const month = convertVolatility(50, 'month')
console.assert(Math.abs(month.day - 9.129) < 0.001, month)
console.assert(Object.keys(month).every(key => VOLATILITY_PERIODS[key]), month)
console.log('volatility OK')
