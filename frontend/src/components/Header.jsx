import { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchConfig, toggleCardVisibility, fetchCurrentUser,
  fetchNotifications, markNotificationRead, markAllNotificationsRead,
  acceptInvite, declineInvite, acceptApplication, declineApplication,
} from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import ProfileCard from './ProfileCard'
import LanguageSwitcher from './LanguageSwitcher'
import { formatCompact } from './TransactionsPanel'
import { Bell, LogOut, X, Check, Wallet } from 'lucide-react'

function formatMoney(n) {
  return Number(n || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const STORAGE_KEY = 'tradeverse_user'

function getStoredUser() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return null
}

function Header({ username, balance, onLogout, rtKey = 0 }) {
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

  // Живая лента уведомлений с сервера (в т.ч. приглашения в компанию)
  const loadNotifs = useCallback(async () => {
    try {
      const data = await fetchNotifications(30)
      setNotifications(data.items || [])
    } catch { /* ignore */ }
  }, [])

  // 30с был основным источником обновлений до WS; теперь rtKey (см. ниже) и
  // tv:notif уже покрывают live-обновления, поэтому интервал — редкий
  // резервный фолбэк на случай пропущенного push, как и у остальных вкладок.
  useEffect(() => {
    loadNotifs()
    const id = setInterval(loadNotifs, 120000)
    return () => clearInterval(id)
  }, [loadNotifs])

  // Мгновенная перезагрузка при realtime-событии (WebSocket из Dashboard).
  useEffect(() => {
    if (rtKey) loadNotifs()
  }, [rtKey, loadNotifs])

  // Push-событие от NotificationCenter — обновляем ленту без задержки debounce.
  useEffect(() => {
    const onNotif = () => loadNotifs()
    window.addEventListener('tv:notif', onNotif)
    return () => window.removeEventListener('tv:notif', onNotif)
  }, [loadNotifs])

  const markAsRead = async (id) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
    try { await markNotificationRead(id) } catch { /* ignore */ }
  }

  const markAllRead = async () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })))
    try { await markAllNotificationsRead() } catch { /* ignore */ }
  }

  const handleInvite = async (notif, accept) => {
    const inviteId = notif?.data?.inviteId
    if (!inviteId) return
    try {
      if (accept) await acceptInvite(inviteId)
      else await declineInvite(inviteId)
      await markNotificationRead(notif.id)
      await loadNotifs()
    } catch { /* ignore */ }
  }

  const handleApplication = async (notif, accept) => {
    const appId = notif?.data?.applicationId
    if (!appId) return
    try {
      if (accept) await acceptApplication(appId)
      else await declineApplication(appId)
      await markNotificationRead(notif.id)
      await loadNotifs()
    } catch { /* ignore */ }
  }

  const notifAction = (notif, accept) => {
    if (notif.type === 'company_application') return handleApplication(notif, accept)
    return handleInvite(notif, accept)
  }

  const formatNotifTime = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return isNaN(d.getTime()) ? '' : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
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
        {balance != null && (
          <div className="header-balance" title={`${t('account.balance')}: ${formatMoney(balance)} $`}>
            <Wallet size={16} />
            <span className="header-balance-value">{formatCompact(balance)} $</span>
          </div>
        )}
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
                {notifications.length === 0 && (
                  <div className="notification-empty">{t('notifications.noNotifications')}</div>
                )}
                {notifications.map(n => {
                  const isActionable =
                    (n.type === 'company_invite' && n.data?.inviteId) ||
                    (n.type === 'company_application' && n.data?.applicationId)
                  return (
                    <div
                      key={n.id}
                      className={`notification-item ${n.read ? 'read' : 'unread'}`}
                      onClick={() => !isActionable && markAsRead(n.id)}
                    >
                      {!n.read && <div className="notification-dot" />}
                      <div className="notification-content">
                        <span className="notification-title">{n.title}</span>
                        {n.body && <span className="notification-text">{n.body}</span>}
                        <span className="notification-time">{formatNotifTime(n.createdAt)}</span>
                        {isActionable && (
                          <div className="notification-actions">
                            <button className="notif-accept" onClick={(e) => { e.stopPropagation(); notifAction(n, true) }}>
                              <Check size={13} /> {t('company.accept')}
                            </button>
                            <button className="notif-decline" onClick={(e) => { e.stopPropagation(); notifAction(n, false) }}>
                              <X size={13} /> {t('company.decline')}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
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