// MiningBulkView · массовое управление майнинг-фермами.
// Два режима: массовые действия (запуск/остановка/ремонт) над выбранными
// фермами и авто-сборка нескольких ферм указанными комплектующими.
// Бэкенд: POST /api/mining/bulk/action и /api/mining/bulk/assemble
// (backend/mining.py). Открывается с экрана выбора дома в MiningTab.
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchFarms, fetchMiningParts, bulkFarmAction, bulkAssemble,
} from '../services/api'
import { formatCompact } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import { toast } from './Toast'
import {
  Bot, ChevronLeft, Play, Square, Wrench, Hammer, X,
} from 'lucide-react'

// Категории для авто-сборки: порядок = порядок установки в ферму.
const ASM_CATS = [
  { cat: 'rack', single: true }, { cat: 'case', single: true },
  { cat: 'motherboard', single: true }, { cat: 'cpu', single: true },
  { cat: 'ram', single: true }, { cat: 'ssd', single: true },
  { cat: 'cooling', single: true }, { cat: 'ups', single: true },
  { cat: 'network', single: true },
  { cat: 'psu', multi: true }, { cat: 'gpu', multi: true }, { cat: 'fan', multi: true },
]

// Краткая характеристика детали (копия partSpec из MiningTab).
function partSpec(cat, s = {}, t) {
  if (cat === 'gpu') return s.hashrate ? ` · ${formatCompact(s.hashrate)} H/s` : ''
  if (cat === 'psu') return s.power ? ` · ${s.power}W` : ''
  if (cat === 'cooling' || cat === 'fan') return s.cooling ? ` · ${s.cooling}` : ''
  if (cat === 'cpu') return s.cores ? ` · ${t('units.cores', { count: s.cores })}` : ''
  if (cat === 'motherboard') return s.gpuSlots ? ` · ${s.gpuSlots} GPU` : ''
  if (cat === 'ram' || cat === 'ssd') return s.gb ? ` · ${s.gb} ${t('units.gb')}` : ''
  return ''
}

