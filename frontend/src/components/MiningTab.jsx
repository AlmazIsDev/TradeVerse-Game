import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchFarms, fetchMiningMarket, createFarm, deleteFarm, installComponent,
  uninstallComponent, startMining, stopMining, setFarmCoin, setOverclock,
  repairFarm, farmManager,
} from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import {
  Cpu, Play, Square, Trash2, Wrench, Zap, Thermometer, Gauge, Activity,
  Plus, X, AlertTriangle, Check, Bot, TrendingUp, HardDrive, Server,
} from 'lucide-react'

// Категории компонентов: обязательные помечены req.
const CATS = [
  { cat: 'motherboard', req: true }, { cat: 'cpu', req: true }, { cat: 'psu', req: true },
  { cat: 'ram', req: true }, { cat: 'ssd', req: true }, { cat: 'cooling', req: true },
  { cat: 'gpu', req: true, multi: true }, { cat: 'fan', multi: true },
  { cat: 'case' }, { cat: 'rack' }, { cat: 'ups' }, { cat: 'network' },
]
const SINGLE_ROLES = ['motherboard', 'cpu', 'psu', 'ram', 'ssd', 'cooling', 'case', 'rack', 'ups', 'network']

function MiningTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [farms, setFarms] = useState([])
  const [market, setMarket] = useState({ coins: [], best: null })
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [openId, setOpenId] = useState(null)

  const load = useCallback(async () => {
    try {
      const [f, m] = await Promise.all([fetchFarms(), fetchMiningMarket().catch(() => ({ coins: [], best: null }))])
      setFarms(f)
      setMarket(m)
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Realtime: события фермы приходят по WebSocket (Dashboard ретранслирует), + резервный поллинг.
  useEffect(() => {
    const onRt = (e) => { if (e.detail?.type === 'mining') load() }
    window.addEventListener('tv:realtime', onRt)
    const id = setInterval(load, 12000)
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
        <h2 className="tab-title">{t('nav.mining')}</h2>
        <div className="asset-card skeleton" style={{ height: 200 }} />
      </div>
    )
  }

  return (
    <div className="mining-tab">
      <div className="leaderboard-title-row">
        <Server size={22} className="icon" />
        <h2 className="tab-title">{t('nav.mining')}</h2>
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <div className="mining-create">
        <input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('mining.farmName')} maxLength={40} />
        <button className="asset-act upgrade" disabled={busy || newName.trim().length < 2}
          onClick={() => run(() => createFarm(newName.trim()), 'mining.created').then(() => setNewName(''))}>
          <Plus size={15} /> {t('mining.createFarm')}
        </button>
      </div>

      {farms.length === 0 && (
        <div className="empty-state"><span className="placeholder-icon"><Server size={48} /></span><p>{t('mining.noFarms')}</p></div>
      )}

      <div className="mining-farms">
        {farms.map(farm => {
          const s = farm.stats || {}
          const open = openId === farm.id
          const mining = farm.status === 'mining'
          return (
            <div key={farm.id} className={`mining-farm ${farm.status}`}>
              <div className="mining-farm-head" onClick={() => setOpenId(open ? null : farm.id)}>
                <div className="mfh-title">
                  <span className={`mining-status ${farm.status}`} />
                  <b>{farm.name}</b>
                  {farm.coin && <span className="mining-coin">{farm.coin}</span>}
                </div>
                <div className="mfh-quick">
                  <span title={t('mining.hashrate')}><Activity size={13} /> {formatCompact(s.hashrate)} H/s</span>
                  <span className={`temp ${tempClass(s.temperature)}`} title={t('mining.temp')}><Thermometer size={13} /> {s.temperature ?? '—'}°</span>
                  <span className={s.profitPerHour >= 0 ? 'up' : 'down'} title={t('mining.profitHr')}><TrendingUp size={13} /> {formatMoney(s.profitPerHour)}/ч</span>
                </div>
              </div>

              {open && (
                <div className="mining-farm-body">
                  {/* Мониторинг */}
                  <div className="mining-stats">
                    <div className="ms"><Activity size={15} /><span>{t('mining.hashrate')}</span><b>{formatCompact(s.hashrate)} H/s</b></div>
                    <div className="ms"><Zap size={15} /><span>{t('mining.power')}</span><b>{formatCompact(s.power)} W</b></div>
                    <div className="ms"><Thermometer size={15} /><span>{t('mining.temp')}</span><b className={tempClass(s.temperature)}>{s.temperature ?? '—'}°C</b></div>
                    <div className="ms"><Gauge size={15} /><span>{t('mining.condition')}</span><b>{farm.condition}%</b></div>
                    <div className="ms"><TrendingUp size={15} /><span>{t('mining.incomeHr')}</span><b className="up">${formatMoney(s.revenuePerHour)}</b></div>
                    <div className="ms"><Zap size={15} /><span>{t('mining.elecHr')}</span><b className="down">${formatMoney(s.electricityPerHour)}</b></div>
                    <div className="ms"><TrendingUp size={15} /><span>{t('mining.profitHr')}</span><b className={s.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(s.profitPerHour)}</b></div>
                    <div className="ms"><HardDrive size={15} /><span>{t('mining.earned')}</span><b>${formatCompact(farm.totalEarned)}</b></div>
                  </div>

                  {farm.missing?.length > 0 && (
                    <div className="mining-missing"><AlertTriangle size={14} /> {t('mining.missing')}: {farm.missing.map(m => t(`mining.comp.${m}`, m)).join(', ')}</div>
                  )}

                  {/* Управление добычей */}
                  <div className="mining-controls">
                    {mining ? (
                      <button className="asset-act sell" disabled={busy} onClick={() => run(() => stopMining(farm.id))}><Square size={14} /> {t('mining.stop')}</button>
                    ) : (
                      <button className="asset-act collect" disabled={busy || farm.missing?.length > 0} onClick={() => run(() => startMining(farm.id), 'mining.started')}><Play size={14} /> {t('mining.start')}</button>
                    )}
                    <select value={farm.coin || ''} onChange={e => run(() => setFarmCoin(farm.id, e.target.value))}>
                      <option value="">{t('mining.selectCoin')}</option>
                      {market.coins.map(c => <option key={c.symbol} value={c.symbol}>{c.symbol} · ${formatMoney(c.price)}</option>)}
                    </select>
                    {market.best && <span className="mining-best">{t('mining.aiBest')}: <b>{market.best}</b></span>}
                    <label className="mining-oc">
                      {t('mining.overclock')}: {farm.overclock}x
                      <input type="range" min="0.8" max="1.5" step="0.05" value={farm.overclock}
                        onChange={e => run(() => setOverclock(farm.id, Number(e.target.value)))} />
                    </label>
                    {farm.condition < 100 && (
                      <button className="asset-act" disabled={busy} onClick={() => run(() => repairFarm(farm.id), 'mining.repaired')}>
                        <Wrench size={14} /> {t('mining.repair')} (${formatMoney(farm.repairCost)})
                      </button>
                    )}
                    <button className="asset-act sell" disabled={busy} onClick={() => run(() => deleteFarm(farm.id))}><Trash2 size={14} /> {t('mining.dismantle')}</button>
                  </div>

                  {/* Управляющий */}
                  <div className="mining-manager">
                    <Bot size={16} />
                    {farm.manager?.type === 'ai' ? (
                      <>
                        <span>{t('mining.aiManager')} · {t('mining.level')} {farm.manager.level} · ${formatMoney(farm.manager.salary)}/ч</span>
                        <button className="asset-act upgrade" disabled={busy} onClick={() => run(() => farmManager(farm.id, 'upgrade'), 'mining.mgrUpgraded')}>{t('mining.upgrade')}</button>
                        <button className="asset-act" disabled={busy} onClick={() => run(() => farmManager(farm.id, 'fire'))}>{t('mining.fire')}</button>
                      </>
                    ) : (
                      <>
                        <span>{t('mining.playerManaged')}</span>
                        <button className="asset-act upgrade" disabled={busy} onClick={() => run(() => farmManager(farm.id, 'hire'), 'mining.mgrHired')}>{t('mining.hireAi')}</button>
                      </>
                    )}
                  </div>

                  {/* Сборка */}
                  <div className="mining-assembly">
                    <h4>{t('mining.assembly')}</h4>
                    <div className="mining-comps">
                      {CATS.map(({ cat, req, multi }) => {
                        const installed = multi
                          ? (cat === 'gpu' ? farm.components?.gpus : farm.components?.fans) || []
                          : (farm.components?.[cat] ? [farm.components[cat]] : [])
                        return (
                          <div key={cat} className={`mining-comp ${req ? 'req' : ''}`}>
                            <div className="mc-head">
                              <span>{t(`mining.comp.${cat}`, cat)}{req && ' *'}</span>
                              <button className="mc-add" disabled={busy} onClick={() => run(() => installComponent(farm.id, cat))}><Plus size={13} /></button>
                            </div>
                            {installed.map(it => (
                              <div key={it.hwId} className="mc-item">
                                <span>{it.name}</span>
                                <button className="mc-rm" disabled={busy} onClick={() => run(() => uninstallComponent(farm.id, it.hwId))}><X size={12} /></button>
                              </div>
                            ))}
                          </div>
                        )
                      })}
                    </div>
                    <p className="mining-hint">{t('mining.buyHint')}</p>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default MiningTab
