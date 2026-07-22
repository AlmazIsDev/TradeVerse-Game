import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCityMap, buyWarcoin, attackBusiness, guessCombination, protectBusiness,
  fetchCityBonuses, fetchItStudioJobs, fetchMyStudios, orderStudioJob,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import ConfirmDialog from './ConfirmDialog'
import ItStudioOrderModal from './ItStudioOrderModal'
import PlayerProfileModal from './PlayerProfileModal'
import {
  Castle, Coins, Shield, Swords, X, Check, AlertTriangle, Crown, Lock, PlusCircle,
  Gift, Zap, ShieldPlus, Clock,
} from 'lucide-react'

// Форматирует секунды в M:SS для таймера автосбора.
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

// Палитра «пегов» для комбинации (индекс символа → цвет)
const PEG_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#6366f1', '#a855f7', '#ec4899', '#f5f5f5']

// Изображения зданий на карте (эмодзи вместо ассетов — работает без сети)
const BUILDING_EMOJI = {
  market: '🏬', bank: '🏦', casino: '🎰', port: '⚓', mall: '🛍️', factory: '🏭',
  stadium: '🏟️', airport: '✈️', hotel: '🏨', tower: '🏢', studio: '🎬', refinery: '🛢️',
}

function CityRoofTab({ balance = 0, onBalanceChange, currentUserId }) {
  const { t } = useTranslation()
  const [map, setMap] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)      // business
  const [profileId, setProfileId] = useState(null)
  const [session, setSession] = useState(null)        // { sessionId, length, symbolRange, ... }
  const [guess, setGuess] = useState([])
  const [attempts, setAttempts] = useState([])        // [{ guess, exact, present }]
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [buyModal, setBuyModal] = useState(false)
  const [buyAmount, setBuyAmount] = useState('10')
  const [bonuses, setBonuses] = useState(null)
  const bonusAnchors = useRef({})     // slug -> момент (мс), от которого считаем локальный отсчёт readyInSec
  const [itStudioJobs, setItStudioJobs] = useState([])
  const [studios, setStudios] = useState([])          // собственные IT-студии игрока
  const [orderModal, setOrderModal] = useState(null)   // { mode, businessId }
  const [orderBusy, setOrderBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [data, b, jobs, myStudios] = await Promise.all([
        fetchCityMap(), fetchCityBonuses().catch(() => null), fetchItStudioJobs().catch(() => []),
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

  useEffect(() => { load() }, [load])

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
        setFeedback(null)
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
    setFeedback(null)
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
    setFeedback(null)
    try {
      const res = await attackBusiness(selected.id)
      setSession(res)
      setGuess(Array(res.length).fill(0))
      setAttempts([])
      setMap(m => ({ ...m, warcoin: { ...m.warcoin, balance: res.warcoin } }))
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
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
    setFeedback(null)
    try {
      const res = await guessCombination(session.sessionId, guess)
      if (res.solved) {
        setFeedback({
          type: 'success',
          text: res.capturedIncome > 0
            ? t('cityroof.capturedWithIncome', { amount: res.capturedIncome.toLocaleString('ru-RU') })
            : t('cityroof.captured'),
        })
        setAttempts(a => [...a, { guess: [...guess], exact: res.exact, present: res.present }])
        setSession(null)
        await load()
        setTimeout(() => setSelected(null), 1200)
      } else if (res.exhausted) {
        setAttempts(a => [...a, { guess: [...guess], exact: res.exact, present: res.present }])
        setFeedback({ type: 'error', text: t('cityroof.exhausted') })
        setSession(null)
      } else {
        setAttempts(a => [...a, { guess: [...guess], exact: res.exact, present: res.present }])
        setFeedback({ type: 'info', text: t('cityroof.tryAgain', { attempts: res.attempts, max: res.maxAttempts }) })
      }
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const doProtect = async (level) => {
    if (!selected) return
    setBusy(true)
    setFeedback(null)
    try {
      const res = await protectBusiness(selected.id, level)
      setMap(m => ({ ...m, warcoin: { ...m.warcoin, balance: res.warcoin } }))
      setSelected(res.business)
      setFeedback({ type: 'success', text: t('cityroof.protected', { level }) })
      await load()
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
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
      setFeedback({ type: 'success', text: okText })
      setOrderModal(null)
      setItStudioJobs(await fetchItStudioJobs())
      setStudios(await fetchMyStudios())
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
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
      setFeedback({ type: 'error', text: err.message })
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

      {/* Панель WarCoin + статус события */}
      <div className="cityroof-bar">
        <div className="wc-chip">
          <Coins size={16} />
          <span className="wc-balance">{map?.warcoin?.balance ?? 0} WC</span>
          <span className="wc-league">{t(`cityroof.leagues.${wc.league}`, wc.league)} · {formatMoney(wc.price)} $</span>
          <button className="wc-buy" onClick={() => setBuyModal(true)}><PlusCircle size={14} /> {t('cityroof.buyWc')}</button>
        </div>
        <div className={`cityroof-status ${map?.isActive ? 'active' : ''}`}>
          {t('cityroof.season')} {map?.season} · {map?.isActive ? t('cityroof.eventActive') : t('cityroof.eventClosed')}
        </div>
      </div>

      <p className="cityroof-hint">{t('cityroof.hint', { cost: map?.attackCost ?? 10 })}</p>

      {/* Бонусы зданий во владении — доход зачисляется автоматически (автосбор) */}
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
                      <span className="cbonus-name">{b.name}</span>
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

      {/* Карта — реальное изображение города с интерактивными зданиями поверх */}
      <div className="cityroof-map">
        <img className="cityroof-map-img" src="/city.webp" alt="" aria-hidden="true" draggable="false" />
        <div className="cityroof-map-grid">
          {map?.businesses?.map(b => (
            <button
              key={b.id}
              className={`city-tile ${b.isMine ? 'mine' : ''} ${b.ownerId ? 'owned' : 'free'}`}
              style={{
                left: `${(b.x ?? 0) * 25}%`,
                top: `${(b.y ?? 0) * (100 / 3)}%`,
                ...(b.ownerColor ? { '--tile-color': b.ownerColor } : {}),
              }}
              onClick={() => openBusiness(b)}
            >
              <span className="city-tile-info">
                <span className="city-tile-name">{b.name}</span>
                <span className="city-tile-reward"><Coins size={11} /> {b.reward}</span>
                <span className="city-tile-owner">
                  {b.isMine ? t('cityroof.yours') : (b.ownerName || t('cityroof.free'))}
                </span>
              </span>
              {b.protectionLevel > 0 && (
                <span className="city-tile-shield"><Shield size={11} /> {b.protectionLevel}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Модалка бизнеса */}
      {selected && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content cityroof-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={closeModal}><X size={18} /></button>
            <h3>{selected.name}</h3>
            <p className="modal-price">
              <Coins size={14} /> {t('cityroof.reward')}: {selected.reward} ·
              {' '}{selected.ownerName
                ? selected.isMine
                  ? t('cityroof.owner', { name: t('cityroof.yours') })
                  : <>{t('cityroof.ownerLabel', 'Владелец')}: <span className="player-link" onClick={() => setProfileId(selected.ownerId)}>{selected.ownerName}</span></>
                : t('cityroof.free')}
              {selected.protectionLevel > 0 && <> · <Shield size={12} /> {selected.protectionLevel}</>}
            </p>

            {feedback && (
              <div className={`transfer-feedback ${feedback.type === 'info' ? '' : feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : feedback.type === 'error' ? <AlertTriangle size={16} /> : <Swords size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}

            {/* Владелец — защита (WC) + IT-студия */}
            {selected.isMine && (
              <div className="cityroof-protect">
                <h4><Lock size={14} /> {t('cityroof.protection')}</h4>
                <div className="protect-levels">
                  {[1, 2, 3, 4, 5].map(lvl => (
                    <button
                      key={lvl}
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
                  ))}
                </div>
                {renderStudioAction('defense')}
              </div>
            )}

            {/* Не владелец — атака (мини-игра) + IT-студия */}
            {!selected.isMine && !session && (
              <button className="cityroof-attack-btn" disabled={busy}
                onClick={() => setConfirm({
                  danger: true,
                  title: t('cityroof.attack', { cost: map?.attackCost ?? 10 }),
                  message: t('confirm.attack', { name: selected.name, cost: map?.attackCost ?? 10 }),
                  onConfirm: startAttack,
                })}>
                <Swords size={16} /> {busy ? t('bank.processing') : t('cityroof.attack', { cost: map?.attackCost ?? 10 })}
              </button>
            )}
            {!selected.isMine && selected.ownerId && !session && renderStudioAction('attack')}

            {/* Мини-игра */}
            {session && (
              <div className="cityroof-game">
                <p className="cityroof-game-hint">{t('cityroof.guessHint', { len: session.length, colors: session.symbolRange })}</p>
                <div className="peg-row">
                  {guess.map((s, i) => (
                    <button key={i} className="peg" style={{ background: PEG_COLORS[s % PEG_COLORS.length] }}
                      onClick={() => cyclePeg(i)} disabled={busy} aria-label={`peg-${i}`} />
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
                          {a.guess.map((s, i) => <span key={i} className="peg-mini" style={{ background: PEG_COLORS[s % PEG_COLORS.length] }} />)}
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

      {/* Покупка WC */}
      {buyModal && (
        <div className="modal-overlay" onClick={() => !busy && setBuyModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setBuyModal(false)}><X size={18} /></button>
            <h3>{t('cityroof.buyWc')}</h3>
            <p className="modal-price">{formatMoney(wc.price)} $ / WC · {t('bank.currentBalance')}: ${formatMoney(balance)}</p>
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
