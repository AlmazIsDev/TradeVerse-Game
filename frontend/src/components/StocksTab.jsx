import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchStocksV2, tradeStock, fetchPortfolio } from '../services/api'
import { useApi } from '../hooks/useApi'
import { TrendingUp, TrendingDown, DollarSign, AlertTriangle, Briefcase } from 'lucide-react'

const STORAGE_KEY = 'tradeverse_user'

function StocksTab({ onUserUpdate }) {
  const { t } = useTranslation()
  const { data: stocks, loading, error, refetch } = useApi(fetchStocksV2)
  const { data: portfolio, refetch: refetchPortfolio } = useApi(fetchPortfolio)
  const [modalStock, setModalStock] = useState(null)
  const [modalAction, setModalAction] = useState(null)
  const [modalQuantity, setModalQuantity] = useState(1)
  const [trading, setTrading] = useState(false)
  const [tradeError, setTradeError] = useState(null)

  const openModal = (stock, action) => {
    setModalStock(stock)
    setModalAction(action)
    setModalQuantity(1)
    setTradeError(null)
  }

  const closeModal = () => {
    if (trading) return
    setModalStock(null)
    setModalAction(null)
    setModalQuantity(1)
    setTradeError(null)
  }

  const handleConfirm = async () => {
    if (!modalStock || !modalAction) return
    setTrading(true)
    setTradeError(null)
    try {
      const result = await tradeStock(modalStock.symbol, modalAction, modalQuantity)
      // Обновляем баланс в глобальном состоянии (шапка/аккаунт) и localStorage.
      if (result?.balance != null) {
        if (onUserUpdate) {
          onUserUpdate({ balance: result.balance })
        } else {
          try {
            const stored = localStorage.getItem(STORAGE_KEY)
            if (stored) {
              const u = JSON.parse(stored)
              u.balance = result.balance
              localStorage.setItem(STORAGE_KEY, JSON.stringify(u))
            }
          } catch { /* ignore */ }
        }
      }
      await Promise.all([refetch(), refetchPortfolio()])
      setModalStock(null)
      setModalAction(null)
      setModalQuantity(1)
    } catch (err) {
      setTradeError(err.message || t('common.error'))
    } finally {
      setTrading(false)
    }
  }

  const makeMiniChart = (data, isUp) => {
    if (!data || data.length < 2) return null
    const max = Math.max(...data)
    const min = Math.min(...data)
    const range = max - min || 1
    const points = data.map((v, i) => {
      const x = (i / (data.length - 1)) * 100
      const y = 100 - ((v - min) / range) * 80
      return `${x},${y}`
    }).join(' ')
    return (
      <svg className="mini-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline
          points={points}
          fill="none"
          stroke={isUp ? '#10b981' : '#ef4444'}
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  const formatMoney = (n) => (Number(n) || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const portfolioValue = (portfolio || []).reduce((sum, p) => sum + (p.value || 0), 0)
  const portfolioPnl = (portfolio || []).reduce((sum, p) => sum + (p.pnl || 0), 0)

  const renderPortfolio = () => {
    if (!portfolio || portfolio.length === 0) return null
    return (
      <div className="portfolio-panel">
        <div className="portfolio-header">
          <Briefcase size={18} className="icon" />
          <h3>{t('stocks.portfolio')}</h3>
          <span className="portfolio-total">
            {t('stocks.portfolioValue')}: <strong>${formatMoney(portfolioValue)}</strong>
            <span className={`portfolio-total-pnl ${portfolioPnl >= 0 ? 'up' : 'down'}`}>
              ({portfolioPnl >= 0 ? '+' : ''}{formatMoney(portfolioPnl)} $)
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
                    {up ? '+' : ''}{formatMoney(p.pnl)} $
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="stocks-tab">
        <h2 className="tab-title">{t('stocks.title')}</h2>
        <div className="loading-state">
          <div className="spinner" />
          <p>{t('common.loading')}</p>
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

  if (!stocks || stocks.length === 0) {
    return (
      <div className="stocks-tab">
        <h2 className="tab-title">{t('stocks.title')}</h2>
        <div className="empty-state">
          <p>{t('stocks.noData')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="stocks-tab">
      <h2 className="tab-title">{t('stocks.title')}</h2>
      {renderPortfolio()}
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
                {stock.chart && makeMiniChart(stock.chart, isUp)}
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
      </div>

      {modalStock && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>{modalAction === 'buy' ? t('stocks.buyShares', { ticker: modalStock.symbol }) : t('stocks.sellShares', { ticker: modalStock.symbol })}</h3>
            <p className="modal-company">{modalStock.name}</p>
            <p className="modal-price"><DollarSign size={16} className="icon" /> {t('stocks.pricePerShare')}: ${formatMoney(modalStock.price)}</p>
            {modalStock.freeShares != null && (
              <div className="modal-quantity">
                <label>{t('common.quantity')}:</label>
                <input
                  type="number"
                  min="1"
                  max={modalStock.freeShares}
                  value={modalQuantity}
                  onChange={e => setModalQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                />
              </div>
            )}
            <p className="modal-total">
              {t('common.total')}: <strong>${formatMoney(modalStock.price * modalQuantity)}</strong>
            </p>
            {tradeError && (
              <p className="modal-error" role="alert">
                <AlertTriangle size={14} className="icon" /> {tradeError}
              </p>
            )}
            <div className="modal-buttons">
              <button
                className={`stock-btn ${modalAction === 'buy' ? 'buy-btn' : 'sell-btn'}`}
                onClick={handleConfirm}
                disabled={trading}
              >
                {trading ? t('common.loading') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={closeModal} disabled={trading}>
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
