// MiningBulkView · массовые действия (запуск/остановка/ремонт) и авто-сборка
// ферм указанными комплектующими. Бэкенд: POST /api/mining/bulk/action и
// /api/mining/bulk/assemble (backend/mining.py). Открывается из MiningTab.
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchFarms, fetchMiningParts, fetchMiningMarket, fetchMiningHouses,
  bulkFarmAction, bulkAssemble,
} from '../services/api'
import { formatCompact, formatMoney } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import { toast } from './Toast'
import ConfirmDialog from './ConfirmDialog'
import {
  Bot, ChevronLeft, Play, Square, Wrench, Hammer, X, Droplet, Coins, Trash2, Check, Zap,
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
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState({})            // {farmId: true}
  const [parts, setParts] = useState({})
  const [busy, setBusy] = useState(false)
  const [asmOpen, setAsmOpen] = useState(false)
  // Прогресс длинных массовых операций: {label, done, total} — чанкинг по
  // 200 ферм даёт обновление каждые ~3-5 с вместо молчаливого ожидания.
  const [progress, setProgress] = useState(null)
  const [choice, setAsmChoice] = useState({})   // выбранные для сборки детали {cat: {hwId, qty}}
  const [coins, setCoins] = useState([])        // рынок монет для bulk-выбора монеты
  const [coinSel, setCoinSel] = useState('')
  const [coolantQty, setCoolantQty] = useState(1)
  const [ocValue, setOcValue] = useState(1)
  const [aiToggles, setAiToggles] = useState({ autoRepair: true, autoCoin: true, autoRestart: true })
  const [confirm, setConfirm] = useState(null)
  const [houses, setHouses] = useState([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [f, p, m, hs] = await Promise.all([
        fetchFarms(),
        fetchMiningParts().catch(() => ({})),
        fetchMiningMarket().catch(() => ({ coins: [], best: null })),
        fetchMiningHouses().catch(() => []),
      ])
      setFarms(f || [])
      setParts(p || {})
      setCoins(m?.coins || [])
      setHouses(hs || [])
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setLoading(false)
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

  // Группы домов: {group name|null -> farmIds}. null = дома без группы.
  const groups = useMemo(() => {
    const byId = Object.fromEntries((houses || []).map(h => [h.id, h.group || null]))
    const map = {}
    for (const f of farms) {
      const g = byId[f.houseId] ?? null
      const key = g || '__none__'
      if (!map[key]) map[key] = { key, name: g, farmIds: [] }
      map[key].farmIds.push(f.id)
    }
    return Object.values(map)
  }, [houses, farms])

  // Клик по группе: все фермы группы выбираются, повторный клик — снимает выбор.
  const selectGroup = (key) => {
    const g = groups.find(x => x.key === key)
    if (!g) return
    setSel(s => {
      const all = g.farmIds.every(id => s[id])
      const n = { ...s }
      for (const id of g.farmIds) {
        if (all) delete n[id]
        else n[id] = true
      }
      return n
    })
  }

  const runAction = async (action, extra) => {
    if (!selectedIds.length) return
    setBusy(true)
    const CH = 200
    let ok = 0, fail = 0, firstErr = null
    try {
      for (let i = 0; i < selectedIds.length; i += CH) {
        const chunk = selectedIds.slice(i, i + CH)
        setProgress({ label: t('mining.bulk.progressAction', 'Действие'), done: i, total: selectedIds.length })
        const res = await bulkFarmAction(action, chunk, extra)
        const fails = (res?.results || []).filter(r => !r.ok)
        ok += (res?.results?.length || 0) - fails.length
        fail += fails.length
        if (!firstErr && fails.length) firstErr = fails[0].error
      }
      if (fail) {
        toast(t('mining.bulk.partial', { ok, fail }) + (firstErr ? ' · ' + firstErr : ''), 'error')
      } else {
        toast(t('mining.bulk.done'))
      }
      await load()
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  // Выбор комплектующих: {cat: {hwId, qty}}. Для multi берутся ВСЕ свободные
  // экземпляры того же товара (как installMany в MiningTab), но не больше qty.
  const applyAsm = async (choice) => {
    // Инвентарь сгруппирован по товарам: бэкенд сам распределяет qty свободных
    // единиц товара по фермам (пул на категорию). Однорольной категории нужно
    // по детали на каждую несобранную ферму.
    const items = []
    for (const { cat, multi } of ASM_CATS) {
      const c = choice[cat]
      if (!c?.itemId) continue
      // qtyPerChunk: однорольной — 1 деталь на ферму чанка; multi — qty это
      // «шт. на ферму», умножается на фермы чанка = общий пул запроса
      // (неизрасходованный остаток пула не списывается).
      items.push({ category: cat, itemId: c.itemId, qty: multi ? (c.qty || 1) : 0,
        perFarm: multi ? (c.qty || 1) : 1, qtyPerChunk: !multi })
    }
    if (!items.length) { toast(t('mining.bulk.noPartsChosen', 'Комплектующие не выбраны'), 'error'); return }
    setBusy(true)
    setAsmOpen(false)
    const CH = 200
    const farmList = selectedUnassembled
    const total = farmList.length
    let assembled = 0
    let firstErr = null
    try {
      for (let i = 0; i < total; i += CH) {
        const chunk = farmList.slice(i, i + CH)
        setProgress({ label: t('mining.bulk.assembling', 'Сборка ферм'), done: i, total })
        const payload = items.map(it => ({ ...it, qty: it.qtyPerChunk ? chunk.length : it.qty * chunk.length }))
        const res = await bulkAssemble(chunk, payload)
        assembled += res?.assembled || 0
        if (!firstErr) {
          for (const r of res?.results || []) {
            if (r.error) { firstErr = r.error; break }
            // Категория пропущена (нет деталей/мест/зависимости) — показываем
            // первую причину, ферма при этом собирается частично.
            if (r.skipped) {
              const [cat, msg] = Object.entries(r.skipped)[0]
              firstErr = `${t(`mining.comp.${cat}`, cat)}: ${msg}`
              break
            }
          }
        }
        setProgress({ label: t('mining.bulk.assembling', 'Сборка ферм'), done: Math.min(i + CH, total), total })
      }
      toast(t('mining.bulk.assembled', { n: assembled }))
      if (firstErr) toast(firstErr, 'error')
      setAsmOpen(false)
      await load()
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  const allChecked = selectedIds.length === farms.length && farms.length > 0
  return (
    <div className="mining-tab">
      <div className="leaderboard-title-row">
        <Bot size={22} className="icon" />
        <h2 className="tab-title">{t('mining.bulk.title', 'Массовое управление фермами')}</h2>
        {progress && (
          <div className="mining-bulk-progressbar" role="status">
            <span className="mining-bulk-progressbar-label">{progress.label}</span>
            <div className="mining-bulk-progressbar-track">
              <div className="mining-bulk-progressbar-fill"
                style={{ width: `${progress.total ? Math.round((progress.done / progress.total) * 100) : 0}%` }} />
            </div>
            <span className="mining-bulk-progressbar-num">{progress.done} / {progress.total}</span>
          </div>
        )}
      </div>

      <div className="mining-nav-row" style={{ marginBottom: 'var(--spacing-md)' }}>
        <button className="asset-interact-btn" onClick={onBack}>
          <ChevronLeft size={16} /> {t('mining.toHouses', 'К домам')}
        </button>
      </div>

      <div className="mining-bulk-toolbar">
        <div className="mbt-pair">
          <div className="mbt-section">
            <span className="mbt-title">{t('mining.bulk.secActions', 'Действия')}</span>
            <div className="mbt-row">
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
            </div>
          </div>

          {groups.length > 0 && (
            <div className="mbt-section">
              <span className="mbt-title">{t('mining.bulk.groups', 'Группы домов')}</span>
              <div className="mbt-row">
                <select className="mslot-pick" disabled={busy} value="" onChange={e => { if (e.target.value) selectGroup(e.target.value) }}>
                  <option value="">{t('mining.bulk.selectGroup', '— выбрать группу —')}</option>
                  {groups.map(g => (
                    <option key={g.key} value={g.key}>
                      {g.name || t('mining.noGroup', 'Без группы')} ({g.farmIds.length})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>

        <div className="mbt-pair">
          <div className="mbt-section">
            <span className="mbt-title">{t('mining.bulk.secService', 'Обслуживание и ИИ-управляющий')}</span>
            <div className="mbt-row">
              <span className="mining-bulk-label">{t('mining.bulk.coolant', 'ОЖ')}</span>
              <input type="number" min="1" max="4" className="tx-input mining-bulk-qty" disabled={busy}
                value={coolantQty}
                onChange={e => setCoolantQty(Math.max(1, Math.min(4, parseInt(e.target.value, 10) || 1)))} />
              <button className="asset-act" disabled={busy || !selectedIds.length} onClick={() => runAction('coolant', { qty: coolantQty })}>
                <Droplet size={14} /> {t('mining.bulk.coolantAdd', 'Заправить')}
              </button>
              <span className="mbt-divider" />
              <span className="mbt-nowrap">
                <span className="mining-bulk-label">{t('mining.overclock', 'Разгон')}</span>
                <input type="number" min="0.8" max="1.5" step="0.05" className="tx-input mining-bulk-qty" disabled={busy}
                  value={ocValue}
                  onChange={e => setOcValue(Math.max(0.8, Math.min(1.5, parseFloat(e.target.value) || 1)))} />
                <button className="asset-act" disabled={busy || !selectedIds.length}
                  title={t('mining.bulk.overclockHint', 'Установить разгон на всех выбранных фермах. БП каждой фермы проверяется: где мощности не хватает, ферма не будет разогнана.')}
                  onClick={() => runAction('overclock', { value: ocValue })}>
                  <Zap size={14} /> {t('mining.bulk.overclock', 'Разгон')}
                </button>
              </span>
              <span className="mbt-divider" />
              <button className="asset-act upgrade" disabled={busy || !selectedIds.length} onClick={() => runAction('hire')}
                title={t('mining.bulk.hireHint', 'Нанять ИИ-управляющего на каждую выбранную ферму (120 000 $/ферма)')}>
                <Bot size={14} /> {t('mining.bulk.hire', 'Нанять ИИ')}
              </button>
              <button className="asset-act" disabled={busy || !selectedIds.length} onClick={() => runAction('upgrade')}
                title={t('mining.bulk.upgradeHint', 'Поднять ИИ-управляющего на уровень на каждой выбранной ферме')}>
                {t('mining.bulk.upgrade', 'Повысить ИИ')}
              </button>
              <button className="asset-act" disabled={busy || !selectedIds.length} onClick={() => runAction('fire')}
                title={t('mining.bulk.fireHint', 'Уволить ИИ-управляющего на выбранных фермах')}>
                {t('mining.bulk.fire', 'Уволить ИИ')}
              </button>
            </div>
          </div>

          <div className="mbt-section">
            <span className="mbt-title">{t('mining.bulk.secAuto', 'Автономность ИИ и монета')}</span>
            <div className="mbt-row">
              {[['autoRepair', 'mining.autoRepair'], ['autoCoin', 'mining.autoCoin'], ['autoRestart', 'mining.autoRestart']].map(([key, lk]) => (
                <label key={key} className="mining-bulk-toggle">
                  <input type="checkbox" disabled={busy} checked={aiToggles[key]}
                    onChange={e => setAiToggles(s => ({ ...s, [key]: e.target.checked }))} />
                  {t(lk)}
                </label>
              ))}
              <button className="asset-act" disabled={busy || !selectedIds.length}
                onClick={() => runAction('settings', { settings: aiToggles })}>
                <Check size={14} /> {t('mining.bulk.applySettings', 'Применить настройки')}
              </button>
              <span className="mbt-divider" />
              <span className="mbt-nowrap">
                <span className="mining-bulk-label">{t('mining.bulk.coin', 'Монета')}</span>
                <select className="mslot-pick" disabled={busy} value={coinSel}
                  onChange={e => setCoinSel(e.target.value)}>
                  <option value="">{t('mining.bulk.pickCoin', '— выбрать монету —')}</option>
                  {coins.map(c => <option key={c.symbol} value={c.symbol}>{c.symbol} · ${formatMoney(c.price)}</option>)}
                </select>
                <button className="asset-act" disabled={busy || !selectedIds.length || !coinSel}
                  onClick={() => runAction('coin', { symbol: coinSel })}>
                  <Coins size={14} /> {t('mining.bulk.setCoin', 'Задать монету')}
                </button>
              </span>
              <span className="mbt-divider" />
              <button className="asset-act mbt-danger" disabled={busy || !selectedIds.length}
                onClick={() => setConfirm({
                  title: t('mining.bulk.uninstallTitle', 'Снять всё железо'),
                  message: t('mining.bulk.uninstallMsg', 'С {{n}} ферм будет снято всё оборудование — оно вернётся в инвентарь, добыча остановится.').replace('{{n}}', String(selectedIds.length)),
                  onConfirm: () => runAction('uninstall'),
                })}>
                <Trash2 size={14} /> {t('mining.bulk.uninstall', 'Снять всё железо')}
              </button>
            </div>
          </div>
        </div>
      </div>

      {farms.length > 0 && (
        <div className="mining-bulk-listhead">
          <label className="mining-bulk-selectall">
            <input type="checkbox" checked={allChecked}
              onChange={e => setSel(e.target.checked ? Object.fromEntries(farms.map(f => [f.id, true])) : {})} />
            {t('mining.bulk.all', 'Все')}
          </label>
          <span className="mining-bulk-selected">
            {t('mining.bulk.selected', 'Выбрано')}: {selectedIds.length} / {farms.length}
          </span>
        </div>
      )}

      {loading ? (
        <div className="loading-state"><div className="spinner" /><p>{t('common.loading')}</p></div>
      ) : farms.length === 0 ? (
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
          <div className="modal-content asm-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setAsmOpen(false)}><X size={18} /></button>
            <h3><Hammer size={17} /> {t('mining.bulk.assemble', 'Авто-сборка')}</h3>
            <p className="modal-price">{t('mining.bulk.asmDesc', 'Выберите по одному товару на категорию — он ставится на каждую выбранную несобранную ферму. Чего не хватит или куда не влезет — категория пропустится, установленное останется (причина — в уведомлении). Порядок: корпус/стойка → мат. плата → процессор → ОЗУ → SSD → охлаждение → ИБП → сеть → БП → видеокарты → вентиляторы.')}</p>
            <div className="asm-grid">
              {ASM_CATS.map(({ cat, multi }) => {
                const chosen = choice[cat]?.itemId
                const cnt = (parts[cat] || []).find(p => p.itemId === chosen)?.count || 0
                const need = selectedUnassembled.length
                const mqty = choice[cat]?.qty || 1
                const hint = !chosen ? null
                  : multi
                    ? t('mining.bulk.asmMultiHint', { qty: mqty, free: cnt })
                      + (cnt < need * mqty ? ' — ' + t('mining.bulk.asmMultiShort', { need, total: need * mqty, free: cnt }) : '')
                    : t('mining.bulk.asmSingleHint', { need, free: cnt })
                const short = chosen && (multi ? cnt < need * mqty : cnt < need)
                return (
                  <div key={cat} className={`asm-row${chosen ? ' chosen' : ''}`}
                    title={t(`mining.bulk.tip.${cat}`, '')}>
                    <div className="asm-line">
                      <span className="asm-cat">{t(`mining.comp.${cat}`, cat)}</span>
                      <select className="mslot-pick" disabled={busy} value={chosen || ''}
                        onChange={e => {
                          const v = e.target.value
                          setAsmChoice(c => {
                            const n = { ...c }
                            if (!v) delete n[cat]
                            // multi: поле = шт. НА КАЖДУЮ ферму; дефолт — весь
                            // остаток поровну по фермам (лишнее останется в инвентаре)
                            else n[cat] = { itemId: v, qty: multi ? Math.max(1, Math.min(2000, Math.ceil(((parts[cat] || []).find(p => p.itemId === v)?.count || 1) / Math.max(1, need)))) : 1 }
                            return n
                          })
                        }}>
                        <option value="">{t('mining.bulk.notSet', '— не ставить —')}</option>
                        {(parts[cat] || []).map(p => (
                          <option key={p.itemId} value={p.itemId}>{hwName(p, t)}{partSpec(cat, p.specs, t)}{p.count > 1 ? ` (×${p.count})` : ''}</option>
                        ))}
                      </select>
                      {multi && chosen && (
                        <input type="number" min="1" max="2000" disabled={busy} className="tx-input asm-qty"
                          title={t('mining.bulk.asmPerFarmTitle', '')}
                          value={choice[cat]?.qty || 1}
                          onChange={e => setAsmChoice(c => ({ ...c, [cat]: { ...c[cat], qty: Math.max(1, Math.min(2000, parseInt(e.target.value, 10) || 1)) } }))} />
                      )}
                      {chosen && (
                        <button className="mslot-rm" onClick={() => setAsmChoice(c => { const n = { ...c }; delete n[cat]; return n })}><X size={12} /></button>
                      )}
                    </div>
                    {hint && <small className={`asm-hint${short ? ' short' : ''}`}>{hint}</small>}
                  </div>
                )
              })}
            </div>
            {choice['rack']?.itemId && choice['case']?.itemId && (
              <div className="asm-warn">{t('mining.bulk.asmCaseRackWarn', 'Стойка и корпус взаимоисключающие — выберите что-то одно. Стойка — общий пул слотов на несколько ферм.')}</div>
            )}
            <div className="asm-footer">
              <span className="asm-summary">
                {t('mining.bulk.asmSummary', { farms: selectedUnassembled.length, cats: ASM_CATS.filter(({ cat }) => choice[cat]?.itemId).length })}
              </span>
              <div className="modal-buttons">
                <button className="stock-btn buy-btn" disabled={busy} onClick={() => applyAsm(choice)}>{t('mining.bulk.apply', 'Собрать')}</button>
                <button className="stock-btn cancel-btn" onClick={() => setAsmOpen(false)}>{t('common.cancel')}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirm}
        busy={busy}
        title={confirm?.title}
        message={confirm?.message}
        onConfirm={() => { const h = confirm?.onConfirm; setConfirm(null); h?.() }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
