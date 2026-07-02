import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchStocks } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { TrendingUp, TrendingDown, DollarSign, AlertTriangle } from 'lucide-react'

function StocksTab() {
  const { t } = useTranslation()
  const { data: stocks, loading, error } = useApiOnMount(fetchStocks)
  const [modalStock, setModalStock] = useState(null)
  const [modalAction, setModalAction] = useState(null)
  const [modalQuantity, setModalQuantity] = useState(1)

  const openModal = (stock, action) => {
    setModalStock(stock)
    setModalAction(action)
    setModalQuantity(1)
  }

  const closeModal = () => {
    setModalStock(null)
    setModalAction(null)
    setModalQuantity(1)
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

  const formatMoney = (n) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

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
            <div className="modal-buttons">
              <button className={`stock-btn ${modalAction === 'buy' ? 'buy-btn' : 'sell-btn'}`} onClick={closeModal}>
                {t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={closeModal}>
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
