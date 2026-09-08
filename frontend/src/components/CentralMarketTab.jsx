import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchMyAssets } from '../services/api'
import {
  Plus, Search, X, Filter, ArrowUpDown, ArrowUp, ArrowDown,
  Package, Tag, Hash, DollarSign, AlertTriangle, Check, ChevronDown,
  Edit3, Trash2, ShoppingCart, User,
} from 'lucide-react'

// Категории для фильтра и бейджей.
const CATEGORIES = [
  { id: 'all', icon: '🗂️' },
  { id: 'realestate', icon: '🏠' },
  { id: 'business', icon: '🏢' },
  { id: 'car', icon: '🚗' },
  { id: 'item', icon: '📦' },
  { id: 'other', icon: '✨' },
]

// Каталог возможных предметов (используется для режима «Свободный предмет»,
// когда игрок хочет выставить то, чего у него сейчас нет в инвентаре).
const ITEM_CATALOG = [
  { id: 'flat2', name: 'Квартира', category: 'realestate' },
  { id: 'townhouse', name: 'Таунхаус', category: 'realestate' },
  { id: 'villa', name: 'Вилла', category: 'realestate' },
  { id: 'penthouse', name: 'Пентхаус', category: 'realestate' },
  { id: 'castle', name: 'Замок', category: 'realestate' },
  { id: 'coffee', name: 'Кофейня', category: 'business' },
  { id: 'shawarma', name: 'Шаурмячная', category: 'business' },
  { id: 'carwash', name: 'Автомойка', category: 'business' },
  { id: 'factory', name: 'Завод', category: 'business' },
  { id: 'itstudio_basic', name: 'IT-студия (Basic)', category: 'business' },
  { id: 'sedan', name: 'Седан', category: 'car' },
  { id: 'sport', name: 'Спорткар', category: 'car' },
  { id: 'super', name: 'Суперкар', category: 'car' },
  { id: 'metal', name: 'Металл', category: 'item' },
  { id: 'wood', name: 'Древесина', category: 'item' },
]

function findItemMeta(itemId) {
  return ITEM_CATALOG.find(i => i.id === itemId) || { id: itemId, name: itemId, category: 'other' }
}

