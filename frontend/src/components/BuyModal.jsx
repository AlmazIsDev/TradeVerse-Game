// ─────────────────────────────────────────────────────────────────────────────
// BuyModal · модалка покупки товара в магазине.
// Поля: количество (степпер +/-, 1..1000), цена за шт., итоговая цена,
// текущий баланс игрока. Кнопка «Купить» в демо-режиме просто закрывает
// окно и показывает toast — бэкенд не вызывается (по требованию задачи).
// ─────────────────────────────────────────────────────────────────────────────
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Minus, Plus, ShoppingCart, Wallet, DollarSign } from 'lucide-react'
import { formatMoney } from './TransactionsPanel'

/**
 * props:
 *   open: boolean
 *   item: { id, name, price, color, category, slug? }
 *   balance: number
 *   maxQty: верхняя граница степпера (по умолчанию 1000)
 *   onConfirm(qty): вызывается при нажатии «Купить»
 *   onCancel(): закрытие
 */
function BuyModal({
  open,
  item,
  balance = 0,
  maxQty = 1000,
  onConfirm,
  onCancel,
}) {
  const { t } = useTranslation()
  const [qty, setQty] = useState(1)

  // Сбрасываем количество на 1 при каждом открытии/смене товара.
  useEffect(() => {
    if (open) setQty(1)
  }, [open, item?.id])

  if (!open || !item) return null

  const price = Number(item.price) || 0
  const total = price * qty
  const affordable = balance >= total
  const color = item.color || '#22c55e'
  const inc = () => setQty(q => Math.min(maxQty, q + 1))
  const dec = () => setQty(q => Math.max(1, q - 1))
  const onInput = (e) => {
    const v = parseInt(e.target.value, 10)
    setQty(Number.isFinite(v) ? Math.max(1, Math.min(maxQty, v)) : 1)
  }

  return (
    <div className="modal-overlay buy-modal-overlay" onClick={onCancel}>
      <div className="modal-content buy-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onCancel} aria-label={t('common.close')}>
          <X size={18} />
        </button>

        <div className="buy-modal-head">
          <span className="buy-modal-icon" style={{ background: color }}>
            <ShoppingCart size={22} />
          </span>
          <div className="buy-modal-title">
            <div className="buy-modal-eyebrow">{t('common.buy')}</div>
            <h3 className="buy-modal-name">{item.name}</h3>
          </div>
        </div>

        <div className="buy-modal-row buy-modal-qty">
          <label className="buy-modal-label">{t('buyModal.quantity')}</label>
          <div className="buy-modal-stepper">
            <button type="button" className="gpu-qty-btn" onClick={dec} disabled={qty <= 1}>
              <Minus size={14} />
            </button>
            <input
              type="number" min="1" max={maxQty} value={qty}
              onChange={onInput}
            />
            <button type="button" className="gpu-qty-btn" onClick={inc} disabled={qty >= maxQty}>
              <Plus size={14} />
            </button>
          </div>
        </div>

        <div className="buy-modal-grid">
          <div className="buy-modal-cell">
            <div className="buy-modal-cell-label"><DollarSign size={12} /> {t('buyModal.pricePerUnit')}</div>
            <div className="buy-modal-cell-value">${formatMoney(price)}</div>
          </div>
          <div className="buy-modal-cell buy-modal-cell-accent">
            <div className="buy-modal-cell-label"><ShoppingCart size={12} /> {t('buyModal.total')}</div>
            <div className="buy-modal-cell-value">${formatMoney(total)}</div>
          </div>
          <div className="buy-modal-cell buy-modal-cell-balance">
            <div className="buy-modal-cell-label"><Wallet size={12} /> {t('buyModal.balance')}</div>
            <div className="buy-modal-cell-value">${formatMoney(balance)}</div>
          </div>
        </div>

        {!affordable && (
          <div className="buy-modal-warn">{t('stocks.insufficientFunds')}</div>
        )}

        <div className="buy-modal-actions">
          <button className="buy-modal-cancel" onClick={onCancel} type="button">
            {t('common.cancel')}
          </button>
          <button
            className="buy-modal-buy"
            style={{ background: affordable ? color : undefined }}
            disabled={!affordable}
            onClick={() => onConfirm?.(qty)}
            type="button"
          >
            {t('common.buy')}
          </button>
        </div>
      </div>
    </div>
  )
}

export default BuyModal
