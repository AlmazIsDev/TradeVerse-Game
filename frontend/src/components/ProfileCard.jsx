import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { CreditCard, Eye, EyeOff, CheckCheck } from 'lucide-react'
import { toggleCardVisibility } from '../services/api'

function ProfileCard({ cardNumber, cardVisible, onVisibilityChange }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const displayNumber = cardNumber
    ? cardVisible
      ? cardNumber
      : '****-****-****-' + cardNumber.slice(-5)
    : null

  const handleToggleVisibility = async (e) => {
    e.stopPropagation()
    try {
      const result = await toggleCardVisibility()
      if (onVisibilityChange) onVisibilityChange(result.card_visible)
    } catch {
      // ignore
    }
  }

  const handleCopyCard = useCallback(async () => {
    if (!cardNumber) return
    try {
      await navigator.clipboard.writeText(cardNumber)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback
      const ta = document.createElement('textarea')
      ta.value = cardNumber
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [cardNumber])

  return (
    <div className="profile-card" onClick={handleCopyCard} title={t('header.copyCard') || 'Скопировать номер карты'}>
      <div className="profile-card-chip"><CreditCard size={16} /></div>
      {displayNumber ? (
        <div className="profile-card-number">{displayNumber}</div>
      ) : (
        <div className="profile-card-number profile-card-empty">—</div>
      )}
      <div className="profile-card-label">{t('profile.card')}</div>
      {displayNumber && (
        <button
          className="profile-card-visibility-btn"
          onClick={handleToggleVisibility}
          title={cardVisible ? (t('header.hideCard') || 'Скрыть карту') : (t('header.showCard') || 'Показать карту')}
        >
          {cardVisible ? <Eye size={14} /> : <EyeOff size={14} />}
        </button>
      )}
      {copied && <span className="profile-card-copied"><CheckCheck size={14} /></span>}
    </div>
  )
}

export default ProfileCard
