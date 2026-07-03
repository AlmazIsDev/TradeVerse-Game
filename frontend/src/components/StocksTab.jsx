import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchStocksV2, tradeStock } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { TrendingUp, TrendingDown, DollarSign, AlertTriangle, Loader2 } from 'lucide-react'

function StocksTab() {
  const { t } = useTranslation()
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
      </div>

      {modalStock && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
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
              </div>
            )}

            <div className="modal-buttons">
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
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default StocksTab
