import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Minus, Plus, DollarSign, ShoppingCart, Loader2 } from 'lucide-react'
import { purchaseItem } from '../services/api'

function BuyModal({ product, onClose, onPurchaseSuccess }) {
  const { t } = useTranslation()
  const [quantity, setQuantity] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const price = Number(product.price) || 0
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

  const handleBuy = async () => {
    setLoading(true)
    setError(null)
    try {
      await purchaseItem({
        item_id: String(product.id ?? ''),
        item_name: String(product.name ?? ''),
        item_category: String(product.category ?? product.type ?? 'shop'),
        price: Number(price),
        quantity: Number(quantity),
      })
      if (typeof onPurchaseSuccess === 'function') {
        onPurchaseSuccess()
      }
      onClose()
    } catch (err) {
      setError(err.message || 'Не удалось совершить покупку')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="buy-modal" onClick={e => e.stopPropagation()}>
        <button className="buy-modal-close" onClick={onClose}>
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

        {error && (
          <div className="buy-modal-error" style={{ color: '#ef4444', marginBottom: 12, textAlign: 'center' }}>
            {error}
          </div>
        )}

        <div className="buy-modal-actions">
          <button className="buy-modal-cancel" onClick={onClose} disabled={loading}>
            {t('common.cancel')}
          </button>
          <button
            className="buy-modal-confirm"
            onClick={handleBuy}
            disabled={loading}
          >
            {loading ? <Loader2 size={16} className="spin" /> : t('common.buy')}
          </button>
        </div>
      </div>
    </div>
  )
}

export default BuyModal
