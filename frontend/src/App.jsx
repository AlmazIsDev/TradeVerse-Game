import { useCallback, useEffect, useState } from 'react'
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
  }, [])

  const handleLogin = (userData) => {
    const userObj = typeof userData === 'string'
      ? { username: userData, id: null, role: 'user', token: null }
      : userData
    setUser(userObj)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(userObj))
  }

  const handleLogout = useCallback(() => {
    // Инвалидируем refresh-токен на сервере (fire-and-forget)
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        if (parsed.refresh_token) {
          fetch(
            `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/auth/logout`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh_token: parsed.refresh_token }),
            }
          ).catch(() => {})
        }
      }
    } catch { /* ignore */ }

    setUser(null)
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  // Слушаем принудительный логаут (истёк refresh-токен)
  useEffect(() => {
    const onForceLogout = () => {
      setUser(null)
    }
    window.addEventListener('auth:force-logout', onForceLogout)
    return () => window.removeEventListener('auth:force-logout', onForceLogout)
  }, [])

  if (!user) {
    return <AuthPage onLogin={handleLogin} />
  }

  return <Dashboard user={user} onLogout={handleLogout} />
}

export default App
