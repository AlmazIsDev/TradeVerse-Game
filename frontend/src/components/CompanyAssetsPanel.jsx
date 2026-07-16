import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  listPropertyForRent, cancelRent, upgradeAsset, fetchMaterialsPrice, buyMaterials,
  fetchMyStudios, buyStudioMaterials, orderStudioJob, fetchCityMap,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import ConfirmDialog from './ConfirmDialog'
import ItStudioOrderModal from './ItStudioOrderModal'
import {
  LayoutGrid, Home, Car, Briefcase, KeyRound, X, Check, AlertTriangle, TrendingUp, Users,
  ArrowUpCircle, Package, Swords, ShieldPlus, Cpu, SlidersHorizontal, ChevronDown,
} from 'lucide-react'

const TABS = [
  { id: 'all', icon: LayoutGrid },
  { id: 'realestate', icon: Home },
  { id: 'car', icon: Car },
  { id: 'business', icon: Briefcase },
]

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

/**
 * Активы компании — интерфейс, аналогичный «Моё имущество», с вкладками и меню
 * «Взаимодействие»: аренда, улучшение, закупка материалов и полноценные заказы
 * IT-студии (атака/защита) прямо из активов компании. Доход идёт в бюджет
 * компании. Управлять может только владелец (сервер проверяет владельца заново).
 */
