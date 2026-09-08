import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { formatMoney } from './TransactionsPanel'
import { ADMIN_MARKET_CATALOG, ADMIN_DEFAULT_PRICES } from '../utils/adminCatalog'
import {
  Home, Briefcase, Search, Clock, AlertTriangle,
  TrendingUp, Coins, LayoutGrid, KeyRound,
} from 'lucide-react'

// Категории-пилюли. Транспорт (car) удалён по требованию — на вкладке «Рынок»
// остались только недвижимость и бизнесы из админ-каталога.
const CATEGORIES = [
  { id: 'all', icon: LayoutGrid },
  { id: 'realestate', icon: Home },
  { id: 'business', icon: Briefcase },
]

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

const TYPE_EMOJI = { realestate: '🏠', business: '🏢' }

// Сопоставление category бизнеса (retail/service/tech/office) → эмодзи для
// быстрой визуальной идентификации. Дублируется из adminCatalog.js, потому что
// карточка на «Рынке» рисуется здесь, а не из каталога напрямую.
const BIZ_CAT_EMOJI = {
  retail: '🛍️',
  service: '🛠️',
  tech: '💻',
  office: '🏢',
}

function MarketTab() {
  const { t } = useTranslation()
  const [category, setCategory] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)

  // Дебаунс для поля поиска — без него ввод дёргает фильтр на каждую клавишу.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => clearTimeout(id)
  }, [searchInput])

  // Сохранённые админом цены. Подтягиваются ТОЛЬКО если залогинен админ —
  // обычные игроки видят дефолты из ADMIN_MARKET_CATALOG (согласованные
  // с экономикой). Словарь: {<numericId>: <price>}, где numericId = N
  // из admin-re-N / admin-biz-N.
  const [adminPrices, setAdminPrices] = useState({})

  useEffect(() => {
    let cancelled = false
    async function loadAdminPrices() {
      try {
        const stored = localStorage.getItem('tradeverse_user')
        const user = stored ? JSON.parse(stored) : null
        if (user?.role !== 'admin') return
        const token = user.token
        if (!token) return
        const resp = await fetch('/api/admin/shop-prices', {
          headers: { 'Authorization': 'Bearer ' + token },
        })
        if (cancelled || !resp.ok) return
        const data = await resp.json()
        const stored_prices = data.prices || {}
        // Подмешиваем дефолты, чтобы было что показать, если админ ещё
        // ничего не правил.
        const merged = { ...ADMIN_DEFAULT_PRICES }
        for (const k of Object.keys(stored_prices)) {
          if (stored_prices[k] !== undefined) merged[k] = stored_prices[k]
        }
        if (!cancelled) setAdminPrices(merged)
      } catch {
        // ignore — MarketTab работает и без админ-цен
      }
    }
    loadAdminPrices()
    return () => { cancelled = true }
  }, [])

  // Витрина собирается из ADMIN_MARKET_CATALOG (см. utils/adminCatalog.js):
  // это справочник из PriceEditorTab (admin.prices.realestate / business).
  // Покупка/продажа пока отключены — кнопка «Купить» заменена на «Скоро»
  // (как в ShopTab для GPU/CPU/case). Бэкенд /api/assets/market не дёргаем.
  const items = useMemo(() => {
    try {
      let list = ADMIN_MARKET_CATALOG
      if (category !== 'all') {
        list = list.filter(it => it.category === category)
      }
      if (search) {
        const q = search.toLowerCase()
        list = list.filter(it =>
          (it.name || '').toLowerCase().includes(q) ||
          (it.rarity || '').toLowerCase().includes(q) ||
          (it.category_business || '').toLowerCase().includes(q),
        )
      }
      // Если для этой позиции админ сохранил свою цену — показываем её.
      // В adminCatalog id имеет вид admin-re-<N> / admin-biz-<N>; в
      // adminPrices ключ — число N (см. ADMIN_DEFAULT_PRICES).
      const hasAdminOverride = Object.keys(adminPrices).length > 0
      if (hasAdminOverride) {
        list = list.map(it => {
          const m = (it.id || '').match(/^admin-(?:re|biz)-(\d+)$/)
          if (!m) return it
          const pid = parseInt(m[1], 10)
          if (adminPrices[pid] != null) {
            return { ...it, price: adminPrices[pid], priceOverridden: true }
          }
          return it
        })
      }
      // Сортировка: дешёвые сверху, легендарные в конце.
      return [...list].sort((a, b) => (a.price || 0) - (b.price || 0))
    } catch (e) {
      setError(e.message)
      return []
    }
  }, [category, search, adminPrices])

  const cardEmoji = useCallback((it) => {
    if (it.category === 'business') {
      return BIZ_CAT_EMOJI[it.category_business] || it.emoji || '🏢'
    }
    return TYPE_EMOJI[it.category] || '📦'
  }, [])

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

      <div className="market-rental-note">
        <KeyRound size={16} />
        <span>{t('market.rentalNote')}</span>
      </div>

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {!error && items.length === 0 && (
        <div className="empty-state"><p>{t('market.noItems')}</p></div>
      )}

      {!error && items.length > 0 && (
        <div className="asset-grid">
          {items.map(item => {
            const rc = RARITY_COLOR[item.rarity] || 'var(--color-accent)'
            return (
              <div
                key={item.id}
                className="asset-card market-card"
                style={{ borderTopColor: rc }}
              >
                <div
                  className="asset-banner"
                  style={{ background: RARITY_GRAD[item.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}
                >
                  <span className="asset-banner-emoji">{cardEmoji(item)}</span>
                </div>
                <span className="market-card-name">{item.name}</span>
                {(item.rarity || item.category_business) && (
                  <div className="market-card-meta">
                    {item.rarity && (
                      <span className="market-card-rarity" style={{ color: rc }}>
                        {t(`realestate.rarities.${item.rarity}`, item.rarity)}
                      </span>
                    )}
                    {item.category_business && (
                      <span className="market-card-cat">
                        {t(`business.categories.${item.category_business}`, item.category_business)}
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
                </div>
                <div className="market-card-price">
                  <span className="mcp-value"><Coins size={16} /> ${formatMoney(item.price)}</span>
                </div>
                {/* Все позиции здесь — из админ-каталога, покупка/продажа
                    пока не подключены к бэкенду (см. adminCatalog.js). */}
                <button
                  className="asset-buy-btn market-soon-btn"
                  disabled
                  title={t('market.soonHint', t('shop.soonHint'))}
                >
                  <Clock size={14} /> {t('market.soon', t('shop.soon'))}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default MarketTab
