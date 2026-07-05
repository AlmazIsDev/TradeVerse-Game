import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchTransactions } from '../services/api'
import {
  ArrowDownLeft, ArrowUpRight, Search, ChevronLeft, ChevronRight,
  Send, LineChart, Coins, Briefcase, Home, ShoppingCart, Settings, AlertTriangle,
  Store, Castle, Gift,
} from 'lucide-react'

const PAGE_SIZE = 8

const CATEGORY_ICON = {
  transfer: Send,
  trade: LineChart,
  crypto: Coins,
  business: Briefcase,
  realestate: Home,
  company: Store,
  cityroof: Castle,
  dividend: Gift,
  shop: ShoppingCart,
  system: Settings,
}

function formatMoney(n) {
  return Number(n || 0).toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/**
 * Полная панель истории операций: фильтр (все/доход/расход), поиск,
 * сортировка, пагинация, карточки. Данные — из JWT-scoped API.
 */
function TransactionsPanel({ refreshKey = 0, category }) {
  const { t } = useTranslation()
  const [direction, setDirection] = useState('')
  const [sort, setSort] = useState('date_desc')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Дебаунс поиска
  useEffect(() => {
    const id = setTimeout(() => { setSearch(searchInput.trim()); setPage(0) }, 350)
    return () => clearTimeout(id)
  }, [searchInput])

  // Сброс страницы при смене фильтра/сортировки
  useEffect(() => { setPage(0) }, [direction, sort])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchTransactions({
      direction: direction || undefined,
      category: category || undefined,
      search: search || undefined,
      sort,
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    })
      .then(res => { if (!cancelled) { setData(res); setLoading(false) } })
      .catch(err => { if (!cancelled) { setError(err.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [direction, sort, search, page, refreshKey, category])

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / PAGE_SIZE))
  const fromItem = data.total === 0 ? 0 : page * PAGE_SIZE + 1
  const toItem = Math.min((page + 1) * PAGE_SIZE, data.total || 0)

  const directionFilters = useMemo(() => ([
    { id: '', label: t('tx.all') },
    { id: 'income', label: t('tx.income') },
    { id: 'expense', label: t('tx.expense') },
  ]), [t])

  return (
    <div className="tx-panel">
      <div className="tx-toolbar">
        <div className="tx-search">
          <Search size={16} className="tx-search-icon" />
          <input
            type="text"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            placeholder={t('tx.searchPlaceholder')}
          />
        </div>
        <div className="tx-filters">
          {directionFilters.map(f => (
            <button
              key={f.id || 'all'}
              className={`tx-pill ${direction === f.id ? 'active' : ''}`}
              onClick={() => setDirection(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <select className="tx-sort" value={sort} onChange={e => setSort(e.target.value)}>
          <option value="date_desc">{t('tx.sortDateDesc')}</option>
          <option value="date_asc">{t('tx.sortDateAsc')}</option>
          <option value="amount_desc">{t('tx.sortAmountDesc')}</option>
          <option value="amount_asc">{t('tx.sortAmountAsc')}</option>
        </select>
      </div>

      {loading && (
        <div className="tx-list">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="tx-card skeleton" />
          ))}
        </div>
      )}

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {!loading && !error && data.items.length === 0 && (
        <div className="empty-state"><p>{t('tx.empty')}</p></div>
      )}

      {!loading && !error && data.items.length > 0 && (
        <div className="tx-list">
          {data.items.map(item => {
            const isIncome = item.direction === 'income'
            const CatIcon = CATEGORY_ICON[item.category] || Settings
            return (
              <div key={item.id} className={`tx-card ${item.direction}`}>
                <div className={`tx-card-icon ${item.direction}`}>
                  {isIncome ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}
                </div>
                <div className="tx-card-body">
                  <span className="tx-card-label">{item.label}</span>
                  <span className="tx-card-meta">
                    <span className="tx-card-cat">
                      <CatIcon size={12} />
                      {t(`tx.categories.${item.category}`, item.category)}
                    </span>
                    <span className="tx-card-date">{formatDateTime(item.timestamp)}</span>
                  </span>
                </div>
                <div className="tx-card-amounts">
                  <span className={`tx-card-amount ${item.direction}`}>
                    {isIncome ? '+' : '−'}{formatMoney(item.amount)} $
                  </span>
                  {item.balance_after != null && (
                    <span className="tx-card-balance">{formatMoney(item.balance_after)} $</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {!loading && !error && data.total > PAGE_SIZE && (
        <div className="tx-pagination">
          <button
            className="tx-page-btn"
            disabled={page === 0}
            onClick={() => setPage(p => Math.max(0, p - 1))}
          >
            <ChevronLeft size={16} /> {t('tx.prev')}
          </button>
          <span className="tx-page-info">
            {t('tx.showing', { from: fromItem, to: toItem, total: data.total })}
          </span>
          <button
            className="tx-page-btn"
            disabled={page >= totalPages - 1}
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
          >
            {t('tx.next')} <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

export { formatMoney, formatDateTime }
export default TransactionsPanel
