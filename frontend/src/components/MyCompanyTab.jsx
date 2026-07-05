import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCompany, createCompany, inviteEmployee, updateMemberSalary,
  fireMember, collectCompanyProfit, companyDeposit, companyWithdraw,
} from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import {
  Store, Users, TrendingUp, Wallet, HandCoins, ArrowDownToLine,
  ArrowUpFromLine, UserPlus, Trash2, Check, X, AlertTriangle, Building2, Package,
} from 'lucide-react'

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
  const [invite, setInvite] = useState({ username: '', role: 'worker', salary: '' })
  const [editing, setEditing] = useState(null)      // { userId, salary }
  const [moneyModal, setMoneyModal] = useState(null) // 'deposit' | 'withdraw'
  const [moneyAmount, setMoneyAmount] = useState('')

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
      </div>
    )
  }

  // ── Есть компания ──
  return (
    <div className="company-tab">
      <div className="leaderboard-title-row">
        <Store size={22} className="icon" />
        <h2 className="tab-title">{data.name}</h2>
      </div>

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

      {/* Активы компании — реальный источник дохода */}
      <div className="company-section">
        <h3><Package size={16} /> {t('company.assets')} ({data.assetCount})</h3>
        {data.assets.length === 0 ? (
          <p className="empty-state">{t('company.noAssets')}</p>
        ) : (
          <div className="company-emp-list">
            {data.assets.map(a => (
              <div key={a.id} className="company-emp">
                <div className="company-emp-info">
                  <span className="company-emp-name">{a.name}</span>
                  <span className="company-emp-role">{t(`market.cat_${a.type}`, a.type)} · {t('myassets.level')} {a.level}</span>
                </div>
                <div className="company-emp-actions">
                  <span className="company-emp-salary">+${formatMoney(a.profitPerHour)}/ч</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Сотрудники (по приглашению) */}
      <div className="company-section">
        <h3><Users size={16} /> {t('company.employees')} ({data.memberCount})</h3>

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
                {editing?.userId === m.userId ? (
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
    </div>
  )
}

export default MyCompanyTab
