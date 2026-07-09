import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchAssetMarket, buyAsset } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  Home, Briefcase, Car, Search, AlertTriangle, Check, X,
  TrendingUp, Coins, LayoutGrid,
} from 'lucide-react'

const CATEGORIES = [
  { id: 'all', icon: LayoutGrid },
  { id: 'realestate', icon: Home },
  { id: 'business', icon: Briefcase },
  { id: 'car', icon: Car },
]

const RARITY_COLOR = {
  common: '#9ca3af', uncommon: '#22c55e', rare: '#3b82f6',
  epic: '#a855f7', legendary: '#f59e0b',
}

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

function MarketTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [category, setCategory] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [confirm, setConfirm] = useState(null)   // item pending purchase
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => clearTimeout(id)
  }, [searchInput])

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await fetchAssetMarket({ type: category === 'all' ? undefined : category, search: search || undefined })
      setItems(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [category, search])

  useEffect(() => { load() }, [load])

  // Динамический рынок дрейфует на сервере раз в тик планировщика (см.
  // backend/assets.py tick_market) — обновляем список тихо, без скелетона.
  useEffect(() => {
    const onRealtime = (ev) => {
      if (ev.detail?.type === 'market_update') load(true)
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [load])

  const doBuy = async () => {
    if (!confirm) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await buyAsset(confirm.slug)
      onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('market.bought') })
      setTimeout(() => { setConfirm(null); setFeedback(null) }, 800)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="market-tab">
      <h2 className="tab-title">{t('nav.realestate')}</h2>

      <div className="market-toolbar">
        <div className="market-cats">
          {CATEGORIES.map(c => {
            const Icon = c.icon
            return (
              <button
                key={c.id}
                className={`tx-pill ${category === c.id ? 'active' : ''}`}
                onClick={() => setCategory(c.id)}
              >
                <Icon size={14} /> {c.id === 'all' ? t('common.all') : t(`market.cat_${c.id}`)}
              </button>
            )
          })}
        </div>
        <div className="tx-search market-search">
          <Search size={16} className="tx-search-icon" />
          <input
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            placeholder={t('market.searchPlaceholder')}
          />
        </div>
      </div>

      {loading && (
        <div className="asset-grid">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="asset-card skeleton" style={{ height: 190 }} />)}
        </div>
      )}

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="empty-state"><p>{t('market.noItems')}</p></div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="asset-grid">
          {items.map(item => {
            const rc = RARITY_COLOR[item.rarity] || 'var(--color-accent)'
            const affordable = balance >= item.price
            return (
              <div key={item.slug} className={`asset-card ${item.type === 'car' ? 'car-card' : ''}`} style={{ borderTopColor: rc }}>
                <div className="asset-banner" style={{ background: RARITY_GRAD[item.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}>
                  <span className="asset-banner-emoji">{ASSET_EMOJI[item.slug] || TYPE_EMOJI[item.type] || '📦'}</span>
                </div>
                <div className="asset-card-head">
                  <span className="asset-name">{item.name}</span>
                  {item.rarity && <span className="asset-rarity" style={{ color: rc }}>{t(`realestate.rarities.${item.rarity}`, item.rarity)}</span>}
                  {item.category && <span className="asset-rarity">{t(`business.categories.${item.category}`, item.category)}</span>}
                </div>
                <div className="asset-stats">
                  {item.rooms != null && <div className="asset-stat"><span>{t('realestate.rooms')}</span><b>{item.rooms}</b></div>}
                  {item.employees > 0 && <div className="asset-stat"><span>{t('market.employees')}</span><b>{item.employees}</b></div>}
                  {item.profitPerHour > 0 && (
                    <div className="asset-stat"><span>{t('market.profitPerHour')}</span>
                      <b className="up"><TrendingUp size={12} /> {formatMoney(item.profitPerHour)} $</b></div>
                  )}
                  {item.meta?.prestige != null && <div className="asset-stat"><span>{t('market.prestige')}</span><b>{item.meta.prestige}</b></div>}
                </div>
                <div className="asset-price">
                  <Coins size={14} /> ${formatMoney(item.price)}
                  {item.trend != null && item.trend !== 0 && (
                    <span className={`asset-trend ${item.trend >= 0 ? 'up' : 'down'}`}>
                      {item.trend >= 0 ? '▲' : '▼'} {Math.abs(item.trend).toFixed(1)}%
                    </span>
                  )}
                </div>
                <button
                  className="asset-buy-btn"
                  onClick={() => { setConfirm(item); setFeedback(null) }}
                  disabled={!affordable}
                >
                  {affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}

      {confirm && (
        <div className="modal-overlay" onClick={() => !busy && setConfirm(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setConfirm(null)}><X size={18} /></button>
            <h3>{t('common.buy')}: {confirm.name}</h3>
            <p className="modal-total">{t('common.total')}: <strong>${formatMoney(confirm.price)}</strong></p>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={doBuy} disabled={busy}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setConfirm(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MarketTab
