// NEXUS · Магазин оборудования. Дома/бизнесы — на вкладке «Рынок» (MarketTab).
// Каталог: GET /api/shop/catalog (базовые позиции + админские серии), имена
// и id согласованы с utils/shopCatalog.js. Покупка: POST /api/shop/buy.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchShopCatalog,
  buyHardware,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import ShopBuyModal from './ShopBuyModal'
import { toast } from './Toast'
import Tooltip from './Tooltip'
import {
  Monitor, Cpu, Box, Package, MemoryStick, HardDrive, Snowflake, Zap, CircuitBoard, Server,
  Search, DollarSign, ArrowUpDown, AlertTriangle, ShoppingCart, Network, PlugZap, Fan,
} from 'lucide-react'

// Фильтр-пилюли: категории магазина. supplies — расходники с бэкенда.
const CATEGORIES = [
  { id: '', icon: ShoppingCart },            // Все
  { id: 'gpu', icon: Monitor },
  { id: 'cpu', icon: Cpu },
  { id: 'motherboard', icon: CircuitBoard },
  { id: 'ram', icon: MemoryStick },
  { id: 'ssd', icon: HardDrive },
  { id: 'cooling', icon: Snowflake },
  { id: 'psu', icon: Zap },
  { id: 'case', icon: Box },
  { id: 'rack', icon: Server },
  { id: 'fan', icon: Fan },
  { id: 'network', icon: Network },
  { id: 'ups', icon: PlugZap },
  { id: 'supplies', icon: Package },
]

const CAT_COLOR = {
  gpu: '#818cf8', cpu: '#a855f7', motherboard: '#06b6d4', ram: '#10b981',
  ssd: '#eab308', cooling: '#0ea5e9', psu: '#f59e0b', case: '#94a3b8', rack: '#64748b',
  fan: '#38bdf8', network: '#2dd4bf', ups: '#fb7185', supplies: '#f97316',
}

function specLine(cat, s = {}, t) {
  switch (cat) {
    case 'gpu': return `${s.hashrate >= 1000 ? (s.hashrate / 1000).toFixed(1) + 'k' : s.hashrate} H/s · ${s.power}W`
    case 'cpu': return `${t('units.cores', { count: s.cores })} · ${s.power}W`
    case 'motherboard': return `${s.gpuSlots || 0} GPU · ${s.power || 0}W`
    case 'ram': return `${s.gb} ГБ · ${s.power || 0}W`
    case 'ssd': return `${s.gb} ГБ · ${s.power || 0}W`
    case 'cooling': return `${s.cooling || 0} Вт охл. · ${s.power || 0}W`
    case 'fan': return `${s.cooling || 0} Вт охл. · ${s.power || 0}W`
    case 'psu': return `${s.power || 0}W`
    case 'case': return `${t('units.slots', { count: s.slots })}`
    case 'rack': return `${t('units.slots', { count: s.slots })}`
    case 'network': return s.speed >= 1000 ? `${s.speed / 1000} Гбит/с` : `${s.speed || 0} Мбит/с`
    case 'ups': return s.backup >= 1000 ? `${s.backup / 1000} kVA` : `${s.backup || 0} VA`
    case 'supplies': return t(`supplies.${s.kind}`, s.kind || '')
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
  // Товар для ShopBuyModal (null = модалка закрыта).
  const [buyItem, setBuyItem] = useState(null)
  // busy — пока идёт POST /api/shop/buy (блокирует кнопку и крестик модалки).
  const [buyBusy, setBuyBusy] = useState(false)

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 250)
    return () => clearTimeout(id)
  }, [searchInput])

