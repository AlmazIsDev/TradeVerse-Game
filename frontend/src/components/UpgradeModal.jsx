import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { X, ArrowUpCircle, ChevronLeft, ChevronRight, TrendingUp, Wallet, KeyRound } from 'lucide-react'
import { fetchUpgradePreview } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'

/**
 * Модалка «Улучшения»: горизонтальный скроллер уровней. Все суммы (цена шага,
 * накопленная цена, доход, стоимость) приходят с сервера — см.
 * assets.py _upgrade_plan, чтобы превью не разошлось со списанием.
 */
function UpgradeModal({ asset, balance = 0, busy = false, onClose, onConfirm }) {
  const { t } = useTranslation()
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(1)   // на сколько уровней качаем
  const trackRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    fetchUpgradePreview(asset.id)
      .then(data => { if (!cancelled) setPreview(data) })
      .catch(err => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [asset.id])

  const levels = preview?.levels || []
  const target = levels[selected - 1]
  const current = preview?.current

  // Держим выбранную карточку в поле зрения при переключении стрелками/клавишами.
  useEffect(() => {
    const el = trackRef.current?.querySelector('.upgrade-step.active')
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  }, [selected])

  const shift = (d) => setSelected(s => Math.min(levels.length || 1, Math.max(1, s + d)))

  const affordable = target ? balance >= target.totalCost : false
  const delta = (key) => target && current ? target[key] - current[key] : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content upgrade-modal" onClick={e => e.stopPropagation()}
        onKeyDown={e => {
          if (e.key === 'ArrowRight') { e.preventDefault(); shift(1) }
          if (e.key === 'ArrowLeft') { e.preventDefault(); shift(-1) }
        }}
        tabIndex={-1}
      >
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <h3><ArrowUpCircle size={17} /> {t('upgrade.title')}: {t(`assetNames.${asset.slug}`, asset.name)}</h3>

        {error && <p className="modal-price down">{error}</p>}
        {!preview && !error && <p className="modal-price">{t('common.loading')}</p>}

        {preview && (
          <>
            <p className="modal-price">
              {t('upgrade.currentLevel')}: <b>{current.level}</b> → <b>{target?.level}</b>
            </p>

            <div className="upgrade-scroller">
              <button className="upgrade-arrow" onClick={() => shift(-1)} disabled={selected <= 1}
                aria-label={t('upgrade.prev')}><ChevronLeft size={18} /></button>

              <div className="upgrade-track" ref={trackRef}>
                {levels.map((lv, i) => (
                  <button key={lv.level} type="button"
                    className={`upgrade-step ${i + 1 === selected ? 'active' : ''} ${i + 1 <= selected ? 'included' : ''}`}
                    onClick={() => setSelected(i + 1)}>
                    <span className="upgrade-step-level">{t('myassets.level')} {lv.level}</span>
                    <span className="upgrade-step-profit up">${formatMoney(lv.profitPerHour)}{t('units.perHour')}</span>
                    <span className="upgrade-step-cost">${formatMoney(lv.totalCost)}</span>
                  </button>
                ))}
              </div>

              <button className="upgrade-arrow" onClick={() => shift(1)} disabled={selected >= levels.length}
                aria-label={t('upgrade.next')}><ChevronRight size={18} /></button>
            </div>

            <div className="upgrade-summary">
              <div className="upgrade-row">
                <span><TrendingUp size={13} /> {t('market.profitPerHour')}</span>
                <b>${formatMoney(current.profitPerHour)} → <span className="up">${formatMoney(target.profitPerHour)}</span>
                  <i className="upgrade-delta">+${formatMoney(delta('profitPerHour'))}</i></b>
              </div>
              <div className="upgrade-row">
                <span><Wallet size={13} /> {t('myassets.value')}</span>
                <b>${formatMoney(current.value)} → <span className="up">${formatMoney(target.value)}</span></b>
              </div>
              {current.rentRatePerHour > 0 && (
                <div className="upgrade-row">
                  <span><KeyRound size={13} /> {t('upgrade.rentRate')}</span>
                  <b>${formatMoney(current.rentRatePerHour)} → <span className="up">${formatMoney(target.rentRatePerHour)}</span></b>
                </div>
              )}
              <div className="upgrade-row payback">
                <span>{t('upgrade.payback')}</span>
                <b>{delta('profitPerHour') > 0
                  ? t('upgrade.paybackHours', { hours: Math.ceil(target.totalCost / delta('profitPerHour')) })
                  : '—'}</b>
              </div>
            </div>

            <p className="modal-total">
              {t('upgrade.totalCost')}: <strong className={affordable ? '' : 'down'}>${formatMoney(target.totalCost)}</strong>
              {' '}<span className="upgrade-balance">({t('upgrade.balance')}: ${formatMoney(balance)})</span>
            </p>

            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy || !affordable}
                onClick={() => {
                  if (!affordable) { toast(t('upgrade.notEnough'), 'error'); return }
                  onConfirm(selected, target.totalCost, target.level)
                }}>
                {t('upgrade.confirm', { levels: selected })}
              </button>
              <button className="stock-btn cancel-btn" onClick={onClose}>{t('common.cancel')}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default UpgradeModal
