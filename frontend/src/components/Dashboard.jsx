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
import AdminPanel from './AdminPanel'
import { fetchCurrentUser, API_BASE_URL } from '../services/api'
import { Shield } from 'lucide-react'

const STORAGE_KEY = 'tradeverse_user'

function Dashboard({ user, onLogout }) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('account')
  const [showAdmin, setShowAdmin] = useState(false)
  const [balance, setBalance] = useState(user?.balance ?? 0)
  const [rtKey, setRtKey] = useState(0)

  const isAdmin = user?.role === 'admin'

  // Realtime через WebSocket: обновляет баланс и уведомления без перезагрузки.
  // Polling в Header остаётся резервным механизмом, если WS недоступен.
  useEffect(() => {
    let socket
    let ping
    let debounce
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
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
      const token = stored.token
      if (!token) return undefined
      const url = API_BASE_URL.replace(/^http/, 'ws') + '/ws?token=' + encodeURIComponent(token)
      socket = new WebSocket(url)
      socket.onmessage = (ev) => {
        let data = null
        try { data = JSON.parse(ev.data) } catch { /* ignore */ }
        // Событие баланса применяем мгновенно (без сетевого запроса) — верхняя
        // панель обновляется сразу при любом изменении баланса.
        if (data?.type === 'balance' && data.balance != null) {
          handleBalanceChange(data.balance)
        } else {
          scheduleSync()
        }
        // Ретрансляция события другим вкладкам (напр. MiningTab слушает 'tv:realtime').
        if (data) { try { window.dispatchEvent(new CustomEvent('tv:realtime', { detail: data })) } catch { /* ignore */ } }
      }
      ping = setInterval(() => {
        try { if (socket.readyState === 1) socket.send('ping') } catch { /* ignore */ }
      }, 25000)
    } catch { /* ignore — останется polling */ }
    return () => {
      try { clearInterval(ping); clearTimeout(debounce); if (socket) socket.close() } catch { /* ignore */ }
    }
  }, [])

  // Синхронизируем баланс с сервером при монтировании (localStorage может устареть)
  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then(data => {
        if (cancelled || data?.balance == null) return
        setBalance(data.balance)
        try {
          const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
          localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...stored, balance: data.balance }))
        } catch { /* ignore */ }
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
        return <CityRoofTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'mining':
        return <MiningTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'crypto':
        return <CryptoTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'realestate':
        return <MarketTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'myhomes':
        return <MyAssetsTab defaultType="realestate" balance={balance} onBalanceChange={handleBalanceChange} />
      case 'mybusiness':
        return <MyAssetsTab defaultType="business" balance={balance} onBalanceChange={handleBalanceChange} />
      case 'mycompany':
        return <MyCompanyTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'leaderboard':
        return <LeaderboardTab currentUserId={user?.id} />
      default:
        return <AccountTab balance={balance} />
    }
  }

  return (
    <div className="dashboard">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} user={user} />
      <div className="dashboard-main">
        <Header username={user?.username} balance={balance} onLogout={onLogout} rtKey={rtKey} />
        <div className="dashboard-content">
          {renderContent()}
        </div>
      </div>
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
