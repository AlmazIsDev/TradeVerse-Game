// ─────────────────────────────────────────────────────────────────────────────
// MarketBuyModal · модалка подтверждения покупки актива на вкладке «Рынок».
// Без степпера количества: покупаем ровно один экземпляр (дома/бизнесы/заводы
// и источники в этой игре — штучные активы). Над кнопкой «Купить» показываем
// товар, текущий баланс и цену.
// ─────────────────────────────────────────────────────────────────────────────
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X, ShoppingCart, Wallet, Coins, Package } from 'lucide-react'
import { formatMoney } from './TransactionsPanel'

/**
 * props:
 *   open: boolean
 *   item: { slug, name, price, color?, emoji?, rarity?, category?, type? }
 *   balance: number
 *   busy:   boolean   (пока идёт покупка)
 *   onConfirm(): вызывается при нажатии «Купить»
 *   onCancel():   закрытие
 */
function MarketBuyModal({ open, item, balance = 0, busy = false, onConfirm, onCancel }) {
  const { t } = useTranslation()

  // Закрываем по Esc.
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onCancel?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open || !item) return null

  const price = Number(item.price) || 0
  const affordable = balance >= price
  const color = item.color || '#22c55e'

  return (
    <div className="modal-overlay market-buy-modal-overlay" onClick={onCancel}>
      <div className="modal-content market-buy-modal" onClick={e => e.stopPropagation()}>
        <button
          className="crypto-modal-close"
          onClick={onCancel}
          aria-label={t('common.close')}
          type="button"
        >
          <X size={18} />
        </button>

        {/* 1) Товар: эмодзи/иконка + название + подкатегория/тип. */}
        <div className="market-buy-modal-item">
          <div
            className="market-buy-modal-icon"
            style={{ background: color }}
            aria-hidden
          >
            {item.emoji ? (
              <span className="market-buy-modal-emoji">{item.emoji}</span>
            ) : (
              <Package size={26} />
            )}
          </div>
          <div className="market-buy-modal-item-text">
            <div className="market-buy-modal-eyebrow">{t('market.buyItem', 'Покупка')}</div>
            <h3 className="market-buy-modal-name">{item.name}</h3>
            {item.subtitle && (
              <div className="market-buy-modal-subtitle">{item.subtitle}</div>
            )}
          </div>
        </div>

        {/* 2) Баланс игрока. */}
        <div className="market-buy-modal-row">
          <div className="market-buy-modal-row-label">
            <Wallet size={14} /> {t('buyModal.balance', 'Баланс')}
          </div>
          <div className="market-buy-modal-row-value">${formatMoney(balance)}</div>
        </div>

        {/* 3) Цена товара. */}
        <div className="market-buy-modal-row market-buy-modal-row-price">
          <div className="market-buy-modal-row-label">
            <Coins size={14} /> {t('buyModal.pricePerUnit', 'Цена')}
          </div>
          <div className="market-buy-modal-row-value">${formatMoney(price)}</div>
        </div>

        {!affordable && (
          <div className="buy-modal-warn">
            {t('stocks.insufficientFunds', 'Недостаточно средств')}
          </div>
        )}

        {/* 4) Кнопка «Купить». */}
        <button
          type="button"
          className="market-buy-modal-buy"
          style={{ background: affordable ? color : undefined }}
          disabled={!affordable || busy}
          onClick={onConfirm}
        >
          <ShoppingCart size={16} /> {busy
            ? t('common.loading', 'Загрузка...')
            : t('common.buy', 'Купить')}
        </button>
      </div>
    </div>
  )
}

export default MarketBuyModal
