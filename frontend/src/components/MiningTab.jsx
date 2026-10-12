import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchFarms, fetchMiningHouses, fetchMiningMarket, fetchMiningParts,
  createFarm, deleteFarm, installComponent, installComponentsBatch,
  uninstallComponent, startMining, stopMining, setFarmCoin, setOverclock,
  repairFarm, farmManager, addCoolant, bulkCreateFarms, setHouseGroup,
} from '../services/api'
import { formatMoney, formatCompact } from './TransactionsPanel'
import { hwName } from '../utils/hwName'
import ConfirmDialog from './ConfirmDialog'
import MiningBulkView from './MiningBulkView'
import {
  Play, Square, Trash2, Wrench, Zap, Thermometer, Gauge, Activity,
  Plus, X, AlertTriangle, Check, Bot, TrendingUp, HardDrive, Server, Cpu,
  Home, ChevronLeft, ChevronRight, Droplet,
} from 'lucide-react'

// Категории компонентов: обязательные помечены req; multi — можно несколько.
// Стойки (rack) вернулись: большая сборка в одном слоте подвала; корпус — до 5 GPU.
const CATS = [
  { cat: 'motherboard', req: true }, { cat: 'cpu', req: true }, { cat: 'psu', req: true, multi: true },
  { cat: 'ram', req: true }, { cat: 'ssd', req: true }, { cat: 'cooling', req: true },
  { cat: 'gpu', req: true, multi: true }, { cat: 'fan', multi: true },
  { cat: 'rack' }, { cat: 'case' }, { cat: 'ups' }, { cat: 'network' },
]

// Краткая характеристика детали для выпадающего списка.
function partSpec(cat, s = {}, t) {
  if (cat === 'gpu') return s.hashrate ? ` · ${formatCompact(s.hashrate)} H/s` : ''
  if (cat === 'psu') return s.power ? ` · ${s.power}W` : ''
  if (cat === 'cooling' || cat === 'fan') return s.cooling ? ` · ${s.cooling}` : ''
  if (cat === 'cpu') return s.cores ? ` · ${t('units.cores', { count: s.cores })}` : ''
  if (cat === 'motherboard') return s.gpuSlots ? ` · ${s.gpuSlots} GPU` : ''
  if (cat === 'rack' || cat === 'case') return s.slots ? ` · ${s.slots}` : ''
  if (cat === 'ram' || cat === 'ssd') return s.gb ? ` · ${s.gb} ${t('units.gb')}` : ''
  return ''
}

