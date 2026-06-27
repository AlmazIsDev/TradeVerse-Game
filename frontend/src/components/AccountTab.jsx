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
    startOfWeek.setDate(today.getDate() - today.getDay())
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(startOfWeek)
      d.setDate(startOfWeek.getDate() + i)
      return {
        day: t(`common.${DAY_KEYS[d.getDay()]}`),
        income: 0,
        expense: 0,
      }
    })
  }, [t])

  const maxVal = Math.max(...chartData.map(d => Math.max(d.income, d.expense)))

  const formatMoney = (n) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const totalIncome = transactions
    ? transactions.filter(t => t.type === 'income').reduce((sum, t) => sum + t.amount, 0)
    : 0
  const totalExpense = transactions
    ? transactions.filter(t => t.type === 'expense').reduce((sum, t) => sum + t.amount, 0)
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
        {!loading && !error && transactions && transactions.map(t => (
          <div key={t.id} className={`transaction-row ${t.type}`}>
            <div className="transaction-icon">{t.type === 'income' ? <TrendingUp size={16} /> : <TrendingDown size={16} />}</div>
            <div className="transaction-info">
              <span className="transaction-label">{t.label}</span>
              <span className="transaction-date">{t.date}</span>
            </div>
            <span className={`transaction-amount ${t.type}`}>
              {t.type === 'income' ? '+' : '-'}{formatMoney(t.amount)} $
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AccountTab
