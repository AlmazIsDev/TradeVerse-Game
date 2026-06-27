import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchStocks, fetchConfig, request, adminUpdateUser, adminDeleteUser } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import {
  Plus, Trash2, Edit3, Save, X, Settings, Users, ArrowLeftRight,
  Package, ChevronDown, ChevronUp, ShieldAlert
} from 'lucide-react'

const CARD_NUMBER_RE = /^\d{4}-\d{4}-\d{4}-\d{5}$/

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
  const [users, setUsers] = useState([])
  const [transactions, setTransactions] = useState([])
  const [configItems, setConfigItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [editingStock, setEditingStock] = useState(null)
  const [newStock, setNewStock] = useState({ symbol: '', name: '', price: '', change: '0', changePercent: '0' })
  const [newConfig, setNewConfig] = useState({ key: '', value: '' })
  const [message, setMessage] = useState(null)

  // Состояние для редактирования пользователя
  const [editingUser, setEditingUser] = useState(null)
  const [editForm, setEditForm] = useState({
    username: '',
    balance: '',
    role: 'user',
    card_number: '',
  })
  const [editErrors, setEditErrors] = useState({})

  useEffect(() => {
    loadData()
  }, [activeSection])

  const loadData = async () => {
    setLoading(true)
    try {
      if (activeSection === 'stocks') {
        const data = await fetchStocks()
        setStocks(data)
      } else if (activeSection === 'users') {
        const data = await request('/api/admin/users')
        setUsers(data)
      } else if (activeSection === 'transactions') {
        const data = await request('/api/admin/transactions')
        setTransactions(data)
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
      showMessage(t('admin.loadError') + ': ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const showMessage = (text) => {
    setMessage(text)
    setTimeout(() => setMessage(null), 3000)
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
    })
    setEditErrors({})
  }

  const handleSaveUser = async () => {
    if (!validateEditForm()) return

    const payload = {
      username: editForm.username.trim(),
      balance: parseFloat(editForm.balance),
      role: editForm.role,
    }

    // Добавляем card_number только если заполнен
    if (editForm.card_number.trim()) {
      payload.card_number = editForm.card_number.trim()
    }

    try {
      await adminUpdateUser(editingUser, payload)
      setEditingUser(null)
      showMessage(t('admin.userUpdated'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleDeleteUser = async (userId, username) => {
    if (!confirm(t('admin.deleteUserConfirm', { username }))) return
    try {
      await adminDeleteUser(userId)
      showMessage(t('admin.userDeleted', { username }))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  // ── Обработчики акций ──────────────────────────────────────────────────────

  const handleAddStock = async () => {
    if (!newStock.symbol || !newStock.name || !newStock.price) {
      showMessage(t('admin.fillAllFields'))
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
      showMessage(t('admin.stockAdded'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
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
      showMessage(t('admin.stockUpdated'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleDeleteStock = async (symbol) => {
    if (!confirm(t('admin.deleteStockConfirm', { symbol }))) return
    try {
      await request(`/api/stocks/${symbol}`, { method: 'DELETE' })
      showMessage(t('admin.stockDeleted', { symbol }))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleDeleteTransaction = async (txId) => {
    if (!confirm(t('admin.deleteTransactionConfirm'))) return
    try {
      await request(`/api/admin/transactions/${txId}`, { method: 'DELETE' })
      showMessage(t('admin.transactionDeleted'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const handleSaveConfig = async () => {
    if (!newConfig.key || !newConfig.value) {
      showMessage(t('admin.fillKeyAndValue'))
      return
    }
    try {
      await request('/api/config', {
        method: 'POST',
        body: JSON.stringify({ key: newConfig.key, value: newConfig.value }),
      })
      setNewConfig({ key: '', value: '' })
      showMessage(t('admin.configUpdated'))
      loadData()
    } catch (err) {
      showMessage(t('admin.error') + ': ' + err.message)
    }
  }

  const sections = [
    { id: 'stocks', label: t('admin.stocks'), icon: Package },
    { id: 'users', label: t('admin.users'), icon: Users },
    { id: 'transactions', label: t('admin.transactions'), icon: ArrowLeftRight },
    { id: 'config', label: t('admin.config'), icon: Settings },
  ]

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <h2>{t('admin.title')}</h2>
        <button className="admin-close-btn" onClick={onClose}>
          <X size={20} />
        </button>
      </div>

      {message && <div className="admin-message">{message}</div>}

      <div className="admin-tabs">
        {sections.map(s => (
          <button
            key={s.id}
            className={`admin-tab ${activeSection === s.id ? 'active' : ''}`}
            onClick={() => setActiveSection(s.id)}
          >
            <s.icon size={16} />
            {s.label}
          </button>
        ))}
      </div>

      <div className="admin-content">
        {loading && <div className="loading-state"><div className="spinner" /><p>{t('common.loading')}</p></div>}

        {!loading && activeSection === 'stocks' && (
          <div>
            <div className="admin-add-form">
              <h3>{t('admin.addStock')}</h3>
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

            <div className="admin-list">
              {stocks.map(stock => (
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
                        <span className="stock-price">${stock.price?.toFixed(2)}</span>
                      </div>
                      <div className="stock-actions">
                        <button className="admin-btn" onClick={() => setEditingStock({ ...stock })}>
                          <Edit3 size={14} />
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

        {!loading && activeSection === 'users' && (
          <div className="admin-list">
            {users.map(u => (
              <div key={u.id} className="admin-user-item">
                {editingUser === u.id ? (
                  <div className="admin-user-edit-form">
                    <div className="admin-user-edit-header">
                      <strong>{t('admin.editUser')}: {u.username}</strong>
                      <span className="user-id-label">ID: {u.id}</span>
                    </div>
                    <div className="admin-user-edit-fields">
                      <div className="admin-field-group">
                        <label>{t('admin.fieldUsername')}</label>
                        <input
                          type="text"
                          value={editForm.username}
                          onChange={e => setEditForm({ ...editForm, username: e.target.value })}
                          className={`admin-input${editErrors.username ? ' admin-input-error' : ''}`}
                        />
                        {editErrors.username && <span className="admin-field-error">{editErrors.username}</span>}
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.fieldBalance')}</label>
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={editForm.balance}
                          onChange={e => setEditForm({ ...editForm, balance: e.target.value })}
                          className={`admin-input${editErrors.balance ? ' admin-input-error' : ''}`}
                        />
                        {editErrors.balance && <span className="admin-field-error">{editErrors.balance}</span>}
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.fieldRole')}</label>
                        <select
                          value={editForm.role}
                          onChange={e => setEditForm({ ...editForm, role: e.target.value })}
                          className={`admin-input${editErrors.role ? ' admin-input-error' : ''}`}
                        >
                          <option value="user">user</option>
                          <option value="admin">admin</option>
                        </select>
                        {editErrors.role && <span className="admin-field-error">{editErrors.role}</span>}
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.fieldCardNumber')}</label>
                        <input
                          type="text"
                          value={editForm.card_number}
                          onChange={e => setEditForm({ ...editForm, card_number: e.target.value })}
                          className={`admin-input${editErrors.card_number ? ' admin-input-error' : ''}`}
                          placeholder="XXXX-XXXX-XXXX-XXXXX"
                          maxLength={20}
                        />
                        {editErrors.card_number && <span className="admin-field-error">{editErrors.card_number}</span>}
                      </div>
                    </div>
                    <div className="admin-user-edit-actions">
                      <button className="admin-btn admin-btn-primary" onClick={handleSaveUser}>
                        <Save size={14} /> {t('admin.save')}
                      </button>
                      <button className="admin-btn" onClick={handleCancelEditUser}>
                        <X size={14} /> {t('admin.cancel')}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="admin-user-info">
                      <div>
                        <strong>{u.username}</strong>
                        <span className={`user-role ${u.role || 'user'}`}>{u.role || 'user'}</span>
                      </div>
                      <div className="admin-user-meta">
                        <span className="user-balance">${u.balance != null ? u.balance.toFixed(2) : '0.00'}</span>
                        <span className="user-date">{u.created_at}</span>
                      </div>
                    </div>
                    <div className="user-actions">
                      <button className="admin-btn" onClick={() => handleStartEditUser(u)}>
                        <Edit3 size={14} />
                      </button>
                      <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteUser(u.id, u.username)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
            {users.length === 0 && <p className="empty-state">{t('admin.noUsers')}</p>}
          </div>
        )}

        {!loading && activeSection === 'transactions' && (
          <div className="admin-list">
            {transactions.map(tx => (
              <div key={tx.id} className="admin-tx-item">
                <div>
                  <span className={`tx-type ${tx.type}`}>{tx.type}</span>
                  <strong>{tx.symbol}</strong>
                  <span>{tx.amount} × ${tx.price}</span>
                </div>
                <div className="tx-right">
                  <span>{tx.timestamp}</span>
                  <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteTransaction(tx.id)}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
            {transactions.length === 0 && <p className="empty-state">{t('admin.noTransactions')}</p>}
          </div>
        )}

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
  )
}

export default AdminPanel
