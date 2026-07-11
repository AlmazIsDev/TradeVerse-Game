import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { listPropertyForRent, cancelRent } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  LayoutGrid, Home, Car, Briefcase, KeyRound, X, Check, AlertTriangle, TrendingUp, Users,
} from 'lucide-react'

const TABS = [
  { id: 'all', icon: LayoutGrid },
  { id: 'realestate', icon: Home },
  { id: 'car', icon: Car },
  { id: 'business', icon: Briefcase },
]

const ASSET_EMOJI = {
  studio: '🏠', flat2: '🏢', townhouse: '🏘️', villa: '🏖️', penthouse: '🌆', castle: '🏰',
  shawarma: '🌯', coffee: '☕', carwash: '🚿', factory: '🏭',
  itstudio_basic: '💻', itstudio_medium: '💻', itstudio_advanced: '💻', itstudio_premium: '💻',
  citycar: '🚗', sedan: '🚙', sport: '🏎️', super: '🏎️',
}
const TYPE_EMOJI = { realestate: '🏠', business: '🏢', car: '🚗' }

// Пресеты срока аренды (в часах) — кнопки в модалке сдачи в аренду.
const RENT_DURATIONS = [
  { key: 'd1', hours: 24 }, { key: 'd2', hours: 48 }, { key: 'd4', hours: 96 },
  { key: 'd7', hours: 168 }, { key: 'd10', hours: 240 }, { key: 'd12', hours: 288 },
  { key: 'd14', hours: 336 }, { key: 'd16', hours: 384 }, { key: 'd18', hours: 432 },
  { key: 'd30', hours: 720 },
]
const RARITY_GRAD = {
  common: 'linear-gradient(135deg,#334155,#1e293b)',
  uncommon: 'linear-gradient(135deg,#166534,#14532d)',
  rare: 'linear-gradient(135deg,#1e40af,#1e3a8a)',
  epic: 'linear-gradient(135deg,#6b21a8,#4c1d95)',
  legendary: 'linear-gradient(135deg,#b45309,#78350f)',
}

/**
 * Активы компании — интерфейс, аналогичный «Моё имущество», с вкладками.
 * Недвижимость, авто и бизнесы можно сдавать в аренду — доход идёт в бюджет компании.
 * Видеть список могут все сотрудники, управлять арендой — только владелец.
 */
