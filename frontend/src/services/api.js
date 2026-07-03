const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const STORAGE_KEY = 'tradeverse_user'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Получить JWT access-токен из localStorage */
function getAuthToken() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const user = JSON.parse(stored)
      return user.token || null
    }
  } catch { /* ignore */ }
  return null
}

/** Получить refresh-токен из localStorage */
function getRefreshToken() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const user = JSON.parse(stored)
      return user.refresh_token || null
    }
  } catch { /* ignore */ }
  return null
}

/** Обновить оба токена в localStorage */
function saveTokens(accessToken, refreshToken) {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const user = JSON.parse(stored)
      user.token = accessToken
      if (refreshToken) user.refresh_token = refreshToken
      localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    }
  } catch { /* ignore */ }
}

/** Очистить localStorage и выбросить событие принудительного логаута */
function forceLogout() {
  localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new CustomEvent('auth:force-logout'))
}

// ── Refresh lock: предотвращает параллельные refresh-запросы ──────────────
let refreshPromise = null

async function refreshAccessToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    forceLogout()
    throw new ApiError('Сессия истекла. Войдите заново.', 401)
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })

    if (!response.ok) {
      forceLogout()
      throw new ApiError('Сессия истекла. Войдите заново.', 401)
    }

    const data = await response.json()
    saveTokens(data.token, data.refresh_token)
    return data.token
  } catch (err) {
    if (err instanceof ApiError) throw err
    forceLogout()
    throw new ApiError('Не удалось обновить сессию.', 401)
  }
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`

  // Автоматически добавляем JWT- заголовок Authorization
  const token = getAuthToken()
  const authHeaders = {}
  if (token) {
    authHeaders['Authorization'] = `Bearer ${token}`
  }

  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
      ...options.headers,
    },
    ...options,
  }

  try {
    const response = await fetch(url, config)

    // ── 401 Interceptor: пробуем refresh, затем повторяем запрос ────────
    if (response.status === 401 && getRefreshToken()) {
      // Блокируем параллельные refresh-запросы
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => { refreshPromise = null })
      }
      const newToken = await refreshPromise

      // Повторяем оригинальный запрос с новым access-токеном
      const retryConfig = {
        ...config,
        headers: {
          ...config.headers,
          Authorization: `Bearer ${newToken}`,
        },
      }
      const retryResponse = await fetch(url, retryConfig)
      if (!retryResponse.ok) {
        const errorText = await retryResponse.text().catch(() => '')
        throw new ApiError(
          errorText || `Ошибка сервера: ${retryResponse.status}`,
          retryResponse.status
        )
      }
      return await retryResponse.json()
    }

    if (!response.ok) {
      const errorText = await response.text().catch(() => '')
      // При 401 автоматически разлогиниваем
      if (response.status === 401 && typeof window !== 'undefined') {
        localStorage.removeItem(STORAGE_KEY)
        window.dispatchEvent(new CustomEvent('auth:unauthorized'))
      }
      throw new ApiError(
        errorText || `Ошибка сервера: ${response.status}`,
        response.status
      )
    }

    return await response.json()
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError('Не удалось подключиться к серверу. Проверьте подключение.', 0)
  }
}

export async function fetchStocks() {
  return request('/api/stocks')
}

export async function fetchStock(symbol) {
  return request(`/api/stocks/${encodeURIComponent(symbol)}`)
}

export async function fetchTransactions(userId, limit = 50) {
  const params = new URLSearchParams()
  if (userId) params.set('user_id', userId)
  if (limit) params.set('limit', limit)
  const query = params.toString()
  return request(`/api/account/transactions${query ? `?${query}` : ''}`)
}

export async function fetchConfig(key) {
  return request(`/api/config/${encodeURIComponent(key)}`)
}

export async function fetchLeaderboard(limit = 10) {
  const params = new URLSearchParams()
  if (limit) params.set('limit', limit)
  return request(`/api/leaderboard?${params.toString()}`)
}

export async function toggleCardVisibility() {
  return request('/api/user/card-visibility', { method: 'PATCH' })
}

export async function fetchCurrentUser() {
  return request('/api/user/me')
}

export async function adminUpdateUser(userId, data) {
  return request(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminDeleteUser(userId) {
  return request(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}

// ── Stock Trading API ─────────────────────────────────────────────────────────

export async function fetchStocksV2() {
  return request('/api/v2/stocks')
}

export async function fetchStockV2(symbol) {
  return request(`/api/v2/stocks/${encodeURIComponent(symbol)}`)
}

export async function tradeStock(symbol, action, quantity) {
  return request('/api/v2/stocks/trade', {
    method: 'POST',
    body: JSON.stringify({ symbol, action, quantity }),
  })
}

export async function fetchPortfolio() {
  return request('/api/v2/stocks/portfolio')
}

export async function fetchStockOrders(limit = 50) {
  const params = new URLSearchParams()
  if (limit) params.set('limit', limit)
  return request(`/api/v2/stocks/orders?${params.toString()}`)
}

export async function fetchStockEvents(symbol = null, limit = 20) {
  const params = new URLSearchParams()
  if (symbol) params.set('symbol', symbol)
  if (limit) params.set('limit', limit)
  return request(`/api/v2/stocks/events?${params.toString()}`)
}

export async function updateStockConfig(symbol, configData) {
  return request(`/api/v2/stocks/${encodeURIComponent(symbol)}/config`, {
    method: 'PATCH',
    body: JSON.stringify(configData),
  })
}

// ── Shop Purchase API ────────────────────────────────────────────────────────

export async function purchaseItem(purchaseData) {
  return request('/api/shop/purchase', {
    method: 'POST',
    body: JSON.stringify(purchaseData),
  })
}

export async function fetchMyPurchases(limit = 100) {
  const params = new URLSearchParams()
  if (limit) params.set('limit', limit)
  return request(`/api/shop/purchases?${params.toString()}`)
}

export async function fetchBotOrders(limit = 100) {
  const params = new URLSearchParams()
  if (limit) params.set('limit', limit)
  return request(`/api/v2/stocks/bot-orders?${params.toString()}`)
}

export { API_BASE_URL, ApiError, request, forceLogout }
