import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
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

// Локаль числового форматирования по текущему языку интерфейса.
const LOCALE_BY_LANG = { es: 'es-ES', en: 'en-US', ru: 'ru-RU' }
function currentLocale() {
  return LOCALE_BY_LANG[i18n.language?.slice(0, 2)] || 'en-US'
}

function formatMoney(n) {
  return Number(n || 0).toLocaleString(currentLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** Компактный формат для больших сумм (3,5 млн, 12,30 трлн) — чтобы числа не вылезали из блоков. */
function formatCompact(n) {
  const v = Number(n || 0)
  const abs = Math.abs(v)
  const locale = currentLocale()
  const s = (x) => Number(x).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const u = (k) => ' ' + i18n.t(`units.${k}`)
  if (abs >= 1e12) return s(v / 1e12) + u('trillionShort')
  if (abs >= 1e9) return s(v / 1e9) + u('billionShort')
  if (abs >= 1e6) return s(v / 1e6) + u('millionShort')
  if (abs >= 1e5) return Number(v / 1e3).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + u('thousandShort')
  return v.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Полная сумма до миллиона, компактная (млн/млрд) выше — числа не переносятся по цифрам. */
function formatMoneyShort(n) {
  const v = Number(n || 0)
  return Math.abs(v) >= 1e6 ? formatCompact(v) + ' $' : formatMoney(v) + ' $'
}

/**
 * Количество монет/акций без потери значащих цифр.
 *
 * Округлять нельзя: мелкий остаток вроде 0.00000042 схлопывался в «0», и
 * страница токена показывала ноль, хотя портфель стоил реальных денег.
 * Целые печатаем без дробной части, дробные — до 8 знаков без хвостовых нулей.
 */
function formatQty(n) {
  const v = Number(n || 0)
  if (!Number.isFinite(v)) return '0'
  if (Number.isInteger(v)) {
    // Целые с хвостом нулей (3 500 000) компактно: «3,50 млн» вместо «3,5e+6».
    if (Math.abs(v) >= 1e6) return formatCompact(v)
    return v.toLocaleString(currentLocale())
  }
  const [int, frac = ''] = v.toFixed(8).replace(/0+$/, '').split('.')
  // Пыль меньше 1e-8 округлилась бы в ноль — показываем значащие цифры как есть.
  if (!frac && v !== 0) {
    if (Math.abs(v) >= 1e6) return formatCompact(v)
    return v.toPrecision(2).replace('.', ',')
  }
  const intPart = Number(int).toLocaleString(currentLocale())
  const decSep = currentLocale().startsWith('ru') || currentLocale().startsWith('es') ? ',' : '.'
  return frac ? `${intPart}${decSep}${frac}` : intPart
}

function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(currentLocale(), {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/**
 * Описание операции по структурированным полям (meta/symbol/category).
 * Если данных недостаточно, возвращает исходный label с сервера.
 */
function describeItem(item, t) {
  const meta = item.meta || {}
  const qty = meta.quantity ?? meta.qty
  const action = meta.action
  if (item.symbol && qty != null && (action === 'buy' || action === 'sell')) {
    return t(`tx.tpl.${action}`, {
      qty: formatQty(qty),
      symbol: item.symbol,
      defaultValue: item.label,
    })
  }
  if (item.category === 'crypto' && item.symbol && qty != null) {
    const kind = item.direction === 'income' ? 'sell' : 'buy'
    return t(`tx.tpl.${kind}`, { qty: formatQty(qty), symbol: item.symbol, defaultValue: item.label })
  }
  if (item.category === 'farm' && meta.liters != null) {
    return t('tx.tpl.fuel', { liters: formatQty(meta.liters), defaultValue: item.label })
  }
  if (item.category === 'cityroof' && meta.warcoin != null) {
    return t('tx.tpl.warcoin', { qty: formatQty(meta.warcoin), defaultValue: item.label })
  }
  if (meta.slug && i18n.exists(`assetNames.${meta.slug}`)) {
    const name = t(`assetNames.${meta.slug}`)
    if (/^Покупка:/.test(item.label)) return t('tx.tpl.buyItem', { name })
    if (/^Продажа:/.test(item.label)) return t('tx.tpl.sellItem', { name })
    if (/^Доход:/.test(item.label)) return t('tx.tpl.income', { name })
  }
  return item.label
}

/**
 * Полная панель истории операций: фильтр (все/доход/расход), поиск,
 * сортировка, пагинация, карточки. Данные — из JWT-scoped API.
 */
function TransactionsPanel({ refreshKey = 0, category, companyId }) {
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
      companyId: companyId || undefined,
    })
      .then(res => { if (!cancelled) { setData(res); setLoading(false) } })
      .catch(err => { if (!cancelled) { setError(err.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [direction, sort, search, page, refreshKey, category, companyId])

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / PAGE_SIZE))
  const fromItem = data.total === 0 ? 0 : page * PAGE_SIZE + 1
  const toItem = Math.min((page + 1) * PAGE_SIZE, data.total || 0)
  const isExact = data.totalExact !== false
  const canGoNext = data.hasMore !== undefined ? data.hasMore : page < totalPages - 1

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
                  <span className="tx-card-label">{describeItem(item, t)}</span>
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

      {!loading && !error && (data.total > PAGE_SIZE || page > 0 || data.hasMore) && (
        <div className="tx-pagination">
          <button
            className="tx-page-btn"
            disabled={page === 0}
            onClick={() => setPage(p => Math.max(0, p - 1))}
          >
            <ChevronLeft size={16} /> {t('tx.prev')}
          </button>
          <span className="tx-page-info">
            {isExact
              ? t('tx.showing', { from: fromItem, to: toItem, total: data.total })
              : `${t('tx.page', { page: page + 1 })} (${fromItem}–${toItem})`
            }
          </span>
          <button
            className="tx-page-btn"
            disabled={!canGoNext}
            onClick={() => setPage(p => p + 1)}
          >
            {t('tx.next')} <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

export { formatMoney, formatMoneyShort, formatCompact, formatQty, formatDateTime }
export default TransactionsPanel
