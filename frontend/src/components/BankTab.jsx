import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { createTransfer, fetchWeeklyAnalytics, fetchCryptoAccount } from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import {
  Send, History, User, DollarSign, MessageSquare, CheckCircle, AlertTriangle,
  LayoutGrid, BarChart3, Coins, TrendingUp, TrendingDown, Wallet, ArrowRight,
} from 'lucide-react'

const WD = ['dayMon', 'dayTue', 'dayWed', 'dayThu', 'dayFri', 'daySat', 'daySun']

function BankTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [view, setView] = useState('overview')   // overview | transfer | history | analytics
  const [recipient, setRecipient] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const [localBalance, setLocalBalance] = useState(balance)
  const [refreshKey, setRefreshKey] = useState(0)
  const [analytics, setAnalytics] = useState(null)
  const [crypto, setCrypto] = useState(null)

  useEffect(() => { setLocalBalance(balance) }, [balance])

  const loadSummary = useCallback(async () => {
    try {
      const [a, c] = await Promise.all([
        fetchWeeklyAnalytics().catch(() => null),
        fetchCryptoAccount().catch(() => null),
      ])
      setAnalytics(a)
      setCrypto(c)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadSummary() }, [loadSummary, refreshKey])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setFeedback(null)
    const parsedAmount = parseFloat(amount)
    if (!recipient.trim()) { setFeedback({ type: 'error', text: t('bank.recipientNotFound') }); return }
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) { setFeedback({ type: 'error', text: t('bank.invalidAmount') }); return }
    if (parsedAmount > localBalance) { setFeedback({ type: 'error', text: t('bank.insufficientFunds') }); return }

    setSubmitting(true)
    try {
      const result = await createTransfer({ recipient: recipient.trim(), amount: parsedAmount, note: note.trim() || undefined })
      setFeedback({ type: 'success', text: t('bank.transferSuccess', { amount: formatMoney(result.amount), recipient: result.recipient }) })
      setLocalBalance(result.balance)
      onBalanceChange?.(result.balance)
      setRecipient(''); setAmount(''); setNote('')
      setRefreshKey(k => k + 1)
    } catch (err) {
      const msg = err.message || ''
      let text = msg
      if (msg.includes('самому себе')) text = t('bank.selfTransfer')
      else if (msg.includes('не найден')) text = t('bank.recipientNotFound')
      else if (msg.includes('Недостаточно')) text = t('bank.insufficientFunds')
      setFeedback({ type: 'error', text })
    } finally {
      setSubmitting(false)
    }
  }

  const NAV = [
    { id: 'overview', icon: LayoutGrid, label: t('bank.overview') },
    { id: 'transfer', icon: Send, label: t('bank.transfer') },
    { id: 'history', icon: History, label: t('bank.history') },
    { id: 'analytics', icon: BarChart3, label: t('account.weeklyAnalytics') },
  ]

  const maxBar = analytics ? Math.max(1, ...analytics.days.map(d => Math.max(d.income, d.expense))) : 1

  return (
    <div className="bank-tab">
      <h2 className="tab-title">{t('bank.title')}</h2>

      <div className="bank-nav">
        {NAV.map(n => {
          const Icon = n.icon
          return (
            <button key={n.id} className={`bank-nav-btn ${view === n.id ? 'active' : ''}`} onClick={() => setView(n.id)}>
              <Icon size={16} /> <span>{n.label}</span>
            </button>
          )
        })}
      </div>

      {/* ── Обзор ── */}
      {view === 'overview' && (
        <div className="bank-overview">
          <div className="bank-hero-card">
            <div className="bank-hero-top">
              <span className="bank-hero-label"><Wallet size={15} /> {t('bank.mainAccount')}</span>
              {analytics && (
                <span className={`bank-hero-net ${analytics.net >= 0 ? 'up' : 'down'}`}>
                  {analytics.net >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  {analytics.net >= 0 ? '+' : ''}{formatMoney(analytics.net)} $ / {t('common.week')}
                </span>
              )}
            </div>
            <div className="bank-hero-balance">{formatMoney(localBalance)} <span>$</span></div>
            <button className="bank-hero-action" onClick={() => setView('transfer')}>
              <Send size={15} /> {t('bank.sendMoney')}
            </button>
          </div>

          <div className="bank-mini-stats">
            <div className="bank-mini income"><TrendingUp size={18} /><div><span>{t('account.earned')}</span><b>+{formatMoney(analytics?.income)} $</b></div></div>
            <div className="bank-mini expense"><TrendingDown size={18} /><div><span>{t('account.spent')}</span><b>−{formatMoney(analytics?.expense)} $</b></div></div>
            <div className="bank-mini ops"><BarChart3 size={18} /><div><span>{t('account.operations')}</span><b>{analytics?.operations ?? 0}</b></div></div>
          </div>

          <div className="bank-crypto-card">
            <div className="bank-crypto-head">
              <span><Coins size={16} /> {t('bank.cryptoAccount')}</span>
            </div>
            {crypto?.opened ? (
              <div className="bank-crypto-body">
                <code className="bank-crypto-wallet">{crypto.wallet}</code>
                <div className="bank-crypto-val">
                  <span>{t('crypto.portfolioValue')}</span>
                  <b>{formatMoney(crypto.portfolioValue)} $</b>
                </div>
              </div>
            ) : (
              <p className="bank-crypto-closed">{t('bank.cryptoClosed')} <ArrowRight size={13} /></p>
            )}
          </div>
        </div>
      )}

      {/* ── Переводы ── */}
      {view === 'transfer' && (
        <div className="transfer-layout">
          <div className="transfer-balance-card">
            <span className="transfer-balance-label">{t('bank.currentBalance')}</span>
            <span className="transfer-balance-value">{formatMoney(localBalance)} $</span>
          </div>
          <form className="transfer-form" onSubmit={handleSubmit}>
            <h3 className="transfer-form-title">{t('bank.transferTitle')}</h3>
            <label className="transfer-field">
              <span><User size={14} /> {t('bank.recipient')}</span>
              <input type="text" value={recipient} onChange={e => setRecipient(e.target.value)} placeholder={t('bank.recipientPlaceholder')} autoComplete="off" />
            </label>
            <label className="transfer-field">
              <span><DollarSign size={14} /> {t('bank.amount')}</span>
              <input type="number" min="0.01" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
            </label>
            <label className="transfer-field">
              <span><MessageSquare size={14} /> {t('bank.note')}</span>
              <input type="text" value={note} onChange={e => setNote(e.target.value)} placeholder={t('bank.notePlaceholder')} maxLength={120} />
            </label>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <CheckCircle size={16} /> : <AlertTriangle size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}
            <button type="submit" className="transfer-submit" disabled={submitting}>
              {submitting ? t('bank.processing') : <><Send size={16} /> {t('bank.sendMoney')}</>}
            </button>
          </form>
        </div>
      )}

      {/* ── История ── */}
      {view === 'history' && <TransactionsPanel refreshKey={refreshKey} />}

      {/* ── Аналитика ── */}
      {view === 'analytics' && (
        <div className="bank-analytics">
          <div className="bank-mini-stats">
            <div className="bank-mini income"><TrendingUp size={18} /><div><span>{t('account.earned')}</span><b>+{formatMoney(analytics?.income)} $</b></div></div>
            <div className="bank-mini expense"><TrendingDown size={18} /><div><span>{t('account.spent')}</span><b>−{formatMoney(analytics?.expense)} $</b></div></div>
            <div className="bank-mini net"><DollarSign size={18} /><div><span>{t('account.netChange')}</span><b className={(analytics?.net ?? 0) >= 0 ? 'up' : 'down'}>{(analytics?.net ?? 0) >= 0 ? '+' : ''}{formatMoney(analytics?.net)} $</b></div></div>
          </div>
          <div className="bank-chart-card">
            <h3>{t('account.weeklyAnalytics')}</h3>
            <div className="bank-chart">
              {(analytics?.days || []).map((d, i) => (
                <div key={i} className="bank-chart-col">
                  <div className="bank-chart-bars">
                    <div className="bank-bar income" style={{ height: `${(d.income / maxBar) * 100}%` }} title={`+${formatMoney(d.income)} $`} />
                    <div className="bank-bar expense" style={{ height: `${(d.expense / maxBar) * 100}%` }} title={`−${formatMoney(d.expense)} $`} />
                  </div>
                  <span className="bank-chart-label">{t(`common.${WD[d.weekday]}`)}</span>
                </div>
              ))}
            </div>
            <div className="bank-chart-legend">
              <span className="legend-income">{t('account.income')}</span>
              <span className="legend-expense">{t('account.expense')}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default BankTab
