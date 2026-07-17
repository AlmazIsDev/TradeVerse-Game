import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchLeaderboard, fetchCompanyLeaderboard } from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import { Trophy, AlertTriangle, Crown, Medal, Building2 } from 'lucide-react'

const SORTS = ['networth', 'profit', 'cash', 'stocks', 'crypto', 'assets', 'company']
// Разбивка капитала под именем игрока — какие поля показывать чипами и какой
// sort их подсвечивает (чтобы было очевидно, что делает каждый фильтр).
const BREAKDOWN = [
  { key: 'cash', sort: 'cash' },
  { key: 'stocks', sort: 'stocks' },
  { key: 'crypto', sort: 'crypto' },
  { key: 'assets', sort: 'assets' },
  { key: 'company', sort: 'company' },
]

function RankBadge({ rank }) {
  if (rank === 1) return <span className="rank-badge rank-gold"><Crown size={16} /></span>
  if (rank === 2) return <span className="rank-badge rank-silver"><Medal size={16} /></span>
  if (rank === 3) return <span className="rank-badge rank-bronze"><Medal size={16} /></span>
  return <span className="rank-badge">{rank}</span>
}

function LeaderboardTab({ currentUserId }) {
  const { t } = useTranslation()
  const [mode, setMode] = useState('players')   // players | companies
  const [entries, setEntries] = useState([])
  const [sort, setSort] = useState('networth')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = mode === 'companies'
        ? await fetchCompanyLeaderboard(20)
        : await fetchLeaderboard(20, sort)
      setEntries(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [sort, mode])

  useEffect(() => { load() }, [load])

  // Периодический сигнал от scheduler'а (см. backend/scheduler.py) — не сами
  // данные (расчёт капитала всех игроков тяжёлый), а лёгкий триггер перечитать
  // уже закэшированный на бэкенде GET /api/leaderboard.
  useEffect(() => {
    const onRealtime = (ev) => {
      if (ev.detail?.type === 'leaderboard_update') load(true)
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [load])

  return (
    <div className="leaderboard-tab">
      <div className="leaderboard-title-row">
        <Trophy size={22} className="icon" />
        <h2 className="tab-title">{t('nav.leaderboard')}</h2>
      </div>

      <div className="leaderboard-modes">
        {['players', 'companies'].map(m => (
          <button
            key={m}
            className={`tx-pill ${mode === m ? 'active' : ''}`}
            onClick={() => setMode(m)}
          >
            {m === 'companies' ? <Building2 size={14} /> : <Trophy size={14} />} {t(`leaderboard.mode${m === 'companies' ? 'Companies' : 'Players'}`)}
          </button>
        ))}
      </div>

      {mode === 'players' && (
        <div className="leaderboard-sorts">
          {SORTS.map(s => (
            <button
              key={s}
              className={`tx-pill ${sort === s ? 'active' : ''}`}
              onClick={() => setSort(s)}
            >
              {t(`leaderboard.sort_${s}`)}
            </button>
          ))}
        </div>
      )}

      {loading && (
        <div className="leaderboard-table">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="leaderboard-row skeleton" style={{ height: 56 }} />
          ))}
        </div>
      )}

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div className="empty-state"><p>{t(mode === 'companies' ? 'leaderboard.noCompanies' : 'leaderboard.noData')}</p></div>
      )}

      {!loading && !error && entries.length > 0 && mode === 'players' && (
        <div className="leaderboard-table">
          <div className="leaderboard-row leaderboard-head">
            <span className="lb-rank">#</span>
            <span className="lb-player">{t('leaderboard.player')}</span>
            <span className="lb-networth">{t('leaderboard.netWorth')}</span>
            <span className="lb-profit">{t('leaderboard.profit7d')}</span>
          </div>
          {entries.map(entry => {
            const isMe = currentUserId && entry.userId === currentUserId
            const up = entry.profit >= 0
            return (
              <div
                key={entry.userId}
                className={`leaderboard-row ${isMe ? 'leaderboard-me' : ''} ${entry.rank <= 3 ? 'leaderboard-top' : ''}`}
              >
                <span className="lb-rank"><RankBadge rank={entry.rank} /></span>
                <span className="lb-player">
                  {entry.avatar ? (
                    <img className="lb-avatar lb-avatar-img" src={entry.avatar} alt={entry.username} />
                  ) : (
                    <span className="lb-avatar">{(entry.username || '?').slice(0, 2).toUpperCase()}</span>
                  )}
                  <span style={{ minWidth: 0 }}>
                    <span className="lb-name">
                      {entry.username}
                      {isMe && <span className="lb-you">{t('leaderboard.you')}</span>}
                    </span>
                    <span className="lb-breakdown">
                      {BREAKDOWN.map(b => (
                        <span key={b.key} className={`lb-chip ${sort === b.sort ? 'active' : ''}`} title={`$${formatMoney(entry[b.key] || 0)}`}>
                          {t(`leaderboard.col_${b.key}`)} <b>${formatCompact(entry[b.key] || 0)}</b>
                        </span>
                      ))}
                    </span>
                  </span>
                </span>
                <span className="lb-networth" title={`$${formatMoney(entry.netWorth)}`}>${formatCompact(entry.netWorth)}</span>
                <span className={`lb-profit ${up ? 'up' : 'down'}`} title={`${t('leaderboard.profitLifetime')}: ${formatMoney(entry.profitAllTime)} $`}>
                  {up ? '+' : '−'}{formatCompact(Math.abs(entry.profit))} $
                  {entry.profitAllTime != null && (
                    <span className="lb-profit-sub">{t('leaderboard.profitLifetime')}: {entry.profitAllTime >= 0 ? '+' : '−'}{formatCompact(Math.abs(entry.profitAllTime))} $</span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {!loading && !error && entries.length > 0 && mode === 'companies' && (
        <div className="leaderboard-table">
          <div className="leaderboard-row leaderboard-head">
            <span className="lb-rank">#</span>
            <span className="lb-player">{t('leaderboard.company')}</span>
            <span className="lb-networth">{t('leaderboard.value')}</span>
            <span className="lb-profit">{t('leaderboard.assets')}</span>
          </div>
          {entries.map(entry => (
            <div
              key={entry.companyId}
              className={`leaderboard-row ${entry.rank <= 3 ? 'leaderboard-top' : ''}`}
            >
              <span className="lb-rank"><RankBadge rank={entry.rank} /></span>
              <span className="lb-player">
                {entry.logo ? (
                  <img className="lb-avatar lb-avatar-img lb-logo" src={entry.logo} alt={entry.name} />
                ) : (
                  <span className="lb-avatar lb-logo"><Building2 size={16} /></span>
                )}
                <span style={{ minWidth: 0 }}>
                  <span className="lb-name">{entry.name}</span>
                  <span className="lb-breakdown">
                    <span className="lb-chip" title={`$${formatMoney(entry.budget || 0)}`}>{t('leaderboard.budget')} <b>${formatCompact(entry.budget || 0)}</b></span>
                    <span className="lb-chip" title={`$${formatMoney(entry.assets || 0)}`}>{t('leaderboard.assets')} <b>${formatCompact(entry.assets || 0)}</b></span>
                  </span>
                </span>
              </span>
              <span className="lb-networth" title={`$${formatMoney(entry.value)}`}>${formatCompact(entry.value)}</span>
              <span className="lb-profit" title={`$${formatMoney(entry.assets || 0)}`}>${formatCompact(entry.assets || 0)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default LeaderboardTab
