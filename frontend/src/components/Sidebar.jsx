import { useTranslation } from 'react-i18next'
// Car — иконка для пункта меню «Автосалон» (CarsTab).
import { Wallet, Building2, ShoppingCart, Castle, Coins, TrendingUp, Home, Building, Store, Trophy, Cpu, Settings, Landmark, Car, Handshake } from 'lucide-react'

const ICON_MAP = {
  account: Wallet,
  bank: Building2,
  shop: ShoppingCart,
  cityroof: Castle,
  crypto: Coins,
  stocks: TrendingUp,
  mining: Cpu,
  realestate: Home,
  centralmarket: Landmark,
  myhomes: Building,
  mycompany: Store,
  leaderboard: Trophy,
  settings: Settings,
  cars: Car,
  playerbusinesses: Handshake,
}

function Sidebar({ activeTab, onTabChange }) {
  const { t } = useTranslation()

  // Пункты сгруппированы по смыслу: финансы, рынки, активы, сообщество.
  const groups = [
    { title: t('nav.groupFinance'), items: [
      { id: 'account', label: t('nav.account') },
      { id: 'bank', label: t('nav.bank') },
    ] },
    { title: t('nav.groupMarkets'), items: [
      { id: 'centralmarket', label: t('nav.centralMarket') },
      { id: 'crypto', label: t('nav.crypto') },
      { id: 'stocks', label: t('nav.stocks') },
      { id: 'realestate', label: t('nav.realestate') },
      { id: 'shop', label: t('nav.shop') },
      { id: 'cars', label: t('nav.cars', 'Автосалон') },
      { id: 'playerbusinesses', label: t('nav.playerBusinesses', 'Бизнесы игроков') },
    ] },
    { title: t('nav.groupAssets'), items: [
      { id: 'mining', label: t('nav.mining') },
      { id: 'cityroof', label: t('nav.cityroof') },
      { id: 'myhomes', label: t('nav.myhomes') },
      { id: 'mycompany', label: t('nav.mycompany') },
    ] },
    { title: t('nav.groupCommunity'), items: [
      { id: 'leaderboard', label: t('nav.leaderboard') },
    ] },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon"><img src="/favicon.svg" alt="TradeVerse" className="logo-glyph" /></div>
        <span className="sidebar-logo-text">TradeVerse</span>
      </div>
      <nav className="sidebar-nav">
        {groups.map(group => (
          <div className="sidebar-group" key={group.title}>
            <span className="sidebar-group-title">{group.title}</span>
            {group.items.map(item => {
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
          </div>
        ))}
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
