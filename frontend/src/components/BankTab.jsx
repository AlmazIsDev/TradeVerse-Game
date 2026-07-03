import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchTransactions } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { ShoppingCart, CheckCircle, AlertTriangle, CreditCard, Bitcoin, ArrowRightLeft, X } from 'lucide-react'

function BankTab({ userId }) {
  const { t } = useTranslation()
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

  const formatMoney = (n) => n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const getTxType = (t) => {
    if (t.type === 'purchase' || t.type === 'expense') return 'purchase'
    if (t.profit > 0) return 'success'
    if (t.loss > 0) return 'loss'
    return 'purchase'
  }

  const getTxLabel = (t) => {
    if (t.label) return t.label
    const type = getTxType(t)
    if (type === 'purchase') return t('bank.purchase')
    if (type === 'success') return t('bank.successSale')
    if (type === 'loss') return t('bank.lossSale')
    return t('bank.operation')
  }

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
      <h2 className="tab-title">{t('bank.title')} — {t('bank.history')}</h2>

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

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {!loading && !error && (!transactions || transactions.length === 0) && (
        <div className="empty-state">
          <p>{t('bank.noData')}</p>
        </div>
      )}

      {!loading && !error && transactions && transactions.length > 0 && (
        <div className="bank-transactions">
          {transactions.map(t => {
            const txType = getTxType(t)
            return (
              <div key={t.id} className={`bank-transaction ${txType}`}>
                <div className="bank-tx-icon">
                  {txType === 'purchase' && <ShoppingCart size={20} />}
                  {txType === 'success' && <CheckCircle size={20} />}
                  {txType === 'loss' && <AlertTriangle size={20} />}
                </div>
                <div className="bank-tx-info">
                  <span className={`bank-tx-label ${txType}`}>{getTxLabel(t)}</span>
                  <span className="bank-tx-stock">{t.stock || t.ticker} · {t.company}</span>
                  <span className="bank-tx-meta">
                    {t.quantity} {t('common.shares')} · {t.date}
                  </span>
                </div>
                <div className="bank-tx-amounts">
                  <span className="bank-tx-total">{formatMoney(t.amount)} $</span>
                  {txType === 'success' && t.profit > 0 && (
                    <span className="bank-tx-profit">+{formatMoney(t.profit)} $</span>
                  )}
                  {txType === 'loss' && t.loss > 0 && (
                    <span className="bank-tx-loss">(-{formatMoney(t.loss)} $)</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default BankTab
