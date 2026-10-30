// ─────────────────────────────────────────────────────────────────────────────
// GpuShopEditor · модалка «Управлять магазином» для завода видеокарт.
// Данные: GET /api/production/{unitId}/gpu-shop. Цены: POST .../gpu-shop/price.
// Открыть/закрыть: POST .../gpu-shop/publish. Себестоимость видит только владелец.
// ─────────────────────────────────────────────────────────────────────────────
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Store, Loader2, X, Save, Trash2, Info, AlertTriangle } from 'lucide-react'
import { fetchGpuShop, setGpuShopPrice, setGpuShopPublished } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'

// Сервер присылает нарушения одной строкой через «;» или с переносами.
function splitViolations(message) {
  return String(message || '')
    .split(/;|\n/)
    .map(s => s.trim())
    .filter(Boolean)
}

function GpuShopEditor({ unitId, onClose }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [busyItem, setBusyItem] = useState(null)
  const [publishBusy, setPublishBusy] = useState(false)
  const [violations, setViolations] = useState([])

  const load = useCallback(async () => {
    try {
      const res = await fetchGpuShop(unitId)
      setData(res)
      setDrafts(Object.fromEntries(
        (res.items || []).map(it => [it.id, it.price != null ? String(it.price) : '']),
      ))
      setLoadError('')
    } catch (e) {
      setLoadError(e?.message || t('gpuShop.loadError'))
    } finally {
      setLoading(false)
    }
  }, [unitId, t])

  useEffect(() => { load() }, [load])

  const saveItem = async (it, clear = false) => {
    const raw = clear ? '' : String(drafts[it.id] ?? '').trim()
    const price = raw === '' ? null : Number(raw)
    if (price !== null && (!Number.isFinite(price) || price <= 0)) {
      toast(t('gpuShop.invalidPrice'), 'error')
      return
    }
    setBusyItem(it.id)
    try {
      await setGpuShopPrice(unitId, it.id, price)
      toast(price === null ? t('gpuShop.removed') : t('gpuShop.saved'), 'success')
      await load()
    } catch (e) {
      toast(e?.message || t('gpuShop.error'), 'error')
    } finally {
      setBusyItem(null)
    }
  }

  const togglePublish = async () => {
    const next = !data?.published
    setPublishBusy(true)
    setViolations([])
    try {
      await setGpuShopPublished(unitId, next)
      toast(next ? t('gpuShop.published') : t('gpuShop.unpublished'), 'success')
      await load()
    } catch (e) {
      setViolations(splitViolations(e?.message))
      toast(e?.message || t('gpuShop.error'), 'error')
    } finally {
      setPublishBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content gpu-shop-editor" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" title={t('common.close')} aria-label={t('common.close')} onClick={onClose}>
          <X size={18} />
        </button>
        <h3><Store size={17} /> {t('gpuShop.manageTitle')}</h3>

        {loading && <div className="empty-state"><Loader2 size={20} className="spin" /></div>}
        {!loading && loadError && <p className="gpu-shop-error">{loadError}</p>}

        {!loading && data && (
          <>
            <div className="gpu-shop-status">
              <span>{t('gpuShop.status')}:</span>
              <b className={data.published ? 'gpu-shop-open' : 'gpu-shop-closed'}>
                {data.published ? t('gpuShop.statusOpen') : t('gpuShop.statusClosed')}
              </b>
            </div>

            <p className="farm-hint gpu-shop-hint"><Info size={12} /> {t('gpuShop.priceHint')}</p>

            <table className="gpu-shop-table">
              <thead>
                <tr>
                  <th>{t('gpuShop.item')}</th>
                  <th>{t('gpuShop.costPrice')}</th>
                  <th>{t('gpuShop.priceInput')}</th>
                  <th>{t('gpuShop.profit')}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(data.items || []).map(it => (
                  <tr key={it.id}>
                    <td className="gpu-shop-name">{t(`gpuShop.items.${it.id}`, it.id)}</td>
                    <td>${formatMoney(it.costPrice)}</td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        className="gpu-shop-price-input"
                        value={drafts[it.id] ?? ''}
                        placeholder={t('gpuShop.notPriced')}
                        disabled={busyItem === it.id}
                        onChange={e => setDrafts({ ...drafts, [it.id]: e.target.value })}
                      />
                    </td>
                    <td className={it.priced && it.profit <= 0 ? 'gpu-shop-closed' : ''}>
                      {it.priced ? `$${formatMoney(it.profit)}` : '—'}
                    </td>
                    <td className="gpu-shop-actions">
                      <button className="farm-btn primary" disabled={busyItem === it.id}
                        onClick={() => saveItem(it)} title={t('gpuShop.save')}>
                        <Save size={14} /> {t('gpuShop.save')}
                      </button>
                      {it.priced && (
                        <button className="farm-btn" disabled={busyItem === it.id}
                          onClick={() => saveItem(it, true)} title={t('gpuShop.remove')}>
                          <Trash2 size={14} /> {t('gpuShop.remove')}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {violations.length > 0 && (
              <div className="gpu-shop-violations">
                <div><AlertTriangle size={14} /> <b>{t('gpuShop.violations')}</b></div>
                <ul>
                  {violations.map((v, i) => <li key={i}>{v}</li>)}
                </ul>
              </div>
            )}

            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={publishBusy} onClick={togglePublish}>
                {data.published ? t('gpuShop.close') : t('gpuShop.open')}
              </button>
              <button className="stock-btn cancel-btn" onClick={onClose}>{t('common.close')}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default GpuShopEditor
