// ShopBuyModal · модалка покупки в магазине (ShopTab). Как MarketBuyModal,
// плюс степпер количества: железо/расходники покупаются партией.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  X, Minus, Plus,
  ShoppingCart, Wallet, Coins, Package, Receipt,
} from 'lucide-react'
import { formatMoney } from './TransactionsPanel'

function ShopBuyModal({
  open,
  item,
  balance = 0,
  maxQty = 1000,
  busy = false,
  onConfirm,
  onCancel,
}) {
  const { t } = useTranslation()
  const [qty, setQty] = useState(1)

  useEffect(() => { if (open) setQty(1) }, [open, item?.id])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onCancel?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open || !item) return null

  const price = Number(item.price) || 0
  const total = price * qty
  const affordable = balance >= total
  const color = item.color || '#0071e3'

  const inc = () => setQty(q => Math.min(maxQty, q + 1))
  const dec = () => setQty(q => Math.max(1, q - 1))
  const onInput = (e) => {
    const v = parseInt(e.target.value, 10)
    setQty(Number.isFinite(v) ? Math.max(1, Math.min(maxQty, v)) : 1)
  }

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

        <div className="market-buy-modal-item">
          <div
            className="market-buy-modal-icon"
            style={{ background: color }}
            aria-hidden
          >
            {item.emoji
              ? <span className="market-buy-modal-emoji">{item.emoji}</span>
              : <Package size={26} />}
          </div>
          <div className="market-buy-modal-item-text">
            <div className="market-buy-modal-eyebrow">
              {t('buyModal.title', { defaultValue: 'Покупка' })}
            </div>
            <h3 className="market-buy-modal-name">{item.name}</h3>
            {item.category && (
              <div className="market-buy-modal-subtitle">
                {t(`mining.comp.${item.category}`, item.category)}
              </div>
            )}
          </div>
        </div>

        <div className="market-buy-modal-qty">
          <div className="market-buy-modal-qty-label">
            {t('buyModal.quantity', 'Количество')}
          </div>
          <div className="market-buy-modal-stepper">
            <button
              type="button"
              className="market-buy-modal-stepper-btn"
              onClick={dec}
              disabled={qty <= 1}
              aria-label="−"
            >
              <Minus size={14} />
            </button>
            <input
              type="number" min="1" max={maxQty} value={qty}
              onChange={onInput}
              className="market-buy-modal-stepper-input"
            />
            <button
              type="button"
              className="market-buy-modal-stepper-btn"
              onClick={inc}
              disabled={qty >= maxQty}
              aria-label="+"
            >
              <Plus size={14} />
            </button>
          </div>
        </div>

        <div className="market-buy-modal-row">
          <div className="market-buy-modal-row-label">
            <Wallet size={14} /> {t('buyModal.balance', 'Баланс')}
          </div>
          <div className="market-buy-modal-row-value">${formatMoney(balance)}</div>
        </div>

        <div className="market-buy-modal-row">
          <div className="market-buy-modal-row-label">
            <Coins size={14} /> {t('buyModal.pricePerUnit', 'Цена за шт.')}
          </div>
          <div className="market-buy-modal-row-value">${formatMoney(price)}</div>
        </div>

        <div className="market-buy-modal-row market-buy-modal-row-price">
          <div className="market-buy-modal-row-label">
            <Receipt size={14} /> {t('buyModal.total', 'Итого')}
          </div>
          <div className="market-buy-modal-row-value">${formatMoney(total)}</div>
        </div>

        {!affordable && (
          <div className="buy-modal-warn">
            {t('stocks.insufficientFunds', 'Недостаточно средств')}
          </div>
        )}

        <button
          type="button"
          className="market-buy-modal-buy"
          style={{ background: affordable ? color : undefined }}
          disabled={!affordable || busy}
          onClick={() => onConfirm?.(qty)}
        >
          <ShoppingCart size={16} /> {busy
            ? t('common.loading', 'Загрузка...')
            : t('common.buy', 'Купить')}
        </button>
      </div>
    </div>
  )
}

export default ShopBuyModal