function CompanyAssetsPanel({ assets = [], isOwner = false, onBalanceChange, onClose, onRefresh }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState('all')
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)
  const [rentModal, setRentModal] = useState(null)
  const [rentForm, setRentForm] = useState({ minHours: '6' })
  const [confirm, setConfirm] = useState(null)                  // { title, message, danger, onConfirm }
  const [menuOpenId, setMenuOpenId] = useState(null)
  const [studios, setStudios] = useState([])
  const [materialsInfo, setMaterialsInfo] = useState(null)
  const [materialsModal, setMaterialsModal] = useState(null)    // business asset
  const [materialsQty, setMaterialsQty] = useState('10')
  const [suppliesModal, setSuppliesModal] = useState(null)      // { asset, studio }
  const [suppliesBizQty, setSuppliesBizQty] = useState('10')
  const [suppliesStudioQty, setSuppliesStudioQty] = useState('10')
  const [orderModal, setOrderModal] = useState(null)            // { mode }
  const [cityMap, setCityMap] = useState(null)
  const [orderBusy, setOrderBusy] = useState(false)
  const menuRef = useRef(null)

  const flash = (text, type = 'success') => { setMsg({ text, type }); setTimeout(() => setMsg(null), 2400) }
  const emojiFor = (a) => ASSET_EMOJI[a.slug] || TYPE_EMOJI[a.type] || '📦'
  const list = tab === 'all' ? assets : assets.filter(a => a.type === tab)

  // IT-студии игрока (в т.ч. переданные компании — запрос идёт по userId).
  const loadStudios = useCallback(() => {
    fetchMyStudios().then(setStudios).catch(() => setStudios([]))
  }, [])
  useEffect(() => { loadStudios() }, [loadStudios])

  // Закрытие меню «Взаимодействие» по клику вне него.
  useEffect(() => {
    if (!menuOpenId) return
    const onClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpenId(null)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [menuOpenId])

  const refreshAll = async () => { await onRefresh?.(); loadStudios() }

  const act = async (id, fn, okKey) => {
    setBusyId(id)
    try {
      const res = await fn(id)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(t(okKey))
      await refreshAll()
    } catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
  }
  const askAct = (id, fn, okKey, conf) => setConfirm({ ...conf, onConfirm: () => act(id, fn, okKey) })

  const doCancel = (id) => askAct(id, cancelRent, 'rent.cancelled', { title: t('rent.list'), message: t('confirm.cancelRent') })

  const submitRent = async () => {
    if (!rentModal) return
    const minHours = Math.floor(Number(rentForm.minHours))
    if (!(minHours >= 1)) { flash(t('rent.invalid'), 'error'); return }
    setBusyId(rentModal.id)
    try {
      await listPropertyForRent(rentModal.id, minHours)
      flash(t('rent.listed'))
      setRentModal(null)
      await refreshAll()
    } catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
  }

  const openMaterials = async (asset) => {
    setMaterialsModal(asset); setMaterialsQty('10')
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
      await refreshAll()
    } catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
  }

  const openSupplies = async (asset) => {
    const studio = studios.find(x => x.assetId === asset.id) || null
    setSuppliesModal({ asset, studio })
    setSuppliesBizQty('10'); setSuppliesStudioQty('10')
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
      await refreshAll()
    } catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
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
      loadStudios()
      setSuppliesModal(m => m && { ...m, studio: res.studio ? { ...m.studio, ...res.studio } : m.studio })
    } catch (err) { flash(err.message, 'error') } finally { setBusyId(null) }
  }

  const openOrder = async (mode) => {
    setOrderModal({ mode })
    if (!cityMap) { try { setCityMap(await fetchCityMap()) } catch { setCityMap(null) } }
  }

  const submitOrder = async (assetId, businessId) => {
    if (!orderModal) return
    setOrderBusy(true)
    try {
      const res = await orderStudioJob(assetId, businessId, orderModal.mode)
      if (res?.balance != null) onBalanceChange?.(res.balance)
      flash(res.readyInMinutes != null
        ? t('itstudio.orderedMinutes', { minutes: res.readyInMinutes })
        : t('itstudio.ordered', { hours: res.readyInHours }))
      setOrderModal(null)
      await refreshAll()
    } catch (err) { flash(err.message, 'error') } finally { setOrderBusy(false) }
  }

  // Действия меню «Взаимодействие» для актива компании (только для владельца).
  const buildActions = (a) => {
    const busy = busyId === a.id
    const isCar = a.type === 'car'
    const actions = []

    if (!isCar) {
      actions.push({
        key: 'upgrade', className: 'upgrade', disabled: busy,
        icon: <ArrowUpCircle size={15} />, label: `${t('myassets.upgrade')} ($${formatMoney(a.upgradeCost)})`,
        onClick: () => askAct(a.id, upgradeAsset, 'myassets.upgraded', { title: t('myassets.upgrade'), message: t('confirm.upgrade', { cost: formatMoney(a.upgradeCost) }) }),
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
        actions.push({
          key: 'itstudio-supplies', disabled: busy, icon: <Package size={15} />,
          label: t('itstudio.buySupplies') + (a.materialsBoostPct > 0 ? ` (+${Math.round(a.materialsBoostPct * 100)}%)` : ''),
          onClick: () => openSupplies(a),
        })
        actions.push({ key: 'itstudio-attack', disabled: busy, icon: <Swords size={15} />, label: t('itstudio.attack'), onClick: () => openOrder('attack') })
        actions.push({ key: 'itstudio-defense', disabled: busy, icon: <ShieldPlus size={15} />, label: t('itstudio.defense'), onClick: () => openOrder('defense') })
      }
    }
    if (a.type === 'realestate' || a.type === 'car' || a.type === 'business') {
      if (a.rental?.status === 'listed') {
        actions.push({ key: 'rent-cancel', disabled: busy, icon: <KeyRound size={15} />, label: t('common.cancel'), onClick: () => doCancel(a.id) })
      } else if (a.rental?.status !== 'rented') {
        actions.push({ key: 'rent-list', disabled: busy, icon: <KeyRound size={15} />, label: t('rent.list'), onClick: () => { setRentModal(a); setRentForm({ minHours: '6' }) } })
      }
    }
    return actions
  }

  const renderRentalStatus = (a) => {
    if (a.rental?.status === 'listed') {
      return <div className="asset-rental listed"><KeyRound size={13} /> {t('rent.waiting')}</div>
    }
    if (a.rental?.status === 'rented') {
      return <div className="asset-rental rented"><KeyRound size={13} /> {t('rent.rented')} · ${formatMoney(a.rental.price)}</div>
    }
    return null
  }

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
        <div className="itstudio-material"><span>{s.material.name}</span><b>{s.material.qty}</b></div>
      </div>
    )
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content company-assets-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <h3><Briefcase size={18} /> {t('company.assets')}</h3>

        <div className="market-cats" style={{ margin: 'var(--spacing-md) 0' }}>
          {TABS.map(tb => {
            const Icon = tb.icon
            return (
              <button key={tb.id} className={`tx-pill ${tab === tb.id ? 'active' : ''}`} onClick={() => setTab(tb.id)}>
                <Icon size={14} /> {tb.id === 'all' ? t('common.all') : t(`market.cat_${tb.id}`)}
              </button>
            )
          })}
        </div>

        {msg && (
          <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
            {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
          </div>
        )}

        <p className="company-note">{t('company.rentNote')}</p>

        {list.length === 0 ? (
          <div className="empty-state">
            <span className="placeholder-icon">{TYPE_EMOJI[tab] || '📦'}</span>
            <p>{t('company.noAssets')}</p>
          </div>
        ) : (
          <div className="asset-grid">
            {list.map(a => {
              const isCar = a.type === 'car'
              const busy = busyId === a.id
              return (
                <div key={a.id} className={`asset-card owned ${isCar ? 'car-card' : ''} ${menuOpenId === a.id ? 'menu-open' : ''}`}>
                  <div className="asset-banner" style={{ background: RARITY_GRAD[a.rarity] || 'linear-gradient(135deg,#334155,#1e293b)' }}>
                    <span className="asset-banner-emoji">{emojiFor(a)}</span>
                    <span className="asset-level">{t('myassets.level')} {a.level}</span>
                  </div>
                  <div className="asset-card-head"><span className="asset-name">{t(`assetNames.${a.slug}`, a.name)}</span></div>
                  <div className="asset-stats">
                    <div className="asset-stat"><span>{t('myassets.value')}</span><b>${formatMoney(a.value)}</b></div>
                    {!isCar && a.profitPerHour !== 0 && (
                      <div className="asset-stat"><span><TrendingUp size={12} /> {t('market.profitPerHour')}</span>
                        <b className={a.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(a.profitPerHour)}</b></div>
                    )}
                    {a.type === 'business' && (
                      <div className="asset-stat"><span><Users size={12} /> {t('market.employees')}</span><b>{a.employees}</b></div>
                    )}
                    {a.rooms != null && <div className="asset-stat"><span>{t('realestate.rooms')}</span><b>{a.rooms}</b></div>}
                  </div>
                  {renderRentalStatus(a)}
                  {renderStudio(a)}

                  {isOwner && (
                    <div className="asset-interact" ref={menuOpenId === a.id ? menuRef : null}>
                      <button className="asset-interact-btn" disabled={busy}
                        onClick={() => setMenuOpenId(id => id === a.id ? null : a.id)}>
                        <SlidersHorizontal size={15} /> {t('myassets.interact')} <ChevronDown size={14} />
                      </button>
                      {menuOpenId === a.id && (
                        <div className="asset-menu">
                          {buildActions(a).map(action => (
                            <button key={action.key} className={`asset-menu-item ${action.className || ''}`}
                              disabled={action.disabled}
                              onClick={action.info ? undefined : () => { action.onClick(); setMenuOpenId(null) }}>
                              {action.icon} {action.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
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
              <p className="modal-price">{t('company.rentDesc')}</p>
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
                <input type="number" min="1" max="500" value={materialsQty} autoFocus onChange={e => setMaterialsQty(e.target.value)} /></div>
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

              <div className="supplies-section">
                <h4 className="supplies-section-title">{t('materials.incomeSection')}</h4>
                <p className="modal-price">{t('materials.desc', { boost: Math.round((materialsInfo?.boostPerUnit || 0) * 100), cap: Math.round((materialsInfo?.boostCap || 0) * 100), hours: materialsInfo?.durationHours || 0 })}</p>
                <p className="modal-price">{t('materials.unitPrice')}: <strong>${formatMoney(materialsInfo?.unitPrice)}</strong></p>
                <div className="modal-quantity"><label>{t('common.quantity')}:</label>
                  <input type="number" min="1" max="500" value={suppliesBizQty} onChange={e => setSuppliesBizQty(e.target.value)} /></div>
                <p className="modal-total">{t('common.total')}: <strong>${formatMoney((Math.floor(Number(suppliesBizQty)) || 0) * (materialsInfo?.unitPrice || 0))}</strong></p>
                <button className="stock-btn buy-btn" onClick={submitSuppliesBiz} disabled={busyId === suppliesModal.asset.id || !materialsInfo}>{t('materials.buy')}</button>
              </div>

              {suppliesModal.studio?.material && (
                <div className="supplies-section">
                  <h4 className="supplies-section-title">{t('itstudio.studioSection')}</h4>
                  <p className="modal-price">{suppliesModal.studio.material.name}: <strong>${formatMoney(suppliesModal.studio.material.unitCost)}</strong> / {t('common.quantity').toLowerCase()} · {t('itstudio.inStock')}: <b>{suppliesModal.studio.material.qty}</b></p>
                  <div className="modal-quantity"><label>{t('common.quantity')}:</label>
                    <input type="number" min="1" max="500" value={suppliesStudioQty} onChange={e => setSuppliesStudioQty(e.target.value)} /></div>
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

        <ConfirmDialog
          open={!!confirm}
          danger={confirm?.danger}
          title={confirm?.title}
          message={confirm?.message}
          onConfirm={() => { confirm?.onConfirm?.(); setConfirm(null) }}
          onCancel={() => setConfirm(null)}
        />
      </div>
    </div>
  )
}

export default CompanyAssetsPanel
