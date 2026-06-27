import { useState } from 'react'

function BankTab() {
  const [transactions] = useState([
    {
      id: 1, type: 'purchase', label: 'Трата',
      stock: 'AAPL', company: 'Apple Inc.',
      amount: 9125.00, quantity: 50, date: '27.06.2026 14:32'
    },
    {
      id: 2, type: 'success', label: 'Успешная продажа',
      stock: 'TSLA', company: 'Tesla Inc.',
      amount: 12290.00, profit: 1790.00, quantity: 50, date: '27.06.2026 12:15'
    },
    {
      id: 3, type: 'purchase', label: 'Трата',
      stock: 'GAZP', company: 'Gazprom',
      amount: 4689.00, quantity: 30, date: '26.06.2026 18:45'
    },
    {
      id: 4, type: 'loss', label: 'Минусовая продажа',
      stock: 'NVDA', company: 'NVIDIA',
      amount: 26250.00, loss: 3750.00, quantity: 30, date: '26.06.2026 16:20'
    },
    {
      id: 5, type: 'success', label: 'Успешная продажа',
      stock: 'SBER', company: 'СберБанк',
      amount: 8622.00, profit: 1222.00, quantity: 30, date: '25.06.2026 10:05'
    },
    {
      id: 6, type: 'purchase', label: 'Трата',
      stock: 'MSFT', company: 'Microsoft',
      amount: 18945.00, quantity: 50, date: '25.06.2026 09:30'
    },
    {
      id: 7, type: 'loss', label: 'Минусовая продажа',
      stock: 'AAPL', company: 'Apple Inc.',
      amount: 5475.00, loss: 1025.00, quantity: 30, date: '24.06.2026 22:10'
    },
    {
      id: 8, type: 'success', label: 'Успешная продажа',
      stock: 'GAZP', company: 'Gazprom',
      amount: 9378.00, profit: 1878.00, quantity: 60, date: '24.06.2026 15:45'
    },
  ])

  const formatMoney = (n) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  return (
    <div className="bank-tab">
      <h2 className="tab-title">Банк — История транзакций</h2>
      <div className="bank-transactions">
        {transactions.map(t => (
          <div key={t.id} className={`bank-transaction ${t.type}`}>
            <div className="bank-tx-icon">
              {t.type === 'purchase' && '🛒'}
              {t.type === 'success' && '✅'}
              {t.type === 'loss' && '⚠️'}
            </div>
            <div className="bank-tx-info">
              <span className={`bank-tx-label ${t.type}`}>{t.label}</span>
              <span className="bank-tx-stock">{t.stock} · {t.company}</span>
              <span className="bank-tx-meta">
                {t.quantity} акций · {t.date}
              </span>
            </div>
            <div className="bank-tx-amounts">
              <span className="bank-tx-total">{formatMoney(t.amount)} ₽</span>
              {t.type === 'success' && (
                <span className="bank-tx-profit">+{formatMoney(t.profit)} ₽</span>
              )}
              {t.type === 'loss' && (
                <span className="bank-tx-loss">(-{formatMoney(t.loss)} ₽)</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default BankTab
