import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatMoney } from './TransactionsPanel'
import {
  Search, Gpu, Microchip, CircuitBoard, MemoryStick, HardDrive, Zap, Fan,
  Server, Network, Box, Package, Wrench, Trash2, Info,
} from 'lucide-react'

// Иконка и порядок категории железа (остальные — в конец списка).
const CAT_ICONS = {
  gpu: Gpu, asic: Gpu, cpu: Microchip, motherboard: CircuitBoard,
  ram: MemoryStick, ssd: HardDrive, psu: Zap, cooling: Fan, fan: Fan,
  case: Box, rack: Server, ups: Zap, network: Network, supplies: Package,
}
const CAT_ORDER = Object.keys(CAT_ICONS)

// Краткие характеристики для чипов на карточке (единицы универсальны для RU/EN).
function specChips(hw, t) {
  const s = hw.specs || {}
  switch (hw.category) {
    case 'gpu': case 'asic':
      return [s.hashrate != null && `${s.hashrate} TH/s`, s.power != null && `${s.power} W`].filter(Boolean)
    case 'cpu':
      return [s.cores != null && t('units.cores', { count: s.cores }), s.multiplier != null && `×${s.multiplier}`].filter(Boolean)
    case 'motherboard':
      return [s.gpuSlots != null && `${s.gpuSlots} GPU`].filter(Boolean)
    case 'ram': case 'ssd':
      return [s.gb != null && `${s.gb} GB`].filter(Boolean)
    case 'psu': case 'ups':
      return [`${s.power ?? s.backup ?? 0} W`]
    case 'cooling': case 'fan':
      return [s.cooling != null && `${s.cooling} W`].filter(Boolean)
    case 'case': case 'rack':
      return [s.slots != null && `${s.slots} ${t('inventory.slotsShort')}`].filter(Boolean)
    case 'network':
      return [s.speed != null && `${s.speed} ${t('inventory.mbits')}`].filter(Boolean)
    default:
      return []
  }
}

/**
 * Список железа игрока (вкладка «Инвентарь» и одноимённая вкладка в модалке
 * имущества админа): чипы категорий, поиск, фильтр установлено/свободно,
 * сортировка и карточки с баром состояния. admin — режим админки: кнопки
 * «снять с фермы»/«удалить» (onUninstall/onDelete), у игрока список read-only.
 */
