/**
 * Число из поля ввода. Русская локаль печатает дробь с запятой, а `Number('26,4')`
 * даёт NaN — из-за этого котировка не запрашивалась и вся разбивка показывала $0,00.
 */
export function parseQty(value, market) {
  const n = Number(String(value ?? '').replace(',', '.').replace(/\s/g, ''))
  if (!Number.isFinite(n)) return 0
  return market === 'stock' ? Math.floor(n) : n
}

/**
 * Приводит вычисленное количество к строке для поля ввода: точка как разделитель
 * (иначе Number снова упрётся в запятую), акции — целыми.
 */
export function quantizeQty(value, market) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return ''
  if (market === 'stock') return String(Math.floor(n))
  // Обрезаем, а не округляем: округление вверх вылезет за доступный остаток.
  return String(Math.floor(n * 1e8) / 1e8)
}
