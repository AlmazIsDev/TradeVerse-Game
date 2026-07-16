// Единый источник правды для оформления.
//
// Две независимые оси, обе сохраняются в localStorage и применяются к
// <html>, переопределяя только слой токенов в index.css — вся дизайн-система
// реагирует автоматически:
//
//   • База (data-theme):  'light' | 'dark' | 'tradeverse'
//        полные палитры поверхностей/текста/теней.
//   • Акцент:             'default' | '<hex>'
//        переопределяет семейство --color-accent инлайн-переменными поверх
//        любой базы. 'default' — снять оверрайды (берётся акцент базы).
//
// Первичное применение (до отрисовки, чтобы не было вспышки) делает встроенный
// скрипт в index.html; здесь — рантайм-переключение и подписка (событие
// 'tv:theme' для canvas-графиков, которые не видят CSS-переменные).

export const THEME_KEY = 'tradeverse_theme'
export const ACCENT_KEY = 'tradeverse_accent'
export const BASES = ['light', 'dark', 'tradeverse']

// Готовые акценты (кроме «своего» цвета). null — акцент базовой палитры.
export const ACCENT_PRESETS = {
  default: null,
  green: '#34c759',
}

const META_BG = { light: '#f5f5f7', dark: '#000000', tradeverse: '#0f1117' }

// ── helpers ──────────────────────────────────────────────────────────────
function clamp(n) { return Math.max(0, Math.min(255, Math.round(n))) }

/** '#rgb' | '#rrggbb' → {r,g,b} | null. */
export function hexToRgb(hex) {
  if (typeof hex !== 'string') return null
  let h = hex.trim().replace(/^#/, '')
  if (h.length === 3) h = h.split('').map(c => c + c).join('')
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null
  return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) }
}

function rgbToHex({ r, g, b }) {
  return '#' + [r, g, b].map(v => clamp(v).toString(16).padStart(2, '0')).join('')
}

/** Осветлить/затемнить: ratio>0 к белому, <0 к чёрному. */
function shade({ r, g, b }, ratio) {
  const t = ratio < 0 ? 0 : 255
  const p = Math.abs(ratio)
  return { r: r + (t - r) * p, g: g + (t - g) * p, b: b + (t - b) * p }
}

/** Относительная яркость (WCAG) 0..1 — для выбора контрастного текста. */
function luminance({ r, g, b }) {
  const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

// ── state getters ──────────────────────────────────────────────────────────
export function getTheme() {
  if (typeof window === 'undefined') return 'light'
  const s = window.localStorage.getItem(THEME_KEY)
  return BASES.includes(s) ? s : 'light'
}

/** Текущий акцент: 'default' или hex-строка. */
export function getAccent() {
  if (typeof window === 'undefined') return 'default'
  const s = window.localStorage.getItem(ACCENT_KEY)
  if (!s || s === 'default') return 'default'
  return hexToRgb(s) ? s : 'default'
}

// ── apply ──────────────────────────────────────────────────────────────────
/** Применяет инлайн-акцент (или снимает его при 'default'). Экспортируется,
 *  чтобы boot-скрипт и рантайм шли одним путём. */
export function applyAccentVars(accent) {
  const root = document.documentElement
  const props = [
    '--color-accent', '--color-accent-hover', '--color-accent-active',
    '--accent-soft', '--accent-soft-hover', '--on-accent',
  ]
  if (!accent || accent === 'default') {
    props.forEach(p => root.style.removeProperty(p))
    return
  }
  const rgb = hexToRgb(accent)
  if (!rgb) { props.forEach(p => root.style.removeProperty(p)); return }
  const { r, g, b } = rgb
  const soft = a => `rgba(${r}, ${g}, ${b}, ${a})`
  root.style.setProperty('--color-accent', rgbToHex(rgb))
  root.style.setProperty('--color-accent-hover', rgbToHex(shade(rgb, 0.12)))
  root.style.setProperty('--color-accent-active', rgbToHex(shade(rgb, -0.08)))
  root.style.setProperty('--accent-soft', soft(0.14))
  root.style.setProperty('--accent-soft-hover', soft(0.22))
  // Контрастный текст на акценте — чтобы светлые пользовательские цвета
  // (жёлтый, салатовый) не давали белый текст на белом.
  root.style.setProperty('--on-accent', luminance(rgb) > 0.55 ? '#1d1d1f' : '#ffffff')
}

/** Применяет базовую тему (поверхности) + текущий/переданный акцент. */
export function applyTheme(base, accent = getAccent()) {
  const next = BASES.includes(base) ? base : 'light'
  const root = document.documentElement
  if (next === 'light') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', next)
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', META_BG[next] || META_BG.light)
  applyAccentVars(accent)
  try { window.localStorage.setItem(THEME_KEY, next) } catch { /* приватный режим */ }
  window.dispatchEvent(new CustomEvent('tv:theme', { detail: { base: next, accent } }))
  return next
}

/** Меняет только акцент, база не трогается. accent: 'default' | hex. */
export function setAccent(accent) {
  const value = accent === 'default' || hexToRgb(accent) ? accent : 'default'
  applyAccentVars(value)
  try { window.localStorage.setItem(ACCENT_KEY, value) } catch { /* приватный режим */ }
  window.dispatchEvent(new CustomEvent('tv:theme', { detail: { base: getTheme(), accent: value } }))
  return value
}

/** Быстрое переключение светлая ↔ тёмная (для основного тумблера). */
export function toggleTheme() {
  return applyTheme(getTheme() === 'dark' ? 'light' : 'dark')
}
