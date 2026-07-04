import { useTranslation } from 'react-i18next'
import { fetchWeeklyAnalytics } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import {
  TrendingUp, TrendingDown, DollarSign, Activity, AlertTriangle,
} from 'lucide-react'

const WEEKDAY_KEYS = ['dayMon', 'dayTue', 'dayWed', 'dayThu', 'dayFri', 'daySat', 'daySun']

function AccountTab({ balance = 0 }) {
  const { t } = useTranslation()
  const { data, loading, error } = useApiOnMount(() => fetchWeeklyAnalytics())

  const analytics = data || { income: 0, expense: 0, net: 0, operations: 0, days: [] }
  const displayBalance = data?.balance != null ? data.balance : balance
  const days = analytics.days || []
  const maxVal = Math.max(1, ...days.map(d => Math.max(d.income, d.expense)))
  const netPositive = analytics.net >= 0

  return (
    <div className="account-tab">
      <h2 className="tab-title">{t('account.title')}</h2>

      <div className="account-stats">
        <div className="stat-card stat-balance">
          <div className="stat-icon"><DollarSign size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.balance')}</span>
            <span className="stat-value">{formatMoney(displayBalance)} $</span>
          </div>
        </div>
        <div className="stat-card stat-income">
          <div className="stat-icon"><TrendingUp size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.earned')}</span>
            <span className="stat-value">+{formatMoney(analytics.income)} $</span>
          </div>
        </div>
        <div className="stat-card stat-expense">
          <div className="stat-icon"><TrendingDown size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.spent')}</span>
            <span className="stat-value">-{formatMoney(analytics.expense)} $</span>
          </div>
        </div>
        <div className={`stat-card ${netPositive ? 'stat-income' : 'stat-expense'}`}>
          <div className="stat-icon"><Activity size={24} className="icon" /></div>
          <div className="stat-info">
            <span className="stat-label">{t('account.netChange')}</span>
            <span className="stat-value">
              {netPositive ? '+' : '−'}{formatMoney(Math.abs(analytics.net))} $
            </span>
            <span className="stat-sub">{t('account.operations')}: {analytics.operations}</span>
          </div>
        </div>
      </div>

      <div className="account-chart">
        <h3>{t('account.weeklyAnalytics')}</h3>
        {error && (
          <div className="error-state">
            <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
            <p>{t('common.error')}: {error}</p>
          </div>
        )}
        {loading && <div className="chart-container skeleton-chart" />}
        {!loading && !error && (
          <>
            <div className="chart-container">
              {days.map((d, i) => (
                <div key={d.date || i} className="chart-bar-group">
                  <div className="chart-bars">
                    <div
                      className="chart-bar bar-income"
                      style={{ height: `${(d.income / maxVal) * 100}%` }}
                      title={`${t('account.incomeLabel')}: ${formatMoney(d.income)} $`}
                    />
                    <div
                      className="chart-bar bar-expense"
                      style={{ height: `${(d.expense / maxVal) * 100}%` }}
                      title={`${t('account.expenseLabel')}: ${formatMoney(d.expense)} $`}
                    />
                  </div>
                  <span className="chart-label">{t(`common.${WEEKDAY_KEYS[d.weekday] || 'dayMon'}`)}</span>
                </div>
              ))}
            </div>
            <div className="chart-legend">
              <span className="legend-item legend-income">{t('account.income')}</span>
              <span className="legend-item legend-expense">{t('account.expense')}</span>
            </div>
          </>
        )}
      </div>

      <div className="account-transactions">
        <h3>{t('account.recentTransactions')}</h3>
        <TransactionsPanel />
      </div>
    </div>
  )
}

export default AccountTab
