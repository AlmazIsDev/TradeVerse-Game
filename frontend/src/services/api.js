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
  stopTokenRefresh()
  localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new CustomEvent('auth:force-logout'))
}

/**
 * Разлогин по инициативе пользователя: инвалидируем refresh-токен на сервере
 * (best-effort), затем очищаем локальное состояние. Логаут происходит локально
 * даже если сетевой запрос упал.
 */
async function logoutUser() {
  const refreshToken = getRefreshToken()
  stopTokenRefresh()
  if (refreshToken) {
    try {
      await fetch(`${API_BASE_URL}/api/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    } catch { /* сеть недоступна — всё равно выходим локально */ }
  }
  localStorage.removeItem(STORAGE_KEY)
}

// ── Проактивное обновление access-токена ────────────────────────────────────
// Декодируем `exp` из JWT (base64url payload) и планируем refresh за ~2 мин до
// истечения. Также обновляем токен при возврате фокуса на вкладку, если он
// близок к истечению. 401-интерцептор остаётся страховкой.

const REFRESH_LEEWAY_MS = 2 * 60 * 1000 // обновляем за 2 минуты до exp

let refreshTimer = null
let focusHandlerBound = false

/** Вернуть Unix-время (ms) истечения access-токена или null. */
function getTokenExpiryMs(token) {
  if (!token || typeof token !== 'string') return null
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    let payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    // Восстанавливаем padding для корректного base64
    while (payload.length % 4) payload += '='
    const json = JSON.parse(atob(payload))
    if (typeof json.exp !== 'number') return null
    return json.exp * 1000
  } catch {
    return null
  }
}

/**
 * Обновить access-токен через общий (across-caller) lock и перепланировать
 * следующий проактивный refresh. Используется и таймером, и focus-хендлером —
 * единая точка, чтобы поведение блокировки/повтора не расходилось между ними.
 */
async function refreshAndReschedule() {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => { refreshPromise = null })
  }
  try {
    await refreshPromise
    scheduleTokenRefresh() // перепланируем после успешного обновления
  } catch { /* refreshAccessToken уже вызвал forceLogout */ }
}

/** Запланировать следующий refresh на основе exp текущего access-токена. */
function scheduleTokenRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }

  const token = getAuthToken()
  const expMs = getTokenExpiryMs(token)
  if (expMs == null) return

  // Обновляем за REFRESH_LEEWAY_MS до истечения, но не реже чем через 1с
  const delay = Math.max(1000, expMs - Date.now() - REFRESH_LEEWAY_MS)

  refreshTimer = setTimeout(refreshAndReschedule, delay)
}

/** Обновить токен при фокусе, если он истёк или близок к истечению. */
async function onWindowFocus() {
  if (!getRefreshToken()) return
  const expMs = getTokenExpiryMs(getAuthToken())
  // Если exp неизвестен или уже близок к истечению — освежаем немедленно
  if (expMs == null || expMs - Date.now() <= REFRESH_LEEWAY_MS) {
    await refreshAndReschedule()
  }
}

/** Запустить проактивное обновление (вызывать при логине / монтировании). */
function startTokenRefresh() {
  if (!getRefreshToken()) return
  scheduleTokenRefresh()
  if (!focusHandlerBound && typeof window !== 'undefined') {
    window.addEventListener('focus', onWindowFocus)
    focusHandlerBound = true
  }
}

/** Остановить проактивное обновление (вызывать при логауте). */
function stopTokenRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
  if (focusHandlerBound && typeof window !== 'undefined') {
    window.removeEventListener('focus', onWindowFocus)
    focusHandlerBound = false
  }
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
    // Перепланируем проактивный refresh под новый exp (страховка для 401-пути)
    scheduleTokenRefresh()
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

  // Для FormData (загрузка файлов, напр. аватар) НЕ проставляем Content-Type —
  // браузер сам подставит правильный multipart/form-data с boundary.
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const config = {
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
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
      const raw = await response.text().catch(() => '')
      // При 401 без refresh-токена автоматически разлогиниваем
      if (response.status === 401 && typeof window !== 'undefined') {
        localStorage.removeItem(STORAGE_KEY)
        window.dispatchEvent(new CustomEvent('auth:unauthorized'))
      }
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
  const { direction, category, search, sort, skip, limit, companyId } = opts
  if (direction) params.set('direction', direction)
  if (category) params.set('category', category)
  if (search) params.set('search', search)
  if (sort) params.set('sort', sort)
  if (skip != null) params.set('skip', skip)
  if (limit != null) params.set('limit', limit)
  if (companyId) params.set('companyId', companyId)
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

/** Сменить никнейм. */
export async function updateProfile(data) {
  return request('/api/user/profile', { method: 'PATCH', body: JSON.stringify(data) })
}

/** Сменить пароль (требует текущий пароль). */
export async function changePassword(data) {
  return request('/api/user/password', { method: 'POST', body: JSON.stringify(data) })
}

/**
 * Загрузить/сменить аватар. dataUrl — уже сжатое на клиенте изображение
 * (см. SettingsPage: canvas resize → toDataURL), передаётся как обычный JSON
 * (не multipart) и хранится строкой в документе пользователя — без отдельной
 * инфраструктуры файлового хранилища. Возвращает { avatar }.
 */
export async function uploadAvatar(dataUrl) {
  return request('/api/user/avatar', { method: 'PATCH', body: JSON.stringify({ avatar: dataUrl }) })
}

/** Удалить аватар — сброс на инициалы. */
export async function deleteAvatar() {
  return request('/api/user/avatar', { method: 'DELETE' })
}

/** Переключить участие в таблице лидеров. */
export async function toggleLeaderboardVisibility() {
  return request('/api/user/leaderboard-visibility', { method: 'PATCH' })
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

// ── Admin: имущество игрока ─────────────────────────────────────────────────

/** Полный список имущества игрока: активы, майнинг-фермы, компания, бизнесы «Крыши города». */
export async function adminFetchUserProperty(userId) {
  return request(`/api/admin/users/${encodeURIComponent(userId)}/property`)
}

export async function adminUpdateAsset(assetId, data) {
  return request(`/api/assets/admin/${encodeURIComponent(assetId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminDeleteAsset(assetId) {
  return request(`/api/assets/admin/${encodeURIComponent(assetId)}`, { method: 'DELETE' })
}

export async function adminTransferAsset(assetId, toUsername) {
  return request(`/api/assets/admin/${encodeURIComponent(assetId)}/transfer`, {
    method: 'POST',
    body: JSON.stringify({ toUsername }),
  })
}

export async function adminUpdateFarm(farmId, data) {
  return request(`/api/mining/admin/farms/${encodeURIComponent(farmId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminDeleteFarm(farmId) {
  return request(`/api/mining/admin/farms/${encodeURIComponent(farmId)}`, { method: 'DELETE' })
}

export async function adminTransferFarm(farmId, toUsername) {
  return request(`/api/mining/admin/farms/${encodeURIComponent(farmId)}/transfer`, {
    method: 'POST',
    body: JSON.stringify({ toUsername }),
  })
}

export async function adminUpdateCompany(companyId, data) {
  return request(`/api/company/admin/${encodeURIComponent(companyId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminDeleteCompany(companyId) {
  return request(`/api/company/admin/${encodeURIComponent(companyId)}`, { method: 'DELETE' })
}

export async function adminTransferCompany(companyId, toUsername) {
  return request(`/api/company/admin/${encodeURIComponent(companyId)}/transfer`, {
    method: 'POST',
    body: JSON.stringify({ toUsername }),
  })
}

export async function adminUpdateBusiness(businessId, data) {
  return request(`/api/cityroof/admin/businesses/${encodeURIComponent(businessId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function adminVacateBusiness(businessId) {
  return request(`/api/cityroof/admin/businesses/${encodeURIComponent(businessId)}/vacate`, {
    method: 'POST',
  })
}

export async function adminTransferBusiness(businessId, toUsername) {
  return request(`/api/cityroof/admin/businesses/${encodeURIComponent(businessId)}/transfer`, {
    method: 'POST',
    body: JSON.stringify({ toUsername }),
  })
}

// ── Admin economy panel ────────────────────────────────────────────────────────

export async function fetchEconomyAnalytics() {
  return request('/api/admin/economy/analytics')
}

export async function fetchEconomyConfig() {
  return request('/api/admin/economy/config')
}

export async function updateEconomyConfig(data) {
  return request('/api/admin/economy/config', { method: 'POST', body: JSON.stringify(data) })
}

export async function fetchEconomyEvents() {
  return request('/api/admin/economy/events')
}

export async function startEconomyEvent(type) {
  return request('/api/admin/economy/events/start', { method: 'POST', body: JSON.stringify({ type }) })
}

export async function stopEconomyEvent(eventId) {
  return request(`/api/admin/economy/events/${encodeURIComponent(eventId)}/stop`, { method: 'POST' })
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

export async function transferCrypto(recipient, symbol, amount) {
  return request('/api/crypto/transfer', {
    method: 'POST',
    body: JSON.stringify({ recipient, symbol, amount }),
  })
}

export async function fetchCryptoTransfers(limit = 30) {
  return request(`/api/crypto/transfers?limit=${limit}`)
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

export async function fetchBotOrders(limit = 100) {
  const params = new URLSearchParams()
  if (limit) params.set('limit', limit)
  return request(`/api/v2/stocks/bot-orders?${params.toString()}`)
}

export async function issueStock({ name, symbol, description, totalShares, price }) {
  return request('/api/v2/stocks/issue', {
    method: 'POST',
    body: JSON.stringify({ name, symbol, description, totalShares, price }),
  })
}

export async function payDividend(symbol, perShare) {
  return request(`/api/v2/stocks/${encodeURIComponent(symbol)}/dividend`, {
    method: 'POST',
    body: JSON.stringify({ perShare }),
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

export async function collectAllAssets() {
  return request('/api/assets/collect-all', { method: 'POST' })
}

export async function upgradeAsset(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/upgrade`, { method: 'POST' })
}

export async function sellAsset(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/sell`, { method: 'POST' })
}

export async function transferAssetToCompany(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/transfer-to-company`, { method: 'POST' })
}

export async function transferAssetToPlayer(id, toUsername) {
  return request(`/api/assets/${encodeURIComponent(id)}/transfer-to-player`, {
    method: 'POST', body: JSON.stringify({ toUsername }),
  })
}

export async function tuneCar(id, part) {
  return request(`/api/assets/${encodeURIComponent(id)}/tune`, { method: 'POST', body: JSON.stringify({ part }) })
}

export async function listPropertyForRent(id, minHours) {
  return request(`/api/assets/${encodeURIComponent(id)}/rent/list`, {
    method: 'POST', body: JSON.stringify({ minHours }),
  })
}

export async function cancelRent(id) {
  return request(`/api/assets/${encodeURIComponent(id)}/rent/cancel`, { method: 'POST' })
}

// ── Materials for business ───────────────────────────────────────────────────

export async function fetchMaterialsPrice() {
  return request('/api/assets/materials/price')
}

export async function buyMaterials(id, qty) {
  return request(`/api/assets/${encodeURIComponent(id)}/materials/buy`, {
    method: 'POST', body: JSON.stringify({ qty }),
  })
}

// ── Notifications API ───────────────────────────────────────────────────────────

export async function fetchNotifications(limit = 30) {
  return request(`/api/notifications?limit=${limit}`)
}

export async function markNotificationRead(id) {
  return request(`/api/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' })
}

export async function markAllNotificationsRead() {
  return request('/api/notifications/read-all', { method: 'POST' })
}

// ── Market data (history / asset detail / favorites) ────────────────────────────

export async function fetchMarketAsset(market, symbol) {
  return request(`/api/market/asset?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`)
}

export async function fetchMarketHistory(market, symbol, interval = '7d') {
  return request(`/api/market/history?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`)
}

export async function fetchFavorites() {
  return request('/api/favorites')
}

export async function toggleFavorite(market, symbol) {
  return request('/api/favorites/toggle', { method: 'POST', body: JSON.stringify({ market, symbol }) })
}

// ── Company API ────────────────────────────────────────────────────────────────

export async function fetchCompany() {
  return request('/api/company')
}

export async function createCompany(name) {
  return request('/api/company', { method: 'POST', body: JSON.stringify({ name }) })
}

export async function updateCompanySettings(payload) {
  return request('/api/company', { method: 'PATCH', body: JSON.stringify(payload) })
}

export async function disbandCompany() {
  return request('/api/company', { method: 'DELETE' })
}

export async function leaveCompany() {
  return request('/api/company/leave', { method: 'POST' })
}

export async function updateMemberSalary(memberUserId, salary) {
  return request(`/api/company/members/${encodeURIComponent(memberUserId)}`, {
    method: 'PATCH', body: JSON.stringify({ salary }),
  })
}

export async function updateOwnerSalary(salary) {
  return request('/api/company/owner-salary', {
    method: 'PATCH', body: JSON.stringify({ salary }),
  })
}

export async function fireMember(memberUserId) {
  return request(`/api/company/members/${encodeURIComponent(memberUserId)}`, { method: 'DELETE' })
}

export async function inviteEmployee({ username, role, salary }) {
  return request('/api/company/invite', { method: 'POST', body: JSON.stringify({ username, role, salary }) })
}

export async function fetchMyInvites() {
  return request('/api/company/invites')
}

export async function acceptInvite(inviteId) {
  return request(`/api/company/invites/${encodeURIComponent(inviteId)}/accept`, { method: 'POST' })
}

export async function declineInvite(inviteId) {
  return request(`/api/company/invites/${encodeURIComponent(inviteId)}/decline`, { method: 'POST' })
}

export async function fetchMyJobs() {
  return request('/api/company/my-jobs')
}

export async function fetchCompanies(search) {
  const q = search ? `?search=${encodeURIComponent(search)}` : ''
  return request(`/api/company/list${q}`)
}

export async function applyToCompany(companyId) {
  return request(`/api/company/apply/${encodeURIComponent(companyId)}`, { method: 'POST' })
}

export async function acceptApplication(appId) {
  return request(`/api/company/applications/${encodeURIComponent(appId)}/accept`, { method: 'POST' })
}

export async function declineApplication(appId) {
  return request(`/api/company/applications/${encodeURIComponent(appId)}/decline`, { method: 'POST' })
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

export async function companyIpo({ symbol, totalShares }) {
  return request('/api/company/ipo', {
    method: 'POST', body: JSON.stringify({ symbol, totalShares }),
  })
}

export async function companyDividend(perShare) {
  return request('/api/company/dividend', {
    method: 'POST', body: JSON.stringify({ perShare }),
  })
}

// ── Media / СМИ (разоблачения) ─────────────────────────────────────────────────

export async function fetchMediaStatus() {
  return request('/api/media/status')
}

export async function fetchMediaTargets() {
  return request('/api/media/targets')
}

export async function fetchMediaFeed() {
  return request('/api/media/feed')
}

export async function orderExpose({ targetType, targetId, budget }) {
  return request('/api/media/expose', {
    method: 'POST', body: JSON.stringify({ targetType, targetId, budget }),
  })
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

export async function fetchCityBonuses() {
  return request('/api/cityroof/bonuses')
}

export async function fetchMyStudios() {
  return request('/api/cityroof/itstudio/mystudios')
}

export async function buyStudioMaterials(assetId, qty) {
  return request('/api/cityroof/itstudio/materials/buy', { method: 'POST', body: JSON.stringify({ assetId, qty }) })
}

export async function orderStudioJob(assetId, businessId, type) {
  return request('/api/cityroof/itstudio/order', { method: 'POST', body: JSON.stringify({ assetId, businessId, type }) })
}

export async function fetchItStudioJobs() {
  return request('/api/cityroof/itstudio/jobs')
}

// ── Hardware shop ───────────────────────────────────────────────────────────────

export async function fetchShopCatalog(category) {
  const q = category ? `?category=${encodeURIComponent(category)}` : ''
  return request(`/api/shop/catalog${q}`)
}

export async function buyHardware(itemId, quantity = 1) {
  return request('/api/shop/buy', { method: 'POST', body: JSON.stringify({ itemId, quantity }) })
}

export async function fetchInventory() {
  return request('/api/shop/inventory')
}

// ── Mining farms ────────────────────────────────────────────────────────────────

export async function fetchFarms() { return request('/api/mining/farms') }
export async function fetchMiningMarket() { return request('/api/mining/market') }
export async function fetchMiningParts() { return request('/api/mining/parts') }
export async function createFarm(name) { return request('/api/mining/farms', { method: 'POST', body: JSON.stringify({ name }) }) }
export async function deleteFarm(id) { return request(`/api/mining/farms/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
export async function installComponent(id, category, hwId) { return request(`/api/mining/farms/${encodeURIComponent(id)}/install`, { method: 'POST', body: JSON.stringify({ category, hwId }) }) }
export async function uninstallComponent(id, hwId) { return request(`/api/mining/farms/${encodeURIComponent(id)}/uninstall`, { method: 'POST', body: JSON.stringify({ hwId }) }) }
export async function startMining(id) { return request(`/api/mining/farms/${encodeURIComponent(id)}/start`, { method: 'POST' }) }
export async function stopMining(id) { return request(`/api/mining/farms/${encodeURIComponent(id)}/stop`, { method: 'POST' }) }
export async function setFarmCoin(id, symbol) { return request(`/api/mining/farms/${encodeURIComponent(id)}/coin`, { method: 'POST', body: JSON.stringify({ symbol }) }) }
export async function setOverclock(id, value) { return request(`/api/mining/farms/${encodeURIComponent(id)}/overclock`, { method: 'POST', body: JSON.stringify({ value }) }) }
export async function repairFarm(id) { return request(`/api/mining/farms/${encodeURIComponent(id)}/repair`, { method: 'POST' }) }
export async function farmManager(id, action) { return request(`/api/mining/farms/${encodeURIComponent(id)}/manager`, { method: 'POST', body: JSON.stringify({ action }) }) }

export {
  API_BASE_URL,
  ApiError,
  request,
  forceLogout,
  logoutUser,
  saveTokens,
  getRefreshToken,
  startTokenRefresh,
  stopTokenRefresh,
}
