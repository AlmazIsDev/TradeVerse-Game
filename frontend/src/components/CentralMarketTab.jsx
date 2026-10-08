import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMarketLots, createMarketLot, updateMarketLot, cancelMarketLot, buyMarketLot,
  fetchMyAssets, fetchInventory,
} from '../services/api'
import { toast } from './Toast'
import { formatMoney } from './TransactionsPanel'
import ConfirmDialog from './ConfirmDialog'
import {
  Plus, Search, X, Filter, ArrowUpDown, ArrowUp, ArrowDown,
  Package, Tag, Hash, DollarSign, AlertTriangle, ChevronDown,
  Edit3, Trash2, ShoppingCart, User,
} from 'lucide-react'

// ─────────────────────────────────────────────────────────────────────────────
// CentralMarketTab · Центральный рынок — p2p торговля между игроками.
// Бэкенд: backend/market_lots.py. Два вида лотов:
//   kind:"asset"    — актив из «Моих активов» (дом/бизнес/авто/завод…), qty=1;
//   kind:"hardware" — железо из инвентаря магазина, qty ≤ свободных штук.
// Режим «свободный предмет» удалён: продавать можно только то, чем владеешь —
// сервер иначе отклонит лот.
// ─────────────────────────────────────────────────────────────────────────────

const KINDS = [
  { id: 'all', icon: '🗂️' },
  { id: 'asset', icon: '🏠' },
  { id: 'hardware', icon: '📦' },
]

