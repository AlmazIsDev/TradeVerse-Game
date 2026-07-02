import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import Sidebar from './Sidebar'
import Header from './Header'
import AccountTab from './AccountTab'
import StocksTab from './StocksTab'
import BankTab from './BankTab'
import ShopTab from './ShopTab'
import LeaderboardTab from './LeaderboardTab'
import AdminPanel from './AdminPanel'
import { fetchCurrentUser } from '../services/api'
import { Castle, Coins, Home, Building, Briefcase, Store, Shield } from 'lucide-react'

function Dashboard({ user, onLogout, onUserUpdate }) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('account')
  const [showAdmin, setShowAdmin] = useState(false)

  const isAdmin = user?.role === 'admin'

  // Подтягиваем актуальные данные пользователя (баланс/роль) с сервера при входе.
  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then(data => {
        if (cancelled || !data) return
        onUserUpdate?.({
          id: data.id,
          balance: data.balance,
          role: data.role,
          card_number: data.card_number,
          card_visible: data.card_visible,
        })
      })
      .catch(() => { /* offline / unauthorized — используем локальные данные */ })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const renderContent = () => {
    switch (activeTab) {
      case 'account':
        return <AccountTab userId={user?.id} balance={user?.balance} />
      case 'stocks':
        return <StocksTab onUserUpdate={onUserUpdate} />
      case 'bank':
        return <BankTab userId={user?.id} />
      case 'shop':
        return <ShopTab />
      case 'leaderboard':
        return <LeaderboardTab currentUserId={user?.id} />
      case 'cityroof':
        return <PlaceholderTab title={t('nav.cityroof')} icon={Castle} />
      case 'crypto':
        return <PlaceholderTab title={t('nav.crypto')} icon={Coins} />
      case 'realestate':
        return <PlaceholderTab title={t('nav.realestate')} icon={Home} />
      case 'myhomes':
        return <PlaceholderTab title={t('nav.myhomes')} icon={Building} />
      case 'mybusiness':
        return <PlaceholderTab title={t('nav.mybusiness')} icon={Briefcase} />
      case 'mycompany':
        return <PlaceholderTab title={t('nav.mycompany')} icon={Store} />
      default:
        return <AccountTab userId={user?.id} balance={user?.balance} />
    }
  }

  return (
    <div className="dashboard">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} user={user} />
      <div className="dashboard-main">
        <Header username={user?.username} balance={user?.balance} onLogout={onLogout} />
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

function PlaceholderTab({ title, icon: Icon }) {
  const { t } = useTranslation()
  return (
    <div className="placeholder-tab">
      <h2 className="tab-title">{title}</h2>
      <div className="placeholder-content">
        <span className="placeholder-icon"><Icon size={48} /></span>
        <p>{t('dashboard.comingSoon', { title })}</p>
      </div>
    </div>
  )
}

export default Dashboard
