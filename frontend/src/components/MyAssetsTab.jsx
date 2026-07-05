import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMyAssets, collectAsset, upgradeAsset, sellAsset,
  transferAssetToCompany, listPropertyForRent, cancelRent,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  Home, Car, Briefcase, ArrowUpCircle, HandCoins, Trash2, AlertTriangle,
  TrendingUp, Users, Wallet, Building2, KeyRound, Check, X, Gauge,
} from 'lucide-react'

const TYPE_TABS = [
  { id: 'realestate', icon: Home },
  { id: 'car', icon: Car },
  { id: 'business', icon: Briefcase },
]

// «Изображения» объектов (эмодзи-баннеры вместо фото — работает без внешних ассетов)
const ASSET_EMOJI = {
  studio: '🏠', flat2: '🏢', townhouse: '🏘️', villa: '🏖️', penthouse: '🌆', castle: '🏰',
  shawarma: '🌯', coffee: '☕', carwash: '🚿', itstudio: '💻', factory: '🏭',
  citycar: '🚗', sedan: '🚙', sport: '🏎️', super: '🏎️',
}
const TYPE_EMOJI = { realestate: '🏠', business: '🏢', car: '🚗' }
const RARITY_GRAD = {
  common: 'linear-gradient(135deg,#334155,#1e293b)',
  uncommon: 'linear-gradient(135deg,#166534,#14532d)',
  rare: 'linear-gradient(135deg,#1e40af,#1e3a8a)',
  epic: 'linear-gradient(135deg,#6b21a8,#4c1d95)',
  legendary: 'linear-gradient(135deg,#b45309,#78350f)',
}