function fmtMoney(n) {
  if (n == null || isNaN(n)) return '—'
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function CentralMarketTab() {
  const { t } = useTranslation()

  // ── Состояние лотов и инвентаря ────────────────────────────────────────
  const [lots, setLots] = useState([])
  const [inventory, setInventory] = useState([])
  const [inventoryLoading, setInventoryLoading] = useState(false)

  // ── Текущий пользователь (для определения «свой/чужой» лот) ────────────
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const raw = localStorage.getItem('tradeverse_user')
      return raw ? JSON.parse(raw) : null
    } catch { return null }
  })

  // ── Фильтры/сортировка/поиск ───────────────────────────────────────────
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [category, setCategory] = useState('all')
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [minQty, setMinQty] = useState('')
  const [maxQty, setMaxQty] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 250)
    return () => clearTimeout(id)
  }, [searchInput])

  // Сортировка: default | price_asc | price_desc
  const [sort, setSort] = useState('default')
  const cycleSort = useCallback(() => {
    setSort(s => s === 'default' ? 'price_asc' : s === 'price_asc' ? 'price_desc' : 'default')
  }, [])

  // ── Создание лота ──────────────────────────────────────────────────────
  const [createOpen, setCreateOpen] = useState(false)
  const [createSource, setCreateSource] = useState('inventory')  // 'inventory' | 'free'
  const [createItemId, setCreateItemId] = useState('')
  const [createQty, setCreateQty] = useState('1')
  const [createPrice, setCreatePrice] = useState('')
  const [createError, setCreateError] = useState(null)
  const [createBusy, setCreateBusy] = useState(false)

  // ── Редактирование/удаление лота ───────────────────────────────────────
  const [editLot, setEditLot] = useState(null)  // объект лота или null
  const [editQty, setEditQty] = useState('1')
  const [editPrice, setEditPrice] = useState('')
  const [editError, setEditError] = useState(null)
  const [editBusy, setEditBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)  // lot или null

  // ── Тост ────────────────────────────────────────────────────────────────
  const [toast, setToast] = useState(null)
  const toastTimerRef = useRef(null)
  const showToast = useCallback((kind, text) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    setToast({ kind, text })
    toastTimerRef.current = setTimeout(() => setToast(null), 2500)
  }, [])

  // ── Загрузка инвентаря ────────────────────────────────────────────────
  const loadInventory = useCallback(async () => {
    setInventoryLoading(true)
    try {
      const data = await fetchMyAssets()
      setInventory(Array.isArray(data) ? data : (data?.items || []))
    } catch {
      setInventory([])
    } finally {
      setInventoryLoading(false)
    }
  }, [])

  useEffect(() => { loadInventory() }, [loadInventory])

  // Делаем список инвентаря плоским: { id, slug, name, type, qty }
  const inventoryOptions = useMemo(() => {
    return inventory.map(a => ({
      id: a._id || a.id || a.slug,
      slug: a.slug,
      name: a.name || a.slug,
      type: a.type || 'other',
      qty: a.qty ?? a.quantity ?? 1,
    }))
  }, [inventory])

  // ── Сброс/инициализация формы создания ───────────────────────────────
  const resetCreate = useCallback(() => {
    setCreateSource('inventory')
    setCreateItemId('')
    setCreateQty('1')
    setCreatePrice('')
    setCreateError(null)
    setCreateBusy(false)
  }, [])
  const openCreate = useCallback(() => {
    resetCreate()
    // Если инвентарь пуст, по умолчанию предлагаем «свободный» режим
    if (inventoryOptions.length === 0) setCreateSource('free')
    setCreateOpen(true)
  }, [resetCreate, inventoryOptions.length])
  const closeCreate = useCallback(() => {
    setCreateOpen(false)
    resetCreate()
  }, [resetCreate])

  // ── Создание лота (мок) ───────────────────────────────────────────────
  const submitCreate = useCallback(async () => {
    setCreateError(null)
    const qty = Number(createQty)
    const price = Number(createPrice)
    if (!createItemId) return setCreateError(t('createLot.errorItem'))
    if (!Number.isFinite(qty) || qty <= 0) return setCreateError(t('createLot.errorQty'))
    if (!Number.isFinite(price) || price <= 0) return setCreateError(t('createLot.errorPrice'))

    // В режиме инвентаря: кол-во не должно превышать остаток
    if (createSource === 'inventory') {
      const src = inventoryOptions.find(o => o.id === createItemId || o.slug === createItemId)
      if (src && qty > src.qty) {
        return setCreateError(t('createLot.errorQtyExceed', { max: src.qty }))
      }
    }

    setCreateBusy(true)
    try {
      await new Promise(r => setTimeout(r, 350))
      const newLot = {
        id: Date.now(),
        itemId: createItemId,
        qty,
        pricePerItem: price,
        sellerId: currentUser?.id || 'me',
        seller: currentUser?.username || t('createLot.you'),
        createdAt: Date.now(),
      }
      setLots(prev => [newLot, ...prev])
      showToast('success', t('createLot.success'))
      closeCreate()
    } catch (e) {
      setCreateError(e?.message || t('common.error'))
    } finally {
      setCreateBusy(false)
    }
  }, [createItemId, createQty, createPrice, createSource, inventoryOptions, currentUser, t, showToast, closeCreate])

  // ── Редактирование лота (мок) ─────────────────────────────────────────
  const openEdit = useCallback((lot) => {
    setEditLot(lot)
    setEditQty(String(lot.qty))
    setEditPrice(String(lot.pricePerItem))
    setEditError(null)
    setEditBusy(false)
  }, [])
  const closeEdit = useCallback(() => {
    setEditLot(null)
    setEditError(null)
    setEditBusy(false)
  }, [])
  const submitEdit = useCallback(async () => {
    if (!editLot) return
    setEditError(null)
    const qty = Number(editQty)
    const price = Number(editPrice)
    if (!Number.isFinite(qty) || qty <= 0) return setEditError(t('createLot.errorQty'))
    if (!Number.isFinite(price) || price <= 0) return setEditError(t('createLot.errorPrice'))
    setEditBusy(true)
    try {
      await new Promise(r => setTimeout(r, 300))
      setLots(prev => prev.map(l => l.id === editLot.id ? { ...l, qty, pricePerItem: price } : l))
      showToast('success', t('centralmarket.editSuccess'))
      closeEdit()
    } catch (e) {
      setEditError(e?.message || t('common.error'))
    } finally {
      setEditBusy(false)
    }
  }, [editLot, editQty, editPrice, t, showToast, closeEdit])

  // ── Удаление лота (мок) ───────────────────────────────────────────────
  const doDelete = useCallback(async (lot) => {
    try {
      await new Promise(r => setTimeout(r, 250))
      setLots(prev => prev.filter(l => l.id !== lot.id))
      showToast('success', t('centralmarket.deleteSuccess'))
      setConfirmDelete(null)
    } catch (e) {
      showToast('error', e?.message || t('common.error'))
    }
  }, [showToast, t])

  // ── Покупка лота (мок) ────────────────────────────────────────────────
  const buyLot = useCallback(async (lot) => {
    showToast('success', t('centralmarket.buySuccess', { name: findItemMeta(lot.itemId).name, qty: lot.qty }))
    setLots(prev => prev.filter(l => l.id !== lot.id))
  }, [showToast, t])

  // ── Фильтрация + сортировка ───────────────────────────────────────────
  const filtered = useMemo(() => {
    const minP = minPrice === '' ? -Infinity : Number(minPrice)
    const maxP = maxPrice === '' ? Infinity : Number(maxPrice)
    const minQ = minQty === '' ? -Infinity : Number(minQty)
    const maxQ = maxQty === '' ? Infinity : Number(maxQty)
    const q = search

    return lots
      .filter(lot => {
        const item = findItemMeta(lot.itemId)
        if (category !== 'all' && item.category !== category) return false
        if (lot.pricePerItem < minP || lot.pricePerItem > maxP) return false
        if (lot.qty < minQ || lot.qty > maxQ) return false
        if (q) {
          const name = item.name.toLowerCase()
          const cat = item.category.toLowerCase()
          const seller = (lot.seller || '').toLowerCase()
          if (!name.includes(q) && !cat.includes(q) && !seller.includes(q)) return false
        }
        return true
      })
      .sort((a, b) => sort === 'price_asc'
        ? a.pricePerItem - b.pricePerItem
        : sort === 'price_desc'
          ? b.pricePerItem - a.pricePerItem
          : 0)
  }, [lots, category, minPrice, maxPrice, minQty, maxQty, search, sort])

  const resetFilters = () => {
    setCategory('all')
    setMinPrice(''); setMaxPrice('')
    setMinQty(''); setMaxQty('')
    setSearchInput('')
    setSort('default')
  }

  const hasActiveFilters =
    category !== 'all' || minPrice !== '' || maxPrice !== '' ||
    minQty !== '' || maxQty !== '' || search !== '' || sort !== 'default'

  const isOwn = (lot) =>
    currentUser?.id && lot.sellerId && String(lot.sellerId) === String(currentUser.id)

  return (
    <div className="centralmarket-tab">
      <div className="centralmarket-header">
        <div>
          <h2 className="tab-title">{t('nav.centralMarket')}</h2>
          <p className="centralmarket-subtitle">{t('centralmarket.subtitle')}</p>
        </div>
        <button
          type="button"
          className="centralmarket-create-btn"
          onClick={openCreate}
        >
          <Plus size={16} /> {t('centralmarket.createLot')}
        </button>
      </div>

      {/* Верхняя управляющая полоса: [тогглер] [сортировка] [поиск] */}
      <div className="centralmarket-toolbar">
        <div className="centralmarket-toolbar-left">
          <button
            type="button"
            className={`centralmarket-filters-toggle ${filtersOpen ? 'is-open' : ''}`}
            onClick={() => setFiltersOpen(o => !o)}
            aria-expanded={filtersOpen}
            title={t('common.filter')}
          >
            <Filter size={14} />
            <ChevronDown
              size={14}
              className={`centralmarket-filters-chev ${filtersOpen ? 'rot' : ''}`}
            />
          </button>

          <button
            type="button"
            className={`centralmarket-sort-btn sort-${sort}`}
            onClick={cycleSort}
            title={t('common.sort')}
          >
            {sort === 'default' && (
              <>
                <ArrowUpDown size={14} />
                <span>{t('common.sort')}</span>
              </>
            )}
            {sort === 'price_asc' && (
              <>
                <ArrowUp size={14} />
                <span>{t('centralmarket.sortPriceAsc')}</span>
              </>
            )}
            {sort === 'price_desc' && (
              <>
                <ArrowDown size={14} />
                <span>{t('centralmarket.sortPriceDesc')}</span>
              </>
            )}
          </button>
        </div>

        <div className="centralmarket-toolbar-right">
          <div className="tx-search centralmarket-search">
            <Search size={16} className="tx-search-icon" />
            <input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder={t('centralmarket.searchPlaceholder')}
            />
          </div>
        </div>
      </div>

      {/* Выпадающая панель фильтров */}
      {filtersOpen && (
        <div className="centralmarket-filters">
          <div className="centralmarket-filters-body">
            <div className="centralmarket-filter">
              <span className="centralmarket-filter-label">
                <Filter size={12} /> {t('centralmarket.category')}
              </span>
              <div className="centralmarket-cat-pills">
                {CATEGORIES.map(c => (
                  <button
                    key={c.id}
                    type="button"
                    className={`tx-pill ${category === c.id ? 'active' : ''}`}
                    onClick={() => setCategory(c.id)}
                    title={c.id}
                  >
                    <span style={{ marginRight: 4 }}>{c.icon}</span>
                    {c.id === 'all' ? t('common.all') : t(`centralmarket.cat_${c.id}`, c.id)}
                  </button>
                ))}
              </div>
            </div>

            <div className="centralmarket-filters-row centralmarket-filters-row--numeric">
              <div className="centralmarket-filter centralmarket-filter--numeric">
                <span className="centralmarket-filter-label">
                  <DollarSign size={12} /> {t('common.price')}, {t('common.from')}–{t('common.to')}
                </span>
                <div className="centralmarket-num-pair">
                  <input
                    type="number" min="0" inputMode="numeric"
                    value={minPrice} onChange={e => setMinPrice(e.target.value)}
                    placeholder={t('common.from')} className="centralmarket-num-input"
                  />
                  <span className="centralmarket-num-dash">—</span>
                  <input
                    type="number" min="0" inputMode="numeric"
                    value={maxPrice} onChange={e => setMaxPrice(e.target.value)}
                    placeholder={t('common.to')} className="centralmarket-num-input"
                  />
                </div>
              </div>

              <div className="centralmarket-filter centralmarket-filter--numeric">
                <span className="centralmarket-filter-label">
                  <Hash size={12} /> {t('centralmarket.quantity')}, {t('common.from')}–{t('common.to')}
                </span>
                <div className="centralmarket-num-pair">
                  <input
                    type="number" min="0" inputMode="numeric"
                    value={minQty} onChange={e => setMinQty(e.target.value)}
                    placeholder={t('common.from')} className="centralmarket-num-input"
                  />
                  <span className="centralmarket-num-dash">—</span>
                  <input
                    type="number" min="0" inputMode="numeric"
                    value={maxQty} onChange={e => setMaxQty(e.target.value)}
                    placeholder={t('common.to')} className="centralmarket-num-input"
                  />
                </div>
              </div>

              {hasActiveFilters && (
                <button type="button" className="centralmarket-reset" onClick={resetFilters}>
                  <X size={14} /> {t('centralmarket.resetFilters')}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Список лотов */}
      <div className="centralmarket-lots">
        <div className="centralmarket-lots-header">
          <span>{t('centralmarket.lotsCount', { count: filtered.length })}</span>
        </div>
        {filtered.length === 0 ? (
          <div className="centralmarket-empty">
            <div className="centralmarket-empty-icon">🛒</div>
            <h3 className="centralmarket-empty-title">{t('centralmarket.emptyTitle')}</h3>
            <p className="centralmarket-empty-text">
              {lots.length === 0
                ? t('centralmarket.emptyTextEmpty')
                : t('centralmarket.emptyTextFiltered')}
            </p>
            {lots.length === 0 && (
              <button
                type="button"
                className="centralmarket-create-btn centralmarket-empty-cta"
                onClick={openCreate}
              >
                <Plus size={16} /> {t('centralmarket.createFirstLot')}
              </button>
            )}
          </div>
        ) : (
          <div className="centralmarket-lots-grid">
            {filtered.map(lot => {
              const item = findItemMeta(lot.itemId)
              const total = lot.qty * lot.pricePerItem
              const own = isOwn(lot)
              return (
                <div key={lot.id} className={`centralmarket-lot ${own ? 'is-own' : ''}`}>
                  <div className="centralmarket-lot-icon">
                    <span>{CATEGORIES.find(c => c.id === item.category)?.icon || '📦'}</span>
                  </div>

                  <div className="centralmarket-lot-main">
                    <div className="centralmarket-lot-name">{item.name}</div>
                    <div className="centralmarket-lot-meta">
                      <span className="centralmarket-lot-pill">
                        <Tag size={11} /> {t(`centralmarket.cat_${item.category}`, item.category)}
                      </span>
                      <span className="centralmarket-lot-pill">
                        <Hash size={11} /> ×{lot.qty}
                      </span>
                      <span className="centralmarket-lot-seller">
                        <User size={11} /> {lot.seller}
                      </span>
                    </div>
                  </div>

                  <div className="centralmarket-lot-price">
                    <div className="centralmarket-lot-price-unit">
                      <DollarSign size={12} /> {fmtMoney(lot.pricePerItem)}
                      <span className="centralmarket-lot-price-suffix">/ {t('centralmarket.perItem')}</span>
                    </div>
                    <div className="centralmarket-lot-price-total">
                      <Package size={11} /> {t('common.total')}: {fmtMoney(total)}
                    </div>
                  </div>

                  {own ? (
                    <div className="centralmarket-lot-actions">
                      <button
                        type="button"
                        className="centralmarket-lot-btn centralmarket-lot-btn--edit"
                        onClick={() => openEdit(lot)}
                      >
                        <Edit3 size={13} /> {t('centralmarket.edit')}
                      </button>
                      <button
                        type="button"
                        className="centralmarket-lot-btn centralmarket-lot-btn--danger"
                        onClick={() => setConfirmDelete(lot)}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ) : (
                    <div className="centralmarket-lot-actions">
                      <button
                        type="button"
                        className="centralmarket-lot-btn centralmarket-lot-btn--buy"
                        onClick={() => buyLot(lot)}
                      >
                        <ShoppingCart size={13} /> {t('common.buy')}
                        <span className="centralmarket-lot-btn-price">{fmtMoney(total)}</span>
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Модалка создания лота */}
      {createOpen && (
        <div className="modal-overlay" onClick={() => !createBusy && closeCreate()}>
          <div className="modal-content centralmarket-modal" onClick={e => e.stopPropagation()}>
            <button
              type="button"
              className="crypto-modal-close"
              onClick={closeCreate}
              disabled={createBusy}
            >
              <X size={18} />
            </button>
            <h3 className="centralmarket-modal-title">
              <Plus size={18} /> {t('createLot.title')}
            </h3>
            <p className="centralmarket-modal-subtitle">{t('createLot.subtitle')}</p>

            {/* Выбор источника предмета */}
            <div className="centralmarket-source-pills">
              <button
                type="button"
                className={`tx-pill ${createSource === 'inventory' ? 'active' : ''}`}
                onClick={() => { setCreateSource('inventory'); setCreateItemId('') }}
                disabled={createBusy}
              >
                <Package size={12} /> {t('createLot.sourceInventory')}
              </button>
              <button
                type="button"
                className={`tx-pill ${createSource === 'free' ? 'active' : ''}`}
                onClick={() => { setCreateSource('free'); setCreateItemId('') }}
                disabled={createBusy}
              >
                <Tag size={12} /> {t('createLot.sourceFree')}
              </button>
            </div>

            <label className="centralmarket-field">
              <span><Package size={13} /> {t('createLot.item')}</span>
              {createSource === 'inventory' ? (
                <select
                  value={createItemId}
                  onChange={e => setCreateItemId(e.target.value)}
                  disabled={createBusy || inventoryLoading}
                  className="centralmarket-select"
                >
                  <option value="" disabled>
                    {inventoryLoading
                      ? t('common.loading')
                      : inventoryOptions.length === 0
                        ? t('createLot.inventoryEmpty')
                        : t('createLot.itemPlaceholder')}
                  </option>
                  {inventoryOptions.map(o => (
                    <option key={o.id} value={o.slug || o.id}>
                      {o.name} · ×{o.qty} {t('centralmarket.inStock')}
                    </option>
                  ))}
                </select>
              ) : (
                <select
                  value={createItemId}
                  onChange={e => setCreateItemId(e.target.value)}
                  disabled={createBusy}
                  className="centralmarket-select"
                >
                  <option value="" disabled>{t('createLot.itemPlaceholder')}</option>
                  {ITEM_CATALOG.map(i => (
                    <option key={i.id} value={i.id}>
                      {i.name} · {t(`centralmarket.cat_${i.category}`, i.category)}
                    </option>
                  ))}
                </select>
              )}
            </label>

            <div className="centralmarket-field-row">
              <label className="centralmarket-field">
                <span><Hash size={13} /> {t('createLot.qty')}</span>
                <input
                  type="number" min="1" step="1"
                  value={createQty}
                  onChange={e => setCreateQty(e.target.value)}
                  disabled={createBusy}
                  className="centralmarket-input"
                />
              </label>
              <label className="centralmarket-field">
                <span><DollarSign size={13} /> {t('createLot.pricePerItem')}</span>
                <input
                  type="number" min="0" step="0.01"
                  value={createPrice}
                  onChange={e => setCreatePrice(e.target.value)}
                  disabled={createBusy}
                  placeholder="0.00"
                  className="centralmarket-input"
                />
              </label>
            </div>

            {createError && (
              <div className="transfer-feedback error">
                <AlertTriangle size={16} />
                <span>{createError}</span>
              </div>
            )}

            <div className="modal-buttons">
              <button type="button" className="stock-btn buy-btn" onClick={submitCreate} disabled={createBusy}>
                {createBusy ? t('bank.processing') : t('createLot.submit')}
              </button>
              <button type="button" className="stock-btn cancel-btn" onClick={closeCreate} disabled={createBusy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка редактирования лота */}
      {editLot && (
        <div className="modal-overlay" onClick={() => !editBusy && closeEdit()}>
          <div className="modal-content centralmarket-modal" onClick={e => e.stopPropagation()}>
            <button
              type="button"
              className="crypto-modal-close"
              onClick={closeEdit}
              disabled={editBusy}
            >
              <X size={18} />
            </button>
            <h3 className="centralmarket-modal-title">
              <Edit3 size={18} /> {t('centralmarket.editTitle')}
            </h3>
            <p className="centralmarket-modal-subtitle">
              {findItemMeta(editLot.itemId).name} · {t('common.total')}: {fmtMoney(editLot.qty * editLot.pricePerItem)}
            </p>

            <div className="centralmarket-field-row">
              <label className="centralmarket-field">
                <span><Hash size={13} /> {t('createLot.qty')}</span>
                <input
                  type="number" min="1" step="1"
                  value={editQty}
                  onChange={e => setEditQty(e.target.value)}
                  disabled={editBusy}
                  className="centralmarket-input"
                />
              </label>
              <label className="centralmarket-field">
                <span><DollarSign size={13} /> {t('createLot.pricePerItem')}</span>
                <input
                  type="number" min="0" step="0.01"
                  value={editPrice}
                  onChange={e => setEditPrice(e.target.value)}
                  disabled={editBusy}
                  className="centralmarket-input"
                />
              </label>
            </div>

            {editError && (
              <div className="transfer-feedback error">
                <AlertTriangle size={16} />
                <span>{editError}</span>
              </div>
            )}

            <div className="modal-buttons">
              <button type="button" className="stock-btn buy-btn" onClick={submitEdit} disabled={editBusy}>
                {editBusy ? t('bank.processing') : t('common.save')}
              </button>
              <button
                type="button"
                className="stock-btn cancel-btn centralmarket-btn-danger"
                onClick={() => { setConfirmDelete(editLot); closeEdit() }}
                disabled={editBusy}
              >
                <Trash2 size={13} /> {t('centralmarket.delete')}
              </button>
              <button type="button" className="stock-btn cancel-btn" onClick={closeEdit} disabled={editBusy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Подтверждение удаления */}
      {confirmDelete && (
        <div className="modal-overlay" onClick={() => setConfirmDelete(null)}>
          <div className="modal-content centralmarket-modal" onClick={e => e.stopPropagation()}>
            <h3 className="centralmarket-modal-title">
              <Trash2 size={18} /> {t('centralmarket.deleteTitle')}
            </h3>
            <p className="centralmarket-modal-subtitle">
              {t('centralmarket.deleteConfirm', { name: findItemMeta(confirmDelete.itemId).name })}
            </p>
            <div className="modal-buttons">
              <button
                type="button"
                className="stock-btn buy-btn centralmarket-btn-danger"
                onClick={() => doDelete(confirmDelete)}
              >
                {t('common.yes')}, {t('centralmarket.delete').toLowerCase()}
              </button>
              <button
                type="button"
                className="stock-btn cancel-btn"
                onClick={() => setConfirmDelete(null)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className={`centralmarket-toast ${toast.kind}`}>
          {toast.kind === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{toast.text}</span>
        </div>
      )}
    </div>
  )
}

export default CentralMarketTab
