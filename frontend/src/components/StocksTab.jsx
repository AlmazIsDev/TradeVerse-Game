import { useState } from 'react'

function StocksTab() {
  const [stocks] = useState([
    {
      id: 1, company: 'Apple Inc.', ticker: 'AAPL',
      price: 182.50, change: +3.24, freeShares: 1240,
      chart: [170, 172, 175, 173, 178, 180, 182]
    },
    {
      id: 2, company: 'Tesla Inc.', ticker: 'TSLA',
      price: 245.80, change: -5.12, freeShares: 890,
      chart: [260, 255, 258, 250, 248, 246, 245]
    },
    {
      id: 3, company: 'Gazprom', ticker: 'GAZP',
      price: 156.30, change: +1.87, freeShares: 3200,
      chart: [150, 152, 151, 154, 155, 156, 156]
    },
    {
      id: 4, company: 'Microsoft', ticker: 'MSFT',
      price: 378.90, change: +7.45, freeShares: 670,
      chart: [365, 368, 370, 372, 375, 376, 378]
    },
    {
      id: 5, company: 'NVIDIA', ticker: 'NVDA',
      price: 875.20, change: -12.30, freeShares: 430,
      chart: [900, 895, 890, 885, 880, 878, 875]
    },
    {
      id: 6, company: 'СберБанк', ticker: 'SBER',
      price: 287.40, change: +4.56, freeShares: 2100,
      chart: [275, 278, 280, 282, 284, 286, 287]
    },
  ])

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

  return (
    <div className="stocks-tab">
      <h2 className="tab-title">Акции</h2>
      <div className="stocks-grid">
        {stocks.map(stock => {
          const isUp = stock.change >= 0
          return (
            <div key={stock.id} className={`stock-card ${isUp ? 'stock-up' : 'stock-down'}`}>
              <div className="stock-header">
                <div className="stock-company-info">
                  <span className="stock-ticker">{stock.ticker}</span>
                  <span className="stock-company-name">{stock.company}</span>
                </div>
                <span className={`stock-change ${isUp ? 'up' : 'down'}`}>
                  {isUp ? '▲' : '▼'} {Math.abs(stock.change).toFixed(2)}%
                </span>
              </div>
              <div className="stock-chart-area">
                {makeMiniChart(stock.chart, isUp)}
              </div>
              <div className="stock-details">
                <div className="stock-price-row">
                  <span className="stock-price-label">Цена</span>
                  <span className="stock-price-value">${formatMoney(stock.price)}</span>
                </div>
                <div className="stock-shares-row">
                  <span className="stock-shares-label">Свободных</span>
                  <span className="stock-shares-value">{stock.freeShares.toLocaleString('ru-RU')}</span>
                </div>
              </div>
              <div className="stock-actions">
                <button className="stock-btn buy-btn" onClick={() => openModal(stock, 'buy')}>
                  Купить
                </button>
                <button className="stock-btn sell-btn" onClick={() => openModal(stock, 'sell')}>
                  Продать
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {modalStock && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>{modalAction === 'buy' ? 'Купить' : 'Продать'} акции {modalStock.ticker}</h3>
            <p className="modal-company">{modalStock.company}</p>
            <p className="modal-price">Цена за акцию: ${formatMoney(modalStock.price)}</p>
            <div className="modal-quantity">
              <label>Количество:</label>
              <input
                type="number"
                min="1"
                max={modalStock.freeShares}
                value={modalQuantity}
                onChange={e => setModalQuantity(Math.max(1, parseInt(e.target.value) || 1))}
              />
            </div>
            <p className="modal-total">
              Итого: <strong>${formatMoney(modalStock.price * modalQuantity)}</strong>
            </p>
            <div className="modal-buttons">
              <button className={`stock-btn ${modalAction === 'buy' ? 'buy-btn' : 'sell-btn'}`} onClick={closeModal}>
                Подтвердить
              </button>
              <button className="stock-btn cancel-btn" onClick={closeModal}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default StocksTab
