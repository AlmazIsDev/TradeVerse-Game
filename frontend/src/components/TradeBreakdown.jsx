import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { quoteStock, quoteCrypto } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { AlertTriangle } from 'lucide-react'
import { parseQty } from '../utils/qty'

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

  const qty = parseQty(quantity, market)

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
  // Без котировки печатаем прочерк, а не «$0,00»: ноль читается как реальная сумма.
  const money = v => (quote ? `$${formatMoney(v)}` : '—')

  return (
    <>
      <div className={`trade-breakdown ${loading ? 'loading' : ''}`}>
        <div className="tb-row">
          <span>{t('trade.fillPrice')}</span>
          <b>{money(quote?.fillPrice)}</b>
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
          <b>{money(quote?.cost)}</b>
        </div>
        <div className="tb-row">
          <span>{t('trade.feeLabel')}{quote ? ` (${(quote.feeRate * 100).toFixed(1)}%)` : ''}</span>
          <b>{quote ? `${isBuy ? '+' : '−'}$${formatMoney(quote.fee)}` : '—'}</b>
        </div>
        <div className="tb-row tb-total">
          <span>{isBuy ? t('trade.youPay') : t('trade.youGet')}</span>
          <strong>{money(quote?.total)}</strong>
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
