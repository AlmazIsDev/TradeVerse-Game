<<<<<<< HEAD
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchTransactions } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { ShoppingCart, CheckCircle, AlertTriangle, CreditCard, Bitcoin, ArrowRightLeft, X } from 'lucide-react'
=======
import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { createTransfer, fetchWeeklyAnalytics, fetchCryptoAccount } from '../services/api'
import TransactionsPanel, { formatMoney, formatCompact } from './TransactionsPanel'
import AnalyticsChart from './AnalyticsChart'
import {
  Send, History, User, DollarSign, MessageSquare, CheckCircle, AlertTriangle,
  LayoutGrid, BarChart3, Coins, TrendingUp, TrendingDown, Wallet, ArrowRight,
} from 'lucide-react'
>>>>>>> origin/Marlow

function BankTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
<<<<<<< HEAD
  const [cryptoUnlocked, setCryptoUnlocked] = useState(false)
  const [transferModal, setTransferModal] = useState(false)
  const [transferStep, setTransferStep] = useState('select')
  const [transferType, setTransferType] = useState('')
  const [moneyForm, setMoneyForm] = useState({ account1: '', account2: '', account3: '', account4: '' })
  const [cryptoForm, setCryptoForm] = useState({ currency: '', prefix1: '', prefix2: '', account1: '', account2: '', account3: '', account4: '' })
  const [transferAmount, setTransferAmount] = useState('')

  const { data: transactions, loading, error } = useApiOnMount(
    () => fetchTransactions(userId, 100)
  )
