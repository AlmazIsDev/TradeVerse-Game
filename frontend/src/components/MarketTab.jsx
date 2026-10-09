import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { formatMoney } from './TransactionsPanel'
// Модалка подтверждения покупки для вкладки «Рынок»: показывает товар,
// баланс, цену и кнопку «Купить».
import MarketBuyModal from './MarketBuyModal'
import { fetchAssetMarket, buyAsset } from '../services/api'
import { toast } from './Toast'
// Категории MarketTab. type бэкенда + type каталога должны совпадать
// ('realestate' / 'business' / 'factory' / 'source'), чтобы фильтрация на
// бэкенде и локальный fallback работали одинаково.
import {
  ADMIN_REAL_ESTATE_CATALOG,
  ADMIN_BUSINESS_CATALOG,
  ADMIN_FACTORIES_CATALOG,
  ADMIN_SOURCES_CATALOG,
  ADMIN_WAREHOUSES_CATALOG,
} from '../utils/adminCatalog'
import {
  Home, Briefcase, Search, AlertTriangle,
  Coins, LayoutGrid, ShoppingCart,
  ArrowUpDown, ArrowUp, ArrowDown,
  Factory, Mountain, Warehouse,
} from 'lucide-react'
import { assetImage } from '../utils/assetImages'

// Ранг редкости для сортировки (common < uncommon < rare < epic < legendary).
const RARITY_RANK = { common: 0, uncommon: 1, rare: 2, epic: 3, legendary: 4 }

// Категории-пилюли. Транспорт (car) удалён по требованию — на вкладке «Рынок»
// остались только недвижимость и бизнесы.
// Категории-пилюли на вкладке «Рынок». Добавлены разделы «Заводы» и
// «Источники». Иконки импортированы из lucide-react.
const CATEGORIES = [
  { id: 'all', icon: LayoutGrid },
  { id: 'realestate', icon: Home },
  { id: 'business', icon: Briefcase },
  { id: 'factory', icon: Factory },
  { id: 'source', icon: Mountain },
  { id: 'warehouse', icon: Warehouse },
]

// Разрешённые slug-ы на вкладке «Рынок». Включают недвижимость, бизнесы,
// заводы и источники из admin-каталога (frontend/src/utils/adminCatalog.js).
// Любые другие slug-и (старые 6 базовых домов, 8 базовых бизнесов, itstudio_*,
// media_holding, машины) НЕ отображаются и НЕ покупаются здесь — даже если
// бэкенд их возвращает. Это гарантирует, что витрина показывает только новую
// линейку независимо от того, перезапущен ли бэкенд.
const ADMIN_SLUG_PREFIXES = ['admin-re-', 'admin-biz-', 'admin-fac-', 'admin-src-', 'admin-wh-']
function isAdminMarketSlug(slug) {
  if (!slug) return false
  return ADMIN_SLUG_PREFIXES.some(p => slug.startsWith(p))
}

