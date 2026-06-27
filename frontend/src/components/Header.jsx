import ProfileCard from './ProfileCard'

function Header({ username }) {
  const initials = username ? username.slice(0, 2).toUpperCase() : 'TV'

  return (
    <header className="header">
      <div className="header-left">
        <div className="header-logo">
          <span className="header-logo-icon">T</span>
          <span className="header-logo-text">TradeVerse</span>
        </div>
      </div>
      <div className="header-right">
        <ProfileCard />
        <div className="header-user">
          <span className="header-username">{username}</span>
          <div className="header-avatar">{initials}</div>
        </div>
      </div>
    </header>
  )
}

export default Header
