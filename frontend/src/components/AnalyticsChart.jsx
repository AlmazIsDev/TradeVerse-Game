import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { formatMoney } from './TransactionsPanel'

const WD = ['dayMon', 'dayTue', 'dayWed', 'dayThu', 'dayFri', 'daySat', 'daySun']

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

/**
 * Единый график аналитики (доход/расход по дням) с красивыми CSS-подсказками.
 * Используется в Аккаунте и Банке — единый стиль во всём проекте.
 * props: days: [{ date, weekday, income, expense }]
 */
function AnalyticsChart({ days = [] }) {
  const { t } = useTranslation()
  const [hover, setHover] = useState(null)
  const maxVal = Math.max(1, ...days.map(d => Math.max(d.income || 0, d.expense || 0)))

  const netOf = (d) => (d.income || 0) - (d.expense || 0)

  return (
    <div className="analytics-chart">
      <div className="ac-plot">
        {days.map((d, i) => {
          const net = netOf(d)
          const prevNet = i > 0 ? netOf(days[i - 1]) : null
          const delta = prevNet != null ? net - prevNet : null
          const active = hover === i
          return (
            <div
              key={d.date || i}
              className={`ac-col ${active ? 'active' : ''}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(h => (h === i ? null : h))}
            >
              {active && (
                <div className="ac-tooltip" role="tooltip">
                  <div className="ac-tt-date">{fmtDate(d.date)}</div>
                  <div className="ac-tt-row"><span className="ac-dot income" />{t('account.income')}<b className="up">+{formatMoney(d.income)} $</b></div>
                  <div className="ac-tt-row"><span className="ac-dot expense" />{t('account.expense')}<b className="down">−{formatMoney(d.expense)} $</b></div>
                  <div className="ac-tt-row"><span className="ac-dot net" />{t('account.netChange')}<b className={net >= 0 ? 'up' : 'down'}>{net >= 0 ? '+' : '−'}{formatMoney(Math.abs(net))} $</b></div>
                  {delta != null && (
                    <div className="ac-tt-delta">
                      {delta >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                      <span className={delta >= 0 ? 'up' : 'down'}>
                        {delta >= 0 ? '+' : '−'}{formatMoney(Math.abs(delta))} $ {t('account.vsPrevDay')}
                      </span>
                    </div>
                  )}
                </div>
              )}
              <div className="ac-bars">
                <div className="ac-bar income" style={{ height: `${((d.income || 0) / maxVal) * 100}%` }} />
                <div className="ac-bar expense" style={{ height: `${((d.expense || 0) / maxVal) * 100}%` }} />
              </div>
              <span className="ac-label">{t(`common.${WD[d.weekday] ?? 'dayMon'}`)}</span>
            </div>
          )
        })}
      </div>
      <div className="ac-legend">
        <span className="ac-legend-item"><span className="ac-dot income" /> {t('account.income')}</span>
        <span className="ac-legend-item"><span className="ac-dot expense" /> {t('account.expense')}</span>
      </div>
    </div>
  )
}

export default AnalyticsChart
