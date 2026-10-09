// ProductionPanel · управление производством: источник (шахта/лесопилка/поле),
// пекарня (завод produces='bread') и склад.
// Рендерится из MyAssetsTab вместо списка активов (как FarmPanel для поля).
//
// Данные: GET /api/production/overview — юниты, склады, фуры, поля, цены.
// Действия:
//   POST /api/production/{id}/config           — получатель / поставщик пшеницы
//   POST /api/production/{id}/trucks           — назначить фуры (до 5 на поток)
//   POST /api/production/{id}/workers          — нанять работников (0..50)
//   POST /api/production/{id}/food             — заказать хлеб для работников
//   POST /api/production/{id}/storage-upgrade  — прокачка хранилища (до 10 ур.)
//   POST /api/production/{id}/sell             — продать ресурс (со склада тоже)
//   POST /api/production/{id}/haul-now         — отправить свободные фуры сейчас

import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, Package, Users, Wheat, Truck, Coins, Info, Loader2, AlertTriangle, Send } from 'lucide-react'
import {
  fetchProductionOverview, setProductionConfig, setProductionTrucks,
  setProductionWorkers, buyProductionFood, upgradeProductionStorage,
  sellProductionResource, productionHaulNow,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'

// Эмодзи ресурсов (res id из backend/resources.py).
const RES_EMOJI = {
  wheat: '🌾', carrot: '🥕', potato: '🥔', sunflower: '🌻', bread: '🍞',
  stone: '🪨', copper: '🟠', silver: '⚪', bronze: '🟤', metal: '⛓️',
  gold: '🟡', diamond: '💎', wood: '🪵', processed_wood: '🪵',
}

const TYPE_LABEL = {
  mine: '⛏️', sawmill: '🪵', field: '🌾', bakery: '🍞', warehouse: '🏬',
}

function ProductionPanel({ unitId, onBack, balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [workersInput, setWorkersInput] = useState('')
  const [foodQty, setFoodQty] = useState('100')
  const [sellQty, setSellQty] = useState({})
  const [tick, setTick] = useState(0)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const d = await fetchProductionOverview()
      setData(d)
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])
  // Обновление каждые 20 сек: рейсы фур, приход ресурса.
  useEffect(() => {
    const id = setInterval(() => { setTick(k => k + 1); load(true) }, 20000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const unit = data?.units?.find(u => u.id === unitId) || null
  const warehouse = data?.warehouses?.find(w => w.id === unitId) || null
  const trucks = data?.trucks || []
  const prices = data?.prices || {}
  // Склад поля (user_fields) — для отображения урожая в панели поля.
  const fieldStore = unit?.category === 'field'
    ? (data?.fields?.find(f => f.id === unit.id)?.storage || {})
    : null

  const runAction = async (fn, okMsg) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res && typeof res.balance === 'number' && onBalanceChange) onBalanceChange(res.balance)
      if (okMsg) toast(okMsg, 'success')
      await load(true)
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setBusy(false)
    }
  }

  // Список получателей для источника: склады (+ пекарня — только для пшеницы).
  const destinationOptions = []
  for (const w of (data?.warehouses || [])) destinationOptions.push(w)
  if (unit && !unit.isBakery && unit.resource === 'wheat') {
    for (const u of (data?.units || [])) if (u.isBakery) destinationOptions.push(u)
  }

  // Поставщики пшеницы для пекарни: поля + склады.
  const inputOptions = []
  if (unit?.isBakery) {
    for (const f of (data?.fields || [])) inputOptions.push({ id: f.id, name: f.name })
    for (const w of (data?.warehouses || [])) inputOptions.push({ id: w.id, name: w.name })
  }

  // Ресурсы, доступные для продажи: у поля — склад поля, иначе prod.storage / storage склада.

  if (loading) {
    return <div className="farm-panel"><div className="empty-state"><Loader2 size={24} className="spin" /> {t('common.loading', 'Загрузка…')}</div></div>
  }
  if (!unit && !warehouse) {
    return (
      <div className="farm-panel">
        <div className="leaderboard-title-row">
          <button className="asset-interact-btn" onClick={onBack}><ChevronLeft size={16} /> {t('common.back', 'Назад')}</button>
        </div>
        <div className="empty-state"><AlertTriangle size={24} /><p>{t('prod.manage', 'Управление производством')}</p></div>
      </div>
    )
  }

  const name = unit?.name || warehouse.name
  return (
    <div className="farm-panel">
      <div className="leaderboard-title-row">
        <button className="asset-interact-btn" onClick={onBack} style={{ padding: '6px 10px' }}>
          <ChevronLeft size={16} /> {t('common.back', 'Назад')}
        </button>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <Package size={22} className="icon" />
          <h2 className="tab-title" style={{ margin: 0, flex: 1 }}>{t('prod.manage', 'Управление производством')}: {name}</h2>
        </span>
      </div>

      {warehouse && <WarehouseSections />}

      {unit && (
        <>
          {/* ── Хранилище ── */}
          <section className="farm-block">
            <h3><Package size={16} /> {t('prod.storage', 'Хранилище')} · {t('prod.storageLevel', { level: unit.storageLevel })}</h3>
            <div className="farm-storage-list">
              {Object.entries(unit.storage || {}).length === 0 && Object.entries(fieldStore || {}).length === 0 && (
                <p className="farm-hint"><Info size={12} /> {t('prod.nothingToSell', 'Склад пуст')}</p>
              )}
              {Object.entries(fieldStore || unit.storage || {}).map(([res, qty]) => (
                <div key={res} className="farm-storage-row">
                  <span className="farm-storage-name">
                    <span>{RES_EMOJI[res] || '📦'}</span>
                    {t(`prod.res_${res}`, res)}
                  </span>
                  <span className="farm-storage-qty">{qty} / {unit.storageCap}</span>
                  <span className="farm-storage-actions">
                    <SellRow res={res} />
                  </span>
                </div>
              ))}
            </div>
            <p className="farm-price">
              {unit.outputPerHour > 0 && !unit.isBakery && (
                <>{t('market.productionPerHour', 'Производство/ч')}: <b>{unit.outputPerHour}</b>{' · '}</>
              )}
              <button className="farm-btn" disabled={busy || unit.storageLevel >= 10}
                onClick={() => runAction(() => upgradeProductionStorage(unit.id), t('prod.storageUpgrade', 'Улучшить хранилище'))}>
                {unit.storageLevel >= 10 ? t('prod.storageMax', 'Максимальный уровень') : `${t('prod.storageUpgrade', 'Улучшить хранилище')} ($${formatMoney(unit.storageUpgradeCost)})`}
              </button>
            </p>
          </section>

          {/* ── Работники ── */}
          <section className="farm-block">
            <h3><Users size={16} /> {t('prod.workers', 'Работники')}</h3>
            <p className="farm-hint"><Info size={12} /> {t('prod.workersHint')}</p>
            <div className="farm-input-row">
              <label>{t('prod.workers')} (0..{unit.maxWorkers}):</label>
              <input type="number" min="0" max={unit.maxWorkers} value={workersInput}
                placeholder={String(unit.workers)}
                onChange={e => setWorkersInput(e.target.value)} />
              <button className="farm-btn" disabled={busy}
                onClick={() => runAction(() => setProductionWorkers(unit.id, Math.max(0, Math.min(unit.maxWorkers, Math.floor(Number(workersInput) || 0)))), t('prod.workers'))}>
                {t('common.save', 'Сохранить')}
              </button>
            </div>
            <p className="farm-price">
              {t('prod.efficiency')}: <b>{efficiencyPct(unit)}%</b>
              {unit.employees > 0 && <> · {t('market.employees', 'Сотрудники')}: {unit.employees}</>}
            </p>
          </section>

          {/* ── Еда ── */}
          <section className="farm-block">
            <h3><Wheat size={16} /> {t('prod.food', 'Еда (хлеб)')}</h3>
            <p className="farm-hint"><Info size={12} /> {t('prod.foodHint')}</p>
            <p className="farm-price">
              {t('prod.foodStock')}: <b>{unit.food} кг</b>
              {unit.foodDemandPerH > 0 && <> · −{unit.foodDemandPerH} кг/ч</>}
            </p>
            <div className="farm-input-row">
              <label>{t('prod.foodBuy')} (кг):</label>
              <input type="number" min="1" value={foodQty} onChange={e => setFoodQty(e.target.value)} />
              <button className="farm-btn" disabled={busy}
                onClick={() => runAction(() => buyProductionFood(unit.id, Math.max(1, Math.floor(Number(foodQty) || 0))), t('prod.foodBuy'))}>
                {t('common.buy', 'Купить')}
              </button>
            </div>
            <p className="farm-price">
              ${formatMoney(prices.bread || 0)}/кг · {t('common.total', 'Итого')}: <b className="up">${formatMoney((Math.floor(Number(foodQty)) || 0) * (prices.bread || 0))}</b>
            </p>
          </section>

          {unit.isBakery && (
            <section className="farm-block">
              <h3><Wheat size={16} /> {t('prod.recipe', { consumes: unit.consumesPerHour, produces: unit.outputPerHour })}</h3>
              <p className="farm-hint"><Info size={12} /> {t('prod.inputHint')}</p>
              <div className="farm-input-row">
                <label>{t('prod.input', 'Поставщик пшеницы')}:</label>
                <select value={unit.inputId || ''} disabled={busy}
                  onChange={e => runAction(() => setProductionConfig(unit.id, { inputId: e.target.value || null }))}>
                  <option value="">— {t('common.none', 'нет')} —</option>
                  {inputOptions.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </div>
            </section>
          )}

          {/* ── Логистика ── */}
          {!warehouse && (
            <section className="farm-block">
              <h3><Truck size={16} /> {t('prod.trucks', 'Фуры')}</h3>
              <p className="farm-hint"><Info size={12} /> {t('prod.trucksHint', { max: 5, minutes: data.tripMinutes || 20 })}</p>
              {!unit.isBakery && (
                <div className="farm-input-row">
                  <label>{t('prod.destination', 'Куда возим')}:</label>
                  <select value={unit.destinationId || ''} disabled={busy}
                    onChange={e => runAction(() => setProductionConfig(unit.id, { destinationId: e.target.value || null }))}>
                    <option value="">— {t('common.none', 'нет')} —</option>
                    {destinationOptions.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </div>
              )}
              <p className="farm-price"><b>{t('prod.trucksOutput', 'Фуры на вывоз')}</b></p>
              {trucks.length === 0 && <p className="farm-hint"><Info size={12} /> {t('prod.noTrucks', 'Фуры не назначены')}</p>}
              {trucks.map(tr => (
                <TruckRow key={tr.id} truck={tr} slot="output" unit={unit} />
              ))}
              {unit.isBakery && (
                <>
                  <p className="farm-price" style={{ marginTop: 8 }}><b>{t('prod.trucksInput', 'Фуры на завоз пшеницы')}</b></p>
                  {trucks.map(tr => <TruckRow key={tr.id} truck={tr} slot="input" unit={unit} />)}
                </>
              )}
              <button className="farm-btn primary" disabled={busy || !unit.destinationId}
                onClick={() => runAction(() => productionHaulNow(unit.id), t('prod.haulNow', 'Отправить фуры'))}>
                <Send size={14} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                {t('prod.haulNow', 'Отправить фуры')}
              </button>
              {!unit.destinationId && <p className="farm-hint"><Info size={12} /> {t('prod.noDestination', 'Получатель не выбран')}</p>}
            </section>
          )}
        </>
      )}
    </div>
  )

  // ── Вложенные рендеры ──

  function SellRow({ res }) {
    const price = prices[res] || 0
    return (
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <input type="number" min="0" step="0.1" style={{ width: 64 }}
          value={sellQty[`${unitId}:${res}`] ?? ''}
          placeholder={`${t('prod.sell', 'Продать')} ($${formatMoney(price)})`}
          onChange={e => setSellQty(s => ({ ...s, [`${unitId}:${res}`]: e.target.value }))} />
        <button className="farm-btn" disabled={busy}
          onClick={() => {
            const qty = Number(sellQty[`${unitId}:${res}`]) || 0
            if (qty <= 0) return
            runAction(() => sellProductionResource(unitId, res, qty), t('prod.sell', 'Продано'))
            setSellQty(s => ({ ...s, [`${unitId}:${res}`]: '' }))
          }}>
          {t('prod.sell', 'Продать')}
        </button>
      </span>
    )
  }

  function TruckRow({ truck, slot }) {
    const assigned = (unit.trucks?.[slot] || []).includes(truck.id)
    const isBusy = !!truck.hauling?.until && new Date(truck.hauling.until) > new Date()
    const toggle = () => {
      const cur = new Set(unit.trucks?.[slot] || [])
      if (cur.has(truck.id)) cur.delete(truck.id)
      else {
        if (cur.size >= 5) { toast(t('prod.trucksHint', { max: 5, minutes: data.tripMinutes }), 'error'); return }
        cur.add(truck.id)
      }
      runAction(() => setProductionTrucks(unit.id, slot, [...cur]))
    }
    return (
      <div className="farm-storage-row">
        <span className="farm-storage-name">🚚 {truck.name} <small>({truck.cargoKg} кг)</small></span>
        <span className="farm-storage-qty">
          {isBusy ? <><Truck size={13} /> {t('prod.truckBusy', 'В рейсе')}</> : ''}
        </span>
        <span className="farm-storage-actions">
          <button className={`farm-btn ${assigned ? 'primary' : ''}`} disabled={busy} onClick={toggle}>
            {assigned ? '✓' : '+'}
          </button>
        </span>
      </div>
    )
  }

  // ── Секция склада: все ресурсы + продажа ──
  function WarehouseSections() {
    const entries = Object.entries(warehouse.storage || {})
    return (
      <section className="farm-block">
        <h3><Package size={16} /> {t('prod.all', 'Все ресурсы')}</h3>
        <p className="farm-price">
          {t('market.capacity', 'Запас')}: <b>{warehouse.used} / {warehouse.cap}</b>
        </p>
        {entries.length === 0 && (
          <p className="farm-hint"><Info size={12} /> {t('prod.nothingToSell', 'Склад пуст — ждёт поставок от источников')}</p>
        )}
        {entries.map(([res, qty]) => (
          <div key={res} className="farm-storage-row">
            <span className="farm-storage-name">
              <span>{RES_EMOJI[res] || '📦'}</span>
              {t(`prod.res_${res}`, res)}
            </span>
            <span className="farm-storage-qty">{qty}</span>
            <span className="farm-storage-actions">
              <SellRow res={res} />
            </span>
          </div>
        ))}
      </section>
    )
  }
}

// Эффективность штата в % (та же формула, что на сервере).
function efficiencyPct(unit) {
  if (!unit || unit.workers <= 0) return 0
  const wf = Math.min(2, unit.workers / Math.max(1, unit.employees || 1))
  const ff = unit.foodDemandPerH > 0 && unit.food < unit.foodDemandPerH ? 0.6 : 1.0
  return Math.round(wf * ff * 100)
}

export default ProductionPanel
