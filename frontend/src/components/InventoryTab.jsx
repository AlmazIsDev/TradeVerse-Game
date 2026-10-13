import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchMyAssets, fetchHardwareInventory, fetchFarms, sellHardware } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import MyAssetsTab from './MyAssetsTab'
import HardwareInventory from './HardwareInventory'
import { toast } from './Toast'
import ConfirmDialog from './ConfirmDialog'
import { Boxes, Home, Cpu, LayoutGrid, TrendingUp, Wallet, HandCoins, Pickaxe, ArrowRight, AlertTriangle } from 'lucide-react'

// Страницы инвентаря: обзор → имущество (активы) → железо (оборудование).
const PAGES = [
  { id: 'overview', icon: LayoutGrid },
  { id: 'assets', icon: Home },
  { id: 'hardware', icon: Cpu },
]

/**
 * Вкладка «Инвентарь» — всё, чем владеет игрок, разбитое по страницам:
 *  - «Обзор» — сводные цифры по имуществу/железу/фермам и быстрые переходы;
 *  - «Имущество» — полноценный список активов (переиспользует MyAssetsTab
 *    со всеми его действиями: аренда, тюнинг, улучшение, продажа…);
 *  - «Железо» — единицы оборудования (HardwareInventory): свободное и
 *    установленное, состояние, категории, поиск.
 */
