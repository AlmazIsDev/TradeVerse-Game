import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Monitor, Zap, DollarSign, ArrowUpDown, AlertTriangle, Check } from 'lucide-react'
import { fetchShopCatalog, buyHardware } from '../services/api'
import { formatMoney } from './TransactionsPanel'

const BRAND_COLORS = {
  CrystalCore: '#818cf8', Pyronix: '#fb923c', Archivex: '#4ade80',
}

function GpuShop({ onBack, balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [brand, setBrand] = useState('')
  const [sortBy, setSortBy] = useState('price')
  const [sortOrder, setSortOrder] = useState('asc')
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await fetchShopCatalog('gpu'))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const brands = useMemo(() => [...new Set(items.map(i => i.brand).filter(Boolean))], [items])

  const filtered = useMemo(() => {
    let r = items.filter(i => !brand || i.brand === brand)
    r = [...r].sort((a, b) => {
      const va = sortBy === 'hashrate' ? (a.specs?.hashrate || 0) : a.price
      const vb = sortBy === 'hashrate' ? (b.specs?.hashrate || 0) : b.price
      return sortOrder === 'asc' ? va - vb : vb - va
    })
    return r
  }, [items, brand, sortBy, sortOrder])

  const flash = (text, type = 'success') => { setMsg({ text, type }); setTimeout(() => setMsg(null), 2200) }

  const buy = async (item) => {
    setBusyId(item.id)
    try {
      const res = await buyHardware(item.id, 1)
      onBalanceChange?.(res.balance)
      flash(t('market.bought'))
      await load()   // цены могли сдвинуться
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const toggleSort = (field) => {
    if (sortBy === field) setSortOrder(o => (o === 'asc' ? 'desc' : 'asc'))
    else { setSortBy(field); setSortOrder('asc') }
  }

  const fmtHash = (h) => (h >= 1000 ? `${(h / 1000).toFixed(1)}k` : `${h}`)

  return (
    <div className="shop-tab">
      <div className="shop-section-header">
        <button className="shop-back-btn" onClick={onBack}><ArrowLeft size={18} /><span>{t('shop.gpu')}</span></button>
        <h2 className="tab-title">{t('shop.gpuCards')}</h2>
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <div className="gpu-toolbar">
        <select className="admin-input" value={brand} onChange={e => setBrand(e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">{t('common.all')}</option>
          {brands.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        <button className={`gpu-sort-btn ${sortBy === 'hashrate' ? 'active' : ''}`} onClick={() => toggleSort('hashrate')}>
          <Zap size={14} /> {t('gpu.hashrate')} {sortBy === 'hashrate' && (sortOrder === 'asc' ? '↑' : '↓')}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} /> {t('common.price')} {sortBy === 'price' && (sortOrder === 'asc' ? '↑' : '↓')}
        </button>
      </div>

      {loading && (
        <div className="gpu-grid">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="gpu-card skeleton" style={{ height: 150 }} />)}
        </div>
      )}
      {error && <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>}

      {!loading && !error && (
        <div className="gpu-grid">
          {filtered.map(item => {
            const color = BRAND_COLORS[item.brand] || item.color || '#6366f1'
            const affordable = balance >= item.price
            return (
              <div key={item.id} className="gpu-card" style={{ borderColor: `${color}55` }}>
                <span className="gpu-card-icon" style={{ background: color }}><Monitor size={22} /></span>
                <span className="gpu-card-name">{item.name}</span>
                <div className="gpu-card-specs">
                  <span><Zap size={12} style={{ color }} /> {fmtHash(item.specs?.hashrate || 0)} H/s</span>
                  <span>{item.specs?.power || 0}W</span>
                </div>
                <div className="gpu-card-price"><DollarSign size={12} style={{ color }} /> ${formatMoney(item.price)}</div>
                <button
                  className="gpu-card-buy"
                  style={{ background: affordable ? color : undefined }}
                  disabled={!affordable || busyId === item.id}
                  onClick={() => buy(item)}
                >
                  {busyId === item.id ? t('bank.processing') : affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default GpuShop
