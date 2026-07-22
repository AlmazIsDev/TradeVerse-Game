import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchPlayerProfile } from '../services/api'
import { X, Award, Check, BarChart3 } from 'lucide-react'

/**
 * Публичная карточка игрока (в стиле Telegram): аватар, никнейм, «о себе»,
 * капитал и ачивки. Данные — из GET /api/user/{id}/profile (те же цифры, что
 * в таблице лидеров). Открывается кликом по нику в составе компании, таблице
 * лидеров и «Крыше города».
 */
function PlayerProfileModal({ userId, onClose }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fetchPlayerProfile(userId)
      .then(res => { if (alive) setData(res) })
      .catch(err => { if (alive) setError(err.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [userId])

  const initials = (data?.username || '?').slice(0, 2).toUpperCase()
  const stats = data?.stats || {}
  const money = (v) => `$${Number(v || 0).toLocaleString('ru-RU', { maximumFractionDigits: 0 })}`

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content player-profile-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>

        {loading ? (
          <div className="pp-loading">{t('common.loading', 'Загрузка…')}</div>
        ) : error ? (
          <div className="pp-error">{error}</div>
        ) : (
          <>
            <div className="pp-head">
              <div className="pp-avatar">
                {data.avatar ? <img src={data.avatar} alt={data.username} /> : <span>{initials}</span>}
              </div>
              <h3 className="pp-name">{data.username}</h3>
              {data.bio && <p className="pp-bio">{data.bio}</p>}
            </div>

            <div className="pp-section">
              <div className="pp-section-title"><BarChart3 size={15} /> {t('settings.statsTitle')}</div>
              <div className="pp-stats-grid">
                {[
                  ['netWorth', stats.netWorth],
                  ['cash', stats.cash],
                  ['stocks', stats.stocks],
                  ['crypto', stats.crypto],
                  ['assets', stats.assets],
                  ['company', stats.company],
                  ['warcoin', stats.warcoin],
                  ['profit', stats.profit],
                ].map(([key, val]) => (
                  <div className="pp-stat" key={key}>
                    <span className="pp-stat-label">{t(`settings.stat.${key}`)}</span>
                    <span className={`pp-stat-value ${key === 'profit' && (val || 0) < 0 ? 'neg' : ''}`}>{money(val)}</span>
                  </div>
                ))}
              </div>
            </div>

            {(data.achievements || []).length > 0 && (
              <div className="pp-section">
                <div className="pp-section-title"><Award size={15} /> {t('settings.achievementsTitle')}</div>
                <div className="pp-achievements">
                  {data.achievements.map(a => (
                    <div className={`pp-achievement ${a.reached ? 'reached' : ''}`} key={a.id}>
                      <Award size={14} />
                      <span>{t(`settings.achievement.${a.id}`)}</span>
                      {a.reached && <Check size={13} className="pp-achievement-check" />}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default PlayerProfileModal
