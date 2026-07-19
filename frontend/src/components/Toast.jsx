import { useState, useEffect, useCallback, useRef } from 'react'
import { Check, AlertTriangle, Info, X } from 'lucide-react'

// Глобальные тосты через window-событие 'tv:toast' — тот же паттерн шины, что
// уже используется в проекте (tv:realtime, tv:notif). Любой компонент вызывает
// toast(text, type) без проброса контекста. Один <ToastHost/> в Dashboard.
const TTL_MS = 3200
let seq = 0

export function toast(text, type = 'success') {
  if (!text) return
  try {
    window.dispatchEvent(new CustomEvent('tv:toast', { detail: { text, type } }))
  } catch { /* ignore */ }
}

const ICONS = { success: Check, error: AlertTriangle, info: Info }

function ToastHost() {
  const [items, setItems] = useState([])   // [{ id, text, type }]
  const timers = useRef([])

  const dismiss = useCallback((id) => {
    setItems(prev => prev.filter(i => i.id !== id))
  }, [])

  useEffect(() => {
    const onToast = (ev) => {
      const { text, type = 'success' } = ev.detail || {}
      if (!text) return
      const id = ++seq
      setItems(prev => [...prev, { id, text, type }].slice(-4))
      const timer = setTimeout(() => dismiss(id), TTL_MS)
      timers.current.push(timer)
    }
    window.addEventListener('tv:toast', onToast)
    return () => {
      window.removeEventListener('tv:toast', onToast)
      timers.current.forEach(clearTimeout)
      timers.current = []
    }
  }, [dismiss])

  if (items.length === 0) return null

  return (
    <div className="tv-toast-stack" role="status" aria-live="polite">
      {items.map(item => {
        const Icon = ICONS[item.type] || Info
        return (
          <div key={item.id} className={`tv-toast tv-toast-${item.type}`}>
            <span className="tv-toast-icon"><Icon size={16} /></span>
            <span className="tv-toast-text">{item.text}</span>
            <button className="tv-toast-close" onClick={() => dismiss(item.id)} aria-label="close">
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default ToastHost
