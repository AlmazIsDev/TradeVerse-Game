import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCompany, createCompany, inviteEmployee, updateMemberSalary,
  fireMember, collectCompanyProfit, companyDeposit, companyWithdraw,
  fetchCompanies, applyToCompany, updateCompanySettings, disbandCompany, leaveCompany,
} from '../services/api'
import TransactionsPanel, { formatMoney, formatCompact } from './TransactionsPanel'
import CompanyAssetsPanel from './CompanyAssetsPanel'
import ConfirmDialog from './ConfirmDialog'
import {
  Store, Users, TrendingUp, Wallet, HandCoins, ArrowDownToLine,
  ArrowUpFromLine, UserPlus, Trash2, Check, X, AlertTriangle, Building2, Package,
  Search, LogIn, ChevronRight, Settings, Eye, EyeOff, Unlock, Lock,
} from 'lucide-react'

const LOGO_EMOJI = ['🏢', '🏦', '🏭', '🚀', '💎', '⚙️', '🛰️', '🏗️', '💼', '🌐', '⚡', '🔧']

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
            ? (/^https?:\/\//.test(data.logo)
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

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <div className="asset-summary">
        <div className="asset-summary-card"><span><Wallet size={12} /> {t('company.budget')}</span><b>${formatMoney(data.budget)}</b></div>
        <div className="asset-summary-card"><span><TrendingUp size={12} /> {t('company.revenue')}</span><b className="up">${formatMoney(data.revenuePerHour)}/ч</b></div>
        <div className="asset-summary-card"><span>{t('company.payroll')}</span><b className="down">${formatMoney(data.payrollPerHour)}/ч</b></div>
        <div className="asset-summary-card"><span>{t('company.profit')}</span><b className={data.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(data.profitPerHour)}/ч</b></div>
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
            {data.assetCount} · +${formatMoney(data.assets.reduce((s, a) => s + (a.profitPerHour || 0), 0))}/ч
          </span>
        </div>
        <ChevronRight size={20} className="cac-chevron" />
      </button>

      {showAssets && (
        <CompanyAssetsPanel
          assets={data.assets}
          isOwner={data.isOwner}
          onClose={() => setShowAssets(false)}
          onRefresh={async () => { await load(); setRefreshKey(k => k + 1) }}
        />
      )}

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
                  <span className="company-emp-name">{m.username}</span>
                  <span className="company-emp-role">{t(`company.roles.${m.role}`, m.role)}</span>
                </div>
                {m.role === 'owner' ? (
                  <span className="company-emp-salary">—</span>
                ) : !data.isOwner ? (
                  <span className="company-emp-salary">${formatMoney(m.salary)}/ч</span>
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
                    <span className="company-emp-salary">${formatMoney(m.salary)}/ч</span>
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
        <TransactionsPanel category="company" refreshKey={refreshKey} />
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
            <input className="company-name-input" maxLength={300} value={settingsModal.logo}
              placeholder={t('company.logoPlaceholder')}
              onChange={e => setSettingsModal({ ...settingsModal, logo: e.target.value })} />

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
    </div>
  )
}

export default MyCompanyTab
