function Sidebar({ activeTab, onTabChange }) {
  const menuItems = [
    { id: 'account', label: 'Счёт', icon: '💰' },
    { id: 'bank', label: 'Банк', icon: '🏦' },
    { id: 'shop', label: 'Магазин', icon: '🛒' },
    { id: 'events', label: 'Мероприятия', icon: '🎉' },
    { id: 'crypto', label: 'Криптовалюта', icon: '🪙' },
    { id: 'stocks', label: 'Акции', icon: '📈' },
    { id: 'realestate', label: 'Покупка недвижимости', icon: '🏠' },
    { id: 'myhomes', label: 'Мои дома', icon: '🏡' },
    { id: 'mybusiness', label: 'Мои бизнесы', icon: '💼' },
    { id: 'mycompany', label: 'Моя Компания', icon: '🏢' },
    { id: 'leaderboard', label: 'Таблица лидеров', icon: '🏆' },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">T</div>
        <span className="sidebar-logo-text">TradeVerse</span>
      </div>
      <nav className="sidebar-nav">
        {menuItems.map(item => (
          <button
            key={item.id}
            className={`sidebar-item ${activeTab === item.id ? 'active' : ''}`}
            onClick={() => onTabChange(item.id)}
          >
            <span className="sidebar-item-icon">{item.icon}</span>
            <span className="sidebar-item-label">{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  )
}

export default Sidebar
