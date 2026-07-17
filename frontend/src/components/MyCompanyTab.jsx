import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCompany, createCompany, inviteEmployee, updateMemberSalary,
  fireMember, collectCompanyProfit, companyDeposit, companyWithdraw,
  fetchCompanies, applyToCompany, updateCompanySettings, disbandCompany, leaveCompany,
  updateOwnerSalary, companyIpo, companyDividend,
  companyRecallStock, companyIssueCrypto, companyRecallCrypto,
} from '../services/api'
import TransactionsPanel, { formatMoney, formatCompact } from './TransactionsPanel'
import CompanyAssetsPanel from './CompanyAssetsPanel'
import ConfirmDialog from './ConfirmDialog'
import {
  Store, Users, TrendingUp, Wallet, HandCoins, ArrowDownToLine,
  ArrowUpFromLine, UserPlus, Trash2, Check, X, AlertTriangle, Building2, Package,
  Search, LogIn, ChevronRight, Settings, Eye, EyeOff, Unlock, Lock, LineChart, Coins, Upload,
} from 'lucide-react'

const LOGO_EMOJI = ['🏢', '🏦', '🏭', '🚀', '💎', '⚙️', '🛰️', '🏗️', '💼', '🌐', '⚡', '🔧']

// Сжимает выбранный логотип до квадрата LOGO_SIZE×LOGO_SIZE (cover-crop) и
// отдаёт data URL — так же, как аватар профиля (см. SettingsPage). Хранится
// прямо в поле companies.logo, без файлового хранилища.
const LOGO_SIZE = 256
const LOGO_QUALITY = 0.85

function readAndResizeImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('read-failed'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('decode-failed'))
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = LOGO_SIZE
        canvas.height = LOGO_SIZE
        const ctx = canvas.getContext('2d')
        const scale = Math.max(LOGO_SIZE / img.width, LOGO_SIZE / img.height)
        const w = img.width * scale
        const h = img.height * scale
        ctx.drawImage(img, (LOGO_SIZE - w) / 2, (LOGO_SIZE - h) / 2, w, h)
        resolve(canvas.toDataURL('image/jpeg', LOGO_QUALITY))
      }
      img.src = reader.result
    }
    reader.readAsDataURL(file)
  })
}

function MyCompanyTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [roles, setRoles] = useState([])
  const [foundingFee, setFoundingFee] = useState(10000)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const [newName, setNewName] = useState('')
  const [companies, setCompanies] = useState([])
  const [companySearch, setCompanySearch] = useState('')
  const [invite, setInvite] = useState({ username: '', role: 'worker', salary: '' })
  const [editing, setEditing] = useState(null)      // { userId, salary }
  const [moneyModal, setMoneyModal] = useState(null) // 'deposit' | 'withdraw'
  const [moneyAmount, setMoneyAmount] = useState('')
  const [showAssets, setShowAssets] = useState(false)
  const [settingsModal, setSettingsModal] = useState(null) // { name, description, logo, isOpen, visibleInSearch }
  const [confirmDisband, setConfirmDisband] = useState(false)
  const [confirmLeave, setConfirmLeave] = useState(false)
  const [ipoModal, setIpoModal] = useState(null)   // { symbol, totalShares }
  const [dividendModal, setDividendModal] = useState(null) // { perShare }
  const [cryptoModal, setCryptoModal] = useState(null)     // { symbol, supply, name }
  const [confirmRecall, setConfirmRecall] = useState(null) // 'stock' | 'crypto'
  const logoFileRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const res = await fetchCompany()
      setData(res.company)
      setRoles(res.roles || [])
      if (res.foundingFee != null) setFoundingFee(res.foundingFee)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Realtime: обновляем компанию (сотрудники/бюджет) при событиях от WebSocket —
  // например когда приглашённый игрок принял приглашение (владелец видит live).
  useEffect(() => {
    const onCompany = () => load()
    const onRealtime = (ev) => {
      const d = ev.detail
      if (d?.type === 'notification' && ['company', 'company_invite', 'company_application'].includes(d.notification?.type)) {
        load()
      }
    }
    window.addEventListener('tv:company-refresh', onCompany)
    window.addEventListener('tv:realtime', onRealtime)
    return () => {
      window.removeEventListener('tv:company-refresh', onCompany)
      window.removeEventListener('tv:realtime', onRealtime)
    }
  }, [load])

  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 2600)
  }

  const run = async (fn, okKey, after) => {
    setBusy(true)
    try {
      const res = await fn()
      if (res?.balance != null) onBalanceChange?.(res.balance)
      if (res?.company !== undefined) setData(res.company)
      if (okKey) flash(t(okKey))
      setRefreshKey(k => k + 1)
      after?.(res)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const loadCompanies = useCallback(async () => {
    try { setCompanies(await fetchCompanies(companySearch || undefined)) } catch { /* ignore */ }
  }, [companySearch])

  useEffect(() => {
    if (data) return
    const id = setTimeout(loadCompanies, 300)
    return () => clearTimeout(id)
  }, [loadCompanies, data])

  const doApply = async (id) => {
    try {
      await applyToCompany(id)
      flash(t('company.applied'))
      await loadCompanies()
    } catch (err) {
      flash(err.message, 'error')
    }
  }

  const openSettings = () => setSettingsModal({
    name: data.name,
    description: data.description || '',
    logo: data.logo || '',
    isOpen: data.isOpen !== false,
    visibleInSearch: data.visibleInSearch !== false,
  })

  const onLogoFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''   // позволяем выбрать тот же файл повторно
    if (!file) return
    if (!file.type.startsWith('image/')) { flash(t('settings.avatarInvalid'), 'error'); return }
    try {
      const dataUrl = await readAndResizeImage(file)
      setSettingsModal(m => m && { ...m, logo: dataUrl })
    } catch {
      flash(t('settings.avatarInvalid'), 'error')
    }
  }

  const saveSettings = async () => {
    setBusy(true)
    try {
      const res = await updateCompanySettings({
        name: settingsModal.name.trim(),
        description: settingsModal.description.trim(),
        logo: settingsModal.logo.trim(),
        isOpen: settingsModal.isOpen,
        visibleInSearch: settingsModal.visibleInSearch,
      })
      if (res?.company) setData(res.company)
      flash(t('company.settingsSaved'))
      setSettingsModal(null)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doDisband = async () => {
    setBusy(true)
    try {
      await disbandCompany()
      setConfirmDisband(false)
      setSettingsModal(null)
      setData(null)
      flash(t('company.disbanded'))
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doLeave = async () => {
    setBusy(true)
    try {
      await leaveCompany()
      setConfirmLeave(false)
      setData(null)
      flash(t('company.left'))
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doIpo = async () => {
    const totalShares = Math.floor(Number(ipoModal.totalShares))
    if (!ipoModal.symbol.trim() || !(totalShares >= 1000)) {
      flash(t('company.ipo.invalid'), 'error'); return
    }
    setBusy(true)
    try {
      const res = await companyIpo({ symbol: ipoModal.symbol.trim().toUpperCase(), totalShares })
      if (res?.company) setData(res.company)
      flash(t('company.ipo.placed', { symbol: res.symbol, price: formatMoney(res.price) }))
      setIpoModal(null)
      setRefreshKey(k => k + 1)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doDividend = async () => {
    const per = Number(dividendModal.perShare)
    if (!(per > 0)) { flash(t('company.ipo.dividendInvalid'), 'error'); return }
    setBusy(true)
    try {
      const res = await companyDividend(per)
      if (res?.company) setData(res.company)
      flash(t('company.ipo.dividendPaid', { total: formatMoney(res.paid), holders: res.holders }))
      setDividendModal(null)
      setRefreshKey(k => k + 1)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doIssueCrypto = async () => {
    const supply = Math.floor(Number(cryptoModal.supply))
    if (!cryptoModal.symbol.trim() || !(supply >= 10000)) {
      flash(t('company.crypto.invalid'), 'error'); return
    }
    setBusy(true)
    try {
      const res = await companyIssueCrypto({
        symbol: cryptoModal.symbol.trim().toUpperCase(), supply,
        name: cryptoModal.name.trim() || undefined,
      })
      if (res?.company) setData(res.company)
      flash(t('company.crypto.issued', { symbol: res.symbol, price: formatMoney(res.price) }))
      setCryptoModal(null)
      setRefreshKey(k => k + 1)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doRecall = async () => {
    const kind = confirmRecall
    setBusy(true)
    try {
      const res = kind === 'crypto' ? await companyRecallCrypto() : await companyRecallStock()
      if (res?.company) setData(res.company)
      flash(t(kind === 'crypto' ? 'company.crypto.recalled' : 'company.ipo.recalled'))
      setConfirmRecall(null)
      setRefreshKey(k => k + 1)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="company-tab">
        <h2 className="tab-title">{t('nav.mycompany')}</h2>
        <div className="asset-card skeleton" style={{ height: 200 }} />
      </div>
    )
  }

  // ── Нет компании ──
  if (!data) {
    return (
      <div className="company-tab">
        <h2 className="tab-title">{t('nav.mycompany')}</h2>
        <div className="crypto-onboard">
          <div className="crypto-onboard-icon"><Building2 size={56} /></div>
          <h3>{t('company.createTitle')}</h3>
          <p>{t('company.createDesc', { fee: formatMoney(foundingFee) })}</p>
          {msg && (
            <div className={`transfer-feedback ${msg.type}`}><AlertTriangle size={16} /><span>{msg.text}</span></div>
          )}
          <input
            className="company-name-input"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder={t('company.namePlaceholder')}
            maxLength={40}
          />
          <button
            className="crypto-open-btn"
            disabled={busy || newName.trim().length < 2}
            onClick={() => run(() => createCompany(newName.trim()), 'company.created')}
          >
            <Store size={18} /> {busy ? t('bank.processing') : t('company.create')}
          </button>
        </div>

        <div className="company-browse">
          <div className="company-browse-head">
            <h3><Building2 size={16} /> {t('company.browseTitle')}</h3>
            <div className="tx-search">
              <Search size={16} className="tx-search-icon" />
              <input value={companySearch} onChange={e => setCompanySearch(e.target.value)} placeholder={t('company.searchPlaceholder')} />
            </div>
          </div>
          {companies.length === 0 ? (
            <p className="empty-state">{t('company.noCompanies')}</p>
          ) : (
            <div className="company-browse-list">
              {companies.map(c => (
                <div key={c.id} className="company-browse-item">
                  <div className="cbi-info">
                    <span className="cbi-name">{c.name}</span>
                    <span className="cbi-meta">{c.ownerName} · 👥 {c.memberCount} · ${formatCompact(c.capital)}</span>
                  </div>
                  <button className="asset-act upgrade" disabled={c.isMine || c.applied} onClick={() => doApply(c.id)}>
                    <LogIn size={14} /> {c.applied ? t('company.applicationSent') : t('company.apply')}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Есть компания ──
  return (
    <div className="company-tab">
      <div className="leaderboard-title-row company-title-row">
        <span className="company-logo-badge">
          {data.logo
            ? (/^(https?:\/\/|data:image\/)/.test(data.logo)
                ? <img src={data.logo} alt="" className="company-logo-img" />
                : <span className="company-logo-emoji">{data.logo}</span>)
            : <Store size={22} className="icon" />}
        </span>
        <h2 className="tab-title">{data.name}</h2>
        {!data.isOwner && data.viewerRole && (
          <span className="company-role-badge">{t('company.yourRole')}: {t(`company.roles.${data.viewerRole}`, data.viewerRole)}</span>
        )}
        {data.isOwner ? (
          <button className="company-settings-btn" onClick={openSettings} title={t('company.settings')}>
            <Settings size={18} />
          </button>
        ) : (
          <button className="company-disband-btn compact" disabled={busy} onClick={() => setConfirmLeave(true)}>
            <LogIn size={15} /> {t('company.leave')}
          </button>
        )}
      </div>
      {data.description && <p className="company-description">{data.description}</p>}

      {data.reputationFactor != null && data.reputationFactor < 1 && (
        <div className="transfer-feedback error" style={{ marginBottom: 'var(--spacing-md)' }}>
          <AlertTriangle size={16} />
          <span>{t('company.reputationCrisis', { pct: Math.round((1 - data.reputationFactor) * 100) })}</span>
        </div>
      )}
      {data.reputationFactor != null && data.reputationFactor > 1 && (
        <div className="transfer-feedback success" style={{ marginBottom: 'var(--spacing-md)' }}>
          <Check size={16} />
          <span>{t('company.reputationBoost', { pct: Math.round((data.reputationFactor - 1) * 100) })}</span>
        </div>
      )}

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <div className="asset-summary">
        <div className="asset-summary-card"><span><Wallet size={12} /> {t('company.budget')}</span><b>${formatMoney(data.budget)}</b></div>
        <div className="asset-summary-card"><span><TrendingUp size={12} /> {t('company.revenue')}</span><b className="up">${formatMoney(data.revenuePerHour)}{t('units.perHour')}</b></div>
        <div className="asset-summary-card"><span>{t('company.payroll')}</span><b className="down">${formatMoney(data.payrollPerHour)}{t('units.perHour')}</b></div>
        <div className="asset-summary-card"><span>{t('company.profit')}</span><b className={data.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(data.profitPerHour)}{t('units.perHour')}</b></div>
      </div>

      <p className="company-note">{t('company.incomeNote')}</p>

      {data.isOwner && (
        <div className="company-actions">
          <button className="asset-act collect" disabled={busy || data.accrued <= 0}
            onClick={() => run(collectCompanyProfit, 'company.collected')}>
            <HandCoins size={15} /> {t('company.collect')} (${formatMoney(data.accrued)})
          </button>
          <button className="asset-act" disabled={busy} onClick={() => { setMoneyModal('deposit'); setMoneyAmount('') }}>
            <ArrowDownToLine size={15} /> {t('company.deposit')}
          </button>
          <button className="asset-act upgrade" disabled={busy} onClick={() => { setMoneyModal('withdraw'); setMoneyAmount('') }}>
            <ArrowUpFromLine size={15} /> {t('company.withdraw')}
          </button>
        </div>
      )}

      {/* Активы компании — видят все сотрудники (интерфейс как «Моё имущество»);
          управлять арендой (внутри панели) может только владелец. */}
      <button className="company-assets-card" onClick={() => setShowAssets(true)}>
        <span className="cac-icon"><Package size={22} /></span>
        <div className="cac-info">
          <span className="cac-title">{t('company.assets')}</span>
          <span className="cac-meta">
            {data.assetCount} · +${formatMoney(data.assets.reduce((s, a) => s + (a.profitPerHour || 0), 0))}{t('units.perHour')}
          </span>
        </div>
        <ChevronRight size={20} className="cac-chevron" />
      </button>

      {showAssets && (
        <CompanyAssetsPanel
          assets={data.assets}
          isOwner={data.isOwner}
          onBalanceChange={onBalanceChange}
          onClose={() => setShowAssets(false)}
          onRefresh={async () => { await load(); setRefreshKey(k => k + 1) }}
        />
      )}

      {/* Акции компании — IPO и дивиденды (только владелец управляет) */}
      <div className="company-section">
        <h3><LineChart size={16} /> {t('company.ipo.title')}</h3>
        {data.stock ? (
          <div className="company-stock-card">
            <div className="csc-row">
              <span className="csc-symbol">{data.stock.symbol}</span>
              <span className={`csc-price ${data.stock.changePercent >= 0 ? 'up' : 'down'}`}>
                ${formatMoney(data.stock.price)}
                {data.stock.changePercent != null && ` (${data.stock.changePercent >= 0 ? '+' : ''}${data.stock.changePercent}%)`}
              </span>
            </div>
            <div className="csc-meta">
              <span>{t('company.ipo.marketCap')}: ${formatCompact(data.stock.marketCap)}</span>
              <span>{t('company.ipo.freeShares')}: {formatCompact(data.stock.freeShares)}</span>
            </div>
            {data.isOwner && (
              <div className="csc-actions">
                <button className="asset-act upgrade" disabled={busy}
                  onClick={() => setDividendModal({ perShare: '' })}>
                  <Coins size={14} /> {t('company.ipo.payDividend')}
                </button>
                <button className="asset-act danger" disabled={busy}
                  onClick={() => setConfirmRecall('stock')}>
                  <Trash2 size={14} /> {t('company.ipo.recall')}
                </button>
              </div>
            )}
          </div>
        ) : data.isOwner ? (
          <div className="company-stock-empty">
            <p className="company-note">{t('company.ipo.desc')}</p>
            <button className="asset-act upgrade" disabled={busy}
              onClick={() => setIpoModal({ symbol: '', totalShares: '1000000' })}>
              <TrendingUp size={14} /> {t('company.ipo.place')}
            </button>
          </div>
        ) : (
          <p className="empty-state">{t('company.ipo.none')}</p>
        )}
      </div>

      {/* Криптовалюта компании — эмиссия и отзыв (только владелец управляет) */}
      <div className="company-section">
        <h3><Coins size={16} /> {t('company.crypto.title')}</h3>
        {data.crypto ? (
          <div className="company-stock-card">
            <div className="csc-row">
              <span className="csc-symbol">{data.crypto.symbol}</span>
              <span className={`csc-price ${data.crypto.change24h >= 0 ? 'up' : 'down'}`}>
                ${formatMoney(data.crypto.price)}
                {data.crypto.change24h != null && ` (${data.crypto.change24h >= 0 ? '+' : ''}${data.crypto.change24h}%)`}
              </span>
            </div>
            <div className="csc-meta">
              <span>{t('company.ipo.marketCap')}: ${formatCompact(data.crypto.marketCap)}</span>
              <span>{t('company.crypto.supply')}: {formatCompact(data.crypto.supply)}</span>
            </div>
            {data.isOwner && (
              <div className="csc-actions">
                <button className="asset-act danger" disabled={busy}
                  onClick={() => setConfirmRecall('crypto')}>
                  <Trash2 size={14} /> {t('company.crypto.recall')}
                </button>
              </div>
            )}
          </div>
        ) : data.isOwner ? (
          <div className="company-stock-empty">
            <p className="company-note">{t('company.crypto.desc')}</p>
            <button className="asset-act upgrade" disabled={busy}
              onClick={() => setCryptoModal({ symbol: '', supply: '10000000', name: '' })}>
              <Coins size={14} /> {t('company.crypto.issue')}
            </button>
          </div>
        ) : (
          <p className="empty-state">{t('company.crypto.none')}</p>
        )}
      </div>

      {/* Сотрудники (по приглашению) */}
      <div className="company-section">
        <h3><Users size={16} /> {t('company.employees')} ({data.memberCount})</h3>

        {data.isOwner && (
          <div className="company-hire">
            <input placeholder={t('company.invitePlayer')} value={invite.username}
              onChange={e => setInvite({ ...invite, username: e.target.value })} />
            <select value={invite.role} onChange={e => setInvite({ ...invite, role: e.target.value })}>
              {roles.map(r => <option key={r} value={r}>{t(`company.roles.${r}`, r)}</option>)}
            </select>
            <input type="number" min="1" placeholder={t('company.salary')} value={invite.salary}
              onChange={e => setInvite({ ...invite, salary: e.target.value })} />
            <button className="asset-act upgrade" disabled={busy || !invite.username.trim() || !(Number(invite.salary) > 0)}
              onClick={() => run(
                () => inviteEmployee({ username: invite.username.trim(), role: invite.role, salary: Number(invite.salary) }),
                'company.invited',
                () => setInvite({ username: '', role: 'worker', salary: '' }),
              )}>
              <UserPlus size={15} /> {t('company.invite')}
            </button>
          </div>
        )}

        {data.members.length === 0 ? (
          <p className="empty-state">{t('company.noEmployees')}</p>
        ) : (
          <div className="company-emp-list">
            {data.members.map(m => (
              <div key={m.userId} className="company-emp">
                <div className="company-emp-info">
                  {m.avatar ? (
                    <img className="company-emp-avatar company-emp-avatar-img" src={m.avatar} alt={m.username} />
                  ) : (
                    <span className="company-emp-avatar">{(m.username || '?').slice(0, 2).toUpperCase()}</span>
                  )}
                  <div className="company-emp-text">
                    <span className="company-emp-name">{m.username}</span>
                    <span className="company-emp-role">{t(`company.roles.${m.role}`, m.role)}</span>
                  </div>
                </div>
                {m.role === 'owner' ? (
                  !data.isOwner ? (
                    <span className="company-emp-salary">${formatMoney(m.salary || 0)}{t('units.perHour')}</span>
                  ) : editing?.userId === m.userId ? (
                    <div className="company-emp-edit">
                      <input type="number" min="0" value={editing.salary}
                        onChange={ev => setEditing({ ...editing, salary: ev.target.value })} />
                      <button className="asset-act collect" disabled={busy}
                        onClick={() => run(() => updateOwnerSalary(Number(editing.salary)), 'company.salaryUpdated', () => setEditing(null))}>
                        <Check size={14} />
                      </button>
                      <button className="asset-act" onClick={() => setEditing(null)}><X size={14} /></button>
                    </div>
                  ) : (
                    <div className="company-emp-actions">
                      <span className="company-emp-salary">${formatMoney(m.salary || 0)}{t('units.perHour')}</span>
                      <button className="asset-act" onClick={() => setEditing({ userId: m.userId, salary: String(m.salary || 0) })}>{t('company.editSalary')}</button>
                    </div>
                  )
                ) : !data.isOwner ? (
                  <span className="company-emp-salary">${formatMoney(m.salary)}{t('units.perHour')}</span>
                ) : editing?.userId === m.userId ? (
                  <div className="company-emp-edit">
                    <input type="number" min="1" value={editing.salary}
                      onChange={ev => setEditing({ ...editing, salary: ev.target.value })} />
                    <button className="asset-act collect" disabled={busy}
                      onClick={() => run(() => updateMemberSalary(m.userId, Number(editing.salary)), 'company.salaryUpdated', () => setEditing(null))}>
                      <Check size={14} />
                    </button>
                    <button className="asset-act" onClick={() => setEditing(null)}><X size={14} /></button>
                  </div>
                ) : (
                  <div className="company-emp-actions">
                    <span className="company-emp-salary">${formatMoney(m.salary)}{t('units.perHour')}</span>
                    <button className="asset-act" onClick={() => setEditing({ userId: m.userId, salary: String(m.salary) })}>{t('company.editSalary')}</button>
                    <button className="asset-act sell" disabled={busy}
                      onClick={() => run(() => fireMember(m.userId), 'company.fired')}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="company-section">
        <h3>{t('bank.history')}</h3>
        <TransactionsPanel category="company" companyId={data.id} refreshKey={refreshKey} />
      </div>

      {moneyModal && (
        <div className="modal-overlay" onClick={() => !busy && setMoneyModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setMoneyModal(null)}><X size={18} /></button>
            <h3>{moneyModal === 'deposit' ? t('company.deposit') : t('company.withdraw')}</h3>
            <p className="modal-price">
              {moneyModal === 'deposit'
                ? `${t('bank.currentBalance')}: $${formatMoney(balance)}`
                : `${t('company.budget')}: $${formatMoney(data.budget)}`}
            </p>
            <div className="modal-quantity">
              <label>{t('bank.amount')}:</label>
              <input type="number" min="1" step="any" value={moneyAmount} autoFocus
                onChange={e => setMoneyAmount(e.target.value)} />
            </div>
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy || !(Number(moneyAmount) > 0)}
                onClick={() => run(
                  () => (moneyModal === 'deposit' ? companyDeposit(Number(moneyAmount)) : companyWithdraw(Number(moneyAmount))),
                  moneyModal === 'deposit' ? 'company.deposited' : 'company.withdrawn',
                  () => setMoneyModal(null),
                )}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setMoneyModal(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {ipoModal && (
        <div className="modal-overlay" onClick={() => !busy && setIpoModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setIpoModal(null)} disabled={busy}><X size={18} /></button>
            <h3><TrendingUp size={18} /> {t('company.ipo.place')}</h3>
            <p className="modal-price">{t('company.ipo.priceNote')}</p>
            <label className="settings-label">{t('company.ipo.ticker')}</label>
            <input className="company-name-input" maxLength={6} value={ipoModal.symbol}
              placeholder="ABCD"
              onChange={e => setIpoModal({ ...ipoModal, symbol: e.target.value.toUpperCase() })} />
            <label className="settings-label">{t('company.ipo.shares')}</label>
            <input className="company-name-input" type="number" min="1000" step="1000" value={ipoModal.totalShares}
              onChange={e => setIpoModal({ ...ipoModal, totalShares: e.target.value })} />
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy || !ipoModal.symbol.trim() || !(Number(ipoModal.totalShares) >= 1000)}
                onClick={doIpo}>
                {busy ? t('bank.processing') : t('company.ipo.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setIpoModal(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {dividendModal && (
        <div className="modal-overlay" onClick={() => !busy && setDividendModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setDividendModal(null)} disabled={busy}><X size={18} /></button>
            <h3><Coins size={18} /> {t('company.ipo.payDividend')}</h3>
            <p className="modal-price">{t('company.ipo.dividendNote')}</p>
            <div className="modal-quantity">
              <label>{t('company.ipo.perShare')}:</label>
              <input type="number" min="0" step="any" value={dividendModal.perShare} autoFocus
                onChange={e => setDividendModal({ perShare: e.target.value })} />
            </div>
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy || !(Number(dividendModal.perShare) > 0)}
                onClick={doDividend}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setDividendModal(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {cryptoModal && (
        <div className="modal-overlay" onClick={() => !busy && setCryptoModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setCryptoModal(null)} disabled={busy}><X size={18} /></button>
            <h3><Coins size={18} /> {t('company.crypto.issue')}</h3>
            <p className="modal-price">{t('company.crypto.priceNote')}</p>
            <label className="settings-label">{t('company.ipo.ticker')}</label>
            <input className="company-name-input" maxLength={6} value={cryptoModal.symbol}
              placeholder="COIN"
              onChange={e => setCryptoModal({ ...cryptoModal, symbol: e.target.value.toUpperCase() })} />
            <label className="settings-label">{t('company.crypto.nameLabel')}</label>
            <input className="company-name-input" maxLength={40} value={cryptoModal.name}
              placeholder={t('company.crypto.namePlaceholder')}
              onChange={e => setCryptoModal({ ...cryptoModal, name: e.target.value })} />
            <label className="settings-label">{t('company.crypto.supply')}</label>
            <input className="company-name-input" type="number" min="10000" step="10000" value={cryptoModal.supply}
              onChange={e => setCryptoModal({ ...cryptoModal, supply: e.target.value })} />
            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy || !cryptoModal.symbol.trim() || !(Number(cryptoModal.supply) >= 10000)}
                onClick={doIssueCrypto}>
                {busy ? t('bank.processing') : t('company.crypto.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setCryptoModal(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {settingsModal && (
        <div className="modal-overlay" onClick={() => !busy && setSettingsModal(null)}>
          <div className="modal-content company-settings-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setSettingsModal(null)} disabled={busy}><X size={18} /></button>
            <h3><Settings size={18} /> {t('company.settings')}</h3>

            <label className="settings-label">{t('company.namePlaceholder')}</label>
            <input className="company-name-input" maxLength={40} value={settingsModal.name}
              onChange={e => setSettingsModal({ ...settingsModal, name: e.target.value })} />

            <label className="settings-label">{t('company.descriptionLabel')}</label>
            <textarea className="company-desc-input" maxLength={200} rows={3} value={settingsModal.description}
              placeholder={t('company.descriptionPlaceholder')}
              onChange={e => setSettingsModal({ ...settingsModal, description: e.target.value })} />

            <label className="settings-label">{t('company.logoLabel')}</label>
            <div className="logo-emoji-row">
              {LOGO_EMOJI.map(em => (
                <button key={em} type="button"
                  className={`logo-emoji-btn ${settingsModal.logo === em ? 'active' : ''}`}
                  onClick={() => setSettingsModal({ ...settingsModal, logo: em })}>{em}</button>
              ))}
            </div>
            <div className="company-logo-upload">
              {/^data:image\//.test(settingsModal.logo) && (
                <img src={settingsModal.logo} alt="" className="company-logo-preview" />
              )}
              <input ref={logoFileRef} type="file" accept="image/*" hidden onChange={onLogoFile} />
              <button type="button" className="stock-btn" disabled={busy}
                onClick={() => logoFileRef.current?.click()}>
                <Upload size={15} /> {t('company.logoUpload')}
              </button>
              {/^data:image\//.test(settingsModal.logo) && (
                <button type="button" className="stock-btn cancel-btn" disabled={busy}
                  onClick={() => setSettingsModal({ ...settingsModal, logo: '' })}>
                  <Trash2 size={15} /> {t('common.delete')}
                </button>
              )}
            </div>

            <div className="settings-toggles">
              <button type="button" className={`settings-toggle ${settingsModal.isOpen ? 'on' : ''}`}
                onClick={() => setSettingsModal({ ...settingsModal, isOpen: !settingsModal.isOpen })}>
                {settingsModal.isOpen ? <Unlock size={15} /> : <Lock size={15} />}
                {settingsModal.isOpen ? t('company.open') : t('company.closed')}
              </button>
              <button type="button" className={`settings-toggle ${settingsModal.visibleInSearch ? 'on' : ''}`}
                onClick={() => setSettingsModal({ ...settingsModal, visibleInSearch: !settingsModal.visibleInSearch })}>
                {settingsModal.visibleInSearch ? <Eye size={15} /> : <EyeOff size={15} />}
                {settingsModal.visibleInSearch ? t('company.visible') : t('company.hidden')}
              </button>
            </div>

            <div className="modal-buttons">
              <button className="stock-btn buy-btn" disabled={busy || settingsModal.name.trim().length < 2} onClick={saveSettings}>
                {busy ? t('bank.processing') : t('common.save')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setSettingsModal(null)} disabled={busy}>
                {t('common.cancel')}
              </button>
            </div>

            <button className="company-disband-btn" disabled={busy} onClick={() => setConfirmDisband(true)}>
              <AlertTriangle size={15} /> {t('company.disband')}
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmDisband}
        danger
        busy={busy}
        title={t('company.disband')}
        message={t('company.disbandConfirm')}
        confirmLabel={t('common.yes')}
        cancelLabel={t('common.no')}
        onConfirm={doDisband}
        onCancel={() => setConfirmDisband(false)}
      />

      <ConfirmDialog
        open={confirmLeave}
        danger
        busy={busy}
        title={t('company.leave')}
        message={t('company.leaveConfirm')}
        confirmLabel={t('common.yes')}
        cancelLabel={t('common.no')}
        onConfirm={doLeave}
        onCancel={() => setConfirmLeave(false)}
      />

      <ConfirmDialog
        open={!!confirmRecall}
        danger
        busy={busy}
        title={t(confirmRecall === 'crypto' ? 'company.crypto.recall' : 'company.ipo.recall')}
        message={t(confirmRecall === 'crypto' ? 'company.crypto.recallConfirm' : 'company.ipo.recallConfirm')}
        confirmLabel={t('common.yes')}
        cancelLabel={t('common.no')}
        onConfirm={doRecall}
        onCancel={() => setConfirmRecall(null)}
      />
    </div>
  )
}

export default MyCompanyTab
