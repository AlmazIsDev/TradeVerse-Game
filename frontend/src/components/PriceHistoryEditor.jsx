import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Plus, Trash2, Save, X, RefreshCw, Edit3, Search, ChevronLeft, ChevronRight, ChevronUp, ChevronDown,
} from 'lucide-react'
import {
  adminListPriceHistory, adminAddPricePoint, adminUpdatePricePoint,
  adminDeletePricePoint, adminRegeneratePriceHistory,
} from '../services/api'
import { toast } from './Toast'

const PAGE_SIZE = 50

// Формат должен совпадать с PH_TS_FORMAT на сервере: поиск идёт по той же строке,
// которую видит админ в таблице.
function fmtTs(iso) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const p = n => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}

function PriceHistoryEditor({ market, symbol, onClose }) {
  const { t } = useTranslation()
  const [data, setData] = useState({ items: [], total: 0, asset: {} })
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [editPrice, setEditPrice] = useState('')
  const [newPrice, setNewPrice] = useState('')
  const [regenPrice, setRegenPrice] = useState('')
  const [regenVolatility, setRegenVolatility] = useState('')
  const [regenerating, setRegenerating] = useState(false)
  const [search, setSearch] = useState('')       // дебаунсенное значение, уходит на сервер
  const [searchInput, setSearchInput] = useState('')
  const [page, setPage] = useState(0)
  const [sort, setSort] = useState('ts')
  const [order, setOrder] = useState(-1)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await adminListPriceHistory(market, symbol, {
        q: search || undefined, skip: page * PAGE_SIZE, limit: PAGE_SIZE, sort, order,
      }))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [market, symbol, search, page, sort, order])

  useEffect(() => { load() }, [load])

  useEffect(() => { setPage(0) }, [search, sort, order])

  // Дебаунс: у символа десятки тысяч точек, не дёргаем сервер на каждый символ.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), 400)
    return () => clearTimeout(id)
  }, [searchInput])

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
      toast(err.message, 'error')
    }
  }

  const handleDelete = async (id) => {
    if (!confirm(t('admin.priceHistory.deletePointConfirm'))) return
    try {
      await adminDeletePricePoint(id)
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const handleAdd = async () => {
    if (!newPrice) return
    try {
      await adminAddPricePoint({ market, symbol, price: parseFloat(newPrice) })
      setNewPrice('')
      await load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  const handleRegenerate = async () => {
    const price = regenPrice === '' ? data.asset?.price : parseFloat(regenPrice)
    const volatility = regenVolatility === '' ? data.asset?.volatility : parseFloat(regenVolatility)
    if (!(price > 0)) return toast(t('admin.priceHistory.badPrice'), 'error')
    if (!(volatility > 0 && volatility <= 1)) return toast(t('admin.priceHistory.badVolatility'), 'error')
    if (!confirm(t('admin.priceHistory.regenerateConfirm', { count: data.total, price, volatility }))) return
    setRegenerating(true)
    try {
      const res = await adminRegeneratePriceHistory({ market, symbol, price, volatility })
      toast(t('admin.priceHistory.regenerated', { count: res.points }))
      setRegenPrice('')
      setRegenVolatility('')
      setSearchInput('')
      setPage(0)
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setRegenerating(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE))
  const hasNext = page + 1 < totalPages

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content price-history-modal" onClick={e => e.stopPropagation()}>
        <div className="price-history-header">
          <h3>{t('admin.priceHistory.title')}: {symbol}</h3>
          <button className="admin-btn" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="price-history-regenerate">
          <input
            type="number" step="0.01" className="admin-input"
            placeholder={`${t('admin.priceHistory.priceOverride')}: ${data.asset?.price ?? '—'}`}
            value={regenPrice} onChange={e => setRegenPrice(e.target.value)}
          />
          <input
            type="number" step="0.01" className="admin-input"
            placeholder={`${t('admin.priceHistory.volatilityOverride')}: ${data.asset?.volatility ?? '—'}`}
            value={regenVolatility} onChange={e => setRegenVolatility(e.target.value)}
          />
          <button className="admin-btn admin-btn-danger" onClick={handleRegenerate} disabled={regenerating}>
            <RefreshCw size={14} className={regenerating ? 'spin' : ''} />
            {regenerating ? t('admin.priceHistory.regenerating') : t('admin.priceHistory.regenerate')}
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

        <div className="price-history-toolbar">
          <div className="tx-search"><Search size={15} className="tx-search-icon" />
            <input value={searchInput} onChange={e => setSearchInput(e.target.value)}
              placeholder={t('admin.priceHistory.searchPlaceholder')} /></div>
          <select className="admin-input" value={sort} onChange={e => setSort(e.target.value)}>
            <option value="ts">{t('admin.priceHistory.sortTs')}</option>
            <option value="price">{t('admin.priceHistory.sortPrice')}</option>
          </select>
          <button className="admin-btn" onClick={() => setOrder(o => -o)}
            title={order >= 0 ? t('admin.database.sortAsc') : t('admin.database.sortDesc')}>
            {order >= 0 ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          <span className="admin-count">{data.total}</span>
        </div>

        {loading && <p>{t('common.loading')}</p>}
        {!loading && data.items.length === 0 && <p className="empty-state">{t('admin.priceHistory.noPoints')}</p>}

        <div className="price-history-table">
          {data.items.map(p => (
            <div key={p.id} className="price-history-row">
              <span className="price-history-ts">{fmtTs(p.ts)}</span>
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

        {(page > 0 || hasNext) && (
          <div className="price-history-toolbar db-pagination">
            <button className="admin-btn" disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))}>
              <ChevronLeft size={14} />
            </button>
            <span className="admin-count">
              {t('admin.database.pageOf', { page: page + 1, total: totalPages })}
            </span>
            <button className="admin-btn" disabled={!hasNext} onClick={() => setPage(p => p + 1)}>
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default PriceHistoryEditor
