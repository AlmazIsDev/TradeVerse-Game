import { useState } from 'react'
import Sidebar from './Sidebar'
import Header from './Header'
import AccountTab from './AccountTab'
import StocksTab from './StocksTab'
import BankTab from './BankTab'

function Dashboard({ username, onLogout }) {
  const [activeTab, setActiveTab] = useState('account')

  const renderContent = () => {
    switch (activeTab) {
      case 'account':
        return <AccountTab />
      case 'stocks':
        return <StocksTab />
      case 'bank':
        return <BankTab />
      case 'shop':
        return <PlaceholderTab title="Магазин" icon="🛒" />
      case 'events':
        return <PlaceholderTab title="Мероприятия" icon="🎉" />
      case 'crypto':
        return <PlaceholderTab title="Криптовалюта" icon="🪙" />
      case 'realestate':
        return <PlaceholderTab title="Покупка недвижимости" icon="🏠" />
      case 'myhomes':
        return <PlaceholderTab title="Мои дома" icon="🏡" />
      case 'mybusiness':
        return <PlaceholderTab title="Мои бизнесы" icon="💼" />
      case 'mycompany':
        return <PlaceholderTab title="Моя Компания" icon="🏢" />
      case 'leaderboard':
        return <PlaceholderTab title="Таблица лидеров" icon="🏆" />
      default:
        return <AccountTab />
    }
  }

  return (
    <div className="dashboard">
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
      <div className="dashboard-main">
        <Header username={username} />
        <div className="dashboard-content">
          {renderContent()}
        </div>
      </div>
    </div>
  )
}

function PlaceholderTab({ title, icon }) {
  return (
    <div className="placeholder-tab">
      <h2 className="tab-title">{title}</h2>
      <div className="placeholder-content">
        <span className="placeholder-icon">{icon}</span>
        <p>Раздел «{title}» скоро будет доступен</p>
      </div>
    </div>
  )
}

export default Dashboard
