import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMediaStatus, fetchMediaTargets, fetchMediaFeed, orderExpose,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  Newspaper, Megaphone, AlertTriangle, Check, X, Target, TrendingDown, TrendingUp,
  Building2, User, Clock,
} from 'lucide-react'

/**
 * Модалка «Разоблачение в СМИ» — открывается из меню «Взаимодействие» на активе
 * «Медиахолдинг» (см. MyAssetsTab). Владелец Медиахолдинга заказывает разоблачение
 * против компании ИЛИ игрока. Новость готовится 15 мин–2 ч, затем планировщик
 * разыгрывает исход: успех снижает доход бизнесов цели (15–80% от взноса) и роняет
 * цену её акции; провал сжигает взнос и временно повышает доход цели.
 */
function MediaExposeModal({ onClose, onBalanceChange }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState(null)
  const [targets, setTargets] = useState({ companies: [], players: [] })
  const [feed, setFeed] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [form, setForm] = useState({ targetType: 'company', targetId: '', budget: '' })

  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 4000)
  }

  const load = useCallback(async () => {
    try {
      const st = await fetchMediaStatus()
      setStatus(st)
      const [tg, fd] = await Promise.all([fetchMediaTargets(), fetchMediaFeed()])
      setTargets(tg && tg.companies ? tg : { companies: [], players: [] })
      setFeed(fd)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const currentList = form.targetType === 'company' ? targets.companies : targets.players

  // Предпросмотр шанса успеха от взноса (формула зеркалит backend media._success_chance)
  const chancePreview = () => {
    if (!status) return null
    const b = Number(form.budget)
    if (!(b >= (status.minBudget || 0))) return null
    const extra = (status.chanceMax - status.chanceBase) * Math.min(1, b / status.chanceScale)
    return Math.min(status.chanceMax, status.chanceBase + extra)
  }

  // Предпросмотр силы удара 15–80% (зеркалит backend media._hit_pct)
  const hitPreview = () => {
    if (!status) return null
    const b = Number(form.budget)
    if (!(b >= (status.minBudget || 0))) return null
    const extra = (status.hitMaxPct - status.hitMinPct) * Math.min(1, b / status.hitScale)
    return Math.min(status.hitMaxPct, status.hitMinPct + extra)
  }

  const setType = (targetType) => setForm({ ...form, targetType, targetId: '' })

  const submit = async () => {
    const budget = Number(form.budget)
    if (!form.targetId) { flash(t('media.pickTarget'), 'error'); return }
    if (!(budget >= (status?.minBudget || 0))) { flash(t('media.budgetTooLow', { min: formatMoney(status?.minBudget || 0) }), 'error'); return }
    setBusy(true)
    try {
      const res = await orderExpose({ targetType: form.targetType, targetId: form.targetId, budget })
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('media.resultPending', { minutes: res.prepMinutes }), 'success')
      setForm({ ...form, targetId: '', budget: '' })
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const chance = chancePreview()
  const hit = hitPreview()

  return (
    <div className="modal-overlay" onClick={() => !busy && onClose?.()}>
      <div className="modal-content media-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={() => onClose?.()} disabled={busy}><X size={18} /></button>
        <h3><Newspaper size={18} /> {t('media.orderTitle')}</h3>

        {loading ? (
          <div className="asset-card skeleton" style={{ height: 160 }} />
        ) : (
          <>
            <p className="company-note">{t('media.intro', {
              hitMin: Math.round((status?.hitMinPct || 0) * 100),
              hitMax: Math.round((status?.hitMaxPct || 0) * 100),
              hoursMin: status?.effectHoursMin,
              hoursMax: status?.effectHoursMax,
              stock: Math.round((status?.stockHitPct || 0) * 100),
              prepMin: status?.prepMinMinutes,
              prepMax: status?.prepMaxMinutes,
            })}</p>

            {msg && (
              <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
                {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
              </div>
            )}

            {/* Тип цели: компания или игрок */}
            <div className="media-type-toggle">
              <button
                type="button"
                className={`tx-pill ${form.targetType === 'company' ? 'active' : ''}`}
                onClick={() => setType('company')}
              >
                <Building2 size={14} /> {t('media.typeCompany')}
              </button>
              <button
                type="button"
                className={`tx-pill ${form.targetType === 'player' ? 'active' : ''}`}
                onClick={() => setType('player')}
              >
                <User size={14} /> {t('media.typePlayer')}
              </button>
            </div>

            <label className="settings-label">{t('media.targetLabel')}</label>
            <select
              className="company-name-input"
              value={form.targetId}
              onChange={e => setForm({ ...form, targetId: e.target.value })}
            >
              <option value="">{t('media.pickTarget')}</option>
              {currentList.map(c => (
                <option key={c.id} value={c.id}>
                  {form.targetType === 'company' ? `${c.name} · ${c.ownerName}` : c.name}
                </option>
              ))}
            </select>

            <label className="settings-label">{t('media.budgetLabel')}</label>
            <input
              className="company-name-input"
              type="number" min={status?.minBudget} step="any"
              placeholder={t('media.budgetPlaceholder', { min: formatMoney(status?.minBudget || 0) })}
              value={form.budget}
              onChange={e => setForm({ ...form, budget: e.target.value })}
            />

            {chance != null && (
              <p className="media-chance">
                <Target size={14} /> {t('media.chance', { pct: Math.round(chance * 100) })}
                {hit != null && <> · <TrendingDown size={14} /> {t('media.hit', { pct: Math.round(hit * 100) })}</>}
              </p>
            )}

            <p className="media-warn">{t('media.warn', { backfire: Math.round((status?.backfirePct || 0) * 100) })}</p>

            <div className="modal-buttons">
              <button
                className="stock-btn buy-btn"
                disabled={busy || !form.targetId || !(Number(form.budget) >= (status?.minBudget || 0))}
                onClick={submit}
              >
                <Megaphone size={16} /> {busy ? t('bank.processing') : t('media.order')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => onClose?.()} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>

            {currentList.length === 0 && (
              <p className="empty-state">{t('media.noTargets')}</p>
            )}

            <div className="company-section" style={{ marginTop: 'var(--spacing-md)' }}>
              <h4 className="supplies-section-title"><Newspaper size={14} /> {t('media.feedTitle')}</h4>
              {feed.length === 0 ? (
                <p className="empty-state">{t('media.feedEmpty')}</p>
              ) : (
                <div className="media-feed-list">
                  {feed.map(e => (
                    <div key={e.id} className={`media-feed-item ${e.outcome}`}>
                      <span className="media-feed-icon">
                        {e.outcome === 'pending'
                          ? <Clock size={16} />
                          : e.outcome === 'success'
                            ? <TrendingDown size={16} />
                            : <TrendingUp size={16} />}
                      </span>
                      <div className="media-feed-text">
                        <span className="media-feed-title">
                          {e.outcome === 'pending'
                            ? t('media.feedPending', { name: e.targetName })
                            : e.outcome === 'success'
                              ? t('media.feedSuccess', { company: e.targetName })
                              : t('media.feedFail', { company: e.targetName })}
                        </span>
                        <span className="media-feed-date">
                          {e.createdAt ? new Date(e.createdAt).toLocaleString() : ''}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default MediaExposeModal
