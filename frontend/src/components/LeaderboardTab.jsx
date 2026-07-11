import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchLeaderboard } from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import { Trophy, AlertTriangle, Crown, Medal } from 'lucide-react'

const SORTS = ['networth', 'profit', 'cash', 'stocks', 'crypto']

function RankBadge({ rank }) {
  if (rank === 1) return <span className="rank-badge rank-gold"><Crown size={16} /></span>
  if (rank === 2) return <span className="rank-badge rank-silver"><Medal size={16} /></span>
  if (rank === 3) return <span className="rank-badge rank-bronze"><Medal size={16} /></span>
  return <span className="rank-badge">{rank}</span>
}

function LeaderboardTab({ currentUserId }) {
  const { t } = useTranslation()
  const [entries, setEntries] = useState([])
  const [sort, setSort] = useState('networth')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await fetchLeaderboard(20, sort)
      setEntries(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [sort])

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
        <div className="empty-state"><p>{t('leaderboard.noData')}</p></div>
      )}

      {!loading && !error && entries.length > 0 && (
        <div className="leaderboard-table">
          <div className="leaderboard-row leaderboard-head">
            <span className="lb-rank">#</span>
            <span className="lb-player">{t('leaderboard.player')}</span>
            <span className="lb-networth">{t('leaderboard.netWorth')}</span>
            <span className="lb-profit">{t('leaderboard.profit')}</span>
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
                  <span className="lb-name">
                    {entry.username}
                    {isMe && <span className="lb-you">{t('leaderboard.you')}</span>}
                  </span>
                </span>
                <span className="lb-networth" title={`$${formatMoney(entry.netWorth)}`}>${formatCompact(entry.netWorth)}</span>
                <span className={`lb-profit ${up ? 'up' : 'down'}`} title={`${formatMoney(entry.profit)} $`}>
                  {up ? '+' : '−'}{formatCompact(Math.abs(entry.profit))} $
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default LeaderboardTab
