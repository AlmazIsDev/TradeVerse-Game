// FarmPanel · управление полем (источник category='field').
// Рендерится в MyAssetsTab вместо списка активов, когда пользователь открыл
// конкретное поле через меню «Взаимодействие».
//
//数据来源:
//   GET /api/farm/catalog  — справочник культур, цены клеток/топлива, потолок склада
//   GET /api/farm/my       — сводка: поля (с детализацией клеток), машины, топливо
// Действия:
//   POST /api/farm/plant           — посадить культуру (требует трактор + топливо)
//   POST /api/farm/harvest         — собрать урожай в склад (требует комбайн + топливо)
//   POST /api/farm/cells/buy       — купить блок клеток (экспоненциальная цена)
//   POST /api/farm/fuel/buy        — купить топливо за деньги
//   POST /api/farm/sell-storage    — продать культуру со склада за деньги
//
// Сетка клеток рендерится как CSS Grid side×side (50×50 = 2500 клеток).
// Кнопки «Посадить всё / Собрать всё» шлют пустой cellIndices — сервер
// обработает все подходящие клетки за один прогон.

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, Sprout, Package, Fuel, Coins, Info, AlertTriangle, Loader2, Truck } from 'lucide-react'
import {
  fetchFarmCatalog, fetchMyFarm, buyFarmCells, farmPlant, farmHarvest,
  buyFuel, sellStorage,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'
import Tooltip from './Tooltip'

// Эмодзи культур (по cropId) — для сетки и склада.
const CROP_EMOJI = {
  wheat: '🌾',
  carrot: '🥕',
  potato: '🥔',
  sunflower: '🌻',
}
// Цвета культур для подсветки клеток в сетке.
const CROP_COLOR = {
  wheat: '#eab308',
  carrot: '#f97316',
  potato: '#a16207',
  sunflower: '#facc15',
}

function FarmPanel({ assetId, assetName, onBack, onOpenProduction, balance, onBalanceChange }) {
  const { t } = useTranslation()
  const [catalog, setCatalog] = useState(null)
  const [farm, setFarm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [selectedCrop, setSelectedCrop] = useState('wheat')
  const [cellsBlocks, setCellsBlocks] = useState(1)
  const [fuelLiters, setFuelLiters] = useState('100')
  const [sellQty, setSellQty] = useState({})
  // Индекс обновления таймера (обновляем ready/growing каждые 10 сек).
  const [tick, setTick] = useState(0)

  const load = useCallback(async () => {
    // Грузим параллельно, но ошибки обрабатываем независимо: падение одного
    // эндпоинта не должно блокировать отображение другого, иначе при
    // сетевом сбое пользователь видит пустую панель и непонятный тост.
    setLoading(true)
    await Promise.all([
      fetchFarmCatalog()
        .then(c => setCatalog(c))
        .catch(err => {
          toast(`Каталог фермы: ${err?.message || t('common.error', 'Ошибка')}`, 'error')
        }),
      fetchMyFarm()
        .then(m => setFarm(m))
        .catch(err => {
          toast(`Данные фермы: ${err?.message || t('common.error', 'Ошибка')}`, 'error')
        }),
    ])
    setLoading(false)
  }, [t])

  useEffect(() => { load() }, [load])

  // Таймер: каждые 10 секунд обновляем состояние, чтобы growing → ready
  // переключались без ручного запроса.
  useEffect(() => {
    // Каждые 5 сек — этого хватает, чтобы обратный отсчёт и прогресс-бары
    // клеток/машин пересчитывались без ручного запроса к серверу.
    const id = setInterval(() => setTick(k => k + 1), 30000)
    return () => clearInterval(id)
  }, [])

  const field = useMemo(() => {
    if (!farm) return null
    return (farm.fields || []).find(f => f.assetId === assetId) || null
  }, [farm, assetId])

  const tractor = useMemo(() => {
    if (!farm) return null
    const v = (farm.machines || []).find(m => m.itemId?.startsWith('tractor_'))
    if (!v) return null
    return { ...v, kind: 'tractor' }
  }, [farm])
  const combine = useMemo(() => {
    if (!farm) return null
    const v = (farm.machines || []).find(m => m.itemId?.startsWith('combine_'))
    if (!v) return null
    return { ...v, kind: 'combine' }
  }, [farm])

  const fuel = farm?.fuel ?? 0
  const cellsInfo = catalog?.cells || {}
  const cellsAlreadyBought = field
    ? Math.max(0, (field.totalCells || 0) - (cellsInfo.startTotal || 0))
    : 0
  const cellsBuyStep = cellsInfo.buyStep || 100
  const cellsUnitCost = useMemo(() => {
    if (!cellsInfo.buyBase) return 0
    return cellsInfo.buyBase * Math.pow(cellsInfo.buyScale || 1, cellsAlreadyBought / cellsBuyStep)
  }, [cellsInfo, cellsAlreadyBought, cellsBuyStep])
  const cellsTotalCost = Math.round(cellsUnitCost * cellsBlocks * 100) / 100
  const fuelPrice = catalog?.fuel?.pricePerLiter ?? 0
  // Считаем как бэкенд: литры округляются вверх до пачки (fuel.bundleSize),
  // иначе превью расходится с реальным списанием.
  const fuelBundle = catalog?.fuel?.bundleSize ?? 100
  const fuelLitersRounded = Math.max(
    fuelBundle,
    Math.ceil((Number(fuelLiters) || 0) / fuelBundle) * fuelBundle,
  )
  const fuelTotal = Math.round(fuelLitersRounded * fuelPrice * 100) / 100
  const storageCap = catalog?.storage?.perResource ?? 4000

  // Действия.
  const runAction = async (fn, okMsg) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res && typeof res.balance === 'number' && onBalanceChange) onBalanceChange(res.balance)
      if (okMsg) toast(okMsg, 'success')
      await load()
    } catch (e) {
      toast(e?.message || t('common.error', 'Ошибка'), 'error')
    } finally {
      setBusy(false)
    }
  }

  const doPlantAll = () =>
    runAction(() => farmPlant(assetId, selectedCrop), t('farm.planted', 'Посадка запущена'))
  const doHarvestAll = () =>
    runAction(() => farmHarvest(assetId), t('farm.harvested', 'Сбор завершён'))
  const doBuyCells = () =>
    runAction(() => buyFarmCells(assetId, cellsBlocks), t('farm.cellsBought', 'Участок куплен'))
  const doBuyFuel = () =>
    runAction(() => buyFuel(Math.max(1, Math.floor(Number(fuelLiters) || 0))), t('farm.fuelBought', 'Топливо куплено'))
  const doSellStorage = async (cropId) => {
    const qty = Math.max(0, Number(sellQty[cropId]) || 0)
    if (qty <= 0) return
    await runAction(() => sellStorage(assetId, cropId, qty), t('farm.storageSold', 'Культура продана'))
    // Сброс поля: иначе устаревшее число уедет в следующую продажу
    // (бэкенд при qty > остатка теперь отвечает 400).
    setSellQty(s => ({ ...s, [cropId]: '' }))
  }

  // Статус клетки с локальным пересчётом (растёт 'growing' → 'ready' без
  // запроса к серверу). Возвращает { status, progress (0..1), readyMs }.
  const cellInfoOf = (c) => {
    if (c.crop && c.readyAt) {
      const plantedMs = c.plantedAt ? new Date(c.plantedAt).getTime() : null
      const readyMs = new Date(c.readyAt).getTime()
      const now = Date.now()
      if (readyMs <= now) return { status: 'ready', progress: 1, readyMs }
      if (plantedMs) {
        const total = Math.max(1, readyMs - plantedMs)
        const done = Math.max(0, now - plantedMs)
        return { status: 'growing', progress: Math.min(1, done / total), readyMs }
      }
    }
    return { status: c.status || 'empty', progress: 0, readyMs: null }
  }
  // Локальный снимок статуса (для подсветки/легенды).
  const cellStatusOf = (c) => cellInfoOf(c).status
  // Форматирует оставшееся время в мм:сс / чч:мм.
  const fmtRemain = (ms) => {
    if (ms == null) return ''
    const s = Math.max(0, Math.round(ms / 1000))
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    const ss = s % 60
    if (h > 0) return `${h}ч ${m}м`
    if (m > 0) return `${m}м ${ss}с`
    return `${ss}с`
  }

  return (
    <div className="farm-panel">
      <div className="source-panel-actions">
        <button className="asset-interact-btn" onClick={onBack} title={t('common.back')}>
          <ChevronLeft size={16} /> {t('common.back')}
        </button>
        {onOpenProduction && (
          <button className="asset-interact-btn" onClick={onOpenProduction} title={t('prod.manage', 'Управление производством')}>
            <Truck size={16} /> {t('prod.manage', 'Управление производством')}
          </button>
        )}
      </div>
      <div className="source-panel-title">
        <Sprout size={22} className="icon" />
        <h2 className="tab-title">{t('farm.manage', 'Управление полем')}: {assetName}</h2>
      </div>

      {loading ? (
        <div className="empty-state"><Loader2 size={24} className="spin" /> {t('common.loading', 'Загрузка…')}</div>
      ) : !field ? (
        <div className="empty-state">
          <AlertTriangle size={24} />
          <p>{t('farm.noField', 'Поле ещё не создано. Купите участок в разделе «Рынок».')}</p>
        </div>
      ) : (
        <>
          {/* Сводка ресурсов */}
          <div className="farm-summary">
            <div className="farm-summary-card">
              <span>{t('farm.fuel', 'Топливо')}</span>
              <b><Fuel size={14} style={{ verticalAlign: '-2px', marginRight: 4 }} />{fuel.toFixed(0)} л</b>
            </div>
            <div className="farm-summary-card">
              <span>{t('farm.tractor', 'Трактор')}</span>
              {tractor ? (tractor.busy ? (
                <>
                  <b>{t('farm.busy', 'Занят')} · {fmtRemain(tractor.remainingMinutes * 60000)}</b>
                  <div className="farm-bar"><div className="farm-bar-fill" style={{ width: '100%' }} /></div>
                </>
              ) : <b>{t('farm.free', 'Свободен')}</b>) : <b>{t('farm.noVehicle', 'Нет')}</b>}
            </div>
            <div className="farm-summary-card">
              <span>{t('farm.combine', 'Комбайн')}</span>
              {combine ? (combine.busy ? (
                <>
                  <b>{t('farm.busy', 'Занят')} · {fmtRemain(combine.remainingMinutes * 60000)}</b>
                  <div className="farm-bar"><div className="farm-bar-fill" style={{ width: '100%' }} /></div>
                </>
              ) : <b>{t('farm.free', 'Свободен')}</b>) : <b>{t('farm.noVehicle', 'Нет')}</b>}
            </div>
            <div className="farm-summary-card">
              <span>{t('farm.cells', 'Клетки')}</span>
              <b>{field.empty}/{field.totalCells}</b>
            </div>
          </div>

          {/* Активные посевы: прогресс по каждой культуре + ETA ближайшего */}
          {(() => {
            const groups = {}
            let nearestMs = null
            for (const c of (field.cells || [])) {
              const info = cellInfoOf(c)
              if (info.status !== 'growing' || !c.crop) continue
              if (!groups[c.crop]) groups[c.crop] = { count: 0, nearest: null }
              groups[c.crop].count += 1
              if (info.readyMs != null) {
                if (groups[c.crop].nearest == null || info.readyMs < groups[c.crop].nearest) {
                  groups[c.crop].nearest = info.readyMs
                }
                if (nearestMs == null || info.readyMs < nearestMs) nearestMs = info.readyMs
              }
            }
            const entries = Object.entries(groups)
            if (entries.length === 0) return null
            return (
              <div className="farm-summary farm-crops-progress">
                {entries.map(([cropId, g]) => {
                  const remain = g.nearest != null ? Math.max(0, g.nearest - Date.now()) : 0
                  return (
                    <div key={cropId} className="farm-summary-card">
                      <span>
                        <span style={{ marginRight: 4 }}>{CROP_EMOJI[cropId] || '🌾'}</span>
                        {t(`farm.crop_${cropId}`, cropId)} · {g.count}
                      </span>
                      <b>{remain > 0 ? fmtRemain(remain) : t('farm.ready', 'Готово')}</b>
                    </div>
                  )
                })}
              </div>
            )
          })()}

          <div className="farm-body">
            {/* Текстовая сводка по клеткам вместо 2500 DOM-нод сетки.
                Вся информация (что растёт, сколько осталось) тут же. */}
            <div className="farm-grid-wrap">
              <div className="farm-text-summary">
                <div className="farm-text-row">
                  <span className="farm-text-label">{t('farm.empty', 'Пустая')}</span>
                  <b className="farm-text-val">{field.empty || 0}</b>
                </div>
                <div className="farm-text-row">
                  <span className="farm-text-label">{t('farm.growing', 'Выращивается')}</span>
                  <b className="farm-text-val">{field.growing || 0}</b>
                </div>
                <div className="farm-text-row">
                  <span className="farm-text-label">{t('farm.ready', 'Готово')}</span>
                  <b className="farm-text-val farm-text-ready">{field.ready || 0}</b>
                </div>
                <div className="farm-text-row">
                  <span className="farm-text-label">{t('farm.cells', 'Всего клеток')}</span>
                  <b className="farm-text-val">{field.totalCells || 0}</b>
                </div>
              </div>
            </div>

            {/* Правая колонка: управление */}
            <div className="farm-side">
              {/* Посадка */}
              <section className="farm-block">
                <h3><Sprout size={16} /> {t('farm.plant', 'Посадка')}</h3>
                <div className="farm-crop-picker">
                  {Object.entries(CROP_EMOJI).map(([id, emoji]) => (
                    <button key={id}
                      className={`farm-crop-chip ${selectedCrop === id ? 'active' : ''}`}
                      onClick={() => setSelectedCrop(id)}>
                      <span>{emoji}</span>
                      <span>{t(`farm.crop_${id}`, id)}</span>
                    </button>
                  ))}
                </div>
                <button className="farm-btn primary" disabled={busy || !tractor || tractor.busy}
                  onClick={doPlantAll}>
                  {t('farm.plantAll', 'Посадить всё')}
                </button>
                {!tractor && <p className="farm-hint"><Info size={12} /> {t('farm.needTractor', 'Купить трактор в «Автосалон → Ферма」')}</p>}
              </section>

              {/* Сбор */}
              <section className="farm-block">
                <h3><Sprout size={16} /> {t('farm.harvest', 'Сбор')}</h3>
                <button className="farm-btn primary" disabled={busy || !combine || combine.busy || field.ready === 0}
                  onClick={doHarvestAll}>
                  {t('farm.harvestAll', 'Собрать всё готовое')}
                </button>
                {!combine && <p className="farm-hint"><Info size={12} /> {t('farm.needCombine', 'Купить комбайн в «Автосалон → Ферма」')}</p>}
              </section>

              {/* Склад */}
              <section className="farm-block">
                <h3><Package size={16} /> {t('farm.storage', 'Склад')}</h3>
                {field.storage && Object.keys(field.storage).length > 0 ? (
                  <div className="farm-storage-list">
                    {Object.entries(field.storage).map(([cropId, qty]) => (
                      <div key={cropId} className="farm-storage-row">
                        <span className="farm-storage-name">
                          <span>{CROP_EMOJI[cropId] || '🌾'}</span>
                          {t(`farm.crop_${cropId}`, cropId)}
                        </span>
                        <span className="farm-storage-qty">{qty.toFixed(1)} / {storageCap}</span>
                        <div className="farm-storage-actions">
                          <input type="number" min="0" max={qty} step="0.1"
                            value={sellQty[cropId] ?? qty.toFixed(1)}
                            onChange={e => setSellQty(s => ({ ...s, [cropId]: e.target.value }))}
                            style={{ width: 64 }} />
                          <button className="farm-btn" disabled={busy}
                            onClick={() => doSellStorage(cropId)}>
                            {t('farm.sell', 'Продать')}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="farm-hint"><Info size={12} /> {t('farm.storageEmpty', 'Склад пуст')}</p>
                )}
              </section>

              {/* Докупка клеток */}
              <section className="farm-block">
                <h3><Sprout size={16} /> {t('farm.buyCells', 'Купить участок')}</h3>
                <div className="farm-input-row">
                  <label>{t('farm.blocks', 'Блоки')} ({cellsBuyStep} м²/блок):<Tooltip text={t('farm.blocksHelp')} /></label>
                  <input type="number" min="1" max={cellsInfo.maxBlocks || 100} value={cellsBlocks}
                    onChange={e => setCellsBlocks(Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
                </div>
                <p className="farm-price">
                  {t('farm.unitCost', 'Цена за блок')}: <b>${formatMoney(cellsUnitCost)}</b>
                  {' · '}{t('common.total', 'Итого')}: <b className="up">${formatMoney(cellsTotalCost)}</b>
                </p>
                <button className="farm-btn primary" disabled={busy || balance < cellsTotalCost}
                  onClick={doBuyCells}>
                  {t('common.buy', 'Купить')}
                </button>
              </section>

              {/* Покупка топлива */}
              <section className="farm-block">
                <h3><Fuel size={16} /> {t('farm.buyFuel', 'Купить топливо')}</h3>
                <div className="farm-input-row">
                  <label>{t('farm.liters', 'Литры')}:<Tooltip text={t('farm.litersHelp')} /></label>
                  <input type="number" min="1" max={100000} value={fuelLiters}
                    onChange={e => setFuelLiters(e.target.value)} />
                </div>
                <p className="farm-price">
                  {t('farm.pricePerLiter', 'Цена за литр')}: <b>${formatMoney(fuelPrice)}</b>
                  {' · '}{t('common.total', 'Итого')}: <b className="up">${formatMoney(fuelTotal)}</b>
                </p>
                <button className="farm-btn primary" disabled={busy || balance < fuelTotal}
                  onClick={doBuyFuel}>
                  {t('common.buy', 'Купить')}
                </button>
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default FarmPanel
