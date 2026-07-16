import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import Sidebar from './Sidebar'
import Header from './Header'
import AccountTab from './AccountTab'
import StocksTab from './StocksTab'
import BankTab from './BankTab'
import CryptoTab from './CryptoTab'
import ShopTab from './ShopTab'
import LeaderboardTab from './LeaderboardTab'
import MarketTab from './MarketTab'
import MyAssetsTab from './MyAssetsTab'
import MyCompanyTab from './MyCompanyTab'
import CityRoofTab from './CityRoofTab'
import MiningTab from './MiningTab'
import SettingsPage from './SettingsPage'
import AdminPanel from './AdminPanel'
import NotificationCenter from './NotificationCenter'
import { fetchCurrentUser, API_BASE_URL } from '../services/api'
import { Shield } from 'lucide-react'

const STORAGE_KEY = 'tradeverse_user'

// Типы WS-сообщений, которые рассылаются ВСЕМ игрокам (не привязаны к текущему
// пользователю). Их не нужно превращать в fetchCurrentUser — иначе каждая
// сделка/тик любого игрока вызывала бы рефетч у всех. Вкладки, которым эти
// данные нужны, слушают tv:realtime и обновляются точечно.
const GLOBAL_BROADCAST_TYPES = new Set([
  'market_update', 'price_tick', 'leaderboard_update', 'economy_stats',
])

function Dashboard({ user, onLogout, onUserUpdate }) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('account')
  const [showAdmin, setShowAdmin] = useState(false)
  const [balance, setBalance] = useState(user?.balance ?? 0)
  const [rtKey, setRtKey] = useState(0)

  const isAdmin = user?.role === 'admin'

  // Realtime через WebSocket: обновляет баланс и уведомления без перезагрузки.
  // Polling в Header остаётся резервным механизмом, если WS недоступен.
  //
  // Access-токен ротируется каждые ~30 минут (см. ACCESS_TOKEN_EXPIRE_MINUTES
  // в backend/auth.py), а сервер валидирует токен только один раз — при
  // хендшейке (backend/ws.py). Поэтому при любом закрытии сокета мы обязаны
  // переподключаться со свежим токеном из localStorage, а не переиспользовать
  // токен, снятый при монтировании компонента — иначе после первой ротации
  // переподключение с устаревшим токеном будет неизменно отклоняться сервером.
  useEffect(() => {
    let socket
    let ping
    let debounce
    let reconnectTimer
    let cancelled = false
    // Всплески событий (напр. серия тиков майнинга) схлопываем в один запрос
    // за баланс/обновление — иначе fetchCurrentUser бил бы на каждое сообщение.
    const scheduleSync = () => {
      if (debounce) return
      debounce = setTimeout(() => {
        debounce = null
        fetchCurrentUser().then(d => { if (d?.balance != null) setBalance(d.balance) }).catch(() => {})
        setRtKey(k => k + 1)
      }, 1200)
    }
    const connect = () => {
      if (cancelled) return
      try {
        const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
        const token = stored.token
        if (!token) return
        const url = API_BASE_URL.replace(/^http/, 'ws') + '/ws?token=' + encodeURIComponent(token)
        socket = new WebSocket(url)
        socket.onmessage = (ev) => {
          let data = null
          try { data = JSON.parse(ev.data) } catch { /* ignore */ }
          // Событие баланса применяем мгновенно (без сетевого запроса) — верхняя
          // панель обновляется сразу при любом изменении баланса.
          if (data?.type === 'balance' && data.balance != null) {
            handleBalanceChange(data.balance)
          } else if (data && !GLOBAL_BROADCAST_TYPES.has(data.type)) {
            // Глобальные бродкасты (рынок/лидерборд/тики цен) шлются ВСЕМ игрокам
            // на каждую сделку/тик — они не меняют баланс текущего игрока, поэтому
            // не должны вызывать fetchCurrentUser (иначе N-кратный fan-out на всех).
            // Соответствующие вкладки обновляют свои данные сами через tv:realtime.
            scheduleSync()
          }
          // Ретрансляция события другим вкладкам (напр. MiningTab слушает 'tv:realtime').
          if (data) { try { window.dispatchEvent(new CustomEvent('tv:realtime', { detail: data })) } catch { /* ignore */ } }
        }
        ping = setInterval(() => {
          try { if (socket.readyState === 1) socket.send('ping') } catch { /* ignore */ }
        }, 25000)
        socket.onclose = () => {
          clearInterval(ping)
          if (cancelled) return
          // Переподключаемся с актуальным (возможно, уже обновлённым) токеном.
          reconnectTimer = setTimeout(connect, 5000)
        }
      } catch { /* ignore — останется polling */ }
    }
    connect()
    return () => {
      cancelled = true
      try {
        clearInterval(ping)
        clearTimeout(debounce)
        clearTimeout(reconnectTimer)
        if (socket) { socket.onclose = null; socket.close() }
      } catch { /* ignore */ }
    }
  }, [])

  // Синхронизируем баланс/профиль с сервером при монтировании (localStorage
  // может устареть — напр. никнейм/аватар были изменены в другой вкладке/сессии).
  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then(data => {
        if (cancelled || !data) return
        if (data.balance != null) setBalance(data.balance)
        onUserUpdate?.({
          balance: data.balance, username: data.username,
          avatar: data.avatar, created_at: data.created_at,
        })
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const handleBalanceChange = useCallback((newBalance) => {
    setBalance(newBalance)
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...stored, balance: newBalance }))
    } catch { /* ignore */ }
  }, [])

  const renderContent = () => {
    switch (activeTab) {
      case 'account':
        return <AccountTab balance={balance} />
      case 'stocks':
        return <StocksTab balance={balance} onBalanceChange={handleBalanceChange} currentUserId={user?.id} />
      case 'bank':
        return <BankTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'shop':
        return <ShopTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'cityroof':
        return <CityRoofTab balance={balance} onBalanceChange={handleBalanceChange} currentUserId={user?.id} />
      case 'mining':
        return <MiningTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'crypto':
        return <CryptoTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'realestate':
        return <MarketTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'myhomes':
        return <MyAssetsTab defaultType="all" balance={balance} onBalanceChange={handleBalanceChange} />
      case 'mybusiness':
        return <MyAssetsTab defaultType="business" balance={balance} onBalanceChange={handleBalanceChange} />
      case 'mycompany':
        return <MyCompanyTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'leaderboard':
        return <LeaderboardTab currentUserId={user?.id} />
      case 'settings':
        return <SettingsPage user={user} onUserUpdate={onUserUpdate} />
      default:
        return <AccountTab balance={balance} />
    }
  }

  return (
    <div className="dashboard">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} user={user} />
      <div className="dashboard-main">
        <Header
          user={user}
          balance={balance}
          onLogout={onLogout}
          rtKey={rtKey}
          onOpenSettings={() => setActiveTab('settings')}
        />
        <div className="dashboard-content">
          {renderContent()}
        </div>
      </div>
      <NotificationCenter />
      {isAdmin && (
        <button
          className="admin-fab"
          title={t('dashboard.adminPanel')}
          onClick={() => setShowAdmin(true)}
        >
          <Shield size={22} />
        </button>
      )}
      {showAdmin && <AdminPanel user={user} onClose={() => setShowAdmin(false)} />}
    </div>
  )
}

export default Dashboard