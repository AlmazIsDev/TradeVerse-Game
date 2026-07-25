import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchStocks, fetchStocksV2, fetchConfig, request, adminUpdateUser, adminDeleteUser, updateStockConfig,
  adminListCollections, adminListDocuments, adminCreateDocument, adminUpdateDocument, adminDeleteDocument,
  adminListTransactions,
  fetchCryptoMarket, adminUpdateCoin, adminCreateCoin, adminDeleteCoin,
} from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import EconomyAdmin from './EconomyAdmin'
import UserPropertyModal from './UserPropertyModal'
import PriceHistoryEditor from './PriceHistoryEditor'
import {
  Plus, Trash2, Edit3, Save, X, Settings, Users, ArrowLeftRight,
  Package, ChevronDown, ChevronUp, ShieldAlert, Sliders, HelpCircle, Activity, Search, DollarSign, RefreshCw, Briefcase, EyeOff,
  Database, Coins, ChevronLeft, ChevronRight,
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

const CARD_NUMBER_RE = /^\d{4}-\d{4}-\d{4}-\d{5}$/

// Подсветка полей документа по типу значения — чтобы не путаться где что.
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

// Поля транзакций: сортировка + точечный поиск вида "Категория: cityroof".
const TX_FIELDS = [
  { key: 'timestamp', i18n: 'admin.txTime', fallback: 'Время' },
  { key: 'direction', i18n: 'admin.txDirection', fallback: 'Операция' },
  { key: 'label', i18n: 'admin.txLabel', fallback: 'Описание' },
  { key: 'category', i18n: 'admin.txCategory', fallback: 'Категория' },
  { key: 'username', i18n: 'admin.txUser', fallback: 'Игрок' },
  { key: 'amount', i18n: 'admin.txAmount', fallback: 'Сумма' },
  { key: 'balanceAfter', i18n: 'admin.txBalance', fallback: 'Баланс после' },
]

function AdminPanel({ user, onClose }) {
  const { t } = useTranslation()

  // Защита на уровне компонента: если пользователь не админ — показываем сообщение
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
  const [activeSection, setActiveSection] = useState('stocks')
  const [stocks, setStocks] = useState([])
  const [stocksV2, setStocksV2] = useState([])
  const [users, setUsers] = useState([])
  const [transactions, setTransactions] = useState({ items: [], has_more: false })
  const [txFilter, setTxFilter] = useState('all') // 'all' | 'income' | 'expense' | 'bot'
  const [txSearch, setTxSearch] = useState('')       // дебаунсенное значение, уходит на сервер
  const [txSearchInput, setTxSearchInput] = useState('') // сырой ввод
  const [txSort, setTxSort] = useState('timestamp')
  const [txOrder, setTxOrder] = useState(-1) // 1 asc / -1 desc
  const [txPage, setTxPage] = useState(0)    // 0-based
  const [txNonce, setTxNonce] = useState(0)  // ручное обновление (кнопка/удаление)
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

  // Состояние для редактирования пользователя
  const [editingUser, setEditingUser] = useState(null)
  const [userSearch, setUserSearch] = useState('')
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
  const [propertyUser, setPropertyUser] = useState(null)

  // ── Состояние для вкладки "База данных" ─────────────────────────────────
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

  // ── Состояние для вкладки "Крипта" ──────────────────────────────────────
  const [coins, setCoins] = useState([])
  const [coinSearch, setCoinSearch] = useState('')
  const [editingCoin, setEditingCoin] = useState(null) // символ редактируемой монеты
  const [coinForm, setCoinForm] = useState({ name: '', price: '', marketCap: '', volatility: '', color: '', description: '' })
  const [showAddCoinForm, setShowAddCoinForm] = useState(false)
  const [newCoin, setNewCoin] = useState({ symbol: '', name: '', price: '', volatility: '0.05', color: '#6366f1', supply: '', description: '' })
  const [chartAsset, setChartAsset] = useState(null) // { market, symbol } | null — открывает PriceHistoryEditor

  useEffect(() => {
    loadData()
  }, [activeSection])

  // Сброс на первую страницу при смене коллекции, поиска или сортировки.
  useEffect(() => { setDbPage(0) }, [dbActiveCollection, dbSearch, dbSort, dbOrder])

  // Дебаунс поискового ввода — regex-поиск по 900k дорогой, не дёргаем на каждый символ.
  useEffect(() => {
    const id = setTimeout(() => setDbSearch(dbSearchInput.trim()), 400)
    return () => clearTimeout(id)
  }, [dbSearchInput])

  // Точечный поиск: "поле: значение" (напр. «Категория: cityroof», "username: admin").
  // Поле распознаём и по имени, и по локализованной подписи; иначе — свободный поиск.
  const parseTxSearch = (raw) => {
    const s = raw.trim()
    const m = s.match(/^([^:]+):\s*(.*)$/)
    if (!m) return { q: s, field: undefined }
    const key = m[1].trim().toLowerCase()
    const f = TX_FIELDS.find(x => x.key.toLowerCase() === key || t(x.i18n, x.fallback).toLowerCase() === key)
    return f ? { q: m[2].trim(), field: f.key } : { q: s, field: undefined }
  }

  // Сброс на первую страницу при смене фильтра, поиска или сортировки.
  useEffect(() => { setTxPage(0) }, [txFilter, txSearch, txSort, txOrder])

  // Дебаунс: regex-поиск идёт по 180k записям, не дёргаем сервер на каждый символ.
  useEffect(() => {
    const id = setTimeout(() => setTxSearch(txSearchInput.trim()), 400)
    return () => clearTimeout(id)
  }, [txSearchInput])

  useEffect(() => {
    if (activeSection !== 'transactions') return
    const { q, field } = parseTxSearch(txSearch)
    adminListTransactions({
      q: q || undefined, field, kind: txFilter,
      skip: txPage * TX_PAGE_SIZE, limit: TX_PAGE_SIZE,
      sort: txSort, order: txOrder,
    })
      .then(setTransactions)
      .catch(err => toast(t('admin.loadError') + ': ' + err.message, 'error'))
  }, [activeSection, txFilter, txSearch, txSort, txOrder, txPage, txNonce])

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
      } else if (activeSection === 'transactions') {
        // Транзакции грузит отдельный effect (по фильтру/поиску/сортировке/странице).
      } else if (activeSection === 'database') {
        if (dbCollections.length === 0) {
          const cols = await adminListCollections()
          setDbCollections(cols)
          if (!dbActiveCollection && cols.length) setDbActiveCollection(cols[0])
        }
        // Документы грузит отдельный effect (по dbActiveCollection/page/sort/search).
      } else if (activeSection === 'crypto') {
        const data = await fetchCryptoMarket()
        // Прячем API-монеты (CoinGecko) — их всё равно перезатирает рефреш;
        // админ управляет только игровыми и компанийными монетами.
        setCoins(data.filter(c => c.source !== 'coingecko'))
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

  // ── Валидация формы редактирования пользователя ────────────────────────────

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

  // ── Обработчики пользователя ───────────────────────────────────────────────

  const handleStartEditUser = (u) => {
    setEditingUser(u.id)
    setEditForm({
      username: u.username || '',
      balance: u.balance != null ? String(u.balance) : '',
      role: u.role || 'user',
      card_number: u.card_number || '',
      hidden_from_leaderboard: !!u.hidden_from_leaderboard,
      leaderboard_lock: !!u.leaderboard_lock,
    })
    setEditErrors({})
  }

  const handleCancelEditUser = () => {
    setEditingUser(null)
    setEditForm({
      username: '',
      balance: '',
      role: 'user',
      card_number: '',
      hidden_from_leaderboard: false,
      leaderboard_lock: false,
    })
    setEditErrors({})
  }

  const handleSaveUser = async () => {
    if (!validateEditForm()) return

    const payload = {
      username: editForm.username.trim(),
      balance: parseFloat(editForm.balance),
      role: editForm.role,
      hidden_from_leaderboard: editForm.hidden_from_leaderboard,
      leaderboard_lock: editForm.leaderboard_lock,
    }

    // Добавляем card_number только если заполнен
    if (editForm.card_number.trim()) {
      payload.card_number = editForm.card_number.trim()
    }

    try {
      await adminUpdateUser(editingUser, payload)
      setEditingUser(null)
      toast(t('admin.userUpdated'))
      loadData()
    } catch (err) {
      toast(t('admin.error') + ': ' + err.message, 'error')
    }
  }

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

  // ── Обработчики акций ──────────────────────────────────────────────────────

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

  // ── Обработчики конфига акций ────────────────────────────────────────────

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

  // ── Обработчики базы данных ────────────────────────────────────────────────

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

  // ── Обработчики крипты ─────────────────────────────────────────────────────

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

  const sections = [
    { id: 'stocks', label: t('admin.stocks'), icon: Package },
    { id: 'crypto', label: t('admin.crypto.title'), icon: Coins },
    { id: 'prices', label: t('admin.prices.title'), icon: DollarSign },
    { id: 'users', label: t('admin.users'), icon: Users },
    { id: 'transactions', label: t('admin.transactions'), icon: ArrowLeftRight },
    { id: 'economy', label: t('econ.tab'), icon: Activity },
    { id: 'config', label: t('admin.config'), icon: Settings },
    { id: 'database', label: t('admin.database.title'), icon: Database },
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
          {sections.map(s => (
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

        {activeSection === 'economy' && <EconomyAdmin />}

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

            {/* Stock Config Section */}
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
          // Поля для сортировки — объединение ключей документов текущей страницы.
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

        {/* Config Modal */}
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
              </div>
              {users.filter(u => !userSearch || (u.username || '').toLowerCase().includes(userSearch.toLowerCase())).map(u => (
                <div key={u.id} className={`admin-user-item${editingUser === u.id ? ' editing' : ''}`}>
                  <div className="admin-user-info">
                    <div>
                      <strong>{u.username}</strong>
                      <span className={`user-role ${u.role || 'user'}`}>{u.role || 'user'}</span>
                      {u.hidden_from_leaderboard && (
                        <span className="user-role admin" title={t('admin.fieldHiddenFromLeaderboard')}>
                          <EyeOff size={12} />
                        </span>
                      )}
                    </div>
                    <div className="admin-user-meta">
                      <span className="user-balance">${u.balance != null ? u.balance.toFixed(2) : '0.00'}</span>
                      <span className="user-date">{u.created_at}</span>
                    </div>
                  </div>
                  <div className="user-actions">
                    <button className="admin-btn" onClick={() => setPropertyUser(u)} title={t('admin.property.title')}>
                      <Briefcase size={14} />
                    </button>
                    <button className="admin-btn" onClick={() => handleStartEditUser(u)}>
                      <Edit3 size={14} />
                    </button>
                    <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteUser(u.id, u.username)}>
                      <Trash2 size={14} />
                    </button>
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

        {!loading && activeSection === 'transactions' && (() => {
          const fmtTs = (ts) => {
            if (!ts) return '—'
            const d = new Date(ts)
            if (isNaN(d.getTime())) return ts
            const p = n => String(n).padStart(2, '0')
            return `${p(d.getDate())}.${p(d.getMonth()+1)}.${String(d.getFullYear()).slice(2)} ${p(d.getHours())}:${p(d.getMinutes())}`
          }
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
                <div className="tx-chips">
                  {['all', 'income', 'expense', 'bot'].map(f => (
                    <button key={f} className={`tx-chip ${txFilter === f ? 'active' : ''}`} onClick={() => setTxFilter(f)}>
                      {t(`admin.txFilter.${f}`, f.toUpperCase())}
                    </button>
                  ))}
                </div>
                <select className="admin-input tx-sort-select" value={txSort} onChange={e => setTxSort(e.target.value)}>
                  {TX_FIELDS.map(f => <option key={f.key} value={f.key}>{t(f.i18n, f.fallback)}</option>)}
                </select>
                <button className="admin-btn" onClick={() => setTxOrder(o => -o)}
                  title={txOrder >= 0 ? t('admin.database.sortAsc') : t('admin.database.sortDesc')}>
                  {txOrder >= 0 ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                <button className="admin-btn" onClick={() => setTxNonce(n => n + 1)} title={t('admin.refresh')}>
                  <RefreshCw size={14} />
                </button>
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
                        {tx.source === 'user'
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
