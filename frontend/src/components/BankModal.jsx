import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

// Общая модальная оболочка банка: затемнение, крестик, закрытие по Esc и клику по фону
function BankModal({ title, onClose, wide = false, children }) {
  const { t } = useTranslation()
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [onClose])

  return (
    <div
      className="bank-modal-overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className={`bank-modal${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="bank-modal-head">
          <h3>{title}</h3>
          <button type="button" className="bank-modal-close" onClick={onClose} aria-label={t('bank.close', 'Закрыть')}>
            <X size={18} />
          </button>
        </div>
        <div className="bank-modal-body">{children}</div>
      </div>
    </div>
  )
}

export default BankModal
