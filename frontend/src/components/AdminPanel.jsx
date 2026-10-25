import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchStocks, fetchStocksV2, fetchConfig, request, adminUpdateUser, adminDeleteUser, updateStockConfig,
  adminListCollections, adminListDocuments, adminCreateDocument, adminUpdateDocument, adminDeleteDocument,
  adminListTransactions, adminTxFilterOptions,
  fetchCryptoMarket, adminUpdateCoin, adminCreateCoin, adminDeleteCoin,
  fetchAdminPermissions, updateAdminPermissions, adminUpdateUserBans,
  adminSetUserPassword, adminLogoutUser, adminLoginAs, adminGetIpGroups, adminGetAuditLog, adminListLots, adminCancelLot, adminBroadcast,
  fetchSyntheticConfig, saveSyntheticConfig, triggerSynthetic, fetchSyntheticOrders,
} from '../services/api'
import TxFilters, { TX_FIELDS } from './TxFilters'
import { formatCompact } from './TransactionsPanel'
import { useApiOnMount } from '../hooks/useApi'
import EconomyAdmin from './EconomyAdmin'
import UserPropertyModal from './UserPropertyModal'
import PriceHistoryEditor from './PriceHistoryEditor'
import {
  Plus, Trash2, Edit3, Save, X, Settings, Users, ArrowLeftRight,
  Package, ChevronDown, ChevronUp, ShieldAlert, Sliders, HelpCircle, Activity, Search, DollarSign, RefreshCw, Briefcase, EyeOff,
  Database, Coins, ChevronLeft, ChevronRight, Bot, KeyRound, LogOut, LogIn, Gavel, Megaphone,
} from 'lucide-react'
import PriceEditorTab from './PriceEditorTab'
import { toast } from './Toast'

function Tooltip({ text }) {
  const [show, setShow] = useState(false)
  return (
    <span
      className="tooltip-wrapper"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <HelpCircle size={14} className="tooltip-icon" />
      {show && <span className="tooltip-text">{text}</span>}
    </span>
  )
}

function TriStateCheckbox({ checked, indeterminate, onChange }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate }, [indeterminate])
  return <input ref={ref} type="checkbox" checked={checked} onChange={onChange} />
}

function BanDetails({ ban = {}, onChange, t }) {
  return (
    <span className="admin-ban-details">
      <input type="date" className="admin-input admin-ban-until" value={ban.until || ''}
        title={t('admin.banUntil')} onChange={e => onChange({ until: e.target.value })} />
      <input type="text" className="admin-input admin-ban-reason" placeholder={t('admin.banReason')}
        value={ban.reason || ''} onChange={e => onChange({ reason: e.target.value })} />
    </span>
  )
}

const CARD_NUMBER_RE = /^\d{4}-\d{4}-\d{4}-\d{5}$/