function CompanyAssetsPanel({ assets = [], isOwner = false, onClose, onRefresh }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState('all')
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)
  const [rentModal, setRentModal] = useState(null)
  const [rentForm, setRentForm] = useState({ minHours: '6' })

  const flash = (text, type = 'success') => { setMsg({ text, type }); setTimeout(() => setMsg(null), 2400) }
  const emojiFor = (a) => ASSET_EMOJI[a.slug] || TYPE_EMOJI[a.type] || '📦'
  const list = tab === 'all' ? assets : assets.filter(a => a.type === tab)

  const doCancel = async (id) => {
    setBusyId(id)
    try { await cancelRent(id); flash(t('rent.cancelled')); await onRefresh?.() }
    catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
  }

  const submitRent = async () => {
    if (!rentModal) return
    const minHours = Math.floor(Number(rentForm.minHours))
    if (!(minHours >= 1)) { flash(t('rent.invalid'), 'error'); return }
    setBusyId(rentModal.id)
    try {
      await listPropertyForRent(rentModal.id, minHours)
      flash(t('rent.listed'))
      setRentModal(null)
      await onRefresh?.()
    } catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
  }

  const renderRental = (a) => {
    if (a.type !== 'realestate' && a.type !== 'car' && a.type !== 'business') return null
    if (a.rental?.status === 'listed') {
      return (
        <div className="asset-rental listed">
          <KeyRound size={13} /> {t('rent.waiting')}
          {isOwner && (
            <button className="asset-rental-cancel" disabled={busyId === a.id} onClick={() => doCancel(a.id)}>{t('common.cancel')}</button>
          )}
        </div>
      )
    }
    if (a.rental?.status === 'rented') {
      return <div className="asset-rental rented"><KeyRound size={13} /> {t('rent.rented')} · ${formatMoney(a.rental.price)}</div>
    }
    if (!isOwner) return null
    return (
      <button className="asset-act" disabled={busyId === a.id}
        onClick={() => { setRentModal(a); setRentForm({ minHours: '6' }) }}>
        <KeyRound size={15} /> {t('rent.list')}
      </button>
    )
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content company-assets-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <h3><Briefcase size={18} /> {t('company.assets')}</h3>

        <div className="market-cats" style={{ margin: 'var(--spacing-md) 0' }}>
          {TABS.map(tb => {
            const Icon = tb.icon
            return (
              <button key={tb.id} className={`tx-pill ${tab === tb.id ? 'active' : ''}`} onClick={() => setTab(tb.id)}>
                <Icon size={14} /> {tb.id === 'all' ? t('common.all') : t(`market.cat_${tb.id}`)}
              </button>
            )
          })}
        </div>

        {msg && (
          <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
            {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
          </div>
        )}

        <p className="company-note">{t('company.rentNote')}</p>

        {list.length === 0 ? (
          <div className="empty-state">
            <span className="placeholder-icon">{TYPE_EMOJI[tab] || '📦'}</span>
            <p>{t('company.noAssets')}</p>
          </div>
        ) : (
          <div className="asset-grid">
            {list.map(a => {
              const isCar = a.type === 'car'
              return (
                <div key={a.id} className={`asset-card owned ${isCar ? 'car-card' : ''}`}>
                  <div className="asset-banner" style={{ background: RARITY_GRAD[a.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}>
                    <span className="asset-banner-emoji">{emojiFor(a)}</span>
                    <span className="asset-level">{t('myassets.level')} {a.level}</span>
                  </div>
                  <div className="asset-card-head"><span className="asset-name">{t(`assetNames.${a.slug}`, a.name)}</span></div>
                  <div className="asset-stats">
                    <div className="asset-stat"><span>{t('myassets.value')}</span><b>${formatMoney(a.value)}</b></div>
                    {!isCar && a.profitPerHour !== 0 && (
                      <div className="asset-stat"><span><TrendingUp size={12} /> {t('market.profitPerHour')}</span>
                        <b className={a.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(a.profitPerHour)}</b></div>
                    )}
                    {a.type === 'business' && (
                      <div className="asset-stat"><span><Users size={12} /> {t('market.employees')}</span><b>{a.employees}</b></div>
                    )}
                    {a.rooms != null && <div className="asset-stat"><span>{t('realestate.rooms')}</span><b>{a.rooms}</b></div>}
                  </div>
                  {renderRental(a)}
                </div>
              )
            })}
          </div>
        )}

        {rentModal && (
          <div className="modal-overlay" onClick={() => setRentModal(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <button className="crypto-modal-close" onClick={() => setRentModal(null)}><X size={18} /></button>
              <h3>{t('rent.title')}: {t(`assetNames.${rentModal.slug}`, rentModal.name)}</h3>
              <p className="modal-price">{t('company.rentDesc')}</p>
              <div className="rent-duration-grid">
                {RENT_DURATIONS.map(d => (
                  <button key={d.key} type="button"
                    className={`tx-pill ${Number(rentForm.minHours) === d.hours ? 'active' : ''}`}
                    onClick={() => setRentForm({ ...rentForm, minHours: String(d.hours) })}>
                    {t(`rent.${d.key}`)}
                  </button>
                ))}
              </div>
              <div className="modal-quantity"><label>{t('rent.custom')}:</label>
                <input type="number" min="1" max="720" value={rentForm.minHours} onChange={e => setRentForm({ ...rentForm, minHours: e.target.value })} /></div>
              <p className="rent-max-hint">{t('rent.ratePerHour', { rate: formatMoney(rentModal.rentRatePerHour) })}</p>
              <p className="modal-price">{t('rent.total')}: <b>${formatMoney((rentModal.rentRatePerHour || 0) * (Number(rentForm.minHours) || 0))}</b></p>
              <div className="modal-buttons">
                <button className="stock-btn buy-btn" onClick={submitRent} disabled={busyId === rentModal.id}>{t('rent.publish')}</button>
                <button className="stock-btn cancel-btn" onClick={() => setRentModal(null)}>{t('common.cancel')}</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default CompanyAssetsPanel
