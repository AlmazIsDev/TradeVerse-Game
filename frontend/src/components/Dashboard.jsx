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
import AdminPanel from './AdminPanel'
import { fetchCurrentUser } from '../services/api'
import { Home, Briefcase, Shield } from 'lucide-react'

const STORAGE_KEY = 'tradeverse_user'

function Dashboard({ user, onLogout }) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('account')
  const [showAdmin, setShowAdmin] = useState(false)
  const [balance, setBalance] = useState(user?.balance ?? 0)

  const isAdmin = user?.role === 'admin'

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
        return <StocksTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'bank':
        return <BankTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'shop':
        return <ShopTab />
      case 'cityroof':
        return <CityRoofTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'crypto':
        return <CryptoTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'realestate':
        return <MarketTab balance={balance} onBalanceChange={handleBalanceChange} />
      case 'myhomes':
        return <MyAssetsTab types={['realestate', 'car']} titleKey="nav.myhomes" icon={Home} balance={balance} onBalanceChange={handleBalanceChange} />
      case 'mybusiness':
        return <MyAssetsTab types={['business']} titleKey="nav.mybusiness" icon={Briefcase} balance={balance} onBalanceChange={handleBalanceChange} />
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
        <Header username={user?.username} balance={balance} onLogout={onLogout} />
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
