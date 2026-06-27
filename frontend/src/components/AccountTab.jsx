import { useState } from 'react'

function AccountTab() {
  const [accountData] = useState({
    balance: 125430.75,
    totalIncome: 89250.00,
    totalExpense: 43820.25,
    investments: 32450.50,
  })

  const [transactions] = useState([
    { id: 1, type: 'income', label: 'Дивиденды Apple', amount: 1250.00, date: '27.06.2026' },
    { id: 2, type: 'expense', label: 'Покупка акций Tesla', amount: 5300.00, date: '27.06.2026' },
    { id: 3, type: 'income', label: 'Прибыль от продажи BTC', amount: 8700.00, date: '26.06.2026' },
    { id: 4, type: 'expense', label: 'Инвестиция в недвижимость', amount: 15000.00, date: '26.06.2026' },
    { id: 5, type: 'income', label: 'Зарплата компании', amount: 25000.00, date: '25.06.2026' },
    { id: 6, type: 'expense', label: 'Покупка акций Gazprom', amount: 3200.00, date: '25.06.2026' },
  ])

  const [chartData] = useState([
    { day: 'Пн', income: 5200, expense: 3100 },
    { day: 'Вт', income: 8700, expense: 5300 },
    { day: 'Ср', income: 3200, expense: 15000 },
    { day: 'Чт', income: 25000, expense: 3200 },
    { day: 'Пт', income: 12500, expense: 8900 },
    { day: 'Сб', income: 6800, expense: 2100 },
    { day: 'Вс', income: 15000, expense: 4200 },
  ])

  const maxVal = Math.max(...chartData.map(d => Math.max(d.income, d.expense)))

  const formatMoney = (n) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  return (
    <div className="account-tab">
      <h2 className="tab-title">Счёт</h2>

      <div className="account-stats">
        <div className="stat-card stat-balance">
          <div className="stat-icon">💎</div>
          <div className="stat-info">
            <span className="stat-label">Баланс</span>
            <span className="stat-value">{formatMoney(accountData.balance)} ₽</span>
          </div>
        </div>
        <div className="stat-card stat-income">
          <div className="stat-icon">📈</div>
          <div className="stat-info">
            <span className="stat-label">Доходы</span>
            <span className="stat-value">+{formatMoney(accountData.totalIncome)} ₽</span>
          </div>
        </div>
        <div className="stat-card stat-expense">
          <div className="stat-icon">📉</div>
          <div className="stat-info">
            <span className="stat-label">Расходы</span>
            <span className="stat-value">-{formatMoney(accountData.totalExpense)} ₽</span>
          </div>
        </div>
        <div className="stat-card stat-invest">
          <div className="stat-icon">📊</div>
          <div className="stat-info">
            <span className="stat-label">Инвестиции</span>
            <span className="stat-value">{formatMoney(accountData.investments)} ₽</span>
          </div>
        </div>
      </div>

      <div className="account-chart">
        <h3>Аналитика за неделю</h3>
        <div className="chart-container">
          {chartData.map((d, i) => (
            <div key={i} className="chart-bar-group">
              <div className="chart-bars">
                <div
                  className="chart-bar bar-income"
                  style={{ height: `${(d.income / maxVal) * 100}%` }}
                  title={`Доход: ${d.income} ₽`}
                />
                <div
                  className="chart-bar bar-expense"
                  style={{ height: `${(d.expense / maxVal) * 100}%` }}
                  title={`Расход: ${d.expense} ₽`}
                />
              </div>
              <span className="chart-label">{d.day}</span>
            </div>
          ))}
        </div>
        <div className="chart-legend">
          <span className="legend-item legend-income">Доходы</span>
          <span className="legend-item legend-expense">Расходы</span>
        </div>
      </div>

      <div className="account-transactions">
        <h3>Последние операции</h3>
        {transactions.map(t => (
          <div key={t.id} className={`transaction-row ${t.type}`}>
            <div className="transaction-icon">{t.type === 'income' ? '↗' : '↘'}</div>
            <div className="transaction-info">
              <span className="transaction-label">{t.label}</span>
              <span className="transaction-date">{t.date}</span>
            </div>
            <span className={`transaction-amount ${t.type}`}>
              {t.type === 'income' ? '+' : '-'}{formatMoney(t.amount)} ₽
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AccountTab
