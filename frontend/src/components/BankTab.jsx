import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { createTransfer } from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import { Send, History, User, DollarSign, MessageSquare, CheckCircle, AlertTriangle } from 'lucide-react'

function BankTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [view, setView] = useState('transfer')     // 'transfer' | 'history'
  const [recipient, setRecipient] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState(null)    // {type:'success'|'error', text}
  const [localBalance, setLocalBalance] = useState(balance)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setFeedback(null)

    const parsedAmount = parseFloat(amount)
    if (!recipient.trim()) {
      setFeedback({ type: 'error', text: t('bank.recipientNotFound') })
      return
    }
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
      setFeedback({ type: 'error', text: t('bank.invalidAmount') })
      return
    }
    if (parsedAmount > localBalance) {
      setFeedback({ type: 'error', text: t('bank.insufficientFunds') })
      return
    }

    setSubmitting(true)
    try {
      const result = await createTransfer({
        recipient: recipient.trim(),
        amount: parsedAmount,
        note: note.trim() || undefined,
      })
      setFeedback({
        type: 'success',
        text: t('bank.transferSuccess', {
          amount: formatMoney(result.amount),
          recipient: result.recipient,
        }),
      })
      setLocalBalance(result.balance)
      onBalanceChange?.(result.balance)
      setRecipient('')
      setAmount('')
      setNote('')
      setRefreshKey(k => k + 1)
    } catch (err) {
      // Разбираем понятные ошибки сервера
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

  return (
    <div className="bank-tab">
      <h2 className="tab-title">{t('bank.title')}</h2>

      <div className="bank-tabs">
        <button
          className={`bank-tab-btn ${view === 'transfer' ? 'active' : ''}`}
          onClick={() => setView('transfer')}
        >
          <Send size={16} /> {t('bank.transfer')}
        </button>
        <button
          className={`bank-tab-btn ${view === 'history' ? 'active' : ''}`}
          onClick={() => setView('history')}
        >
          <History size={16} /> {t('bank.history')}
        </button>
      </div>

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
              <input
                type="text"
                value={recipient}
                onChange={e => setRecipient(e.target.value)}
                placeholder={t('bank.recipientPlaceholder')}
                autoComplete="off"
              />
            </label>

            <label className="transfer-field">
              <span><DollarSign size={14} /> {t('bank.amount')}</span>
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder="0.00"
              />
            </label>

            <label className="transfer-field">
              <span><MessageSquare size={14} /> {t('bank.note')}</span>
              <input
                type="text"
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder={t('bank.notePlaceholder')}
                maxLength={120}
              />
            </label>

            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success'
                  ? <CheckCircle size={16} />
                  : <AlertTriangle size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}

            <button type="submit" className="transfer-submit" disabled={submitting}>
              {submitting ? t('bank.processing') : <><Send size={16} /> {t('bank.sendMoney')}</>}
            </button>
          </form>
        </div>
      )}

      {view === 'history' && <TransactionsPanel refreshKey={refreshKey} />}
    </div>
  )
}

export default BankTab
