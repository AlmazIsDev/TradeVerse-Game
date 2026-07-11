import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Swords, ShieldPlus, Clock, AlertTriangle } from 'lucide-react'

/**
 * Общая модалка заказа операции IT-студии (атака/защита) — используется и
 * из MyAssetsTab («Моя недвижимость»), и из CityRoofTab («Крыша города»),
 * чтобы не дублировать логику выбора студии/цели в двух местах. Цена,
 * материалы и шанс успеха приходят с сервера (map.itstudio + studios);
 * клиент только выбирает assetId/businessId — подделать исход нельзя,
 * сервер всё пересчитывает и валидирует заново (см. backend/cityroof.py
 * order_itstudio).
 */
function ItStudioOrderModal({ mode, map, initialBusinessId, studios = [], onSubmit, onClose, busy }) {
  const { t } = useTranslation()
  const cfg = map?.itstudio
  const targets = (map?.businesses || []).filter(b => (mode === 'attack' ? (!b.isMine && b.ownerId) : b.isMine))

  const [businessId, setBusinessId] = useState(initialBusinessId || targets[0]?.id || '')
  const [assetId, setAssetId] = useState(studios[0]?.assetId || '')

  const business = (map?.businesses || []).find(b => b.id === businessId)
  const studio = studios.find(s => s.assetId === assetId)

  const cost = cfg && business
    ? Math.round(cfg.costBase + (business.protectionLevel || 0) * cfg.costPerProtection)
    : 0
  const materialsNeeded = mode === 'attack' ? cfg?.materialsPerAttack : cfg?.materialsPerDefense
  const baseChance = studio ? (mode === 'attack' ? studio.attackChance : studio.defenseChance) : 0
  const shielded = mode === 'attack' && !!business?.shieldActive
  const effectiveChance = Math.max(0.05, baseChance - (shielded ? (cfg?.shieldPenalty || 0) : 0))
  const hasMaterials = studio && studio.material.qty >= (materialsNeeded || 0)
  const pendingJob = studio?.pendingJob

  const canSubmit = !!studio && !!business && hasMaterials && !pendingJob && !busy

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content itstudio-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <h3>
          {mode === 'attack' ? <Swords size={17} /> : <ShieldPlus size={17} />}
          {' '}{t(mode === 'attack' ? 'itstudio.orderAttack' : 'itstudio.orderDefense')}
        </h3>

        {studios.length === 0 && <p className="modal-price">{t('itstudio.needStudio')}</p>}

        {studios.length > 0 && targets.length === 0 && (
          <p className="modal-price">{t(mode === 'attack' ? 'itstudio.noTargets' : 'itstudio.noOwnBusiness')}</p>
        )}

        {studios.length > 0 && targets.length > 0 && (
          <>
            {studios.length > 1 && (
              <div className="modal-quantity">
                <label>{t('itstudio.selectStudio')}:</label>
                <select value={assetId} onChange={e => setAssetId(e.target.value)}>
                  {studios.map(s => (
                    <option key={s.assetId} value={s.assetId}>
                      {s.name} · {t(`itstudio.tier.${s.tier}`)} · {t('itstudio.level')} {s.level}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {!initialBusinessId && (
              <div className="modal-quantity">
                <label>{t('itstudio.selectTarget')}:</label>
                <select value={businessId} onChange={e => setBusinessId(e.target.value)}>
                  {targets.map(b => (
                    <option key={b.id} value={b.id}>
                      {b.name}{mode === 'attack' && b.ownerName ? ` (${b.ownerName})` : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {studio && business && (
              <div className="itstudio-preview">
                <div><span>{t('itstudio.cost')}</span><b>${cost.toLocaleString('ru-RU')}</b></div>
                <div><span>{t('itstudio.chance')}</span><b>{Math.round(effectiveChance * 100)}%</b></div>
                <div>
                  <span>{studio.material.name}</span>
                  <b className={hasMaterials ? '' : 'down'}>{studio.material.qty}/{materialsNeeded}</b>
                </div>
                {shielded && (
                  <div className="itstudio-shield-warn"><AlertTriangle size={12} /> {t('itstudio.targetShielded')}</div>
                )}
              </div>
            )}

            {pendingJob && (
              <p className="itstudio-pending"><Clock size={13} /> {t('itstudio.pending')}</p>
            )}
            {studio && !hasMaterials && !pendingJob && (
              <p className="transfer-feedback error"><AlertTriangle size={14} /><span>{t('itstudio.needMaterials')}</span></p>
            )}

            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={!canSubmit} onClick={() => onSubmit(assetId, businessId)}>
                {busy ? t('bank.processing') : t('itstudio.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default ItStudioOrderModal
