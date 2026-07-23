import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, Save, X, RefreshCw, Edit3 } from 'lucide-react'
import {
  adminListPriceHistory, adminAddPricePoint, adminUpdatePricePoint,
  adminDeletePricePoint, adminRegeneratePriceHistory,
} from '../services/api'

function PriceHistoryEditor({ market, symbol, onClose }) {
  const { t } = useTranslation()
  const [points, setPoints] = useState([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [editPrice, setEditPrice] = useState('')
  const [newPrice, setNewPrice] = useState('')
  const [regenPrice, setRegenPrice] = useState('')
  const [regenVolatility, setRegenVolatility] = useState('')
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await adminListPriceHistory(market, symbol)
      setPoints(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [market, symbol])

  useEffect(() => { load() }, [load])

  const handleStartEdit = (p) => {
    setEditingId(p.id)
    setEditPrice(String(p.price))
  }

  const handleSaveEdit = async (id) => {
    try {
      await adminUpdatePricePoint(id, { price: parseFloat(editPrice) })
      setEditingId(null)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm(t('admin.priceHistory.deletePointConfirm'))) return
    try {
      await adminDeletePricePoint(id)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleAdd = async () => {
    if (!newPrice) return
    try {
      await adminAddPricePoint({ market, symbol, price: parseFloat(newPrice) })
      setNewPrice('')
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleRegenerate = async () => {
    if (!confirm(t('admin.priceHistory.regenerateConfirm'))) return
    try {
      const payload = { market, symbol }
      if (regenPrice) payload.price = parseFloat(regenPrice)
      if (regenVolatility) payload.volatility = parseFloat(regenVolatility)
      await adminRegeneratePriceHistory(payload)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content price-history-modal" onClick={e => e.stopPropagation()}>
        <div className="price-history-header">
          <h3>{t('admin.priceHistory.title')}: {symbol}</h3>
          <button className="admin-btn" onClick={onClose}><X size={16} /></button>
        </div>

        {error && <div className="admin-message">{error}</div>}

        <div className="price-history-regenerate">
          <input
            type="number" step="0.01" placeholder={t('admin.priceHistory.priceOverride')}
            value={regenPrice} onChange={e => setRegenPrice(e.target.value)} className="admin-input"
          />
          <input
            type="number" step="0.01" placeholder={t('admin.priceHistory.volatilityOverride')}
            value={regenVolatility} onChange={e => setRegenVolatility(e.target.value)} className="admin-input"
          />
          <button className="admin-btn admin-btn-danger" onClick={handleRegenerate}>
            <RefreshCw size={14} /> {t('admin.priceHistory.regenerate')}
          </button>
        </div>

        <div className="form-row">
          <input
            type="number" step="0.01" placeholder={t('admin.priceHistory.newPointPrice')}
            value={newPrice} onChange={e => setNewPrice(e.target.value)} className="admin-input"
          />
          <button className="admin-btn admin-btn-primary" onClick={handleAdd}>
            <Plus size={14} /> {t('admin.priceHistory.addPoint')}
          </button>
        </div>

        {loading && <p>{t('common.loading')}</p>}
        {!loading && points.length === 0 && <p className="empty-state">{t('admin.priceHistory.noPoints')}</p>}

        <div className="price-history-table">
          {points.map(p => (
            <div key={p.id} className="price-history-row">
              <span className="price-history-ts">{new Date(p.ts).toLocaleString()}</span>
              {editingId === p.id ? (
                <>
                  <input
                    type="number" step="0.01" value={editPrice}
                    onChange={e => setEditPrice(e.target.value)} className="admin-input"
                  />
                  <button className="admin-btn admin-btn-primary" onClick={() => handleSaveEdit(p.id)}>
                    <Save size={14} />
                  </button>
                  <button className="admin-btn" onClick={() => setEditingId(null)}>
                    <X size={14} />
                  </button>
                </>
              ) : (
                <>
                  <span className="price-history-price">{p.price}</span>
                  <button className="admin-btn" onClick={() => handleStartEdit(p)}>
                    <Edit3 size={14} />
                  </button>
                  <button className="admin-btn admin-btn-danger" onClick={() => handleDelete(p.id)}>
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default PriceHistoryEditor
