import { useTranslation } from 'react-i18next'
import { fetchTransactions } from '../services/api'
import { useApiOnMount } from '../hooks/useApi'
import { ShoppingCart, CheckCircle, AlertTriangle } from 'lucide-react'

function BankTab({ userId }) {
  const { t } = useTranslation()
  const { data: transactions, loading, error } = useApiOnMount(
    () => fetchTransactions(userId, 100)
  )

  const formatMoney = (n) => (Number(n) || 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const formatDate = (ts) => {
    if (!ts) return ''
    const d = new Date(ts)
    return isNaN(d.getTime())
      ? ''
      : d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
  }

  // Бэкенд-транзакции: { type: 'buy' | 'sell', symbol, amount, price, timestamp }.
  // Покупка (buy) — расход, продажа (sell) — поступление от продажи.
  const getTxType = (tx) => (tx.type === 'sell' ? 'success' : 'purchase')
  const getTxLabel = (tx) => (tx.type === 'sell' ? t('bank.successSale') : t('bank.purchase'))
  const txValue = (tx) => (Number(tx.amount) || 0) * (Number(tx.price) || 0)

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
          {transactions.map(tx => {
            const txType = getTxType(tx)
            return (
              <div key={tx.id} className={`bank-transaction ${txType}`}>
                <div className="bank-tx-icon">
                  {txType === 'purchase' ? <ShoppingCart size={20} /> : <CheckCircle size={20} />}
                </div>
                <div className="bank-tx-info">
                  <span className={`bank-tx-label ${txType}`}>{getTxLabel(tx)}</span>
                  <span className="bank-tx-stock">{tx.symbol}</span>
                  <span className="bank-tx-meta">
                    {tx.amount} {t('common.shares')} · {formatDate(tx.timestamp)}
                  </span>
                </div>
                <div className="bank-tx-amounts">
                  <span className="bank-tx-total">{formatMoney(txValue(tx))} $</span>
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
