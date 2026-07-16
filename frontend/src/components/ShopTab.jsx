import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchShopCatalog, buyHardware } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import ConfirmDialog from './ConfirmDialog'
import {
  Monitor, Cpu, HardDrive, Zap, Fan, Box, Server, Battery, Network,
  Search, DollarSign, ArrowUpDown, AlertTriangle, Check, ShoppingCart,
} from 'lucide-react'

// Магазин оборудования NEXUS — единый каталог всех комплектующих.
// Реиспользует существующий backend /api/shop (каталог + покупка).
const CATEGORIES = [
  { id: '', icon: ShoppingCart },        // Все
  { id: 'gpu', icon: Monitor },
  { id: 'cpu', icon: Cpu },
  { id: 'motherboard', icon: Cpu },
  { id: 'ram', icon: HardDrive },
  { id: 'ssd', icon: HardDrive },
  { id: 'psu', icon: Zap },
  { id: 'cooling', icon: Fan },
  { id: 'case', icon: Box },
  { id: 'rack', icon: Server },
  { id: 'fan', icon: Fan },
  { id: 'ups', icon: Battery },
  { id: 'network', icon: Network },
]

const CAT_COLOR = {
  gpu: '#818cf8', cpu: '#a855f7', motherboard: '#0ea5e9', ram: '#22d3ee',
  ssd: '#34d399', psu: '#eab308', cooling: '#06b6d4', case: '#94a3b8',
  rack: '#64748b', fan: '#38bdf8', ups: '#f59e0b', network: '#818cf8',
}

function specLine(cat, s = {}) {
  switch (cat) {
    case 'gpu': return `${s.hashrate >= 1000 ? (s.hashrate / 1000).toFixed(1) + 'k' : s.hashrate} H/s · ${s.power}W`
    case 'cpu': return `${s.cores} ядер · ${s.power}W`
    case 'motherboard': return `${s.gpuSlots} слотов GPU`
    case 'ram': return `${s.gb} ГБ`
    case 'ssd': return `${s.gb} ГБ`
    case 'psu': return `${s.power} W`
    case 'cooling': return `${s.cooling} охл.`
    case 'fan': return `${s.cooling} охл. · ${s.power}W`
    case 'case': return `${s.slots} слотов`
    case 'rack': return `${s.slots} GPU${s.industrial ? ' · пром.' : ''}`
    case 'ups': return `${s.backup} VA`
    case 'network': return `${s.speed >= 1000 ? (s.speed / 1000) + ' Гбит' : s.speed + ' Мбит'}`
    default: return ''
  }
}

function ShopTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [category, setCategory] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)
  const [confirm, setConfirm] = useState(null)   // item awaiting purchase confirmation

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 250)
    return () => clearTimeout(id)
  }, [searchInput])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await fetchShopCatalog(category || undefined))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [category])

  useEffect(() => { load() }, [load])

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

  const view = useMemo(() => {
    let r = items
    if (search) r = r.filter(i => (i.name || '').toLowerCase().includes(search))
    return [...r].sort((a, b) => sortOrder === 'asc' ? a.price - b.price : b.price - a.price)
  }, [items, search, sortOrder])

  return (
    <div className="shop-tab">
      <div className="leaderboard-title-row">
        <ShoppingCart size={22} className="icon" />
        <h2 className="tab-title">NEXUS · {t('nav.shop')}</h2>
      </div>
      <p className="shop-subtitle">{t('shop.nexusDesc')}</p>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <div className="market-toolbar">
        <div className="market-cats">
          {CATEGORIES.map(c => {
            const Icon = c.icon
            return (
              <button key={c.id || 'all'} className={`tx-pill ${category === c.id ? 'active' : ''}`} onClick={() => setCategory(c.id)}>
                <Icon size={14} /> {c.id === '' ? t('common.all') : t(`mining.comp.${c.id}`, c.id)}
              </button>
            )
          })}
        </div>
        <div className="shop-toolbar-right">
          <div className="tx-search market-search">
            <Search size={16} className="tx-search-icon" />
            <input value={searchInput} onChange={e => setSearchInput(e.target.value)} placeholder={t('market.searchPlaceholder')} />
          </div>
          <button className="gpu-sort-btn active" onClick={() => setSortOrder(o => o === 'asc' ? 'desc' : 'asc')}>
            <ArrowUpDown size={14} /> {t('common.price')} {sortOrder === 'asc' ? '↑' : '↓'}
          </button>
        </div>
      </div>

      {loading && (
        <div className="gpu-grid">
          {Array.from({ length: 10 }).map((_, i) => <div key={i} className="gpu-card skeleton" style={{ height: 150 }} />)}
        </div>
      )}
      {error && <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>}

      {!loading && !error && view.length === 0 && (
        <div className="empty-state"><p>{t('market.noItems')}</p></div>
      )}

      {!loading && !error && view.length > 0 && (
        <div className="gpu-grid">
          {view.map(item => {
            const color = CAT_COLOR[item.category] || item.color || '#0071e3'
            const affordable = balance >= item.price
            const CatIcon = (CATEGORIES.find(c => c.id === item.category) || {}).icon || Cpu
            return (
              <div key={item.id} className="gpu-card" style={{ borderColor: `${color}55` }}>
                <span className="gpu-card-icon" style={{ background: color }}><CatIcon size={20} /></span>
                <span className="gpu-card-cat">{t(`mining.comp.${item.category}`, item.category)}</span>
                <span className="gpu-card-name">{hwName(item, t)}</span>
                <div className="gpu-card-specs"><span>{specLine(item.category, item.specs)}</span></div>
                <div className="gpu-card-price"><DollarSign size={12} style={{ color }} /> ${formatMoney(item.price)}</div>
                <button
                  className="gpu-card-buy"
                  style={{ background: affordable ? color : undefined }}
                  disabled={!affordable || busyId === item.id}
                  onClick={() => setConfirm(item)}
                >
                  {busyId === item.id ? t('bank.processing') : affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}

      <ConfirmDialog
        open={!!confirm}
        busy={busyId === confirm?.id}
        title={t('common.buy')}
        message={confirm ? t('confirm.buyHardware', { name: hwName(confirm, t), price: formatMoney(confirm.price) }) : ''}
        confirmLabel={t('common.buy')}
        onConfirm={async () => { const it = confirm; setConfirm(null); await buy(it) }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}

export default ShopTab
