import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMyAssets, collectAsset, upgradeAsset, sellAsset, fetchCompany,
  transferAssetToCompany, listPropertyForRent, cancelRent, tuneCar,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import ConfirmDialog from './ConfirmDialog'
import {
  Home, Car, Briefcase, ArrowUpCircle, HandCoins, Trash2, AlertTriangle,
  TrendingUp, Users, Wallet, Building2, KeyRound, Check, X, Gauge, LayoutGrid, Wrench,
} from 'lucide-react'

// Детали тюнинга авто (порядок и подписи; стоимость считает сервер).
const TUNE_PARTS = ['engine', 'turbo', 'gearbox', 'suspension', 'brakes', 'tires', 'exhaust']

const TYPE_TABS = [
  { id: 'all', icon: LayoutGrid },
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
  const [rentForm, setRentForm] = useState({ minHours: '6' })
  const [tuneModal, setTuneModal] = useState(null)   // car asset
  const [confirm, setConfirm] = useState(null)       // { title, message, danger, onConfirm }
  const [isCompanyOwner, setIsCompanyOwner] = useState(false)

  useEffect(() => {
    fetchCompany().then(res => setIsCompanyOwner(!!res.company?.isOwner)).catch(() => setIsCompanyOwner(false))
  }, [])

  // Синхронизируем открытую модалку тюнинга с обновлёнными данными.
  useEffect(() => {
    if (tuneModal) {
      const fresh = assets.find(a => a.id === tuneModal.id)
      if (fresh && fresh !== tuneModal) setTuneModal(fresh)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assets])

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

  // Открыть подтверждение перед действием (act выполнится по «Да»).
  const askAct = (id, fn, okKey, conf) =>
    setConfirm({ ...conf, onConfirm: () => act(id, fn, okKey) })

  const submitRent = async () => {
    if (!rentModal) return
    const minHours = Math.floor(Number(rentForm.minHours))
    if (!(minHours >= 1)) { flash(t('rent.invalid'), 'error'); return }
    setBusyId(rentModal.id)
    try {
      await listPropertyForRent(rentModal.id, minHours)
      flash(t('rent.listed'))
      setRentModal(null)
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const tuneCost = (car, part) => Math.round((car.price || 0) * 0.05 * ((car.tuning?.[part] || 0) + 1))

  const doTune = async (car, part) => {
    setBusyId(car.id)
    try {
      const res = await tuneCar(car.id, part)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('tune.done'))
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const list = activeType === 'all' ? assets : assets.filter(a => a.type === activeType)
  const totalValue = list.reduce((s, a) => s + (a.value || 0), 0)
  const totalProfit = list.reduce((s, a) => s + (a.profitPerHour || 0), 0)
  const totalAccrued = list.reduce((s, a) => s + (a.accrued || 0), 0)

  const emojiFor = (a) => ASSET_EMOJI[a.slug] || TYPE_EMOJI[a.type] || '📦'

  const renderRental = (a) => {
    if (a.type !== 'realestate' && a.type !== 'car') return null
    if (a.rental?.status === 'listed') {
      return (
        <div className="asset-rental listed">
          <KeyRound size={13} /> {t('rent.waiting')}
          <button className="asset-rental-cancel" disabled={busyId === a.id}
            onClick={() => askAct(a.id, cancelRent, 'rent.cancelled', { title: t('rent.list'), message: t('confirm.cancelRent') })}>{t('common.cancel')}</button>
        </div>
      )
    }
    if (a.rental?.status === 'rented') {
      return <div className="asset-rental rented"><KeyRound size={13} /> {t('rent.rented')} · ${formatMoney(a.rental.price)}</div>
    }
    return (
      <button className="asset-act" disabled={busyId === a.id}
        onClick={() => { setRentModal(a); setRentForm({ minHours: '6' }) }}>
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
              <Icon size={14} /> {tab.id === 'all' ? t('common.all') : t(`market.cat_${tab.id}`)}
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
          <span className="placeholder-icon">{TYPE_EMOJI[activeType] || '📦'}</span>
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

                <div className={`asset-actions ${isCar ? 'compact' : ''}`}>
                  {!isCar && a.profitPerHour > 0 && (
                    <button className="asset-act collect" disabled={busy || a.accrued <= 0}
                      onClick={() => askAct(a.id, collectAsset, 'myassets.collected', { title: t('myassets.collect'), message: t('confirm.collect', { amount: formatMoney(a.accrued) }) })}>
                      <HandCoins size={15} /> {t('myassets.collect')}
                    </button>
                  )}
                  {!isCar && (
                    <button className="asset-act upgrade" disabled={busy}
                      onClick={() => askAct(a.id, upgradeAsset, 'myassets.upgraded', { title: t('myassets.upgrade'), message: t('confirm.upgrade', { cost: formatMoney(a.upgradeCost) }) })}>
                      <ArrowUpCircle size={15} /> {t('myassets.upgrade')} (${formatMoney(a.upgradeCost)})
                    </button>
                  )}
                  {isCar && (
                    <button className="asset-act upgrade" disabled={busy} onClick={() => setTuneModal(a)}>
                      <Wrench size={15} /> {t('tune.title')}
                    </button>
                  )}
                  {isCompanyOwner && (
                    <button className="asset-act" disabled={busy} title={t('myassets.toCompanyHint')}
                      onClick={() => askAct(a.id, transferAssetToCompany, 'myassets.transferred', { title: t('myassets.toCompany'), message: t('confirm.transfer', { name: a.name }) })}>
                      <Building2 size={15} /> {t('myassets.toCompany')}
                    </button>
                  )}
                  <button className="asset-act sell" disabled={busy}
                    onClick={() => askAct(a.id, sellAsset, 'myassets.sold', { danger: true, title: t('myassets.sell'), message: t('confirm.sell', { name: a.name, value: formatMoney(a.value) }) })}>
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
            <div className="modal-quantity"><label>{t('rent.minHours')}:</label>
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

      {tuneModal && (
        <div className="modal-overlay" onClick={() => busyId !== tuneModal.id && setTuneModal(null)}>
          <div className="modal-content tune-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setTuneModal(null)}><X size={18} /></button>
            <h3><Wrench size={18} /> {t('tune.title')}: {tuneModal.name}</h3>
            <div className="tune-summary">
              <div><span>{t('market.prestige')}</span><b>{tuneModal.meta?.prestige ?? 0}</b></div>
              <div><span>{t('myassets.value')}</span><b>${formatMoney(tuneModal.value)}</b></div>
            </div>
            <div className="tune-parts">
              {TUNE_PARTS.map(part => {
                const lvl = tuneModal.tuning?.[part] || 0
                const max = tuneModal.tuneMaxLevel || 5
                const maxed = lvl >= max
                const cost = tuneCost(tuneModal, part)
                return (
                  <div key={part} className="tune-part">
                    <div className="tune-part-info">
                      <span className="tune-part-name">{t(`tune.parts.${part}`)}</span>
                      <div className="tune-levels">
                        {Array.from({ length: max }).map((_, i) => (
                          <span key={i} className={`tune-pip ${i < lvl ? 'on' : ''}`} />
                        ))}
                      </div>
                    </div>
                    <button className="asset-act upgrade" disabled={busyId === tuneModal.id || maxed}
                      onClick={() => doTune(tuneModal, part)}>
                      {maxed ? t('tune.max') : <>+1 · ${formatMoney(cost)}</>}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirm}
        danger={confirm?.danger}
        title={confirm?.title}
        message={confirm?.message}
        onConfirm={() => { confirm?.onConfirm?.(); setConfirm(null) }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}

export default MyAssetsTab