export default function MiningBulkView({ onBack }) {
  const { t } = useTranslation()
  const [farms, setFarms] = useState([])
  const [sel, setSel] = useState({})            // {farmId: true}
  const [parts, setParts] = useState({})
  const [busy, setBusy] = useState(false)
  const [asmOpen, setAsmOpen] = useState(false)
  const [choice, setAsmChoice] = useState({})   // выбранные для сборки детали {cat: {hwId, qty}}

  const load = useCallback(async () => {
    try {
      const [f, p] = await Promise.all([
        fetchFarms(),
        fetchMiningParts().catch(() => ({})),
      ])
      setFarms(f || [])
      setParts(p || {})
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    }
  }, [t])

  useEffect(() => { load() }, [load])

  const selectedIds = useMemo(
    () => farms.filter(f => sel[f.id]).map(f => f.id),
    [farms, sel],
  )
  const selectedUnassembled = useMemo(
    () => farms.filter(f => sel[f.id] && f.missing?.length > 0).map(f => f.id),
    [farms, sel],
  )

  const runAction = async (action) => {
    if (!selectedIds.length) return
    setBusy(true)
    try {
      const res = await bulkFarmAction(action, selectedIds)
      const fails = (res?.results || []).filter(r => !r.ok)
      if (fails.length) {
        toast(t('mining.bulk.partial', { ok: res.results.length - fails.length, fail: fails.length }) + ' · ' + fails[0].error, 'error')
      } else {
        toast(t('mining.bulk.done'))
      }
      await load()
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setBusy(false)
    }
  }

  // ── Авто-сборка ───────────────────────────────────────────────────────────
  // Выбор комплектующих: {cat: {hwId, qty}}. Для multi берутся ВСЕ свободные
  // экземпляры того же товара (как installMany в MiningTab), но не больше qty.
  const applyAsm = async (choice) => {
    const items = []
    for (const { cat, multi } of ASM_CATS) {
      const c = choice[cat]
      if (!c?.hwId) continue
      const avail = parts[cat] || []
      if (multi) {
        const picked = avail.find(p => p.hwId === c.hwId)
        if (!picked) continue
        const key = hwName(picked, t) + partSpec(cat, picked.specs, t)
        const ids = avail.filter(p => hwName(p, t) + partSpec(cat, p.specs, t) === key)
          .slice(0, c.qty || 1).map(p => p.hwId)
        if (ids.length) items.push({ category: cat, hwIds: ids })
      } else {
        items.push({ category: cat, hwIds: [c.hwId] })
      }
    }
    if (!items.length) { toast(t('mining.bulk.noPartsChosen', 'Комплектующие не выбраны'), 'error'); return }
    setBusy(true)
    try {
      const res = await bulkAssemble(selectedUnassembled.length ? selectedUnassembled : [], items)
      const ok = res?.assembled || 0
      const fails = (res?.results || []).filter(r => !r.ok)
      if (ok === 0 && fails.length) {
        toast(fails[0].error, 'error')
      } else {
        toast(t('mining.bulk.assembled', { n: ok }))
        if (fails.length) toast(fails[0].error, 'error')
      }
      setAsmOpen(false)
      await load()
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setBusy(false)
    }
  }

  // ── Рендер ───────────────────────────────────────────────────────────────
  const allChecked = selectedIds.length === farms.length && farms.length > 0
  return (
    <div className="mining-tab">
      <div className="leaderboard-title-row">
        <Bot size={22} className="icon" />
        <h2 className="tab-title">{t('mining.bulk.title', 'Массовое управление фермами')}</h2>
      </div>

      <div className="mining-nav-row" style={{ marginBottom: 'var(--spacing-md)' }}>
        <button className="asset-interact-btn" onClick={onBack}>
          <ChevronLeft size={16} /> {t('mining.toHouses', 'К домам')}
        </button>
      </div>

      <div className="market-cats" style={{ marginBottom: 'var(--spacing-md)' }}>
        <button className="asset-act upgrade" disabled={busy || !selectedIds.length} onClick={() => runAction('start')}>
          <Play size={14} /> {t('mining.bulk.start', 'Запустить')}
        </button>
        <button className="asset-act" disabled={busy || !selectedIds.length} onClick={() => runAction('stop')}>
          <Square size={14} /> {t('mining.bulk.stop', 'Остановить')}
        </button>
        <button className="asset-act" disabled={busy || !selectedIds.length} onClick={() => runAction('repair')}>
          <Wrench size={14} /> {t('mining.bulk.repair', 'Починить')}
        </button>
        <button className="asset-act upgrade" disabled={busy || !selectedUnassembled.length}
          onClick={() => setAsmOpen(true)}
          title={t('mining.bulk.asmHint', 'Собрать выбранные несобранные фермы указанными деталями')}>
          <Hammer size={14} /> {t('mining.bulk.assemble', 'Авто-сборка')}
        </button>
        <label className="mining-bulk-selectall" style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={allChecked}
            onChange={e => setSel(e.target.checked ? Object.fromEntries(farms.map(f => [f.id, true])) : {})} />
          {t('mining.bulk.all', 'Все')}
        </label>
      </div>

      {farms.length === 0 ? (
        <div className="empty-state"><p>{t('mining.bulk.noFarms', 'Ферм пока нет — создайте их в подвалах домов.')}</p></div>
      ) : (
        <div className="mining-bulk-list">
          {farms.map(f => (
            <label key={f.id} className="mining-bulk-row">
              <input type="checkbox" checked={!!sel[f.id]} onChange={e => setSel(s => ({ ...s, [f.id]: e.target.checked }))} />
              <span className="mining-bulk-name">{f.name}</span>
              <span className={`mining-status ${f.status}`} />
              <span className="mining-bulk-state">{t(`mining.state.${f.status || 'idle'}`, f.status || 'idle')}</span>
              <span className="mining-bulk-meta">
                {f.missing?.length > 0
                  ? t('mining.missing') + ': ' + f.missing.map(m => t(`mining.comp.${m}`, m)).join(', ')
                  : `${t('mining.hashrate')}: ${formatCompact(f.stats?.hashrate || 0)} H/s · ${t('mining.condition')}: ${f.condition}%`}
              </span>
            </label>
          ))}
        </div>
      )}

      {asmOpen && (
        <div className="modal-overlay" onClick={() => !busy && setAsmOpen(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setAsmOpen(false)}><X size={18} /></button>
            <h3><Hammer size={17} /> {t('mining.bulk.assemble', 'Авто-сборка')}</h3>
            <p className="modal-price">{t('mining.bulk.asmDesc', 'Детали ставятся в выбранные несобранные фермы по очереди; закончатся — сборка остановится.')}</p>
            {ASM_CATS.map(({ cat, multi, single }) => (
              <div key={cat} className="mslot-pick-row" style={{ margin: '6px 0' }}>
                <label className="mpc-field" style={{ flex: 1 }}>
                  <span>{t(`mining.comp.${cat}`, cat)}</span>
                  <select className="mslot-pick" disabled={busy} value=""
                    onChange={e => { if (e.target.value) setAsmChoice(c => ({ ...c, [cat]: { hwId: e.target.value, qty: 1 } })) }}>
                    <option value="">{choice[cat]?.hwId
                      ? hwName((parts[cat] || []).find(p => p.hwId === choice[cat].hwId) || {}, t)
                      : t('mining.bulk.notSet', '— не ставить —')}</option>
                    {(parts[cat] || []).map(p => (
                      <option key={p.hwId} value={p.hwId}>{hwName(p, t)}{partSpec(cat, p.specs, t)}</option>
                    ))}
                  </select>
                </label>
                {multi && (
                  <input type="number" min="1" max="50" disabled={busy} className="tx-input"
                    value={choice[cat]?.qty || 1}
                    onChange={e => setAsmChoice(c => ({ ...c, [cat]: { ...c[cat], qty: Math.max(1, Math.min(50, parseInt(e.target.value, 10) || 1)) } }))} />
                )}
                {choice[cat]?.hwId && (
                  <button className="mslot-rm" onClick={() => setAsmChoice(c => { const n = { ...c }; delete n[cat]; return n })}><X size={12} /></button>
                )}
              </div>
              )
            )}
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy} onClick={() => applyAsm(choice)}>{t('mining.bulk.apply', 'Собрать')}</button>
              <button className="stock-btn cancel-btn" onClick={() => setAsmOpen(false)}>{t('common.cancel')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
