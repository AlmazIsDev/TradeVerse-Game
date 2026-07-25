import { useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Самодостаточный canvas-график (без внешних зависимостей).
 * Поддерживает: линию и свечи, наведение с подсказкой, зум колёсиком,
 * перемещение перетаскиванием, плавную перерисовку под devicePixelRatio.
 *
 * props: candles [{t,o,h,l,c}], line [{t,p}], type 'line'|'candle',
 *        color, height, up, down
 */
function PriceChart({ candles = [], line = [], type = 'line', color = '#0071e3', height = 340, up = '#34c759', down = '#ff3b30' }) {
  const { t: translate } = useTranslation()
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const view = useRef({ start: 0, count: 0 })
  const hover = useRef(-1)
  const drag = useRef(null)
  // Подпись «нет данных» читаем из ref внутри canvas-draw, чтобы не тянуть t в его зависимости.
  const noDataLabel = useRef('')
  noDataLabel.current = translate('chart.noData')

  const data = type === 'candle' ? candles : line
  const len = data.length

  const fmtPrice = (p) => {
    if (p == null) return ''
    if (p >= 1000) return p.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
    if (p >= 1) return p.toFixed(2)
    return p.toFixed(4)
  }
  const fmtTime = (t) => {
    const d = new Date(t * 1000)
    if (isNaN(d.getTime())) return ''
    return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  }

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return
    const dpr = window.devicePixelRatio || 1
    const W = wrap.clientWidth
    const H = height
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    canvas.style.width = W + 'px'
    canvas.style.height = H + 'px'
    const ctx = canvas.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)

    // Хром графика (сетка, оси, кроссхэйр, подсказка) зависит от темы —
    // canvas не видит CSS-переменные, поэтому подбираем палитру по data-theme.
    const dark = document.documentElement.getAttribute('data-theme') === 'dark'
    const C = dark ? {
      grid: 'rgba(255,255,255,0.08)', axis: '#8e8e93', crosshair: 'rgba(255,255,255,0.28)',
      tipBg: 'rgba(28,28,30,0.94)', tipBorder: 'rgba(255,255,255,0.14)', tipText: '#f5f5f7', tipSub: '#8e8e93',
    } : {
      grid: 'rgba(0,0,0,0.07)', axis: '#86868b', crosshair: 'rgba(0,0,0,0.22)',
      tipBg: 'rgba(255,255,255,0.94)', tipBorder: 'rgba(0,0,0,0.10)', tipText: '#1d1d1f', tipSub: '#86868b',
    }

    const padL = 10, padR = 62, padT = 14, padB = 24
    const plotW = W - padL - padR
    const plotH = H - padT - padB

    if (len < 2) {
      ctx.fillStyle = C.axis
      ctx.font = '13px -apple-system, Inter, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(noDataLabel.current, W / 2, H / 2)
      return
    }

    let { start, count } = view.current
    if (count <= 0 || count > len) count = len
    if (start < 0) start = 0
    if (start + count > len) start = len - count
    view.current = { start, count }

    const vis = data.slice(start, start + count)
    let min = Infinity, max = -Infinity
    for (const d of vis) {
      if (type === 'candle') { min = Math.min(min, d.l); max = Math.max(max, d.h) }
      else { min = Math.min(min, d.p); max = Math.max(max, d.p) }
    }
    if (!isFinite(min) || !isFinite(max)) return
    const pad = (max - min) * 0.08 || max * 0.05 || 1
    min -= pad; max += pad
    const range = max - min || 1

    const xAt = (i) => padL + (count === 1 ? plotW / 2 : (i / (count - 1)) * plotW)
    // Свечи центрируем в равных слотах, иначе крайние свечи наполовину срезаются
    // паддингом (правая уходит под подписи оси цены).
    const xCandle = (i) => padL + (i + 0.5) * (plotW / count)
    const yAt = (p) => padT + (1 - (p - min) / range) * plotH

    // Сетка + ось цены
    ctx.strokeStyle = C.grid
    ctx.fillStyle = C.axis
    ctx.font = '11px -apple-system, Inter, sans-serif'
    ctx.lineWidth = 1
    ctx.textAlign = 'left'
    const gridN = 5
    for (let g = 0; g <= gridN; g++) {
      const y = padT + (g / gridN) * plotH
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke()
      const price = max - (g / gridN) * range
      ctx.fillText('$' + fmtPrice(price), padL + plotW + 6, y + 3)
    }
    // Ось времени
    ctx.textAlign = 'center'
    const xTick = type === 'candle' ? xCandle : xAt
    const ticks = Math.min(5, count)
    for (let g = 0; g < ticks; g++) {
      const i = Math.round((g / Math.max(1, ticks - 1)) * (count - 1))
      const x = xTick(i)
      ctx.fillText(fmtTime(vis[i].t), Math.min(Math.max(x, 28), padL + plotW - 28), H - 7)
    }

    if (type === 'candle') {
      const cw = Math.max(1, Math.round((plotW / count) * 0.7))
      for (let i = 0; i < count; i++) {
        const d = vis[i]
        // Пиксельное выравнивание: дробные координаты на canvas дают размытый
        // фитиль и «исчезающее» тело у доджи (o==c). Округляем к device-px.
        const x = Math.round(xCandle(i)) + 0.5
        const bull = d.c >= d.o
        ctx.strokeStyle = bull ? up : down
        ctx.fillStyle = bull ? up : down
        ctx.beginPath(); ctx.moveTo(x, Math.round(yAt(d.h))); ctx.lineTo(x, Math.round(yAt(d.l))); ctx.stroke()
        const yo = Math.round(yAt(d.o)), yc = Math.round(yAt(d.c))
        const top = Math.min(yo, yc)
        const bx = Math.round(x - cw / 2)
        ctx.fillRect(bx, top, cw, Math.max(1, Math.abs(yc - yo)))
      }
    } else {
      // Заливка-градиент под линией
      const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH)
      grad.addColorStop(0, color + '44')
      grad.addColorStop(1, color + '00')
      ctx.beginPath()
      ctx.moveTo(xAt(0), yAt(vis[0].p))
      for (let i = 1; i < count; i++) ctx.lineTo(xAt(i), yAt(vis[i].p))
      ctx.lineTo(xAt(count - 1), padT + plotH)
      ctx.lineTo(xAt(0), padT + plotH)
      ctx.closePath()
      ctx.fillStyle = grad
      ctx.fill()
      // Линия
      ctx.beginPath()
      ctx.moveTo(xAt(0), yAt(vis[0].p))
      for (let i = 1; i < count; i++) ctx.lineTo(xAt(i), yAt(vis[i].p))
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.lineJoin = 'round'
      ctx.stroke()
    }

    // Кроссхэйр + подсказка
    const h = hover.current
    if (h >= 0 && h < count) {
      const d = vis[h]
      const x = type === 'candle' ? xCandle(h) : xAt(h)
      const py = type === 'candle' ? yAt(d.c) : yAt(d.p)
      ctx.strokeStyle = C.crosshair
      ctx.setLineDash([4, 4])
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(padL, py); ctx.lineTo(padL + plotW, py); ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = color
      ctx.beginPath(); ctx.arc(x, py, 3.5, 0, Math.PI * 2); ctx.fill()

      const label = type === 'candle'
        ? `O ${fmtPrice(d.o)} H ${fmtPrice(d.h)} L ${fmtPrice(d.l)} C ${fmtPrice(d.c)}`
        : `$${fmtPrice(d.p)}`
      const timeLabel = fmtTime(d.t)
      ctx.font = '11px -apple-system, Inter, sans-serif'
      const tw = Math.max(ctx.measureText(label).width, ctx.measureText(timeLabel).width) + 16
      let bx = x + 10
      if (bx + tw > padL + plotW) bx = x - tw - 10
      ctx.fillStyle = C.tipBg
      ctx.strokeStyle = C.tipBorder
      ctx.beginPath()
      ctx.roundRect(bx, padT + 6, tw, 38, 8)
      ctx.fill(); ctx.stroke()
      ctx.fillStyle = C.tipText
      ctx.textAlign = 'left'
      ctx.fillText(label, bx + 8, padT + 22)
      ctx.fillStyle = C.tipSub
      ctx.fillText(timeLabel, bx + 8, padT + 37)
    }
  }, [data, len, type, color, height, up, down])

  // Сброс окна при смене данных
  useEffect(() => {
    view.current = { start: 0, count: len }
    hover.current = -1
    draw()
  }, [len, type, draw])

  // Ресайз
  useEffect(() => {
    const ro = new ResizeObserver(() => draw())
    if (wrapRef.current) ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [draw])

  // Перерисовка при смене темы — хром графика зависит от data-theme.
  useEffect(() => {
    const onTheme = () => draw()
    window.addEventListener('tv:theme', onTheme)
    return () => window.removeEventListener('tv:theme', onTheme)
  }, [draw])

  const idxFromEvent = (e) => {
    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()
    const W = rect.width
    const padL = 10, padR = 62
    const plotW = W - padL - padR
    const { count } = view.current
    const rel = (e.clientX - rect.left - padL) / plotW
    const raw = type === 'candle' ? rel * count - 0.5 : rel * (count - 1)
    return Math.max(0, Math.min(count - 1, Math.round(raw)))
  }

  const onMove = (e) => {
    if (drag.current) {
      const rect = canvasRef.current.getBoundingClientRect()
      const plotW = rect.width - 72
      const { count } = view.current
      const perPx = count / plotW
      const shift = Math.round((drag.current.x - e.clientX) * perPx)
      view.current.start = drag.current.start + shift
      draw()
      return
    }
    hover.current = idxFromEvent(e)
    draw()
  }
  const onLeave = () => { hover.current = -1; drag.current = null; draw() }
  const onDown = (e) => { drag.current = { x: e.clientX, start: view.current.start } }
  const onUp = () => { drag.current = null }
  const onWheel = useCallback((e) => {
    e.preventDefault()
    const { start, count } = view.current
    const center = hover.current >= 0 ? start + hover.current : start + count / 2
    const factor = e.deltaY < 0 ? 0.85 : 1.18
    let newCount = Math.round(count * factor)
    newCount = Math.max(8, Math.min(len, newCount))
    let newStart = Math.round(center - (center - start) * (newCount / count))
    newStart = Math.max(0, Math.min(len - newCount, newStart))
    view.current = { start: newStart, count: newCount }
    draw()
  }, [len, draw])

  // React onWheel — пассивный слушатель, поэтому preventDefault() не работает и
  // страница прокручивается при зуме. Вешаем вручную с { passive: false }.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [onWheel])

  return (
    <div className="price-chart-wrap" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        style={{ display: 'block', cursor: drag.current ? 'grabbing' : 'crosshair', touchAction: 'none' }}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
        onMouseDown={onDown}
        onMouseUp={onUp}
      />
    </div>
  )
}

export default PriceChart