async function loadShopItems(category) {
  return await fetchShopCatalog(category || undefined)
}

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const items = await loadShopItems(category)
      setItems(items)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [category])

  useEffect(() => { load() }, [load])

  // Покупка: POST /api/shop/buy, баланс обновляется на успехе.
  const handleBuyConfirm = async (qty) => {
    const item = buyItem
    if (!item) return
    // Не закрываем модалку сразу — пусть крутится «Загрузка…», и только после
    // успешного ответа сервера закрываем. Если ошибка — модалка остаётся
    // открытой, чтобы игрок мог повторить или скорректировать количество.
    setBuyBusy(true)
    try {
      const res = await buyHardware(item.id, qty)
      if (res && typeof res.balance === 'number' && onBalanceChange) {
        onBalanceChange(res.balance)
      }
      const total = res?.total != null ? res.total : (item.price * qty)
      toast(t('market.bought', { defaultValue: 'Куплено' }) + ` — $${formatMoney(total)}`)
      setBuyItem(null)
    } catch (err) {
      toast(err?.message || t('common.error', { defaultValue: 'Ошибка' }), 'error')
    } finally {
      setBuyBusy(false)
    }
  }

  const SHOP_CATEGORIES = new Set([
    'gpu', 'cpu', 'motherboard', 'ram', 'ssd', 'cooling', 'psu', 'case', 'rack',
    'fan', 'network', 'ups', 'supplies',
  ])

  const view = useMemo(() => {
    let r = items.filter(i => SHOP_CATEGORIES.has(i.category))
    if (search) r = r.filter(i => (i.name || '').toLowerCase().includes(search))
    return [...r].sort((a, b) => sortOrder === 'asc' ? a.price - b.price : b.price - a.price)
  }, [items, search, sortOrder])

  return (
    <div className="shop-tab">
      <div className="leaderboard-title-row">
        <ShoppingCart size={22} className="icon" />
        <h2 className="tab-title">NEXUS · {t('nav.shop')}</h2>
      </div>

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
          <Tooltip text={t('shop.sortPriceHelp', { direction: sortOrder === 'asc' ? t('common.ascending', 'по возрастанию') : t('common.descending', 'по убыванию') })}>
            <button className="gpu-sort-btn active" title={t('shop.sortPriceHelp', { direction: sortOrder === 'asc' ? t('common.ascending', 'по возрастанию') : t('common.descending', 'по убыванию') })} aria-label={t('shop.sortPriceHelp', { direction: sortOrder === 'asc' ? t('common.ascending', 'по возрастанию') : t('common.descending', 'по убыванию') })} onClick={() => setSortOrder(o => o === 'asc' ? 'desc' : 'asc')}>
              <ArrowUpDown size={14} /> {t('common.price')} {sortOrder === 'asc' ? '↑' : '↓'}
            </button>
          </Tooltip>
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
            // Цвет по мощности/тиру приходит из каталога (item.color); категорийный — запасной.
            const color = item.color || CAT_COLOR[item.category] || '#0071e3'
            const CatIcon = (CATEGORIES.find(c => c.id === item.category) || {}).icon || Cpu
            const affordable = balance >= item.price
            return (
              <div key={item.id} className="gpu-card gpu-card-compact" style={{ borderColor: `${color}55` }}>
                <div className="gpu-card-head">
                  <span className="gpu-card-icon" style={{ background: color }}><CatIcon size={18} /></span>
                  <div className="gpu-card-headtext">
                    <span className="gpu-card-cat">{t(`mining.comp.${item.category}`, item.category)}</span>
                    <span className="gpu-card-name">{hwName(item, t)}</span>
                  </div>
                </div>
                <div className="gpu-card-foot">
                  <div className="gpu-card-specs"><span>{specLine(item.category, item.specs, t)}</span></div>
                  <div className="gpu-card-price"><DollarSign size={12} style={{ color }} /> ${formatMoney(item.price)}</div>
                </div>
                <button
                  className="gpu-card-buy"
                  style={{ background: affordable ? color : undefined }}
                  disabled={!affordable}
                  onClick={() => setBuyItem(item)}
                >
                  {affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}

      <ShopBuyModal
        open={!!buyItem}
        item={buyItem}
        balance={balance}
        busy={buyBusy}
        onConfirm={handleBuyConfirm}
        onCancel={() => { if (!buyBusy) setBuyItem(null) }}
      />
    </div>
  )
}

export default ShopTab
