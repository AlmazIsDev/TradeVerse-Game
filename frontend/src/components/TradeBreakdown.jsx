import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { quoteStock, quoteCrypto } from '../services/api'
import { formatMoney, formatQty } from './TransactionsPanel'
import { AlertTriangle } from 'lucide-react'
import { parseQty, quantizeQty } from '../utils/qty'
import Tooltip from './Tooltip'

const FRACTIONS = [0.25, 0.5, 0.75, 1]

/**
 * Поле количества + разбивка сделки по котировке бэкенда.
 *
 * Сервер возвращает цену сделки, impact и комиссию: формулу нельзя считать
 * на клиенте, иначе котировка и фактическое списание разойдутся.
 *
 * onQuote получает котировку (или null), чтобы владелец модалки мог
 * заблокировать кнопку подтверждения.
 */
function TradeBreakdown({
  market, symbol, action, quantity, onQuantityChange,
  balance = 0, held = 0, onQuote,
}) {
  const { t } = useTranslation()
  const [quote, setQuote] = useState(null)
  const [loading, setLoading] = useState(false)

  const qty = parseQty(quantity, market)
  const isBuy = action === 'buy'

  useEffect(() => {
    if (!symbol || !action) {
      setQuote(null); onQuote?.(null)
      return
    }
    let cancelled = false
    setLoading(true)
    const id = setTimeout(() => {
      const fn = market === 'stock' ? quoteStock : quoteCrypto
      // Запрашиваем и при пустом поле: qty=0 даёт нулевую сумму, но приносит
      // maxAffordable — без него кнопки долей не знали бы, от чего считать.
      fn(symbol, action, Math.max(0, qty))
        .then(res => {
          if (cancelled) return
          setQuote(res); setLoading(false); onQuote?.(qty > 0 ? res : null)
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

  const priced = quote && qty > 0
  const impact = priced ? (quote.nextPrice ?? quote.fillPrice) - quote.price : 0
  const short = isBuy && priced ? quote.total - balance : 0
  // Без котировки печатаем прочерк, а не «$0,00»: ноль читается как реальная сумма.
  const money = v => (priced ? `$${formatMoney(v)}` : '—')
  const tradeMax = isBuy ? (quote?.maxAffordable ?? 0) : held

  return (
    <>
      <div className="tm-field">
        <div className="tm-field-head">
          <label htmlFor="tm-qty">{t('common.quantity')}<Tooltip text={t('trade.quantityHelp')} /></label>
          {tradeMax > 0 && (
            <span className="tm-avail">
              {isBuy ? t('trade.affordable') : t('trade.available')}: <b>{formatQty(tradeMax)}</b>
            </span>
          )}
        </div>
        <input
          id="tm-qty" type="text" inputMode="decimal" value={quantity} autoFocus
          placeholder={market === 'crypto' ? '0.00' : '1'}
          onChange={e => onQuantityChange(e.target.value)}
        />
        <div className="tm-presets">
          {FRACTIONS.map(f => (
            <button
              key={f} type="button" className="tm-preset"
              disabled={!(tradeMax > 0)}
              onClick={() => onQuantityChange(quantizeQty(tradeMax * f, market))}
            >
              {f === 1 ? t('trade.max') : `${f * 100}%`}
            </button>
          ))}
        </div>
      </div>

      <div className={`trade-breakdown ${loading ? 'loading' : ''}`}>
        <div className="tb-row">
          <span>{t('trade.fillPrice')}</span>
          <b>{money(quote?.fillPrice)}</b>
        </div>
        {priced && Math.abs(impact) > 0.004 && (
          <div className="tb-row">
            <span>{t('trade.priceImpact')}<Tooltip text={t('trade.priceImpactHelp')} /></span>
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
          <span>{t('trade.feeLabel')}{priced ? ` (${(quote.feeRate * 100).toFixed(1)}%)` : ''}<Tooltip text={t('trade.feeHelp')} /></span>
          <b>{priced ? `${isBuy ? '+' : '−'}$${formatMoney(quote.fee)}` : '—'}</b>
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
