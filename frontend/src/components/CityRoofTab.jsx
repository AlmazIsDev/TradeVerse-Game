import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCityMap, buyWarcoin, attackBusiness, guessCombination, protectBusiness,
  fetchCityBonuses, fetchItStudioJobs, fetchMyStudios, orderStudioJob, buyDualShield,
} from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import ConfirmDialog from './ConfirmDialog'
import ItStudioOrderModal from './ItStudioOrderModal'
import Tooltip from './Tooltip'
import PlayerProfileModal from './PlayerProfileModal'
import { toast } from './Toast'
import {
  Castle, Coins, Shield, Swords, X, Lock, PlusCircle,
  Gift, Zap, ShieldPlus, Clock, Trophy, DoorOpen, Users, Eye,
  DollarSign,
} from 'lucide-react'

function formatCountdown(sec) {
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}

// Таймер автосбора одного бонуса. Владеет собственным 1-секундным тиком, чтобы
// обратный отсчёт не заставлял перерисовываться всю вкладку (карта + все
// карточки) каждую секунду — ре-рендерится только этот маленький лист.
function BonusCountdown({ anchor, readyInSec }) {
  const { t } = useTranslation()
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const elapsed = (Date.now() - anchor) / 1000
  const remaining = Math.max(0, (readyInSec ?? 0) - elapsed)
  return (
    <span className="cbonus-timer">
      {remaining > 0 ? t('cityroof.nextIncome', { time: formatCountdown(remaining) }) : t('cityroof.incomeReady')}
    </span>
  )
}

// Эффекты-скидки показываются со знаком «-» (снижают стоимость), остальные — «+»
// (см. backend/cityroof.py BUSINESS_BONUS и player_city_effect). Подписи — в i18n
// (cityroof.effects.*), чтобы текст не оставался русским при английской локали.
const DISCOUNT_EFFECTS = new Set(['shop_discount', 'warcoin_discount', 'mining_energy'])

const PEG_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#6366f1', '#a855f7', '#ec4899', '#f5f5f5']

// Изображения зданий на карте (эмодзи вместо ассетов — работает без сети)
const BUILDING_EMOJI = {
  market: '🏬', bank: '🏦', casino: '🎰', port: '⚓', mall: '🛍️', factory: '🏭',
  stadium: '🏟️', airport: '✈️', hotel: '🏨', tower: '🏢', studio: '🎬', refinery: '🛢️',
}

// Названия зданий приходят с бэкенда по-русски (cityroof.py CITY_BUILDINGS);
// локализуем по стабильному slug, оставляя серверное имя запасным вариантом.
const buildingName = (t, slug, fallback) => t(`cityroof.buildings.${slug}`, fallback || slug)

