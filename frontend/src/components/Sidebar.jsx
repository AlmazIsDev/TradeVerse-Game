import { useTranslation } from 'react-i18next'
import { Wallet, Building2, ShoppingCart, Castle, Coins, TrendingUp, Home, Building, Store, Trophy, Cpu, Settings } from 'lucide-react'

const ICON_MAP = {
  account: Wallet,
  bank: Building2,
  shop: ShoppingCart,
  cityroof: Castle,
  crypto: Coins,
  stocks: TrendingUp,
  mining: Cpu,
  realestate: Home,
  myhomes: Building,
  mycompany: Store,
  leaderboard: Trophy,
  settings: Settings,
}

function Sidebar({ activeTab, onTabChange }) {
  const { t } = useTranslation()

  const menuItems = [
    { id: 'account', label: t('nav.account'), icon: 'account' },
    { id: 'bank', label: t('nav.bank'), icon: 'bank' },
    { id: 'shop', label: t('nav.shop'), icon: 'shop' },
    { id: 'cityroof', label: t('nav.cityroof'), icon: 'cityroof' },
    { id: 'crypto', label: t('nav.crypto'), icon: 'crypto' },
    { id: 'stocks', label: t('nav.stocks'), icon: 'stocks' },
    { id: 'mining', label: t('nav.mining'), icon: 'mining' },
    { id: 'realestate', label: t('nav.realestate'), icon: 'realestate' },
    { id: 'myhomes', label: t('nav.myhomes'), icon: 'myhomes' },
    { id: 'mycompany', label: t('nav.mycompany'), icon: 'mycompany' },
    { id: 'leaderboard', label: t('nav.leaderboard'), icon: 'leaderboard' },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon"><img src="/favicon.svg" alt="TradeVerse" className="logo-glyph" /></div>
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
      <div className="sidebar-footer">
        <button
          className={`sidebar-item ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => onTabChange('settings')}
        >
          <span className="sidebar-item-icon"><Settings size={18} /></span>
          <span className="sidebar-item-label">{t('nav.settings')}</span>
        </button>
      </div>
    </aside>
  )
}

export default Sidebar
