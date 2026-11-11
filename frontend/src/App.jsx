import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import './App.css'
import './mobile.css'
import './landing.css'
import AuthPage from './components/AuthPage'
import Dashboard from './components/Dashboard'
import Landing from './components/Landing'
import { logoutUser, startTokenRefresh, stopTokenRefresh, fetchBanStatus } from './services/api'
import SupportPage from './components/SupportPage'

const STORAGE_KEY = 'tradeverse_user'

function App() {
  const [user, setUser] = useState(null)
  const [accountBan, setAccountBan] = useState(null)

  useEffect(() => {
    if (!user) { setAccountBan(null); return }
    let active = true
    fetchBanStatus()
      .then(status => { if (active) setAccountBan(status.account_banned ? status : null) })
      .catch(() => { if (active) setAccountBan(null) })
    return () => { active = false }
  }, [user])

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
            !user
              ? <Landing />
              : accountBan
                ? <BannedView status={accountBan} onLogout={handleLogout} />
                : <Dashboard user={user} onLogout={handleLogout} onUserUpdate={handleUserUpdate} />
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

/** Полный бан аккаунта: доступна только поддержка, чтобы оспорить решение. */
function BannedView({ status, onLogout }) {
  const { t } = useTranslation()
  return (
    <div className="banned-view">
      <h1>{t('banned.title', 'Аккаунт заблокирован')}</h1>
      {status.detail && <p>{status.detail}</p>}
      {status.until && <p>{t('banned.until', 'До')}: {new Date(status.until).toLocaleString()}</p>}
      <p>{t('banned.supportHint', 'Если вы считаете бан ошибочным, откройте обращение в поддержке.')}</p>
      <SupportPage />
      <button type="button" className="support-cancel-btn" onClick={onLogout}>{t('header.logout', 'Выйти')}</button>
    </div>
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
