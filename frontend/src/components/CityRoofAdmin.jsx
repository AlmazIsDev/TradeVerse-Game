import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { adminFetchCityRooms } from '../services/api'
import { formatCompact, formatMoney } from './TransactionsPanel'
import { toast } from './Toast'
import { RefreshCw, Castle, Coins, Lock } from 'lucide-react'

// Все комнаты «Крыши города»: игроку они недоступны, поэтому просмотр чужих
// комнат живёт только здесь. Данные — /api/cityroof/admin/rooms.
function CityRoofAdmin() {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [openRoom, setOpenRoom] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await adminFetchCityRooms())
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const rooms = data?.rooms || []
  const totalWarcoin = rooms.reduce((s, r) => s + (r.warcoinTotal || 0), 0)
  const totalCaptured = rooms.reduce((s, r) => s + (r.capturedBusinesses || 0), 0)
  const totalPlayers = rooms.reduce((s, r) => s + (r.memberCount || 0), 0)

  return (
    <div className="cityroof-admin">
      <div className="admin-section-head">
        <h3>{t('admin.cityroof.title')}</h3>
        <button className="asset-act" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> {t('admin.cityroof.refresh')}
        </button>
      </div>

      <div className="asset-summary">
        <div className="asset-summary-card">
          <span>{t('admin.cityroof.season')}</span>
          <b>{data?.season ?? '—'}</b>
          <small>{data?.week || ''}</small>
        </div>
        <div className="asset-summary-card">
          <span>{t('admin.cityroof.rooms')}</span>
          <b>{rooms.length}</b>
        </div>
        <div className="asset-summary-card">
          <span>{t('admin.cityroof.players')}</span>
          <b>{totalPlayers}</b>
        </div>
        <div className="asset-summary-card">
          <span><Coins size={12} /> {t('admin.cityroof.warcoin')}</span>
          <b>{formatCompact(totalWarcoin)}</b>
        </div>
        <div className="asset-summary-card">
          <span><Castle size={12} /> {t('admin.cityroof.captured')}</span>
          <b>{totalCaptured}</b>
        </div>
      </div>

      {loading && rooms.length === 0 && <p className="empty-state">{t('common.loading')}</p>}
      {!loading && rooms.length === 0 && <p className="empty-state">{t('admin.cityroof.empty')}</p>}

      <div className="cityroof-admin-rooms">
        {rooms.map(room => {
          const expanded = openRoom === room.roomCode
          return (
            <section key={room.roomCode} className="cityroom-card">
              <div
                className="cityroom-head"
                role="button"
                tabIndex={0}
                onClick={() => setOpenRoom(expanded ? null : room.roomCode)}
                onKeyDown={e => e.key === 'Enter' && setOpenRoom(expanded ? null : room.roomCode)}
              >
                <span className="cityroom-code">{room.roomCode}</span>
                <span className="cityroom-league">{t(`cityroof.leagues.${room.league}`, room.league)}</span>
              </div>
              <div className="cityroom-meta">
                {room.memberCount}/{room.capacity}
                {' · '}{t('cityroof.division')}&nbsp;{(room.capitalTier ?? 0) + 1}
                {' · '}{formatCompact(room.warcoinPrice)} $ / WC
              </div>
              <div className="cityroom-meta">
                <span className="cityroof-admin-stat">
                  <Coins size={11} /> {formatCompact(room.warcoinTotal)}
                </span>
                <span className="cityroof-admin-stat">
                  <Castle size={11} /> {room.capturedBusinesses}
                  <span className="cityroof-admin-free">
                    {' '}/ {t('admin.cityroof.free')} {room.freeBusinesses}
                  </span>
                </span>
              </div>

              {expanded && (room.members || []).length > 0 && (
                <div className="cityroof-admin-members">
                  <div className="cityroof-admin-row head">
                    <span>{t('admin.cityroof.player')}</span>
                    <span>{t('admin.cityroof.wcCol')}</span>
                    <span>{t('admin.cityroof.capturedCol')}</span>
                    <span>{t('admin.cityroof.capitalCol')}</span>
                    <span>{t('admin.cityroof.activityCol')}</span>
                  </div>
                  {room.members.map(m => (
                    <div key={m.id} className="cityroof-admin-row">
                      <span className="cityroof-admin-name">{m.name}</span>
                      <span title={formatMoney(m.warcoin)}>{formatCompact(m.warcoin)}</span>
                      <span className={m.businesses > 0 ? 'up' : ''}>{m.businesses}</span>
                      <span title={formatMoney(m.capital)}>{formatCompact(m.capital)}</span>
                      <span className={`cityroof-rank-activity a${m.activityTier}`}>
                        {t(`cityroof.activity.${m.activityLabel}`)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {expanded && (room.members || []).length === 0 && (
                <p className="empty-state">{t('cityroof.noPlayers')}</p>
              )}
            </section>
          )
        })}
      </div>

      <p className="cityroof-admin-note">
        <Lock size={12} /> {t('admin.cityroof.note')}
      </p>
    </div>
  )
}

export default CityRoofAdmin