function InventoryTab({ balance = 0, onBalanceChange, onTabChange }) {
  const { t } = useTranslation()
  const [page, setPage] = useState('overview')
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hwItems, setHwItems] = useState(null)   // список железа — грузится лениво
  const [sellConfirm, setSellConfirm] = useState(null)

  // Продать железо государству (как активы): 65% цены покупки за единицу.
  const handleSellHardware = (item) => {
    const qty = item.qty || 1
    const refund = Math.round((item.purchasePrice || 0) * 0.65 * qty * 100) / 100
    setSellConfirm({
      title: t('inventory.sellTitle'),
      message: t('inventory.sellMsg', { name: item.name, n: qty, price: formatMoney(refund) }),
      onConfirm: async () => {
        try {
          const res = await sellHardware(item.itemId, qty)
          toast(t('inventory.sold', { price: formatMoney(res?.sold ?? refund) }))
          setHwItems(null)   // перечитается эффектом страницы «Железо»
        } catch (err) {
          toast(err.message, 'error')
        }
      },
    })
  }

  // Сводка для «Обзора»: три запроса параллельно, сбои не ломают страницу.
  const loadSummary = useCallback(async () => {
    setLoading(true)
    setError(null)
    const [assets, hw, farms] = await Promise.allSettled([fetchMyAssets(), fetchHardwareInventory(), fetchFarms()])
    if (assets.status === 'rejected' && hw.status === 'rejected' && farms.status === 'rejected') {
      setError(assets.reason?.message || t('common.error'))
    }
    const list = assets.status === 'fulfilled' ? (assets.value.assets || []) : []
    const items = hw.status === 'fulfilled' ? (hw.value.items || []) : []
    const farmList = farms.status === 'fulfilled' ? (farms.value || []) : []
    setSummary({
      assets: list,
      hw: items,
      farms: farmList,
    })
    setLoading(false)
  }, [t])

  useEffect(() => { if (page === 'overview') loadSummary() }, [page, loadSummary])

  // Железо грузим один раз при первом открытии страницы «Железо».
  useEffect(() => {
    if (page !== 'hardware' || hwItems) return
    fetchHardwareInventory()
      .then(d => setHwItems(d.items || []))
      .catch(err => { toast(err.message, 'error'); setHwItems([]) })
  }, [page, hwItems])

  if (page === 'assets') {
    return <MyAssetsTab defaultType="all" balance={balance} onBalanceChange={onBalanceChange} />
  }

  const s = summary
  const assetsValue = s ? s.assets.reduce((acc, a) => acc + (a.value || 0), 0) : 0
  const assetsProfit = s ? s.assets.reduce((acc, a) => acc + (a.profitPerHour || 0), 0) : 0
  const assetsAccrued = s ? s.assets.reduce((acc, a) => acc + (a.accrued || 0), 0) : 0
  const hwQty = (h) => h.qty || 1
  const hwUnits = s ? s.hw.reduce((acc, h) => acc + hwQty(h), 0) : 0
  const hwValue = s ? s.hw.reduce((acc, h) => acc + (h.purchasePrice || 0) * hwQty(h), 0) : 0
  const hwFree = s ? s.hw.filter(h => !h.farmId).reduce((acc, h) => acc + hwQty(h), 0) : 0
  const farmsActive = s ? s.farms.filter(f => f.status === 'mining').length : 0

  return (
    <div className="inventory-tab">
      <div className="leaderboard-title-row">
        <Boxes size={22} className="icon" />
        <h2 className="tab-title">{t('nav.inventory')}</h2>
      </div>

      <div className="market-cats" style={{ marginBottom: 'var(--spacing-lg)' }}>
        {PAGES.map(p => {
          const Icon = p.icon
          return (
            <button key={p.id} className={`tx-pill ${page === p.id ? 'active' : ''}`} onClick={() => setPage(p.id)}>
              <Icon size={14} /> {t(`inventory.page_${p.id}`)}
            </button>
          )
        })}
      </div>

      {page === 'hardware' && (
        hwItems == null
          ? <div className="loading-state"><div className="spinner" /><p>{t('common.loading')}</p></div>
          : <HardwareInventory items={hwItems} busy={!!sellConfirm} onSell={handleSellHardware} />
      )}

      {page === 'overview' && (
        <>
          {loading && <div className="loading-state"><div className="spinner" /><p>{t('common.loading')}</p></div>}
          {error && !loading && (
            <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>
          )}
          {!loading && !error && s && (
            <>
              <div className="asset-summary">
                <div className="asset-summary-card"><span>{t('inventory.ovAssets')}</span><b>${formatMoney(assetsValue)}</b><small>{t('inventory.ovUnits', { n: s.assets.length })}</small></div>
                <div className="asset-summary-card"><span><TrendingUp size={12} /> {t('myassets.profitPerHour')}</span><b className="up">${formatMoney(assetsProfit)}</b></div>
                <div className="asset-summary-card"><span><HandCoins size={12} /> {t('myassets.readyToCollect')}</span><b className="up">${formatMoney(assetsAccrued)}</b></div>
              </div>
              <div className="asset-summary">
                <div className="asset-summary-card"><span>{t('inventory.ovHardware')}</span><b>${formatMoney(hwValue)}</b><small>{t('inventory.ovUnits', { n: s.hw.length })} · {t('inventory.free')} {hwFree}</small></div>
                <div className="asset-summary-card"><span><Pickaxe size={12} /> {t('nav.mining')}</span><b>{t('inventory.ovFarms', { n: s.farms.length, active: farmsActive })}</b></div>
                <div className="asset-summary-card"><span><Wallet size={12} /> {t('myassets.value')}</span><b>${formatMoney(balance)}</b></div>
              </div>

              <div className="inv-links">
                <button className="inv-link" onClick={() => setPage('assets')}>
                  <Home size={18} />
                  <span className="inv-link-text">
                    <b>{t('inventory.page_assets')}</b>
                    <small>{t('inventory.ovUnits', { n: s.assets.length })} · ${formatMoney(assetsValue)}</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button className="inv-link" onClick={() => setPage('hardware')}>
                  <Cpu size={18} />
                  <span className="inv-link-text">
                    <b>{t('inventory.page_hardware')}</b>
                    <small>{t('inventory.ovUnits', { n: hwUnits })} · ${formatMoney(hwValue)}</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button className="inv-link" onClick={() => onTabChange?.('mining')}>
                  <Pickaxe size={18} />
                  <span className="inv-link-text">
                    <b>{t('nav.mining')}</b>
                    <small>{t('inventory.ovFarms', { n: s.farms.length, active: farmsActive })}</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
              </div>
            </>
          )}
        </>
      )}

      <ConfirmDialog
        open={!!sellConfirm}
        title={sellConfirm?.title}
        message={sellConfirm?.message}
        onConfirm={() => { const h = sellConfirm?.onConfirm; setSellConfirm(null); h?.() }}
        onCancel={() => setSellConfirm(null)}
      />
    </div>
  )
}

export default InventoryTab
