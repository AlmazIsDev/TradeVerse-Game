import { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchConfig, toggleCardVisibility, fetchCurrentUser } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import ProfileCard from './ProfileCard'
import LanguageSwitcher from './LanguageSwitcher'
import { Bell, LogOut, X, Check, Eye, EyeOff, CheckCheck } from 'lucide-react'

const STORAGE_KEY = 'tradeverse_user'

function getStoredUser() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return null
}

function Header({ username, onLogout }) {
  const { t } = useTranslation()
  const { data: headerConfig } = useApiOnMount(() => fetchConfig('header_title'))
  const [showNotifications, setShowNotifications] = useState(false)
  const [notifications, setNotifications] = useState([])
  const notifRef = useRef(null)

  const storedUser = getStoredUser()
  const [cardNumber, setCardNumber] = useState(storedUser?.card_number || null)
  const [cardVisible, setCardVisible] = useState(
    storedUser?.card_visible !== undefined ? storedUser.card_visible : true
  )
  const [copied, setCopied] = useState(false)

  const displayName = username || storedUser?.username || t('header.user')
  const initials = displayName ? displayName.slice(0, 2).toUpperCase() : 'TV'
  const headerTitle = headerConfig?.value || 'TradeVerse'
  const unreadCount = notifications.filter(n => !n.read).length

  useEffect(() => {
    function handleClickOutside(e) {
      if (notifRef.current && !notifRef.current.contains(e.target)) {
        setShowNotifications(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Синхронизация card_number с сервера при монтировании
  useEffect(() => {
    let cancelled = false
    async function syncCard() {
      try {
        const data = await fetchCurrentUser()
        if (cancelled) return
        const newCard = data?.card_number || null
        const newVisible = data?.card_visible !== undefined ? data.card_visible : true
        setCardNumber(newCard)
        setCardVisible(newVisible)
        // Обновляем localStorage
        const stored = getStoredUser()
        if (stored) {
          localStorage.setItem(STORAGE_KEY, JSON.stringify({
            ...stored,
            card_number: newCard,
            card_visible: newVisible,
          }))
        }
      } catch {
        // ignore — используем данные из localStorage
      }
    }
    syncCard()
    return () => { cancelled = true }
  }, [])

  const markAsRead = (id) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
  }

  const markAllRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })))
  }

  const handleToggleVisibility = async () => {
    try {
      const result = await toggleCardVisibility()
      setCardVisible(result.card_visible)
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

  const maskedCard = cardNumber
    ? cardVisible
      ? cardNumber
      : '****-****-****-' + cardNumber.slice(-5)
    : null

  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo">
          <span className="header-logo-icon">T</span>
          <span className="header-logo-text">{headerTitle}</span>
        </div>
      </div>
      <div className="header-right">
        <LanguageSwitcher />
        <div className="notification-wrapper" ref={notifRef}>
          <button
            className="header-icon-btn notification-btn"
            title={t('header.notifications')}
            onClick={() => setShowNotifications(!showNotifications)}
          >
            <Bell size={20} />
            {unreadCount > 0 && (
              <span className="notification-badge">{unreadCount}</span>
            )}
          </button>
          {showNotifications && (
            <div className="notification-dropdown">
              <div className="notification-header">
                <span>{t('header.notifications')}</span>
                {unreadCount > 0 && (
                  <button className="mark-all-btn" onClick={markAllRead}>
                    <Check size={14} /> {t('header.markAllRead')}
                  </button>
                )}
                <button className="close-notif-btn" onClick={() => setShowNotifications(false)}>
                  <X size={16} />
                </button>
              </div>
              <div className="notification-list">
                {notifications.map(n => (
                  <div
                    key={n.id}
                    className={`notification-item ${n.read ? 'read' : 'unread'}`}
                    onClick={() => markAsRead(n.id)}
                  >
                    <div className="notification-dot" />
                    <div className="notification-content">
                      <span className="notification-text">{n.text}</span>
                      <span className="notification-time">{n.time}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <ProfileCard
          cardNumber={cardNumber}
          cardVisible={cardVisible}
          onVisibilityChange={(v) => setCardVisible(v)}
        />
        <div className="header-user">
          <span className="header-username">{displayName}</span>
          <div className="header-avatar">{initials}</div>
        </div>
        <button className="header-icon-btn" title={t('header.logout')} onClick={onLogout}>
          <LogOut size={20} />
        </button>
      </div>
    </header>
  )
}

export default Header
