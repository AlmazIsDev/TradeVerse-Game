import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCryptoAccount, fetchCryptoMarket, openCryptoAccount, tradeCrypto,
} from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import {
  Coins, Wallet, TrendingUp, TrendingDown, Copy, Check,
  ArrowUpRight, ArrowDownLeft, AlertTriangle, PlusCircle, X,
} from 'lucide-react'

function formatCoin(n) {
  return Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 6 })
}

function CryptoTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [account, setAccount] = useState(null)
  const [market, setMarket] = useState([])
  const [loading, setLoading] = useState(true)
  const [opening, setOpening] = useState(false)
  const [copied, setCopied] = useState(false)
  const [trade, setTrade] = useState(null)   // {symbol, name, action, price, color}
  const [qty, setQty] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const acc = await fetchCryptoAccount()
      setAccount(acc)
      if (acc.opened) {
        const mkt = await fetchCryptoMarket()
        setMarket(mkt)
      }
    } catch {
      setAccount({ opened: false, holdings: [] })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Живое обновление рынка каждые 20 c
  useEffect(() => {
    if (!account?.opened) return
    const id = setInterval(() => {
      fetchCryptoMarket().then(setMarket).catch(() => {})
    }, 20000)
    return () => clearInterval(id)
  }, [account?.opened])

  const handleOpen = async () => {
    setOpening(true)
    try {
      await openCryptoAccount()
      await load()
    } catch { /* ignore */ } finally { setOpening(false) }
  }

  const handleCopy = async () => {
    if (!account?.wallet) return
    try {
      await navigator.clipboard.writeText(account.wallet)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch { /* ignore */ }
  }

  const openTrade = (coin, action) => {
    setTrade({ ...coin, action })
    setQty('')
    setFeedback(null)
  }

  const holdingFor = (symbol) =>
    account?.holdings?.find(h => h.symbol === symbol)

  const confirmTrade = async () => {
    if (!trade) return
    const q = parseFloat(qty)
    if (!Number.isFinite(q) || q <= 0) {
      setFeedback({ type: 'error', text: t('bank.invalidAmount') })
      return
    }
    const cost = q * trade.price
    if (trade.action === 'buy' && cost > balance) {
      setFeedback({ type: 'error', text: t('crypto.insufficientFunds') })
      return
    }
    const held = holdingFor(trade.symbol)
    if (trade.action === 'sell' && (!held || held.quantity < q)) {
      setFeedback({ type: 'error', text: t('crypto.insufficientCoins') })
      return
    }
    setBusy(true)
    try {
      const res = await tradeCrypto(trade.symbol, trade.action, q)
      onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('crypto.tradeSuccess') })
      setRefreshKey(k => k + 1)
      await load()
      setTimeout(() => setTrade(null), 700)
    } catch (err) {
      const msg = err.message || ''
      let text = msg
      if (msg.includes('Недостаточно средств')) text = t('crypto.insufficientFunds')
      else if (msg.includes('Недостаточно монет')) text = t('crypto.insufficientCoins')
      setFeedback({ type: 'error', text })
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="crypto-tab">
        <h2 className="tab-title">{t('nav.crypto')}</h2>
        <div className="skeleton-chart" style={{ height: 140 }} />
      </div>
    )
  }

  // ── Криптосчёт не открыт ──
  if (!account?.opened) {
    return (
      <div className="crypto-tab">
        <h2 className="tab-title">{t('nav.crypto')}</h2>
        <div className="crypto-onboard">
          <div className="crypto-onboard-icon"><Coins size={56} /></div>
          <h3>{t('crypto.openTitle')}</h3>
          <p>{t('crypto.openDesc')}</p>
          <button className="crypto-open-btn" onClick={handleOpen} disabled={opening}>
            <PlusCircle size={18} />
            {opening ? t('bank.processing') : t('crypto.openAccount')}
          </button>
        </div>
      </div>
    )
  }

  // ── Криптосчёт открыт ──
  return (
    <div className="crypto-tab">
      <h2 className="tab-title">{t('nav.crypto')}</h2>

      <div className="crypto-summary">
        <div className="crypto-wallet-card">
          <span className="crypto-card-label"><Wallet size={14} /> {t('crypto.wallet')}</span>
          <div className="crypto-wallet-row">
            <code className="crypto-wallet-addr">{account.wallet}</code>
            <button className="crypto-copy-btn" onClick={handleCopy} title={t('common.confirm')}>
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
          </div>
        </div>
        <div className="crypto-stat-card">
          <span className="crypto-card-label">{t('crypto.cashBalance')}</span>
          <span className="crypto-stat-value">{formatMoney(balance)} $</span>
        </div>
        <div className="crypto-stat-card accent">
          <span className="crypto-card-label">{t('crypto.portfolioValue')}</span>
          <span className="crypto-stat-value">{formatMoney(account.portfolioValue)} $</span>
        </div>
      </div>

      {/* Холдинги */}
      {account.holdings?.length > 0 && (
        <div className="crypto-section">
          <h3>{t('crypto.myAssets')}</h3>
          <div className="crypto-holdings">
            {account.holdings.map(h => {
              const pnl = (h.price - h.avgPrice) * h.quantity
              const up = pnl >= 0
              return (
                <div key={h.symbol} className="crypto-holding">
                  <span className="crypto-coin-badge" style={{ background: h.color }}>
                    {h.symbol.slice(0, 2)}
                  </span>
                  <div className="crypto-holding-info">
                    <span className="crypto-holding-symbol">{h.symbol}</span>
                    <span className="crypto-holding-qty">{formatCoin(h.quantity)}</span>
                  </div>
                  <div className="crypto-holding-values">
                    <span className="crypto-holding-value">{formatMoney(h.value)} $</span>
                    <span className={`crypto-holding-pnl ${up ? 'up' : 'down'}`}>
                      {up ? '+' : '−'}{formatMoney(Math.abs(pnl))} $
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Рынок */}
      <div className="crypto-section">
        <h3>{t('crypto.market')}</h3>
        <div className="crypto-market">
          {market.map(coin => {
            const up = (coin.change24h || 0) >= 0
            return (
              <div key={coin.symbol} className="crypto-coin">
                <span className="crypto-coin-badge" style={{ background: coin.color }}>
                  {coin.symbol.slice(0, 2)}
                </span>
                <div className="crypto-coin-info">
                  <span className="crypto-coin-symbol">{coin.symbol}</span>
                  <span className="crypto-coin-name">{coin.name}</span>
                </div>
                <div className="crypto-coin-price">
                  <span className="crypto-coin-value">{formatMoney(coin.price)} $</span>
                  <span className={`crypto-coin-change ${up ? 'up' : 'down'}`}>
                    {up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                    {up ? '+' : ''}{(coin.change24h || 0).toFixed(2)}%
                  </span>
                </div>
                <div className="crypto-coin-actions">
                  <button className="crypto-buy" onClick={() => openTrade(coin, 'buy')}>
                    <ArrowDownLeft size={14} /> {t('common.buy')}
                  </button>
                  <button
                    className="crypto-sell"
                    onClick={() => openTrade(coin, 'sell')}
                    disabled={!holdingFor(coin.symbol)}
                  >
                    <ArrowUpRight size={14} /> {t('common.sell')}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* История крипто-операций */}
      <div className="crypto-section">
        <h3>{t('bank.history')}</h3>
        <TransactionsPanel category="crypto" refreshKey={refreshKey} />
      </div>

      {/* Модалка сделки */}
      {trade && (
        <div className="crypto-modal-overlay" onClick={() => !busy && setTrade(null)}>
          <div className="crypto-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setTrade(null)}><X size={18} /></button>
            <h3>
              {trade.action === 'buy' ? t('common.buy') : t('common.sell')} {trade.symbol}
            </h3>
            <p className="crypto-modal-price">{formatMoney(trade.price)} $ / {trade.symbol}</p>

            <label className="transfer-field">
              <span>{t('common.quantity')}</span>
              <input
                type="number" min="0" step="any" value={qty} autoFocus
                onChange={e => setQty(e.target.value)} placeholder="0.00"
              />
            </label>

            <div className="crypto-modal-total">
              {t('common.total')}: <strong>{formatMoney((parseFloat(qty) || 0) * trade.price)} $</strong>
            </div>

            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
                <span>{feedback.text}</span>
              </div>
            )}

            <button
              className={`crypto-confirm ${trade.action}`}
              onClick={confirmTrade} disabled={busy}
            >
              {busy ? t('bank.processing')
                : trade.action === 'buy' ? t('common.buy') : t('common.sell')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default CryptoTab
