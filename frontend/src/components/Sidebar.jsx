import { useTranslation } from 'react-i18next'
import { fetchConfig } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { Wallet, Building2, ShoppingCart, PartyPopper, Coins, TrendingUp, Home, Building, Briefcase, Store, Trophy } from 'lucide-react'

const ICON_MAP = {
  account: Wallet,
  bank: Building2,
  shop: ShoppingCart,
  events: PartyPopper,
  crypto: Coins,
  stocks: TrendingUp,
  realestate: Home,
  myhomes: Building,
  mybusiness: Briefcase,
  mycompany: Store,
  leaderboard: Trophy,
}

function Sidebar({ activeTab, onTabChange }) {
  const { t } = useTranslation()
  const { data: menuConfig, loading } = useApiOnMount(() => fetchConfig('sidebar_menu'))

  const menuItems = [
    { id: 'account', label: t('nav.account'), icon: 'account' },
    { id: 'bank', label: t('nav.bank'), icon: 'bank' },
    { id: 'shop', label: t('nav.shop'), icon: 'shop' },
    { id: 'events', label: t('nav.events'), icon: 'events' },
    { id: 'crypto', label: t('nav.crypto'), icon: 'crypto' },
    { id: 'stocks', label: t('nav.stocks'), icon: 'stocks' },
    { id: 'realestate', label: t('nav.realestate'), icon: 'realestate' },
    { id: 'myhomes', label: t('nav.myhomes'), icon: 'myhomes' },
    { id: 'mybusiness', label: t('nav.mybusiness'), icon: 'mybusiness' },
    { id: 'mycompany', label: t('nav.mycompany'), icon: 'mycompany' },
    { id: 'leaderboard', label: t('nav.leaderboard'), icon: 'leaderboard' },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">T</div>
        <span className="sidebar-logo-text">TradeVerse</span>
      </div>
      <nav className="sidebar-nav">
        {menuItems.map(item => {
          const IconComponent = ICON_MAP[item.id] || Wallet
          return (
            <button
              key={item.id}
              className={`sidebar-item ${activeTab === item.id ? 'active' : ''}`}
              onClick={() => onTabChange(item.id)}
            >
              <span className="sidebar-item-icon"><IconComponent size={18} /></span>
              <span className="sidebar-item-label">{item.label}</span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}

export default Sidebar
