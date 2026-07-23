import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchFarms, fetchMiningMarket, fetchMiningParts, createFarm, deleteFarm, installComponent,
  installComponentsBatch,
  uninstallComponent, startMining, stopMining, setFarmCoin, setOverclock,
  repairFarm, farmManager,
} from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import ConfirmDialog from './ConfirmDialog'
import {
  Play, Square, Trash2, Wrench, Zap, Thermometer, Gauge, Activity,
  Plus, X, AlertTriangle, Check, Bot, TrendingUp, HardDrive, Server, Cpu,
} from 'lucide-react'

// Категории компонентов: обязательные помечены req; multi — можно несколько.
const CATS = [
  { cat: 'motherboard', req: true }, { cat: 'cpu', req: true }, { cat: 'psu', req: true, multi: true },
  { cat: 'ram', req: true }, { cat: 'ssd', req: true }, { cat: 'cooling', req: true },
  { cat: 'gpu', req: true, multi: true }, { cat: 'fan', multi: true },
  { cat: 'case' }, { cat: 'rack' }, { cat: 'ups' }, { cat: 'network' },
]

// Краткая характеристика детали для выпадающего списка.
function partSpec(cat, s = {}, t) {
  if (cat === 'gpu') return s.hashrate ? ` · ${formatCompact(s.hashrate)} H/s` : ''
  if (cat === 'psu') return s.power ? ` · ${s.power}W` : ''
  if (cat === 'cooling' || cat === 'fan') return s.cooling ? ` · ${s.cooling}` : ''
  if (cat === 'cpu') return s.cores ? ` · ${t('units.cores', { count: s.cores })}` : ''
  if (cat === 'motherboard') return s.gpuSlots ? ` · ${s.gpuSlots} GPU` : ''
  if (cat === 'ram' || cat === 'ssd') return s.gb ? ` · ${s.gb} ${t('units.gb')}` : ''
  return ''
}

