import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCityMap, buyWarcoin, attackBusiness, guessCombination, protectBusiness,
  fetchCityBonuses, claimCityBonuses,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  Castle, Coins, Shield, Swords, X, Check, AlertTriangle, Crown, Lock, PlusCircle,
  Gift, HandCoins,
} from 'lucide-react'

// Ярлыки эффектов зданий. Каждый эффект реально подключён в игровой логике
// (см. backend/cityroof.py BUSINESS_BONUS и player_city_effect).
const EFFECT_LABEL = {
  rental_income: 'Доход от аренды',
  asset_income: 'Доход бизнеса и недвижимости',
  company_income: 'Доход компании',
  mining_yield: 'Доход майнинга',
  mining_energy: 'Скидка на электричество фермы',
  shop_discount: 'Скидка на оборудование',
  warcoin_discount: 'Скидка на WarCoin',
  daily_cash: 'Ежедневный доход',
}

// Палитра «пегов» для комбинации (индекс символа → цвет)
const PEG_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#6366f1', '#a855f7', '#ec4899', '#f5f5f5']

// Изображения зданий на карте (эмодзи вместо ассетов — работает без сети)
const BUILDING_EMOJI = {
  market: '🏬', bank: '🏦', casino: '🎰', port: '⚓', mall: '🛍️', factory: '🏭',
  stadium: '🏟️', airport: '✈️', hotel: '🏨', tower: '🏢', studio: '🎬', refinery: '🛢️',
}

function CityRoofTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [map, setMap] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)      // business
  const [session, setSession] = useState(null)        // { sessionId, length, symbolRange, ... }
  const [guess, setGuess] = useState([])
  const [attempts, setAttempts] = useState([])        // [{ guess, exact, present }]
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [buyModal, setBuyModal] = useState(false)
  const [buyAmount, setBuyAmount] = useState('10')
  const [bonuses, setBonuses] = useState(null)

  const load = useCallback(async () => {
    try {
      const [data, b] = await Promise.all([fetchCityMap(), fetchCityBonuses().catch(() => null)])
      setMap(data)
      setBonuses(b)
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [])

  const claimDaily = async () => {
    setBusy(true)
    try {
      const res = await claimCityBonuses()
      onBalanceChange?.(res.balance)
      await load()
    } catch { /* ignore */ } finally {
      setBusy(false)
    }
  }

  useEffect(() => { load() }, [load])

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
        setFeedback({ type: 'success', text: t('cityroof.captured') })
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

      {/* Бонусы зданий во владении */}
      {bonuses && bonuses.bonuses.length > 0 && (
        <div className="cityroof-bonuses">
          <div className="cbonus-head">
            <span><Gift size={16} /> {t('cityroof.yourBonuses')}</span>
            <button className="cbonus-claim" disabled={busy || !bonuses.claimable} onClick={claimDaily}>
              <HandCoins size={14} />
              {bonuses.claimable
                ? t('cityroof.claim', { amount: bonuses.totalDaily.toLocaleString('ru-RU') })
                : t('cityroof.claimIn', { hours: bonuses.hoursUntilClaim })}
            </button>
          </div>
          <div className="cbonus-list">
            {bonuses.bonuses.map(b => (
              <div key={b.slug} className="cbonus-item">
                <span className="cbonus-emoji">{BUILDING_EMOJI[b.slug] || '🏢'}</span>
                <div className="cbonus-info">
                  <span className="cbonus-name">{b.name}</span>
                  <span className="cbonus-effect">{EFFECT_LABEL[b.effect] || b.effect}{b.mult ? ` +${Math.round(b.mult * 100)}%` : ''}</span>
                </div>
                <span className="cbonus-daily">+{b.daily.toLocaleString('ru-RU')} $/д</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Карта */}
      <div className="cityroof-map">
        {map?.businesses?.map(b => (
          <button
            key={b.id}
            className={`city-cell ${b.isMine ? 'mine' : ''} ${b.ownerId ? 'owned' : 'free'}`}
            style={b.ownerColor ? { borderColor: b.ownerColor, boxShadow: `0 0 0 1px ${b.ownerColor}55` } : undefined}
            onClick={() => openBusiness(b)}
          >
            <span className="city-cell-emoji">{BUILDING_EMOJI[b.slug] || '🏢'}</span>
            <span className="city-cell-name">{b.name}</span>
            <span className="city-cell-reward"><Coins size={11} /> {b.reward}</span>
            <span className="city-cell-owner" style={b.ownerColor ? { color: b.ownerColor } : undefined}>
              {b.isMine ? t('cityroof.yours') : (b.ownerName || t('cityroof.free'))}
            </span>
            {b.protectionLevel > 0 && (
              <span className="city-cell-shield"><Shield size={11} /> {b.protectionLevel}</span>
            )}
          </button>
        ))}
      </div>

      {/* Модалка бизнеса */}
      {selected && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content cityroof-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={closeModal}><X size={18} /></button>
            <h3>{selected.name}</h3>
            <p className="modal-price">
              <Coins size={14} /> {t('cityroof.reward')}: {selected.reward} ·
              {' '}{selected.ownerName ? t('cityroof.owner', { name: selected.isMine ? t('cityroof.yours') : selected.ownerName }) : t('cityroof.free')}
              {selected.protectionLevel > 0 && <> · <Shield size={12} /> {selected.protectionLevel}</>}
            </p>

            {feedback && (
              <div className={`transfer-feedback ${feedback.type === 'info' ? '' : feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : feedback.type === 'error' ? <AlertTriangle size={16} /> : <Swords size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}

            {/* Владелец — защита */}
            {selected.isMine && (
              <div className="cityroof-protect">
                <h4><Lock size={14} /> {t('cityroof.protection')}</h4>
                <div className="protect-levels">
                  {[1, 2, 3, 4, 5].map(lvl => (
                    <button
                      key={lvl}
                      className={`protect-lvl ${selected.protectionLevel === lvl ? 'active' : ''}`}
                      disabled={busy}
                      onClick={() => doProtect(lvl)}
                    >
                      <Shield size={13} /> {lvl}
                      <small>{(map?.protectionCosts?.[lvl] ?? lvl * 1000).toLocaleString('ru-RU')} WC</small>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Не владелец — атака */}
            {!selected.isMine && !session && (
              <button className="cityroof-attack-btn" onClick={startAttack} disabled={busy}>
                <Swords size={16} /> {busy ? t('bank.processing') : t('cityroof.attack', { cost: map?.attackCost ?? 10 })}
              </button>
            )}

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
    </div>
  )
}

export default CityRoofTab