const fmtTs = (ts) => {
  if (!ts || typeof ts !== 'string') return '—'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  const p = n => String(n).padStart(2, '0')
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${String(d.getFullYear()).slice(2)} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// refs: карта id-строка -> человекочитаемое имя (юзернейм/название бизнеса).
function DbDocPreview({ doc, refs = {} }) {
  const entries = Object.entries(doc).filter(([k]) => k !== '_id')
  return (
    <div className="db-doc-preview">
      {entries.map(([k, v], i) => {
        const idStr = typeof v === 'string' ? v : v && v.$oid
        const name = idStr && refs[idStr]
        let cls = 'dbv-other', text
        if (name != null) { cls = 'dbv-ref'; text = `${name}` }
        else if (v === null) { cls = 'dbv-null'; text = 'null' }
        else if (typeof v === 'boolean') { cls = 'dbv-bool'; text = String(v) }
        else if (typeof v === 'number') { cls = 'dbv-num'; text = String(v) }
        else if (typeof v === 'string') { cls = 'dbv-str'; text = `"${v}"` }
        else if (v && v.$oid) { cls = 'dbv-id'; text = v.$oid }
        else if (v && v.$date) { cls = 'dbv-date'; text = typeof v.$date === 'string' ? v.$date : JSON.stringify(v.$date) }
        else { text = JSON.stringify(v) }
        return (
          <span key={k} className="db-field">
            <span className="db-key">{k}:</span>
            <span className={cls}>{text}</span>
            {i < entries.length - 1 && <span className="db-sep">,</span>}
          </span>
        )
      })}
    </div>
  )
}
const DB_PAGE_SIZE = 50
const TX_PAGE_SIZE = 50
const TX_PRESETS_KEY = 'tradeverse_admin_tx_presets'

// Сортировки клиентские — список юзеров и так полный.
const USER_SORTS = [
  { key: 'created_at', defOrder: -1 },
  { key: 'username', defOrder: 1 },
  { key: 'balance', defOrder: -1 },
  { key: 'netWorth', defOrder: -1 },
]
const USER_MONEY_CHIPS = [
  { key: 'balance', col: 'cash' },
  { key: 'stocks', col: 'stocks' },
  { key: 'crypto', col: 'crypto' },
  { key: 'assets', col: 'assets' },
  { key: 'company', col: 'company' },
]
// Игровые функции, отключаемые игроку (зеркало PLAYER_FUNCTIONS бэкенда).
const PLAYER_BAN_FUNCS = [
  'transfer', 'crypto', 'crypto_account', 'crypto_trade', 'crypto_transfer',
  'stocks', 'stocks_trade', 'shop', 'shop_buy', 'shop_sell',
  'assets', 'assets_buy', 'assets_upgrade', 'assets_sell', 'assets_rent',
  'centralmarket', 'centralmarket_create', 'centralmarket_buy',
  'mining', 'mining_create', 'mining_hardware', 'mining_operation', 'mining_maintenance', 'mining_ai',
  'farm_sources', 'farm_sources_cells', 'farm_sources_plant', 'farm_sources_harvest', 'farm_sources_fuel', 'farm_sources_sell', 'farm_sources_vehicle',
  'company', 'company_edit', 'company_members', 'company_leave',
  'cityroof', 'cityroof_purchase', 'cityroof_attack', 'cityroof_capture', 'cityroof_protect',
]
const BAN_GROUPS = [
  { id: 'transfer', actions: [] },
  { id: 'crypto', actions: ['crypto_account', 'crypto_trade', 'crypto_transfer'] },
  { id: 'stocks', actions: ['stocks_trade'] },
  { id: 'shop', actions: ['shop_buy', 'shop_sell'] },
  { id: 'assets', actions: ['assets_buy', 'assets_upgrade', 'assets_sell', 'assets_rent'] },
  { id: 'centralmarket', actions: ['centralmarket_create', 'centralmarket_buy'] },
  { id: 'mining', actions: ['mining_create', 'mining_hardware', 'mining_operation', 'mining_maintenance', 'mining_ai'] },
  { id: 'farm_sources', actions: ['farm_sources_cells', 'farm_sources_plant', 'farm_sources_harvest', 'farm_sources_fuel', 'farm_sources_sell', 'farm_sources_vehicle'] },
  { id: 'company', actions: ['company_edit', 'company_members', 'company_leave'] },
  { id: 'cityroof', actions: ['cityroof_purchase', 'cityroof_attack', 'cityroof_capture', 'cityroof_protect'] },
]
const ADMIN_LEVELS = [1, 2, 3, 4]
// Поля конфига ботов по рынкам (зеркало DEFAULT_SYNTHETIC бэкенда).
const SYNTH_FIELDS = {
  stocks: ['probability', 'minShares', 'maxShares', 'roundsPerTick', 'buyBiasMin', 'buyBiasMax'],
  crypto: ['probability', 'minVolumeUsd', 'maxVolumeUsd', 'roundsPerTick', 'buyBiasMin', 'buyBiasMax'],
}


function AdminPanel({ user, onClose }) {
  const { t } = useTranslation()

  // Разрешения текущего админа (из get_me → user.adminFunctions). Пока данных
  // нет (старый localStorage) — не режем UI, бэкенд всё равно проверит.
  const can = (func) => !func || !user?.adminFunctions || user.adminFunctions.includes(func)
  const canEditAdmins = (user?.adminLevel || 0) >= 4

  if (user?.role !== 'admin') {
    return (
      <div className="admin-panel">
        <div className="admin-header">
          <h2>{t('admin.title')}</h2>
          <button className="admin-close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        <div className="admin-access-denied">
          <ShieldAlert size={48} />
          <h3>{t('admin.accessDenied')}</h3>
          <p>{t('admin.accessDeniedDesc')}</p>
        </div>
      </div>
    )
  }
  const [activeSection, setActiveSection] = useState(() => localStorage.getItem('tradeverse_admin_section') || 'users')
  const [stocks, setStocks] = useState([])
  const [stocksV2, setStocksV2] = useState([])
  const [users, setUsers] = useState([])
  const [transactions, setTransactions] = useState({ items: [], has_more: false })
  const [txFilters, setTxFilters] = useState({ include: {}, exclude: {}, ranges: {} })
  const [txOptions, setTxOptions] = useState({ players: [], categories: [], sources: ['user'] })
  const [openTxMenu, setOpenTxMenu] = useState(null) // key открытого дропдауна фильтра
  const [txSearch, setTxSearch] = useState('')       // дебаунсенное значение, уходит на сервер
  const [txSearchInput, setTxSearchInput] = useState('') // сырой ввод
  const [txSort, setTxSort] = useState('timestamp')
  const [txOrder, setTxOrder] = useState(-1) // 1 asc / -1 desc
  const [txPage, setTxPage] = useState(0)    // 0-based
  const [txNonce, setTxNonce] = useState(0)  // ручное обновление (кнопка/удаление)
  const [txPresets, setTxPresets] = useState(() => {
    try { return JSON.parse(localStorage.getItem(TX_PRESETS_KEY) || '{}') } catch { return {} }
  })
  const [txPresetSel, setTxPresetSel] = useState('')
  const [configItems, setConfigItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [editingStock, setEditingStock] = useState(null)
  const [editingStockConfig, setEditingStockConfig] = useState(null)
  const [configForm, setConfigForm] = useState({
    volatility_k: '',
    total_shares: '',
    price_drop_threshold: '',
    price_rise_threshold: '',
    max_order_size_percent: '',
  })
  const [newStock, setNewStock] = useState({ symbol: '', name: '', price: '', change: '0', changePercent: '0' })
  const [showAddForm, setShowAddForm] = useState(false)
  const [newConfig, setNewConfig] = useState({ key: '', value: '' })

  const [editingUser, setEditingUser] = useState(null)
  const [userSearch, setUserSearch] = useState('')
  const [userSort, setUserSort] = useState('created_at')
  const [userOrder, setUserOrder] = useState(-1)
  const [stockSearch, setStockSearch] = useState('')
  const [editForm, setEditForm] = useState({
    username: '',
    balance: '',
    role: 'user',
    card_number: '',
    hidden_from_leaderboard: false,
    leaderboard_lock: false,
  })
  const [editErrors, setEditErrors] = useState({})
  const [originalEditForm, setOriginalEditForm] = useState(null)
  const [originalBanDraft, setOriginalBanDraft] = useState(null)
  const [ipGroups, setIpGroups] = useState(null)
  const [auditLogs, setAuditLogs] = useState([])
  const [newPassword, setNewPassword] = useState('')
  const [pwdBusy, setPwdBusy] = useState(false)
  const [propertyUser, setPropertyUser] = useState(null)
  const [lots, setLots] = useState([])
  const [lotsStatus, setLotsStatus] = useState('active')
  const [bcForm, setBcForm] = useState({ title: '', message: '' })
  const [bcBusy, setBcBusy] = useState(false)
  const [perms, setPerms] = useState(null)
  const [permsSaving, setPermsSaving] = useState(false)
  const [banDraft, setBanDraft] = useState({}) // {func: {on, reason, until}}
  const [expandedBans, setExpandedBans] = useState({})
  const [bansSaving, setBansSaving] = useState(false)

  const [dbCollections, setDbCollections] = useState([])
  const [dbActiveCollection, setDbActiveCollection] = useState('')
  const [dbDocs, setDbDocs] = useState({ items: [], total: 0 })
  const [dbSearch, setDbSearch] = useState('')
  const [dbSearchInput, setDbSearchInput] = useState('') // сырой ввод; dbSearch — дебаунсенное значение
  const [dbPage, setDbPage] = useState(0)          // 0-based
  const [dbSort, setDbSort] = useState('')          // поле сортировки ('' = без сортировки)
  const [dbOrder, setDbOrder] = useState(-1)        // 1 asc / -1 desc
  const [dbEditingDoc, setDbEditingDoc] = useState(null) // { id, text } | { id: null, text } для нового документа
  const [dbJsonError, setDbJsonError] = useState(null)

  const [coins, setCoins] = useState([])
  const [coinSearch, setCoinSearch] = useState('')
  const [editingCoin, setEditingCoin] = useState(null) // символ редактируемой монеты
  const [coinForm, setCoinForm] = useState({ name: '', price: '', marketCap: '', volatility: '', color: '', description: '' })
  const [showAddCoinForm, setShowAddCoinForm] = useState(false)
  const [newCoin, setNewCoin] = useState({ symbol: '', name: '', price: '', volatility: '0.05', color: '#6366f1', supply: '', description: '' })
  const [chartAsset, setChartAsset] = useState(null) // { market, symbol } | null — открывает PriceHistoryEditor

  // Боты-маркетмейкеры: драфт — числа строками, enabled — булево.
  const [synthForm, setSynthForm] = useState(null) // { stocks: {...}, crypto: {...} }
  const [synthStats, setSynthStats] = useState(null)
  const [synthOrders, setSynthOrders] = useState([])
  const [synthManual, setSynthManual] = useState({ symbol: '', side: '', quantity: '' })
  const [synthBusy, setSynthBusy] = useState(false)

  useEffect(() => {
    loadData()
    if (activeSection === 'audit') adminGetAuditLog().then(setAuditLogs).catch(() => setAuditLogs([]))
  }, [activeSection])

  useEffect(() => {
    localStorage.setItem('tradeverse_admin_section', activeSection)
  }, [activeSection])

  useEffect(() => {
    if (activeSection === 'lots') loadData()
  }, [lotsStatus])

  // Если пришёл срез прав без текущего раздела — переключаем на первый доступный.
  useEffect(() => {
    if (user?.adminFunctions && !can(activeSection)) {
      const first = sections.filter(s => can(s.perm))[0]
      if (first) setActiveSection(first.id)
    }
  }, [user?.adminFunctions])

  useEffect(() => { setDbPage(0) }, [dbActiveCollection, dbSearch, dbSort, dbOrder])

  // Дебаунс поискового ввода — regex-поиск по 900k дорогой, не дёргаем на каждый символ.
  useEffect(() => {
    const id = setTimeout(() => setDbSearch(dbSearchInput.trim()), 400)
    return () => clearTimeout(id)
  }, [dbSearchInput])

  // Точечный поиск: "поле: значение" (напр. «Категория: cityroof», "username: admin").
  // Поле распознаём и по имени, и по локализованной подписи; иначе — свободный поиск.
  // Гибрид со справочником: "поле: v1, !v2" — значения дописываются в фильтр поля
  // (с «!» — в исключения), свободный текст остаётся свободным поиском.
  const parseTxSearch = (raw, filters) => {
    const s = raw.trim()
    const m = s.match(/^([^:]+):\s*(.*)$/)
    if (!m) return { q: s, filters }
    const key = m[1].trim().toLowerCase()
    const f = TX_FIELDS.find(x => x.key.toLowerCase() === key || t(x.i18n, x.fallback).toLowerCase() === key)
    if (!f) return { q: s, filters }
    const include = [], exclude = []
    m[2].split(',').map(v => v.trim()).filter(Boolean).forEach(v => {
      if (v.startsWith('!')) exclude.push(v.slice(1)); else include.push(v)
    })
    const next = { include: { ...filters.include }, exclude: { ...filters.exclude }, ranges: filters.ranges }
    if (include.length) next.include[f.key] = [...(next.include[f.key] || []), ...include]
    if (exclude.length) next.exclude[f.key] = [...(next.exclude[f.key] || []), ...exclude]
    return { q: '', filters: next }
  }

  const toggleTxValue = (field, value, mode) => setTxFilters(f => {
    const cur = f[mode][field] || []
    const next = cur.includes(value) ? cur.filter(v => v !== value) : [...cur, value]
    const side = { ...f[mode] }
    if (next.length) side[field] = next
    else delete side[field]
    const other = mode === 'include' ? 'exclude' : 'include'
    const otherSide = { ...f[other] }
    if (otherSide[field]) otherSide[field] = otherSide[field].filter(v => v !== value)
    return { ...f, [mode]: side, [other]: otherSide }
  })

  const setTxMode = (field, mode) => setTxFilters(f => {
    const other = mode === 'include' ? 'exclude' : 'include'
    const vals = f[other][field] || []
    const src = { ...f[other] }
    delete src[field]
    const dst = { ...f[mode], [field]: vals }
    return { ...f, [other]: src, [mode]: dst }
  })

  const setTxRange = (field, side, value) => setTxFilters(f => {
    const r = { ...(f.ranges[field] || {}), [side]: value }
    const ranges = { ...f.ranges, [field]: r }
    if (!Object.values(r).some(v => v !== '' && v != null)) delete ranges[field]
    return { ...f, ranges }
  })

  const saveTxPreset = () => {
    const name = prompt(t('admin.txPresets.namePrompt'))?.trim()
    if (!name) return
    const next = { ...txPresets, [name]: { filters: txFilters, sort: txSort, order: txOrder } }
    setTxPresets(next)
    setTxPresetSel(name)
    localStorage.setItem(TX_PRESETS_KEY, JSON.stringify(next))
    toast(t('admin.txPresets.saved'))
  }

  const applyTxPreset = (name) => {
    setTxPresetSel(name)
    const p = txPresets[name]
    if (!p) return
    setTxFilters(p.filters)
    setTxSort(p.sort || 'timestamp')
    setTxOrder(p.order ?? -1)
  }

  const deleteTxPreset = () => {
    if (!txPresetSel) return
    if (!confirm(t('admin.txPresets.deleteConfirm', { name: txPresetSel }))) return
    const next = { ...txPresets }
    delete next[txPresetSel]
    setTxPresets(next)
    setTxPresetSel('')
    localStorage.setItem(TX_PRESETS_KEY, JSON.stringify(next))
  }

  useEffect(() => { setTxPage(0) }, [txFilters, txSearch, txSort, txOrder])

  // Дебаунс: regex-поиск идёт по 180k записям, не дёргаем сервер на каждый символ.
  useEffect(() => {
    const id = setTimeout(() => setTxSearch(txSearchInput.trim()), 400)
    return () => clearTimeout(id)
  }, [txSearchInput])

  useEffect(() => {
    if (activeSection !== 'transactions') return
    const { q, field, filters } = parseTxSearch(txSearch, txFilters)
    adminListTransactions({
      q: q || undefined, field, filters,
      skip: txPage * TX_PAGE_SIZE, limit: TX_PAGE_SIZE,
      sort: txSort, order: txOrder,
    })
      .then(setTransactions)
      .catch(err => toast(t('admin.loadError') + ': ' + err.message, 'error'))
  }, [activeSection, txFilters, txSearch, txSort, txOrder, txPage, txNonce])

  useEffect(() => {
    if (activeSection !== 'database' || !dbActiveCollection) return
    adminListDocuments(dbActiveCollection, {
      q: dbSearch || undefined,
      skip: dbPage * DB_PAGE_SIZE,
      limit: DB_PAGE_SIZE,
      sort: dbSort || undefined,
      order: dbOrder,
    })
      .then(setDbDocs)
      .catch(err => toast(t('admin.error') + ': ' + err.message, 'error'))
  }, [dbActiveCollection, dbSearch, dbPage, dbSort, dbOrder])

  // Живое обновление списка пользователей (только для админов — см. push_to_admins
  // в backend/ws.py). Транзакции намеренно НЕ обновляются пушем — по решению
  // пользователя они обновляются только вручную кнопкой (см. handleRefreshTransactions).
  useEffect(() => {
    const onRealtime = (ev) => {
      const d = ev.detail
      if (d?.type === 'admin_user_modified' || d?.type === 'admin_user_deleted') {
        if (activeSection === 'users') loadData()
      }
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [activeSection])

  const loadData = async () => {
    setLoading(true)
    try {
      if (activeSection === 'stocks') {
        const data = await fetchStocks()
        setStocks(data)
      } else if (activeSection === 'stockConfig') {
        const data = await fetchStocksV2()
        setStocksV2(data)
      } else if (activeSection === 'users') {
        const data = await request('/api/admin/users')
        setUsers(data)
      } else if (activeSection === 'lots') {
        const data = await adminListLots(lotsStatus)
        setLots(data.lots || [])
      } else if (activeSection === 'perms') {
        const data = await fetchAdminPermissions()
        setPerms(data)
      } else if (activeSection === 'transactions') {
        // Транзакции грузит отдельный effect; здесь — справочник значений фильтров.
        adminTxFilterOptions().then(setTxOptions).catch(() => {})
      } else if (activeSection === 'database') {
        if (dbCollections.length === 0) {
          const cols = await adminListCollections()
          setDbCollections(cols)
          if (!dbActiveCollection && cols.length) setDbActiveCollection(cols[0])
        }
        // Документы грузит отдельный effect (по dbActiveCollection/page/sort/search).
      } else if (activeSection === 'crypto') {
        const data = await fetchCryptoMarket()
        // Прячем API-монеты (COINGECKO-монеты перезатираются рефрешем,
        // ботам там делать нечего — цены с реального рынка).
        setCoins(data.filter(c => c.source !== 'coingecko'))
      } else if (activeSection === 'synthetic') {
        const [cfg, orders] = await Promise.all([
          fetchSyntheticConfig(),
          fetchSyntheticOrders(50).catch(() => []),
        ])
        setSynthForm({
          stocks: Object.fromEntries(Object.entries(cfg.stocks).map(([k, v]) => [k, typeof v === 'boolean' ? v : String(v)])),
          crypto: Object.fromEntries(Object.entries(cfg.crypto).map(([k, v]) => [k, typeof v === 'boolean' ? v : String(v)])),
        })
        setSynthStats(cfg.stats || null)
        setSynthOrders(orders)
      } else if (activeSection === 'config') {
        const keys = ['sidebar_menu', 'header_title', 'app_version']
        const items = []
        for (const key of keys) {
          try {
            const cfg = await fetchConfig(key)
            items.push(cfg)
          } catch {
            items.push({ key, value: '-' })
          }
        }
        setConfigItems(items)
      }
    } catch (err) {
      toast(t('admin.loadError') + ': ' + err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  const validateEditForm = () => {
    const errors = {}

    if (!editForm.username || editForm.username.trim().length < 3) {
      errors.username = t('admin.validationUsernameMin')
    }

    const balance = parseFloat(editForm.balance)
    if (isNaN(balance) || balance < 0) {
      errors.balance = t('admin.validationBalanceNegative')
    }

    if (editForm.role !== 'user' && editForm.role !== 'admin') {
      errors.role = t('admin.validationRoleInvalid')
    }

    if (editForm.card_number && !CARD_NUMBER_RE.test(editForm.card_number)) {
      errors.card_number = t('admin.validationCardFormat')
    }

    setEditErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleStartEditUser = (u) => {
    setEditingUser(u.id)
    const form = {
      username: u.username || '',
      balance: u.balance != null ? String(u.balance) : '',
      role: u.role || 'user',
      admin_level: u.admin_level || 4,
      card_number: u.card_number || '',
      hidden_from_leaderboard: !!u.hidden_from_leaderboard,
      leaderboard_lock: !!u.leaderboard_lock,
    }
    setEditForm(form)
    setOriginalEditForm(form)
    const draftBans = Object.fromEntries(
      Object.entries(u.bans || {}).map(([k, v]) => [k, { on: true, reason: v.reason || '', until: (v.until || '').slice(0, 10) }]),
    )
    setBanDraft(draftBans)
    setOriginalBanDraft(draftBans)
    setEditErrors({})
  }

  const handleResetPassword = async () => {
    if (newPassword.length < 6) return
    setPwdBusy(true)
    try {
      await adminSetUserPassword(editingUser, newPassword)
      setNewPassword('')
      toast(t('admin.passwordResetDone'))
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    } finally {
      setPwdBusy(false)
    }
  }

  const handleLogoutUser = async () => {
    setPwdBusy(true)
    try {
      const res = await adminLogoutUser(editingUser)
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    } finally {
      setPwdBusy(false)
    }
  }

  const handleResetAvatar = async () => {
    if (!confirm(t('admin.avatarResetConfirm'))) return
    try {
      await adminUpdateUser(editingUser, { avatar: null })
      toast(t('admin.avatarResetDone'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleCancelLot = async (lot) => {
    if (!confirm(t('admin.lots.cancelConfirm', { name: lot.name }))) return
    try {
      await adminCancelLot(lot.id)
      toast(t('admin.lots.cancelled'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleBroadcast = async () => {
    if (!bcForm.title.trim()) return
    setBcBusy(true)
    try {
      const res = await adminBroadcast(bcForm.title.trim(), bcForm.message.trim())
      toast(t('admin.broadcast.sent', { count: res.sent }))
      setBcForm({ title: '', message: '' })
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    } finally {
      setBcBusy(false)
    }
  }

  const handleCancelEditUser = () => {
    setEditingUser(null)
    setNewPassword('')
    setEditForm({
      username: '',
      balance: '',
      role: 'user',
      admin_level: 4,
      card_number: '',
      hidden_from_leaderboard: false,
      leaderboard_lock: false,
    })
    setBanDraft({})
    setEditErrors({})
  }

  const handleSaveUser = async () => {
    if (!validateEditForm() || !originalEditForm) return
    const payload = {}
    const normalized = { ...editForm, username: editForm.username.trim(), balance: parseFloat(editForm.balance), card_number: editForm.card_number.trim() }
    for (const key of Object.keys(normalized)) {
      if (normalized[key] !== originalEditForm[key]) payload[key] = normalized[key]
    }
    if (normalized.role !== 'admin') delete payload.admin_level
    const bans = {}
    for (const f of ['account', ...PLAYER_BAN_FUNCS]) {
      const d = banDraft[f]
      if (d?.on) bans[f] = { reason: d.reason?.trim() || null, until: d.until ? `${d.until}T23:59:59` : null }
    }
    const initialBans = {}
    for (const f of ['account', ...PLAYER_BAN_FUNCS]) {
      const d = originalBanDraft?.[f]
      if (d?.on) initialBans[f] = { reason: d.reason?.trim() || null, until: d.until ? `${d.until}T23:59:59` : null }
    }
    try {
      const requests = []
      if (Object.keys(payload).length) requests.push(adminUpdateUser(editingUser, payload))
      if (JSON.stringify(bans) !== JSON.stringify(initialBans)) requests.push(adminUpdateUserBans(editingUser, bans))
      if (newPassword.length >= 6 && can('users_password')) requests.push(adminSetUserPassword(editingUser, newPassword))
      await Promise.all(requests)
      setNewPassword('')
      setEditingUser(null)
      toast(t('admin.userUpdated'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleLoginAs = async (userId) => {
    try {
      const returnToken = localStorage.getItem('token') || ''
      const returnRefresh = localStorage.getItem('refresh_token') || ''
      const pair = await adminLoginAs(userId)
      localStorage.setItem('admin_return_token', returnToken)
      localStorage.setItem('admin_return_refresh_token', returnRefresh)
      localStorage.setItem('admin_return_user', localStorage.getItem('tradeverse_user') || '')
      const target = await request('/api/user/me')
      localStorage.setItem('tradeverse_user', JSON.stringify({ ...target, token: pair.token, refresh_token: pair.refresh_token }))
      window.location.reload()
    } catch (err) { toast(t('admin.error') + ': ' + err.message, 'error') }
  }

  const handleLoadIpGroups = async () => {
    try { setIpGroups(await adminGetIpGroups()) } catch (err) { toast(t('admin.error') + ': ' + err.message, 'error') }
  }

  const toggleBanKeys = (keys, on) => setBanDraft(prev => {
    const next = { ...prev }
    keys.forEach(key => { next[key] = { ...(next[key] || {}), on } })
    return next
  })

  const handleDeleteUser = async (userId, username) => {
    if (!confirm(t('admin.deleteUserConfirm', { username }))) return
    try {
      await adminDeleteUser(userId)
      toast(t('admin.userDeleted', { username }))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  // Сохранение банов: полный срез — не отмеченные функции = бан снят.
  const handleSaveBans = async () => {
    if (!editingUser) return
    setBansSaving(true)
    try {
      const bans = {}
      for (const f of ['account', ...PLAYER_BAN_FUNCS]) {
        if (banDraft[f]?.on) {
          bans[f] = { reason: banDraft[f].reason || null, until: banDraft[f].until ? `${banDraft[f].until}T23:59:59` : null }
        }
      }
      await adminUpdateUserBans(editingUser, bans)
      toast(t('admin.banSaved'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleSavePerms = async () => {
    setPermsSaving(true)
    try {
      const levels = {}
      perms.functions.forEach(f => { levels[f.id] = f.level })
      await updateAdminPermissions(levels)
      toast(t('adminPerms.saved'))
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    } finally {
      setPermsSaving(false)
    }
  }

  const handleAddStock = async () => {
    if (!newStock.symbol || !newStock.name || !newStock.price) {
      toast(t('admin.fillAllFields'), 'error')
      return
    }
    try {
      await request('/api/stocks', {
        method: 'POST',
        body: JSON.stringify({
          symbol: newStock.symbol.toUpperCase(),
          name: newStock.name,
          price: parseFloat(newStock.price),
          change: parseFloat(newStock.change) || 0,
          changePercent: parseFloat(newStock.changePercent) || 0,
        }),
      })
      setNewStock({ symbol: '', name: '', price: '', change: '0', changePercent: '0' })
      toast(t('admin.stockAdded'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleUpdateStock = async (stock) => {
    try {
      await request('/api/stocks', {
        method: 'POST',
        body: JSON.stringify({
          symbol: stock.symbol,
          name: stock.name,
          price: parseFloat(stock.price),
          change: parseFloat(stock.change) || 0,
          changePercent: parseFloat(stock.changePercent) || 0,
        }),
      })
      setEditingStock(null)
      toast(t('admin.stockUpdated'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleDeleteStock = async (symbol) => {
    if (!confirm(t('admin.deleteStockConfirm', { symbol }))) return
    try {
      await request(`/api/stocks/${symbol}`, { method: 'DELETE' })
      toast(t('admin.stockDeleted', { symbol }))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleDeleteTransaction = async (txId) => {
    if (!confirm(t('admin.deleteTransactionConfirm'))) return
    try {
      await request(`/api/admin/transactions/${txId}`, { method: 'DELETE' })
      toast(t('admin.transactionDeleted'))
      setTxNonce(n => n + 1)
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleSaveConfig = async () => {
    if (!newConfig.key || !newConfig.value) {
      toast(t('admin.fillKeyAndValue'), 'error')
      return
    }
    try {
      await request('/api/config', {
        method: 'POST',
        body: JSON.stringify({ key: newConfig.key, value: newConfig.value }),
      })
      setNewConfig({ key: '', value: '' })
      toast(t('admin.configUpdated'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleEditStockConfig = (stock) => {
    setEditingStockConfig(stock.symbol)
    const overrides = stock.configOverrides || {}
    setConfigForm({
      volatility_k: overrides.volatility_k != null ? String(overrides.volatility_k) : '',
      total_shares: overrides.total_shares != null ? String(overrides.total_shares) : '',
      price_drop_threshold: overrides.price_drop_threshold != null ? String(overrides.price_drop_threshold) : '',
      price_rise_threshold: overrides.price_rise_threshold != null ? String(overrides.price_rise_threshold) : '',
      max_order_size_percent: overrides.max_order_size_percent != null ? String(overrides.max_order_size_percent) : '',
    })
  }

  const handleSaveStockConfig = async () => {
    const payload = {}
    if (configForm.volatility_k !== '') payload.volatility_k = parseFloat(configForm.volatility_k)
    if (configForm.total_shares !== '') payload.total_shares = parseInt(configForm.total_shares)
    if (configForm.price_drop_threshold !== '') payload.price_drop_threshold = parseFloat(configForm.price_drop_threshold)
    if (configForm.price_rise_threshold !== '') payload.price_rise_threshold = parseFloat(configForm.price_rise_threshold)
    if (configForm.max_order_size_percent !== '') payload.max_order_size_percent = parseFloat(configForm.max_order_size_percent)

    try {
      await updateStockConfig(editingStockConfig, payload)
      setEditingStockConfig(null)
      toast(t('admin.configUpdated'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleDbOpenNew = () => {
    setDbJsonError(null)
    setDbEditingDoc({ id: null, text: '{\n  \n}' })
  }

  const handleDbOpenEdit = (doc) => {
    setDbJsonError(null)
    const id = doc._id?.$oid || doc._id
    setDbEditingDoc({ id, text: JSON.stringify(doc, null, 2) })
  }

  const reloadDbDocs = async () => {
    const data = await adminListDocuments(dbActiveCollection, {
      q: dbSearch || undefined,
      skip: dbPage * DB_PAGE_SIZE,
      limit: DB_PAGE_SIZE,
      sort: dbSort || undefined,
      order: dbOrder,
    })
    setDbDocs(data)
  }

  const handleDbSave = async () => {
    let parsed
    try {
      parsed = JSON.parse(dbEditingDoc.text)
    } catch (err) {
      setDbJsonError(t('admin.database.invalidJson') + ': ' + err.message)
      return
    }
    try {
      if (dbEditingDoc.id) {
        await adminUpdateDocument(dbActiveCollection, dbEditingDoc.id, parsed)
      } else {
        await adminCreateDocument(dbActiveCollection, parsed)
      }
      setDbEditingDoc(null)
      toast(t('admin.database.saved'))
      await reloadDbDocs()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleDbDelete = async (doc) => {
    const id = doc._id?.$oid || doc._id
    if (!confirm(t('admin.database.deleteConfirm'))) return
    try {
      await adminDeleteDocument(dbActiveCollection, id)
      toast(t('admin.database.deleted'))
      await reloadDbDocs()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleStartEditCoin = (coin) => {
    setEditingCoin(coin.symbol)
    setCoinForm({
      name: coin.name || '',
      price: coin.price != null ? String(coin.price) : '',
      marketCap: coin.marketCap != null ? String(coin.marketCap) : '',
      volatility: coin.volatility != null ? String(coin.volatility) : '',
      color: coin.color || '',
      description: coin.description || '',
    })
  }

  const handleSaveCoin = async () => {
    const payload = {}
    if (coinForm.name) payload.name = coinForm.name
    if (coinForm.price !== '') payload.price = parseFloat(coinForm.price)
    if (coinForm.marketCap !== '') payload.marketCap = parseFloat(coinForm.marketCap)
    if (coinForm.volatility !== '') payload.volatility = parseFloat(coinForm.volatility)
    if (coinForm.color) payload.color = coinForm.color
    if (coinForm.description !== '') payload.description = coinForm.description
    try {
      await adminUpdateCoin(editingCoin, payload)
      setEditingCoin(null)
      toast(t('admin.crypto.saved'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleAddCoin = async () => {
    if (!newCoin.symbol || !newCoin.name || !newCoin.price) {
      toast(t('admin.fillAllFields'), 'error')
      return
    }
    try {
      await adminCreateCoin({
        symbol: newCoin.symbol.toUpperCase(),
        name: newCoin.name,
        price: parseFloat(newCoin.price),
        volatility: parseFloat(newCoin.volatility) || 0.05,
        color: newCoin.color || '#6366f1',
        supply: newCoin.supply !== '' ? parseFloat(newCoin.supply) : undefined,
        description: newCoin.description,
      })
      setNewCoin({ symbol: '', name: '', price: '', volatility: '0.05', color: '#6366f1', supply: '', description: '' })
      setShowAddCoinForm(false)
      toast(t('admin.crypto.added'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleDeleteCoin = async (symbol) => {
    if (!confirm(t('admin.crypto.deleteConfirm', { symbol }))) return
    try {
      await adminDeleteCoin(symbol)
      toast(t('admin.crypto.deleted', { symbol }))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

  const handleSaveSynthetic = async () => {
    setSynthBusy(true)
    try {
      // Числовые поля ушли в драфт строками — конвертируем обратно.
      const payload = { stocks: {}, crypto: {} }
      for (const market of ['stocks', 'crypto']) {
        const src = synthForm[market] || {}
        payload[market] = {
          enabled: !!src.enabled,
          ...Object.fromEntries(SYNTH_FIELDS[market].map(k => [k, parseFloat(src[k]) || 0])),
        }
        // Целочисленные поля (для крипты min/maxShares не существует).
        for (const k of ['minShares', 'maxShares', 'roundsPerTick']) {
          if (k in payload[market]) payload[market][k] = Math.round(payload[market][k])
        }
      }
      await saveSyntheticConfig(payload)
      toast(t('admin.synthetic.saved'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    } finally {
      setSynthBusy(false)
    }
  }

  const handleTriggerSynthetic = async (manual) => {
    setSynthBusy(true)
    try {
      let body = {}
      if (manual) {
        body = {
          market: 'all',
          symbol: synthManual.symbol.trim().toUpperCase() || undefined,
          side: synthManual.side || undefined,
          quantity: synthManual.quantity !== '' ? parseFloat(synthManual.quantity) : undefined,
        }
      }
      const res = await triggerSynthetic(body)
      const ex = res.executed || {}
      toast(t('admin.synthetic.triggered', { stocks: ex.stocks ?? 0, crypto: ex.crypto ?? 0 }))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    } finally {
      setSynthBusy(false)
    }
  }

  const sections = [
    { id: 'stocks', perm: 'stocks', label: t('admin.stocks'), icon: Package },
    { id: 'crypto', perm: 'crypto', label: t('admin.crypto.title'), icon: Coins },
    { id: 'prices', perm: 'catalog_prices', label: t('admin.prices.title'), icon: DollarSign },
    { id: 'synthetic', perm: 'synthetic', label: t('admin.synthetic.title'), icon: Bot },
    { id: 'users', perm: 'users_view', label: t('admin.users'), icon: Users },
    { id: 'audit', perm: 'users_view', label: t('admin.auditLog'), icon: Activity },
    { id: 'lots', perm: 'central_market', label: t('admin.lots.title'), icon: Gavel },
    { id: 'transactions', perm: 'transactions_view', label: t('admin.transactions'), icon: ArrowLeftRight },
    { id: 'broadcast', perm: 'broadcast', label: t('admin.broadcast.title'), icon: Megaphone },
    { id: 'economy', perm: 'economy_view', label: t('econ.tab'), icon: Activity },
    { id: 'config', perm: 'config', label: t('admin.config'), icon: Settings },
    { id: 'database', perm: 'database', label: t('admin.database.title'), icon: Database },
    { id: 'perms', perm: 'admin_perms', label: t('adminPerms.title'), icon: ShieldAlert },
  ]

  return (
    <div className="admin-panel admin-panel-modern">
      <div className="admin-header">
        <h2><ShieldAlert size={20} /> {t('admin.title')}</h2>
        <button className="admin-close-btn" onClick={onClose}>
          <X size={20} />
        </button>
      </div>


      <div className="admin-body">
        <aside className="admin-sidebar">
          {sections.filter(s => can(s.perm)).map(s => (
            <button
              key={s.id}
              className={`admin-nav-item ${activeSection === s.id ? 'active' : ''}`}
              onClick={() => setActiveSection(s.id)}
            >
              <s.icon size={18} />
              <span>{s.label}</span>
            </button>
          ))}
        </aside>

        <div className={`admin-content${editingUser && activeSection === 'users' ? ' has-panel' : ''}`}>
        {loading && activeSection !== 'economy' && <div className="loading-state"><div className="spinner" /><p>{t('common.loading')}</p></div>}

        {activeSection === 'economy' && <EconomyAdmin canEditConfig={can('economy_config')} />}

        {!loading && activeSection === 'stocks' && (
          <div>
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" onClick={() => setShowAddForm(v => !v)}>
                <Plus size={16} /> {t('admin.addStock')}
              </button>
            </div>
            {showAddForm && (
              <div className="admin-add-form">
                <div className="form-row">
                  <input
                    placeholder={t('admin.tickerPlaceholder')}
                    value={newStock.symbol}
                    onChange={e => setNewStock({ ...newStock, symbol: e.target.value })}
                    className="admin-input"
                  />
                  <input
                    placeholder={t('admin.namePlaceholder')}
                    value={newStock.name}
                    onChange={e => setNewStock({ ...newStock, name: e.target.value })}
                    className="admin-input"
                  />
                  <input
                    placeholder={t('admin.pricePlaceholder')}
                    type="number"
                    value={newStock.price}
                    onChange={e => setNewStock({ ...newStock, price: e.target.value })}
                    className="admin-input"
                  />
                  <button className="admin-btn admin-btn-primary" onClick={handleAddStock}>
                    <Plus size={16} /> {t('admin.addButton')}
                  </button>
                </div>
              </div>
            )}

            <div className="admin-section-divider">
              <h3>{t('admin.stockConfig') || 'Конфигурация акций'}</h3>
              <p className="admin-section-hint">{t('admin.stockConfigHint') || 'Настройте параметры волатильности и поведения для каждой акции'}</p>
            </div>

            <div className="admin-list">
              <div className="admin-toolbar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={stockSearch} onChange={e => setStockSearch(e.target.value)} placeholder={t('admin.searchStocks')} /></div>
                <span className="admin-count">{stocks.length}</span>
              </div>
              {stocks.filter(s => !stockSearch || s.symbol.toLowerCase().includes(stockSearch.toLowerCase()) || (s.name || '').toLowerCase().includes(stockSearch.toLowerCase())).map(stock => (
                <div key={stock.id} className="admin-stock-item">
                  {editingStock?.id === stock.id ? (
                    <div className="form-row">
                      <input
                        value={editingStock.name}
                        onChange={e => setEditingStock({ ...editingStock, name: e.target.value })}
                        className="admin-input"
                      />
                      <input
                        type="number"
                        value={editingStock.price}
                        onChange={e => setEditingStock({ ...editingStock, price: e.target.value })}
                        className="admin-input"
                      />
                      <button className="admin-btn admin-btn-primary" onClick={() => handleUpdateStock(editingStock)}>
                        <Save size={14} />
                      </button>
                      <button className="admin-btn" onClick={() => setEditingStock(null)}>
                        <X size={14} />
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="stock-info">
                        <strong>{stock.symbol}</strong>
                        <span>{stock.name}</span>
                        <span className={`stock-price ${stock.changePercent > 0 ? 'up' : stock.changePercent < 0 ? 'down' : ''}`}>${stock.price?.toFixed(2)}</span>
                      </div>
                      <div className="stock-actions">
                        <button className="admin-btn" onClick={() => setEditingStock({ ...stock })}>
                          <Edit3 size={14} />
                        </button>
                        <button className="admin-btn" onClick={() => setChartAsset({ market: 'stock', symbol: stock.symbol })} title={t('admin.priceHistory.title')}>
                          <RefreshCw size={14} />
                        </button>
                        <button className="admin-btn" onClick={() => handleEditStockConfig({ ...stock })} title={t('admin.stockConfig') || 'Настроить конфиг'}>
                          <Sliders size={14} />
                        </button>
                        <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteStock(stock.symbol)}>
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {!loading && activeSection === 'prices' && (
          <PriceEditorTab />
        )}

        {!loading && activeSection === 'database' && (() => {
          const sortFields = [...new Set(dbDocs.items.flatMap(d => Object.keys(d)))]
          // total известен только без поиска; при поиске листаем по has_more.
          const knownTotal = dbDocs.total != null
          const totalPages = knownTotal ? Math.max(1, Math.ceil((dbDocs.total || 0) / DB_PAGE_SIZE)) : null
          const hasNext = knownTotal ? dbPage + 1 < totalPages : !!dbDocs.has_more
          const showPager = dbPage > 0 || hasNext
          return (
          <div>
            <div className="admin-toolbar">
              <select
                className="admin-input"
                value={dbActiveCollection}
                onChange={e => setDbActiveCollection(e.target.value)}
              >
                {dbCollections.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <div className="tx-search"><Search size={15} className="tx-search-icon" />
                <input value={dbSearchInput} onChange={e => setDbSearchInput(e.target.value)} placeholder={t('admin.database.searchPlaceholder')} /></div>
              <select className="admin-input" value={dbSort} onChange={e => setDbSort(e.target.value)}>
                <option value="">{t('admin.database.sortNone')}</option>
                {sortFields.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
              <button className="admin-btn" disabled={!dbSort} onClick={() => setDbOrder(o => -o)}
                title={dbOrder >= 0 ? t('admin.database.sortAsc') : t('admin.database.sortDesc')}>
                {dbOrder >= 0 ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
              <span className="admin-count">{knownTotal ? dbDocs.total : dbDocs.items.length}</span>
              <button className="admin-btn admin-btn-primary" onClick={handleDbOpenNew}>
                <Plus size={16} /> {t('admin.database.newDocument')}
              </button>
            </div>
            <div className="admin-list">
              {dbDocs.items.map(doc => {
                const id = doc._id?.$oid || doc._id
                return (
                  <div key={id} className="admin-stock-item">
                    <DbDocPreview doc={doc} refs={dbDocs.refs} />
                    <div className="stock-actions">
                      <button className="admin-btn" onClick={() => handleDbOpenEdit(doc)}>
                        <Edit3 size={14} />
                      </button>
                      <button className="admin-btn admin-btn-danger" onClick={() => handleDbDelete(doc)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                )
              })}
              {dbDocs.items.length === 0 && <p className="empty-state">{t('admin.database.noDocuments')}</p>}
            </div>
            {showPager && (
              <div className="admin-toolbar db-pagination">
                <button className="admin-btn" disabled={dbPage === 0} onClick={() => setDbPage(p => Math.max(0, p - 1))}>
                  <ChevronLeft size={14} />
                </button>
                <span className="admin-count">
                  {knownTotal ? t('admin.database.pageOf', { page: dbPage + 1, total: totalPages }) : dbPage + 1}
                </span>
                <button className="admin-btn" disabled={!hasNext} onClick={() => setDbPage(p => p + 1)}>
                  <ChevronRight size={14} />
                </button>
              </div>
            )}
          </div>
          )
        })()}

        {dbEditingDoc && (
          <div className="modal-overlay" onClick={() => setDbEditingDoc(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>{dbEditingDoc.id ? t('admin.database.editDocument') : t('admin.database.newDocument')}</h3>
              <textarea
                className="admin-input db-json-textarea"
                value={dbEditingDoc.text}
                onChange={e => setDbEditingDoc({ ...dbEditingDoc, text: e.target.value })}
                rows={16}
              />
              {dbJsonError && <div className="admin-field-error">{dbJsonError}</div>}
              <div className="modal-buttons">
                <button className="admin-btn admin-btn-primary" onClick={handleDbSave}>
                  <Save size={14} /> {t('admin.save')}
                </button>
                <button className="admin-btn" onClick={() => setDbEditingDoc(null)}>
                  {t('admin.cancel')}
                </button>
              </div>
            </div>
          </div>
        )}

        {!loading && activeSection === 'crypto' && (
          <div>
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" onClick={() => setShowAddCoinForm(v => !v)}>
                <Plus size={16} /> {t('admin.crypto.addCoin')}
              </button>
            </div>
            {showAddCoinForm && (
              <div className="admin-add-form">
                <div className="form-row">
                  <input placeholder={t('admin.tickerPlaceholder')} value={newCoin.symbol}
                    onChange={e => setNewCoin({ ...newCoin, symbol: e.target.value })} className="admin-input" />
                  <input placeholder={t('admin.namePlaceholder')} value={newCoin.name}
                    onChange={e => setNewCoin({ ...newCoin, name: e.target.value })} className="admin-input" />
                  <input placeholder={t('admin.pricePlaceholder')} type="number" value={newCoin.price}
                    onChange={e => setNewCoin({ ...newCoin, price: e.target.value })} className="admin-input" />
                  <input placeholder={t('admin.crypto.supplyPlaceholder')} type="number" value={newCoin.supply}
                    onChange={e => setNewCoin({ ...newCoin, supply: e.target.value })} className="admin-input" />
                  <button className="admin-btn admin-btn-primary" onClick={handleAddCoin}>
                    <Plus size={16} /> {t('admin.addButton')}
                  </button>
                </div>
              </div>
            )}
            <div className="admin-list">
              <div className="admin-toolbar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={coinSearch} onChange={e => setCoinSearch(e.target.value)} placeholder={t('admin.searchStocks')} /></div>
                <span className="admin-count">{coins.length}</span>
              </div>
              {coins.filter(c => !coinSearch || c.symbol.toLowerCase().includes(coinSearch.toLowerCase()) || (c.name || '').toLowerCase().includes(coinSearch.toLowerCase())).map(coin => (
                <div key={coin.symbol} className="admin-stock-item">
                  <div className="stock-info">
                    <strong>{coin.symbol}</strong>
                    <span>{coin.name}</span>
                    <span className="stock-price">${coin.price?.toFixed?.(coin.price < 1 ? 6 : 2)}</span>
                    <span className="admin-count">{t('admin.crypto.marketCap')}: {coin.marketCap != null ? `$${Math.round(coin.marketCap).toLocaleString()}` : '—'}</span>
                  </div>
                  <div className="stock-actions">
                    <button className="admin-btn" onClick={() => setChartAsset({ market: 'crypto', symbol: coin.symbol })} title={t('admin.priceHistory.title')}>
                      <RefreshCw size={14} />
                    </button>
                    <button className="admin-btn" onClick={() => handleStartEditCoin(coin)}>
                      <Edit3 size={14} />
                    </button>
                    <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteCoin(coin.symbol)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
              {coins.length === 0 && <p className="empty-state">{t('admin.crypto.noCoins')}</p>}
            </div>
          </div>
        )}

        {!loading && activeSection === 'synthetic' && synthForm && (() => {
          const fmtQty = (q) => {
            const n = Number(q) || 0
            return n >= 1 ? n.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
                          : n.toLocaleString('ru-RU', { maximumFractionDigits: 8 })
          }
          return (
          <div>
            <div className="admin-section-divider">
              <h3>{t('admin.synthetic.title')}</h3>
              <p className="admin-section-hint">{t('admin.synthetic.hint')}</p>
            </div>
            {['stocks', 'crypto'].map(market => (
              <div key={market} className="admin-add-form">
                <h3>{t(market === 'stocks' ? 'admin.synthetic.marketStocks' : 'admin.synthetic.marketCrypto')}</h3>
                <div className="admin-field-checkbox">
                  <label>
                    <input type="checkbox" checked={!!synthForm[market].enabled}
                      onChange={e => setSynthForm({
                        ...synthForm,
                        [market]: { ...synthForm[market], enabled: e.target.checked },
                      })} />
                    {t('admin.synthetic.enabled')}
                  </label>
                </div>
                {SYNTH_FIELDS[market].map(key => (
                  <div key={key} className="config-field">
                    <label title={key === 'probability' ? t('admin.synthetic.probabilityHelp')
                      : ['buyBiasMin', 'buyBiasMax'].includes(key) ? t('admin.synthetic.biasHelp')
                      : key === 'roundsPerTick' ? t('admin.synthetic.roundsHelp') : undefined}>
                      {t(`admin.synthetic.${key}`)}
                    </label>
                    <input type="number" step="any" min="0" value={synthForm[market][key] ?? ''}
                      onChange={e => setSynthForm({
                        ...synthForm,
                        [market]: { ...synthForm[market], [key]: e.target.value },
                      })} />
                  </div>
                ))}
              </div>
            ))}
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" disabled={synthBusy} onClick={handleSaveSynthetic}>
                <Save size={14} /> {t('admin.synthetic.save')}
              </button>
              <button className="admin-btn" disabled={synthBusy} onClick={() => handleTriggerSynthetic(false)}>
                <RefreshCw size={14} /> {t('admin.synthetic.triggerRound')}
              </button>
              {synthStats && (
                <span className="admin-count">
                  {t('admin.synthetic.stats24h', { stocks: synthStats.stocks24h ?? 0, crypto: synthStats.crypto24h ?? 0 })}
                </span>
              )}
            </div>

            <div className="admin-add-form">
              <h3>{t('admin.synthetic.manualTitle')}</h3>
              <p className="admin-section-hint">{t('admin.synthetic.manualHint')}</p>
              <div className="form-row">
                <input placeholder={t('admin.synthetic.symbolPh')} value={synthManual.symbol}
                  onChange={e => setSynthManual({ ...synthManual, symbol: e.target.value })} className="admin-input" />
                <select value={synthManual.side} onChange={e => setSynthManual({ ...synthManual, side: e.target.value })} className="admin-input">
                  <option value="">{t('admin.synthetic.sideRandom')}</option>
                  <option value="buy">{t('admin.synthetic.sideBuy')}</option>
                  <option value="sell">{t('admin.synthetic.sideSell')}</option>
                </select>
                <input placeholder={t('admin.synthetic.quantityPh')} type="number" step="any" min="0" value={synthManual.quantity}
                  onChange={e => setSynthManual({ ...synthManual, quantity: e.target.value })} className="admin-input" />
                <button className="admin-btn admin-btn-primary" disabled={synthBusy || !synthManual.symbol.trim()}
                  onClick={() => handleTriggerSynthetic(true)}>
                  <Bot size={14} /> {t('admin.synthetic.doTrade')}
                </button>
              </div>
            </div>

            <div className="admin-section-divider">
              <h3>{t('admin.synthetic.feedTitle')}</h3>
              <div className="stock-actions">
                <span className="admin-count">{synthOrders.length}</span>
                <button className="admin-btn" onClick={loadData} title={t('admin.synthetic.refresh')}>
                  <RefreshCw size={14} />
                </button>
              </div>
            </div>
            <div className="admin-list">
              {synthOrders.map(o => (
                <div key={o.id} className="admin-stock-item">
                  <div className="stock-info">
                    <strong>{o.symbol}</strong>
                    <span>{t(o.market === 'stocks' ? 'admin.synthetic.marketStocks' : 'admin.synthetic.marketCrypto')}</span>
                    <span className={`tx-type ${o.action === 'buy' ? 'income' : 'expense'}`}>
                      {t(o.action === 'buy' ? 'admin.synthetic.sideBuy' : 'admin.synthetic.sideSell')}
                    </span>
                    <span className="admin-count">{fmtQty(o.quantity)} × ${o.price != null ? Number(o.price).toLocaleString('ru-RU', { maximumFractionDigits: 6 }) : '—'}</span>
                  </div>
                  <div className="stock-actions">
                    <span className="user-date">{fmtTs(o.timestamp)}</span>
                  </div>
                </div>
              ))}
              {synthOrders.length === 0 && <p className="empty-state">{t('admin.synthetic.feedEmpty')}</p>}
            </div>
          </div>
          )
        })()}

        {editingCoin && (
          <div className="modal-overlay" onClick={() => setEditingCoin(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>{t('admin.crypto.editCoin')}: {editingCoin}</h3>
              <div className="config-form">
                <div className="config-field">
                  <label>{t('admin.name')}</label>
                  <input value={coinForm.name} onChange={e => setCoinForm({ ...coinForm, name: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.price')}</label>
                  <input type="number" step="0.000001" value={coinForm.price}
                    onChange={e => setCoinForm({ ...coinForm, price: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>
                    {t('admin.crypto.marketCap')}
                    <Tooltip text={t('admin.crypto.marketCapHelp')} />
                  </label>
                  <input type="number" step="1" value={coinForm.marketCap}
                    onChange={e => setCoinForm({ ...coinForm, marketCap: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.crypto.volatility')}</label>
                  <input type="number" step="0.01" min="0.001" max="1" value={coinForm.volatility}
                    onChange={e => setCoinForm({ ...coinForm, volatility: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.crypto.color')}</label>
                  <input type="color" value={coinForm.color || '#6366f1'}
                    onChange={e => setCoinForm({ ...coinForm, color: e.target.value })} />
                </div>
                <div className="config-field">
                  <label>{t('admin.crypto.description')}</label>
                  <input value={coinForm.description} onChange={e => setCoinForm({ ...coinForm, description: e.target.value })} />
                </div>
              </div>
              <div className="modal-buttons">
                <button className="admin-btn admin-btn-primary" onClick={handleSaveCoin}>
                  <Save size={14} /> {t('admin.save')}
                </button>
                <button className="admin-btn" onClick={() => setEditingCoin(null)}>
                  {t('admin.cancel')}
                </button>
              </div>
            </div>
          </div>
        )}

        {chartAsset && (
          <PriceHistoryEditor
            market={chartAsset.market}
            symbol={chartAsset.symbol}
            onClose={() => setChartAsset(null)}
          />
        )}

        {editingStockConfig && (
          <div className="modal-overlay" onClick={() => setEditingStockConfig(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>{t('admin.editStockConfig') || 'Конфигурация'}: {editingStockConfig}</h3>
              <div className="config-form">
                <div className="config-field">
                  <label>
                    {t('admin.volatilityK') || 'Волатильность (K)'}
                    <Tooltip text={t('admin.volatilityKHelp') || 'Чем выше значение, тем сильнее меняется цена при сделках. 0.1 — стабильно, 0.5 — волатильно'} />
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.001"
                    max="1"
                    placeholder="0.1"
                    value={configForm.volatility_k}
                    onChange={e => setConfigForm({ ...configForm, volatility_k: e.target.value })}
                  />
                </div>
                <div className="config-field">
                  <label>
                    {t('admin.totalShares') || 'Всего акций'}
                    <Tooltip text={t('admin.totalSharesHelp') || 'Общее количество акций компании. Влияет на формулу расчёта цены: ΔP = Price × K × (ΔVolume / TotalShares)'} />
                  </label>
                  <input
                    type="number"
                    min="1"
                    placeholder="1000000000"
                    value={configForm.total_shares}
                    onChange={e => setConfigForm({ ...configForm, total_shares: e.target.value })}
                  />
                </div>
                <div className="config-field">
                  <label>
                    {t('admin.priceDropThreshold') || 'Порог падения'}
                    <Tooltip text={t('admin.priceDropThresholdHelp') || 'При падении цены на этот % розница начинает активно покупать (ловить дно). Например: -0.05 = -5%'} />
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="-0.5"
                    max="0"
                    placeholder="-0.05"
                    value={configForm.price_drop_threshold}
                    onChange={e => setConfigForm({ ...configForm, price_drop_threshold: e.target.value })}
                  />
                </div>
                <div className="config-field">
                  <label>
                    {t('admin.priceRiseThreshold') || 'Порог роста'}
                    <Tooltip text={t('admin.priceRiseThresholdHelp') || 'При росте цены на этот % киты начинают фиксировать прибыль. Например: 0.10 = +10%'} />
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    placeholder="0.10"
                    value={configForm.price_rise_threshold}
                    onChange={e => setConfigForm({ ...configForm, price_rise_threshold: e.target.value })}
                  />
                </div>
                <div className="config-field">
                  <label>
                    {t('admin.maxOrderSize') || 'Макс. ордер (%)'}
                    <Tooltip text={t('admin.maxOrderSizeHelp') || 'Максимальный размер одного ордера в % от свободных акций. Защита от манипуляций'} />
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    min="0.001"
                    max="0.5"
                    placeholder="0.01"
                    value={configForm.max_order_size_percent}
                    onChange={e => setConfigForm({ ...configForm, max_order_size_percent: e.target.value })}
                  />
                </div>
              </div>
              <div className="modal-buttons">
                <button className="admin-btn admin-btn-primary" onClick={handleSaveStockConfig}>
                  <Save size={14} /> {t('admin.save')}
                </button>
                <button className="admin-btn" onClick={() => setEditingStockConfig(null)}>
                  {t('admin.cancel')}
                </button>
              </div>
            </div>
          </div>
        )}

        {!loading && activeSection === 'users' && (
          <>
            <div className="admin-list">
              <div className="admin-toolbar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={userSearch} onChange={e => setUserSearch(e.target.value)} placeholder={t('admin.searchUsers')} /></div>
                <span className="admin-count">{t('admin.totalUsers')}: {users.length}</span>
                {can('users_view') && <button className="admin-btn" onClick={handleLoadIpGroups}><Search size={14} /> {t('admin.ipGroups')}</button>}
              </div>
              {ipGroups && <div className="admin-ip-groups">
                {ipGroups.length ? ipGroups.map(group => <div key={group.ip}><strong>{group.ip}</strong><span>{group.users.map(user => user.username).join(', ')}</span></div>) : <span className="user-date">{t('admin.ipGroupsEmpty')}</span>}
              </div>}
              {[...users]
                .filter(u => !userSearch || (u.username || '').toLowerCase().includes(userSearch.toLowerCase()))
                .sort((a, b) => {
                  const dir = userOrder >= 0 ? 1 : -1
                  const av = a[userSort], bv = b[userSort]
                  if (typeof av === 'string' || typeof bv === 'string') {
                    return String(av ?? '').localeCompare(String(bv ?? '')) * dir
                  }
                  return ((av ?? 0) - (bv ?? 0)) * dir
                })
                .map(u => (
                <div key={u.id} className={`admin-user-item${editingUser === u.id ? ' editing' : ''}`}>
                  <div className="admin-user-info">
                    <div>
                      <strong>{u.username}</strong>
                      <span className={`user-role ${u.role || 'user'}`}>{u.role || 'user'}</span>
                      {u.role === 'admin' && (
                        <span className="user-role user" title={t('adminPerms.levelTitle')}>L{u.admin_level || 4}</span>
                      )}
                      {Object.keys(u.bans || {}).length > 0 && (
                        <span className="user-role admin" title={Object.keys(u.bans).join(', ')}>
                          <ShieldAlert size={12} />
                        </span>
                      )}
                      {u.hidden_from_leaderboard && (
                        <span className="user-role admin" title={t('admin.fieldHiddenFromLeaderboard')}>
                          <EyeOff size={12} />
                        </span>
                      )}
                    </div>
                    <span className="lb-breakdown admin-user-money">
                      {USER_MONEY_CHIPS.map(c => (
                        <span key={c.key} className={`lb-chip${userSort === c.key ? ' active' : ''}`}
                          title={`$${(u[c.key] ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}`}>
                          {t(`leaderboard.col_${c.col}`)} <b>${formatCompact(u[c.key] ?? 0)}</b>
                        </span>
                      ))}
                    </span>
                    <div className="admin-user-meta">
                      <span className="user-date">{fmtTs(u.created_at)}</span>
                      {u.ips?.length > 0 && (
                        <span className="user-date" title={u.ips.map(x => x.ip).join(', ')}>
                          IP: {u.ips[0].ip}{u.ips.length > 1 ? ` (+${u.ips.length - 1})` : ''}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="admin-user-capital" title={`$${(u.netWorth ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}`}>
                    ${formatCompact(u.netWorth ?? 0)}
                  </span>
                  <div className="user-actions">
                    {can('users_property') && (
                      <button className="admin-btn" onClick={() => setPropertyUser(u)} title={t('admin.property.title')}>
                        <Briefcase size={14} />
                      </button>
                    )}
                    {can('users_edit') && u.role !== 'admin' && (
                      <button className="admin-btn" onClick={() => handleLoginAs(u.id)} title={t('admin.loginAs')}>
                        <LogIn size={14} />
                      </button>
                    )}
                    {can('users_edit') && (
                      <button className="admin-btn" onClick={() => handleStartEditUser(u)}>
                        <Edit3 size={14} />
                      </button>
                    )}
                    {can('users_delete') && (
                      <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteUser(u.id, u.username)}>
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {users.length === 0 && <p className="empty-state">{t('admin.noUsers')}</p>}
            </div>
            {editingUser && (() => {
              const u = users.find(x => x.id === editingUser)
              return (
                <aside className="user-edit-panel">
                  <div className="user-edit-panel-header">
                    <strong>{t('admin.editUser')}: {u?.username}</strong>
                    <button className="admin-btn" onClick={handleCancelEditUser}><X size={16} /></button>
                  </div>
                  <div className="user-edit-panel-body">
                    <div className="admin-field-group">
                      <label>{t('admin.fieldUsername')}</label>
                      <input type="text" value={editForm.username}
                        onChange={e => setEditForm({ ...editForm, username: e.target.value })}
                        className={`admin-input${editErrors.username ? ' admin-input-error' : ''}`} />
                      {editErrors.username && <span className="admin-field-error">{editErrors.username}</span>}
                    </div>
                    <div className="admin-field-group">
                      <label>{t('admin.fieldBalance')}</label>
                      <input type="number" step="0.01" min="0" value={editForm.balance}
                        onChange={e => setEditForm({ ...editForm, balance: e.target.value })}
                        className={`admin-input${editErrors.balance ? ' admin-input-error' : ''}`} />
                      {editErrors.balance && <span className="admin-field-error">{editErrors.balance}</span>}
                    </div>
                    <div className="admin-field-group">
                      <label>{t('admin.fieldRole')}</label>
                      <select value={editForm.role}
                        onChange={e => setEditForm({ ...editForm, role: e.target.value })}
                        className={`admin-input${editErrors.role ? ' admin-input-error' : ''}`}>
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                      {editErrors.role && <span className="admin-field-error">{editErrors.role}</span>}
                    </div>
                    {editForm.role === 'admin' && (
                      <div className="admin-field-group">
                        <label>{t('adminPerms.levelTitle')}</label>
                        <select value={editForm.admin_level}
                          onChange={e => setEditForm({ ...editForm, admin_level: Number(e.target.value) })}
                          className="admin-input">
                          {ADMIN_LEVELS.map(l => (
                            <option key={l} value={l}>L{l} — {t(`adminPerms.level${l}`)}</option>
                          ))}
                        </select>
                      </div>
                    )}
                    <div className="admin-field-group">
                      <label>{t('admin.fieldCardNumber')}</label>
                      <input type="text" value={editForm.card_number}
                        onChange={e => setEditForm({ ...editForm, card_number: e.target.value })}
                        className={`admin-input${editErrors.card_number ? ' admin-input-error' : ''}`}
                        placeholder="XXXX-XXXX-XXXX-XXXXX" maxLength={20} />
                      {editErrors.card_number && <span className="admin-field-error">{editErrors.card_number}</span>}
                    </div>
                    <div className="admin-field-checkbox">
                      <label>
                        <input type="checkbox" checked={editForm.hidden_from_leaderboard}
                          onChange={e => setEditForm({ ...editForm, hidden_from_leaderboard: e.target.checked })} />
                        {t('admin.fieldHiddenFromLeaderboard')}
                      </label>
                    </div>
                    <div className="admin-field-checkbox">
                      <label>
                        <input type="checkbox" checked={editForm.leaderboard_lock}
                          onChange={e => setEditForm({ ...editForm, leaderboard_lock: e.target.checked })} />
                        {t('admin.fieldLeaderboardLock')}
                      </label>
                    </div>
                  </div>
                  <div className="admin-field-group admin-bans-block">
                    <label>{t('admin.bansTitle')}</label>
                    <div className="admin-ban-tree">
                      <div className="admin-ban-group admin-ban-account">
                        <button type="button" className="admin-ban-toggle" onClick={() => setExpandedBans(prev => ({ ...prev, account: !prev.account }))}>
                          {expandedBans.account ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                        <TriStateCheckbox checked={!!banDraft.account?.on}
                          indeterminate={!banDraft.account?.on && PLAYER_BAN_FUNCS.some(key => banDraft[key]?.on)}
                          onChange={e => toggleBanKeys(['account', ...PLAYER_BAN_FUNCS], e.target.checked)} />
                        <span>{t('admin.banAccount')}</span>
                        {banDraft.account?.on && <BanDetails ban={banDraft.account} onChange={patch => setBanDraft({ ...banDraft, account: { ...banDraft.account, ...patch } })} t={t} />}
                      </div>
                      {expandedBans.account && <div className="admin-ban-children">
                        {BAN_GROUPS.map(group => {
                          const keys = [group.id, ...group.actions]
                          const groupOn = keys.every(key => banDraft[key]?.on)
                          const hasChildren = group.actions.length > 0
                          return <div key={group.id} className="admin-ban-group">
                            {hasChildren ? <button type="button" className="admin-ban-toggle" onClick={() => setExpandedBans(prev => ({ ...prev, [group.id]: !prev[group.id] }))}>
                              {expandedBans[group.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </button> : <span className="admin-ban-toggle-spacer" />}
                            <TriStateCheckbox checked={groupOn}
                              indeterminate={!groupOn && keys.some(key => banDraft[key]?.on)}
                              onChange={e => toggleBanKeys(keys, e.target.checked)} />
                            <span>{t(`banFunc.${group.id}`)}</span>
                            {groupOn && <BanDetails ban={banDraft[group.id]} onChange={patch => setBanDraft({ ...banDraft, [group.id]: { ...(banDraft[group.id] || {}), on: true, ...patch } })} t={t} />}
                            {hasChildren && expandedBans[group.id] && !groupOn && <div className="admin-ban-children">
                              {group.actions.map(f => {
                                const d = banDraft[f] || {}
                                return <label key={f} className="admin-ban-row">
                                  <input type="checkbox" checked={!!d.on} onChange={e => toggleBanKeys([f], e.target.checked)} />
                                  <span>{t(`banFunc.${f}`)}</span>
                                  {d.on && <BanDetails ban={d} onChange={patch => setBanDraft({ ...banDraft, [f]: { ...d, ...patch } })} t={t} />}
                                </label>
                              })}
                            </div>}
                          </div>
                        })}
                      </div>}
                    </div>
                  </div>
                  <div className="admin-field-group">
                    <label>{t('admin.fieldIps')}</label>
                    {(u.ips || []).map(x => (
                      <div key={x.ip} className="admin-ip-row">
                        <span>{x.ip}</span>
                        <span className="user-date">{fmtTs(x.at)}</span>
                      </div>
                    ))}
                    {!u.ips?.length && <span className="user-date">{t('admin.ipsEmpty')}</span>}
                  </div>
                  {can('users_password') && (
                    <div className="admin-field-group">
                      <label>{t('admin.resetPassword')}</label>
                      <input type="text" className="admin-input" value={newPassword}
                        placeholder={t('admin.resetPasswordPh')} maxLength={72}
                        onChange={e => setNewPassword(e.target.value)} />
                    </div>
                  )}
                  {can('users_logout') && (
                    <button className="admin-btn" disabled={pwdBusy} onClick={handleLogoutUser}>
                      <LogOut size={14} /> {t('admin.logoutUser')}
                    </button>
                  )}
                  {can('users_edit') && (
                    <button className="admin-btn" onClick={handleResetAvatar}>
                      <EyeOff size={14} /> {t('admin.avatarReset')}
                    </button>
                  )}
                  <div className="user-edit-panel-actions">
                    <button className="admin-btn admin-btn-primary" onClick={handleSaveUser}>
                      <Save size={14} /> {t('admin.save')}
                    </button>
                    <button className="admin-btn" onClick={handleCancelEditUser}>
                      <X size={14} /> {t('admin.cancel')}
                    </button>
                  </div>
                </aside>
              )
            })()}
          </>
        )}

        {!loading && activeSection === 'audit' && (
          <div className="admin-audit-log">
            {auditLogs.length === 0 && <p className="empty-state">{t('admin.auditEmpty')}</p>}
            {auditLogs.map((log, index) => (
              <div className="admin-audit-row" key={`${log.createdAt}-${index}`}>
                <span className="user-date">{fmtTs(log.createdAt)}</span>
                <strong>{log.action}</strong>
                <span>{log.actorUsername}</span>
                {log.targetUsername && <span>→ {log.targetUsername}</span>}
                {Object.keys(log.changes || {}).length > 0 && <code>{JSON.stringify(log.changes)}</code>}
              </div>
            ))}
          </div>
        )}

        {!loading && activeSection === 'lots' && (
          <div>
            <div className="admin-toolbar">
              <select className="admin-input" value={lotsStatus} onChange={e => setLotsStatus(e.target.value)}>
                {['active', 'sold', 'cancelled', 'all'].map(s => (
                  <option key={s} value={s}>{t(`admin.lots.status_${s}`)}</option>
                ))}
              </select>
              <span className="admin-count">{t('admin.lots.count', { count: lots.length })}</span>
            </div>
            <div className="admin-list">
              {lots.map(l => (
                <div key={l.id} className="admin-stock-item">
                  <div className="stock-info">
                    <strong>{l.name}</strong>
                    <span>{t(l.kind === 'asset' ? 'centralmarket.cat_asset' : 'centralmarket.cat_hardware')}</span>
                    <span>{l.seller}</span>
                    <span className="admin-count">×{l.qty} · ${Number(l.pricePerItem || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}</span>
                  </div>
                  <div className="stock-actions">
                    <span className="user-date">{fmtTs(l.createdAt)}</span>
                    {l.kind === 'asset' && can('users_property') && (
                      <button className="admin-btn" title={t('admin.property.title')}
                        onClick={() => setPropertyUser({ id: l.sellerId, username: l.seller })}>
                        <Briefcase size={14} />
                    </button>
                    )}
                    <button className="admin-btn admin-btn-danger" title={t('admin.lots.cancelLot')}
                      onClick={() => handleCancelLot(l)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
              {lots.length === 0 && <p className="empty-state">{t('admin.lots.empty')}</p>}
            </div>
          </div>
        )}

        {!loading && activeSection === 'broadcast' && (
          <div>
            <div className="admin-section-divider">
              <h3>{t('admin.broadcast.title')}</h3>
              <p className="admin-section-hint">{t('admin.broadcast.hint')}</p>
            </div>
            <div className="admin-add-form">
              <div className="config-field">
                <label>{t('admin.broadcast.titleLabel')}</label>
                <input className="admin-input" value={bcForm.title} maxLength={120}
                  onChange={e => setBcForm({ ...bcForm, title: e.target.value })} />
              </div>
              <div className="config-field">
                <label>{t('admin.broadcast.messageLabel')}</label>
                <textarea className="admin-input db-json-textarea" rows={4} value={bcForm.message}
                  maxLength={2000} onChange={e => setBcForm({ ...bcForm, message: e.target.value })} />
              </div>
            </div>
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" disabled={bcBusy || !bcForm.title.trim()}
                onClick={handleBroadcast}>
                <Megaphone size={14} /> {t('admin.broadcast.send')}
              </button>
            </div>
          </div>
        )}

        {!loading && activeSection === 'perms' && (
          <div>
            <div className="admin-section-divider">
              <h3>{t('adminPerms.title')}</h3>
              <p className="admin-section-hint">{t('adminPerms.hint')}</p>
            </div>
            <div className="admin-list">
              {(perms?.functions || []).map(f => (
                <div key={f.id} className="admin-stock-item">
                  <div className="stock-info">
                    <strong>{t(f.label)}</strong>
                    {f.fixed && <span className="user-role admin" title={t('adminPerms.fixedHint')}>fixed L4</span>}
                  </div>
                  <select
                    className="admin-input"
                    style={{ width: 220 }}
                    value={f.level}
                    disabled={f.fixed}
                    onChange={e => setPerms({
                      ...perms,
                      functions: perms.functions.map(x => x.id === f.id ? { ...x, level: Number(e.target.value) } : x),
                    })}
                  >
                    {ADMIN_LEVELS.map(l => <option key={l} value={l}>L{l} — {t(`adminPerms.level${l}`)}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" disabled={permsSaving} onClick={handleSavePerms}>
                <Save size={14} /> {t('econ.save')}
              </button>
              <span className="admin-count">{t('adminPerms.hintLevels')}</span>
            </div>
          </div>
        )}

        {!loading && activeSection === 'transactions' && (() => {
          const fmtMoney = (v) => `$${Math.abs(Number(v) || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          // Единый поток операций реестра и сделок ботов приходит уже отфильтрованным,
          // отсортированным и постранично — иначе искать можно было бы только внутри
          // последних N записей (см. /api/admin/transactions).
          const rows = transactions.items
          const hasNext = !!transactions.has_more
          return (
            <>
              <div className="tx-filter-bar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={txSearchInput} onChange={e => setTxSearchInput(e.target.value)} placeholder={t('admin.searchTx', 'Поиск по операции, категории, игроку...')} /></div>
                <TxFilters
                  filters={txFilters} setFilters={setTxFilters}
                  options={txOptions} openMenu={openTxMenu} setOpenMenu={setOpenTxMenu}
                  toggleValue={toggleTxValue} setMode={setTxMode} setRange={setTxRange}
                  sort={txSort} onSort={setTxSort}
                />
                <button className="admin-btn" onClick={() => setTxOrder(o => -o)}
                  title={txOrder >= 0 ? t('admin.database.sortAsc') : t('admin.database.sortDesc')}>
                  {txOrder >= 0 ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                <button className="admin-btn" onClick={() => setTxNonce(n => n + 1)} title={t('admin.refresh')}>
                  <RefreshCw size={14} />
                </button>
                <div className="tx-preset-group">
                  <select className="admin-input" value={txPresetSel} onChange={e => applyTxPreset(e.target.value)}
                    title={t('admin.txPresets.title')}>
                    <option value="">{t('admin.txPresets.load')}</option>
                    {Object.keys(txPresets).map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                  <button className="admin-btn" onClick={saveTxPreset} title={t('admin.txPresets.save')}>
                    <Save size={14} />
                  </button>
                  <button className="admin-btn" disabled={!txPresetSel} onClick={deleteTxPreset} title={t('admin.txPresets.delete')}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              <div className="admin-tx-table tx-cols-6">
                <div className="admin-tx-row admin-tx-head">
                  <span>{t('admin.txDirection', 'Операция')}</span>
                  <span>{t('admin.txLabel', 'Описание')}</span>
                  <span>{t('admin.txCategory', 'Категория')}</span>
                  <span>{t('admin.txUser', 'Игрок')}</span>
                  <span className="tx-num">{t('admin.txAmount', 'Сумма')}</span>
                  <span className="tx-num">{t('admin.txBalance', 'Баланс после')}</span>
                  <span>{t('admin.txTime', 'Время')}</span>
                  <span></span>
                </div>
                {rows.map(tx => {
                  const income = tx.direction === 'income'
                  return (
                    <div key={`${tx.source}-${tx.id}`} className={`admin-tx-row ${tx.source === 'bot' ? 'bot' : ''}`}>
                      <span><span className={`tx-type ${income ? 'income' : 'expense'}`}>{income ? t('admin.txIn', 'Доход') : t('admin.txOut', 'Расход')}</span></span>
                      <span><strong>{tx.label || '—'}</strong></span>
                      <span><span className="tx-cat">{tx.category || '—'}</span></span>
                      <span className="tx-user">{tx.username || '—'}</span>
                      <span className={`tx-num tx-amount ${income ? 'income' : 'expense'}`}>{income ? '+' : '−'}{fmtMoney(tx.amount)}</span>
                      <span className="tx-num tx-balance">{tx.balanceAfter != null ? fmtMoney(tx.balanceAfter) : '—'}</span>
                      <span className="tx-time">{fmtTs(tx.timestamp)}</span>
                      <span className="tx-act">
                        {tx.source === 'user' && can('transactions_delete')
                          ? <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteTransaction(tx.id)}><Trash2 size={14} /></button>
                          : <span className="tx-dash">—</span>}
                      </span>
                    </div>
                  )
                })}
                {rows.length === 0 && <p className="empty-state">{t('admin.noTransactions')}</p>}
              </div>
              {(txPage > 0 || hasNext) && (
                <div className="admin-toolbar db-pagination">
                  <button className="admin-btn" disabled={txPage === 0} onClick={() => setTxPage(p => Math.max(0, p - 1))}>
                    <ChevronLeft size={14} />
                  </button>
                  <span className="admin-count">{txPage + 1}</span>
                  <button className="admin-btn" disabled={!hasNext} onClick={() => setTxPage(p => p + 1)}>
                    <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </>
          )
        })()}

        {!loading && activeSection === 'config' && (
          <div>
            <div className="admin-add-form">
              <h3>{t('admin.addConfig')}</h3>
              <div className="form-row">
                <input
                  placeholder={t('admin.keyPlaceholder')}
                  value={newConfig.key}
                  onChange={e => setNewConfig({ ...newConfig, key: e.target.value })}
                  className="admin-input"
                />
                <input
                  placeholder={t('admin.valuePlaceholder')}
                  value={newConfig.value}
                  onChange={e => setNewConfig({ ...newConfig, value: e.target.value })}
                  className="admin-input"
                />
                <button className="admin-btn admin-btn-primary" onClick={handleSaveConfig}>
                  <Save size={16} /> {t('admin.save')}
                </button>
              </div>
            </div>
            <div className="admin-list">
              {configItems.map(cfg => (
                <div key={cfg.key} className="admin-config-item">
                  <div>
                    <strong>{cfg.key}</strong>
                    <span className="config-value">{cfg.value}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>

      {propertyUser && (
        <UserPropertyModal
          username={propertyUser.username}
          userId={propertyUser.id}
          onClose={() => setPropertyUser(null)}
        />
      )}
    </div>
  )
}

export default AdminPanel
