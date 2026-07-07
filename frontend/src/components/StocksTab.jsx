<<<<<<< HEAD
import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
<<<<<<< HEAD
import { fetchStocksV2, tradeStock } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { TrendingUp, TrendingDown, DollarSign, AlertTriangle, Loader2 } from 'lucide-react'
=======
=======
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
>>>>>>> origin/Marlow
import { fetchStocksV2, tradeStock, fetchPortfolio, issueStock, payDividend } from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import AssetDetail from './AssetDetail'
import {
  TrendingUp, TrendingDown, Briefcase, AlertTriangle, Check, X, PlusCircle, Gift,
<<<<<<< HEAD
} from 'lucide-react'
>>>>>>> origin/Marlow

function StocksTab({ balance = 0, onBalanceChange, currentUserId }) {
  const { t } = useTranslation()
<<<<<<< HEAD
  const { data: stocks, loading, error } = useApiOnMount(fetchStocksV2)
  const [modalStock, setModalStock] = useState(null)
  const [modalAction, setModalAction] = useState(null)
  const [modalQuantity, setModalQuantity] = useState(1)
  const [tradeLoading, setTradeLoading] = useState(false)
  const [tradeResult, setTradeResult] = useState(null)
  const [tradeError, setTradeError] = useState(null)

  const openModal = (stock, action) => {
    setModalStock(stock)
    setModalAction(action)
    setModalQuantity(1)
    setTradeResult(null)
    setTradeError(null)
  }

  const closeModal = () => {
    setModalStock(null)
    setModalAction(null)
    setModalQuantity(1)
    setTradeResult(null)
    setTradeError(null)
  }

  const handleTrade = async () => {
    if (!modalStock || !modalAction || modalQuantity < 1) return

    setTradeLoading(true)
    setTradeResult(null)
    setTradeError(null)

    try {
      const result = await tradeStock(modalStock.symbol, modalAction, modalQuantity)
      setTradeResult(result)
      // Обновляем список акций после успешной сделки
      setTimeout(() => window.location.reload(), 1500)
    } catch (err) {
      setTradeError(err.message || t('common.error'))
    } finally {
      setTradeLoading(false)
    }
  }

  const makeMiniChart = (data, isUp, symbol) => {
    // Если нет данных - не показываем график
    if (!data || data.length < 2) return null

    const chartData = data
    const max = Math.max(...chartData)
    const min = Math.min(...chartData)
    const range = max - min || 1
    const padding = 8
    const usableHeight = 100 - padding * 2

    const points = chartData.map((v, i) => {
      const x = (i / (chartData.length - 1)) * 100
      const y = 100 - padding - ((v - min) / range) * usableHeight
      return `${x},${y}`
    }).join(' ')

    // Точки для закрашенной области
    const areaPoints = `0,100 ${points} 100,100`

    // Определяем цвет на основе тренда
    const startPrice = chartData[0]
    const endPrice = chartData[chartData.length - 1]
    const isPositiveTrend = endPrice >= startPrice
    const color = isPositiveTrend ? '#22c55e' : '#ef4444'
    const colorFaded = isPositiveTrend ? 'rgba(34, 197, 9415)' : 'rgba(239, 68, 68, 0.15)'

    // Уникальный ID для градиента
    const gradientId = `grad-${symbol}-${isPositiveTrend ? 'up' : 'down'}`

    return (
      <svg className="mini-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="50%" stopColor={color} stopOpacity="0.08" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Сетка */}
        <line x1="0" y1="25" x2="100" y2="25" stroke="rgba(255,255,255,0.03)" strokeWidth="0.5" />
        <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(255,255,255,0.03)" strokeWidth="0.5" />
        <line x1="0" y1="75" x2="100" y2="75" stroke="rgba(255,255,255,0.03)" strokeWidth="0.5" />

        {/* Закрашенная область */}
        <polygon
          points={areaPoints}
          fill={`url(#${gradientId})`}
        />

        {/* Основная линия */}
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Точка начала */}
        <circle
          cx="0"
          cy={100 - padding - ((chartData[0] - min) / range) * usableHeight}
          r="1.5"
          fill={color}
          opacity="0.6"
        />

        {/* Точка конца (текущая цена) */}
        <circle
          cx="100"
          cy={100 - padding - ((endPrice - min) / range) * usableHeight}
          r="2"
          fill={color}
        />

        {/* Пунктирная линия тренда */}
        <line
          x1="0"
          cy={100 - padding - ((chartData[0] - min) / range) * usableHeight}
          x2="100"
          y2={100 - padding - ((endPrice - min) / range) * usableHeight}
          stroke={color}
          strokeWidth="0.5"
          strokeDasharray="2,2"
          opacity="0.4"
        />
      </svg>
    )
  }

  const formatMoney = (n) => {
    if (n == null) return '0.00'
    return n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
=======
  const [detailSymbol, setDetailSymbol] = useState(null)
  const [stocks, setStocks] = useState([])
  const [portfolio, setPortfolio] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [trade, setTrade] = useState(null)     // { ...stock, action }
  const [qty, setQty] = useState('1')
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [issueModal, setIssueModal] = useState(false)
  const [issueForm, setIssueForm] = useState({ name: '', symbol: '', price: '', totalShares: '1000000' })
  const [dividend, setDividend] = useState(null)   // stock being paid dividends
  const [perShare, setPerShare] = useState('')

  const load = useCallback(async () => {
    try {
      const [mkt, pf] = await Promise.all([fetchStocksV2(), fetchPortfolio()])
      setStocks(mkt)
      setPortfolio(pf)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openTrade = (stock, action) => {
    setTrade({ ...stock, action })
    setQty('1')
    setFeedback(null)
  }

  const heldFor = (symbol) => portfolio.find(p => p.symbol === symbol)

  const confirmTrade = async () => {
    if (!trade) return
    const q = Math.floor(Number(qty))
    if (!Number.isFinite(q) || q < 1) {
      setFeedback({ type: 'error', text: t('bank.invalidAmount') })
      return
    }
    if (trade.action === 'buy' && q * trade.price > balance) {
      setFeedback({ type: 'error', text: t('stocks.insufficientFunds') })
      return
    }
    const held = heldFor(trade.symbol)
    if (trade.action === 'sell' && (!held || held.quantity < q)) {
      setFeedback({ type: 'error', text: t('stocks.insufficientShares') })
      return
    }
    setBusy(true)
    try {
      const res = await tradeStock(trade.symbol, trade.action, q)
      onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('stocks.tradeSuccess') })
      setRefreshKey(k => k + 1)
      await load()
      setTimeout(() => setTrade(null), 700)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message || t('common.error') })
    } finally {
      setBusy(false)
    }
  }

  const doIssue = async () => {
    const totalShares = Math.floor(Number(issueForm.totalShares))
    const price = Number(issueForm.price)
    if (!issueForm.name.trim() || !issueForm.symbol.trim() || !(price > 0) || !(totalShares >= 1000)) {
      setFeedback({ type: 'error', text: t('stocks.issueInvalid') })
      return
    }
    setBusy(true)
    try {
      const res = await issueStock({
        name: issueForm.name.trim(),
        symbol: issueForm.symbol.trim().toUpperCase(),
        description: '',
        totalShares,
        price,
      })
      onBalanceChange?.(res.balance)
      setIssueModal(false)
      setIssueForm({ name: '', symbol: '', price: '', totalShares: '1000000' })
      setRefreshKey(k => k + 1)
      await load()
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const doDividend = async () => {
    if (!dividend) return
    const per = Number(perShare)
    if (!(per > 0)) return
    setBusy(true)
    try {
      const res = await payDividend(dividend.symbol, per)
      if (res.balance != null) onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('stocks.dividendPaid', { total: formatMoney(res.paid), holders: res.holders }) })
      setDividend(null)
      setPerShare('')
      setRefreshKey(k => k + 1)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  if (detailSymbol) {
    return (
      <AssetDetail
        market="stock"
        symbol={detailSymbol}
        onBack={() => { setDetailSymbol(null); load() }}
        balance={balance}
        onBalanceChange={onBalanceChange}
        onTraded={load}
      />
    )
  }

  const portfolioValue = portfolio.reduce((s, p) => s + (p.value || 0), 0)
  const portfolioPnl = portfolio.reduce((s, p) => s + (p.pnl || 0), 0)
>>>>>>> origin/Marlow

  if (loading) {
    return (
      <div className="stocks-tab">
        <h2 className="tab-title">{t('stocks.title')}</h2>
        <div className="stocks-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="stock-card skeleton" style={{ height: 180 }} />
          ))}
        </div>
=======
  Search, Activity, ArrowDownLeft, ArrowUpRight,
} from 'lucide-react'

