import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchFarms, fetchMiningMarket, fetchMiningParts, createFarm, deleteFarm, installComponent,
  uninstallComponent, startMining, stopMining, setFarmCoin, setOverclock,
  repairFarm, farmManager,
} from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import {
  Play, Square, Trash2, Wrench, Zap, Thermometer, Gauge, Activity,
  Plus, X, AlertTriangle, Check, Bot, TrendingUp, HardDrive, Server, Cpu,
} from 'lucide-react'

// Категории компонентов: обязательные помечены req; multi — можно несколько.
const CATS = [
  { cat: 'motherboard', req: true }, { cat: 'cpu', req: true }, { cat: 'psu', req: true },
  { cat: 'ram', req: true }, { cat: 'ssd', req: true }, { cat: 'cooling', req: true },
  { cat: 'gpu', req: true, multi: true }, { cat: 'fan', multi: true },
  { cat: 'case' }, { cat: 'rack' }, { cat: 'ups' }, { cat: 'network' },
]

// Краткая характеристика детали для выпадающего списка.
function partSpec(cat, s = {}) {
  if (cat === 'gpu') return s.hashrate ? ` · ${formatCompact(s.hashrate)} H/s` : ''
  if (cat === 'psu') return s.power ? ` · ${s.power}W` : ''
  if (cat === 'cooling' || cat === 'fan') return s.cooling ? ` · ${s.cooling}` : ''
  if (cat === 'cpu') return s.cores ? ` · ${s.cores} ядер` : ''
  if (cat === 'motherboard') return s.gpuSlots ? ` · ${s.gpuSlots} GPU` : ''
  if (cat === 'ram' || cat === 'ssd') return s.gb ? ` · ${s.gb} ГБ` : ''
  return ''
}

function MiningTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [farms, setFarms] = useState([])
  const [market, setMarket] = useState({ coins: [], best: null })
  const [parts, setParts] = useState({})
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [activeId, setActiveId] = useState(null)

  const load = useCallback(async () => {
    try {
      const [f, m, p] = await Promise.all([
        fetchFarms(),
        fetchMiningMarket().catch(() => ({ coins: [], best: null })),
        fetchMiningParts().catch(() => ({})),
      ])
      setFarms(f)
      setMarket(m)
      setParts(p)
      setActiveId(prev => (prev && f.some(x => x.id === prev)) ? prev : (f[0]?.id ?? null))
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Realtime: события фермы по WebSocket + резервный поллинг (реже, чтобы не грузить).
  useEffect(() => {
    const onRt = (e) => { if (e.detail?.type === 'mining') load() }
    window.addEventListener('tv:realtime', onRt)
    const id = setInterval(load, 20000)
    return () => { window.removeEventListener('tv:realtime', onRt); clearInterval(id) }
  }, [load])

  const flash = (text, type = 'success') => { setMsg({ text, type }); setTimeout(() => setMsg(null), 2400) }

  const run = async (fn, okKey) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res?.balance != null) onBalanceChange?.(res.balance)
      if (okKey) flash(t(okKey))
      await load()
      return res
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const tempClass = (temp) => (temp >= 85 ? 'crit' : temp >= 70 ? 'warn' : 'ok')

  if (loading) {
    return (
      <div className="mining-tab">
        <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>
        <div className="asset-card skeleton" style={{ height: 220 }} />
      </div>
    )
  }

  // ── Нет ферм: красивая карточка-приглашение ──
  if (farms.length === 0) {
    return (
      <div className="mining-tab">
        <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>
        {msg && (
          <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
            {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
          </div>
        )}
        <div className="crypto-onboard mining-onboard">
          <div className="crypto-onboard-icon"><Server size={56} /></div>
          <h3>{t('mining.onboardTitle')}</h3>
          <p>{t('mining.onboardDesc')}</p>
          <div className="mining-onboard-form">
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('mining.farmName')} maxLength={40} />
            <button className="crypto-open-btn" disabled={busy || newName.trim().length < 2}
              onClick={() => run(() => createFarm(newName.trim()), 'mining.created').then(() => setNewName(''))}>
              <Plus size={18} /> {t('mining.createFarm')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const farm = farms.find(f => f.id === activeId) || farms[0]
  const s = farm.stats || {}
  const mining = farm.status === 'mining'
  const assembled = !(farm.missing?.length > 0)

  return (
    <div className="mining-tab">
      <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      {/* Селектор ферм + добавление новой */}
      <div className="mining-farm-tabs">
        {farms.map(f => (
          <button key={f.id} className={`mining-farm-tab ${f.id === activeId ? 'active' : ''}`} onClick={() => setActiveId(f.id)}>
            <span className={`mining-status ${f.status}`} /> {f.name}
          </button>
        ))}
        <div className="mining-add-farm">
          <input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('mining.newFarm')} maxLength={40} />
          <button className="asset-act upgrade" disabled={busy || newName.trim().length < 2}
            onClick={() => run(() => createFarm(newName.trim()), 'mining.created').then(() => setNewName(''))}>
            <Plus size={15} />
          </button>
        </div>
      </div>

      {/* Панель управления фермой */}
      <div className={`mining-panel ${farm.status}`}>
        <div className="mining-panel-head">
          <div className="mph-title">
            <span className={`mining-status ${farm.status}`} />
            <h3>{farm.name}</h3>
            {farm.coin && <span className="mining-coin">{farm.coin}</span>}
            <span className={`mining-state-badge ${farm.status}`}>{t(`mining.state.${farm.status}`, farm.status)}</span>
          </div>
          <div className="mph-actions">
            {mining ? (
              <button className="asset-act sell" disabled={busy} onClick={() => run(() => stopMining(farm.id))}><Square size={14} /> {t('mining.stop')}</button>
            ) : (
              <button className="asset-act collect" disabled={busy || !assembled} onClick={() => run(() => startMining(farm.id), 'mining.started')}><Play size={14} /> {t('mining.start')}</button>
            )}
            <button className="asset-act sell" disabled={busy} onClick={() => run(() => deleteFarm(farm.id))}><Trash2 size={14} /> {t('mining.dismantle')}</button>
          </div>
        </div>

        {farm.missing?.length > 0 && (
          <div className="mining-missing"><AlertTriangle size={14} /> {t('mining.missing')}: {farm.missing.map(m => t(`mining.comp.${m}`, m)).join(', ')}</div>
        )}

        {/* Мониторинг — карточки */}
        <div className="mining-stat-cards">
          <div className="msc"><Activity size={16} /><span>{t('mining.hashrate')}</span><b>{formatCompact(s.hashrate)} H/s</b></div>
          <div className="msc"><Zap size={16} /><span>{t('mining.power')}</span><b>{formatCompact(s.power)} W</b></div>
          <div className="msc"><Thermometer size={16} /><span>{t('mining.temp')}</span><b className={tempClass(s.temperature)}>{s.temperature ?? '—'}°C</b></div>
          <div className="msc"><Gauge size={16} /><span>{t('mining.condition')}</span><b>{farm.condition}%</b></div>
          <div className="msc"><TrendingUp size={16} /><span>{t('mining.incomeHr')}</span><b className="up">${formatMoney(s.revenuePerHour)}</b></div>
          <div className="msc"><Zap size={16} /><span>{t('mining.elecHr')}</span><b className="down">${formatMoney(s.electricityPerHour)}</b></div>
          <div className="msc"><TrendingUp size={16} /><span>{t('mining.profitHr')}</span><b className={s.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(s.profitPerHour)}</b></div>
          <div className="msc"><HardDrive size={16} /><span>{t('mining.earned')}</span><b>${formatCompact(farm.totalEarned)}</b></div>
        </div>

        {/* Настройки добычи */}
        <div className="mining-panel-controls">
          <label className="mpc-field">
            <span>{t('mining.selectCoin')}</span>
            <select value={farm.coin || ''} onChange={e => run(() => setFarmCoin(farm.id, e.target.value))}>
              <option value="">{t('mining.selectCoin')}</option>
              {market.coins.map(c => <option key={c.symbol} value={c.symbol}>{c.symbol} · ${formatMoney(c.price)}</option>)}
            </select>
            {market.best && <small className="mining-best">{t('mining.aiBest')}: <b>{market.best}</b></small>}
          </label>
          <label className="mpc-field">
            <span>{t('mining.overclock')}: {farm.overclock}x</span>
            <input type="range" min="0.8" max="1.5" step="0.05" value={farm.overclock}
              onChange={e => run(() => setOverclock(farm.id, Number(e.target.value)))} />
          </label>
          {farm.condition < 100 && (
            <button className="asset-act" disabled={busy} onClick={() => run(() => repairFarm(farm.id), 'mining.repaired')}>
              <Wrench size={14} /> {t('mining.repair')} (${formatMoney(farm.repairCost)})
            </button>
          )}
        </div>

        {/* Управляющий */}
        <div className="mining-manager-card">
          <div className="mmc-icon"><Bot size={20} /></div>
          {farm.manager?.type === 'ai' ? (
            <>
              <div className="mmc-info">
                <b>{t('mining.aiManager')}</b>
                <span>{t('mining.level')} {farm.manager.level} · ${formatMoney(farm.manager.salary)}/ч</span>
              </div>
              <div className="mmc-actions">
                <button className="asset-act upgrade" disabled={busy} onClick={() => run(() => farmManager(farm.id, 'upgrade'), 'mining.mgrUpgraded')}>{t('mining.upgrade')}</button>
                <button className="asset-act" disabled={busy} onClick={() => run(() => farmManager(farm.id, 'fire'))}>{t('mining.fire')}</button>
              </div>
            </>
          ) : (
            <>
              <div className="mmc-info">
                <b>{t('mining.playerManaged')}</b>
                <span>{assembled ? t('mining.aiManagerHint') : t('mining.assembleForManager')}</span>
              </div>
              <div className="mmc-actions">
                <button className="asset-act upgrade" disabled={busy || !assembled} title={assembled ? '' : t('mining.assembleForManager')}
                  onClick={() => run(() => farmManager(farm.id, 'hire'), 'mining.mgrHired')}>{t('mining.hireAi')}</button>
              </div>
            </>
          )}
        </div>

        {/* Сборка — выбор комплектующих */}
        <div className="mining-assembly">
          <h4><Cpu size={16} /> {t('mining.assembly')}</h4>
          <div className="mining-slots">
            {CATS.map(({ cat, req, multi }) => {
              const installed = multi
                ? (cat === 'gpu' ? farm.components?.gpus : farm.components?.fans) || []
                : (farm.components?.[cat] ? [farm.components[cat]] : [])
              const avail = parts[cat] || []
              const canAdd = multi || installed.length === 0
              return (
                <div key={cat} className={`mining-slot ${req ? 'req' : ''} ${installed.length ? 'filled' : ''}`}>
                  <div className="mslot-head">
                    <span className="mslot-name">{t(`mining.comp.${cat}`, cat)}{req && <em> *</em>}</span>
                    {multi && installed.length > 0 && <span className="mslot-count">×{installed.length}</span>}
                  </div>
                  {installed.map(it => (
                    <div key={it.hwId} className="mslot-item">
                      <span>{it.name}</span>
                      <button className="mslot-rm" disabled={busy} onClick={() => run(() => uninstallComponent(farm.id, it.hwId))}><X size={12} /></button>
                    </div>
                  ))}
                  {canAdd && (
                    avail.length > 0 ? (
                      <select className="mslot-pick" disabled={busy} value=""
                        onChange={e => { if (e.target.value) run(() => installComponent(farm.id, cat, e.target.value)) }}>
                        <option value="">{t('mining.pickPart')}</option>
                        {avail.map(p => <option key={p.hwId} value={p.hwId}>{p.name}{partSpec(cat, p.specs)}</option>)}
                      </select>
                    ) : (
                      <span className="mslot-empty">{t('mining.noParts')}</span>
                    )
                  )}
                </div>
              )
            })}
          </div>
          <p className="mining-hint">{t('mining.buyHint')}</p>
        </div>
      </div>
    </div>
  )
}

export default MiningTab
