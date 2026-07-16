import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMyAssets, collectAsset, upgradeAsset, sellAsset, fetchCompany,
  transferAssetToCompany, listPropertyForRent, cancelRent, tuneCar,
  fetchMaterialsPrice, buyMaterials,
  fetchMyStudios, buyStudioMaterials, orderStudioJob, fetchCityMap,
  collectAllAssets,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import ConfirmDialog from './ConfirmDialog'
import ItStudioOrderModal from './ItStudioOrderModal'
import {
  Home, Car, Briefcase, ArrowUpCircle, HandCoins, Trash2, AlertTriangle,
  TrendingUp, Users, Wallet, Building2, KeyRound, Check, X, Gauge, LayoutGrid, Wrench, Package,
  Swords, ShieldPlus, Cpu, SlidersHorizontal, ChevronDown,
} from 'lucide-react'

// Детали тюнинга авто (порядок и подписи; стоимость считает сервер).
const TUNE_PARTS = ['engine', 'turbo', 'gearbox', 'suspension', 'brakes', 'tires', 'exhaust']

const TYPE_TABS = [
  { id: 'all', icon: LayoutGrid },
  { id: 'realestate', icon: Home },
  { id: 'car', icon: Car },
  { id: 'business', icon: Briefcase },
]

// «Изображения» объектов (эмодзи-баннеры вместо фото — работает без внешних ассетов)
const ASSET_EMOJI = {
  studio: '🏠', flat2: '🏢', townhouse: '🏘️', villa: '🏖️', penthouse: '🌆', castle: '🏰',
  shawarma: '🌯', coffee: '☕', carwash: '🚿', factory: '🏭',
  itstudio_basic: '💻', itstudio_medium: '💻', itstudio_advanced: '💻', itstudio_premium: '💻',
  citycar: '🚗', sedan: '🚙', sport: '🏎️', super: '🏎️',
}
const TYPE_EMOJI = { realestate: '🏠', business: '🏢', car: '🚗' }

// Пресеты срока аренды (в часах) — кнопки в модалке сдачи в аренду.
const RENT_DURATIONS = [
  { key: 'd1', hours: 24 }, { key: 'd2', hours: 48 }, { key: 'd4', hours: 96 },
  { key: 'd7', hours: 168 }, { key: 'd10', hours: 240 }, { key: 'd12', hours: 288 },
  { key: 'd14', hours: 336 }, { key: 'd16', hours: 384 }, { key: 'd18', hours: 432 },
  { key: 'd30', hours: 720 },
]
const RARITY_GRAD = {
  common: 'linear-gradient(135deg,#334155,#1e293b)',
  uncommon: 'linear-gradient(135deg,#166534,#14532d)',
  rare: 'linear-gradient(135deg,#1e40af,#1e3a8a)',
  epic: 'linear-gradient(135deg,#6b21a8,#4c1d95)',
  legendary: 'linear-gradient(135deg,#b45309,#78350f)',
}

