import { useTranslation } from 'react-i18next'
import { fetchTransactions } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { ShoppingCart, CheckCircle, AlertTriangle } from 'lucide-react'

function BankTab({ userId }) {
  const { t } = useTranslation()
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

  return (
    <div className="bank-tab">
      <h2 className="tab-title">{t('bank.title')} — {t('bank.history')}</h2>

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
