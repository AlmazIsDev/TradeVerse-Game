import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchStocksV2, tradeStock, fetchPortfolio } from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import {
  TrendingUp, TrendingDown, Briefcase, AlertTriangle, Check, X,
} from 'lucide-react'

function StocksTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [stocks, setStocks] = useState([])
  const [portfolio, setPortfolio] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [trade, setTrade] = useState(null)     // { ...stock, action }
  const [qty, setQty] = useState('1')
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

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

  const portfolioValue = portfolio.reduce((s, p) => s + (p.value || 0), 0)
  const portfolioPnl = portfolio.reduce((s, p) => s + (p.pnl || 0), 0)

  if (loading) {
    return (
      <div className="stocks-tab">
        <h2 className="tab-title">{t('stocks.title')}</h2>
        <div className="stocks-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="stock-card skeleton" style={{ height: 180 }} />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="stocks-tab">
        <h2 className="tab-title">{t('stocks.title')}</h2>
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="stocks-tab">
      <h2 className="tab-title">{t('stocks.title')}</h2>

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
              <div key={stock.id || stock.symbol} className={`stock-card ${isUp ? 'stock-up' : 'stock-down'}`}>
                <div className="stock-header">
                  <div className="stock-company-info">
                    <span className="stock-ticker">{stock.symbol}</span>
                    <span className="stock-company-name">{stock.name}</span>
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
                  <button className="stock-btn buy-btn" onClick={() => openTrade(stock, 'buy')}>
                    {t('common.buy')}
                  </button>
                  <button
                    className="stock-btn sell-btn"
                    onClick={() => openTrade(stock, 'sell')}
                    disabled={!stock.heldQuantity}
                  >
                    {t('common.sell')}
                  </button>
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
              <button
                className={`stock-btn ${trade.action === 'buy' ? 'buy-btn' : 'sell-btn'}`}
                onClick={confirmTrade}
                disabled={busy}
              >
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setTrade(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default StocksTab
