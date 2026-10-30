import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

// Поля транзакций: сортировка + точечный поиск вида "Категория: cityroof".
export const TX_FIELDS = [
  { key: 'timestamp', i18n: 'admin.txTime' },
  { key: 'direction', i18n: 'admin.txDirection' },
  { key: 'label', i18n: 'admin.txLabel' },
  { key: 'category', i18n: 'admin.txCategory' },
  { key: 'username', i18n: 'admin.txUser' },
  { key: 'amount', i18n: 'admin.txAmount' },
  { key: 'balanceAfter', i18n: 'admin.txBalance' },
]

export default function TxFilters({ filters, setFilters, options, openMenu, setOpenMenu, toggleValue, setMode, setRange, sort, onSort }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [wordsInput, setWordsInput] = useState('')
  const [wordsMode, setWordsMode] = useState('include')
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
    if (f) return t(f.i18n)
    if (key === 'auto') return t('admin.txAuto')
    if (key === 'words') return t('admin.txWords')
    return key
  }
  const activeCount = (key) =>
    (filters.include[key]?.length || 0) + (filters.exclude[key]?.length || 0)

  const MENUS = [
    { key: 'players', label: t('admin.txUser'), options: (options.players || []).map(p => ({ value: p.id, label: p.username })) },
    { key: 'categories', label: t('admin.txCategory'), options: (options.categories || []).map(c => ({ value: c, label: c })) },
    { key: 'directions', label: t('admin.txDirection'), options: [{ value: 'income', label: t('admin.txIn') }, { value: 'expense', label: t('admin.txOut') }] },
    { key: 'sources', label: t('admin.txSource'), options: (options.sources || []).map(s => ({ value: s, label: s === 'user' ? t('admin.txSourceUser') : s })) },
    { key: 'auto', label: t('admin.txAuto'), options: [
      { value: 'salary', label: t('admin.txAutoSalary') },
      { value: 'cityroof', label: t('admin.txAutoCityroof') },
      { value: 'mining', label: t('admin.txAutoMining') },
      { value: 'farm_expenses', label: t('admin.txAutoFarm') },
      { value: 'realestate', label: t('admin.txAutoRealestate') },
    ] },
  ]
  const RANGES = [
    { key: 'timestamp', label: t('admin.txTime'), fields: ['from', 'to'], type: 'datetime-local' },
    { key: 'amount', label: t('admin.txAmount'), fields: ['min', 'max'], type: 'number' },
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
                <button className={`tx-chip ${(filters.exclude[menu.key] ? 'exclude' : 'include') === 'include' ? 'active' : ''}`} onClick={() => setMode(menu.key, 'include')}>{t('admin.txModeInclude')}</button>
                <button className={`tx-chip ${(filters.exclude[menu.key] ? 'exclude' : 'include') === 'exclude' ? 'active' : ''}`} onClick={() => setMode(menu.key, 'exclude')}>{t('admin.txModeExclude')}</button>
              </div>
              {menu.key !== 'directions' && menu.key !== 'auto' && (
                <input className="admin-input" style={{ width: '100%', marginBottom: 6 }} placeholder={t('admin.txSearchInList')}
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
              <input className="admin-input" type={r.type} placeholder={t('admin.txRangeFrom')}
                value={(filters.ranges[r.key] || {})[r.fields[0]] ?? ''}
                onChange={e => setRange(r.key, r.fields[0], e.target.value)} />
              <input className="admin-input" type={r.type} placeholder={t('admin.txRangeTo')}
                value={(filters.ranges[r.key] || {})[r.fields[1]] ?? ''}
                onChange={e => setRange(r.key, r.fields[1], e.target.value)}/>
            </div>
          )}
        </div>
      ))}
      {/* Слова: включить/кроме — свободный ввод по описанию операции */}
      <div className="tx-filter-menu" style={{ position: 'relative' }}>
        <button className={`tx-chip ${((filters.include.words?.length || 0) + (filters.exclude.words?.length || 0)) ? 'active' : ''}`}
          onClick={() => setOpenMenu(openMenu === 'words' ? null : 'words')}>
          {t('admin.txWords')}{((filters.include.words?.length || 0) + (filters.exclude.words?.length || 0))
            ? ` (${(filters.include.words?.length || 0) + (filters.exclude.words?.length || 0)})` : ''}
        </button>
        {openMenu === 'words' && (
          <div className="tx-filter-dropdown" style={{ position: 'absolute', zIndex: 10, background: 'var(--bg-elev, #1e1f24)', border: '1px solid var(--border, #333)', borderRadius: 8, padding: 8, marginTop: 4, minWidth: 240 }}>
            <div className="tx-filter-modes" style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
              <button className={`tx-chip ${wordsMode === 'include' ? 'active' : ''}`} onClick={() => setWordsMode('include')}>{t('admin.txModeInclude')}</button>
              <button className={`tx-chip ${wordsMode === 'exclude' ? 'active' : ''}`} onClick={() => setWordsMode('exclude')}>{t('admin.txModeExclude')}</button>
            </div>
            <input className="admin-input" style={{ width: '100%' }} autoFocus
              placeholder={t('admin.txWordsPh')} value={wordsInput}
              onChange={e => setWordsInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && wordsInput.trim()) {
                  toggleValue('words', wordsInput.trim(), wordsMode)
                  setWordsInput('')
                }
              }} />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
              {(filters.include.words || []).map(w => (
                <button key={'iw-' + w} className="tx-chip active" onClick={() => toggleValue('words', w, 'include')}>{w} ×</button>
              ))}
              {(filters.exclude.words || []).map(w => (
                <button key={'ew-' + w} className="tx-chip active" onClick={() => toggleValue('words', w, 'exclude')}>≠ {w} ×</button>
              ))}
            </div>
          </div>
        )}
      </div>
      {/* Сортировка */}
      <select className="admin-input tx-sort-select" value={sort} onChange={e => onSort(e.target.value)}>
        {TX_FIELDS.map(f => <option key={f.key} value={f.key}>{t(f.i18n)}</option>)}
      </select>
    </>
  )
}
