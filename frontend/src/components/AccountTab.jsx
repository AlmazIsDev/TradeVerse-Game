import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchTransactions } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { TrendingUp, TrendingDown, AlertTriangle, DollarSign } from 'lucide-react'

const DAY_KEYS = ['daySun', 'dayMon', 'dayTue', 'dayWed', 'dayThu', 'dayFri', 'daySat']

function AccountTab({ userId, balance = 0 }) {
  const { t } = useTranslation()
  const { data: transactions, loading, error } = useApiOnMount(
    () => fetchTransactions(userId, 50)
  )
  const chartData = useMemo(() => {
    const today = new Date()
    const startOfWeek = new Date(today)
    startOfWeek.setHours(0, 0, 0, 0)
    startOfWeek.setDate(today.getDate() - today.getDay())
    const endOfWeek = new Date(startOfWeek)
    endOfWeek.setDate(startOfWeek.getDate() + 7)

    const days = Array.from({ length: 7 }, (_, i) => {
      const d = new Date(startOfWeek)
      d.setDate(startOfWeek.getDate() + i)
      return {
        day: t(`common.${DAY_KEYS[d.getDay()]}`),
        income: 0,
        expense: 0,
      }
    })

    // Наполняем график реальными сделками текущей недели (sell — доход, buy — расход).
    if (Array.isArray(transactions)) {
      const DAY_MS = 24 * 60 * 60 * 1000
      for (const tx of transactions) {
        const ts = new Date(tx.timestamp)
        if (isNaN(ts.getTime()) || ts < startOfWeek || ts >= endOfWeek) continue
        const idx = Math.floor((ts - startOfWeek) / DAY_MS)
        if (idx < 0 || idx > 6) continue
        const value = (Number(tx.amount) || 0) * (Number(tx.price) || 0)
        if (tx.type === 'sell') days[idx].income += value
        else days[idx].expense += value
      }
    }
    return days
  }, [t, transactions])

  // max(1, …) — чтобы не делить на ноль, когда сделок ещё нет.
  const maxVal = Math.max(1, ...chartData.map(d => Math.max(d.income, d.expense)))

  const formatMoney = (n) => (Number(n) || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const formatDate = (ts) => {
    if (!ts) return ''
    const d = new Date(ts)
    return isNaN(d.getTime())
      ? ''
      : d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
  }

  // Транзакции с бэкенда: { type: 'buy' | 'sell', symbol, amount, price, timestamp }.
  // Продажа (sell) — поступление средств, покупка (buy) — расход.
  const txValue = (tx) => (Number(tx.amount) || 0) * (Number(tx.price) || 0)

  const totalIncome = transactions
    ? transactions.filter(tx => tx.type === 'sell').reduce((sum, tx) => sum + txValue(tx), 0)
    : 0
  const totalExpense = transactions
    ? transactions.filter(tx => tx.type === 'buy').reduce((sum, tx) => sum + txValue(tx), 0)
    : 0

  return (
    <div className="account-tab">
      <h2 className="tab-title">{t('account.title')}</h2>

      <div className="account-stats">
        <div className="stat-card stat-balance">
          <div className="stat-icon"><DollarSign size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.balance')}</span>
            <span className="stat-value">{formatMoney(balance)} $</span>
          </div>
        </div>
        <div className="stat-card stat-income">
          <div className="stat-icon"><TrendingUp size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.income')}</span>
            <span className="stat-value">+{formatMoney(totalIncome)} $</span>
          </div>
        </div>
        <div className="stat-card stat-expense">
          <div className="stat-icon"><TrendingDown size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.expense')}</span>
            <span className="stat-value">-{formatMoney(totalExpense)} $</span>
          </div>
        </div>
      </div>

      <div className="account-chart">
        <h3>{t('account.weeklyAnalytics')}</h3>
        <div className="chart-container">
          {chartData.map((d, i) => (
            <div key={i} className="chart-bar-group">
              <div className="chart-bars">
                <div
                  className="chart-bar bar-income"
                  style={{ height: `${(d.income / maxVal) * 100}%` }}
                  title={`${t('account.incomeLabel')}: ${d.income} $`}
                />
                <div
                  className="chart-bar bar-expense"
                  style={{ height: `${(d.expense / maxVal) * 100}%` }}
                  title={`${t('account.expenseLabel')}: ${d.expense} $`}
                />
              </div>
              <span className="chart-label">{d.day}</span>
            </div>
          ))}
        </div>
        <div className="chart-legend">
          <span className="legend-item legend-income">{t('account.income')}</span>
          <span className="legend-item legend-expense">{t('account.expense')}</span>
        </div>
      </div>

      <div className="account-transactions">
        <h3>{t('account.transactions')}</h3>
        {loading && (
          <div className="loading-state">
            <div className="spinner" />
            <p>{t('common.loading')}</p>
          </div>
        )}
        {error && (
          <div className="error-state">
            <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
            <p>{t('common.error')}: {error}</p>
          </div>
        )}
        {!loading && !error && transactions && transactions.length === 0 && (
          <div className="empty-state">
            <p>{t('account.noData')}</p>
          </div>
        )}
        {!loading && !error && transactions && transactions.map(tx => {
          const isIncome = tx.type === 'sell'
          const kind = isIncome ? 'income' : 'expense'
          return (
            <div key={tx.id} className={`transaction-row ${kind}`}>
              <div className="transaction-icon">{isIncome ? <TrendingUp size={16} /> : <TrendingDown size={16} />}</div>
              <div className="transaction-info">
                <span className="transaction-label">{t(`common.${tx.type}`)} {tx.symbol}</span>
                <span className="transaction-date">{formatDate(tx.timestamp)}</span>
              </div>
              <span className={`transaction-amount ${kind}`}>
                {isIncome ? '+' : '-'}{formatMoney(txValue(tx))} $
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default AccountTab
