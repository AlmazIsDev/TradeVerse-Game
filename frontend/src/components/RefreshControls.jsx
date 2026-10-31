// RefreshControls · выбор интервала авто-обновления (select 5с/15с/30с/1мин) и
// кнопка ручного обновления. Живёт внутри интерфейса конкретного актива
// (AssetDetail — тулбар графика). Интервал хранится в localStorage
// ('refreshIntervalMs') и общий для крипты и акций.
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw } from 'lucide-react'

export const REFRESH_OPTIONS = [5000, 15000, 30000, 60000]

export function loadRefreshInterval() {
  const v = Number(localStorage.getItem('refreshIntervalMs'))
  return REFRESH_OPTIONS.includes(v) ? v : 15000
}

// Авто-обновление по выбранному интервалу (onRefresh — стабильный useCallback).
export function useAutoRefresh(onRefresh, intervalMs) {
  useEffect(() => {
    if (!intervalMs) return undefined
    const id = setInterval(onRefresh, intervalMs)
    return () => clearInterval(id)
  }, [onRefresh, intervalMs])
}

export default function RefreshControls({ intervalMs, onIntervalChange, onRefresh, busy = false }) {
  const { t } = useTranslation()
  const label = (ms) => (ms >= 60000
    ? t('refresh.min', { n: ms / 60000 })
    : t('refresh.sec', { n: ms / 1000 }))
  return (
    <div className="refresh-controls">
      <select
        className="refresh-select"
        value={intervalMs}
        disabled={busy}
        onChange={e => onIntervalChange(Number(e.target.value))}
        title={t('refresh.auto')}
        aria-label={t('refresh.auto')}
      >
        {REFRESH_OPTIONS.map(ms => (
          <option key={ms} value={ms}>{label(ms)}</option>
        ))}
      </select>
      <button
        type="button"
        className="refresh-btn"
        disabled={busy}
        onClick={onRefresh}
        title={t('refresh.now')}
        aria-label={t('refresh.now')}
      >
        <RefreshCw size={15} className={busy ? 'refresh-spin' : ''} />
      </button>
    </div>
  )
}