function HardwareInventory({ items = [], farmNameById = {}, admin = false, busy = false, onUninstall, onDelete, onSell }) {
  const { t } = useTranslation()
  const [cat, setCat] = useState('all')
  const [status, setStatus] = useState('all')   // all | free | installed
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('new')       // new | price | condition

  const cats = useMemo(() => {
    const present = new Set(items.map(h => h.category))
    return CAT_ORDER.filter(c => present.has(c)).concat([...present].filter(c => !CAT_ICONS[c]))
  }, [items])

  // Свободное железо приходит ГРУПАМИ по товару (qty > 1) — сервер не
  // отдаёт тысячи одинаковых единиц поштучно.
  const qtyOf = (h) => h.qty || 1
  const totalValue = items.reduce((s, h) => s + (h.purchasePrice || 0) * qtyOf(h), 0)
  const freeCount = items.filter(h => !h.farmId).reduce((s, h) => s + qtyOf(h), 0)

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    let out = items.filter(h =>
      (cat === 'all' || h.category === cat) &&
      (status === 'all' || (status === 'free' ? !h.farmId : !!h.farmId)) &&
      (!q || (h.name || '').toLowerCase().includes(q)))
    if (sort === 'price') out = [...out].sort((a, b) => (b.purchasePrice || 0) - (a.purchasePrice || 0))
    if (sort === 'condition') out = [...out].sort((a, b) => (a.condition ?? 100) - (b.condition ?? 100))
    return out
  }, [items, cat, status, query, sort])

  const farmNameOf = (h) => h.farmName || farmNameById[h.farmId] || null

  return (
    <div className="inv-panel">
      <div className="asset-summary">
        <div className="asset-summary-card"><span>{t('inventory.units')}</span><b>{items.reduce((s, h) => s + qtyOf(h), 0)}</b></div>
        <div className="asset-summary-card"><span>{t('inventory.totalCost')}</span><b>${formatMoney(totalValue)}</b></div>
        <div className="asset-summary-card"><span>{t('inventory.free')}</span><b>{freeCount}</b></div>
        <div className="asset-summary-card"><span>{t('inventory.installed')}</span><b>{items.reduce((s, h) => s + qtyOf(h), 0) - freeCount}</b></div>
      </div>

      <div className="inv-toolbar">
        <div className="market-cats">
          <button className={`tx-pill ${status === 'all' ? 'active' : ''}`} onClick={() => setStatus('all')}>{t('common.all')}</button>
          <button className={`tx-pill ${status === 'free' ? 'active' : ''}`} onClick={() => setStatus('free')}>{t('inventory.free')}</button>
          <button className={`tx-pill ${status === 'installed' ? 'active' : ''}`} onClick={() => setStatus('installed')}>{t('inventory.installed')}</button>
          <span className="inv-toolbar-sep" />
          <button className={`tx-pill ${cat === 'all' ? 'active' : ''}`} onClick={() => setCat('all')}>{t('inventory.catAll')}</button>
          {cats.map(c => {
            const Icon = CAT_ICONS[c] || Package
            return (
              <button key={c} className={`tx-pill ${cat === c ? 'active' : ''}`} onClick={() => setCat(c)}>
                <Icon size={13} /> {t(`mining.comp.${c}`, c)}
              </button>
            )
          })}
        </div>
        <div className="inv-toolbar-right">
          <div className="tx-search">
            <Search size={15} className="tx-search-icon" />
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder={t('inventory.search')} />
          </div>
          <select className="inv-sort" value={sort} onChange={e => setSort(e.target.value)}>
            <option value="new">{t('inventory.sortNew')}</option>
            <option value="price">{t('inventory.sortPrice')}</option>
            <option value="condition">{t('inventory.sortCondition')}</option>
          </select>
        </div>
      </div>

      {!admin && freeCount > 0 && (
        <div className="asset-hint" style={{ marginBottom: 'var(--spacing-md)' }}>
          <Info size={13} /> {t('inventory.sellHint')}
        </div>
      )}

      {list.length === 0 ? (
        <div className="empty-state">
          <span className="placeholder-icon">🔌</span>
          <p>{items.length === 0 ? t('inventory.empty') : t('inventory.notFound')}</p>
        </div>
      ) : (
        <div className="inv-grid">
          {list.map(h => {
            const Icon = CAT_ICONS[h.category] || Package
            const cond = Math.round(h.condition ?? 100)
            const condClass = cond >= 70 ? 'ok' : cond >= 35 ? 'mid' : 'low'
            const chips = specChips(h, t)
            const farmName = farmNameOf(h)
            return (
              <div key={h.id} className="inv-card">
                <div className="inv-card-head">
                  <span className="inv-icon"><Icon size={17} /></span>
                  <span className="inv-name" title={h.name}>{h.name}{qtyOf(h) > 1 && <b className="inv-qty"> ×{qtyOf(h)}</b>}</span>
                  <span className={`inv-badge ${h.farmId ? 'installed' : 'free'}`}>
                    {h.farmId ? t('inventory.installed') : t('inventory.free')}
                  </span>
                </div>
                {chips.length > 0 && (
                  <div className="inv-specs">{chips.map((c, i) => <span key={i} className="inv-chip">{c}</span>)}</div>
                )}
                <div className="inv-cond-row">
                  <div className="inv-cond"><div className={`inv-cond-fill ${condClass}`} style={{ width: `${cond}%` }} /></div>
                  <span className={`inv-cond-pct ${condClass}`}>{cond}%</span>
                </div>
                <div className="inv-meta">
                  {h.purchasePrice != null && <span>${formatMoney(h.purchasePrice)}{qtyOf(h) > 1 ? ` ×${qtyOf(h)}` : ''}</span>}
                  {h.farmId && <span className="inv-farm" title={farmName || ''}>{farmName || t('inventory.installedOn')}</span>}
                </div>
                {!admin && !h.farmId && onSell && (
                  <div className="user-actions inv-actions">
                    <button className="admin-btn admin-btn-danger" title={t('inventory.sellTitle')}
                      disabled={busy} onClick={() => onSell(h)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
                {admin && (
                  <div className="user-actions inv-actions">
                    {h.farmId && (
                      <button className="admin-btn" title={t('admin.property.hwUninstall')}
                        disabled={busy} onClick={() => onUninstall?.(h)}>
                        <Wrench size={14} />
                      </button>
                    )}
                    <button className="admin-btn admin-btn-danger" title={t('admin.property.delete')}
                      onClick={() => onDelete?.(h)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default HardwareInventory
