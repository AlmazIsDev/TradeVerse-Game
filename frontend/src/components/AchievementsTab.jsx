import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Award, Lock } from 'lucide-react'
import { getUserAchievements } from '../services/api'

function AchievementsTab() {
  const { t } = useTranslation()
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getUserAchievements()
      .then((data) => { if (!cancelled) setItems(data.achievements || []) })
      .catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [])

  const unlockedCount = items ? items.filter((a) => a.unlocked).length : 0

  return (
    <div className="achievements-tab">
      <div className="leaderboard-title-row">
        <Award size={22} className="icon" />
        <h2 className="tab-title">{t('achievements.title', 'Достижения')}</h2>
      </div>

      {error && <div className="error-state"><p>{error}</p></div>}

      {items && (
        <>
          <p className="settings-hint">{t('achievements.received', 'Получено: {{unlocked}} из {{total}}', { unlocked: unlockedCount, total: items.length })}</p>
          <div className="achievements-grid">
            {items.map((a) => (
              <div
                key={a.id}
                className={`achievement-card rarity-${a.rarity} ${a.unlocked ? 'unlocked' : 'locked'}`}
              >
                <div className="achievement-icon">
                  {a.unlocked ? <Award size={22} /> : <Lock size={22} />}
                </div>
                <div className="achievement-info">
                  <div className="achievement-rarity">{t(`achievementCatalog.rarity.${a.rarity}`, a.rarityName)}</div>
                  <div className="achievement-name">{t(`achievementCatalog.items.${a.id}.name`, a.name)}</div>
                  <div className="achievement-desc">{t(`achievementCatalog.items.${a.id}.desc`, a.desc)}</div>
                  {a.unlocked && a.unlockedAt && (
                    <div className="achievement-date">{new Date(a.unlockedAt).toLocaleDateString('ru-RU')}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default AchievementsTab
