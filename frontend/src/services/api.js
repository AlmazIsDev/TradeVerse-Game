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
      const raw = await response.text().catch(() => '')
      let message = raw
      if (raw) {
        try {
          const parsed = JSON.parse(raw)
          if (typeof parsed?.detail === 'string') {
            message = parsed.detail
          } else if (Array.isArray(parsed?.detail)) {
            // Ошибки валидации Pydantic: [{ loc, msg, ... }]
            message = parsed.detail.map(e => e.msg).filter(Boolean).join('; ') || raw
          }
        } catch { /* тело не JSON — используем как есть */ }
      }
      throw new ApiError(
        message || `Ошибка сервера: ${response.status}`,
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

/**
 * История операций текущего пользователя (JWT-scoped).
 * Возвращает { items, total, skip, limit }.
 * @param {{direction?:string, category?:string, search?:string, sort?:string, skip?:number, limit?:number}} opts
 */
export async function fetchTransactions(opts = {}) {
  const params = new URLSearchParams()
  const { direction, category, search, sort, skip, limit } = opts
  if (direction) params.set('direction', direction)
  if (category) params.set('category', category)
  if (search) params.set('search', search)
  if (sort) params.set('sort', sort)
  if (skip != null) params.set('skip', skip)
  if (limit != null) params.set('limit', limit)
  const query = params.toString()
  return request(`/api/account/transactions${query ? `?${query}` : ''}`)
}

/** Аналитика за неделю: доход/расход/изменение капитала/операции/график. */
export async function fetchWeeklyAnalytics() {
  return request('/api/account/analytics/weekly')
}

/** Перевод денег другому игроку по username или номеру карты. */
export async function createTransfer({ recipient, amount, note }) {
  return request('/api/transfers', {
    method: 'POST',
    body: JSON.stringify({ recipient, amount, note }),
  })
}

export async function fetchConfig(key) {
  return request(`/api/config/${encodeURIComponent(key)}`)
}

export async function fetchLeaderboard(limit = 20, sort = 'networth') {
  const params = new URLSearchParams()
  if (limit) params.set('limit', limit)
  if (sort) params.set('sort', sort)
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

// ── Crypto API ────────────────────────────────────────────────────────────────

export async function openCryptoAccount() {
  return request('/api/crypto/account/open', { method: 'POST' })
}

export async function fetchCryptoAccount() {
  return request('/api/crypto/account')
}

export async function fetchCryptoMarket() {
  return request('/api/crypto/market')
}

export async function tradeCrypto(symbol, action, quantity) {
  return request('/api/crypto/trade', {
    method: 'POST',
    body: JSON.stringify({ symbol, action, quantity }),
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

// ── Assets API (real estate / business / cars) ─────────────────────────────────

export async function fetchAssetMarket(opts = {}) {
  const params = new URLSearchParams()
  const { type, search, min_price, max_price } = opts
  if (type) params.set('type', type)
  if (search) params.set('search', search)
  if (min_price != null) params.set('min_price', min_price)
  if (max_price != null) params.set('max_price', max_price)
  const q = params.toString()
  return request(`/api/assets/market${q ? `?${q}` : ''}`)
}

export async function buyAsset(slug) {
  return request('/api/assets/buy', { method: 'POST', body: JSON.stringify({ slug }) })
}

export async function fetchMyAssets(type) {
  const q = type ? `?type=${encodeURIComponent(type)}` : ''
  return request(`/api/assets/mine${q}`)
}

export async function collectAsset(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/collect`, { method: 'POST' })
}

export async function upgradeAsset(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/upgrade`, { method: 'POST' })
}

export async function sellAsset(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/sell`, { method: 'POST' })
}

// ── Company API ────────────────────────────────────────────────────────────────

export async function fetchCompany() {
  return request('/api/company')
}

export async function createCompany(name) {
  return request('/api/company', { method: 'POST', body: JSON.stringify({ name }) })
}

export async function hireEmployee({ name, role, salary }) {
  return request('/api/company/employees', { method: 'POST', body: JSON.stringify({ name, role, salary }) })
}

export async function updateEmployeeSalary(empId, salary) {
  return request(`/api/company/employees/${encodeURIComponent(empId)}`, {
    method: 'PATCH', body: JSON.stringify({ salary }),
  })
}

export async function fireEmployee(empId) {
  return request(`/api/company/employees/${encodeURIComponent(empId)}`, { method: 'DELETE' })
}

export async function collectCompanyProfit() {
  return request('/api/company/collect', { method: 'POST' })
}

export async function companyDeposit(amount) {
  return request('/api/company/deposit', { method: 'POST', body: JSON.stringify({ amount }) })
}

export async function companyWithdraw(amount) {
  return request('/api/company/withdraw', { method: 'POST', body: JSON.stringify({ amount }) })
}

// ── City Roof (minigame + WarCoin) ─────────────────────────────────────────────

export async function fetchCityMap() {
  return request('/api/cityroof/map')
}

export async function fetchWarcoin() {
  return request('/api/cityroof/warcoin')
}

export async function buyWarcoin(amount) {
  return request('/api/cityroof/warcoin/buy', { method: 'POST', body: JSON.stringify({ amount }) })
}

export async function attackBusiness(id) {
  return request(`/api/cityroof/attack/${encodeURIComponent(id)}`, { method: 'POST' })
}

export async function guessCombination(sessionId, guess) {
  return request('/api/cityroof/guess', { method: 'POST', body: JSON.stringify({ sessionId, guess }) })
}

export async function protectBusiness(id, level) {
  return request(`/api/cityroof/protect/${encodeURIComponent(id)}`, { method: 'POST', body: JSON.stringify({ level }) })
}

export async function fetchSeasons() {
  return request('/api/cityroof/seasons')
}

export { API_BASE_URL, ApiError, request }
