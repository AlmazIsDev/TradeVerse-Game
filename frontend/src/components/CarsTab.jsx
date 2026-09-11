// ─────────────────────────────────────────────────────────────────────────────
// CarsTab · вкладка «Автосалон».
// Три секции: машины (cars), фуры (trucks) и прицепы (trailers).
// Источник каталога — сервер (/api/assets/market?type=car, backend/assets.py
// → _CAR_CATALOG): цены динамические (рыночный множитель), покупка реальная
// через /api/assets/buy. Локальный carsCatalog.js больше не источник данных.
// ─────────────────────────────────────────────────────────────────────────────
import { useEffect, useMemo, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Car, Truck, Search,
  Coins, ShoppingCart, ArrowUp, ArrowDown,
  Fuel, Package as PackageIcon,
} from 'lucide-react'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'
import MarketBuyModal from './MarketBuyModal'
import { fetchAssetMarket, buyAsset } from '../services/api'
import { CAR_SECTIONS } from '../utils/carsCatalog'

// Ранг редкости для сортировки.
const RARITY_RANK = { common: 0, uncommon: 1, rare: 2, epic: 3, legendary: 4 }

// Цвета/градиенты по редкости (как на «Рынке»).
const RARITY_COLOR = {
  common: '#9ca3af', uncommon: '#22c55e', rare: '#3b82f6',
  epic: '#a855f7', legendary: '#f59e0b',
}
const RARITY_GRAD = {
  common:    'linear-gradient(135deg,#334155,#1e293b)',
  uncommon:  'linear-gradient(135deg,#166534,#14532d)',
  rare:      'linear-gradient(135deg,#1e40af,#1e3a8a)',
  epic:      'linear-gradient(135deg,#6b21a8,#4c1d95)',
  legendary: 'linear-gradient(135deg,#b45309,#78350f)',
}

// Эмодзи по типу техники (для карточки и для модалки).
const TYPE_EMOJI = { car: '🚗', truck: '🚛', trailer: '🛻' }

function CarsTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [section, setSection] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('price')   // 'price' | 'rarity'
  const [sortDir, setSortDir] = useState('asc')   // 'asc' | 'desc'
  // pendingBuy — выбранный для покупки товар; null если модалка закрыта.
  const [pendingBuy, setPendingBuy] = useState(null)
  const [busy, setBusy] = useState(false)
  // Каталог с сервера (динамические цены). Секции truck/trailer живут в
  // поле category; легковые — type "car" без категории или category:"car".
  const [cars, setCars] = useState([])
  const [loading, setLoading] = useState(true)

  const loadCars = useCallback(async () => {
    try {
      const data = await fetchAssetMarket({ type: 'car' })
      const items = (Array.isArray(data) ? data : []).map(c => ({
        id: c.slug,
        slug: c.slug,
        name: c.name,
        category: c.category || 'car',
        type: c.category || 'car',
        rarity: c.rarity || 'common',
        price: c.price,
        specs: c.meta || {},
      }))
      setCars(items)
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { loadCars() }, [loadCars])

  // Дебаунс для поля поиска.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => clearTimeout(id)
  }, [searchInput])

  const toggleSort = useCallback((by) => {
    if (sortBy === by) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(by); setSortDir('asc') }
  }, [sortBy])

  // Витрина: фильтр по секции + поиск + сортировка.
  const view = useMemo(() => {
    let r = cars
    if (section !== 'all') r = r.filter(x => x.category === section)
    if (search) {
      const q = search.toLowerCase()
      r = r.filter(x =>
        (x.name || '').toLowerCase().includes(q) ||
        (x.rarity || '').toLowerCase().includes(q),
      )
    }
    const arr = [...r]
    const dir = sortDir === 'desc' ? -1 : 1
    if (sortBy === 'rarity') {
      arr.sort((a, b) => {
        const ra = RARITY_RANK[a.rarity] ?? 0
        const rb = RARITY_RANK[b.rarity] ?? 0
        if (ra !== rb) return (ra - rb) * dir
        return (a.price || 0) - (b.price || 0)
      })
    } else {
      arr.sort((a, b) => ((a.price || 0) - (b.price || 0)) * dir)
    }
    return arr
  }, [cars, section, search, sortBy, sortDir])

  // Клик «Купить» — открыть модалку.
  const handleBuy = useCallback((item) => {
    setPendingBuy({
      ...item,
      emoji: item.emoji || TYPE_EMOJI[item.type] || '🚗',
      subtitle: t(`cars.cat_${item.category}`, item.category),
    })
  }, [t])

  // Подтверждение покупки: реальная покупка через /api/assets/buy.
  const handleConfirm = useCallback(async () => {
    const item = pendingBuy
    if (!item?.slug) return
    setBusy(true)
    try {
      const res = await buyAsset(item.slug)
      if (res && typeof res.balance === 'number' && onBalanceChange) {
        onBalanceChange(res.balance)
      }
      toast(t('market.bought', { defaultValue: 'Куплено' }) + `: ${item.name}`)
      setPendingBuy(null)
      loadCars()   // цена могла сдвинуться (спрос)
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'))
    } finally {
      setBusy(false)
    }
  }, [pendingBuy, onBalanceChange, t, loadCars])

  return (
    <div className="cars-tab market-tab">
      <h2 className="tab-title">{t('cars.title', 'Автосалон')}</h2>

      {/* Тулбар: пилюли секций, сортировка, поиск. */}
      <div className="market-toolbar">
        <div className="market-cats">
          {CAR_SECTIONS.map(s => {
            const Icon = s.id === 'car' ? Car
              : s.id === 'truck' ? Truck
              : s.id === 'trailer' ? PackageIcon
              : Search
            return (
              <button
                key={s.id}
                className={`tx-pill ${section === s.id ? 'active' : ''}`}
                onClick={() => setSection(s.id)}
              >
                <Icon size={14} /> {t(s.label, s.fallback)}
              </button>
            )
          })}
        </div>
        <div className="shop-toolbar-right">
          <button
            type="button"
            className={`tx-pill${sortBy === 'price' ? ' active' : ''}`}
            onClick={() => toggleSort('price')}
            title={t('cars.sortByPrice', 'Сортировка по цене')}
          >
            {sortBy === 'price' && sortDir === 'desc'
              ? <ArrowDown size={14} />
              : <ArrowUp size={14} />}
            {' '}{t('cars.sortPrice', 'Цена')}
          </button>
          <button
            type="button"
            className={`tx-pill${sortBy === 'rarity' ? ' active' : ''}`}
            onClick={() => toggleSort('rarity')}
            title={t('cars.sortByRarity', 'Сортировка по редкости')}
          >
            {sortBy === 'rarity' && sortDir === 'desc'
              ? <ArrowDown size={14} />
              : <ArrowUp size={14} />}
            {' '}{t('cars.sortRarity', 'Редкость')}
          </button>
          <div className="tx-search market-search">
            <Search size={16} className="tx-search-icon" />
            <input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder={t('cars.searchPlaceholder', 'Поиск по технике…')}
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="empty-state"><p>{t('common.loading', 'Загрузка…')}</p></div>
      ) : view.length === 0 ? (
        <div className="empty-state">
          <p>{t('cars.noItems', 'Ничего не найдено')}</p>
        </div>
      ) : (
        <div className="asset-grid">
          {view.map(item => {
            const rc = RARITY_COLOR[item.rarity] || 'var(--color-accent)'
            const affordable = balance >= item.price
            const isTrailer = item.type === 'trailer'
            return (
              <div
                key={item.id}
                className="asset-card market-card"
                style={{ borderTopColor: rc }}
              >
                <div
                  className="asset-banner"
                  style={{ background: RARITY_GRAD[item.rarity] || RARITY_GRAD.common }}
                >
                  <span className="asset-banner-emoji">
                    {item.emoji || TYPE_EMOJI[item.type]}
                  </span>
                </div>
                <span className="market-card-name">{item.name}</span>
                <div className="market-card-meta">
                  <span className="market-card-rarity" style={{ color: rc }}>
                    {t(`realestate.rarities.${item.rarity}`, item.rarity)}
                  </span>
                  <span className="market-card-cat">
                    {t(`cars.cat_${item.category}`, item.category)}
                  </span>
                </div>

                <div className="asset-stats">
                  <div className="asset-stat">
                    <span>
                      <Fuel size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                      {t('cars.fuelPer100km', 'л / 100 км')}
                    </span>
                    <b>{isTrailer ? '—' : (item.specs?.fuelPer100km ?? 0)}</b>
                  </div>
                  <div className="asset-stat">
                    <span>
                      <PackageIcon size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                      {t('cars.cargoKg', 'Грузоподъёмность')}
                    </span>
                    <b>{(item.specs?.cargoKg || 0).toLocaleString('ru-RU')} {t('cars.kg', 'кг')}</b>
                  </div>
                </div>

                <div className="market-card-price">
                  <span className="mcp-value"><Coins size={16} /> ${formatMoney(item.price)}</span>
                </div>
                <button
                  className="asset-buy-btn"
                  style={{ background: affordable ? rc : undefined }}
                  disabled={!affordable}
                  onClick={() => handleBuy(item)}
                >
                  <ShoppingCart size={14} /> {affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}

      <MarketBuyModal
        open={!!pendingBuy}
        item={pendingBuy}
        balance={balance}
        busy={busy}
        onConfirm={handleConfirm}
        onCancel={() => { if (!busy) setPendingBuy(null) }}
      />
    </div>
  )
}

export default CarsTab