=======
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
>>>>>>> origin/Marlow

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

  const handleSelectType = (type) => {
    setTransferType(type)
    setTransferStep('form')
  }

  const handleBack = () => {
    if (transferStep === 'form') {
      setTransferStep('select')
      setTransferType('')
      setMoneyForm({ account1: '', account2: '', account3: '', account4: '' })
      setCryptoForm({ currency: '', prefix1: '', prefix2: '', account1: '', account2: '', account3: '', account4: '' })
      setTransferAmount('')
    } else {
      setTransferModal(false)
      setTransferStep('select')
      setTransferType('')
    }
  }

  const handleMoneyChange = (field, value) => {
    if (/^\d*$/.test(value) && value.length <= 4) {
      setMoneyForm(prev => ({ ...prev, [field]: value }))
    }
  }

  const handleCryptoChange = (field, value) => {
    if (field === 'currency') {
      if (/^[A-Za-z]*$/.test(value) && value.length <= 10) {
        setCryptoForm(prev => ({ ...prev, [field]: value }))
      }
    } else if (field === 'prefix1' || field === 'prefix2') {
      if (/^[A-Za-z]*$/.test(value) && value.length <= 1) {
        setCryptoForm(prev => ({ ...prev, [field]: value }))
      }
    } else {
      if (/^\d*$/.test(value) && value.length <= 4) {
        setCryptoForm(prev => ({ ...prev, [field]: value }))
      }
    }
  }

  const isMoneyValid = () => {
    return moneyForm.account1.length === 4 &&
      moneyForm.account2.length === 4 &&
      moneyForm.account3.length === 4 &&
      moneyForm.account4.length === 4 &&
      transferAmount.length > 0
  }

  const isCryptoValid = () => {
    return cryptoForm.currency.length > 0 &&
      cryptoForm.prefix1.length === 1 &&
      cryptoForm.prefix2.length === 1 &&
      cryptoForm.account1.length === 4 &&
      cryptoForm.account2.length === 4 &&
      cryptoForm.account3.length === 4 &&
      cryptoForm.account4.length === 4 &&
      transferAmount.length > 0
  }

  const handleSubmit = () => {
    if (transferType === 'money' && isMoneyValid()) {
      alert(`Перевод ${transferAmount} $ на счёт ${moneyForm.account1}-${moneyForm.account2}-${moneyForm.account3}-${moneyForm.account4}`)
    } else if (transferType === 'crypto' && isCryptoValid()) {
      alert(`Перевод ${transferAmount} ${cryptoForm.currency} на адрес ${cryptoForm.prefix1}${cryptoForm.prefix2}-${cryptoForm.account1}-${cryptoForm.account2}-${cryptoForm.account3}-${cryptoForm.account4}`)
    }
    handleBack()
  }

  return (
    <div className="bank-tab">
      <h2 className="tab-title">{t('bank.title')}</h2>

<<<<<<< HEAD
      <div className="bank-cards">
        <div className="bank-card">
          <div className="bank-card-top">
            <CreditCard size={28} className="bank-card-icon" />
            <div className="bank-card-number">XXXX-XXXX-XXXX-XXXXX</div>
          </div>
        </div>

        <div className={`bank-card bank-card-crypto ${cryptoUnlocked ? 'unlocked' : ''}`}>
          {!cryptoUnlocked && (
            <div className="bank-card-crypto-overlay">
              <button className="bank-card-unlock-btn" onClick={() => setCryptoUnlocked(true)}>
                Открыть криптосчёт
              </button>
            </div>
          )}
          <div className="bank-card-body">
            <div className="bank-card-crypto-icon">
              <Bitcoin size={28} />
            </div>
            <div className="bank-card-number">TD-XXXX-XXXX-XXXXX</div>
          </div>
        </div>
      </div>

      <button className="bank-transfer-btn" onClick={() => setTransferModal(true)}>
        <ArrowRightLeft size={16} />
        Перевести деньги
      </button>

      {transferModal && (
        <div className="modal-overlay" onClick={handleBack}>
          <div className="transfer-modal" onClick={e => e.stopPropagation()}>
            <div className="transfer-modal-header">
              <h3>{transferStep === 'select' ? 'Выберите тип перевода' : transferType === 'money' ? 'Перевод деньгами' : 'Перевод криптовалютой'}</h3>
              <button className="transfer-modal-close" onClick={handleBack}>
                <X size={20} />
              </button>
            </div>

            {transferStep === 'select' && (
              <div className="transfer-select">
                <button className="transfer-option" onClick={() => handleSelectType('money')}>
                  <CreditCard size={24} />
                  <span>Деньги</span>
                </button>
                <button className="transfer-option" onClick={() => handleSelectType('crypto')}>
                  <Bitcoin size={24} />
                  <span>Криптовалюта</span>
                </button>
              </div>
            )}

            {transferStep === 'form' && transferType === 'money' && (
              <div className="transfer-form">
                <div className="transfer-form-group">
                  <label>Номер счёта получателя</label>
                  <div className="transfer-account-inputs">
                    <input
                      type="text"
                      maxLength={4}
                      value={moneyForm.account1}
                      onChange={(e) => handleMoneyChange('account1', e.target.value)}
                      placeholder="XXXX"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={moneyForm.account2}
                      onChange={(e) => handleMoneyChange('account2', e.target.value)}
                      placeholder="XXXX"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={moneyForm.account3}
                      onChange={(e) => handleMoneyChange('account3', e.target.value)}
                      placeholder="XXXX"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={moneyForm.account4}
                      onChange={(e) => handleMoneyChange('account4', e.target.value)}
                      placeholder="XXXX"
                    />
                  </div>
                </div>
                <div className="transfer-form-group">
                  <label>Сумма перевода ($)</label>
                  <input
                    type="text"
                    value={transferAmount}
                    onChange={(e) => setTransferAmount(e.target.value.replace(/[^\d.]/g, ''))}
                    placeholder="0.00"
                    className="transfer-amount-input"
                  />
                </div>
                <button className="transfer-submit-btn" onClick={handleSubmit} disabled={!isMoneyValid()}>
                  Перевести
                </button>
              </div>
            )}

            {transferStep === 'form' && transferType === 'crypto' && (
              <div className="transfer-form">
                <div className="transfer-form-group">
                  <label>Вид криптовалюты</label>
                  <input
                    type="text"
                    maxLength={10}
                    value={cryptoForm.currency}
                    onChange={(e) => handleCryptoChange('currency', e.target.value)}
                    placeholder="BTC"
                    className="transfer-currency-input"
                  />
                </div>
                <div className="transfer-form-group">
                  <label>Адрес кошелька получателя</label>
                  <div className="transfer-crypto-inputs">
                    <input
                      type="text"
                      maxLength={1}
                      value={cryptoForm.prefix1}
                      onChange={(e) => handleCryptoChange('prefix1', e.target.value)}
                      placeholder="Y"
                      className="transfer-prefix-input"
                    />
                    <input
                      type="text"
                      maxLength={1}
                      value={cryptoForm.prefix2}
                      onChange={(e) => handleCryptoChange('prefix2', e.target.value)}
                      placeholder="Y"
                      className="transfer-prefix-input"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={cryptoForm.account1}
                      onChange={(e) => handleCryptoChange('account1', e.target.value)}
                      placeholder="XXXX"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={cryptoForm.account2}
                      onChange={(e) => handleCryptoChange('account2', e.target.value)}
                      placeholder="XXXX"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={cryptoForm.account3}
                      onChange={(e) => handleCryptoChange('account3', e.target.value)}
                      placeholder="XXXX"
                    />
                    <span>-</span>
                    <input
                      type="text"
                      maxLength={4}
                      value={cryptoForm.account4}
                      onChange={(e) => handleCryptoChange('account4', e.target.value)}
                      placeholder="XXXX"
                    />
                  </div>
                </div>
                <div className="transfer-form-group">
                  <label>Сумма перевода ({cryptoForm.currency || '?'})</label>
                  <input
                    type="text"
                    value={transferAmount}
                    onChange={(e) => setTransferAmount(e.target.value.replace(/[^\d.]/g, ''))}
                    placeholder="0.00"
                    className="transfer-amount-input"
                  />
                </div>
                <button className="transfer-submit-btn" onClick={handleSubmit} disabled={!isCryptoValid()}>
                  Перевести
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {loading && (
        <div className="loading-state">
          <div className="spinner" />
          <p>{t('common.loading')}</p>
        </div>
      )}
=======
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
>>>>>>> origin/Marlow

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
            <div className="bank-hero-balance" title={`${formatMoney(localBalance)} $`}>{formatCompact(localBalance)} <span>$</span></div>
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
            <AnalyticsChart days={analytics?.days || []} />
          </div>
        </div>
      )}
    </div>
  )
}

export default BankTab
