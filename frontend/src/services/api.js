const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const STORAGE_KEY = 'tradeverse_user'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Получить JWT-токен из localStorage */
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

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`

  // Автоматически добавляем JWT-токен в заголовок Authorization
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

    if (!response.ok) {
      const errorText = await response.text().catch(() => '')
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

export async function fetchStocksV2() {
  return request('/api/stocks/v2')
}

export async function updateStockConfig(symbol, configOverrides) {
  return request(`/api/stocks/${encodeURIComponent(symbol)}/config`, {
    method: 'PATCH',
    body: JSON.stringify({ configOverrides }),
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

export { API_BASE_URL, ApiError, request }
