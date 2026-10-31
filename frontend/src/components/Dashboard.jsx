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
import AchievementsTab from './AchievementsTab'
import TutorialTab from './TutorialTab'
import MarketTab from './MarketTab'
import CentralMarketTab from './CentralMarketTab'
import MyAssetsTab from './MyAssetsTab'
import InventoryTab from './InventoryTab'
import MyCompanyTab from './MyCompanyTab'
import CityRoofTab from './CityRoofTab'
import MiningTab from './MiningTab'
import CarsTab from './CarsTab'
import PlayerBusinessesTab from './PlayerBusinessesTab'
import SettingsPage from './SettingsPage'
import SupportPage from './SupportPage'
import AdminPanel from './AdminPanel'
import NotificationCenter from './NotificationCenter'
import LegalFooter from './LegalFooter'
import ToastHost from './Toast'
import { fetchCurrentUser, API_BASE_URL, getTokenExpiryMs, refreshAndReschedule } from '../services/api'
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

  const isAdmin = user?.role === 'admin'

  // Realtime: баланс/уведомления через WS, polling в Header — резерв.
  // Access-токен ротируется каждые ~30 мин (backend/auth.py), сервер валидирует
  // его только при хендшейке (backend/ws.py) — поэтому каждый реконнект обязан
  // брать СВЕЖИЙ токен из localStorage, а не снятый при монтировании.
  useEffect(() => {
    let socket
    let ping
    let debounce
    let reconnectTimer
    let cancelled = false
    let reconnectAttempts = 0
    // Всплески событий (напр. серия тиков майнинга) схлопываем в один запрос
    // за баланс/обновление — иначе fetchCurrentUser бил бы на каждое сообщение.
    const scheduleSync = () => {
      if (debounce) return
      debounce = setTimeout(() => {
        debounce = null
        fetchCurrentUser().then(d => { if (d?.balance != null) setBalance(d.balance) }).catch(() => {})
      }, 1200)
    }
    const connect = async () => {
      if (cancelled) return
      try {
        let stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
        let token = stored.token
        if (!token) return
        // Истёкший токен сервер отклонит сокет (403) — обновляем перед
        // подключением, если истёк/истекает.
        if ((getTokenExpiryMs(token) ?? Infinity) <= Date.now() + 1000) {
          if (!stored.refresh_token) return   // сессия мертва — forceLogout уже сработал
          await refreshAndReschedule()
          stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
          token = stored.token
          if (!token || (getTokenExpiryMs(token) ?? Infinity) <= Date.now()) return
        }
        const url = API_BASE_URL.replace(/^http/, 'ws') + '/ws?token=' + encodeURIComponent(token)
        socket = new WebSocket(url)
        socket.onopen = () => { reconnectAttempts = 0 }
        socket.onmessage = (ev) => {
          let data = null
          try { data = JSON.parse(ev.data) } catch { /* ignore */ }
          // Событие баланса применяем мгновенно (без сетевого запроса) — верхняя
          // панель обновляется сразу при любом изменении баланса.
          if (data?.type === 'balance' && data.balance != null) {
            handleBalanceChange(data.balance)
          } else if (data && !GLOBAL_BROADCAST_TYPES.has(data.type)) {
            // Бродкасты не меняют баланс этого игрока — вкладки обновляются сами
            // через tv:realtime (см. GLOBAL_BROADCAST_TYPES выше).
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
          // Экспоненциальный backoff (макс. 30с) — не долбим сервер при
          // недоступности/отклонении сокета.
          reconnectTimer = setTimeout(connect, Math.min(30000, 1000 * 2 ** reconnectAttempts++))
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
          avatar: data.avatar, banner: data.banner, badges: data.badges,
          created_at: data.created_at,
          role: data.role, adminLevel: data.adminLevel,
          adminFunctions: data.adminFunctions,
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
        return <CryptoTab balance={balance} onBalanceChange={handleBalanceChange} currentUserId={user?.id} />
      case 'realestate':
        return <MarketTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'centralmarket':
        return <CentralMarketTab />
      case 'myhomes':
        return <MyAssetsTab defaultType="all" balance={balance} onBalanceChange={handleBalanceChange} />
      case 'inventory':
        return <InventoryTab balance={balance} onBalanceChange={handleBalanceChange} onTabChange={setActiveTab} />
      case 'mycompany':
        return <MyCompanyTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'cars':
        return <CarsTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'playerbusinesses':
        return <PlayerBusinessesTab />
      case 'leaderboard':
        return <LeaderboardTab currentUserId={user?.id} />
      case 'achievements':
        return <AchievementsTab />
      case 'tutorial':
        return <TutorialTab />
      case 'settings':
        return <SettingsPage user={user} onUserUpdate={onUserUpdate} />
      case 'support':
        return <SupportPage />
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
          onOpenSettings={() => setActiveTab('settings')}
        />
        <div className="dashboard-content">
          {renderContent()}
        </div>
        <LegalFooter />
      </div>
      <NotificationCenter />
      <ToastHost />
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