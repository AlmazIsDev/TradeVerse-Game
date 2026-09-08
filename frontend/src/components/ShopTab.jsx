// ─────────────────────────────────────────────────────────────────────────────
// NEXUS · Магазин оборудования и недвижимости.
// Доступные категории: gpu, cpu, case, supplies (расходники), house (дома).
// Источники каталога:
//   • Железо: GET /api/shop/catalog + adminCatalog.js (витрина 90+ GPU/CPU/case).
//   • Дома:  GET /api/assets/market?type=realestate — 6 типов (studio/flat2/
//            townhouse/villa/penthouse/castle), реальная цена и доход с бэкенда.
// Карточка компактная: иконка, категория, имя, характеристика, цена и кнопка
// «Купить». Количество/итоговая цена/баланс — в модалке BuyModal.
// Бэкенд НЕ вызывается при покупке (демо-режим: кнопка закрывает + toast).
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchShopCatalog, fetchAssetMarket } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import { ADMIN_SHOP_CATALOG } from '../utils/adminCatalog'
import BuyModal from './BuyModal'
import { toast } from './Toast'
// ── Иконки (lucide-react). Home — отдельная пилюля для недвижимости. ──────
import {
  Monitor, Cpu, Box, Package, Clock, Home,
  Search, DollarSign, ArrowUpDown, AlertTriangle, ShoppingCart,
} from 'lucide-react'

// Фильтр-пилюли: категории магазина.
// "supplies" приходит из adminCatalog.js (витрина), "house" — из /api/assets/market.
const CATEGORIES = [
  { id: '', icon: ShoppingCart },        // Все
  { id: 'gpu', icon: Monitor },
  { id: 'cpu', icon: Cpu },
  { id: 'case', icon: Box },
  { id: 'supplies', icon: Package },
  { id: 'house', icon: Home },
]

const CAT_COLOR = {
  gpu: '#818cf8', cpu: '#a855f7', case: '#94a3b8', supplies: '#f97316', house: '#22c55e',
}

// Доход/час для дома: assets.py присылает income_per_hour.
// Число жильцов выводим из rooms (rooms+1, минимум 2).
function houseSpecLine(item, t) {
  const s = item.specs || {}
  const income = s.income_per_hour != null ? `+$${s.income_per_hour}${t('house.incomeShort')}` : ''
  const rooms = s.rooms != null ? `${s.rooms} ${t('house.roomsShort')}` : ''
  const residents = s.rooms != null ? t('house.upTo', { count: Math.max(2, s.rooms + 1) }) : ''
  return [rooms, income, residents].filter(Boolean).join(' · ')
}

function specLine(cat, s = {}, t) {
  switch (cat) {
    case 'gpu': return `${s.hashrate >= 1000 ? (s.hashrate / 1000).toFixed(1) + 'k' : s.hashrate} H/s · ${s.power}W`
    case 'cpu': return `${t('units.cores', { count: s.cores })} · ${s.power}W`
    case 'case': return `${t('units.slots', { count: s.slots })}`
    case 'supplies': return t(`supplies.${s.kind}`, s.kind || '')
    case 'house': {
      // Для обратной совместимости (если когда-нибудь придёт из adminCatalog).
      const income = s.income != null ? `+$${s.income}${t('house.incomeShort')}` : ''
      const residents = s.residents != null ? t('house.upTo', { count: s.residents }) : ''
      const rooms = s.rooms != null ? `${s.rooms} ${t('house.roomsShort')}` : ''
      return [rooms, income, residents].filter(Boolean).join(' · ')
    }
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
  // BuyModal: выбранный товар (открывает модалку покупки) или null.
  // Продажи в магазине больше нет — упращено: карточка показывает только
  // кнопку «Купить», которая открывает BuyModal.
  const [buyItem, setBuyItem] = useState(null)

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 250)
    return () => clearTimeout(id)
  }, [searchInput])

  // Локальный qty-стейт упразднён — см. handleBuyConfirm ниже.

  // loadInventory упразднён: карточка больше не показывает «В наличии» /
  // «Продать» — это переехало в MyAssetsTab.
