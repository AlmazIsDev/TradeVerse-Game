// ─────────────────────────────────────────────────────────────────────────────
// PlayerBusinessesTab · вкладка «Бизнесы игроков».
// Витрина опубликованных магазинов заводов видеокарт: GET /api/production/gpu-shops/published.
// Покупка: POST /api/production/{unitId}/gpu-shop/buy. Себестоимость покупателю не показывается.
// ─────────────────────────────────────────────────────────────────────────────
//
// ВРЕМЕННО ОТКЛЮЧЕНО: раздел закрыт на доработку, вместо витрины выводится
// заглушка «Данный раздел временно недоступен». Загрузка магазинов не
// выполняется. Для возврата витрины поставьте SECTION_TEMP_DISABLED = false.
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Handshake, Loader2, Store, Wrench } from 'lucide-react'
import { fetchPublishedGpuShops, buyGpuShopItem } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'

const SECTION_TEMP_DISABLED = true

function PlayerBusinessesTab() {
  const { t } = useTranslation()
  const [shops, setShops] = useState([])
  const [loading, setLoading] = useState(!SECTION_TEMP_DISABLED)
  const [qtys, setQtys] = useState({})
  const [busyKey, setBusyKey] = useState(null)

  const load = useCallback(async () => {
    if (SECTION_TEMP_DISABLED) return
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

  // Пустое поле ввода — это «1 по умолчанию», а не ноль: Number('') === 0
  // давал ложную ошибку диапазона при очистке инпута.
  const qtyOf = (key) => {
    const raw = String(qtys[key] ?? '').trim()
    if (raw === '') return 1
    const n = Number(raw)
    return Number.isFinite(n) ? Math.floor(n) : NaN
  }

  const buy = async (shop, it) => {
    const key = keyOf(shop.unitId, it.id)
    const qty = qtyOf(key)
    if (!Number.isFinite(qty) || qty < 1 || qty > it.availableQty) {
      toast(t('gpuShop.qtyRange', { max: it.availableQty }), 'error')
      return
    }
    setBusyKey(key)
    try {
      const res = await buyGpuShopItem(shop.unitId, it.id, qty)
      toast(t('gpuShop.bought', { qty: res.qty, amount: formatMoney(res.amount) }), 'success')
      // Сбрасываем количество: иначе следующая покупка уходит тем же числом
      // и падает, если остаток на складе уменьшился.
      setQtys(prev => ({ ...prev, [key]: 1 }))
    } catch (e) {
      toast(e?.message || t('gpuShop.error'), 'error')
    } finally {
      // Сначала перезагрузка, потом снятие блокировки — иначе кнопка
      // на миг становится активной с устаревшим availableQty.
      await load()
      setBusyKey(null)
    }
  }

  return (
    <div className="cars-tab market-tab player-businesses-tab">
      <h2 className="tab-title">
        <Handshake size={22} style={{ verticalAlign: '-4px', marginRight: 8 }} />
        {t('gpuShop.tabTitle')}
      </h2>

      {SECTION_TEMP_DISABLED && (
        <div className="market-temp-unavailable" data-tour="playerbusinesses">
          <Wrench size={34} className="market-temp-unavailable-icon" />
          <p className="market-temp-unavailable-title">
            {t('common.sectionTemporarilyUnavailable', 'Данный раздел временно недоступен')}
          </p>
          <p className="market-temp-unavailable-hint">
            {t('common.sectionTemporarilyUnavailableHint',
              'Мы дорабатываем функционал — раздел вернётся в ближайшее обновление.')}
          </p>
        </div>
      )}

      {!SECTION_TEMP_DISABLED && loading && (
        <div className="empty-state"><Loader2 size={24} className="spin" /></div>
      )}

      {!SECTION_TEMP_DISABLED && !loading && shops.length === 0 && (
        <div className="empty-state"><p>{t('gpuShop.emptyPlayers')}</p></div>
      )}

      {!SECTION_TEMP_DISABLED && !loading && shops.map(shop => (
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
                            step="1"
                            inputMode="numeric"
                            className="gpu-shop-qty-input"
                            aria-label={t('gpuShop.qty')}
                            value={qtys[key] ?? 1}
                            disabled={!canBuy || busyKey === key}
                            onChange={e => {
                              const next = e.target.value
                              setQtys(prev => ({ ...prev, [key]: next }))
                            }}
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