// Ползунок разгона.
function OverclockSlider({ value, disabled, label, onCommit }) {
  const [local, setLocal] = useState(value)
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

// ── Экран выбора дома ──────────────────────────────────────────────────────
function HousesView({ houses, onPickHouse, onBack, onSetGroup }) {
  const { t } = useTranslation()
  if (houses.length === 0) {
    return (
      <div className="crypto-onboard mining-onboard">
        <div className="crypto-onboard-icon"><Home size={56} /></div>
        <h3>{t('mining.noHousesTitle', 'Нет подходящих домов')}</h3>
        <p>{t('mining.noHousesDesc', 'Майнинг работает только в подвалах домов. Купите дом с подвалом на вкладке «Рынок» — чем больше basement, тем больше корпусов можно разместить.')}</p>
        {onBack && (
          <button className="crypto-open-btn" onClick={onBack}>
            <ChevronLeft size={18} /> {t('common.back', 'Назад')}
          </button>
        )}
      </div>
    )
  }
  return (
    <div className="mining-houses">
      <h3><Home size={18} /> {t('mining.chooseHouse', 'Выберите дом для майнинга')}</h3>
      <p className="mining-hint">{t('mining.housesHint', 'Каждый слот подвала = отдельный корпус с собственной фермой.')}</p>
      <div className="mining-houses-grid">
        {houses.map(h => {
          const free = h.slots.filter(s => !s.occupied).length
          const used = h.slots.filter(s => s.occupied).length
          return (
            <div key={h.id} className="mining-house-card" role="button" tabIndex={0}
              onClick={() => onPickHouse(h)}
              onKeyDown={e => { if (e.key === 'Enter' && e.target === e.currentTarget) onPickHouse(h) }}>
              <div className="mining-house-head">
                <Home size={22} className="icon" />
                <span className="mining-house-name">{h.name}</span>
                <span className={`rarity-badge rarity-${h.rarity || 'common'}`}>{h.rarity}</span>
              </div>
              <div className="mining-house-info">
                <div className="mining-house-info-row">
                  <span>{t('mining.basementLabel', 'Подвал (слоты корпусов)')}</span>
                  <b>{h.basement}</b>
                </div>
                <div className="mining-house-info-row">
                  <span>{t('mining.slotsUsed', 'Занято фермами')}</span>
                  <b>{used} / {h.basement}</b>
                </div>
                <div className="mining-house-info-row">
                  <span>{t('mining.slotsFree', 'Свободно')}</span>
                  <b className="up">{free}</b>
                </div>
              </div>
              <div className="mining-house-info-row">
                <span>{t('mining.group', 'Группа')}</span>
                <input
                  className="tx-input mining-house-group"
                  defaultValue={h.group || ''}
                  placeholder={t('mining.groupPlaceholder', '—')}
                  maxLength={30}
                  onClick={e => e.stopPropagation()}
                  onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
                  onBlur={e => {
                    const v = e.target.value.trim()
                    if (v !== (h.group || '')) onSetGroup?.(h.id, v || null)
                  }}
                />
              </div>
              <div className="mining-house-cta">
                <ChevronRight size={16} /> {t('mining.openHouse', 'Открыть')}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Экран выбора слота в доме ─────────────────────────────────────────────
function SlotsView({ house, onPickSlot, onNewSlot, onBack, onFillHouse, qtyValue, onQtyChange, freeCount }) {
  const { t } = useTranslation()
  return (
    <div className="mining-slots-view">
      <div className="mining-nav-row">
        <button className="asset-interact-btn" onClick={onBack}>
          <ChevronLeft size={16} /> {t('mining.toHouses', 'К домам')}
        </button>
        <h3 className="mining-nav-title"><Home size={18} /> {house.name}</h3>
        <span className={`rarity-badge rarity-${house.rarity || 'common'}`}>{house.rarity}</span>
      </div>
      <p className="mining-hint">{t('mining.slotsHint', 'В этом доме {{n}} слотов. Нажмите на слот, чтобы открыть ферму, или на пустой — чтобы создать новую.').replace('{{n}}', String(house.basement))}</p>
      {onFillHouse && house.slots.some(s => !s.occupied) && (
        <div className="mining-bulk-create-row" style={{ marginBottom: 'var(--spacing-md)' }}>
          <span className="mining-bulk-label">{t('mining.slotsAvailable', 'Свободно слотов')}: <b>{freeCount}</b></span>
          <input type="number" min="1" max="1000" className="tx-input mining-bulk-qty"
            value={qtyValue}
            onChange={e => onQtyChange(Math.max(1, Math.min(1000, parseInt(e.target.value, 10) || 1)))} />
          <button className="asset-act upgrade" onClick={onFillHouse}>
            <Plus size={14} /> {t('mining.fillHouseSlots', 'Заполнить свободные слоты')}
          </button>
        </div>
      )}
      <div className="mining-slots-grid">
        {house.slots.map(s => {
          const free = !s.occupied
          return (
            <button
              key={s.index}
              className={`mining-slot-card ${free ? 'free' : 'occupied'}`}
              onClick={() => free ? onNewSlot(s.index) : onPickSlot(s)}
            >
              <div className="mining-slot-num">#{s.index + 1}</div>
              {free ? (
                <>
                  <Plus size={28} className="icon" />
                  <span className="mining-slot-label">{t('mining.slotEmpty', 'Пусто')}</span>
                  <span className="mining-slot-cta">{t('mining.createFarm', 'Создать ферму')}</span>
                </>
              ) : (
                <>
                  <Server size={28} className="icon" />
                  <span className="mining-slot-label">{s.farmName || t('mining.farm', 'Ферма')}</span>
                  <span className={`mining-slot-status status-${s.status || 'idle'}`}>
                    {t(`mining.state.${s.status || 'idle'}`, s.status || 'idle')}
                  </span>
                  <span className="mining-slot-cta">{t('mining.openFarm', 'Открыть')}</span>
                </>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Модалка создания фермы в выбранном слоте (по центру экрана) ─────────
function NewFarmModal({ open, slotIndex, houseName, busy, onConfirm, onCancel }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  useEffect(() => {
    if (open) setName(`Ферма #${(slotIndex ?? 0) + 1}`)
  }, [open, slotIndex])
  if (!open) return null
  const submit = () => {
    const v = name.trim()
    if (v.length < 2) return
    onConfirm(v)
  }
  return (
    <div className="modal-overlay tv-confirm-overlay" onClick={() => !busy && onCancel?.()}>
      <div className="modal-content tv-confirm new-farm-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={() => onCancel?.()} disabled={busy} aria-label="close">
          <X size={18} />
        </button>
        <div className="tv-confirm-icon">
          <Server size={26} />
        </div>
        <h3 className="tv-confirm-title">
          {t('mining.createFarm', 'Создать ферму')} #{slotIndex + 1}
        </h3>
        {houseName && (
          <p className="tv-confirm-message">
            {t('mining.modalHouse', { house: houseName, defaultValue: `Дом: ${houseName}` })}
          </p>
        )}
        <p className="tv-confirm-message">
          {t('mining.newFarmHint', 'Используйте это имя для идентификации фермы.')}
        </p>
        <input
          className="tx-input new-farm-name"
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }}
          maxLength={40}
          autoFocus
          placeholder={t('mining.farmName', 'Название фермы')}
        />
        <div className="tv-confirm-buttons">
          <button
            className="tv-confirm-btn primary"
            disabled={busy || name.trim().length < 2}
            onClick={submit}
          >
            {busy ? t('bank.processing') : t('common.create', 'Создать')}
          </button>
          <button className="tv-confirm-btn cancel" disabled={busy} onClick={() => onCancel?.()}>
            {t('common.cancel', 'Отмена')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Главный компонент вкладки «Майнинг» ───────────────────────────────────
function MiningTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  // view: 'houses' → выбор дома; 'slots' → выбор слота в доме; 'farm' → ферма
  const [view, setView] = useState('houses')
  const [houses, setHouses] = useState([])
  const [currentHouse, setCurrentHouse] = useState(null)
  const [farms, setFarms] = useState([])
  const [market, setMarket] = useState({ coins: [], best: null })
  const [parts, setParts] = useState({})
  const [activeId, setActiveId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [installQty, setInstallQty] = useState({})
  const [newFarmSlot, setNewFarmSlot] = useState(null)
  const [createQty, setCreateQty] = useState(1)

  // ── Загрузка списка домов (заодно обновляет currentHouse — иначе после
  // создания/удаления фермы слоты дома оставались устаревшими до перезахода).
  const loadHouses = useCallback(async () => {
    try {
      const hs = await fetchMiningHouses()
      setHouses(hs || [])
      setCurrentHouse(prev => (prev ? ((hs || []).find(h => h.id === prev.id) || prev) : prev))
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    }
  }, [])

  // ── Загрузка ферм конкретного дома + служебных данных
  // silent — фоновое обновление (WS-событие/поллинг/после действия) без
  // скелетона: раньше каждый такой рефреш перерисовывал экран «перезагрузкой».
  const loadFarmData = useCallback(async (houseId, silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [f, m, p] = await Promise.all([
        fetchFarms(houseId),
        fetchMiningMarket().catch(() => ({ coins: [], best: null })),
        fetchMiningParts().catch(() => ({})),
      ])
      setFarms(f || [])
      setMarket(m)
      setParts(p)
      setActiveId(prev => (prev && (f || []).some(x => x.id === prev)) ? prev : ((f || [])[0]?.id ?? null))
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  // При входе во вкладку — показываем дома.
  useEffect(() => {
    if (view === 'houses') {
      setLoading(true)
      loadHouses().finally(() => setLoading(false))
    }
  }, [view, loadHouses])

  // При переходе к фермам — грузим их.
  useEffect(() => {
    if (view === 'farm' && currentHouse) {
      loadFarmData(currentHouse.id)
    }
  }, [view, currentHouse, loadFarmData])

  // Realtime: события фермы по WebSocket/поллинг — фоновый silent-рефреш без
  // скелетона: раньше каждое событие перерисовывало экран «перезагрузкой».
  useEffect(() => {
    if (view !== 'farm') return undefined
    const onRt = (e) => { if (e.detail?.type === 'mining') loadFarmData(currentHouse.id, true) }
    window.addEventListener('tv:realtime', onRt)
    const id = setInterval(() => loadFarmData(currentHouse.id, true), 20000)
    return () => { window.removeEventListener('tv:realtime', onRt); clearInterval(id) }
  }, [view, currentHouse, loadFarmData])

  const flash = (text, type = 'success') => { setMsg({ text, type }); setTimeout(() => setMsg(null), 2400) }

  const run = async (fn, okKey) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res?.balance != null) onBalanceChange?.(res.balance)
      if (okKey) flash(t(okKey))
      await loadFarmData(currentHouse.id, true)
      return res
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const installMany = async (cat, hwIds) => {
    setBusy(true)
    try {
      // Один batch-запрос вместо последовательных per-item: N раз быстрее и
      // одна перезагрузка данных вместо N.
      const res = await installComponentsBatch(activeId, hwIds.map(hwId => ({ category: cat, hwId })))
      if (res?.error) flash(res.error, 'error')
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
      await loadFarmData(currentHouse.id)
    }
  }

  const pickHouse = (house) => { setCurrentHouse(house); setView('slots') }
  const pickSlot = (slot) => {
    setActiveId(slot.farmId)
    setView('farm')
  }
  const openNewSlot = (slotIndex) => setNewFarmSlot(slotIndex)
  const confirmNewFarm = async (name) => {
    if (newFarmSlot == null || !currentHouse) return
    setBusy(true)
    try {
      const farm = await createFarm(name, currentHouse.id, newFarmSlot)
      setNewFarmSlot(null)
      // После создания — сразу идём к ферме и обновляем дома (текущий дом
      // перечитается в loadHouses → слоты актуальны при возврате).
      setActiveId(farm.id)
      setView('farm')
      await loadHouses()
      // Создание из интерфейса фермы: список ферм дома нужно перезагрузить,
      // эффект на view/currentHouse не сработает (значения не изменились).
      await loadFarmData(currentHouse.id, true)
      flash(t('mining.created', 'Ферма создана'))
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const askDismantle = (f) => setConfirm({
    danger: true,
    title: t('mining.dismantle', 'Разобрать ферму'),
    message: t('confirm.dismantle', { name: f.name }),
    onConfirm: async () => {
      await run(() => deleteFarm(f.id))
      // После удаления — обновить дома; loadHouses синхронизирует currentHouse.
      await loadHouses()
      if (farms.length <= 1) {
        setView('slots')
        setActiveId(null)
      }
    },
  })

  const bulkCreate = async (houseId) => {
    setBusy(true)
    try {
      const res = await bulkCreateFarms({ ...(houseId ? { houseId } : {}), qty: createQty })
      flash(t('mining.bulkCreated', 'Создано ферм: {{n}}').replace('{{n}}', String(res?.created ?? 0)))
      await loadHouses()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const tempClass = (temp) => (temp >= 85 ? 'crit' : temp >= 70 ? 'warn' : 'ok')

  // ── Рендер по состояниям ────────────────────────────────────────────────
  if (view === 'bulk') {
    return <MiningBulkView onBack={() => { setView('houses'); loadHouses() }} />
  }

  if (view === 'houses') {
    return (
      <div className="mining-tab">
        <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>
        {msg && (
          <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
            {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
          </div>
        )}
        <button className="asset-act upgrade" onClick={() => setView('bulk')} style={{ marginBottom: 'var(--spacing-md)' }}>
          <Bot size={15} /> {t('mining.bulk.title', 'Массовое управление фермами')}
        </button>
        <div className="mining-bulk-create-row" style={{ marginBottom: 'var(--spacing-md)' }}>
          <span className="mining-bulk-label">{t('mining.slotsAvailable', 'Свободно слотов')}: <b>{houses.reduce((n, h) => n + h.slots.filter(s => !s.occupied).length, 0)}</b></span>
          <input type="number" min="1" max="1000" className="tx-input mining-bulk-qty" disabled={busy}
            value={createQty}
            onChange={e => setCreateQty(Math.max(1, Math.min(1000, parseInt(e.target.value, 10) || 1)))} />
          <button className="asset-act upgrade" disabled={busy}
            onClick={() => bulkCreate(null)}>
            <Plus size={15} /> {t('mining.bulkCreateAll', 'Создать фермы во всех домах')}
          </button>
        </div>
        {loading ? (
          <div className="asset-card skeleton" style={{ height: 220 }} />
        ) : (
          <HousesView
            houses={houses}
            onPickHouse={pickHouse}
            onSetGroup={(id, g) => run(() => setHouseGroup(id, g)).then(loadHouses)}
          />
        )}
      </div>
    )
  }

  if (view === 'slots') {
    return (
      <div className="mining-tab">
        <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>
        {msg && (
          <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
            {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
          </div>
        )}
        {currentHouse ? (
          <SlotsView
            house={currentHouse}
            onPickSlot={pickSlot}
            onNewSlot={openNewSlot}
            onFillHouse={() => bulkCreate(currentHouse.id)}
            qtyValue={createQty}
            onQtyChange={setCreateQty}
            freeCount={currentHouse.slots.filter(s => !s.occupied).length}
            onBack={() => { setView('houses'); setCurrentHouse(null) }}
          />
        ) : null}
        <NewFarmModal
          open={newFarmSlot != null}
          slotIndex={newFarmSlot || 0}
          houseName={currentHouse?.name}
          busy={busy}
          onConfirm={confirmNewFarm}
          onCancel={() => { if (!busy) setNewFarmSlot(null) }}
        />
      </div>
    )
  }

  // view === 'farm'
  if (loading) {
    return (
      <div className="mining-tab">
        <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>
        <div className="asset-card skeleton" style={{ height: 220 }} />
      </div>
    )
  }
  if (farms.length === 0) {
    return (
      <div className="mining-tab">
        <div className="leaderboard-title-row"><Server size={22} className="icon" /><h2 className="tab-title">{t('nav.mining')}</h2></div>
        <div className="crypto-onboard mining-onboard">
          <div className="crypto-onboard-icon"><Server size={56} /></div>
          <h3>{t('mining.noFarmsInHouse', 'В этом доме ещё нет ферм')}</h3>
          <p>{t('mining.noFarmsInHouseDesc', 'Вернитесь к выбору слота и создайте ферму в одном из подвалов.')}</p>
          <button className="crypto-open-btn" onClick={() => setView('slots')}>
            <ChevronLeft size={18} /> {t('mining.toSlots', 'К слотам')}
          </button>
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

      {/* Хлебные крошки: назад к слотам, потом к домам */}
      <div className="mining-breadcrumbs">
        <button className="asset-interact-btn" onClick={() => { setView('houses'); setActiveId(null); setCurrentHouse(null) }}>
          <Home size={14} /> {t('mining.toHouses', 'К домам')}
        </button>
        <span>›</span>
        <button className="asset-interact-btn" onClick={() => { setView('slots'); setActiveId(null) }}>
          {currentHouse?.name || t('mining.house', 'Дом')}
        </button>
        <span>›</span>
        <span className="mining-breadcrumb-current">{farm.name}</span>
      </div>

      {/* Bulk-управление доступно и отсюда (раньше кнопка была только на экране домов) */}
      <button className="asset-act upgrade" onClick={() => setView('bulk')} style={{ marginBottom: 'var(--spacing-md)' }}>
        <Bot size={15} /> {t('mining.bulk.title', 'Массовое управление фермами')}
      </button>

      {/* Селектор ферм внутри дома + кнопка добавления новой.
          Кнопка «+» появляется только если в этом доме ещё есть свободный слот. */}
      <div className="mining-farm-tabs">
        {farms.map(f => (
          <button key={f.id} className={`mining-farm-tab ${f.id === activeId ? 'active' : ''}`} onClick={() => setActiveId(f.id)}>
            <span className={`mining-status ${f.status}`} /> {f.name}
          </button>
        ))}
        {currentHouse?.slots?.some(s => !s.occupied) && (
          <button className="asset-act upgrade mining-new-farm" onClick={() => {
            const free = currentHouse.slots.find(s => !s.occupied)
            if (free) openNewSlot(free.index)
          }}>
            <Plus size={14} /> {t('mining.newFarm', 'Новая ферма')}
          </button>
        )}
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
          <div className="mph-meta">
            <span className={`mining-coolant-pill ${farm.coolantActive ? 'on' : 'off'}`} title={t('mining.coolantHint', 'Снижает температуру на 25%, 1 шт. на 12 ч')}>
              <Droplet size={12} /> {farm.coolant || 0}/{farm.coolantMax || 4}
              {farm.coolantActive && farm.coolantUntil && (
                <em className="mining-coolant-remaining">{Math.max(0, Math.ceil((new Date(farm.coolantUntil).getTime() - Date.now()) / 3600000))}ч</em>
              )}
            </span>
          </div>
          {/* Иконки-кнопки действий: фиксированная ширина, без растягивания */}
          <div className="mph-actions">
            {mining ? (
              <button className="mining-icon-btn" disabled={busy} onClick={() => run(() => stopMining(farm.id))} title={t('mining.stop')}>
                <Square size={14} />
              </button>
            ) : (
              <button className="mining-icon-btn primary" disabled={busy || !assembled}
                onClick={() => run(() => startMining(farm.id), 'mining.started')} title={t('mining.start')}>
                <Play size={14} />
              </button>
            )}
            <button className="mining-icon-btn danger" disabled={busy} onClick={() => askDismantle(farm)} title={t('mining.dismantle')}>
              <Trash2 size={14} />
            </button>
          </div>
        </div>

        {farm.missing?.length > 0 && (
          <div className="mining-missing"><AlertTriangle size={14} /> {t('mining.missing')}: {farm.missing.map(m => t(`mining.comp.${m}`, m)).join(', ')}</div>
        )}

        {/* Мониторинг */}
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
            <div className={`msc msc-coolant ${farm.coolantActive ? 'coolant-on' : ''}`}>
              <Droplet size={16} />
              <span>{t('mining.coolant', 'Охлаждающая жидкость')}</span>
              <b>{farm.coolant || 0} / {farm.coolantMax || 4}</b>
              <button
                className="asset-act compact msc-btn"
                disabled={busy || (farm.coolant || 0) >= (farm.coolantMax || 4)}
                onClick={() => run(() => addCoolant(farm.id), 'mining.coolantAdded')}
                title={t('mining.coolantPour', 'Заправить охлаждающую жидкость')}
              >
                <Plus size={12} /> {t('mining.coolantAdd', 'Заправить')}
              </button>
              {farm.coolantActive && farm.coolantUntil && (
                <small className="msc-meta">{t('mining.coolantActive', 'Снижает температуру на 25% ещё ~{{h}} ч')
                  .replace('{{h}}', String(Math.max(0, Math.ceil((new Date(farm.coolantUntil).getTime() - Date.now()) / 3600000))))}</small>
              )}
            </div>
          </div>
          {Number(s.temperature) >= Number(s.tempWearThreshold || 40) && (
            <div className="mining-warn-temp">
              <AlertTriangle size={14} />
              {t('mining.warnHighTemp', 'Температура выше порога износа — детали изнашиваются быстрее.')}
            </div>
          )}
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
              <div className="mmc-toggles">
                {[
                  ['autoRepair', 'mining.autoRepair', 'mining.autoRepairHint'],
                  ['autoCoin', 'mining.autoCoin', 'mining.autoCoinHint'],
                  ['autoRestart', 'mining.autoRestart', 'mining.autoRestartHint'],
                ].map(([key, lk, hk]) => (
                  <label key={key} className="mmc-toggle" title={t(hk)}>
                    <input
                      type="checkbox" disabled={busy}
                      checked={farm.manager.settings?.[key] ?? true}
                      onChange={e => run(() => farmManager(farm.id, 'settings', { [key]: e.target.checked }))}
                    />
                    <span>{t(lk)}</span>
                  </label>
                ))}
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
              const multiKey = { gpu: 'gpus', fan: 'fans', psu: 'psus' }[cat]
              const installed = multi
                ? (farm.components?.[multiKey] || [])
                : (farm.components?.[cat] ? [farm.components[cat]] : [])
              const avail = parts[cat] || []
              const altPlacement = null
              const blockedByAlt = false
              const capLeft = multi ? (farm.capacity?.[cat] ?? null) : null
              const capFull = capLeft != null && capLeft <= 0
              const canAdd = (multi || installed.length === 0) && !blockedByAlt && !capFull
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
                      <button className="mslot-rm" disabled={busy}
                        title={g.items.length > 1 ? t('mining.removeOne') : ''}
                        onClick={() => run(() => uninstallComponent(farm.id, g.items[g.items.length - 1].hwId))}><X size={12} /></button>
                    </div>
                  ))}
                  {blockedByAlt ? (
                    <span className="mslot-empty">{t('mining.placementTaken', { other: t(`mining.comp.${altPlacement}`, altPlacement) })}</span>
                  ) : capFull ? (
                    <span className="mslot-empty">{t('mining.capacityFull')}</span>
                  ) : canAdd && (
                    avail.length > 0 ? (
                      <div className="mslot-pick-row">
                        <select className="mslot-pick" disabled={busy} value=""
                          onChange={e => {
                            if (!e.target.value) return
                            const picked = avail.find(p => p.hwId === e.target.value)
                            if (multi) {
                              const want = Math.max(1, Math.min(installQty[cat] || 1, capLeft ?? Infinity))
                              const key = hwName(picked, t) + partSpec(cat, picked.specs, t)
                              const ids = avail.filter(p => hwName(p, t) + partSpec(cat, p.specs, t) === key).slice(0, want).map(p => p.hwId)
                              installMany(cat, ids.length ? ids : [picked.hwId])
                            } else {
                              run(() => installComponent(farm.id, cat, e.target.value))
                            }
                          }}>
                          <option value="">{t('mining.pickPart')}</option>
                          {avail.map(p => <option key={p.hwId} value={p.hwId}>{hwName(p, t)}{partSpec(cat, p.specs, t)}</option>)}
                        </select>
                        {multi && (
                          <span className="mslot-qty">
                            <input type="number" min="1" max={capLeft ?? 999} disabled={busy}
                              value={installQty[cat] || 1}
                              onChange={e => setInstallQty(q => ({ ...q, [cat]: Math.max(1, Math.min(capLeft ?? 999, parseInt(e.target.value, 10) || 1)) }))} />
                          </span>
                        )}
                      </div>
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

        {/* Правая панель — успехи добычи */}
        <div className="mining-success">
          <h4><TrendingUp size={16} /> {t('mining.successTitle')}</h4>
          <div className="mining-success-row"><span>{t('mining.totalMinedCoins')}</span><b>{formatCompact(farm.totalMinedCoins || 0)}{farm.coin ? ` ${farm.coin}` : ''}</b></div>
          <div className="mining-success-row"><span>{t('mining.totalMinedUsd')}</span><b>${formatCompact(farm.totalMinedUsd || 0)}</b></div>
          <div className="mining-success-row"><span>{t('mining.earned')}</span><b className="up">${formatCompact(farm.totalEarned || 0)}</b></div>
          <div className="mining-success-row"><span>{t('mining.hashrate')}</span><b>{formatCompact(s.hashrate || 0)} H/s</b></div>
          <div className="mining-success-row"><span>{t('mining.profitHr')}</span><b className={(s.profitPerHour || 0) >= 0 ? 'up' : 'down'}>${formatMoney(s.profitPerHour || 0)}</b></div>
        </div>
      </div>

      {/* Модалка создания фермы — и отсюда тоже: раньше «Новая ферма» из
          интерфейса фермы открывала её только при заходе в экран дома. */}
      <NewFarmModal
        open={newFarmSlot != null}
        slotIndex={newFarmSlot || 0}
        houseName={currentHouse?.name}
        busy={busy}
        onConfirm={confirmNewFarm}
        onCancel={() => { if (!busy) setNewFarmSlot(null) }}
      />

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
