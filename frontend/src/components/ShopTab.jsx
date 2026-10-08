// ─────────────────────────────────────────────────────────────────────────────
// NEXUS · Магазин оборудования.
// Доступные категории: gpu, cpu, case, supplies (расходники).
// Дома и бизнесы живут на отдельной вкладке «Рынок» (MarketTab).
// Источник каталога: GET /api/shop/catalog — бэкенд отдаёт и базовые
// позиции (gpu-cc-0-0, psu-500, …), и полные админские серии
// (admin-gpu-1..90, admin-cpu-1..90, admin-case-1..90, admin-supply-*).
// Имена и id согласованы с frontend/src/utils/shopCatalog.js.
// Карточка компактная: иконка, категория, имя, характеристика, цена и кнопка
// «Купить». Количество/итоговая цена/баланс — в модалке BuyModal.
// Покупка железа → POST /api/shop/buy.
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchShopCatalog,
  buyHardware,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
// Модалка покупки в едином стиле с рынком: товар → количество → баланс → цена
// за шт. → итого → кнопка «Купить». Старая BuyModal.jsx больше не используется
// (если где-то ещё — не трогаем).
import { hwName } from '../utils/hwName'
import ShopBuyModal from './ShopBuyModal'
import { toast } from './Toast'
// ── Иконки (lucide-react). ───────────────────────────────────────────────
import {
  Monitor, Cpu, Box, Package, MemoryStick, HardDrive, Snowflake, Zap, CircuitBoard,
  Search, DollarSign, ArrowUpDown, AlertTriangle, ShoppingCart,
} from 'lucide-react'

// Фильтр-пилюли: категории магазина (дома убраны — они на «Рынке»).
// "supplies" — расходники с бэкенда (см. /api/shop/catalog).
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
  { id: 'supplies', icon: Package },
]

const CAT_COLOR = {
  gpu: '#818cf8', cpu: '#a855f7', motherboard: '#06b6d4', ram: '#10b981',
  ssd: '#eab308', cooling: '#0ea5e9', psu: '#f59e0b', case: '#94a3b8',
  supplies: '#f97316',
}

function specLine(cat, s = {}, t) {
  switch (cat) {
    case 'gpu': return `${s.hashrate >= 1000 ? (s.hashrate / 1000).toFixed(1) + 'k' : s.hashrate} H/s · ${s.power}W`
    case 'cpu': return `${t('units.cores', { count: s.cores })} · ${s.power}W`
    case 'motherboard': return `${s.gpuSlots || 0} GPU · ${s.power || 0}W`
    case 'ram': return `${s.gb} ГБ · ${s.power || 0}W`
    case 'ssd': return `${s.gb} ГБ · ${s.power || 0}W`
    case 'cooling': return `${s.cooling || 0} Вт охл. · ${s.power || 0}W`
    case 'psu': return `${s.power || 0}W`
    case 'case': return `${t('units.slots', { count: s.slots })}`
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
  // ShopBuyModal: выбранный товар (открывает модалку покупки) или null.
  // Продажи в магазине больше нет — упращено: карточка показывает только
  // кнопку «Купить», которая открывает ShopBuyModal.
  const [buyItem, setBuyItem] = useState(null)
  // busy — пока идёт POST /api/shop/buy (блокирует кнопку и крестик модалки).
  const [buyBusy, setBuyBusy] = useState(false)

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 250)
    return () => clearTimeout(id)
  }, [searchInput])

  // Локальный qty-стейт упразднён — см. handleBuyConfirm ниже.

  // loadInventory упразднён: карточка больше не показывает «В наличии» /
  // «Продать» — это переехало в MyAssetsTab.
// ── Загрузка каталога ──────────────────────────────────────────────
// Железо/расходники: fetchShopCatalog(category) — бэкенд отдаёт и базовые
// позиции (gpu-cc-0-0, psu-500, …), и полные админские серии
// (admin-gpu-1..90, admin-cpu-1..90, admin-case-1..90, admin-supply-*).
// Дома и бизнесы в магазине больше не продаются — они на «Рынке» (MarketTab).
async function loadShopItems(category) {
  // Бэкенд отдаёт и базовые, и админские позиции (см. backend/shop.py).
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
  // loadInventory удалён: карточка больше не показывает инвентарь.

// Покупка: вызывает бэкенд (POST /api/shop/buy для железа/расходников) и
// обновляет баланс игрока после успешной транзакции. Дома/бизнесы покупаются
// на вкладке «Рынок» (MarketTab), здесь их нет.
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
      toast(err?.message || t('common.error', { defaultValue: 'Ошибка' }))
    } finally {
      setBuyBusy(false)
    }
  }

  // Категории, которые показываются в магазине. Дома/бизнесы отсеиваются —
  // они на «Рынке» (MarketTab).
  const SHOP_CATEGORIES = new Set([
    'gpu', 'cpu', 'motherboard', 'ram', 'ssd', 'cooling', 'psu', 'case', 'supplies',
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
            // Цвет по мощности/тиру приходит из каталога (item.color); категорийный — запасной.
            const color = item.color || CAT_COLOR[item.category] || '#0071e3'
            // busy-флаг не нужен — кнопка открывает ShopBuyModal, покупка асинхронна.
            const CatIcon = (CATEGORIES.find(c => c.id === item.category) || {}).icon || Cpu
            // Карточка железа: компактная. Бэкенд отдаёт все позиции
            // (включая admin-gpu/cpu/case/supply), кнопка «Купить» всегда активна.
            const affordable = balance >= item.price
            return (
              <div key={item.id} className="gpu-card gpu-card-compact" style={{ borderColor: `${color}55` }}>
                <span className="gpu-card-icon" style={{ background: color }}><CatIcon size={20} /></span>
                <span className="gpu-card-cat">{t(`mining.comp.${item.category}`, item.category)}</span>
                <span className="gpu-card-name">{hwName(item, t)}</span>
                <div className="gpu-card-specs"><span>{specLine(item.category, item.specs, t)}</span></div>
                <div className="gpu-card-price"><DollarSign size={12} style={{ color }} /> ${formatMoney(item.price)}</div>
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

      {/* Модалка покупки в едином стиле с рынком:
          товар → количество → баланс → цена/шт. → итого → «Купить». */}
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
