import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Minus, Plus, DollarSign, ShoppingCart } from 'lucide-react'

function BuyModal({ product, onClose }) {
  const { t } = useTranslation()
  const [quantity, setQuantity] = useState(1)

  // Закрытие по клавише Escape (доступность).
  useEffect(() => {
    const onKeyDown = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const price = product.price ?? 0
  const total = price * quantity

  const handleQuantityChange = (value) => {
    const num = parseInt(value, 10)
    if (isNaN(num) || num < 1) {
      setQuantity(1)
    } else {
      setQuantity(num)
    }
  }

  const increment = () => setQuantity(prev => prev + 1)
  const decrement = () => setQuantity(prev => Math.max(1, prev - 1))

  // Магазины (GPU/CPU/недвижимость/бизнес) — вторичная система: у товаров ещё нет
  // цен и серверной логики покупки/инвентаря. Пока показываем честный статус,
  // а не имитируем покупку. Основной геймплейный цикл — торговля акциями (Stocks).
  const purchasable = price > 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="buy-modal"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t('common.buy')}
      >
        <button className="buy-modal-close" onClick={onClose} aria-label={t('common.close')}>
          <X size={20} />
        </button>

        <div className="buy-modal-header">
          <ShoppingCart size={24} />
          <h3>{t('common.buy')}</h3>
        </div>

        <div className="buy-modal-product">
          <span className="buy-modal-product-name">{product.name}</span>
          <div className="buy-modal-product-price">
            <DollarSign size={14} />
            <span>{price > 0 ? `$${price.toLocaleString()}` : t('common.notSet')}</span>
          </div>
        </div>

        <div className="buy-modal-quantity">
          <label>{t('buyModal.quantity')}</label>
          <div className="buy-modal-quantity-controls">
            <button className="buy-modal-qty-btn" onClick={decrement} disabled={quantity <= 1}>
              <Minus size={16} />
            </button>
            <input
              type="number"
              min="1"
              value={quantity}
              onChange={(e) => handleQuantityChange(e.target.value)}
              className="buy-modal-qty-input"
            />
            <button className="buy-modal-qty-btn" onClick={increment}>
              <Plus size={16} />
            </button>
          </div>
        </div>

        <div className="buy-modal-total">
          <span>{t('common.total')}:</span>
          <strong>${total.toLocaleString()}</strong>
        </div>

        <p className="buy-modal-note">{t('shop.comingSoon')}</p>

        <div className="buy-modal-actions">
          <button className="buy-modal-cancel" onClick={onClose}>
            {t('common.close')}
          </button>
          <button className="buy-modal-confirm" onClick={onClose} disabled={!purchasable}>
            {t('common.buy')}
          </button>
        </div>
      </div>
    </div>
  )
}

export default BuyModal
