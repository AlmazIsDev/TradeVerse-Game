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
      try {
        const parsed = JSON.parse(stored)
        setUser(parsed)
      } catch {
        setUser({ username: stored, id: null })
      }
    }

    // Автоматический логаут при 401 с сервера
    function onUnauthorized() {
      setUser(null)
      localStorage.removeItem(STORAGE_KEY)
    }
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized)
  }, [])

  const handleLogin = (userData) => {
    const userObj = typeof userData === 'string'
      ? { username: userData, id: null, role: 'user', token: null }
      : userData
    setUser(userObj)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(userObj))
  }

  const handleLogout = () => {
    setUser(null)
    localStorage.removeItem(STORAGE_KEY)
  }

  if (!user) {
    return <AuthPage onLogin={handleLogin} />
  }

  return <Dashboard user={user} onLogout={handleLogout} />
}

export default App