function MyAssetsTab({ defaultType = 'realestate', balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [activeType, setActiveType] = useState(defaultType)
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)
  const [rentModal, setRentModal] = useState(null)   // asset
  const [rentForm, setRentForm] = useState({ minHours: '6' })
  const [tuneModal, setTuneModal] = useState(null)   // car asset
  const [confirm, setConfirm] = useState(null)       // { title, message, danger, onConfirm }
  const [isCompanyOwner, setIsCompanyOwner] = useState(false)
  const [materialsModal, setMaterialsModal] = useState(null)   // business asset
  const [materialsInfo, setMaterialsInfo] = useState(null)     // { unitPrice, boostPerUnit, boostCap }
  const [materialsQty, setMaterialsQty] = useState('10')
  const [studios, setStudios] = useState([])                   // IT-студии игрока (см. cityroof.py mystudios)
  // IT-студия: единая закупка комплектующих (материалы дохода + расходники студии).
  const [suppliesModal, setSuppliesModal] = useState(null)     // { asset, studio }
  const [suppliesBizQty, setSuppliesBizQty] = useState('10')   // материалы буста дохода
  const [suppliesStudioQty, setSuppliesStudioQty] = useState('10') // расходники студии
  const [orderModal, setOrderModal] = useState(null)            // { mode, businessId }
  const [cityMap, setCityMap] = useState(null)
  const [orderBusy, setOrderBusy] = useState(false)
  const [menuOpenId, setMenuOpenId] = useState(null)             // id актива с открытым меню «Взаимодействие»
  const [collectingAll, setCollectingAll] = useState(false)
  const menuRef = useRef(null)

  // Закрытие меню «Взаимодействие» по клику вне него.
  useEffect(() => {
    if (!menuOpenId) return
    const onClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpenId(null)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [menuOpenId])

  // Синхронизируем открытую модалку тюнинга с обновлёнными данными.
  useEffect(() => {
    if (tuneModal) {
      const fresh = assets.find(a => a.id === tuneModal.id)
      if (fresh && fresh !== tuneModal) setTuneModal(fresh)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assets])

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await fetchMyAssets()
      setAssets(data.assets || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // IT-студии: уровень/опыт/материалы/активный заказ — источник правды сервер
  // (см. GET /api/cityroof/itstudio/mystudios), используется и здесь, и в
  // ItStudioOrderModal.
  const loadStudios = useCallback(() => {
    fetchMyStudios().then(setStudios).catch(() => setStudios([]))
  }, [])
  useEffect(() => { loadStudios() }, [loadStudios])

  // Владеет ли игрок компанией — определяет доступность «Передать компании».
  // Проверка дублируется на сервере (см. backend/assets.py transfer_to_company).
  useEffect(() => {
    fetchCompany().then(res => setIsCompanyOwner(!!res?.company?.isOwner)).catch(() => setIsCompanyOwner(false))
  }, [])

  // Аренда заселяется/завершается на сервере (см. backend/assets.py _process_rental) —
  // тихо перечитываем список, без скелетона, чтобы не терять раскрытые модалки.
  useEffect(() => {
    const onRealtime = (ev) => {
      if (ev.detail?.type === 'asset_update') { load(true); loadStudios() }
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [load, loadStudios])

  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 2400)
  }

  const act = async (id, fn, okKey) => {
    setBusyId(id)
    try {
      const res = await fn(id)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t(okKey))
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  // Открыть подтверждение перед действием (act выполнится по «Да»).
  const askAct = (id, fn, okKey, conf) =>
    setConfirm({ ...conf, onConfirm: () => act(id, fn, okKey) })

  const collectAll = async () => {
    setCollectingAll(true)
    try {
      const res = await collectAllAssets()
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(res?.count > 0
        ? t('myassets.collectedAll', { amount: formatMoney(res.collected), count: res.count })
        : t('myassets.nothingToCollect'))
      await load(true)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setCollectingAll(false)
    }
  }

  const submitRent = async () => {
    if (!rentModal) return
    const minHours = Math.floor(Number(rentForm.minHours))
    if (!(minHours >= 1)) { flash(t('rent.invalid'), 'error'); return }
    setBusyId(rentModal.id)
    try {
      await listPropertyForRent(rentModal.id, minHours)
      flash(t('rent.listed'))
      setRentModal(null)
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const openMaterials = async (asset) => {
    setMaterialsModal(asset)
    setMaterialsQty('10')
    try { setMaterialsInfo(await fetchMaterialsPrice()) } catch { setMaterialsInfo(null) }
  }

  const submitMaterials = async () => {
    if (!materialsModal) return
    const qty = Math.floor(Number(materialsQty))
    if (!(qty > 0)) { flash(t('materials.invalid'), 'error'); return }
    setBusyId(materialsModal.id)
    try {
      const res = await buyMaterials(materialsModal.id, qty)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('materials.bought'))
      setMaterialsModal(null)
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  // IT-студия: единая закупка комплектующих. Открывает модалку с обоими
  // видами закупки (материалы дохода бизнеса + расходники студии) — источник
  // цен: fetchMaterialsPrice (доход) и studio.material (студия).
  const openSupplies = async (asset) => {
    const studio = studios.find(x => x.assetId === asset.id) || null
    setSuppliesModal({ asset, studio })
    setSuppliesBizQty('10')
    setSuppliesStudioQty('10')
    try { setMaterialsInfo(await fetchMaterialsPrice()) } catch { setMaterialsInfo(null) }
  }

  const submitSuppliesBiz = async () => {
    if (!suppliesModal) return
    const qty = Math.floor(Number(suppliesBizQty))
    if (!(qty > 0)) { flash(t('materials.invalid'), 'error'); return }
    setBusyId(suppliesModal.asset.id)
    try {
      const res = await buyMaterials(suppliesModal.asset.id, qty)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('materials.bought'))
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const submitSuppliesStudio = async () => {
    if (!suppliesModal) return
    const qty = Math.floor(Number(suppliesStudioQty))
    if (!(qty > 0)) { flash(t('materials.invalid'), 'error'); return }
    setBusyId(suppliesModal.asset.id)
    try {
      const res = await buyStudioMaterials(suppliesModal.asset.id, qty)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('materials.bought'))
      await loadStudios()
      // Обновляем состав студии в открытой модалке (кол-во расходников).
      setSuppliesModal(m => m && { ...m, studio: res.studio ? { ...m.studio, ...res.studio } : m.studio })
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  // Атака/защита требуют карты «Крыши города» (список целей + актуальный
  // конфиг цены/материалов) — подгружаем лениво, только когда открывают заказ.
  const openOrder = async (mode) => {
    setOrderModal({ mode })
    if (!cityMap) {
      try { setCityMap(await fetchCityMap()) } catch { setCityMap(null) }
    }
  }

  const submitOrder = async (assetId, businessId) => {
    if (!orderModal) return
    setOrderBusy(true)
    try {
      const res = await orderStudioJob(assetId, businessId, orderModal.mode)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('itstudio.ordered', { hours: res.readyInHours }))
      setOrderModal(null)
      await loadStudios()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setOrderBusy(false)
    }
  }

  const tuneCost = (car, part) => Math.round((car.price || 0) * 0.05 * ((car.tuning?.[part] || 0) + 1))

  const doTune = async (car, part) => {
    setBusyId(car.id)
    try {
      const res = await tuneCar(car.id, part)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t('tune.done'))
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const list = activeType === 'all' ? assets : assets.filter(a => a.type === activeType)
  const totalValue = list.reduce((s, a) => s + (a.value || 0), 0)
  const totalProfit = list.reduce((s, a) => s + (a.profitPerHour || 0), 0)
  const totalAccrued = list.reduce((s, a) => s + (a.accrued || 0), 0)

  const emojiFor = (a) => ASSET_EMOJI[a.slug] || TYPE_EMOJI[a.type] || '📦'

  // Статус аренды — только инфо-бейдж; сами кнопки (сдать/отменить) вынесены
  // в меню «Взаимодействие» (см. buildActions), чтобы не плодить кнопки на карточке.
  const renderRentalStatus = (a) => {
    if (a.rental?.status === 'listed') {
      return <div className="asset-rental listed"><KeyRound size={13} /> {t('rent.waiting')}</div>
    }
    if (a.rental?.status === 'rented') {
      return <div className="asset-rental rented"><KeyRound size={13} /> {t('rent.rented')} · ${formatMoney(a.rental.price)}</div>
    }
    return null
  }

  // Собирает все применимые к активу действия для меню «Взаимодействие» —
  // раньше это был ряд из 6-7 отдельных кнопок на карточке.
  const buildActions = (a) => {
    const busy = busyId === a.id
    const isCar = a.type === 'car'
    const actions = []

    if (!isCar && a.profitPerHour > 0) {
      actions.push({
        key: 'collect', className: 'collect', disabled: busy || a.accrued <= 0,
        icon: <HandCoins size={15} />, label: t('myassets.collect'),
        onClick: () => askAct(a.id, collectAsset, 'myassets.collected', { title: t('myassets.collect'), message: t('confirm.collect', { amount: formatMoney(a.accrued) }) }),
      })
    }
    if (!isCar) {
      actions.push({
        key: 'upgrade', className: 'upgrade', disabled: busy,
        icon: <ArrowUpCircle size={15} />, label: `${t('myassets.upgrade')} ($${formatMoney(a.upgradeCost)})`,
        onClick: () => askAct(a.id, upgradeAsset, 'myassets.upgraded', { title: t('myassets.upgrade'), message: t('confirm.upgrade', { cost: formatMoney(a.upgradeCost) }) }),
      })
    } else {
      actions.push({
        key: 'tune', className: 'upgrade', disabled: busy,
        icon: <Wrench size={15} />, label: t('tune.title'),
        onClick: () => setTuneModal(a),
      })
    }
    if (a.type === 'business' && !a.slug?.startsWith('itstudio_')) {
      actions.push({
        key: 'materials', disabled: busy, icon: <Package size={15} />,
        label: t('materials.buy') + (a.materialsBoostPct > 0 ? ` (+${Math.round(a.materialsBoostPct * 100)}%)` : ''),
        onClick: () => openMaterials(a),
      })
    }
    if (a.slug?.startsWith('itstudio_')) {
      const s = studios.find(x => x.assetId === a.id)
      if (s?.pendingJob) {
        actions.push({ key: 'itstudio-pending', disabled: true, info: true, icon: <Package size={13} />, label: t('itstudio.pending') })
      } else {
        // IT-студия: единая закупка комплектующих объединяет материалы для
        // буста дохода бизнеса и расходники для атак/защиты студии — оба
        // эффекта сохраняются (см. openSupplies / suppliesModal).
        actions.push({
          key: 'itstudio-supplies', disabled: busy, icon: <Package size={15} />,
          label: t('itstudio.buySupplies') + (a.materialsBoostPct > 0 ? ` (+${Math.round(a.materialsBoostPct * 100)}%)` : ''),
          onClick: () => openSupplies(a),
        })
        actions.push({ key: 'itstudio-attack', disabled: busy, icon: <Swords size={15} />, label: t('itstudio.attack'), onClick: () => openOrder('attack') })
        actions.push({ key: 'itstudio-defense', disabled: busy, icon: <ShieldPlus size={15} />, label: t('itstudio.defense'), onClick: () => openOrder('defense') })
      }
    }
    if (isCompanyOwner) {
      actions.push({
        key: 'toCompany', disabled: busy, icon: <Building2 size={15} />, label: t('myassets.toCompany'),
        onClick: () => askAct(a.id, transferAssetToCompany, 'myassets.transferred', { title: t('myassets.toCompany'), message: t('confirm.transfer', { name: t(`assetNames.${a.slug}`, a.name) }) }),
      })
    }
    if (a.type === 'realestate' || a.type === 'car' || a.type === 'business') {
      if (a.rental?.status === 'listed') {
        actions.push({
          key: 'rent-cancel', disabled: busy, icon: <KeyRound size={15} />, label: t('common.cancel'),
          onClick: () => askAct(a.id, cancelRent, 'rent.cancelled', { title: t('rent.list'), message: t('confirm.cancelRent') }),
        })
      } else if (a.rental?.status !== 'rented') {
        actions.push({
          key: 'rent-list', disabled: busy, icon: <KeyRound size={15} />, label: t('rent.list'),
          onClick: () => { setRentModal(a); setRentForm({ minHours: '6' }) },
        })
      }
    }
    actions.push({
      key: 'sell', className: 'sell', disabled: busy, icon: <Trash2 size={15} />, label: t('myassets.sell'),
      onClick: () => askAct(a.id, sellAsset, 'myassets.sold', { danger: true, title: t('myassets.sell'), message: t('confirm.sell', { name: t(`assetNames.${a.slug}`, a.name), value: formatMoney(a.value) }) }),
    })
    return actions
  }

  // Прокачка/материалы IT-студии (см. cityroof.py studio_progress) — уровень
  // и инвентарь материалов приходят с сервера, отдельно от общего дохода.
  const renderStudio = (a) => {
    if (!a.slug?.startsWith('itstudio_')) return null
    const s = studios.find(x => x.assetId === a.id)
    if (!s) return null
    const xpPct = s.xpToNext == null ? 100 : Math.round(((s.xpPerLevel - s.xpToNext) / s.xpPerLevel) * 100)
    return (
      <div className="itstudio-progress">
        <div className="itstudio-progress-head">
          <span><Cpu size={13} /> {t(`itstudio.tier.${s.tier}`)} · {t('itstudio.level')} {s.level}</span>
          <span className="itstudio-xp">{s.xpToNext == null ? t('itstudio.maxLevel') : `${s.xp} XP`}</span>
        </div>
        {s.xpToNext != null && (
          <div className="itstudio-xp-bar"><div className="itstudio-xp-fill" style={{ width: `${Math.min(100, Math.max(4, xpPct))}%` }} /></div>
        )}
        <div className="itstudio-material">
          <span>{s.material.name}</span>
          <b>{s.material.qty}</b>
        </div>
      </div>
    )
  }

  return (
    <div className="myassets-tab">
      <div className="leaderboard-title-row">
        <Building2 size={22} className="icon" />
        <h2 className="tab-title">{t('nav.myhomes')}</h2>
      </div>

      <div className="market-cats" style={{ marginBottom: 'var(--spacing-lg)' }}>
        {TYPE_TABS.map(tab => {
          const Icon = tab.icon
          return (
            <button key={tab.id} className={`tx-pill ${activeType === tab.id ? 'active' : ''}`}
              onClick={() => setActiveType(tab.id)}>
              <Icon size={14} /> {tab.id === 'all' ? t('common.all') : t(`market.cat_${tab.id}`)}
            </button>
          )
        })}
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      {!loading && !error && list.length > 0 && (
        <div className="asset-summary">
          <div className="asset-summary-card"><span>{t('myassets.totalValue')}</span><b>${formatMoney(totalValue)}</b></div>
          {activeType !== 'car' && <div className="asset-summary-card"><span>{t('myassets.profitPerHour')}</span><b className="up">${formatMoney(totalProfit)}</b></div>}
          {activeType !== 'car' && <div className="asset-summary-card"><span>{t('myassets.readyToCollect')}</span><b className="up">${formatMoney(totalAccrued)}</b></div>}
        </div>
      )}

      {loading && (
        <div className="asset-grid">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="asset-card skeleton" style={{ height: 240 }} />)}
        </div>
      )}

      {error && (
        <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>
      )}

      {!loading && !error && list.length === 0 && (
        <div className="empty-state">
          <span className="placeholder-icon">{TYPE_EMOJI[activeType] || '📦'}</span>
          <p>{t('myassets.empty')}</p>
        </div>
      )}

      {!loading && !error && list.length > 0 && (
        <div className="asset-grid">
          {list.map(a => {
            const busy = busyId === a.id
            const isCar = a.type === 'car'
            return (
              <div key={a.id} className={`asset-card owned ${isCar ? 'car-card' : ''}`}>
                <div className="asset-banner" style={{ background: RARITY_GRAD[a.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}>
                  <span className="asset-banner-emoji">{emojiFor(a)}</span>
                  <span className="asset-level">{t('myassets.level')} {a.level}</span>
                </div>
                <div className="asset-card-head">
                  <span className="asset-name">{t(`assetNames.${a.slug}`, a.name)}</span>
                </div>
                <div className="asset-stats">
                  <div className="asset-stat"><span>{t('myassets.value')}</span><b>${formatMoney(a.value)}</b></div>
                  {!isCar && a.profitPerHour !== 0 && (
                    <div className="asset-stat"><span><TrendingUp size={12} /> {t('market.profitPerHour')}</span>
                      <b className={a.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(a.profitPerHour)}</b></div>
                  )}
                  {a.type === 'business' && (
                    <>
                      <div className="asset-stat"><span><Users size={12} /> {t('market.employees')}</span><b>{a.employees}</b></div>
                      <div className="asset-stat"><span>{t('myassets.upkeep')}</span><b className="down">${formatMoney(a.upkeepPerHour)}/ч</b></div>
                    </>
                  )}
                  {a.rooms != null && <div className="asset-stat"><span>{t('realestate.rooms')}</span><b>{a.rooms}</b></div>}
                  {a.meta?.tax != null && <div className="asset-stat"><span>{t('myassets.tax')}</span><b className="down">${a.meta.tax}/ч</b></div>}
                  {a.meta?.prestige != null && <div className="asset-stat"><span>{t('market.prestige')}</span><b>{a.meta.prestige}</b></div>}
                  {isCar && <div className="asset-stat"><span><Gauge size={12} /> {t('car.condition')}</span><b className="up">{t(`car.cond_${Math.min(a.level, 3)}`, t('car.cond_1'))}</b></div>}
                </div>

                {!isCar && a.profitPerHour > 0 && (
                  <div className="asset-accrued"><Wallet size={14} /> {t('myassets.accrued')}: <b>${formatMoney(a.accrued)}</b></div>
                )}
                {renderRentalStatus(a)}
                {renderStudio(a)}

                <div className="asset-interact" ref={menuOpenId === a.id ? menuRef : null}>
                  <button className="asset-interact-btn" disabled={busy}
                    onClick={() => setMenuOpenId(id => id === a.id ? null : a.id)}>
                    <SlidersHorizontal size={15} /> {t('myassets.interact')} <ChevronDown size={14} />
                  </button>
                  {menuOpenId === a.id && (
                    <div className="asset-menu">
                      {buildActions(a).map(act => (
                        <button key={act.key} className={`asset-menu-item ${act.className || ''}`}
                          disabled={act.disabled}
                          onClick={act.info ? undefined : () => { act.onClick(); setMenuOpenId(null) }}>
                          {act.icon} {act.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {rentModal && (
        <div className="modal-overlay" onClick={() => setRentModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setRentModal(null)}><X size={18} /></button>
            <h3>{t('rent.title')}: {t(`assetNames.${rentModal.slug}`, rentModal.name)}</h3>
            <p className="modal-price">{t('rent.desc')}</p>
            <div className="rent-duration-grid">
              {RENT_DURATIONS.map(d => (
                <button key={d.key} type="button"
                  className={`tx-pill ${Number(rentForm.minHours) === d.hours ? 'active' : ''}`}
                  onClick={() => setRentForm({ ...rentForm, minHours: String(d.hours) })}>
                  {t(`rent.${d.key}`)}
                </button>
              ))}
            </div>
            <div className="modal-quantity"><label>{t('rent.custom')}:</label>
              <input type="number" min="1" max="720" value={rentForm.minHours} onChange={e => setRentForm({ ...rentForm, minHours: e.target.value })} /></div>
            <p className="rent-max-hint">{t('rent.ratePerHour', { rate: formatMoney(rentModal.rentRatePerHour) })}</p>
            <p className="modal-price">{t('rent.total')}: <b>${formatMoney((rentModal.rentRatePerHour || 0) * (Number(rentForm.minHours) || 0))}</b></p>
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={submitRent} disabled={busyId === rentModal.id}>{t('rent.publish')}</button>
              <button className="stock-btn cancel-btn" onClick={() => setRentModal(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </div>
      )}

      {materialsModal && (
        <div className="modal-overlay" onClick={() => setMaterialsModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setMaterialsModal(null)}><X size={18} /></button>
            <h3><Package size={17} /> {t('materials.title')}: {t(`assetNames.${materialsModal.slug}`, materialsModal.name)}</h3>
            <p className="modal-price">{t('materials.desc', { boost: Math.round((materialsInfo?.boostPerUnit || 0) * 100), cap: Math.round((materialsInfo?.boostCap || 0) * 100), hours: materialsInfo?.durationHours || 0 })}</p>
            <p className="modal-price">{t('materials.unitPrice')}: <strong>${formatMoney(materialsInfo?.unitPrice)}</strong></p>
            <div className="modal-quantity"><label>{t('common.quantity')}:</label>
              <input type="number" min="1" max="500" value={materialsQty} autoFocus
                onChange={e => setMaterialsQty(e.target.value)} /></div>
            <p className="modal-total">{t('common.total')}: <strong>${formatMoney((Math.floor(Number(materialsQty)) || 0) * (materialsInfo?.unitPrice || 0))}</strong></p>
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" onClick={submitMaterials} disabled={busyId === materialsModal.id || !materialsInfo}>{t('materials.buy')}</button>
              <button className="stock-btn cancel-btn" onClick={() => setMaterialsModal(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </div>
      )}

      {suppliesModal && (
        <div className="modal-overlay" onClick={() => setSuppliesModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setSuppliesModal(null)}><X size={18} /></button>
            <h3><Package size={17} /> {t('itstudio.buySupplies')}: {t(`assetNames.${suppliesModal.asset.slug}`, suppliesModal.asset.name)}</h3>

            {/* Материалы для буста дохода бизнеса (см. assets.buy_materials). */}
            <div className="supplies-section">
              <h4 className="supplies-section-title">{t('materials.incomeSection')}</h4>
              <p className="modal-price">{t('materials.desc', { boost: Math.round((materialsInfo?.boostPerUnit || 0) * 100), cap: Math.round((materialsInfo?.boostCap || 0) * 100), hours: materialsInfo?.durationHours || 0 })}</p>
              <p className="modal-price">{t('materials.unitPrice')}: <strong>${formatMoney(materialsInfo?.unitPrice)}</strong></p>
              <div className="modal-quantity"><label>{t('common.quantity')}:</label>
                <input type="number" min="1" max="500" value={suppliesBizQty}
                  onChange={e => setSuppliesBizQty(e.target.value)} /></div>
              <p className="modal-total">{t('common.total')}: <strong>${formatMoney((Math.floor(Number(suppliesBizQty)) || 0) * (materialsInfo?.unitPrice || 0))}</strong></p>
              <button className="stock-btn buy-btn" onClick={submitSuppliesBiz} disabled={busyId === suppliesModal.asset.id || !materialsInfo}>{t('materials.buy')}</button>
            </div>

            {/* Расходники студии для атак/защиты (см. cityroof.buy_studio_materials). */}
            {suppliesModal.studio?.material && (
              <div className="supplies-section">
                <h4 className="supplies-section-title">{t('itstudio.studioSection')}</h4>
                <p className="modal-price">{suppliesModal.studio.material.name}: <strong>${formatMoney(suppliesModal.studio.material.unitCost)}</strong> / {t('common.quantity').toLowerCase()} · {t('itstudio.inStock')}: <b>{suppliesModal.studio.material.qty}</b></p>
                <div className="modal-quantity"><label>{t('common.quantity')}:</label>
                  <input type="number" min="1" max="500" value={suppliesStudioQty}
                    onChange={e => setSuppliesStudioQty(e.target.value)} /></div>
                <p className="modal-total">{t('common.total')}: <strong>${formatMoney((Math.floor(Number(suppliesStudioQty)) || 0) * (suppliesModal.studio.material.unitCost || 0))}</strong></p>
                <button className="stock-btn buy-btn" onClick={submitSuppliesStudio} disabled={busyId === suppliesModal.asset.id}>{t('itstudio.buySupplies')}</button>
              </div>
            )}

            <div className="modal-buttons">
              <button className="stock-btn cancel-btn" onClick={() => setSuppliesModal(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </div>
      )}

      {orderModal && (
        <ItStudioOrderModal
          mode={orderModal.mode}
          map={cityMap}
          studios={studios}
          busy={orderBusy}
          onSubmit={submitOrder}
          onClose={() => setOrderModal(null)}
        />
      )}

      {tuneModal && (
        <div className="modal-overlay" onClick={() => busyId !== tuneModal.id && setTuneModal(null)}>
          <div className="modal-content tune-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setTuneModal(null)}><X size={18} /></button>
            <h3><Wrench size={18} /> {t('tune.title')}: {t(`assetNames.${tuneModal.slug}`, tuneModal.name)}</h3>
            <div className="tune-summary">
              <div><span>{t('market.prestige')}</span><b>{tuneModal.meta?.prestige ?? 0}</b></div>
              <div><span>{t('myassets.value')}</span><b>${formatMoney(tuneModal.value)}</b></div>
            </div>
            <div className="tune-parts">
              {TUNE_PARTS.map(part => {
                const lvl = tuneModal.tuning?.[part] || 0
                const max = tuneModal.tuneMaxLevel || 5
                const maxed = lvl >= max
                const cost = tuneCost(tuneModal, part)
                return (
                  <div key={part} className="tune-part">
                    <div className="tune-part-info">
                      <span className="tune-part-name">{t(`tune.parts.${part}`)}</span>
                      <div className="tune-levels">
                        {Array.from({ length: max }).map((_, i) => (
                          <span key={i} className={`tune-pip ${i < lvl ? 'on' : ''}`} />
                        ))}
                      </div>
                    </div>
                    <button className="asset-act upgrade" disabled={busyId === tuneModal.id || maxed}
                      onClick={() => doTune(tuneModal, part)}>
                      {maxed ? t('tune.max') : <>+1 · ${formatMoney(cost)}</>}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirm}
        danger={confirm?.danger}
        title={confirm?.title}
        message={confirm?.message}
        onConfirm={() => { confirm?.onConfirm?.(); setConfirm(null) }}
        onCancel={() => setConfirm(null)}
      />

      {/* Плавающая кнопка «Собрать всю прибыль» — фиксирована по экрану. */}
      <button
        className="collect-all-fab"
        disabled={collectingAll || assets.every(a => (a.accrued || 0) <= 0)}
        onClick={collectAll}
        title={t('myassets.collectAll')}
      >
        <HandCoins size={18} />
        <span>{collectingAll ? t('bank.processing') : t('myassets.collectAll')}</span>
      </button>
    </div>
  )
}

export default MyAssetsTab