function CentralMarketTab() {
  const { t } = useTranslation()

  // ── Состояние лотов и инвентаря ────────────────────────────────────────
  const [lots, setLots] = useState([])
  const [myAssets, setMyAssets] = useState([])      // [{id, name, type}]
  const [myHardware, setMyHardware] = useState([])  // [{itemId, name, count}]
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
  const [kind, setKind] = useState('all')
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

  // ── Загрузка лотов и инвентаря ────────────────────────────────────────
  const loadLots = useCallback(async () => {
    try {
      const data = await fetchMarketLots()
      setLots(Array.isArray(data?.lots) ? data.lots : [])
    } catch {
      setLots([])
    }
  }, [])

  const loadInventory = useCallback(async () => {
    setInventoryLoading(true)
    try {
      const [a, h] = await Promise.all([
        fetchMyAssets().catch(() => ({ assets: [] })),
        fetchInventory().catch(() => []),
      ])
      setMyAssets(Array.isArray(a?.assets) ? a.assets : [])
      setMyHardware(Array.isArray(h) ? h : [])
    } finally {
      setInventoryLoading(false)
    }
  }, [])

  useEffect(() => { loadLots(); loadInventory() }, [loadLots, loadInventory])

  // Realtime: обновляем лоты по WS-событиям рынка.
  useEffect(() => {
    const onRt = (e) => {
      if (['market_sold', 'balance', 'notification'].includes(e.detail?.type)) loadLots()
    }
    window.addEventListener('tv:realtime', onRt)
    return () => window.removeEventListener('tv:realtime', onRt)
  }, [loadLots])

  // ── Создание лота ──────────────────────────────────────────────────────
  const [createOpen, setCreateOpen] = useState(false)
  const [createKind, setCreateKind] = useState('asset')   // 'asset' | 'hardware'
  const [createItemId, setCreateItemId] = useState('')
  const [createQty, setCreateQty] = useState('1')
  const [createPrice, setCreatePrice] = useState('')
  const [createError, setCreateError] = useState(null)
  const [createBusy, setCreateBusy] = useState(false)

  const resetCreate = useCallback(() => {
    setCreateKind('asset')
    setCreateItemId('')
    setCreateQty('1')
    setCreatePrice('')
    setCreateError(null)
    setCreateBusy(false)
  }, [])
  const openCreate = useCallback(() => {
    resetCreate()
    setCreateOpen(true)
  }, [resetCreate])
  const closeCreate = useCallback(() => {
    setCreateOpen(false)
    resetCreate()
  }, [resetCreate])

  const submitCreate = useCallback(async () => {
    setCreateError(null)
    const qty = Number(createQty)
    const price = Number(createPrice)
    if (!createItemId) return setCreateError(t('createLot.errorItem'))
    if (!Number.isFinite(qty) || qty <= 0) return setCreateError(t('createLot.errorQty'))
    if (!Number.isFinite(price) || price <= 0) return setCreateError(t('createLot.errorPrice'))

    setCreateBusy(true)
    try {
      await createMarketLot({ kind: createKind, itemId: createItemId, qty, pricePerItem: price })
      toast(t('createLot.success'))
      closeCreate()
      await Promise.all([loadLots(), loadInventory()])
    } catch (e) {
      setCreateError(e?.message || t('common.error'))
    } finally {
      setCreateBusy(false)
    }
  }, [createKind, createItemId, createQty, createPrice, t, closeCreate, loadLots, loadInventory])

  // ── Редактирование/удаление лота ───────────────────────────────────────
  const [editLot, setEditLot] = useState(null)
  const [editQty, setEditQty] = useState('1')
  const [editPrice, setEditPrice] = useState('')
  const [editError, setEditError] = useState(null)
  const [editBusy, setEditBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

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
      await updateMarketLot(editLot.id, { qty, pricePerItem: price })
      toast(t('centralmarket.editSuccess'))
      closeEdit()
      await loadLots()
    } catch (e) {
      setEditError(e?.message || t('common.error'))
    } finally {
      setEditBusy(false)
    }
  }, [editLot, editQty, editPrice, t, closeEdit, loadLots])

  const doDelete = useCallback(async (lot) => {
    if (!lot || deleteBusy) return
    setDeleteBusy(true)
    try {
      await cancelMarketLot(lot.id)
      toast(t('centralmarket.deleteSuccess'))
      setConfirmDelete(null)
      await loadLots()
    } catch (e) {
      toast(e?.message || t('common.error'), 'error')
    } finally {
      setDeleteBusy(false)
    }
  }, [t, loadLots, deleteBusy])

  // ── Покупка лота ───────────────────────────────────────────────────────
  // Покупаем весь остаток лота сразу (сервер поддерживает и частичную).
  const [buyLot, setBuyLot] = useState(null)   // лот, ожидающий подтверждения
  const [buyBusy, setBuyBusy] = useState(false)
  const confirmBuy = useCallback(async () => {
    if (!buyLot) return
    setBuyBusy(true)
    try {
      const res = await buyMarketLot(buyLot.id, buyLot.qty)
      toast(t('centralmarket.buySuccess', { name: buyLot.name, qty: res?.qty ?? buyLot.qty }))
      setBuyLot(null)
      await loadLots()
    } catch (e) {
      toast(e?.message || t('common.error'), 'error')
      setBuyLot(null)
      await loadLots()
    } finally {
      setBuyBusy(false)
    }
  }, [buyLot, t, loadLots])

  // ── Фильтрация + сортировка ───────────────────────────────────────────
  const filtered = useMemo(() => {
    const minP = minPrice === '' ? -Infinity : Number(minPrice)
    const maxP = maxPrice === '' ? Infinity : Number(maxPrice)
    const minQ = minQty === '' ? -Infinity : Number(minQty)
    const maxQ = maxQty === '' ? Infinity : Number(maxQty)
    const q = search

    return lots
      .filter(lot => {
        if (kind !== 'all' && lot.kind !== kind) return false
        if (lot.pricePerItem < minP || lot.pricePerItem > maxP) return false
        if (lot.qty < minQ || lot.qty > maxQ) return false
        if (q) {
          const name = (lot.name || '').toLowerCase()
          const seller = (lot.seller || '').toLowerCase()
          if (!name.includes(q) && !seller.includes(q)) return false
        }
        return true
      })
      .sort((a, b) => sort === 'price_asc'
        ? a.pricePerItem - b.pricePerItem
        : sort === 'price_desc'
          ? b.pricePerItem - a.pricePerItem
          : 0)
  }, [lots, kind, minPrice, maxPrice, minQty, maxQty, search, sort])

  const resetFilters = () => {
    setKind('all')
    setMinPrice(''); setMaxPrice('')
    setMinQty(''); setMaxQty('')
    setSearchInput('')
    setSort('default')
  }

  const hasActiveFilters =
    kind !== 'all' || minPrice !== '' || maxPrice !== '' ||
    minQty !== '' || maxQty !== '' || search !== '' || sort !== 'default'

  const isOwn = (lot) =>
    currentUser?.id && lot.sellerId && String(lot.sellerId) === String(currentUser.id)

  const kindIcon = (k) => (k === 'asset' ? '🏠' : '📦')
  const kindLabel = (k) => t(`centralmarket.cat_${k}`, k === 'asset' ? 'Активы' : 'Железо')

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
                {KINDS.map(c => (
                  <button
                    key={c.id}
                    type="button"
                    className={`tx-pill ${kind === c.id ? 'active' : ''}`}
                    onClick={() => setKind(c.id)}
                    title={c.id}
                  >
                    <span style={{ marginRight: 4 }}>{c.icon}</span>
                    {c.id === 'all' ? t('common.all') : kindLabel(c.id)}
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
              const total = lot.qty * lot.pricePerItem
              const own = isOwn(lot)
              return (
                <div key={lot.id} className={`centralmarket-lot ${own ? 'is-own' : ''}`}>
                  <div className="centralmarket-lot-icon">
                    <span>{kindIcon(lot.kind)}</span>
                  </div>

                  <div className="centralmarket-lot-main">
                    <div className="centralmarket-lot-name">{lot.name}</div>
                    <div className="centralmarket-lot-meta">
                      <span className="centralmarket-lot-pill">
                        <Tag size={11} /> {kindLabel(lot.kind)}
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
                      <DollarSign size={12} /> {formatMoney(lot.pricePerItem)}
                      <span className="centralmarket-lot-price-suffix">/ {t('centralmarket.perItem')}</span>
                    </div>
                    <div className="centralmarket-lot-price-total">
                      <Package size={11} /> {t('common.total')}: {formatMoney(total)}
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
                        onClick={() => setBuyLot(lot)}
                      >
                        <ShoppingCart size={13} /> {t('common.buy')}
                        <span className="centralmarket-lot-btn-price">{formatMoney(total)}</span>
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

            {/* Тип товара: актив или железо */}
            <div className="centralmarket-source-pills">
              <button
                type="button"
                className={`tx-pill ${createKind === 'asset' ? 'active' : ''}`}
                onClick={() => { setCreateKind('asset'); setCreateItemId('') }}
                disabled={createBusy}
              >
                🏠 {kindLabel('asset')}
              </button>
              <button
                type="button"
                className={`tx-pill ${createKind === 'hardware' ? 'active' : ''}`}
                onClick={() => { setCreateKind('hardware'); setCreateItemId('') }}
                disabled={createBusy}
              >
                📦 {kindLabel('hardware')}
              </button>
            </div>

            <label className="centralmarket-field">
              <span><Package size={13} /> {t('createLot.item')}</span>
              {createKind === 'asset' ? (
                <select
                  value={createItemId}
                  onChange={e => setCreateItemId(e.target.value)}
                  disabled={createBusy || inventoryLoading}
                  className="centralmarket-select"
                >
                  <option value="" disabled>
                    {inventoryLoading
                      ? t('common.loading')
                      : myAssets.length === 0
                        ? t('createLot.inventoryEmpty')
                        : t('createLot.itemPlaceholder')}
                  </option>
                  {myAssets.map(a => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({kindLabel('asset')})
                    </option>
                  ))}
                </select>
              ) : (
                <select
                  value={createItemId}
                  onChange={e => setCreateItemId(e.target.value)}
                  disabled={createBusy || inventoryLoading}
                  className="centralmarket-select"
                >
                  <option value="" disabled>
                    {inventoryLoading
                      ? t('common.loading')
                      : myHardware.length === 0
                        ? t('createLot.inventoryEmpty')
                        : t('createLot.itemPlaceholder')}
                  </option>
                  {myHardware.map(h => (
                    <option key={h.itemId} value={h.itemId}>
                      {h.name} · ×{h.count} {t('centralmarket.inStock')}
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
                  value={createKind === 'asset' ? '1' : createQty}
                  onChange={e => setCreateQty(e.target.value)}
                  disabled={createBusy || createKind === 'asset'}
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
              {editLot.name} · {t('common.total')}: {formatMoney(editLot.qty * editLot.pricePerItem)}
            </p>

            <div className="centralmarket-field-row">
              <label className="centralmarket-field">
                <span><Hash size={13} /> {t('createLot.qty')}</span>
                <input
                  type="number" min="1" step="1"
                  value={editLot.kind === 'asset' ? '1' : editQty}
                  onChange={e => setEditQty(e.target.value)}
                  disabled={editBusy || editLot.kind === 'asset'}
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
      <ConfirmDialog
        open={!!confirmDelete}
        title={t('centralmarket.deleteTitle')}
        message={t('centralmarket.deleteConfirm', { name: confirmDelete?.name ?? '' })}
        confirmLabel={`${t('common.yes')}, ${t('centralmarket.delete').toLowerCase()}`}
        danger
        busy={deleteBusy}
        onConfirm={() => doDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />

      {/* Подтверждение покупки */}
      {buyLot && (
        <div className="modal-overlay" onClick={() => !buyBusy && setBuyLot(null)}>
          <div className="modal-content centralmarket-modal" onClick={e => e.stopPropagation()}>
            <h3 className="centralmarket-modal-title">
              <ShoppingCart size={18} /> {t('common.buy')}
            </h3>
            <p className="centralmarket-modal-subtitle">
              {buyLot.name} ×{buyLot.qty} · {t('common.total')}: {formatMoney(buyLot.qty * buyLot.pricePerItem)}
            </p>
            <div className="modal-buttons">
              <button type="button" className="stock-btn buy-btn" onClick={confirmBuy} disabled={buyBusy}>
                {buyBusy ? t('bank.processing') : t('common.yes')}
              </button>
              <button type="button" className="stock-btn cancel-btn" onClick={() => setBuyLot(null)} disabled={buyBusy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CentralMarketTab
