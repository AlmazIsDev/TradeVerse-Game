import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchCryptoAccount, fetchCryptoMarket, openCryptoAccount, tradeCrypto,
  transferCrypto, fetchCryptoTransfers,
} from '../services/api'
import TransactionsPanel, { formatMoney } from './TransactionsPanel'
import {
  Coins, Wallet, TrendingUp, TrendingDown, Copy, Check,
  ArrowUpRight, ArrowDownLeft, AlertTriangle, PlusCircle, X, Send, Search, Activity,
} from 'lucide-react'
import AssetDetail from './AssetDetail'
import ConfirmDialog from './ConfirmDialog'

function formatCoin(n) {
  return Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 6 })
}

// Простой прогноз по существующим рыночным данным.
function forecast(coin) {
  const change = coin.change24h || 0
  const demand = coin.demand != null ? coin.demand : 1
  const vol = coin.volatility != null ? coin.volatility * 100 : Math.min(25, Math.abs(change) * 1.5 + 3)
  // Вероятность роста: базовые 50% + импульс изменения + давление спроса.
  let probUp = 50 + change * 1.4 + (demand - 1) * 25
  probUp = Math.max(5, Math.min(95, Math.round(probUp)))
  return { change, vol: Math.round(vol * 10) / 10, probUp, up: change >= 0 }
}

function CryptoTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [account, setAccount] = useState(null)
  const [market, setMarket] = useState([])
  const [loading, setLoading] = useState(true)
  const [opening, setOpening] = useState(false)
  const [copied, setCopied] = useState(false)
  const [trade, setTrade] = useState(null)
  const [qty, setQty] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [detailSymbol, setDetailSymbol] = useState(null)
  const [transfer, setTransfer] = useState({ recipient: '', symbol: '', amount: '' })
  const [transferMsg, setTransferMsg] = useState(null)
  const [transferBusy, setTransferBusy] = useState(false)
  const [confirmTransfer, setConfirmTransfer] = useState(null)   // { recipient, symbol, amount }
  const [transfers, setTransfers] = useState([])
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('cap')   // cap | gainers | losers

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const acc = await fetchCryptoAccount()
      setAccount(acc)
      if (acc.opened) {
        const [mkt, trs] = await Promise.all([fetchCryptoMarket(), fetchCryptoTransfers()])
        setMarket(mkt)
        setTransfers(trs)
      }
    } catch {
      // Не сбрасываем в онбординг при фоновом обновлении: сетевой сбой не должен
      // выглядеть как «счёт исчез». Показываем create-экран только на первой загрузке.
      setAccount(prev => prev ?? { opened: false, holdings: [] })
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // WebSocket: реальное обновление цен
  useEffect(() => {
    const handleRealtime = (event) => {
      const data = event.detail
      if (data.type === 'market_update' && data.market === 'crypto') {
        setMarket(prev => {
          const updates = new Map(data.updates.map(u => [u.symbol, u]))
          return prev.map(coin => {
            const upd = updates.get(coin.symbol)
            if (upd) {
              return { ...coin, price: upd.price, change24h: upd.change24h }
            }
            return coin
          })
        })
      } else if (data.type === 'price_tick' && data.market === 'crypto') {
        setMarket(prev => prev.map(coin =>
          coin.symbol === data.symbol
            ? { ...coin, price: data.price, change24h: data.change24h }
            : coin
        ))
      }
    }
    
    window.addEventListener('tv:realtime', handleRealtime)
    return () => window.removeEventListener('tv:realtime', handleRealtime)
  }, [])

  const marketMap = useMemo(() => Object.fromEntries(market.map(c => [c.symbol, c])), [market])

  const handleOpen = async () => {
    setOpening(true)
    try { await openCryptoAccount(); await load() } catch { /* ignore */ } finally { setOpening(false) }
  }

  const handleCopy = async () => {
    if (!account?.wallet) return
    try {
      await navigator.clipboard.writeText(account.wallet)
      setCopied(true); setTimeout(() => setCopied(false), 1800)
    } catch { /* ignore */ }
  }

  const openTrade = (coin, action) => { setTrade({ ...coin, action }); setQty(''); setFeedback(null) }
  const holdingFor = (symbol) => account?.holdings?.find(h => h.symbol === symbol)

  const confirmTrade = async () => {
    if (!trade) return
    const q = parseFloat(qty)
    if (!Number.isFinite(q) || q <= 0) { setFeedback({ type: 'error', text: t('bank.invalidAmount') }); return }
    const cost = q * trade.price
    if (trade.action === 'buy' && cost > balance) { setFeedback({ type: 'error', text: t('crypto.insufficientFunds') }); return }
    const held = holdingFor(trade.symbol)
    if (trade.action === 'sell' && (!held || held.quantity < q)) { setFeedback({ type: 'error', text: t('crypto.insufficientCoins') }); return }
    setBusy(true)
    try {
      const res = await tradeCrypto(trade.symbol, trade.action, q)
      onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('crypto.tradeSuccess') })
      setRefreshKey(k => k + 1)
      await load(true)
      setTimeout(() => setTrade(null), 700)
    } catch (err) {
      const msg = err.message || ''
      let text = msg
      if (msg.includes('Недостаточно средств')) text = t('crypto.insufficientFunds')
      else if (msg.includes('Недостаточно монет')) text = t('crypto.insufficientCoins')
      setFeedback({ type: 'error', text })
    } finally { setBusy(false) }
  }

  const handleTransfer = (e) => {
    e?.preventDefault?.()
    const amt = parseFloat(transfer.amount)
    if (!transfer.recipient.trim() || !transfer.symbol || !(amt > 0)) { setTransferMsg({ type: 'error', text: t('cryptoTransfer.invalid') }); return }
    const held = account?.holdings?.find(h => h.symbol === transfer.symbol)
    if (!held || held.quantity < amt * 1.01) { setTransferMsg({ type: 'error', text: t('crypto.insufficientCoins') }); return }
    setTransferMsg(null)
    setConfirmTransfer({ recipient: transfer.recipient.trim(), symbol: transfer.symbol, amount: amt })
  }

  const doTransfer = async () => {
    if (!confirmTransfer) return
    setTransferBusy(true); setTransferMsg(null)
    try {
      const res = await transferCrypto(confirmTransfer.recipient, confirmTransfer.symbol, confirmTransfer.amount)
      setTransferMsg({ type: 'success', text: t('cryptoTransfer.sent', { amount: confirmTransfer.amount, symbol: res.symbol, recipient: res.recipient }) })
      setTransfer({ recipient: '', symbol: '', amount: '' })
      setRefreshKey(k => k + 1); await load(true)
    } catch (err) { setTransferMsg({ type: 'error', text: err.message }) }
    finally { setTransferBusy(false); setConfirmTransfer(null) }
  }

  const marketView = useMemo(() => {
    let r = market
    if (search) { const s = search.toLowerCase(); r = r.filter(c => c.symbol.toLowerCase().includes(s) || (c.name || '').toLowerCase().includes(s)) }
    r = [...r]
    if (sort === 'gainers') r.sort((a, b) => (b.change24h || 0) - (a.change24h || 0))
    else if (sort === 'losers') r.sort((a, b) => (a.change24h || 0) - (b.change24h || 0))
    return r
  }, [market, search, sort])

  if (loading) {
    return (
      <div className="crypto-tab">
        <h2 className="tab-title">{t('nav.crypto')}</h2>
        <div className="skeleton-chart" style={{ height: 140 }} />
      </div>
    )
  }

  if (detailSymbol) {
    return (
      <AssetDetail market="crypto" symbol={detailSymbol}
        onBack={() => { setDetailSymbol(null); load(true) }}
        balance={balance} onBalanceChange={onBalanceChange} onTraded={() => load(true)} />
    )
  }

  if (!account?.opened) {
    return (
      <div className="crypto-tab">
        <h2 className="tab-title">{t('nav.crypto')}</h2>
        <div className="crypto-onboard">
          <div className="crypto-onboard-icon"><Coins size={56} /></div>
          <h3>{t('crypto.openTitle')}</h3>
          <p>{t('crypto.openDesc')}</p>
          <button className="crypto-open-btn" onClick={handleOpen} disabled={opening}>
            <PlusCircle size={18} />{opening ? t('bank.processing') : t('crypto.openAccount')}
          </button>
        </div>
      </div>
    )
  }

  const coinLogo = (c) => c?.image
    ? <img className="crypto-coin-img" src={c.image} alt={c.symbol} />
    : <span className="crypto-coin-badge" style={{ background: c?.color || '#0071e3' }}>{(c?.symbol || '?').slice(0, 2)}</span>

  const forecastCoins = (account.holdings?.length ? account.holdings.map(h => marketMap[h.symbol]).filter(Boolean) : marketView).slice(0, 4)

  return (
    <div className="crypto-tab">
      <div className="leaderboard-title-row"><Coins size={22} className="icon" /><h2 className="tab-title">{t('nav.crypto')}</h2></div>

      <div className="crypto-layout">
        {/* ЛЕВО: рынок */}
        <div className="crypto-col-main">
          <div className="crypto-section">
            <div className="crypto-market-head">
              <h3>{t('crypto.market')}</h3>
              <div className="crypto-market-tools">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder={t('market.searchPlaceholder')} /></div>
                <div className="crypto-sort">
                  <button className={`tx-pill ${sort === 'cap' ? 'active' : ''}`} onClick={() => setSort('cap')}>{t('crypto.sortCap')}</button>
                  <button className={`tx-pill ${sort === 'gainers' ? 'active' : ''}`} onClick={() => setSort('gainers')}>{t('crypto.gainers')}</button>
                  <button className={`tx-pill ${sort === 'losers' ? 'active' : ''}`} onClick={() => setSort('losers')}>{t('crypto.losers')}</button>
                </div>
              </div>
            </div>
            <div className="crypto-market">
              {marketView.map(coin => {
                const up = (coin.change24h || 0) >= 0
                return (
                  <div key={coin.symbol} className="crypto-coin clickable" onClick={() => setDetailSymbol(coin.symbol)}>
                    {coinLogo(coin)}
                    <div className="crypto-coin-info">
                      <span className="crypto-coin-symbol">{coin.symbol}</span>
                      <span className="crypto-coin-name">{coin.name}</span>
                    </div>
                    <div className="crypto-coin-price">
                      <span className="crypto-coin-value">{formatMoney(coin.price)} $</span>
                      <span className={`crypto-coin-change ${up ? 'up' : 'down'}`}>
                        {up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}{up ? '+' : ''}{(coin.change24h || 0).toFixed(2)}%
                      </span>
                    </div>
                    <div className="crypto-coin-actions">
                      <button className="crypto-buy" onClick={(e) => { e.stopPropagation(); openTrade(coin, 'buy') }}><ArrowDownLeft size={14} /> {t('common.buy')}</button>
                      <button className="crypto-sell" onClick={(e) => { e.stopPropagation(); openTrade(coin, 'sell') }} disabled={!holdingFor(coin.symbol)}><ArrowUpRight size={14} /> {t('common.sell')}</button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* ПРАВО: кошелёк, активы, перевод, прогноз, история */}
        <div className="crypto-col-side">
          <div className="crypto-wallet-card">
            <span className="crypto-card-label"><Wallet size={14} /> {t('crypto.wallet')}</span>
            <div className="crypto-wallet-row">
              <code className="crypto-wallet-addr">{account.wallet}</code>
              <button className="crypto-copy-btn" onClick={handleCopy} title={t('common.confirm')}>{copied ? <Check size={15} /> : <Copy size={15} />}</button>
            </div>
            <div className="crypto-wallet-stats">
              <div><span>{t('crypto.cashBalance')}</span><b>{formatMoney(balance)} $</b></div>
              <div><span>{t('crypto.portfolioValue')}</span><b className="accent">{formatMoney(account.portfolioValue)} $</b></div>
            </div>
          </div>

          {/* Мои активы — с логотипами, кликабельные */}
          <div className="crypto-section">
            <h3>{t('crypto.myAssets')}</h3>
            {account.holdings?.length > 0 ? (
              <div className="crypto-holdings">
                {account.holdings.map(h => {
                  const mk = marketMap[h.symbol]
                  const pnl = (h.price - h.avgPrice) * h.quantity
                  const up = pnl >= 0
                  const ch = mk?.change24h || 0
                  return (
                    <div key={h.symbol} className="crypto-holding clickable" onClick={() => setDetailSymbol(h.symbol)}>
                      {coinLogo({ ...mk, symbol: h.symbol, color: h.color })}
                      <div className="crypto-holding-info">
                        <span className="crypto-holding-symbol">{h.symbol}</span>
                        <span className="crypto-holding-qty">{formatCoin(h.quantity)}</span>
                      </div>
                      <div className="crypto-holding-values">
                        <span className="crypto-holding-value">{formatMoney(h.value)} $</span>
                        <span className={`crypto-holding-pnl ${up ? 'up' : 'down'}`}>{up ? '+' : '−'}{formatMoney(Math.abs(pnl))} $</span>
                      </div>
                      <span className={`crypto-holding-ch ${ch >= 0 ? 'up' : 'down'}`}>{ch >= 0 ? '+' : ''}{ch.toFixed(1)}%</span>
                    </div>
                  )
                })}
              </div>
            ) : <p className="empty-state">{t('crypto.noAssets')}</p>}
          </div>

          {/* Перевод */}
          <div className="crypto-section">
            <h3><Send size={16} /> {t('cryptoTransfer.title')}</h3>
            <form className="crypto-transfer-form" onSubmit={handleTransfer}>
              <input placeholder={t('cryptoTransfer.recipient')} value={transfer.recipient} onChange={e => setTransfer({ ...transfer, recipient: e.target.value })} />
              <select value={transfer.symbol} onChange={e => setTransfer({ ...transfer, symbol: e.target.value })}>
                <option value="">{t('cryptoTransfer.selectCoin')}</option>
                {(account?.holdings || []).map(h => <option key={h.symbol} value={h.symbol}>{h.symbol} · {formatCoin(h.quantity)}</option>)}
              </select>
              <input type="number" min="0" step="any" placeholder={t('cryptoTransfer.amount')} value={transfer.amount} onChange={e => setTransfer({ ...transfer, amount: e.target.value })} />
              <button className="crypto-open-btn" type="submit" disabled={transferBusy}><Send size={15} /> {transferBusy ? t('bank.processing') : t('cryptoTransfer.send')}</button>
            </form>
            <p className="crypto-transfer-fee">{t('cryptoTransfer.fee')}</p>
            {transferMsg && (
              <div className={`transfer-feedback ${transferMsg.type}`}>
                {transferMsg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{transferMsg.text}</span>
              </div>
            )}
            {transfers.length > 0 && (
              <div className="crypto-transfer-history">
                {transfers.map(tr => (
                  <div key={tr.id} className={`crypto-transfer-row ${tr.direction}`}>
                    <span className="ctr-dir">{tr.direction === 'out' ? <ArrowUpRight size={14} /> : <ArrowDownLeft size={14} />}</span>
                    <span className="ctr-main">{tr.direction === 'out' ? t('cryptoTransfer.to') : t('cryptoTransfer.from')} <b>{tr.counterparty}</b></span>
                    <span className={`ctr-amount ${tr.direction}`}>{tr.direction === 'out' ? '−' : '+'}{formatCoin(tr.amount)} {tr.symbol}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Прогноз — между переводом и историей */}
          <div className="crypto-section">
            <h3><Activity size={16} /> {t('crypto.forecast')}</h3>
            <div className="crypto-forecast">
              {forecastCoins.map(c => {
                const f = forecast(c)
                return (
                  <div key={c.symbol} className="cf-card clickable" onClick={() => setDetailSymbol(c.symbol)}>
                    <div className="cf-head">{coinLogo(c)}<span>{c.symbol}</span></div>
                    <div className="cf-row"><span>{t('crypto.trend')}</span><b className={f.up ? 'up' : 'down'}>{f.up ? t('crypto.trendUp') : t('crypto.trendDown')}</b></div>
                    <div className="cf-row"><span>{t('crypto.change24')}</span><b className={f.up ? 'up' : 'down'}>{f.change >= 0 ? '+' : ''}{f.change.toFixed(2)}%</b></div>
                    <div className="cf-row"><span>{t('crypto.volatility')}</span><b>{f.vol}%</b></div>
                    <div className="cf-prob">
                      <div className="cf-prob-bar"><div className="cf-prob-fill" style={{ width: `${f.probUp}%` }} /></div>
                      <span className="cf-prob-label"><b className="up">{f.probUp}%</b> {t('crypto.probUp')}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="crypto-section">
            <h3>{t('bank.history')}</h3>
            <TransactionsPanel category="crypto" refreshKey={refreshKey} />
          </div>
        </div>
      </div>

      {trade && (
        <div className="crypto-modal-overlay" onClick={() => !busy && setTrade(null)}>
          <div className="crypto-modal" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setTrade(null)}><X size={18} /></button>
            <h3>{trade.action === 'buy' ? t('common.buy') : t('common.sell')} {trade.symbol}</h3>
            <p className="crypto-modal-price">{formatMoney(trade.price)} $ / {trade.symbol}</p>
            <label className="transfer-field">
              <span>{t('common.quantity')}</span>
              <input type="number" min="0" step="any" value={qty} autoFocus onChange={e => setQty(e.target.value)} placeholder="0.00" />
            </label>
            <div className="crypto-modal-total">{t('common.total')}: <strong>{formatMoney((parseFloat(qty) || 0) * trade.price)} $</strong></div>
            <div className="crypto-modal-fee">{t('trade.fee', { pct: 0.5 })}: {formatMoney((parseFloat(qty) || 0) * trade.price * 0.005)} $</div>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
              </div>
            )}
            <button className={`crypto-confirm ${trade.action}`} onClick={confirmTrade} disabled={busy}>
              {busy ? t('bank.processing') : trade.action === 'buy' ? t('common.buy') : t('common.sell')}
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmTransfer}
        busy={transferBusy}
        title={t('cryptoTransfer.title', 'Перевод криптовалюты')}
        message={confirmTransfer ? t('confirm.cryptoTransfer', { amount: formatCoin(confirmTransfer.amount), symbol: confirmTransfer.symbol, recipient: confirmTransfer.recipient }) : ''}
        confirmLabel={t('cryptoTransfer.send', 'Отправить')}
        onConfirm={doTransfer}
        onCancel={() => setConfirmTransfer(null)}
      />
    </div>
  )
}

export default CryptoTab
