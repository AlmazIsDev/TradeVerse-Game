import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchWeeklyAnalytics, fetchActiveWorldEvents } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import AnalyticsChart from './AnalyticsChart'
import {
  TrendingUp, TrendingDown, DollarSign, Activity, AlertTriangle,
} from 'lucide-react'

const PERIODS = ['today', 'yesterday', 'week', 'month', 'all']

function AccountTab({ balance = 0 }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState('week')
  const { data, loading, error } = useApiOnMount(() => fetchWeeklyAnalytics(period), [period])
  const { data: eventsData } = useApiOnMount(() => fetchActiveWorldEvents(), [])

  const analytics = data || { income: 0, expense: 0, net: 0, operations: 0, days: [] }
  const displayBalance = data?.balance != null ? data.balance : balance
  const days = analytics.days || []
  const netPositive = analytics.net >= 0
  const worldEvents = eventsData?.active || []

  return (
    <div className="account-tab">
      <h2 className="tab-title">{t('account.title')}</h2>

      {worldEvents.length > 0 && (
        <div className="world-events">
          {worldEvents.map(ev => (
            <div key={ev.id} className="world-event" title={ev.desc || ''}>
              <span className="world-event-icon">{ev.icon}</span>
              <div className="world-event-info">
                <b>{ev.name}</b>
                {ev.desc && <span>{ev.desc}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="account-period">
        {PERIODS.map(p => (
          <button
            key={p}
            className={`tx-pill ${period === p ? 'active' : ''}`}
            onClick={() => setPeriod(p)}
          >
            {t(`account.period.${p}`)}
          </button>
        ))}
      </div>

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
        {!loading && !error && <AnalyticsChart days={days} />}
      </div>

      <div className="account-transactions">
        <h3>{t('account.recentTransactions')}</h3>
        <TransactionsPanel />
      </div>
    </div>
  )
}

export default AccountTab
