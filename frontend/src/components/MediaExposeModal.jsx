import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMediaStatus, fetchMediaTargets, fetchMediaFeed, orderExpose,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  Newspaper, Megaphone, AlertTriangle, Check, X, Target, TrendingDown, TrendingUp,
} from 'lucide-react'

/**
 * Модалка «Разоблачение в СМИ» — открывается из меню «Взаимодействие» на активе
 * «Медиахолдинг» (см. MyAssetsTab). Владелец Медиахолдинга заказывает разоблачение
 * против компании-конкурента: успех снижает доход бизнесов её владельца и роняет
 * цену акции; провал сжигает взнос и временно повышает доход цели.
 */
function MediaExposeModal({ onClose, onBalanceChange }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState(null)
  const [targets, setTargets] = useState([])
  const [feed, setFeed] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [form, setForm] = useState({ targetCompanyId: '', budget: '' })

  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 3200)
  }

  const load = useCallback(async () => {
    try {
      const st = await fetchMediaStatus()
      setStatus(st)
      const [tg, fd] = await Promise.all([fetchMediaTargets(), fetchMediaFeed()])
      setTargets(tg)
      setFeed(fd)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Предпросмотр шанса успеха от взноса (формула зеркалит backend media._success_chance)
  const chancePreview = () => {
    if (!status) return null
    const b = Number(form.budget)
    if (!(b >= (status.minBudget || 0))) return null
    const extra = (status.chanceMax - status.chanceBase) * Math.min(1, b / status.chanceScale)
    return Math.min(status.chanceMax, status.chanceBase + extra)
  }

  const submit = async () => {
    const budget = Number(form.budget)
    if (!form.targetCompanyId) { flash(t('media.pickTarget'), 'error'); return }
    if (!(budget >= (status?.minBudget || 0))) { flash(t('media.budgetTooLow', { min: formatMoney(status?.minBudget || 0) }), 'error'); return }
    setBusy(true)
    try {
      const res = await orderExpose({ targetCompanyId: form.targetCompanyId, budget })
      if (res?.balance != null) onBalanceChange?.(res.balance)
      if (res.outcome === 'success') {
        flash(t('media.resultSuccess', { hours: res.effectHours }), 'success')
      } else {
        flash(t('media.resultFail', { hours: res.effectHours }), 'error')
      }
      setForm({ targetCompanyId: '', budget: '' })
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const chance = chancePreview()

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
              hit: Math.round((status?.hitPct || 0) * 100),
              hours: status?.effectHours,
              stock: Math.round((status?.stockHitPct || 0) * 100),
            })}</p>

            {msg && (
              <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
                {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
              </div>
            )}

            <label className="settings-label">{t('media.targetLabel')}</label>
            <select
              className="company-name-input"
              value={form.targetCompanyId}
              onChange={e => setForm({ ...form, targetCompanyId: e.target.value })}
            >
              <option value="">{t('media.pickTarget')}</option>
              {targets.map(c => (
                <option key={c.id} value={c.id}>{c.name} · {c.ownerName}</option>
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
              </p>
            )}

            <p className="media-warn">{t('media.warn', { backfire: Math.round((status?.backfirePct || 0) * 100) })}</p>

            <div className="modal-buttons">
              <button
                className="stock-btn buy-btn"
                disabled={busy || !form.targetCompanyId || !(Number(form.budget) >= (status?.minBudget || 0))}
                onClick={submit}
              >
                <Megaphone size={16} /> {busy ? t('bank.processing') : t('media.order')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => onClose?.()} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>

            {targets.length === 0 && (
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
                        {e.outcome === 'success' ? <TrendingDown size={16} /> : <TrendingUp size={16} />}
                      </span>
                      <div className="media-feed-text">
                        <span className="media-feed-title">
                          {e.outcome === 'success'
                            ? t('media.feedSuccess', { company: e.targetCompanyName })
                            : t('media.feedFail', { company: e.targetCompanyName })}
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