function CityRoofTab({ balance = 0, onBalanceChange, currentUserId }) {
  const { t } = useTranslation()
  const [map, setMap] = useState(null)
  const [showHelp, setShowHelp] = useState(false)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)      // business
  const [profileId, setProfileId] = useState(null)
  const [session, setSession] = useState(null)        // { sessionId, length, symbolRange, ... }
  const [guess, setGuess] = useState([])
  const [attempts, setAttempts] = useState([])        // [{ guess, feedback, exact, present }]
  const [busy, setBusy] = useState(false)
  const [buyModal, setBuyModal] = useState(false)
  const [buyAmount, setBuyAmount] = useState('10')
  const [bonuses, setBonuses] = useState(null)
  const bonusAnchors = useRef({})     // slug -> момент (мс), от которого считаем локальный отсчёт readyInSec
  const [itStudioJobs, setItStudioJobs] = useState([])
  const [studios, setStudios] = useState([])          // собственные IT-студии игрока
  const [orderModal, setOrderModal] = useState(null)   // { mode, businessId }
  const [orderBusy, setOrderBusy] = useState(false)

  const [selectedRoom, setSelectedRoom] = useState(null)
  const [showRooms, setShowRooms] = useState(false)
  const [highlightedPlayer, setHighlightedPlayer] = useState(null)

  const load = useCallback(async (roomCode = null) => {
    try {
      const [data, b, jobs, myStudios] = await Promise.all([
        fetchCityMap({ allRooms: true, roomCode }), fetchCityBonuses().catch(() => null), fetchItStudioJobs().catch(() => []),
        fetchMyStudios().catch(() => []),
      ])
      setMap(data)
      setBonuses(b)
      setItStudioJobs(jobs)
      setStudios(myStudios)
      const now = Date.now()
      const anchors = {}
      for (const item of b?.bonuses || []) anchors[item.slug] = now
      bonusAnchors.current = anchors
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(selectedRoom) }, [load, selectedRoom])

  // Доход зачисляется автоматически на сервере (Scheduler). Периодически
  // подтягиваем актуальное состояние КД по каждому зданию. Посекундный отсчёт
  // живёт в <BonusCountdown> — отдельном листе, чтобы не ре-рендерить вкладку.
  useEffect(() => {
    const refresh = setInterval(load, 30000)
    return () => clearInterval(refresh)
  }, [load])

  // Живые обновления карты (захват/защита чужими игроками) и точечный сброс
  // таймера автосбора в момент реального зачисления — вместо ожидания
  // 30-сек резервного поллинга.
  useEffect(() => {
    const onRealtime = (e) => {
      const data = e.detail
      if (!data) return
      if (data.type === 'cityroof_captured' || data.type === 'cityroof_protected') {
        const merged = { ...data.business, isMine: currentUserId ? data.business.ownerId === currentUserId : false }
        setMap(m => {
          if (!m) return m
          const idx = m.businesses.findIndex(b => b.id === merged.id)
          if (idx === -1) return m
          const businesses = [...m.businesses]
          businesses[idx] = merged
          return { ...m, businesses }
        })
        setSelected(sel => (sel && sel.id === merged.id) ? merged : sel)
      } else if (data.type === 'cityroof_income') {
        setBonuses(b => {
          if (!b) return b
          const idx = b.bonuses.findIndex(x => x.slug === data.slug)
          if (idx === -1) return b
          const items = [...b.bonuses]
          items[idx] = { ...items[idx], amount: data.amount, readyInSec: data.intervalSec }
          return { ...b, bonuses: items }
        })
        bonusAnchors.current = { ...bonusAnchors.current, [data.slug]: Date.now() }
      } else if (data.type === 'cityroof_season_closed') {
        setSelected(null)
        setSession(null)
        load()
      } else if (data.type === 'notification' && data.notification?.type === 'itstudio') {
        // Заказ IT-студии завершился (см. backend/cityroof.py sweep_itstudio_jobs).
        fetchItStudioJobs().then(setItStudioJobs).catch(() => {})
        fetchMyStudios().then(setStudios).catch(() => {})
      }
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [currentUserId, load])

  const wc = map?.warcoin || { balance: 0, price: 0, league: '' }

  const openBusiness = (b) => {
    setSelected(b)
    setSession(null)
    setGuess([])
    setAttempts([])
  }

  const closeModal = () => {
    if (busy) return
    setSelected(null)
    setSession(null)
  }

  const [confirm, setConfirm] = useState(null)   // { title, message, danger, onConfirm }

  const startAttack = async () => {
    if (!selected) return
    setBusy(true)
    try {
      const res = await attackBusiness(selected.id)
      setSession(res)
      setGuess(Array(res.length).fill(0))
      setAttempts([])
      setMap(m => ({ ...m, warcoin: { ...m.warcoin, balance: res.warcoin } }))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const cyclePeg = (i) => {
    if (!session) return
    setGuess(g => {
      const next = [...g]
      next[i] = (next[i] + 1) % session.symbolRange
      return next
    })
  }

  const submitGuess = async () => {
    if (!session) return
    setBusy(true)
    try {
      const res = await guessCombination(session.sessionId, guess)
      if (res.dualShieldBroken) {
        // Двойной щит: комбинация верна, но бизнес не захвачен — нужен
        // второй заход с новой комбинацией (см. backend submit_guess).
        toast(t('cityroof.dualShieldBroken'), 'info')
        setSession(null)
        setAttempts([])
        setGuess([])
        await load()
      } else if (res.solved) {
        toast(res.capturedIncome > 0
          ? t('cityroof.capturedWithIncome', { amount: res.capturedIncome.toLocaleString('ru-RU') })
          : t('cityroof.captured'))
        setAttempts(a => [...a, { guess: [...guess], feedback: res.feedback, exact: res.exact, present: res.present }])
        setSession(null)
        await load()
        setTimeout(() => setSelected(null), 1200)
      } else if (res.exhausted) {
        setAttempts([])
        setGuess(Array(res.length).fill(0))
        setSession(s => ({ ...s, length: res.length, symbolRange: res.symbolRange, attempts: 0 }))
        toast(t('cityroof.newCombination'), 'info')
      } else {
        setAttempts(a => [...a, { guess: [...guess], feedback: res.feedback, exact: res.exact, present: res.present }])
        toast(t('cityroof.tryAgain', { attempts: res.attempts, max: res.maxAttempts }), 'info')
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doProtect = async (level) => {
    if (!selected) return
    setBusy(true)
    try {
      const res = await protectBusiness(selected.id, level)
      setMap(m => ({ ...m, warcoin: { ...m.warcoin, balance: res.warcoin } }))
      setSelected(res.business)
      toast(t('cityroof.protected', { level }))
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  // Двойной щит — эксклюзив премиальной IT-студии (tier === 'premium').
  // Первое верное угадывание лишь сбивает щит, поэтому захват требует двух
  // комбинаций подряд (см. backend/cityroof.py submit_guess).
  const premiumStudio = studios.find(s => s.tier === 'premium')

  const doDualShield = async () => {
    if (!selected || !premiumStudio) return
    setBusy(true)
    try {
      const res = await buyDualShield(selected.id, premiumStudio.assetId)
      onBalanceChange?.(res.balance)
      setSelected(res.business)
      toast(t('cityroof.dualShieldBought', { hours: res.hours }))
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  // IT-студия: атака/защита требуют владения активом-студией (см. «Моя
  // недвижимость») — здесь только точка входа, вся логика/валидация в
  // ItStudioOrderModal + backend/cityroof.py order_itstudio.
  const renderStudioAction = (mode) => {
    const pendingJob = itStudioJobs.find(j => j.businessId === selected?.id && j.type === mode && j.status === 'pending')
    if (pendingJob) {
      return <div className="itstudio-pending"><Clock size={13} /> {t('itstudio.pending')}</div>
    }
    if (studios.length === 0) {
      return (
        <button className="itstudio-btn" disabled title={t('itstudio.needStudio')}>
          {mode === 'attack' ? <Swords size={15} /> : <ShieldPlus size={15} />} {t('itstudio.needStudio')}
        </button>
      )
    }
    return (
      <button className="itstudio-btn" onClick={() => setOrderModal({ mode, businessId: selected.id })}>
        {mode === 'attack' ? <Swords size={15} /> : <ShieldPlus size={15} />}
        {' '}{t(mode === 'attack' ? 'itstudio.attack' : 'itstudio.defense')}
      </button>
    )
  }

  const submitStudioOrder = async (assetId, businessId) => {
    setOrderBusy(true)
    try {
      const res = await orderStudioJob(assetId, businessId, orderModal.mode)
      onBalanceChange?.(res.balance)
      const okText = res.readyInMinutes != null
        ? t('itstudio.orderedMinutes', { minutes: res.readyInMinutes })
        : t('itstudio.ordered', { hours: res.readyInHours })
      toast(okText)
      setOrderModal(null)
      setItStudioJobs(await fetchItStudioJobs())
      setStudios(await fetchMyStudios())
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setOrderBusy(false)
    }
  }

  const doBuyWc = async () => {
    const amt = Math.floor(Number(buyAmount))
    if (!(amt > 0)) return
    setBusy(true)
    try {
      const res = await buyWarcoin(amt)
      onBalanceChange?.(res.balance)
      setMap(m => ({ ...m, warcoin: { ...m.warcoin, balance: res.warcoin } }))
      setBuyModal(false)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="cityroof-tab">
        <h2 className="tab-title">{t('nav.cityroof')}</h2>
        <div className="asset-card skeleton" style={{ height: 320 }} />
      </div>
    )
  }

  return (
    <div className="cityroof-tab">
      <div className="leaderboard-title-row">
        <Castle size={22} className="icon" />
        <h2 className="tab-title">{t('nav.cityroof')}</h2>
      </div>

      <div className="cityroof-bar">
        <div className="wc-chip">
          <Coins size={16} />
          <span className="wc-balance">{map?.warcoin?.balance ?? 0} WC</span>
          <span className="wc-league">{t(`cityroof.leagues.${wc.league}`, wc.league)} · {formatCompact(wc.price)} $</span>
          <button className="wc-buy" onClick={() => setBuyModal(true)}><PlusCircle size={14} /> {t('cityroof.buyWc')}</button>
        </div>
        <div className={`cityroof-status ${map?.isActive ? 'active' : ''}`}>
          {t('cityroof.season')} {map?.season} · {map?.isActive ? t('cityroof.eventActive') : t('cityroof.eventClosed')}
        </div>
        <div className="cityroof-actions">
          <button className="cityroof-rooms-btn" onClick={() => setShowRooms(true)}>
            <DoorOpen size={14} /> {t('cityroof.roomList', 'Список комнат')}
          </button>
          <button className="cityroof-help-btn" onClick={() => setShowHelp(v => !v)} aria-expanded={showHelp}>
            ? {t('cityroof.help', 'Как играть')}
          </button>
        </div>
      </div>

      {showHelp && (
        <section className="cityroof-help-card">
          <h3>{t('cityroof.helpTitle', 'Крыша города')}</h3>
          <p>{t('cityroof.helpText', 'Выберите чужой бизнес, оплатите атаку и угадайте комбинацию. Владелец получает доход за удержание.')}</p>
          <p>{t('cityroof.helpLeague', 'Лига и комната фиксируются на сезон. Вы играете только в своей комнате — соперники подобраны по капиталу и активности.')}</p>
          <div className="cityroof-legend">
            <span className="cityroom-player active">{t('cityroof.activePlayer', 'Активный игрок')}</span>
            <span className="cityroom-player former">{t('cityroof.formerPlayer', 'Участвовал, но ничего не держит')}</span>
          </div>
        </section>
      )}

      <p className="cityroof-hint">{t('cityroof.hint', { cost: map?.attackCost ?? 10 })}</p>

      {bonuses && bonuses.bonuses.length > 0 && (
        <div className="cityroof-bonuses">
          <div className="cbonus-head">
            <span><Gift size={16} /> {t('cityroof.yourBonuses')}</span>
            <span className="cbonus-auto"><Zap size={13} /> {t('cityroof.autoCollect')}</span>
          </div>
          <div className="cbonus-list">
            {bonuses.bonuses.map(b => {
              const anchor = bonusAnchors.current[b.slug] ?? Date.now()
              const pctSign = DISCOUNT_EFFECTS.has(b.effect) ? '-' : '+'
              return (
                <div key={b.slug} className="cbonus-item">
                  <span className="cbonus-emoji">{BUILDING_EMOJI[b.slug] || '🏢'}</span>
                  <div className="cbonus-body">
                    <div className="cbonus-top">
                      <span className="cbonus-name">{buildingName(t, b.slug, b.name)}</span>
                      <span className="cbonus-daily">+{(b.amount ?? b.daily).toLocaleString('ru-RU')} $</span>
                    </div>
                    <span className="cbonus-effect">
                      {t(`cityroof.effects.${b.effect}`, b.effect)}{b.mult ? ` ${pctSign}${Math.round(b.mult * 100)}%` : ''}
                    </span>
                    <BonusCountdown anchor={anchor} readyInSec={b.readyInSec} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="cityroof-layout">
      <div className="cityroof-map">
        <img className="cityroof-map-img" src="/city.webp" alt="" aria-hidden="true" draggable="false" />
        <div className="cityroof-map-grid">
          {map?.businesses?.map(b => (
            <button
              key={b.id}
              className={`city-tile ${b.isMine ? 'mine' : ''} ${b.ownerId ? 'owned' : 'free'} ${highlightedPlayer && b.ownerId === highlightedPlayer.id ? 'player-highlight' : ''} ${highlightedPlayer && b.ownerId !== highlightedPlayer.id ? 'player-dim' : ''}`}
              style={{
                left: `${(b.x ?? 0) * 25}%`,
                top: `${(b.y ?? 0) * (100 / 3)}%`,
                ...(b.ownerColor ? { '--tile-color': b.ownerColor } : {}),
              }}
              onClick={() => openBusiness(b)}
            >
              <span className="city-tile-info">
                <span className="city-tile-name">{buildingName(t, b.slug, b.name)}</span>
                <span className="city-tile-reward"><DollarSign size={11} /> {b.reward}</span>
                <span className="city-tile-owner">
                  {b.isMine ? t('cityroof.yours') : (b.ownerName || t('cityroof.free'))}
                </span>
              </span>
              {b.dualShieldActive && (
                <span className="city-tile-dual" title={t('cityroof.dualShield')}>
                  <ShieldPlus size={11} /> ×2
                </span>
              )}
              {b.protectionLevel > 0 && (
                <span className="city-tile-shield"><Shield size={11} /> {b.protectionLevel}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Панель справа: участники выбранной комнаты. */}
      <aside className="cityroof-ranks" aria-label={t('cityroof.roomPlayers')}>
        <div className="cityroof-ranks-head">
          <Trophy size={15} />
          <span>{t('cityroof.roomPlayers')}</span>
          <span className="cityroof-ranks-league">{map?.roomMembers ?? 0}/{map?.roomCapacity ?? 8}</span>
        </div>
        <div className="cityroof-ranks-list">
          {(map?.members || []).length === 0 && (
            <p className="cityroof-ranks-empty">{t('cityroof.noPlayers')}</p>
          )}
          {(map?.members || []).map(p => (
            <div key={p.id} className={`cityroof-rank-row ${p.isMe ? 'me' : ''} ${p.active ? 'active' : ''} ${highlightedPlayer?.id === p.id ? 'selected' : ''}`}
              onMouseEnter={() => setHighlightedPlayer(p)} onMouseLeave={() => setHighlightedPlayer(null)}>
              <button className="cityroof-rank-name" onClick={() => setProfileId(p.id)}>{p.name}</button>
              {p.isMe && <span className="cityroof-rank-you">{t('cityroof.yours')}</span>}
              <span className="cityroof-rank-stats">
                <span className="cityroof-rank-wc" title={t('cityroof.warcoinShort')}>
                  <Coins size={11} /> {formatCompact(p.warcoin)}
                </span>
                <span className={`cityroof-rank-biz ${p.businesses > 0 ? 'has' : ''}`} title={t('cityroof.capturedCount')}>
                  <Castle size={11} /> {p.businesses}
                </span>
              </span>
            </div>
          ))}
        </div>
      </aside>
      </div>

      {showRooms && (
        <div className="modal-overlay" onClick={() => setShowRooms(false)}>
          <div className="modal-content cityroof-rooms-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setShowRooms(false)}><X size={18} /></button>
            <div className="cityroof-modal-title"><DoorOpen size={18} /><h3>{t('cityroof.roomList', 'Список комнат')}</h3></div>
            <p className="cityroof-modal-subtitle">{t('cityroof.roomListHint', 'Выберите комнату, чтобы посмотреть карту и владения игроков.')}</p>
            <div className="cityroof-modal-room-list">
              {(map?.rooms || []).map(room => (
                <button key={room.roomCode} className={`cityroof-room-option ${room.roomCode === map.roomCode ? 'active' : ''}`}
                  onClick={() => { setSelectedRoom(room.roomCode); setShowRooms(false); setHighlightedPlayer(null) }}>
                  <span><b>{room.roomCode}</b><small>{t(`cityroof.leagues.${room.league}`, room.league)}</small></span>
                  <span className="cityroof-room-online"><Users size={13} /> {room.roomMembers}/{room.roomCapacity}<Eye size={13} /></span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {highlightedPlayer && (
        <div className="cityroof-owner-popover">
          <b>{highlightedPlayer.name}</b><span>{t('cityroof.owns', 'Владеет')}</span>
          <div>{(map?.businesses || []).filter(b => b.ownerId === highlightedPlayer.id).map(b => buildingName(t, b.slug, b.name)).join(' · ') || t('cityroof.noProperties', 'Нет объектов')}</div>
        </div>
      )}

      {selected && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content cityroof-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={closeModal}><X size={18} /></button>
            <h3>{buildingName(t, selected.slug, selected.name)}</h3>
            <div className="cityroof-business-bonuses">
              <div><strong>{t('cityroof.captureBonus')}<Tooltip text={t('cityroof.captureBonusHelp')} /></strong><span>+{formatCompact(selected.reward)} $</span></div>
              <div><strong>{t('cityroof.holdBonus')}<Tooltip text={t('cityroof.holdBonusHelp')} /></strong><span>+{formatCompact(selected.dailyIncome || 0)} $/{t('cityroof.day')}</span></div>
              {selected.effect && <div><strong>{t(`cityroof.effects.${selected.effect}`, selected.effect)}</strong><span>+{Math.round((selected.effectMultiplier || 0) * 100)}%</span></div>}
              {selected.ownerId && <div><strong>{t('cityroof.ownerLabel')}</strong><span>{selected.ownerName || t('cityroof.yours')}</span></div>}
            </div>
            <p className="modal-price">
              <Coins size={14} /> {t('cityroof.reward')}: {selected.reward} ·
              {' '}{selected.ownerName
                ? selected.isMine
                  ? t('cityroof.owner', { name: t('cityroof.yours') })
                  : <>{t('cityroof.ownerLabel', 'Владелец')}: <span className="player-link" onClick={() => setProfileId(selected.ownerId)}>{selected.ownerName}</span></>
                : t('cityroof.free')}
              {selected.protectionLevel > 0 && <> · <Shield size={12} /> {selected.protectionLevel}</>}
            </p>

            {!map?.readOnly && selected.isMine && (
              <div className="cityroof-protect">
                <h4><Lock size={14} /> {t('cityroof.protection')}</h4>
                {/* Щиты взаимоисключающие: при активном двойном обычные
                    уровни недоступны, чтобы игрок не платил за неработающее. */}
                {selected.dualShieldActive ? (
                  <p className="dualshield-locked">
                    <Lock size={12} /> {t('cityroof.protectionReplacedByDual')}
                  </p>
                ) : (
                <div className="protect-levels">
                  {[1, 2, 3, 4, 5].map(lvl => (
                    <Tooltip key={lvl} text={t('cityroof.protectionLevelHelp', { level: lvl, cost: (map?.protectionCosts?.[lvl] ?? lvl * 1000).toLocaleString('ru-RU') })}>
                      <button
                        className={`protect-lvl ${selected.protectionLevel === lvl ? 'active' : ''}`}
                        disabled={busy}
                        onClick={() => setConfirm({
                          title: t('cityroof.protection'),
                          message: t('confirm.protect', { level: lvl, cost: (map?.protectionCosts?.[lvl] ?? lvl * 1000).toLocaleString('ru-RU') }),
                          onConfirm: () => doProtect(lvl),
                        })}
                      >
                        <Shield size={13} /> {lvl}
                        <small>{(map?.protectionCosts?.[lvl] ?? lvl * 1000).toLocaleString('ru-RU')} WC</small>
                      </button>
                    </Tooltip>
                  ))}
                </div>
                )}
                {!selected.dualShieldActive && renderStudioAction('defense')}

                <div className="cityroof-dualshield">
                  {selected.dualShieldActive ? (
                    <div className="dualshield-active">
                      <ShieldPlus size={14} />
                      <span>
                        {t('cityroof.dualShieldOn')}{' '}
                        <small>{t('cityroof.dualShieldUntil', { date: new Date(selected.dualShieldExpiresAt).toLocaleString() })}</small>
                      </span>
                      <Tooltip text={t('cityroof.dualShieldHelp')} />
                    </div>
                  ) : premiumStudio ? (
                    <>
                      <button
                        className="itstudio-btn dualshield-btn"
                        disabled={busy}
                        onClick={() => setConfirm({
                          title: t('cityroof.dualShield'),
                          message: t('confirm.dualShield', { cost: formatCompact(5_000_000) }),
                          onConfirm: doDualShield,
                        })}
                      >
                        <ShieldPlus size={15} /> {t('cityroof.dualShieldBuy', { cost: formatCompact(5_000_000) })}
                      </button>
                      <Tooltip text={t('cityroof.dualShieldHelp')} />
                    </>
                  ) : (
                    <div className="dualshield-locked">
                      <Lock size={12} /> {t('cityroof.dualShieldNeedsPremium')}
                    </div>
                  )}
                </div>
              </div>
            )}

            {!map?.readOnly && !selected.isMine && !session && (
              <button className="cityroof-attack-btn" disabled={busy}
                onClick={() => setConfirm({
                  danger: true,
                  title: t('cityroof.attack', { cost: map?.attackCost ?? 10 }),
                  message: t('confirm.attack', { name: buildingName(t, selected.slug, selected.name), cost: map?.attackCost ?? 10 }),
                  onConfirm: startAttack,
                })}>
                <Swords size={16} /> {busy ? t('bank.processing') : t('cityroof.attack', { cost: map?.attackCost ?? 10 })}
              </button>
            )}
            {!map?.readOnly && !selected.isMine && selected.ownerId && !session && renderStudioAction('attack')}

            {session && (
              <div className="cityroof-game">
                <p className="cityroof-game-hint">{t('cityroof.guessHint', { len: session.length, colors: session.symbolRange })}</p>
                <div className="peg-row">
                  {guess.map((s, i) => (
                    <button key={i} className="peg" style={{ background: PEG_COLORS[s % PEG_COLORS.length] }}
                      onClick={() => cyclePeg(i)} disabled={busy} aria-label={`peg-${i}`}>
                      {s}
                    </button>
                  ))}
                </div>
                <button className="cityroof-attack-btn" onClick={submitGuess} disabled={busy}>
                  <Swords size={15} /> {t('cityroof.submitGuess')}
                </button>

                {attempts.length > 0 && (
                  <div className="attempt-log">
                    {attempts.map((a, idx) => (
                      <div key={idx} className="attempt-row">
                        <div className="attempt-pegs">
                          {a.guess.map((s, i) => (
                            <span key={i} className={`peg-mini ${a.feedback?.[i] || ''}`}>
                              {s}
                            </span>
                          ))}
                        </div>
                        <span className="attempt-fb">
                          <b className="exact">{a.exact}</b> {t('cityroof.exact')} · <b className="present">{a.present}</b> {t('cityroof.present')}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {buyModal && (
        <div className="modal-overlay" onClick={() => !busy && setBuyModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setBuyModal(false)}><X size={18} /></button>
            <h3>{t('cityroof.buyWc')}</h3>
            <p className="modal-price">{formatCompact(wc.price)} $ / WC · {t('bank.currentBalance')}: ${formatCompact(balance)}</p>
            <div className="modal-quantity">
              <label>{t('common.quantity')}:</label>
              <input type="number" min="1" step="1" value={buyAmount} autoFocus
                onChange={e => setBuyAmount(e.target.value)} />
            </div>
            <p className="modal-total">{t('common.total')}: <strong>${formatMoney((Math.floor(Number(buyAmount)) || 0) * wc.price)}</strong></p>
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={doBuyWc} disabled={busy || !(Number(buyAmount) > 0)}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setBuyModal(false)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {orderModal && (
        <ItStudioOrderModal
          mode={orderModal.mode}
          map={map}
          studios={studios}
          initialBusinessId={orderModal.businessId}
          busy={orderBusy}
          onSubmit={submitStudioOrder}
          onClose={() => setOrderModal(null)}
        />
      )}

      <ConfirmDialog
        open={!!confirm}
        danger={confirm?.danger}
        busy={busy}
        title={confirm?.title}
        message={confirm?.message}
        onConfirm={() => { confirm?.onConfirm?.(); setConfirm(null) }}
        onCancel={() => setConfirm(null)}
      />
      {profileId && <PlayerProfileModal userId={profileId} onClose={() => setProfileId(null)} />}
    </div>
  )
}

export default CityRoofTab
