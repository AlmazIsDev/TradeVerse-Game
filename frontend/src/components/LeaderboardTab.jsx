import { useTranslation } from 'react-i18next'
import { fetchLeaderboard } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { Trophy, AlertTriangle, Crown, Medal } from 'lucide-react'

const formatMoney = (n) =>
  (Number(n) || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function RankBadge({ rank }) {
  if (rank === 1) return <span className="rank-badge rank-gold"><Crown size={16} /></span>
  if (rank === 2) return <span className="rank-badge rank-silver"><Medal size={16} /></span>
  if (rank === 3) return <span className="rank-badge rank-bronze"><Medal size={16} /></span>
  return <span className="rank-badge">{rank}</span>
}

function LeaderboardTab({ currentUserId }) {
  const { t } = useTranslation()
  const { data: entries, loading, error } = useApiOnMount(() => fetchLeaderboard(20))

  if (loading) {
    return (
      <div className="leaderboard-tab">
        <h2 className="tab-title">{t('nav.leaderboard')}</h2>
        <div className="loading-state">
          <div className="spinner" />
          <p>{t('common.loading')}</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="leaderboard-tab">
        <h2 className="tab-title">{t('nav.leaderboard')}</h2>
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      </div>
    )
  }

  if (!entries || entries.length === 0) {
    return (
      <div className="leaderboard-tab">
        <h2 className="tab-title">{t('nav.leaderboard')}</h2>
        <div className="empty-state">
          <p>{t('leaderboard.noData')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="leaderboard-tab">
      <div className="leaderboard-title-row">
        <Trophy size={22} className="icon" />
        <h2 className="tab-title">{t('nav.leaderboard')}</h2>
      </div>

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
                <span className="lb-avatar">{(entry.username || '?').slice(0, 2).toUpperCase()}</span>
                <span className="lb-name">
                  {entry.username}
                  {isMe && <span className="lb-you">{t('leaderboard.you')}</span>}
                </span>
              </span>
              <span className="lb-networth">${formatMoney(entry.netWorth)}</span>
              <span className={`lb-profit ${up ? 'up' : 'down'}`}>
                {up ? '+' : ''}{formatMoney(entry.profit)} $
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default LeaderboardTab