// ── Загрузка каталога ──────────────────────────────────────────────
// Железо: fetchShopCatalog(category) + adminCatalog (для всех 90+ видеокарт/CPU/case).
// Дома: fetchAssetMarket('realestate') — 6 типов, бэкенд возвращает реальную
// цену с учётом динамического множителя, поэтому админскую витрину
// (REAL_ESTATE_PRODUCTS) сюда подмешивать не нужно.
async function loadShopItems(category) {
  if (category === 'house') {
    const market = await fetchAssetMarket('realestate')
    return (market || []).map(m => ({
      id: m.slug,                    // для buyAsset(slug) — см. backend/assets.py
      category: 'house',
      type: 'realestate',
      slug: m.slug,
      name: m.name,
      color: m.color || '#22c55e',
      // houseType: 'asset' — это реальный покупаемый объект (не витрина)
      houseType: 'asset',
      rarity: m.rarity,
      price: m.price,
      specs: {
        rooms: m.rooms,
        basement: m.basement,
        income_per_hour: m.income_per_hour,
        upkeep_per_hour: m.upkeep_per_hour,
      },
    }))
  }
  const backendItems = await fetchShopCatalog(category || undefined)
  // Подмешиваем админскую витрину (GPU/CPU/case/supplies) только если она
  // отсутствует в ответе бэкенда и подходит под активную категорию.
  const backendIds = new Set((backendItems || []).map(i => i.id))
  const adminOnly = ADMIN_SHOP_CATALOG.filter(a =>
    !backendIds.has(a.id) &&
    (!category || a.category === category)
  )
  return [...(backendItems || []), ...adminOnly]
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

// Покупка (демо-режим): кнопка «Купить» в BuyModal просто закрывает окно
// и показывает toast. Бэкенд не вызывается — только фронтенд.
  const handleBuyConfirm = (qty) => {
    const item = buyItem
    if (!item) return
    setBuyItem(null)
    toast(t('market.bought'))
  }

  const view = useMemo(() => {
    let r = items
    // Защитный фильтр по категории — оставляем только то, что продаётся в магазине.
    // 'house' — витрина домов из adminCatalog (REAL_ESTATE_PRODUCTS).
    r = r.filter(i => ['gpu', 'cpu', 'case', 'supplies', 'house'].includes(i.category))
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
            // В демо-режиме busy-флаг не нужен — кнопка просто открывает BuyModal.
            const CatIcon = (CATEGORIES.find(c => c.id === item.category) || {}).icon || Cpu
            // Дома идут отдельной веткой рендера: без qty/sell, иконка Home.
            if (item.category === 'house' || item.houseType === 'asset') {
              const affordable = balance >= item.price
              return (
                <div key={item.id} className="gpu-card" style={{ borderColor: `${color}55` }}>
                  <span className="gpu-card-icon" style={{ background: color }}><Home size={20} /></span>
                  <span className="gpu-card-cat">{t(`mining.comp.${item.category}`, item.category)}</span>
                  <span className="gpu-card-name">{hwName(item, t)}</span>
                  <div className="gpu-card-specs"><span>{houseSpecLine(item, t)}</span></div>
                  {item.specs?.basement > 0 && (
                    <div className="gpu-card-spec-row">
                      {t('realestate.basement', { defaultValue: t('house.basementShort') })}: {item.specs.basement}
                    </div>
                  )}
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
            }
            // Карточка железа: компактная, без qty-степпера, без power-строки.
            const affordable = balance >= item.price
            return (
              <div key={item.id} className="gpu-card gpu-card-compact" style={{ borderColor: `${color}55` }}>
                <span className="gpu-card-icon" style={{ background: color }}><CatIcon size={20} /></span>
                <span className="gpu-card-cat">{t(`mining.comp.${item.category}`, item.category)}</span>
                <span className="gpu-card-name">{hwName(item, t)}</span>
                <div className="gpu-card-specs"><span>{specLine(item.category, item.specs, t)}</span></div>
                <div className="gpu-card-price"><DollarSign size={12} style={{ color }} /> ${formatMoney(item.price)}</div>
                {item.fromAdmin ? (
                  <button
                    className="gpu-card-buy gpu-card-buy-soon"
                    disabled
                    title={t('shop.soonHint')}
                  >
                    <Clock size={12} /> {t('shop.soon')}
                  </button>
                ) : (
                  <button
                    className="gpu-card-buy"
                    style={{ background: affordable ? color : undefined }}
                    disabled={!affordable}
                    onClick={() => setBuyItem(item)}
                  >
                    {affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Модалка покупки: qty, total, balance, кнопка «Купить» (демо). */}
      <BuyModal
        open={!!buyItem}
        item={buyItem}
        balance={balance}
        onConfirm={handleBuyConfirm}
        onCancel={() => setBuyItem(null)}
      />

// Продажа в магазине отключена — карточка показывает только «Купить»,
// продажа/улучшения доступны в MyAssetsTab.
    </div>
  )
}

export default ShopTab