function MyAssetsTab({ defaultType = 'realestate', balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [activeType, setActiveType] = useState(defaultType)
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)
  const [rentModal, setRentModal] = useState(null)   // asset
  const [rentForm, setRentForm] = useState({ price: '', minHours: '6' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchMyAssets()
      setAssets(data.assets || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 2400)
  }

  const act = async (id, fn, okKey) => {
    setBusyId(id)
    try {
      const res = await fn(id)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t(okKey))
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const submitRent = async () => {
    if (!rentModal) return
    const price = Number(rentForm.price)
    const minHours = Math.floor(Number(rentForm.minHours))
    if (!(price > 0) || !(minHours >= 1)) { flash(t('rent.invalid'), 'error'); return }
    setBusyId(rentModal.id)
    try {
      await listPropertyForRent(rentModal.id, price, minHours)
      flash(t('rent.listed'))
      setRentModal(null)
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const list = assets.filter(a => a.type === activeType)
  const totalValue = list.reduce((s, a) => s + (a.value || 0), 0)
  const totalProfit = list.reduce((s, a) => s + (a.profitPerHour || 0), 0)
  const totalAccrued = list.reduce((s, a) => s + (a.accrued || 0), 0)

  const emojiFor = (a) => ASSET_EMOJI[a.slug] || TYPE_EMOJI[a.type] || '📦'

  const renderRental = (a) => {
    if (a.type !== 'realestate') return null
    if (a.rental?.status === 'listed') {
      return (
        <div className="asset-rental listed">
          <KeyRound size={13} /> {t('rent.waiting')}
          <button className="asset-rental-cancel" disabled={busyId === a.id}
            onClick={() => act(a.id, cancelRent, 'rent.cancelled')}>{t('common.cancel')}</button>
        </div>
      )
    }
    if (a.rental?.status === 'rented') {
      return <div className="asset-rental rented"><KeyRound size={13} /> {t('rent.rented')} · ${formatMoney(a.rental.price)}</div>
    }
    return (
      <button className="asset-act" disabled={busyId === a.id}
        onClick={() => { setRentModal(a); setRentForm({ price: String(Math.round(a.incomePerHour * 24) || 100), minHours: '6' }) }}>
        <KeyRound size={15} /> {t('rent.list')}
      </button>
    )
  }

  return (
    <div className="myassets-tab">
      <div className="leaderboard-title-row">
        <Building2 size={22} className="icon" />
        <h2 className="tab-title">{t('nav.myhomes')}</h2>
      </div>

      <div className="market-cats" style={{ marginBottom: 'var(--spacing-lg)' }}>
        {TYPE_TABS.map(tab => {
          const Icon = tab.icon
          return (
            <button key={tab.id} className={`tx-pill ${activeType === tab.id ? 'active' : ''}`}
              onClick={() => setActiveType(tab.id)}>
              <Icon size={14} /> {t(`market.cat_${tab.id}`)}
            </button>
          )
        })}
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      {!loading && !error && list.length > 0 && (
        <div className="asset-summary">
          <div className="asset-summary-card"><span>{t('myassets.totalValue')}</span><b>${formatMoney(totalValue)}</b></div>
          {activeType !== 'car' && <div className="asset-summary-card"><span>{t('myassets.profitPerHour')}</span><b className="up">${formatMoney(totalProfit)}</b></div>}
          {activeType !== 'car' && <div className="asset-summary-card"><span>{t('myassets.readyToCollect')}</span><b className="up">${formatMoney(totalAccrued)}</b></div>}
        </div>
      )}

      {loading && (
        <div className="asset-grid">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="asset-card skeleton" style={{ height: 240 }} />)}
        </div>
      )}

      {error && (
        <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>
      )}

      {!loading && !error && list.length === 0 && (
        <div className="empty-state">
          <span className="placeholder-icon">{TYPE_EMOJI[activeType]}</span>
          <p>{t('myassets.empty')}</p>
        </div>
      )}

      {!loading && !error && list.length > 0 && (
        <div className="asset-grid">
          {list.map(a => {
            const busy = busyId === a.id
            const isCar = a.type === 'car'
            return (
              <div key={a.id} className={`asset-card owned ${isCar ? 'car-card' : ''}`}>
                <div className="asset-banner" style={{ background: RARITY_GRAD[a.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}>
                  <span className="asset-banner-emoji">{emojiFor(a)}</span>
                  <span className="asset-level">{t('myassets.level')} {a.level}</span>
                </div>
                <div className="asset-card-head">
                  <span className="asset-name">{a.name}</span>
                </div>
                <div className="asset-stats">
                  <div className="asset-stat"><span>{t('myassets.value')}</span><b>${formatMoney(a.value)}</b></div>
                  {!isCar && a.profitPerHour !== 0 && (
                    <div className="asset-stat"><span><TrendingUp size={12} /> {t('market.profitPerHour')}</span>
                      <b className={a.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(a.profitPerHour)}</b></div>
                  )}
                  {a.type === 'business' && (
                    <>
                      <div className="asset-stat"><span><Users size={12} /> {t('market.employees')}</span><b>{a.employees}</b></div>
                      <div className="asset-stat"><span>{t('myassets.upkeep')}</span><b className="down">${formatMoney(a.upkeepPerHour)}/ч</b></div>
                    </>
                  )}
                  {a.rooms != null && <div className="asset-stat"><span>{t('realestate.rooms')}</span><b>{a.rooms}</b></div>}
                  {a.meta?.tax != null && <div className="asset-stat"><span>{t('myassets.tax')}</span><b className="down">${a.meta.tax}/ч</b></div>}
                  {a.meta?.prestige != null && <div className="asset-stat"><span>{t('market.prestige')}</span><b>{a.meta.prestige}</b></div>}
                  {isCar && <div className="asset-stat"><span><Gauge size={12} /> {t('car.condition')}</span><b className="up">{t(`car.cond_${Math.min(a.level, 3)}`, t('car.cond_1'))}</b></div>}
                </div>

                {!isCar && a.profitPerHour > 0 && (
                  <div className="asset-accrued"><Wallet size={14} /> {t('myassets.accrued')}: <b>${formatMoney(a.accrued)}</b></div>
                )}
                {renderRental(a)}

                <div className="asset-actions">
                  {!isCar && a.profitPerHour > 0 && (
                    <button className="asset-act collect" disabled={busy || a.accrued <= 0} onClick={() => act(a.id, collectAsset, 'myassets.collected')}>
                      <HandCoins size={15} /> {t('myassets.collect')}
                    </button>
                  )}
                  {!isCar && (
                    <button className="asset-act upgrade" disabled={busy} onClick={() => act(a.id, upgradeAsset, 'myassets.upgraded')}>
                      <ArrowUpCircle size={15} /> {t('myassets.upgrade')} (${formatMoney(a.upgradeCost)})
                    </button>
                  )}
                  <button className="asset-act" disabled={busy} title={t('myassets.toCompanyHint')}
                    onClick={() => act(a.id, transferAssetToCompany, 'myassets.transferred')}>
                    <Building2 size={15} /> {t('myassets.toCompany')}
                  </button>
                  <button className="asset-act sell" disabled={busy} onClick={() => act(a.id, sellAsset, 'myassets.sold')}>
                    <Trash2 size={15} /> {t('myassets.sell')}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {rentModal && (
        <div className="modal-overlay" onClick={() => setRentModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setRentModal(null)}><X size={18} /></button>
            <h3>{t('rent.title')}: {rentModal.name}</h3>
            <p className="modal-price">{t('rent.desc')}</p>
            <div className="modal-quantity"><label>{t('rent.price')}:</label>
              <input type="number" min="1" value={rentForm.price} onChange={e => setRentForm({ ...rentForm, price: e.target.value })} /></div>
            <div className="modal-quantity"><label>{t('rent.minHours')}:</label>
              <input type="number" min="1" max="720" value={rentForm.minHours} onChange={e => setRentForm({ ...rentForm, minHours: e.target.value })} /></div>
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={submitRent} disabled={busyId === rentModal.id}>{t('rent.publish')}</button>
              <button className="stock-btn cancel-btn" onClick={() => setRentModal(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MyAssetsTab
