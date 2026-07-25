import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { quoteStock, quoteCrypto } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { AlertTriangle } from 'lucide-react'

/**
 * Разбивка сделки по котировке бэкенда.
 *
 * Цена исполнения отличается от котировки: крупный ордер сам двигает цену
 * (price-impact), сверху идёт комиссия. Считать это на клиенте нельзя — формула
 * разъедется с бэкендом, и покупка будет падать с «Недостаточно средств» при
 * визуально достаточном балансе. Поэтому сумму спрашиваем у сервера.
 *
 * onQuote получает котировку (или null), чтобы владелец модалки мог
 * заблокировать кнопку подтверждения.
 */
function TradeBreakdown({ market, symbol, action, quantity, balance = 0, onQuote }) {
  const { t } = useTranslation()
  const [quote, setQuote] = useState(null)
  const [loading, setLoading] = useState(false)

  const qty = market === 'stock' ? Math.floor(Number(quantity)) : Number(quantity)

  useEffect(() => {
    if (!symbol || !action || !(qty > 0)) {
      setQuote(null)
      onQuote?.(null)
      return
    }
    let cancelled = false
    setLoading(true)
    const id = setTimeout(() => {
      const fn = market === 'stock' ? quoteStock : quoteCrypto
      fn(symbol, action, qty)
        .then(res => {
          if (cancelled) return
          setQuote(res); setLoading(false); onQuote?.(res)
        })
        .catch(() => {
          if (cancelled) return
          setQuote(null); setLoading(false); onQuote?.(null)
        })
    }, 250)
    return () => { cancelled = true; clearTimeout(id) }
    // onQuote намеренно вне зависимостей: инлайн-колбэк родителя менялся бы
    // каждый рендер и гонял бы запрос по кругу.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, symbol, action, qty])

  const isBuy = action === 'buy'
  const impact = quote ? quote.fillPrice - quote.price : 0
  const short = isBuy && quote ? quote.total - balance : 0

  return (
    <>
      <div className={`trade-breakdown ${loading ? 'loading' : ''}`}>
        <div className="tb-row">
          <span>{t('trade.fillPrice')}</span>
          <b>${formatMoney(quote?.fillPrice ?? 0)}</b>
        </div>
        {quote && Math.abs(impact) > 0.004 && (
          <div className="tb-row">
            <span>{t('trade.priceImpact')}</span>
            <b className={isBuy ? 'down' : 'up'}>
              {isBuy ? '+' : '−'}${formatMoney(Math.abs(impact))}
            </b>
          </div>
        )}
        <div className="tb-row">
          <span>{t('trade.subtotal')}</span>
          <b>${formatMoney(quote?.cost ?? 0)}</b>
        </div>
        <div className="tb-row">
          <span>{t('trade.feeLabel')}{quote ? ` (${(quote.feeRate * 100).toFixed(1)}%)` : ''}</span>
          <b>{isBuy ? '+' : '−'}${formatMoney(quote?.fee ?? 0)}</b>
        </div>
        <div className="tb-row tb-total">
          <span>{isBuy ? t('trade.youPay') : t('trade.youGet')}</span>
          <strong>${formatMoney(quote?.total ?? 0)}</strong>
        </div>
      </div>
      {short > 0 && (
        <p className="trade-warning">
          <AlertTriangle size={14} /> {t('trade.notEnough', { amount: formatMoney(short) })}
        </p>
      )}
    </>
  )
}

export default TradeBreakdown
