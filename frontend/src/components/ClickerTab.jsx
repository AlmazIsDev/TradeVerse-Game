import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MousePointerClick, Zap, ArrowUpCircle, Trophy, RefreshCw, Coins, X, ShoppingBag, HelpCircle } from 'lucide-react'
import { toast } from './Toast'
import PlayerProfileModal from './PlayerProfileModal'
import { fetchClicker, clickClicker, upgradeClicker, buyClickerMultiplier, fetchClickerLeaderboard, fetchClickerCases, openClickerCase, fetchClickerComponentCases } from '../services/api'
import './ClickerTab.css'

const FLUSH_MS = 100

function rewardLabel(reward) {
  if (!reward) return ''
  if (reward.type === 'crypto') return `${reward.title} (${reward.symbol}) · ${reward.amount}`
  if (reward.amount) return `${reward.title} · ${reward.amount}`
  return reward.title
}

export default function ClickerTab({ balance, onBalanceChange }) {
  const { t } = useTranslation()
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
  const pendingClicks = useRef(0)
  const flushTimer = useRef(null)
  const inFlight = useRef(false)
  const canvasRef = useRef(null)

  const load = useCallback(() => Promise.all([fetchClicker(), fetchClickerLeaderboard(), fetchClickerCases(), fetchClickerComponentCases()])
    .then(([clicker, leaderboard, regularCases, hardwareCases]) => {
      setData(clicker); setLeaders(leaderboard); setCases(regularCases); setComponentCases(hardwareCases)
    }).catch(error => setLoadingError(error.message)), [])

  useEffect(() => { load(); return undefined }, [load])

  useEffect(() => {
    const onRealtime = event => {
      if (event.detail?.type !== 'clicker_balance') return
      setData(previous => previous && { ...previous, clicks: event.detail.clicks, clickPower: event.detail.clickPower })
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const context = canvas.getContext('2d')
    const ratio = window.devicePixelRatio || 1
    const size = 230
    canvas.width = size * ratio
    canvas.height = size * ratio
    context.scale(ratio, ratio)
    const gradient = context.createRadialGradient(80, 50, 12, 115, 115, 120)
    gradient.addColorStop(0, '#3b82c4'); gradient.addColorStop(.52, '#123b72'); gradient.addColorStop(1, '#071426')
    context.fillStyle = gradient; context.beginPath(); context.arc(115, 115, 108, 0, Math.PI * 2); context.fill()
    context.strokeStyle = '#93c5fd'; context.lineWidth = 7; context.stroke()
    return undefined
  }, [data?.clickPower])

  const flushClicks = useCallback(async () => {
    if (inFlight.current || pendingClicks.current < 1) return
    const count = pendingClicks.current
    pendingClicks.current = 0
    inFlight.current = true
    try {
      setData(await clickClicker(count))
    } catch (error) {
      pendingClicks.current += count
      toast(error?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      inFlight.current = false
      if (pendingClicks.current > 0) flushTimer.current = setTimeout(flushClicks, FLUSH_MS)
    }
  }, [t])

  const registerClick = useCallback(() => {
    pendingClicks.current += 1
    if (!flushTimer.current) flushTimer.current = setTimeout(() => { flushTimer.current = null; flushClicks() }, FLUSH_MS)
  }, [flushClicks])

  useEffect(() => () => {
    if (flushTimer.current) clearTimeout(flushTimer.current)
    if (pendingClicks.current > 0) flushClicks()
  }, [flushClicks])

  const handleUpgrade = async id => {
    try { setData(await upgradeClicker(id)) } catch (error) { toast(error?.message || t('common.error', 'Ошибка'), 'error') }
  }

  const buyMultiplier = async () => {
    try {
      const result = await buyClickerMultiplier()
      setData(result); onBalanceChange?.(result.balance)
    } catch (error) { toast(error?.message || t('common.error', 'Ошибка'), 'error') }
  }

  const openCase = async item => {
    setCaseBusy(item.id); setReward(null)
    try {
      const result = await openClickerCase(item.id)
      setData(result); setReward(result.reward)
      toast(`${t('clicker.win')}: ${rewardLabel(result.reward) || item.name}`, 'success')
    } catch (error) { toast(error?.message || t('common.error', 'Ошибка'), 'error') }
    finally { setCaseBusy(null) }
  }

  if (!data) return <div className="clicker-page"><p>{loadingError || t('common.loading')}</p></div>

  const allCases = [...cases.map(item => ({ ...item, name: t(`clicker.cases.${item.id}`, item.name) })), ...componentCases]
  const caseCard = item => (
    <article className={`clicker-case-card ${item.tone || 'component'} ${caseBusy === item.id ? 'is-spinning' : ''}`} key={item.id}>
      <div className="clicker-case-icon">{item.icon || '🧩'}</div>
      <h4>{item.name}</h4>
      <div className="clicker-case-actions">
        <button className="clicker-odds-button" type="button" aria-label={t('clicker.odds')} onClick={() => setOddsCase(item)}><HelpCircle size={15} /></button>
        <button type="button" onClick={() => openCase(item)} disabled={caseBusy !== null || data.clicks < item.price}>{caseBusy === item.id ? t('clicker.opening') : `${Number(item.price).toLocaleString()} CLICKS`}</button>
      </div>
    </article>
  )

  return <div className="clicker-page">
    <div className="leaderboard-title-row"><MousePointerClick size={22} className="icon" /><h2 className="tab-title">{t('clicker.title')}</h2></div>
    <p className="clicker-subtitle">{t('clicker.subtitle')}</p>
    {loadingError && <div className="error-state">{loadingError}</div>}
    <div className="clicker-layout"><main>
      <div className="clicker-token-card"><div><span className="clicker-token-label"><Coins size={17} /> {t('clicker.token')}</span><strong>{data.clicks.toLocaleString()} CLICKS</strong><small>{t('clicker.tokenHint')}</small></div><div className="clicker-price"><span>{t('clicker.price')}</span><b>${data.clicksPrice}</b></div></div>
      <div className="clicker-stats"><div><span>{t('clicker.clickPower')}</span><strong>x{data.clickPower}</strong></div><div><span>{t('clicker.passive')}</span><strong>+{data.passiveIncome}/s</strong></div><div><span>{t('clicker.balance')}</span><strong>${Number(balance || 0).toLocaleString()}</strong></div></div>
      <canvas ref={canvasRef} className="clicker-main-button clicker-canvas" role="button" tabIndex="0" aria-label={t('clicker.click')} onPointerDown={registerClick} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); registerClick() } }} />
      <button className="clicker-case-shop-button" onClick={() => setCaseShopOpen(true)}><ShoppingBag size={18} /> {t('clicker.openCaseShop')}</button>
      <div className="clicker-panel"><div className="clicker-multiplier-row"><div><h3><Zap size={18} /> {t('clicker.multiplier')}</h3><p>{t('clicker.multiplierHint', { power: data.clickPower })}</p></div><button onClick={buyMultiplier} disabled={Number(balance || 0) < data.multiplierCost}><ArrowUpCircle size={17} /> ${data.multiplierCost.toLocaleString()}</button></div></div>
      <div className="clicker-upgrades"><h3><Zap size={18} /> {t('clicker.upgrades')}</h3>{Object.entries(data.upgrades).map(([id, item]) => <div className="clicker-upgrade" key={id}><div><b>{item.name}</b><span>{item.description} · +{item.income}/s · ур. {item.level}</span></div><button onClick={() => handleUpgrade(id)} disabled={data.clicks < item.cost}><ArrowUpCircle size={16} /> {item.cost}</button></div>)}</div>
    </main><aside className="clicker-leaderboard"><h3><Trophy size={18} /> {t('clicker.leaderboard')} <button onClick={load}><RefreshCw size={14} /></button></h3>{leaders.map((row, index) => <div className="clicker-rank" key={row.userId || row.username} role="button" tabIndex="0" onClick={() => row.userId && setProfileId(row.userId)} onKeyDown={event => { if ((event.key === 'Enter' || event.key === ' ') && row.userId) setProfileId(row.userId) }}><b>#{index + 1}</b>{row.avatar ? <img className="clicker-rank-avatar" src={row.avatar} alt="" /> : <span className="clicker-rank-avatar clicker-rank-initials">{row.username.slice(0, 2).toUpperCase()}</span>}<span>{row.username}</span><strong>{row.clicks.toLocaleString()}</strong></div>)}</aside></div>
    {caseShopOpen && <div className="clicker-shop-overlay" onClick={() => setCaseShopOpen(false)}><div className="clicker-case-modal" onClick={event => event.stopPropagation()}><button className="clicker-modal-close" onClick={() => setCaseShopOpen(false)}><X size={18} /></button><h2><ShoppingBag size={20} /> {t('clicker.caseShop')}</h2><p>{t('clicker.caseShopHint')}</p><div className="clicker-cases">{allCases.map(caseCard)}</div>{reward && <div className="clicker-reward"><span>🎉</span><b>{t('clicker.win')}</b><strong>{rewardLabel(reward)}</strong></div>}</div></div>}
    {oddsCase && <div className="clicker-shop-overlay" onClick={() => setOddsCase(null)}><div className="clicker-odds-modal" onClick={event => event.stopPropagation()}><button className="clicker-modal-close" onClick={() => setOddsCase(null)}><X size={18} /></button><h2>{t('clicker.oddsTitle')}</h2><h3>{oddsCase.name}</h3>{(oddsCase.odds || []).map(odd => <div className="clicker-odds-row" key={odd.type}><span>{odd.type === 'crypto' ? t('clicker.randomCrypto') : odd.type}</span><strong>{odd.chance}%</strong></div>)}</div></div>}
    {profileId && <PlayerProfileModal userId={profileId} onClose={() => setProfileId(null)} />}
  </div>
}
