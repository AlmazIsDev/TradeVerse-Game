import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

// Поля транзакций: сортировка + точечный поиск вида "Категория: cityroof".
export const TX_FIELDS = [
  { key: 'timestamp', i18n: 'admin.txTime', fallback: 'Время' },
  { key: 'direction', i18n: 'admin.txDirection', fallback: 'Операция' },
  { key: 'label', i18n: 'admin.txLabel', fallback: 'Описание' },
  { key: 'category', i18n: 'admin.txCategory', fallback: 'Категория' },
  { key: 'username', i18n: 'admin.txUser', fallback: 'Игрок' },
  { key: 'amount', i18n: 'admin.txAmount', fallback: 'Сумма' },
  { key: 'balanceAfter', i18n: 'admin.txBalance', fallback: 'Баланс после' },
]

export default function TxFilters({ filters, setFilters, options, openMenu, setOpenMenu, toggleValue, setMode, setRange, sort, onSort }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  // Клик вне любого дропдауна закрывает его.
  useEffect(() => {
    const close = (e) => {
      if (!e.target.closest('.tx-filter-menu')) setOpenMenu(null)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [setOpenMenu])

  const fieldLabel = (key) => {
    const f = TX_FIELDS.find(x => x.key === key)
    return f ? t(f.i18n, f.fallback) : key
  }
  const activeCount = (key) =>
    (filters.include[key]?.length || 0) + (filters.exclude[key]?.length || 0)

  const MENUS = [
    { key: 'players', label: t('admin.txUser', 'Игрок'), options: (options.players || []).map(p => ({ value: p.id, label: p.username })) },
    { key: 'categories', label: t('admin.txCategory', 'Категория'), options: (options.categories || []).map(c => ({ value: c, label: c })) },
    { key: 'directions', label: t('admin.txDirection', 'Операция'), options: [{ value: 'income', label: t('admin.txIn', 'Доход') }, { value: 'expense', label: t('admin.txOut', 'Расход') }] },
    { key: 'sources', label: t('admin.txSource', 'Источник'), options: (options.sources || []).map(s => ({ value: s, label: s === 'user' ? t('admin.txSourceUser', 'Игроки') : s })) },
  ]
  const RANGES = [
    { key: 'timestamp', label: t('admin.txTime', 'Время'), fields: ['from', 'to'], type: 'datetime-local' },
    { key: 'amount', label: t('admin.txAmount', 'Сумма'), fields: ['min', 'max'], type: 'number' },
  ]

  return (
    <>
      {/* Активные фильтры чипами */}
      <div className="tx-chips">
        {Object.entries(filters.include).flatMap(([k, vals]) => (vals || []).map(v => ({ k, v, mode: 'include' }))).map(({ k, v, mode }) => (
          <button key={'i-' + k + v} className="tx-chip active" onClick={() => toggleValue(k, v, mode)}>
            {fieldLabel(k)}: {k === 'players' ? (options.players?.find(p => p.id === v)?.username || v) : v} ×
          </button>
        ))}
        {Object.entries(filters.exclude).flatMap(([k, vals]) => (vals || []).map(v => ({ k, v, mode: 'exclude' }))).map(({ k, v, mode }) => (
          <button key={'e-' + k + v} className="tx-chip active" onClick={() => toggleValue(k, v, mode)}>
            {fieldLabel(k)} ≠ {k === 'players' ? (options.players?.find(p => p.id === v)?.username || v) : v} ×
          </button>
        ))}
      </div>
      {/* Дропдауны мультивыбора */}
      {MENUS.map(menu => (
        <div key={menu.key} className="tx-filter-menu" style={{ position: 'relative' }}>
          <button className="tx-chip" onClick={() => setOpenMenu(openMenu === menu.key ? null : menu.key)}>
            {menu.label}{activeCount(menu.key) ? ` (${activeCount(menu.key)})` : ''}
          </button>
          {openMenu === menu.key && (
            <div className="tx-filter-dropdown" style={{ position: 'absolute', zIndex: 10, background: 'var(--bg-elev, #1e1f24)', border: '1px solid var(--border, #333)', borderRadius: 8, padding: 8, minWidth: 220, maxHeight: 320, overflowY: 'auto', marginTop: 4 }}>
              <div className="tx-filter-modes" style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                <button className={`tx-chip ${(filters.exclude[menu.key] ? 'exclude' : 'include') === 'include' ? 'active' : ''}`} onClick={() => setMode(menu.key, 'include')}>{t('admin.txModeInclude', 'Включить')}</button>
                <button className={`tx-chip ${(filters.exclude[menu.key] ? 'exclude' : 'include') === 'exclude' ? 'active' : ''}`} onClick={() => setMode(menu.key, 'exclude')}>{t('admin.txModeExclude', 'Кроме')}</button>
              </div>
              {menu.key !== 'directions' && (
                <input className="admin-input" style={{ width: '100%', marginBottom: 6 }} placeholder={t('admin.txSearchInList', 'Поиск в списке...')}
                  value={query} onChange={e => setQuery(e.target.value)} />
              )}
              {menu.options.filter(o => !query || o.label.toLowerCase().includes(query.toLowerCase())).map(opt => (
                <label key={opt.value} className="tx-filter-option" style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '2px 0' }}>
                  <input type="checkbox"
                    checked={(filters.exclude[menu.key] || filters.include[menu.key] || []).includes(opt.value)}
                    onChange={() => toggleValue(menu.key, opt.value, filters.exclude[menu.key] ? 'exclude' : 'include')} />
                  {opt.label}
                </label>
              ))}
            </div>
          )}
        </div>
      ))}
      {/* Диапазоны: Время и Сумма */}
      {RANGES.map(r => (
        <div key={r.key} className="tx-filter-menu" style={{ position: 'relative' }}>
          <button className={`tx-chip ${filters.ranges[r.key] ? 'active' : ''}`} onClick={() => setOpenMenu(openMenu === r.key ? null : r.key)}>
            {r.label}{filters.ranges[r.key] ? ' •' : ''}
          </button>
          {openMenu === r.key && (
            <div className="tx-filter-dropdown" style={{ position: 'absolute', zIndex: 10, background: 'var(--bg-elev, #1e1f24)', border: '1px solid var(--border, #333)', borderRadius: 8, padding: 8, marginTop: 4, display: 'flex', gap: 6 }}>
              <input className="admin-input" type={r.type} placeholder={t('admin.txRangeFrom', 'от')}
                value={(filters.ranges[r.key] || {})[r.fields[0]] ?? ''}
                onChange={e => setRange(r.key, r.fields[0], e.target.value)} />
              <input className="admin-input" type={r.type} placeholder={t('admin.txRangeTo', 'до')}
                value={(filters.ranges[r.key] || {})[r.fields[1]] ?? ''}
                onChange={e => setRange(r.key, r.fields[1], e.target.value)}/>
            </div>
          )}
        </div>
      ))}
      {/* Сортировка */}
      <select className="admin-input tx-sort-select" value={sort} onChange={e => onSort(e.target.value)}>
        {TX_FIELDS.map(f => <option key={f.key} value={f.key}>{t(f.i18n, f.fallback)}</option>)}
      </select>
    </>
  )
}
