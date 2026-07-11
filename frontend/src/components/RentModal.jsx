import { useTranslation } from 'react-i18next'
import { formatMoney } from './TransactionsPanel'
import { X, KeyRound } from 'lucide-react'

// Фиксированные сроки аренды (часы) — совпадают с backend/assets.py RENT_DURATIONS_H.
const DURATIONS = [
  { hours: 24, key: '1d' },
  { hours: 48, key: '2d' },
  { hours: 72, key: '3d' },
  { hours: 144, key: '6d' },
  { hours: 288, key: '12d' },
  { hours: 336, key: '14d' },
  { hours: 384, key: '16d' },
  { hours: 720, key: '1m' },
]

/**
 * Модалка выбора срока аренды. Цена для каждого срока приходит с сервера
 * (asset.rentQuotes) — расчитана от стоимости актива, клиент её не задаёт.
 */
function RentModal({ asset, busy, onConfirm, onClose }) {
  const { t } = useTranslation()
  const quotes = asset?.rentQuotes || []
  const priceFor = (hours) => quotes.find(q => q.hours === hours)?.price ?? 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <h3><KeyRound size={17} /> {t('rent.title')}: {asset?.name}</h3>
        <p className="modal-price">{t('rent.desc')}</p>
        <div className="rent-duration-grid">
          {DURATIONS.map(d => (
            <button key={d.hours} className="rent-duration-btn" disabled={busy}
              onClick={() => onConfirm(d.hours)}>
              <span className="rent-duration-label">{t(`rent.duration.${d.key}`)}</span>
              <span className="rent-duration-price">${formatMoney(priceFor(d.hours))}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export default RentModal
