import { useEffect, useState } from 'react'
import './App.css'
import AuthPage from './components/AuthPage'
import Dashboard from './components/Dashboard'

const STORAGE_KEY = 'tradeverse_user'

function App() {
  const [user, setUser] = useState(null)

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      setUser(stored)
    }
  }, [])

  const handleLogin = (username) => {
    setUser(username)
    localStorage.setItem(STORAGE_KEY, username)
  }

  const handleLogout = () => {
    setUser(null)
    localStorage.removeItem(STORAGE_KEY)
  }

  if (!user) {
    return <AuthPage onLogin={handleLogin} />
  }

  return <Dashboard username={user} onLogout={handleLogout} />
}

export default App