// Ползунок разгона: во время перетаскивания меняет только локальное значение
// (без сети), а коммитит на сервер один раз — при отпускании. Иначе каждый шаг
// перетаскивания слал бы POST + полный reload вкладки (шторм запросов, гонки).
function OverclockSlider({ value, disabled, label, onCommit }) {
  const [local, setLocal] = useState(value)
  // Синхронизируемся с внешним значением, когда пользователь не тянет ползунок.
  useEffect(() => { setLocal(value) }, [value])
  const commit = () => { if (local !== value) onCommit(local) }
  return (
    <label className="mpc-field">
      <span>{label}: {local}x</span>
      <input
        type="range" min="0.8" max="1.5" step="0.05" value={local} disabled={disabled}
        onChange={e => setLocal(Number(e.target.value))}
        onMouseUp={commit}
        onTouchEnd={commit}
        onKeyUp={commit}
      />
    </label>
  )
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
  const [confirm, setConfirm] = useState(null)   // { title, message, danger, onConfirm }
  const [cartQty, setCartQty] = useState({}) // `${cat}::${modelKey}` -> сколько ставить оптом (gpu/fan)
  const [openAdd, setOpenAdd] = useState({}) // `${farmId}::${cat}` -> раскрыт ли выбор детали (иначе зелёная «+»)

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

  // Массовая установка одинаковых деталей (GPU/вентиляторы): один batch-запрос,
  // сервер валидирует и ставит каждую по очереди.
  const installMany = async (cat, hwIds) => {
    setBusy(true)
    try {
      const res = await installComponentsBatch(farm.id, hwIds.map(hwId => ({ category: cat, hwId })))
      if (res?.error) flash(res.error, 'error')
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
      await load()
    }
  }

  // Массовое снятие одинаковых деталей: снимаем по одной (сервер валидирует каждую).
  const removeMany = async (hwIds) => {
    setBusy(true)
    try {
      for (const hwId of hwIds) await uninstallComponent(farm.id, hwId)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
      await load()
    }
  }

  const askCreate = () => setConfirm({
    title: t('mining.createFarm'),
    message: t('confirm.createFarm', { name: newName.trim() }),
    onConfirm: () => run(() => createFarm(newName.trim()), 'mining.created').then(() => setNewName('')),
  })

  const askDismantle = (f) => setConfirm({
    danger: true,
    title: t('mining.dismantle'),
    message: t('confirm.dismantle', { name: f.name }),
    onConfirm: () => run(() => deleteFarm(f.id)),
  })

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
              onClick={askCreate}>
              <Plus size={18} /> {t('mining.createFarm')}
            </button>
          </div>
        </div>
        <ConfirmDialog
          open={!!confirm}
          danger={confirm?.danger}
          busy={busy}
          title={confirm?.title}
          message={confirm?.message}
          onConfirm={() => { confirm?.onConfirm?.(); setConfirm(null) }}
          onCancel={() => setConfirm(null)}
        />
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
            onClick={askCreate}>
            <Plus size={15} />
          </button>
        </div>
      </div>

      {/* Панель управления фермой + правая статистика успехов */}
      <div className="mining-body">
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
            <button className="asset-act sell" disabled={busy} onClick={() => askDismantle(farm)}><Trash2 size={14} /> {t('mining.dismantle')}</button>
          </div>
        </div>

        {farm.missing?.length > 0 && (
          <div className="mining-missing"><AlertTriangle size={14} /> {t('mining.missing')}: {farm.missing.map(m => t(`mining.comp.${m}`, m)).join(', ')}</div>
        )}

        {/* Мониторинг — только для собранной фермы (иначе показатели не считаются). */}
        {assembled ? (
          <>
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
          <div className="mining-eff-row">
            {['gpu', 'ram', 'ssd', 'network'].map(k => (
              <span key={k} className={`mining-eff-badge ${(s.efficiency?.[k] ?? 1) < 0.5 ? 'low' : ''}`}>
                {t(`mining.eff.${k}`)}: {Math.round((s.efficiency?.[k] ?? 1) * 100)}%
              </span>
            ))}
            {farm.components?.ups && (
              <span className={`mining-eff-badge ${s.upsProtected ? 'ok' : 'warn'}`}>
                {t('mining.upsStatus')}: {s.upsProtected ? t('mining.upsOk') : t('mining.upsWeak')}
              </span>
            )}
          </div>
          </>
        ) : (
          <div className="mining-not-assembled">
            <Cpu size={18} /> {t('mining.notAssembled')}
          </div>
        )}

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
          <OverclockSlider
            value={farm.overclock}
            disabled={busy}
            label={t('mining.overclock')}
            onCommit={(v) => run(() => setOverclock(farm.id, v))}
          />
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
                <span>{t('mining.level')} {farm.manager.level} · ${formatMoney(farm.manager.salary)}{t('units.perHour')}</span>
                <small className="mmc-desc">{t('mining.managerDesc')}</small>
              </div>
              <div className="mmc-actions">
                {farm.manager.level >= 5 ? (
                  <button className="asset-act upgrade" disabled>{t('mining.maxLevel')}</button>
                ) : (
                  <button className="asset-act upgrade" disabled={busy} onClick={() => run(() => farmManager(farm.id, 'upgrade'), 'mining.mgrUpgraded')}>{t('mining.upgrade')}</button>
                )}
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
              const multiKey = cat === 'gpu' ? 'gpus' : cat === 'fan' ? 'fans' : 'psus'
              const installed = multi
                ? (farm.components?.[multiKey]) || []
                : (farm.components?.[cat] ? [farm.components[cat]] : [])
              const avail = parts[cat] || []
              // Корпус и стойка — взаимоисключающие способы размещения (см.
              // backend/mining.py install_component): пока стоит один, другой недоступен.
              const altPlacement = cat === 'case' ? 'rack' : cat === 'rack' ? 'case' : null
              const blockedByAlt = altPlacement && farm.components?.[altPlacement]
              // Ёмкость размещения: сколько ещё компонентов этой роли влезет
              // (сервер валидирует повторно — см. install_component).
              const capLeft = multi ? (farm.capacity?.[cat] ?? null) : null
              const capFull = capLeft != null && capLeft <= 0
              const canAdd = (multi || installed.length === 0) && !blockedByAlt && !capFull
              // Группируем одинаковые детали (по имени+специфике), чтобы не плодить
              // 13 строк «Промышленные вентиляторы» — показываем «… ×13».
              const groups = []
              for (const it of installed) {
                const key = hwName(it, t) + partSpec(cat, it.specs, t)
                const g = groups.find(x => x.key === key)
                if (g) g.items.push(it); else groups.push({ key, label: hwName(it, t), items: [it] })
              }
              return (
                <div key={cat} className={`mining-slot ${req ? 'req' : ''} ${installed.length ? 'filled' : ''}`}>
                  <div className="mslot-head">
                    <span className="mslot-name">{t(`mining.comp.${cat}`, cat)}{req && <em> *</em>}</span>
                    {multi && installed.length > 0 && (
                      <span className="mslot-count">{capLeft != null ? `${installed.length}/${installed.length + capLeft}` : installed.length}</span>
                    )}
                  </div>
                  <span className="mslot-desc">{t(`mining.desc.${cat}`, '')}</span>
                  {groups.map(g => (
                    <div key={g.key} className="mslot-item">
                      <span>{g.label}{g.items.length > 1 && <b className="mslot-item-qty"> ×{g.items.length}</b>}</span>
                      <span className="mslot-item-actions">
                        {multi && g.items.length > 1 && (
                          <button className="mslot-rm mslot-rm-all" disabled={busy}
                            title={t('mining.removeAll', 'Удалить все')}
                            onClick={() => removeMany(g.items.map(it => it.hwId))}>
                            <X size={12} />{g.items.length}
                          </button>
                        )}
                        <button className="mslot-rm" disabled={busy}
                          title={g.items.length > 1 ? t('mining.removeOne') : ''}
                          onClick={() => run(() => uninstallComponent(farm.id, g.items[g.items.length - 1].hwId))}><X size={12} /></button>
                      </span>
                    </div>
                  ))}
                  {blockedByAlt ? (
                    <span className="mslot-empty">{t('mining.placementTaken', { other: t(`mining.comp.${altPlacement}`, altPlacement) })}</span>
                  ) : capFull ? (
                    <span className="mslot-empty">{t('mining.capacityFull')}</span>
                  ) : canAdd && (() => {
                    const addKey = `${farm.id}::${cat}`
                    if (!openAdd[addKey]) {
                      return (
                        <button className="mslot-add-badge" disabled={busy}
                          title={t('mining.addComponent', 'Добавить')}
                          onClick={() => setOpenAdd(o => ({ ...o, [addKey]: true }))}>
                          <Plus size={14} /> {t('mining.addComponent', 'Добавить')}
                        </button>
                      )
                    }
                    return (
                    avail.length > 0 ? (
                      multi ? (
                        <div className="mslot-cart">
                          {(() => {
                            // Группируем доступные детали по модели (имя+спека), чтобы
                            // показать одну строку на модель с полем количества.
                            const availGroups = []
                            for (const p of avail) {
                              const key = hwName(p, t) + partSpec(cat, p.specs, t)
                              const g = availGroups.find(x => x.key === key)
                              if (g) g.items.push(p)
                              else availGroups.push({ key, label: hwName(p, t), spec: partSpec(cat, p.specs, t), items: [p] })
                            }
                            return availGroups.map(g => {
                              const qtyKey = `${cat}::${g.key}`
                              const maxQty = Math.min(g.items.length, capLeft ?? Infinity)
                              const qty = cartQty[qtyKey] ?? 1
                              return (
                                <div key={g.key} className="mslot-cart-row">
                                  <span className="mslot-cart-label">{g.label}{g.spec}</span>
                                  <span className="mslot-cart-stock" title={t('mining.inStock', 'В наличии')}>{g.items.length}</span>
                                  <input className="mslot-cart-qty" inputMode="numeric" disabled={busy}
                                    value={qty}
                                    onChange={e => {
                                      const v = parseInt(e.target.value, 10)
                                      setCartQty(q => ({ ...q, [qtyKey]: isNaN(v) ? 1 : Math.max(1, Math.min(maxQty, v)) }))
                                    }} />
                                  <button className="mslot-cart-btn" disabled={busy}
                                    onClick={() => {
                                      const want = Math.max(1, Math.min(cartQty[qtyKey] ?? 1, maxQty))
                                      installMany(cat, g.items.slice(0, want).map(p => p.hwId))
                                    }}>
                                    {t('mining.install', 'Поставить')}
                                  </button>
                                </div>
                              )
                            })
                          })()}
                        </div>
                      ) : (
                        <select className="mslot-pick" disabled={busy} value=""
                          onChange={e => { if (e.target.value) run(() => installComponent(farm.id, cat, e.target.value)) }}>
                          <option value="">{t('mining.pickPart')}</option>
                          {avail.map(p => <option key={p.hwId} value={p.hwId}>{hwName(p, t)}{partSpec(cat, p.specs, t)}</option>)}
                        </select>
                      )
                    ) : (
                      <span className="mslot-empty">{t('mining.noParts')}</span>
                    )
                    )
                  })()}
                </div>
              )
            })}
          </div>
          <p className="mining-hint">{t('mining.buyHint')}</p>
        </div>
      </div>

        {/* Правая панель — успехи добычи (lifetime + live). */}
        <div className="mining-success">
          <h4><TrendingUp size={16} /> {t('mining.successTitle')}</h4>
          <div className="mining-success-row"><span>{t('mining.totalMinedCoins')}</span><b>{formatCompact(farm.totalMinedCoins || 0)}{farm.coin ? ` ${farm.coin}` : ''}</b></div>
          <div className="mining-success-row"><span>{t('mining.totalMinedUsd')}</span><b>${formatCompact(farm.totalMinedUsd || 0)}</b></div>
          <div className="mining-success-row"><span>{t('mining.earned')}</span><b className="up">${formatCompact(farm.totalEarned || 0)}</b></div>
          <div className="mining-success-row"><span>{t('mining.hashrate')}</span><b>{formatCompact(s.hashrate || 0)} H/s</b></div>
          <div className="mining-success-row"><span>{t('mining.profitHr')}</span><b className={(s.profitPerHour || 0) >= 0 ? 'up' : 'down'}>${formatMoney(s.profitPerHour || 0)}</b></div>
        </div>
      </div>

      <ConfirmDialog
        open={!!confirm}
        danger={confirm?.danger}
        busy={busy}
        title={confirm?.title}
        message={confirm?.message}
        onConfirm={() => { confirm?.onConfirm?.(); setConfirm(null) }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}

export default MiningTab
