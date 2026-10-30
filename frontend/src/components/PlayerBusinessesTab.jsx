// ─────────────────────────────────────────────────────────────────────────────
// PlayerBusinessesTab · вкладка «Бизнесы игроков».
// Витрина опубликованных магазинов заводов видеокарт: GET /api/production/gpu-shops/published.
// Покупка: POST /api/production/{unitId}/gpu-shop/buy. Себестоимость покупателю не показывается.
// ─────────────────────────────────────────────────────────────────────────────
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Handshake, Loader2, Store } from 'lucide-react'
import { fetchPublishedGpuShops, buyGpuShopItem } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'

function PlayerBusinessesTab() {
  const { t } = useTranslation()
  const [shops, setShops] = useState([])
  const [loading, setLoading] = useState(true)
  const [qtys, setQtys] = useState({})
  const [busyKey, setBusyKey] = useState(null)

  const load = useCallback(async () => {
    try {
      const res = await fetchPublishedGpuShops()
      setShops(res.shops || [])
    } catch (e) {
      toast(e?.message || t('gpuShop.error'), 'error')
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])

  const keyOf = (unitId, itemId) => `${unitId}:${itemId}`

  const buy = async (shop, it) => {
    const key = keyOf(shop.unitId, it.id)
    const qty = Math.floor(Number(qtys[key] ?? 1))
    if (!Number.isFinite(qty) || qty < 1 || qty > it.availableQty) {
      toast(t('gpuShop.qtyRange', { max: it.availableQty }), 'error')
      return
    }
    setBusyKey(key)
    try {
      const res = await buyGpuShopItem(shop.unitId, it.id, qty)
      toast(t('gpuShop.bought', { qty: res.qty, amount: formatMoney(res.amount) }), 'success')
    } catch (e) {
      toast(e?.message || t('gpuShop.error'), 'error')
    } finally {
      setBusyKey(null)
      await load()
    }
  }

  return (
    <div className="cars-tab market-tab player-businesses-tab">
      <h2 className="tab-title">
        <Handshake size={22} style={{ verticalAlign: '-4px', marginRight: 8 }} />
        {t('gpuShop.tabTitle')}
      </h2>

      {loading && <div className="empty-state"><Loader2 size={24} className="spin" /></div>}

      {!loading && shops.length === 0 && (
        <div className="empty-state"><p>{t('gpuShop.emptyPlayers')}</p></div>
      )}

      {!loading && shops.map(shop => (
        <div key={shop.unitId} className="gpu-shop-card">
          <div className="gpu-shop-head">
            <Store size={16} />
            <span>{t('gpuShop.owner')}: <b>{shop.ownerName}</b></span>
            {shop.isOwn && <span className="gpu-shop-own">{t('gpuShop.ownShop')}</span>}
          </div>

          <table className="gpu-shop-table">
            <tbody>
              {shop.items.map(it => {
                const key = keyOf(shop.unitId, it.id)
                const canBuy = !shop.isOwn && it.available && it.availableQty > 0
                return (
                  <tr key={it.id}>
                    <td className="gpu-shop-name">{t(`gpuShop.items.${it.id}`, it.id)}</td>
                    <td>{t('gpuShop.price')}: <b>${formatMoney(it.price)}</b></td>
                    <td className={it.available ? '' : 'gpu-shop-closed'}>
                      {it.available ? t('gpuShop.inStock', { count: it.availableQty }) : t('gpuShop.outOfStock')}
                    </td>
                    <td className="gpu-shop-actions">
                      {!shop.isOwn && (
                        <>
                          <input
                            type="number"
                            min="1"
                            max={it.availableQty}
                            className="gpu-shop-qty-input"
                            aria-label={t('gpuShop.qty')}
                            value={qtys[key] ?? 1}
                            disabled={!canBuy || busyKey === key}
                            onChange={e => setQtys({ ...qtys, [key]: e.target.value })}
                          />
                          <button className="farm-btn primary"
                            disabled={!canBuy || busyKey === key}
                            onClick={() => buy(shop, it)}>
                            {t('gpuShop.buy')}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

export default PlayerBusinessesTab