// Fallback: локальный каталог из adminCatalog.js. Используется, если бэкенд
// по какой-то причине не вернул admin-re-*/admin-biz-* (например, ещё не
// перезапущен после миграции). Структура записей приведена к формату
// /api/assets/market (slug, type, name, price, rarity, ...), чтобы рендер
// MarketTab работал без изменений остального кода.
function buildLocalCatalog() {
  const houses = ADMIN_REAL_ESTATE_CATALOG.map(h => ({
    slug: h.slug,
    type: 'realestate',
    name: h.name,
    rarity: h.rarity,
    rooms: h.rooms,
    basement: h.basement,
    employees: 0,
    price: h.price,
    basePrice: h.price,
    trend: 0,
    incomePerHour: h.specs?.income || 0,
    upkeepPerHour: 0,
    profitPerHour: h.specs?.income || 0,
    meta: {},
    category: h.category_business || null,
  }))
  const businesses = ADMIN_BUSINESS_CATALOG.map(b => ({
    slug: b.slug,
    type: 'business',
    name: b.name,
    rarity: b.rarity || 'common',
    category: b.category_business || b.specs?.category || 'retail',
    rooms: null,
    basement: null,
    employees: b.employees || 0,
    price: b.price,
    basePrice: b.price,
    trend: 0,
    incomePerHour: 0,
    upkeepPerHour: 0,
    profitPerHour: 0,
    meta: {},
  }))
  // Заводы: type='factory', category='gpu'/'cpu'/... — что именно фабрика
  // производит. incomePerHour = выпуск в час (для карточки).
  const factories = ADMIN_FACTORIES_CATALOG.map(f => ({
    slug: f.slug,
    type: 'factory',
    name: f.name,
    rarity: f.rarity || 'rare',
    category: f.category || 'gpu',
    rooms: null,
    basement: null,
    employees: f.employees || 0,
    price: f.price,
    basePrice: f.price,
    trend: 0,
    incomePerHour: 0,
    upkeepPerHour: 0,
    profitPerHour: 0,
    specs: f.specs || {},
    meta: { produces: f.specs?.produces },
  }))
  // Источники ресурсов: type='source', category='mine'/'field'/'sawmill'/...
  const sources = ADMIN_SOURCES_CATALOG.map(s => ({
    slug: s.slug,
    type: 'source',
    name: s.name,
    rarity: s.rarity || 'common',
    category: s.category || 'mine',
    rooms: null,
    basement: null,
    employees: s.employees || 0,
    price: s.price,
    basePrice: s.price,
    trend: 0,
    incomePerHour: 0,
    upkeepPerHour: 0,
    profitPerHour: 0,
    specs: s.specs || {},
    meta: { resource: s.specs?.resource },
  }))
  // Склады: type='warehouse'. Главная характеристика — площадь (areaSqm).
  const warehouses = ADMIN_WAREHOUSES_CATALOG.map(w => ({
    slug: w.slug,
    type: 'warehouse',
    name: w.name,
    rarity: w.rarity || 'common',
    category: 'warehouse',
    rooms: null,
    basement: null,
    employees: w.employees || 0,
    price: w.price,
    basePrice: w.price,
    trend: 0,
    incomePerHour: 0,
    upkeepPerHour: 0,
    profitPerHour: 0,
    specs: w.specs || {},
    meta: { areaSqm: w.specs?.areaSqm },
  }))
  return [...houses, ...businesses, ...factories, ...sources, ...warehouses]
}
const LOCAL_CATALOG = buildLocalCatalog()

const RARITY_COLOR = {
  common: '#9ca3af', uncommon: '#22c55e', rare: '#3b82f6',
  epic: '#a855f7', legendary: '#f59e0b',
}

const RARITY_GRAD = {
  common: 'linear-gradient(135deg,#334155,#1e293b)',
  uncommon: 'linear-gradient(135deg,#166534,#14532d)',
  rare: 'linear-gradient(135deg,#1e40af,#1e3a8a)',
  epic: 'linear-gradient(135deg,#6b21a8,#4c1d95)',
  legendary: 'linear-gradient(135deg,#b45309,#78350f)',
}

const TYPE_EMOJI = { realestate: '🏠', business: '🏢', factory: '🏭', source: '⛰️', warehouse: '🏬' }

const BIZ_CAT_EMOJI = {
  retail: '🛍️',
  service: '🛠️',
  tech: '💻',
  office: '🏢',
}

// Эмодзи для подкатегорий заводов (что именно фабрика производит).
const FAC_PRODUCES_EMOJI = {
  gpu: '🎮',
  cpu: '🧠',
  case: '📦',
  ram: '🧩',
  psu: '⚡',
  bread: '🍞',
}

// Эмодзи для подкатегорий источников (что именно добывается).
const SRC_RESOURCE_EMOJI = {
  metal: '⛓️',
  food: '🌾',
  wood: '🪵',
  stone: '🪨',
  water: '💧',
  oil: '🛢️',
}

function MarketTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [category, setCategory] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  // busy[id] = true, пока идёт покупка (защита от двойного клика).
  const [busy, setBusy] = useState({})
  // pendingBuy — выбранный для покупки товар (для модалки подтверждения).
  // null, если модалка закрыта.
  const [pendingBuy, setPendingBuy] = useState(null)
  // Две независимые сортировки:
  //   sortBy  — по какому полю: 'price' | 'rarity'
  //   sortDir — направление: 'asc' | 'desc'
  // Клик по активной кнопки — переключает направление. Клик по неактивной —
  // делает её активной и сбрасывает направление в 'asc'.
  const [sortBy, setSortBy] = useState('price')   // 'price' | 'rarity'
  const [sortDir, setSortDir] = useState('asc')   // 'asc' | 'desc'
  const toggleSort = useCallback((by) => {
    if (sortBy === by) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(by)
      setSortDir('asc')
    }
  }, [sortBy])

  // Дебаунс для поля поиска — без него ввод дёргает фильтр на каждую клавишу.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => clearTimeout(id)
  }, [searchInput])

  // Загрузка каталога: 81 дом + 12 бизнесов из adminCatalog.js.
  // Бэкенд (GET /api/assets/market) подмешивает живую цену/trend.
  // Покупка идёт POST /api/assets/buy по slug (admin-re-N / admin-biz-N).
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const type = category === 'all' ? undefined : category
      let data = []
      try {
        data = await fetchAssetMarket(type ? { type } : undefined)
      } catch (e) {
        data = []
      }
      const bySlug = new Map()
      for (const it of (Array.isArray(data) ? data : [])) {
        if (it && it.slug) bySlug.set(String(it.slug).trim(), it)
      }
      let locals = LOCAL_CATALOG
      if (type === 'realestate') locals = locals.filter(c => c.type === 'realestate')
      else if (type === 'business') locals = locals.filter(c => c.type === 'business')
      else if (type === 'factory') locals = locals.filter(c => c.type === 'factory')
      else if (type === 'source') locals = locals.filter(c => c.type === 'source')
      else if (type === 'warehouse') locals = locals.filter(c => c.type === 'warehouse')
      const merged = locals.map(local => {
        const fromBack = bySlug.get(local.slug)
        if (fromBack) {
          return {
            ...local,
            ...fromBack,
            slug: fromBack.slug || local.slug,
            type: local.type,
            name: fromBack.name || local.name,
            rarity: fromBack.rarity || local.rarity,
            rooms: fromBack.rooms != null ? fromBack.rooms : local.rooms,
            basement: fromBack.basement != null ? fromBack.basement : local.basement,
            employees: fromBack.employees != null ? fromBack.employees : local.employees,
            price: fromBack.price != null ? fromBack.price : local.price,
            category: fromBack.category || local.category,
          }
        }
        return local
      })
      setItems(merged)
    } catch (err) {
      setError(err?.message || t('common.error', 'Ошибка'))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [category])

  useEffect(() => { load() }, [load])

  // Финальный фильтр витрины: только admin-slug-и + исключаем машины.
  // Это «защитный пояс» — даже если в бэкенде остались старые позиции,
  // они не проберутся на экран.
  // Сортировка управляется двумя независимыми состояниями:
  //   sortBy  = 'price' | 'rarity'   (по какому полю)
  //   sortDir = 'asc'  | 'desc'      (направление)
  // Внутри одной редкости (если sortBy='rarity') — сортируем по цене.
  const view = useMemo(() => {
    let r = items.filter(it => isAdminMarketSlug(it.slug))
    if (search) {
      const q = search.toLowerCase()
      r = r.filter(it =>
        (it.name || '').toLowerCase().includes(q) ||
        (it.rarity || '').toLowerCase().includes(q),
      )
    }
    const arr = [...r]
    const dir = sortDir === 'desc' ? -1 : 1
    if (sortBy === 'rarity') {
      arr.sort((a, b) => {
        const ra = RARITY_RANK[a.rarity] ?? 0
        const rb = RARITY_RANK[b.rarity] ?? 0
        if (ra !== rb) return (ra - rb) * dir        // по редкости с направлением
        return (a.price || 0) - (b.price || 0)       // внутри — по цене ↑
      })
    } else {
      arr.sort((a, b) => ((a.price || 0) - (b.price || 0)) * dir)
    }
    return arr
  }, [items, search, sortBy, sortDir])

  const cardEmoji = useCallback((it) => {
    if (it.type === 'business') {
      return BIZ_CAT_EMOJI[it.category] || '🏢'
    }
    if (it.type === 'factory') {
      // Приоритет: подкатегория производимого продукта, иначе общая иконка.
      return FAC_PRODUCES_EMOJI[it.category] || TYPE_EMOJI.factory
    }
    if (it.type === 'source') {
      return SRC_RESOURCE_EMOJI[it.meta?.resource] || TYPE_EMOJI.source
    }
    return TYPE_EMOJI[it.type] || '📦'
  }, [])

  // Клик по «Купить» в карточке → открываем модалку подтверждения.
  const handleBuy = useCallback((item) => {
    if (!item?.slug) return
    // Эмодзи-иконку берём из cardEmoji(), чтобы баннер в модалке совпадал
    // с тем, что игрок видит на карточке.
    setPendingBuy({
      ...item,
      emoji: cardEmoji(item),
      subtitle: item.type === 'factory'
        ? t('market.cat_factories', 'Заводы')
        : item.type === 'source'
          ? t('market.cat_sources', 'Источники')
          : item.type === 'warehouse'
            ? t('market.cat_warehouses', 'Склады')
            : item.type === 'business'
              ? t('market.cat_business', 'Бизнесы')
              : t('market.cat_realestate', 'Недвижимость'),
    })
  }, [t, cardEmoji])

  // Подтверждение покупки из модалки. Списывает баланс, создаёт экземпляр
  // во владении. На успехе обновляем локальный баланс через onBalanceChange.
  // Фолбэк: если основной /api/assets/buy вернул 404 (например, на сервере
  // прокси режет POST или бэкенд ещё не перезапущен со старым кодом),
  const handleConfirm = useCallback(async () => {
    const item = pendingBuy
    if (!item?.slug) return
    setBusy(prev => ({ ...prev, [item.slug]: true }))
    try {
      const slug = String(item.slug).trim()
      const res = await buyAsset(slug)
      if (res && typeof res.balance === 'number' && onBalanceChange) {
        onBalanceChange(res.balance)
      }
      toast(t('market.bought', { defaultValue: 'Куплено' }) + `: ${item.name}`)
      setPendingBuy(null)
    } catch (err) {
      const detail = err?.status
        ? `[${err.status}] ${err.message || ''}`
        : (err?.message || t('common.error', 'Ошибка'))
      toast(detail, 'error')
    } finally {
      setBusy(prev => ({ ...prev, [item.slug]: false }))
    }
  }, [pendingBuy, onBalanceChange, t])

  const handleCancel = useCallback(() => setPendingBuy(null), [])

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
                <Icon size={14} /> {c.id === 'all' ? t('common.all')
                  : c.id === 'realestate' ? t('market.cat_realestate', 'Недвижимость')
                  : c.id === 'business' ? t('market.cat_business', 'Бизнесы')
                  : c.id === 'factory' ? t('market.cat_factories', 'Заводы')
                  : c.id === 'source' ? t('market.cat_sources', 'Источники')
                  : c.id === 'warehouse' ? t('market.cat_warehouses', 'Склады')
                  : c.id}
              </button>
            )
          })}
        </div>
        <div className="shop-toolbar-right">
          {/* Две независимые кнопки сортировки: по цене и по редкости. */}
          <button
            type="button"
            className={`tx-pill${sortBy === 'price' ? ' active' : ''}`}
            onClick={() => toggleSort('price')}
            title={t('market.sortByPrice', 'Сортировка по цене')}
          >
            {sortBy === 'price' && sortDir === 'desc'
              ? <ArrowDown size={14} />
              : <ArrowUp size={14} />}
            {' '}{t('market.sortPrice', 'Цена')}
          </button>
          <button
            type="button"
            className={`tx-pill${sortBy === 'rarity' ? ' active' : ''}`}
            onClick={() => toggleSort('rarity')}
            title={t('market.sortByRarity', 'Сортировка по редкости')}
          >
            {sortBy === 'rarity' && sortDir === 'desc'
              ? <ArrowDown size={14} />
              : <ArrowUp size={14} />}
            {' '}{t('market.sortRarity', 'Редкость')}
          </button>
          {/* Поиск — всегда на самом правом краю тулбара. */}
          <div className="tx-search market-search">
            <Search size={16} className="tx-search-icon" />
            <input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder={t('market.searchPlaceholder')}
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {loading && (
        <div className="asset-grid">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="asset-card market-card skeleton" style={{ height: 220 }} />
          ))}
        </div>
      )}

      {!loading && !error && view.length === 0 && (
        <div className="empty-state"><p>{t('market.noItems')}</p></div>
      )}

      {!loading && !error && view.length > 0 && (
        <div className="asset-grid">
          {view.map(item => {
            const rc = RARITY_COLOR[item.rarity] || 'var(--color-accent)'
            const affordable = balance >= item.price
            const isBusy = !!busy[item.slug]
            const canBuy = affordable && !isBusy
            const img = assetImage(item.slug, item.type)
            return (
              <div
                key={item.slug}
                className="asset-card market-card"
                style={{ borderTopColor: rc }}
              >
                <div
                  className="asset-banner"
                  style={{ background: RARITY_GRAD[item.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}
                >
                  {img
                    ? <img className="asset-banner-img" src={img} alt="" loading="lazy" />
                    : <span className="asset-banner-emoji">{cardEmoji(item)}</span>}
                </div>
                <span className="market-card-name">{item.name}</span>
                {item.rarity && (
                  <div className="market-card-meta">
                    <span className="market-card-rarity" style={{ color: rc }}>
                      {t(`realestate.rarities.${item.rarity}`, item.rarity)}
                    </span>
                    {item.type === 'business' && item.category && (
                      <span className="market-card-cat">
                        {t(`business.categories.${item.category}`, item.category)}
                      </span>
                    )}
                    {item.type === 'factory' && item.category && (
                      <span className="market-card-cat">
                        {t(`market.factories.${item.category}`, item.category)}
                      </span>
                    )}
                    {item.type === 'source' && item.category && (
                      <span className="market-card-cat">
                        {t(`market.sources.${item.category}`, item.category)}
                      </span>
                    )}
                    {item.type === 'warehouse' && item.specs?.areaSqm != null && (
                      <span className="market-card-cat">
                        {t('market.warehouseBySize', { area: item.specs.areaSqm,
                          defaultValue: `${item.specs.areaSqm.toLocaleString('ru-RU')} м²` })}
                      </span>
                    )}
                  </div>
                )}
                <div className="asset-stats">
                  {item.rooms != null && (
                    <div className="asset-stat">
                      <span>{t('realestate.rooms')}</span><b>{item.rooms}</b>
                    </div>
                  )}
                  {item.employees > 0 && (
                    <div className="asset-stat">
                      <span>{t('market.employees')}</span><b>{item.employees}</b>
                    </div>
                  )}
                  {item.basement != null && (
                    <div className="asset-stat">
                      <span>{t('market.basement')}</span><b>{item.basement}</b>
                    </div>
                  )}
                  {/* Заводы: показываем выпуск в час (outputPerHour). */}
                  {item.type === 'factory' && item.specs?.outputPerHour != null && (
                    <div className="asset-stat">
                      <span>{t('market.productionPerHour', 'Производство/ч')}</span>
                      <b>{item.specs.outputPerHour}</b>
                    </div>
                  )}
                  {/* Источники: показываем добычу и запас. */}
                  {item.type === 'source' && item.specs?.outputPerHour != null && (
                    <div className="asset-stat">
                      <span>{t('market.productionPerHour', 'Производство/ч')}</span>
                      <b>{item.specs.outputPerHour}</b>
                    </div>
                  )}
                  {item.type === 'source' && item.specs?.capacity != null && (
                    <div className="asset-stat">
                      <span>{t('market.capacity', 'Запас')}</span>
                      <b>{item.specs.capacity}</b>
                    </div>
                  )}
                  {/* Склады: главное — площадь (м²) и расчётный запас хранения. */}
                  {item.type === 'warehouse' && item.specs?.areaSqm != null && (
                    <div className="asset-stat">
                      <span>{t('market.areaSqm', 'Площадь')}</span>
                      <b>{item.specs.areaSqm.toLocaleString('ru-RU')} {t('market.sqm', 'м²')}</b>
                    </div>
                  )}
                  {item.type === 'warehouse' && item.specs?.storageCap != null && (
                    <div className="asset-stat">
                      <span>{t('market.capacity', 'Запас')}</span>
                      <b>{item.specs.storageCap.toLocaleString('ru-RU')}</b>
                    </div>
                  )}
                </div>
                <div className="market-card-price">
                  <span className="mcp-value"><Coins size={16} /> ${formatMoney(item.price)}</span>
                </div>
                <button
                  className="asset-buy-btn"
                  style={{ background: canBuy ? rc : undefined }}
                  disabled={!canBuy}
                  onClick={() => handleBuy(item)}
                >
                  <ShoppingCart size={14} /> {affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Модалка подтверждения покупки. */}
      <MarketBuyModal
        open={!!pendingBuy}
        item={pendingBuy}
        balance={balance}
        busy={pendingBuy ? !!busy[pendingBuy.slug] : false}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </div>
  )
}

export default MarketTab
