import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, X } from 'lucide-react'

/**
 * Переиспользуемое модальное окно подтверждения.
 * props: { open, title, message, confirmLabel, cancelLabel, danger, busy, onConfirm, onCancel }
 * Крестик и клик по оверлею = отмена.
 */
function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}) {
  const { t } = useTranslation()
  if (!open) return null

  return (
    <div className="modal-overlay tv-confirm-overlay" onClick={() => !busy && onCancel?.()}>
      <div className="modal-content tv-confirm" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={() => onCancel?.()} disabled={busy}>
          <X size={18} />
        </button>
        <div className={`tv-confirm-icon ${danger ? 'danger' : ''}`}>
          <AlertTriangle size={26} />
        </div>
        <h3 className="tv-confirm-title">{title || t('common.confirmTitle')}</h3>
        {message && <p className="tv-confirm-message">{message}</p>}
        <div className="tv-confirm-buttons">
          <button
            className={`tv-confirm-btn ${danger ? 'danger' : 'primary'}`}
            disabled={busy}
            onClick={() => onConfirm?.()}
          >
            <Check size={15} /> {busy ? t('bank.processing') : (confirmLabel || t('common.yes'))}
          </button>
          <button className="tv-confirm-btn cancel" disabled={busy} onClick={() => onCancel?.()}>
            {cancelLabel || t('common.no')}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConfirmDialog
