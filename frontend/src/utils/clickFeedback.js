const TARGET_SELECTOR = 'button, a, [role="button"], [role="tab"], [role="menuitem"], input[type="checkbox"], input[type="radio"], .tx-pill, .tv-clickable'
const RIPPLE_MS = 650

export function installClickFeedback() {
  if (window.__tvClickFeedback) return
  window.__tvClickFeedback = true

  document.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return
    const el = e.target instanceof Element ? e.target.closest(TARGET_SELECTOR) : null
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return

    const rect = el.getBoundingClientRect()
    const size = Math.max(rect.width, rect.height) * 2
    const ripple = document.createElement('span')
    ripple.className = 'tv-ripple'
    ripple.style.width = ripple.style.height = `${size}px`
    ripple.style.left = `${e.clientX - rect.left - size / 2}px`
    ripple.style.top = `${e.clientY - rect.top - size / 2}px`

    const computed = getComputedStyle(el)
    if (computed.position === 'static') el.style.position = 'relative'
    if (computed.overflow !== 'hidden') el.classList.add('tv-ripple-host')

    el.appendChild(ripple)
    el.classList.add('tv-pressed')
    setTimeout(() => ripple.remove(), RIPPLE_MS)
  }, { passive: true })

  const release = (e) => {
    const el = e.target instanceof Element ? e.target.closest('.tv-pressed') : null
    if (el) el.classList.remove('tv-pressed')
  }
  document.addEventListener('pointerup', release, { passive: true })
  document.addEventListener('pointercancel', release, { passive: true })
  document.addEventListener('pointerleave', release, { passive: true, capture: true })
}
