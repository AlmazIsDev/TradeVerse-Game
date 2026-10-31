import { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import {
  toggleCardVisibility, fetchCurrentUser, getUserLevel,
  fetchNotifications, markNotificationRead, markAllNotificationsRead,
  acceptInvite, declineInvite, acceptApplication, declineApplication,
} from '../services/api'
import ProfileCard from './ProfileCard'
import StatusBadge from './StatusBadge'
import { flagUrl } from '../utils/countries'
import { formatCompact } from './TransactionsPanel'
import {
  Bell, LogOut, X, Check, Wallet, Megaphone, Zap, Users, Store,
  Cpu, Trophy, Settings2, Search, Undo2, Eye, EyeOff,
} from 'lucide-react'

function formatMoney(n) {
  return Number(n || 0).toLocaleString(i18n.language === 'es' ? 'es-ES' : i18n.language === 'en' ? 'en-US' : 'ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const STORAGE_KEY = 'tradeverse_user'

function getStoredUser() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return null
}

function Header({ user, balance, onLogout, onOpenSettings }) {
  const { t } = useTranslation()
  const returnFromImpersonation = () => {
    const token = localStorage.getItem('admin_return_token')
    const refresh = localStorage.getItem('admin_return_refresh_token')
    const adminUser = localStorage.getItem('admin_return_user')
    if (!token || !refresh || !adminUser) return
    localStorage.setItem('tradeverse_user', adminUser)
    localStorage.removeItem('admin_return_token')
    localStorage.removeItem('admin_return_refresh_token')
    localStorage.removeItem('admin_return_user')
    window.location.reload()
  }
  const [showNotifications, setShowNotifications] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [unreadTotal, setUnreadTotal] = useState(0)
  const [unreadByCategory, setUnreadByCategory] = useState({})
  const [notifTab, setNotifTab] = useState('all')
  const [hideAutoInAll, setHideAutoInAll] = useState(() => localStorage.getItem('notifHideAutoInAll') === '1')
  const [notifSearch, setNotifSearch] = useState('')
  const notifRef = useRef(null)
  const dropdownRef = useRef(null)

  const storedUser = getStoredUser()
  const [cardNumber, setCardNumber] = useState(storedUser?.card_number || null)
  const [cardVisible, setCardVisible] = useState(
    storedUser?.card_visible !== undefined ? storedUser.card_visible : true
  )
  const [copied, setCopied] = useState(false)
  const [levelInfo, setLevelInfo] = useState(null)

  useEffect(() => {
    let cancelled = false
    getUserLevel()
      .then((data) => { if (!cancelled) setLevelInfo(data) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const levelProgress = levelInfo
    ? Math.min(100, Math.round(
        ((levelInfo.xp - levelInfo.xpCurrentLevel) /
          Math.max(1, levelInfo.xpNextLevel - levelInfo.xpCurrentLevel)) * 100))
    : 0

  const displayName = user?.username || storedUser?.username || t('header.user')
  const avatar = user?.avatar || storedUser?.avatar || null
  const initials = displayName ? displayName.slice(0, 2).toUpperCase() : 'TV'
  const unreadCount = unreadTotal

  const isActionable = useCallback(
    (n) =>
      (n.type === 'company_invite' && n.data?.inviteId) ||
      (n.type === 'company_application' && n.data?.applicationId),
    [],
  )
  const categoryOf = useCallback((n) => {
    if (n.category) return n.category
    if (n.type === 'broadcast') return 'announcement'
    if (n.type === 'rental' || n.type === 'salary') return 'automatic'
    if (n.type === 'company' || n.type === 'company_invite' || n.type === 'company_application') return 'company'
    if (n.type === 'market' || n.type === 'crypto_transfer') return 'market'
    if (n.type === 'mining') return 'mining'
    if (n.type === 'media' || n.type === 'itstudio' || n.type === 'itstudio_attack' || n.type === 'cityroof') return 'event'
    return 'system'
  }, [])
  const categoryIcon = {
    automatic: Zap, announcement: Megaphone, company: Users,
    market: Store, mining: Cpu, event: Trophy, system: Settings2,
  }

  // Панель не должна вылезать за экран: после открытия (и на resize) измеряем
  // её и при нехватке места сужаем и/или сдвигаем обратно в вьюпорт.
  const clampDropdown = useCallback(() => {
    const el = dropdownRef.current
    if (!el) return
    el.style.transform = ''
    el.style.maxWidth = ''
    const m = 8
    const vw = document.documentElement.clientWidth
    let rect = el.getBoundingClientRect()
    if (rect.width > vw - m * 2) {
      el.style.maxWidth = `${vw - m * 2}px`
      rect = el.getBoundingClientRect()
    }
    let dx = 0
    if (rect.right > vw - m) dx = vw - m - rect.right
    if (rect.left + dx < m) dx = m - rect.left
    if (dx) el.style.transform = `translateX(${dx}px)`
  }, [])

  useEffect(() => {
    if (!showNotifications) return undefined
    clampDropdown()
    window.addEventListener('resize', clampDropdown)
    return () => window.removeEventListener('resize', clampDropdown)
  }, [showNotifications, clampDropdown])

  const tabCategory = { all: null, auto: 'automatic', announce: 'announcement', company: 'company', market: 'market', mining: 'mining', event: 'event' }
  const query = notifSearch.trim().toLocaleLowerCase()
  const visibleNotifications = notifications.filter((n) => {
    const haystack = `${n.title || ''} ${n.body || ''}`.toLocaleLowerCase()
    return !query || haystack.includes(query)
  })
  const tabUnread = (category) => (category ? unreadByCategory[category] || 0 : unreadTotal)
  const tabs = [
    ['all', 'tabAll'], ['auto', 'tabAuto'], ['announce', 'tabAnnounce'],
    ['company', 'tabCompany'], ['market', 'tabMarket'], ['mining', 'tabMining'], ['event', 'tabEvent'],
  ]

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

  // Лента грузится по активной вкладке: иначе последние 30 записей одной категории
  // вытесняют остальные и их не видно. Счётчики по категориям приходят всегда.
  const loadNotifs = useCallback(async () => {
    try {
      const exclude = notifTab === 'all' && hideAutoInAll ? 'automatic' : null
      const data = await fetchNotifications(30, tabCategory[notifTab], exclude)
      setNotifications(data.items || [])
      setUnreadTotal(data.unread || 0)
      setUnreadByCategory(data.unreadByCategory || {})
    } catch { /* ignore */ }
  }, [notifTab, hideAutoInAll])

  const toggleHideAuto = () => {
    setHideAutoInAll(prev => {
      const next = !prev
      localStorage.setItem('notifHideAutoInAll', next ? '1' : '0')
      return next
    })
  }

  // 30с был основным источником обновлений до WS; tv:notif покрывает
  // live-обновления, поэтому интервал — редкий резервный фолбэк.
  useEffect(() => {
    loadNotifs()
    const id = setInterval(loadNotifs, 120000)
    return () => clearInterval(id)
  }, [loadNotifs])

  // Push-событие от NotificationCenter — обновляем ленту без задержки debounce.
  useEffect(() => {
    const onNotif = () => loadNotifs()
    window.addEventListener('tv:notif', onNotif)
    return () => window.removeEventListener('tv:notif', onNotif)
  }, [loadNotifs])

  const markAsRead = async (id) => {
    try { await markNotificationRead(id) } catch { /* ignore */ }
    loadNotifs()
  }

  const markAllRead = async () => {
    try { await markAllNotificationsRead() } catch { /* ignore */ }
    loadNotifs()
  }

  const handleInvite = async (notif, accept) => {
    const inviteId = notif?.data?.inviteId
    if (!inviteId) return
    try {
      if (accept) await acceptInvite(inviteId)
      else await declineInvite(inviteId)
      await markNotificationRead(notif.id)
      await loadNotifs()
      // Обновляем вкладку «Моя компания» — иначе после принятия приглашения
      // здесь (в колокольчике, в отличие от всплывающего попапа) её состояние
      // не перечитывалось, и игрок не видел себя в компании.
      window.dispatchEvent(new CustomEvent('tv:company-refresh'))
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
      window.dispatchEvent(new CustomEvent('tv:company-refresh'))
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
      <div className="header-right">
        {balance != null && (
          <div className="header-balance" title={`${t('account.balance')}: ${formatMoney(balance)} $`}>
            <Wallet size={16} />
            <span className="header-balance-value">{formatCompact(balance)} $</span>
          </div>
        )}
        {levelInfo && (
          <div className="header-level" title={`XP: ${levelInfo.xp} / ${levelInfo.xpNextLevel}`}>
            <span>{t('header.levelShort', 'Ур.')} {levelInfo.level}</span>
            <div className="header-level-bar"><div style={{ width: `${levelProgress}%` }} /></div>
            <span className="header-level-left">{levelInfo.xpNextLevel - levelInfo.xp} XP</span>
          </div>
        )}
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
            <div className="notification-dropdown" ref={dropdownRef}>
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
              <div className="notification-search">
                <Search size={15} />
                <input
                  value={notifSearch}
                  onChange={(e) => setNotifSearch(e.target.value)}
                  placeholder={t('notifications.searchPlaceholder')}
                  aria-label={t('notifications.searchPlaceholder')}
                />
                {notifSearch && <button type="button" title={t('common.clear', 'Очистить')} aria-label={t('common.clear', 'Очистить')} onClick={() => setNotifSearch('')}><X size={14} /></button>}
              </div>
              <div className="notification-tabs">
                {tabs.map(([id, key]) => {
                  const unread = tabUnread(tabCategory[id])
                  const Icon = categoryIcon[tabCategory[id]]
                  return (
                    <button
                      key={id}
                      type="button"
                      className={`notification-tab ${notifTab === id ? 'active' : ''}`}
                      onClick={() => setNotifTab(id)}
                      title={t(`notifications.${key}`)}
                    >
                      {Icon && <Icon size={13} />}
                      <span>{t(`notifications.${key}`)}</span>
                      {unread > 0 && <span className="notification-tab-badge">{unread}</span>}
                    </button>
                  )
                })}
              </div>
              {notifTab === 'all' && (
                <button
                  type="button"
                  className="notification-hide-auto"
                  onClick={toggleHideAuto}
                  title={t(hideAutoInAll ? 'notifications.showAuto' : 'notifications.hideAuto')}
                >
                  {hideAutoInAll ? <Eye size={13} /> : <EyeOff size={13} />}
                  <span>{t(hideAutoInAll ? 'notifications.showAuto' : 'notifications.hideAuto')}</span>
                </button>
              )}
              <div className="notification-list">
                {visibleNotifications.length === 0 && (
                  <div className="notification-empty">{t('notifications.noNotifications')}</div>
                )}
                {visibleNotifications.map(n => {
                  const actionable = isActionable(n)
                  const category = categoryOf(n)
                  const Icon = categoryIcon[category] || Settings2
                  return (
                    <div
                      key={n.id}
                      className={`notification-item ${n.read ? 'read' : 'unread'} notification-${category}`}
                      onClick={() => !actionable && markAsRead(n.id)}
                    >
                      {!n.read && <div className="notification-dot" />}
                      <div className="notification-content">
                        <span className="notification-title">
                          <Icon size={14} className="notification-category-icon" />
                          {n.title}
                        </span>
                        {n.body && <span className="notification-text">{n.body}</span>}
                        <span className="notification-time">{formatNotifTime(n.createdAt)}</span>
                        {actionable && (
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
        <button
          type="button"
          className="header-user header-user-btn"
          title={t('nav.settings')}
          onClick={onOpenSettings}
        >
          {(user?.country || storedUser?.country) && (
            <img className="lb-flag header-flag" src={flagUrl(user?.country || storedUser?.country)} alt={user?.country || storedUser?.country} title={user?.country || storedUser?.country} />
          )}
          <span className="header-username">{displayName}</span>
          {avatar ? (
            <img className="header-avatar header-avatar-img" src={avatar} alt={displayName} />
          ) : (
            <div className="header-avatar">{initials}</div>
          )}
          <StatusBadge user={user || storedUser} size={12} />
        </button>
        {localStorage.getItem('admin_return_token') && (
          <button className="header-icon-btn" title={t('header.returnToAdmin')} onClick={returnFromImpersonation}>
            <Undo2 size={20} />
          </button>
        )}
        <button className="header-icon-btn" title={t('header.logout')} onClick={onLogout}>
          <LogOut size={20} />
        </button>
      </div>
    </header>
  )
}

export default Header