import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  MousePointerClick,
  Zap,
  ArrowUpCircle,
  Trophy,
  RefreshCw,
  Coins,
  X,
  ShoppingBag,
  HelpCircle
} from 'lucide-react'
import { toast } from './Toast'
import PlayerProfileModal from './PlayerProfileModal'
import {
  fetchClicker,
  clickClicker,
  upgradeClicker,
  buyClickerMultiplier,
  fetchClickerLeaderboard,
  fetchClickerCases,
  openClickerCase,
  fetchClickerComponentCases
} from '../services/api'
import './ClickerTab.css'

function rewardLabel(reward) {
  if (!reward) return ''
  if (reward.type === 'crypto') return `${reward.title} (${reward.symbol}) - ${reward.amount}`
  if (reward.amount) return `${reward.title} - ${reward.amount}`
  return reward.title
}

export default function ClickerTab({ balance, onBalanceChange }) {
  const { t } = useTranslation()

  // States
  const [data, setData] = useState(null)
  const [leaders, setLeaders] = useState([])
  const [cases, setCases] = useState([])
  const [componentCases, setComponentCases] = useState([])
  const [caseShopOpen, setCaseShopOpen] = useState(false)
  const [oddsCase, setOddsCase] = useState(null)
  const [profileId, setProfileId] = useState(null)
  const [loadingError, setLoadingError] = useState('')
  const [caseBusy, setCaseBusy] = useState(null)
  const [reward, setReward] = useState(null)

  // Load all clicker data
  const load = useCallback(async () => {
    try {
      const [d, l, c, cc] = await Promise.all([
        fetchClicker(),
        fetchClickerLeaderboard(),
        fetchClickerCases(),
        fetchClickerComponentCases()
      ])
      setData(d)
      setLeaders(l || [])
      setCases(c || [])
      setComponentCases(cc || [])
      setLoadingError('')
    } catch (e) {
      setLoadingError(e.message || t('common.error'))
    }
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  // Click handler
  const click = useCallback(async () => {
    try {
      const result = await clickClicker()
      setData(result)
      if (result.balance !== undefined && onBalanceChange) {
        onBalanceChange(result.balance)
      }
    } catch (e) {
      toast(e.message || t('common.error'), 'error')
    }
  }, [onBalanceChange, t])

  // Upgrade handler
  const upgrade = useCallback(async (id) => {
    if (!id) return
    try {
      const result = await upgradeClicker(id)
      setData(result)
      if (result.balance !== undefined && onBalanceChange) {
        onBalanceChange(result.balance)
      }
    } catch (e) {
      toast(e.message || t('common.error'), 'error')
    }
  }, [onBalanceChange, t])

  // Buy multiplier handler
  const buyMultiplier = useCallback(async () => {
    try {
      const result = await buyClickerMultiplier()
      setData(result)
      if (result.balance !== undefined && onBalanceChange) {
        onBalanceChange(result.balance)
      }
    } catch (e) {
      toast(e.message || t('common.error'), 'error')
    }
  }, [onBalanceChange, t])

  // Open case handler
  const openCase = useCallback(async (item) => {
    if (caseBusy || !item?.id) return

    setCaseShopOpen(true)
    setCaseBusy(item.id)
    setReward(null)

    try {
      const result = await openClickerCase(item.id)
      setData(result)

      const winner = rewardLabel(result.reward) || item.name
      setReward(result.reward)
      toast(`${t('clicker.win')}: ${winner}`, 'success')
      setCaseBusy(null)
    } catch (e) {
      setRoulette(null)
      setCaseBusy(null)
      toast(e.message || t('common.error'), 'error')
    }
  }, [caseBusy, t])

  // The result is already confirmed by the server, so the modal must always
  // be closable. Closing only hides the animation; it does not roll back the reward.
  const closeRoulette = useCallback(() => {
    setRoulette(null)
    setReward(null)
    setCaseBusy(null)
    setCaseShopOpen(false)
  }, [])

  // Close odds modal handler
  const closeOddsModal = useCallback(() => {
    setOddsCase(null)
  }, [])

  // Close profile modal handler
  const closeProfileModal = useCallback(() => {
    setProfileId(null)
  }, [])

  // Loading state
  if (!data) {
    return (
      <div className="clicker-page">
        <p>{loadingError || t('common.loading')}</p>
      </div>
    )
  }

  const allCases = [...(cases || []), ...(componentCases || [])]

  // Case card component
  const CaseCard = ({ item }) => (
    <article className="clicker-case-card" key={item.id}>
      <div className="clicker-case-icon">🎁</div>
      <h4>{item.name || t('clicker.case')}</h4>
      <div className="clicker-case-actions">
        <button
          className="clicker-odds-button"
          onClick={() => setOddsCase(item)}
          aria-label={t('clicker.viewOdds')}
        >
          <HelpCircle size={15} />
        </button>
        <button
          onClick={() => openCase(item)}
          disabled={Boolean(caseBusy) || (data.clicks || 0) < (item.price || 0)}
        >
          {caseBusy === item.id ? t('clicker.opening') : `${Number(item.price || 0).toLocaleString()} CLICKS`}
        </button>
      </div>
    </article>
  )

  // Safe value display
  const safeValue = (value, defaultValue = 0) => {
    const num = Number(value || defaultValue)
    return isNaN(num) ? defaultValue : num
  }

  return (
    <div className="clicker-page">
      {/* Header */}
      <div className="leaderboard-title-row">
        <MousePointerClick size={22} className="icon" />
        <h2 className="tab-title">{t('clicker.title')}</h2>
      </div>

      <p className="clicker-subtitle">{t('clicker.subtitle')}</p>

      <div className="clicker-layout">
        <main>
          {/* Token Card */}
          <div className="clicker-token-card">
            <div>
              <span className="clicker-token-label">
                <Coins size={17} /> {t('clicker.token')}
              </span>
              <strong>{safeValue(data.clicks).toLocaleString()} CLICKS</strong>
            </div>
            <div className="clicker-price">
              <span>{t('clicker.price')}</span>
              <b>${safeValue(data.clicksPrice)}</b>
            </div>
          </div>

          {/* Stats */}
          <div className="clicker-stats">
            <div>
              <span>{t('clicker.clickPower')}</span>
              <strong>x{safeValue(data.clickPower)}</strong>
            </div>
            <div>
              <span>{t('clicker.passive')}</span>
              <strong>+{safeValue(data.passiveIncome)}/s</strong>
            </div>
            <div>
              <span>{t('clicker.balance')}</span>
              <strong>${safeValue(balance).toLocaleString()}</strong>
            </div>
          </div>

          {/* Main Click Button */}
          <button className="clicker-main-button" onClick={click}>
            <MousePointerClick size={38} />
            <b>{t('clicker.click')}</b>
          </button>

          {/* Case Shop Button */}
          <button
            className="clicker-case-shop-button"
            onClick={() => setCaseShopOpen(true)}
          >
            <ShoppingBag size={18} /> {t('clicker.openCaseShop')}
          </button>

          {/* Multiplier Panel */}
          <div className="clicker-panel">
            <div className="clicker-multiplier-row">
              <div>
                <h3>
                  <Zap size={18} /> {t('clicker.multiplier')}
                </h3>
                <p>{t('clicker.multiplierHint', { power: safeValue(data.clickPower) })}</p>
              </div>
              <button
                onClick={buyMultiplier}
                disabled={safeValue(balance) < safeValue(data.multiplierCost)}
              >
                <ArrowUpCircle size={17} /> ${safeValue(data.multiplierCost).toLocaleString()}
              </button>
            </div>
          </div>

          {/* Upgrades */}
          <div className="clicker-upgrades">
            <h3>
              <Zap size={18} /> {t('clicker.upgrades')}
            </h3>
            {data.upgrades && typeof data.upgrades === 'object' && (
              Object.entries(data.upgrades).map(([id, item]) => (
                <div className="clicker-upgrade" key={id}>
                  <div>
                    <b>{item.name || t('clicker.upgrade')}</b>
                    <span>
                      {item.description || ''}
                      {item.income !== undefined && ` · +${safeValue(item.income)}/s`}
                      {item.level !== undefined && ` · ${t('clicker.level')} ${safeValue(item.level)}`}
                    </span>
                  </div>
                  <button
                    onClick={() => upgrade(id)}
                    disabled={(data.clicks || 0) < safeValue(item.cost)}
                  >
                    <ArrowUpCircle size={16} /> {safeValue(item.cost).toLocaleString()}
                  </button>
                </div>
              ))
            )}
          </div>
        </main>

        {/* Leaderboard */}
        <aside className="clicker-leaderboard">
          <h3>
            <Trophy size={18} /> {t('clicker.leaderboard')}
            <button onClick={load}>
              <RefreshCw size={14} />
            </button>
          </h3>
          {Array.isArray(leaders) && leaders.length > 0 ? (
            leaders.map((row, i) => (
              <div className="clicker-rank" key={row.userId || row.username || i}>
                <b>#{i + 1}</b>
                <span>{row.username || t('common.anonymous')}</span>
                <strong>{safeValue(row.clicks).toLocaleString()}</strong>
              </div>
            ))
          ) : (
            <p className="clicker-no-leaders">{t('clicker.noLeaders')}</p>
          )}
        </aside>
      </div>

      {/* Case Shop Modal */}
      {caseShopOpen && (
        <div
          className="clicker-shop-overlay"
          onClick={() => setCaseShopOpen(false)}
        >
          <div className="clicker-case-modal" onClick={(e) => e.stopPropagation()}>
            <button
              className="clicker-modal-close"
              onClick={closeRoulette}
              aria-label={t('common.close')}
            >
              <X size={18} />
            </button>
            <h2>
              <ShoppingBag size={20} /> {t('clicker.caseShop')}
            </h2>
            <p>{t('clicker.caseShopHint')}</p>
            <div className="clicker-cases">
              {allCases.map((item) => (
                <CaseCard key={item.id} item={item} />
              ))}
            </div>

          </div>
        </div>
      )}

      {/* Odds Modal */}
      {oddsCase && (
        <div className="clicker-shop-overlay" onClick={closeOddsModal}>
          <div className="clicker-odds-modal" onClick={(e) => e.stopPropagation()}>
            <button className="clicker-modal-close" onClick={closeOddsModal}>
              <X size={18} />
            </button>
            <h2>{t('clicker.oddsTitle')}</h2>
            {Array.isArray(oddsCase.odds) && oddsCase.odds.length > 0 ? (
              oddsCase.odds.map((odd, i) => (
                <div className="clicker-odds-row" key={i}>
                  <span>{odd.name || odd.type || t('common.unknown')}</span>
                  <strong>{safeValue(odd.chance)}%</strong>
                </div>
              ))
            ) : (
              <p>{t('clicker.noOddsData')}</p>
            )}
          </div>
        </div>
      )}

      {/* Profile Modal */}
      {profileId && (
        <PlayerProfileModal userId={profileId} onClose={closeProfileModal} />
      )}
    </div>
  )
}
