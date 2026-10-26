import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import './App.css'
import './landing.css'
import AuthPage from './components/AuthPage'
import Dashboard from './components/Dashboard'
import Landing from './components/Landing'
import { logoutUser, startTokenRefresh, stopTokenRefresh } from './services/api'

const STORAGE_KEY = 'tradeverse_user'

function App() {
  const [user, setUser] = useState(null)

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        const parsed = JSON.parse(stored)
        setUser(parsed)
        // Проактивное обновление токена для уже залогиненной сессии
        startTokenRefresh()
      } catch {
        setUser({ username: stored, id: null })
      }
    }

    // Автоматический логаут при 401 с сервера
    function onUnauthorized() {
      setUser(null)
      stopTokenRefresh()
      localStorage.removeItem(STORAGE_KEY)
    }
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized)
  }, [])

  const handleLogin = useCallback((userData) => {
    const userObj = typeof userData === 'string'
      ? { username: userData, id: null, role: 'user', token: null }
      : userData
    setUser(userObj)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(userObj))
    // Запускаем проактивное обновление access-токена
    startTokenRefresh()
  }, [])

  const handleLogout = useCallback(() => {
    // Инвалидируем refresh-токен на сервере, затем чистим локальное состояние.
    // logoutUser устойчив к сетевым ошибкам — локальный выход произойдёт в любом случае.
    logoutUser().finally(() => {
      setUser(null)
    })
  }, [])

  // Слушаем принудительный логаут (истёк refresh-токен)
  useEffect(() => {
    const onForceLogout = () => {
      setUser(null)
    }
    window.addEventListener('auth:force-logout', onForceLogout)
    return () => window.removeEventListener('auth:force-logout', onForceLogout)
  }, [])

  // Обновление профиля (никнейм/аватар) из страницы «Настройки» — без
  // перезахода: мержим изменения в состояние и localStorage, всё дерево
  // компонентов (Header, Sidebar, …) получает свежие данные через пропсы.
  const handleUserUpdate = useCallback((patch) => {
    setUser(prev => {
      if (!prev) return prev
      const merged = { ...prev, ...patch }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(merged))
      return merged
    })
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            user
              ? <Dashboard user={user} onLogout={handleLogout} onUserUpdate={handleUserUpdate} />
              : <Landing />
          }
        />
        <Route
          path="/login"
          element={
            user
              ? <Navigate to="/" replace />
              : <LoginRoute onLogin={handleLogin} />
          }
        />
        {/* SPA fallback: неизвестные пути ведут на корень */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

/** Обёртка над AuthPage: после успешного логина уводим на корень (Dashboard). */
function LoginRoute({ onLogin }) {
  const navigate = useNavigate()
  const handleLogin = (userData) => {
    onLogin(userData)
    navigate('/', { replace: true })
  }
  return <AuthPage onLogin={handleLogin} />
}

export default App