// Лёгкий прогноз для акции по проценту изменения (та же логика, что у крипты).
function stockForecast(stock) {
  const change = stock.changePercent || 0
  const vol = Math.round((Math.min(25, Math.abs(change) * 1.5 + 3)) * 10) / 10
  let probUp = 50 + change * 1.4
  probUp = Math.max(5, Math.min(95, Math.round(probUp)))
  return { change, vol, probUp, up: change >= 0 }
}

function StocksTab({ balance = 0, onBalanceChange, currentUserId }) {
  const { t } = useTranslation()
  const [detailSymbol, setDetailSymbol] = useState(null)
  const [stocks, setStocks] = useState([])
  const [portfolio, setPortfolio] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [trade, setTrade] = useState(null)     // { ...stock, action }
  const [qty, setQty] = useState('1')
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [issueModal, setIssueModal] = useState(false)
  const [issueForm, setIssueForm] = useState({ name: '', symbol: '', price: '', totalShares: '1000000' })
  const [dividend, setDividend] = useState(null)   // stock being paid dividends
  const [perShare, setPerShare] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('cap')   // cap | gainers | losers

  const load = useCallback(async () => {
    try {
      const [mkt, pf] = await Promise.all([fetchStocksV2(), fetchPortfolio()])
      setStocks(mkt)
      setPortfolio(pf)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openTrade = (stock, action) => {
    setTrade({ ...stock, action })
    setQty('1')
    setFeedback(null)
  }

  const heldFor = (symbol) => portfolio.find(p => p.symbol === symbol)

  const confirmTrade = async () => {
    if (!trade) return
    const q = Math.floor(Number(qty))
    if (!Number.isFinite(q) || q < 1) {
      setFeedback({ type: 'error', text: t('bank.invalidAmount') })
      return
    }
    if (trade.action === 'buy' && q * trade.price > balance) {
      setFeedback({ type: 'error', text: t('stocks.insufficientFunds') })
      return
    }
    const held = heldFor(trade.symbol)
    if (trade.action === 'sell' && (!held || held.quantity < q)) {
      setFeedback({ type: 'error', text: t('stocks.insufficientShares') })
      return
    }
    setBusy(true)
    try {
      const res = await tradeStock(trade.symbol, trade.action, q)
      onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('stocks.tradeSuccess') })
      setRefreshKey(k => k + 1)
      await load()
      setTimeout(() => setTrade(null), 700)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message || t('common.error') })
    } finally {
      setBusy(false)
    }
  }

  const doIssue = async () => {
    const totalShares = Math.floor(Number(issueForm.totalShares))
    const price = Number(issueForm.price)
    if (!issueForm.name.trim() || !issueForm.symbol.trim() || !(price > 0) || !(totalShares >= 1000)) {
      setFeedback({ type: 'error', text: t('stocks.issueInvalid') })
      return
    }
    setBusy(true)
    try {
      const res = await issueStock({
        name: issueForm.name.trim(),
        symbol: issueForm.symbol.trim().toUpperCase(),
        description: '',
        totalShares,
        price,
      })
      onBalanceChange?.(res.balance)
      setIssueModal(false)
      setIssueForm({ name: '', symbol: '', price: '', totalShares: '1000000' })
      setRefreshKey(k => k + 1)
      await load()
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const doDividend = async () => {
    if (!dividend) return
    const per = Number(perShare)
    if (!(per > 0)) return
    setBusy(true)
    try {
      const res = await payDividend(dividend.symbol, per)
      if (res.balance != null) onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('stocks.dividendPaid', { total: formatMoney(res.paid), holders: res.holders }) })
      setDividend(null)
      setPerShare('')
      setRefreshKey(k => k + 1)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const marketView = useMemo(() => {
    let r = stocks || []
    if (search) {
      const s = search.toLowerCase()
      r = r.filter(c => (c.symbol || '').toLowerCase().includes(s) || (c.name || '').toLowerCase().includes(s))
    }
    r = [...r]
    if (sort === 'gainers') r.sort((a, b) => (b.changePercent || 0) - (a.changePercent || 0))
    else if (sort === 'losers') r.sort((a, b) => (a.changePercent || 0) - (b.changePercent || 0))
    return r
  }, [stocks, search, sort])

  if (detailSymbol) {
    return (
      <AssetDetail
        market="stock"
        symbol={detailSymbol}
        onBack={() => { setDetailSymbol(null); load() }}
        balance={balance}
        onBalanceChange={onBalanceChange}
        onTraded={load}
      />
    )
  }

  const portfolioValue = portfolio.reduce((s, p) => s + (p.value || 0), 0)
  const portfolioPnl = portfolio.reduce((s, p) => s + (p.pnl || 0), 0)

  if (loading) {
    return (
      <div className="stocks-tab crypto-tab">
        <div className="leaderboard-title-row"><Briefcase size={22} className="icon" /><h2 className="tab-title">{t('stocks.title')}</h2></div>
        <div className="skeleton-chart" style={{ height: 160 }} />
>>>>>>> origin/Marlow
      </div>
    )
  }

  if (error) {
    return (
      <div className="stocks-tab crypto-tab">
        <div className="leaderboard-title-row"><Briefcase size={22} className="icon" /><h2 className="tab-title">{t('stocks.title')}</h2></div>
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      </div>
    )
  }

<<<<<<< HEAD
  return (
    <div className="stocks-tab">
<<<<<<< HEAD
      <h2 className="tab-title">{t('stocks.title')}</h2>
      <div className="stocks-grid">
        {stocks.map(stock => {
          const isUp = stock.change >= 0
          const changePercent = stock.changePercent != null ? stock.changePercent : null
          return (
            <div key={stock.id} className={`stock-card ${isUp ? 'stock-up' : 'stock-down'}`}>
              <div className="stock-header">
                <div className="stock-company-info">
                  <span className="stock-ticker">{stock.symbol}</span>
                  <span className="stock-company-name">{stock.name}</span>
                </div>
                {changePercent != null && changePercent !== 0 && (
                  <span className={`stock-change ${isUp ? 'up' : 'down'}`}>
                    {isUp ? <TrendingUp size={14} className="icon" /> : <TrendingDown size={14} className="icon" />} {Math.abs(changePercent).toFixed(2)}%
                  </span>
                )}
              </div>
              <div className="stock-chart-area">
                {makeMiniChart(stock.chart, isUp, stock.symbol)}
              </div>
              <div className="stock-details">
                <div className="stock-price-row">
                  <span className="stock-price-label">{t('stocks.price')}</span>
                  <span className="stock-price-value">${formatMoney(stock.price)}</span>
                </div>
                {stock.freeShares != null && (
                  <div className="stock-shares-row">
                    <span className="stock-shares-label">{t('common.freeShares')}</span>
                    <span className="stock-shares-value">{stock.freeShares.toLocaleString('ru-RU')}</span>
                  </div>
                )}
                {stock.lastEvent && (
                  <div className="stock-event-row">
                    <span className="stock-event-label">⚡ {stock.lastEvent}</span>
                  </div>
                )}
              </div>
              <div className="stock-actions">
                <button className="stock-btn buy-btn" onClick={() => openModal(stock, 'buy')}>
                  {t('common.buy')}
                </button>
                <button className="stock-btn sell-btn" onClick={() => openModal(stock, 'sell')}>
                  {t('common.sell')}
                </button>
              </div>
            </div>
          )
        })}
=======
      <div className="stocks-titlebar">
        <h2 className="tab-title">{t('stocks.title')}</h2>
        <button className="stocks-issue-btn" onClick={() => { setIssueModal(true); setFeedback(null) }}>
          <PlusCircle size={16} /> {t('stocks.issue')}
        </button>
>>>>>>> origin/Marlow
=======
  // Прогноз строим по своим активам, иначе по топу рынка (как в крипте).
  const forecastStocks = (portfolio.length
    ? portfolio.map(p => stocks.find(s => s.symbol === p.symbol)).filter(Boolean)
    : marketView).slice(0, 4)

  const badge = (stock) => (
    <span className="crypto-coin-badge" style={{ background: '#6366f1' }}>{(stock.symbol || '?').slice(0, 2)}</span>
  )

  return (
    <div className="stocks-tab crypto-tab">
      <div className="stocks-titlebar">
        <div className="leaderboard-title-row"><Briefcase size={22} className="icon" /><h2 className="tab-title">{t('stocks.title')}</h2></div>
        <button className="stocks-issue-btn" onClick={() => { setIssueModal(true); setFeedback(null) }}>
          <PlusCircle size={16} /> {t('stocks.issue')}
        </button>
>>>>>>> origin/Marlow
      </div>

      {feedback && !trade && !issueModal && !dividend && (
        <div className={`transfer-feedback ${feedback.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
        </div>
      )}

<<<<<<< HEAD
      {/* Портфель */}
      {portfolio.length > 0 && (
        <div className="portfolio-panel">
          <div className="portfolio-header">
            <Briefcase size={18} className="icon" />
            <h3>{t('stocks.portfolio')}</h3>
            <span className="portfolio-total">
              {t('stocks.portfolioValue')}: <strong>${formatMoney(portfolioValue)}</strong>
              <span className={`portfolio-total-pnl ${portfolioPnl >= 0 ? 'up' : 'down'}`}>
                ({portfolioPnl >= 0 ? '+' : '−'}{formatMoney(Math.abs(portfolioPnl))} $)
              </span>
            </span>
          </div>
          <div className="portfolio-list">
            {portfolio.map(p => {
              const up = p.pnl >= 0
              return (
                <div key={p.symbol} className="portfolio-item">
                  <div className="portfolio-item-main">
                    <span className="portfolio-symbol">{p.symbol}</span>
                    <span className="portfolio-qty">{p.quantity} {t('common.shares')} · ${formatMoney(p.avgPrice)}</span>
                  </div>
                  <div className="portfolio-item-values">
                    <span className="portfolio-value">${formatMoney(p.value)}</span>
                    <span className={`portfolio-pnl ${up ? 'up' : 'down'}`}>
                      {up ? '+' : '−'}{formatMoney(Math.abs(p.pnl))} $
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Рынок */}
      {(!stocks || stocks.length === 0) ? (
        <div className="empty-state"><p>{t('stocks.noData')}</p></div>
      ) : (
        <div className="stocks-grid">
          {stocks.map(stock => {
            const isUp = (stock.change ?? 0) >= 0
            const cp = stock.changePercent
            return (
              <div key={stock.id || stock.symbol} className={`stock-card clickable ${isUp ? 'stock-up' : 'stock-down'}`}
                onClick={() => setDetailSymbol(stock.symbol)}>
                <div className="stock-header">
                  <div className="stock-company-info">
                    <span className="stock-ticker">
                      {stock.symbol}
                      {stock.issuer && <span className="stock-issued-badge">{t('stocks.issued')}</span>}
                    </span>
                    <span className="stock-company-name">
                      {stock.name}
                      {stock.issuerName && <span className="stock-issuer"> · {stock.issuerName}</span>}
                    </span>
                  </div>
                  {cp != null && cp !== 0 && (
                    <span className={`stock-change ${isUp ? 'up' : 'down'}`}>
                      {isUp ? <TrendingUp size={14} className="icon" /> : <TrendingDown size={14} className="icon" />}
                      {Math.abs(cp).toFixed(2)}%
                    </span>
                  )}
                </div>
                <div className="stock-details">
                  <div className="stock-price-row">
                    <span className="stock-price-label">{t('stocks.price')}</span>
                    <span className="stock-price-value">${formatMoney(stock.price)}</span>
                  </div>
                  {stock.heldQuantity > 0 && (
                    <div className="stock-shares-row">
                      <span className="stock-shares-label">{t('stocks.owned')}</span>
                      <span className="stock-shares-value">{stock.heldQuantity.toLocaleString('ru-RU')}</span>
                    </div>
                  )}
                  {stock.freeShares != null && (
                    <div className="stock-shares-row">
                      <span className="stock-shares-label">{t('common.freeShares')}</span>
                      <span className="stock-shares-value">{stock.freeShares.toLocaleString('ru-RU')}</span>
                    </div>
                  )}
                </div>
                <div className="stock-actions">
                  <button className="stock-btn buy-btn" onClick={(e) => { e.stopPropagation(); openTrade(stock, 'buy') }}>
                    {t('common.buy')}
                  </button>
                  <button
                    className="stock-btn sell-btn"
                    onClick={(e) => { e.stopPropagation(); openTrade(stock, 'sell') }}
                    disabled={!stock.heldQuantity}
                  >
                    {t('common.sell')}
                  </button>
                  {stock.issuer && stock.issuer === currentUserId && (
                    <button
                      className="stock-btn dividend-btn"
                      title={t('stocks.payDividend')}
                      onClick={(e) => { e.stopPropagation(); setDividend(stock); setPerShare(''); setFeedback(null) }}
                    >
                      <Gift size={14} />
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* История сделок */}
      <div className="stocks-history">
        <h3>{t('bank.history')}</h3>
        <TransactionsPanel category="trade" refreshKey={refreshKey} />
      </div>

      {/* Модалка сделки */}
      {trade && (
        <div className="modal-overlay" onClick={() => !busy && setTrade(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
<<<<<<< HEAD
            <h3>{modalAction === 'buy' ? t('stocks.buyShares', { ticker: modalStock.symbol }) : t('stocks.sellShares', { ticker: modalStock.symbol })}</h3>
            <p className="modal-company">{modalStock.name}</p>
            <p className="modal-price"><DollarSign size={16} className="icon" /> {t('stocks.pricePerShare')}: ${formatMoney(modalStock.price)}</p>

            {!tradeResult && (
              <>
                <div className="modal-quantity">
                  <label>{t('common.quantity')}:</label>
                  <input
                    type="number"
                    min="1"
                    max={modalStock.freeShares || 1000000}
                    value={modalQuantity}
                    onChange={e => setModalQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                  />
                </div>
                <p className="modal-total">
                  {t('common.total')}: <strong>${formatMoney(modalStock.price * modalQuantity)}</strong>
                </p>
              </>
            )}

            {tradeLoading && (
              <div className="trade-loading">
                <Loader2 size={20} className="spinner" />
                <span>{t('stocks.processing')}</span>
              </div>
            )}

            {tradeResult && (
              <div className="trade-result success">
                <p>✅ {t('stocks.tradeSuccess')}</p>
                <p className="trade-detail">{t('stocks.newPrice')}: <strong>${formatMoney(tradeResult.newStockPrice)}</strong></p>
                {tradeResult.eventApplied && (
                  <p className="trade-event">⚡ {tradeResult.eventApplied}</p>
                )}
              </div>
            )}

            {tradeError && (
              <div className="trade-result error">
                <p>❌ {tradeError}</p>
=======
      <div className="crypto-layout">
        {/* ЛЕВО: рынок акций */}
        <div className="crypto-col-main">
          <div className="crypto-section">
            <div className="crypto-market-head">
              <h3>{t('stocks.market')}</h3>
              <div className="crypto-market-tools">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder={t('market.searchPlaceholder')} /></div>
                <div className="crypto-sort">
                  <button className={`tx-pill ${sort === 'cap' ? 'active' : ''}`} onClick={() => setSort('cap')}>{t('crypto.sortCap')}</button>
                  <button className={`tx-pill ${sort === 'gainers' ? 'active' : ''}`} onClick={() => setSort('gainers')}>{t('crypto.gainers')}</button>
                  <button className={`tx-pill ${sort === 'losers' ? 'active' : ''}`} onClick={() => setSort('losers')}>{t('crypto.losers')}</button>
                </div>
              </div>
            </div>
            {marketView.length === 0 ? (
              <p className="empty-state">{t('stocks.noData')}</p>
            ) : (
              <div className="crypto-market">
                {marketView.map(stock => {
                  const up = (stock.changePercent || 0) >= 0
                  const owned = stock.heldQuantity > 0
                  return (
                    <div key={stock.id || stock.symbol} className="crypto-coin clickable" onClick={() => setDetailSymbol(stock.symbol)}>
                      {badge(stock)}
                      <div className="crypto-coin-info">
                        <span className="crypto-coin-symbol">
                          {stock.symbol}
                          {stock.issuer && <span className="stock-issued-badge">{t('stocks.issued')}</span>}
                        </span>
                        <span className="crypto-coin-name">{stock.name}{stock.issuerName ? ` · ${stock.issuerName}` : ''}</span>
                      </div>
                      <div className="crypto-coin-price">
                        <span className="crypto-coin-value">{formatMoney(stock.price)} $</span>
                        <span className={`crypto-coin-change ${up ? 'up' : 'down'}`}>
                          {up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}{up ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
                        </span>
                      </div>
                      <div className="crypto-coin-actions">
                        <button className="crypto-buy" onClick={(e) => { e.stopPropagation(); openTrade(stock, 'buy') }}><ArrowDownLeft size={14} /> {t('common.buy')}</button>
                        <button className="crypto-sell" onClick={(e) => { e.stopPropagation(); openTrade(stock, 'sell') }} disabled={!owned}><ArrowUpRight size={14} /> {t('common.sell')}</button>
                        {stock.issuer && stock.issuer === currentUserId && (
                          <button className="stock-btn dividend-btn" title={t('stocks.payDividend')}
                            onClick={(e) => { e.stopPropagation(); setDividend(stock); setPerShare(''); setFeedback(null) }}>
                            <Gift size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* ПРАВО: портфель, активы, прогноз, история */}
        <div className="crypto-col-side">
          <div className="crypto-wallet-card">
            <span className="crypto-card-label"><Briefcase size={14} /> {t('stocks.portfolio')}</span>
            <div className="crypto-wallet-stats">
              <div><span>{t('crypto.cashBalance')}</span><b>{formatMoney(balance)} $</b></div>
              <div><span>{t('stocks.portfolioValue')}</span><b className="accent">{formatMoney(portfolioValue)} $</b></div>
              <div><span>{t('stocks.pnl')}</span><b className={portfolioPnl >= 0 ? 'up' : 'down'}>{portfolioPnl >= 0 ? '+' : '−'}{formatMoney(Math.abs(portfolioPnl))} $</b></div>
            </div>
          </div>

          {/* Мои активы */}
          <div className="crypto-section">
            <h3>{t('crypto.myAssets')}</h3>
            {portfolio.length > 0 ? (
              <div className="crypto-holdings">
                {portfolio.map(p => {
                  const up = (p.pnl || 0) >= 0
                  return (
                    <div key={p.symbol} className="crypto-holding clickable" onClick={() => setDetailSymbol(p.symbol)}>
                      {badge(p)}
                      <div className="crypto-holding-info">
                        <span className="crypto-holding-symbol">{p.symbol}</span>
                        <span className="crypto-holding-qty">{p.quantity} {t('common.shares')} · ${formatMoney(p.avgPrice)}</span>
                      </div>
                      <div className="crypto-holding-values">
                        <span className="crypto-holding-value">${formatMoney(p.value)}</span>
                        <span className={`crypto-holding-pnl ${up ? 'up' : 'down'}`}>{up ? '+' : '−'}{formatMoney(Math.abs(p.pnl || 0))} $</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : <p className="empty-state">{t('crypto.noAssets')}</p>}
          </div>

          {/* Прогноз */}
          <div className="crypto-section">
            <h3><Activity size={16} /> {t('crypto.forecast')}</h3>
            <div className="crypto-forecast">
              {forecastStocks.map(s => {
                const f = stockForecast(s)
                return (
                  <div key={s.symbol} className="cf-card clickable" onClick={() => setDetailSymbol(s.symbol)}>
                    <div className="cf-head">{badge(s)}<span>{s.symbol}</span></div>
                    <div className="cf-row"><span>{t('crypto.trend')}</span><b className={f.up ? 'up' : 'down'}>{f.up ? t('crypto.trendUp') : t('crypto.trendDown')}</b></div>
                    <div className="cf-row"><span>{t('crypto.change24')}</span><b className={f.up ? 'up' : 'down'}>{f.change >= 0 ? '+' : ''}{f.change.toFixed(2)}%</b></div>
                    <div className="cf-row"><span>{t('crypto.volatility')}</span><b>{f.vol}%</b></div>
                    <div className="cf-prob">
                      <div className="cf-prob-bar"><div className="cf-prob-fill" style={{ width: `${f.probUp}%` }} /></div>
                      <span className="cf-prob-label"><b className="up">{f.probUp}%</b> {t('crypto.probUp')}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* История сделок */}
          <div className="crypto-section">
            <h3>{t('bank.history')}</h3>
            <TransactionsPanel category="trade" refreshKey={refreshKey} />
          </div>
        </div>
      </div>

      {/* Модалка сделки */}
      {trade && (
        <div className="modal-overlay" onClick={() => !busy && setTrade(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setTrade(null)}><X size={18} /></button>
            <h3>
              {trade.action === 'buy'
                ? t('stocks.buyShares', { ticker: trade.symbol })
                : t('stocks.sellShares', { ticker: trade.symbol })}
            </h3>
            <p className="modal-company">{trade.name}</p>
            <p className="modal-price">{t('stocks.pricePerShare')}: ${formatMoney(trade.price)}</p>

            <div className="modal-quantity">
              <label>{t('common.quantity')}:</label>
              <input
                type="number" min="1" step="1" value={qty} autoFocus
                onChange={e => setQty(e.target.value)}
              />
            </div>

            <p className="modal-total">
              {t('common.total')}: <strong>${formatMoney((Math.floor(Number(qty)) || 0) * trade.price)}</strong>
            </p>

            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
                <span>{feedback.text}</span>
>>>>>>> origin/Marlow
              </div>
            )}

            <div className="modal-buttons">
<<<<<<< HEAD
              {!tradeResult && !tradeLoading && (
                <>
                  <button
                    className={`stock-btn ${modalAction === 'buy' ? 'buy-btn' : 'sell-btn'}`}
                    onClick={handleTrade}
                  >
                    {t('common.confirm')}
                  </button>
                  <button className="stock-btn cancel-btn" onClick={closeModal}>
                    {t('common.cancel')}
                  </button>
                </>
              )}
              {(tradeResult || tradeLoading) && (
                <button className="stock-btn cancel-btn" onClick={closeModal}>
                  {t('common.close')}
                </button>
              )}
=======
            <button className="crypto-modal-close" onClick={() => setTrade(null)}><X size={18} /></button>
            <h3>
              {trade.action === 'buy'
                ? t('stocks.buyShares', { ticker: trade.symbol })
                : t('stocks.sellShares', { ticker: trade.symbol })}
            </h3>
            <p className="modal-company">{trade.name}</p>
            <p className="modal-price">{t('stocks.pricePerShare')}: ${formatMoney(trade.price)}</p>

            <div className="modal-quantity">
              <label>{t('common.quantity')}:</label>
              <input
                type="number" min="1" step="1" value={qty} autoFocus
                onChange={e => setQty(e.target.value)}
              />
            </div>

            <p className="modal-total">
              {t('common.total')}: <strong>${formatMoney((Math.floor(Number(qty)) || 0) * trade.price)}</strong>
            </p>

            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}

            <div className="modal-buttons">
=======
>>>>>>> origin/Marlow
              <button
                className={`stock-btn ${trade.action === 'buy' ? 'buy-btn' : 'sell-btn'}`}
                onClick={confirmTrade}
                disabled={busy}
              >
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setTrade(null)} disabled={busy}>
<<<<<<< HEAD
=======
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка эмиссии акции */}
      {issueModal && (
        <div className="modal-overlay" onClick={() => !busy && setIssueModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setIssueModal(false)}><X size={18} /></button>
            <h3>{t('stocks.issueTitle')}</h3>
            <p className="modal-price">{t('stocks.issueFee')}</p>
            <div className="issue-form">
              <input placeholder={t('stocks.issueName')} value={issueForm.name} maxLength={60}
                onChange={e => setIssueForm({ ...issueForm, name: e.target.value })} />
              <input placeholder={t('stocks.issueTicker')} value={issueForm.symbol} maxLength={6}
                onChange={e => setIssueForm({ ...issueForm, symbol: e.target.value.toUpperCase() })} />
              <input type="number" min="0.01" step="0.01" placeholder={t('stocks.issuePrice')} value={issueForm.price}
                onChange={e => setIssueForm({ ...issueForm, price: e.target.value })} />
              <input type="number" min="1000" step="1000" placeholder={t('stocks.issueShares')} value={issueForm.totalShares}
                onChange={e => setIssueForm({ ...issueForm, totalShares: e.target.value })} />
            </div>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
              </div>
            )}
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={doIssue} disabled={busy}>
                {busy ? t('bank.processing') : t('stocks.issueConfirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setIssueModal(false)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка дивидендов */}
      {dividend && (
        <div className="modal-overlay" onClick={() => !busy && setDividend(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setDividend(null)}><X size={18} /></button>
            <h3>{t('stocks.payDividend')}: {dividend.symbol}</h3>
            <div className="modal-quantity">
              <label>{t('stocks.perShare')}:</label>
              <input type="number" min="0" step="0.01" value={perShare} autoFocus
                onChange={e => setPerShare(e.target.value)} />
            </div>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
              </div>
            )}
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={doDividend} disabled={busy || !(Number(perShare) > 0)}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setDividend(null)} disabled={busy}>
>>>>>>> origin/Marlow
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка эмиссии акции */}
      {issueModal && (
        <div className="modal-overlay" onClick={() => !busy && setIssueModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setIssueModal(false)}><X size={18} /></button>
            <h3>{t('stocks.issueTitle')}</h3>
            <p className="modal-price">{t('stocks.issueFee')}</p>
            <div className="issue-form">
              <input placeholder={t('stocks.issueName')} value={issueForm.name} maxLength={60}
                onChange={e => setIssueForm({ ...issueForm, name: e.target.value })} />
              <input placeholder={t('stocks.issueTicker')} value={issueForm.symbol} maxLength={6}
                onChange={e => setIssueForm({ ...issueForm, symbol: e.target.value.toUpperCase() })} />
              <input type="number" min="0.01" step="0.01" placeholder={t('stocks.issuePrice')} value={issueForm.price}
                onChange={e => setIssueForm({ ...issueForm, price: e.target.value })} />
              <input type="number" min="1000" step="1000" placeholder={t('stocks.issueShares')} value={issueForm.totalShares}
                onChange={e => setIssueForm({ ...issueForm, totalShares: e.target.value })} />
            </div>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
              </div>
            )}
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={doIssue} disabled={busy}>
                {busy ? t('bank.processing') : t('stocks.issueConfirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setIssueModal(false)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка дивидендов */}
      {dividend && (
        <div className="modal-overlay" onClick={() => !busy && setDividend(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setDividend(null)}><X size={18} /></button>
            <h3>{t('stocks.payDividend')}: {dividend.symbol}</h3>
            <div className="modal-quantity">
              <label>{t('stocks.perShare')}:</label>
              <input type="number" min="0" step="0.01" value={perShare} autoFocus
                onChange={e => setPerShare(e.target.value)} />
            </div>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
              </div>
            )}
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={doDividend} disabled={busy || !(Number(perShare) > 0)}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setDividend(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
>>>>>>> origin/Marlow
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default StocksTab
