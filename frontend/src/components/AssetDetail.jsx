import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchMarketAsset, fetchMarketHistory, toggleFavorite, tradeStock, tradeCrypto,
} from '../services/api'
import PriceChart from './PriceChart'
import { formatMoney } from './TransactionsPanel'
import {
  ArrowLeft, Star, TrendingUp, TrendingDown, CandlestickChart, LineChart,
  AlertTriangle, Check, X,
} from 'lucide-react'

const INTERVALS = ['1h', '24h', '7d', '1m', '3m', '6m', '1y', 'all']

function fmtNum(n, digits = 2) {
  if (n == null) return '—'
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' млрд'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' млн'
  return Number(n).toLocaleString('ru-RU', { maximumFractionDigits: digits })
}

function Change({ value }) {
  if (value == null) return <span className="ad-change flat">—</span>
  const up = value >= 0
  return (
    <span className={`ad-change ${up ? 'up' : 'down'}`}>
      {up ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
      {up ? '+' : ''}{value.toFixed(2)}%
    </span>
  )
}

function AssetDetail({ market, symbol, onBack, balance = 0, onBalanceChange, onTraded }) {
  const { t } = useTranslation()
  const [asset, setAsset] = useState(null)
  const [history, setHistory] = useState({ candles: [], line: [] })
  const [timeframe, setTimeframe] = useState('7d')
  const [chartType, setChartType] = useState('line')
  const [loading, setLoading] = useState(true)
  const [chartLoading, setChartLoading] = useState(false)
  const [error, setError] = useState(null)
  const [trade, setTrade] = useState(null)   // 'buy' | 'sell'
  const [qty, setQty] = useState('1')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)

  const loadAsset = useCallback(async () => {
    try {
      const data = await fetchMarketAsset(market, symbol)
      setAsset(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [market, symbol])

  const loadHistory = useCallback(async (iv) => {
    setChartLoading(true)
    try {
      const h = await fetchMarketHistory(market, symbol, iv)
      setHistory(h)
    } catch { /* ignore */ } finally {
      setChartLoading(false)
    }
  }, [market, symbol])

  useEffect(() => { loadAsset() }, [loadAsset])
  useEffect(() => { loadHistory(timeframe) }, [loadHistory, timeframe])

  const doFavorite = async () => {
    try {
      const res = await toggleFavorite(market, symbol)
      setAsset(a => a ? { ...a, isFavorite: res.favorite } : a)
    } catch { /* ignore */ }
  }

  const doTrade = async () => {
    const q = market === 'stock' ? Math.floor(Number(qty)) : Number(qty)
    if (!(q > 0)) { setFeedback({ type: 'error', text: t('bank.invalidAmount') }); return }
    setBusy(true)
    setFeedback(null)
    try {
      const fn = market === 'stock' ? tradeStock : tradeCrypto
      const res = await fn(symbol, trade, q)
      onBalanceChange?.(res.balance)
      setFeedback({ type: 'success', text: t('stocks.tradeSuccess') })
      await Promise.all([loadAsset(), loadHistory(timeframe)])
      onTraded?.()
      setTimeout(() => setTrade(null), 700)
    } catch (err) {
      setFeedback({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="asset-detail">
        <button className="shop-back-btn" onClick={onBack}><ArrowLeft size={18} /> {t('common.back')}</button>
        <div className="asset-card skeleton" style={{ height: 120, marginTop: 'var(--spacing-md)' }} />
        <div className="asset-card skeleton" style={{ height: 340, marginTop: 'var(--spacing-md)' }} />
      </div>
    )
  }

  if (error || !asset) {
    return (
      <div className="asset-detail">
        <button className="shop-back-btn" onClick={onBack}><ArrowLeft size={18} /> {t('common.back')}</button>
        <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>
      </div>
    )
  }

  const changes = asset.stats?.changes || {}
  const held = asset.heldQuantity || 0

  return (
    <div className="asset-detail">
      <button className="shop-back-btn" onClick={onBack}><ArrowLeft size={18} /> {t('common.back')}</button>

      {/* Шапка */}
      <div className="ad-header">
        <span className="ad-logo" style={{ background: asset.color || 'var(--color-accent)' }}>{asset.logo}</span>
        <div className="ad-title">
          <div className="ad-name-row">
            <h2>{asset.name}</h2>
            <span className="ad-ticker">{asset.symbol}</span>
            <button className={`ad-fav ${asset.isFavorite ? 'active' : ''}`} onClick={doFavorite} title={t('asset.favorite')}>
              <Star size={16} fill={asset.isFavorite ? '#fbbf24' : 'none'} />
            </button>
          </div>
          <div className="ad-sector">{asset.sector}{asset.issuerName ? ` · ${asset.issuerName}` : ''}</div>
        </div>
        <div className="ad-price-block">
          <span className="ad-price">${formatMoney(asset.price)}</span>
          <Change value={asset.changePercent} />
        </div>
      </div>

      {/* Статы */}
      <div className="ad-stats-grid">
        <div className="ad-stat"><span>{t('asset.change24h')}</span><Change value={changes['24h']} /></div>
        <div className="ad-stat"><span>{t('asset.change7d')}</span><Change value={changes['7d']} /></div>
        <div className="ad-stat"><span>{t('asset.change1m')}</span><Change value={changes['1m']} /></div>
        <div className="ad-stat"><span>{t('asset.change1y')}</span><Change value={changes['1y']} /></div>
        <div className="ad-stat"><span>{t('asset.marketCap')}</span><b>${fmtNum(asset.marketCap)}</b></div>
        <div className="ad-stat"><span>{t('asset.volume')}</span><b>${fmtNum(asset.volume24h)}</b></div>
        {market === 'stock' && <div className="ad-stat"><span>{t('asset.shares')}</span><b>{fmtNum(asset.totalShares, 0)}</b></div>}
        {market === 'stock' && <div className="ad-stat"><span>{t('common.freeShares')}</span><b>{fmtNum(asset.freeShares, 0)}</b></div>}
        {market === 'crypto' && <div className="ad-stat"><span>{t('asset.supply')}</span><b>{fmtNum(asset.supply, 0)}</b></div>}
        {market === 'crypto' && <div className="ad-stat"><span>{t('asset.ath')}</span><b>${formatMoney(asset.ath)}</b></div>}
        {market === 'crypto' && <div className="ad-stat"><span>{t('asset.atl')}</span><b>${formatMoney(asset.atl)}</b></div>}
        {held > 0 && <div className="ad-stat"><span>{t('stocks.owned')}</span><b className="up">{fmtNum(held, market === 'crypto' ? 4 : 0)}</b></div>}
      </div>

      {asset.description && <p className="ad-description">{asset.description}</p>}

      {/* График */}
      <div className="ad-chart-card">
        <div className="ad-chart-toolbar">
          <div className="ad-intervals">
            {INTERVALS.map(iv => (
              <button key={iv} className={`ad-iv ${timeframe === iv ? 'active' : ''}`} onClick={() => setTimeframe(iv)}>
                {t(`asset.iv_${iv}`)}
              </button>
            ))}
          </div>
          <div className="ad-charttype">
            <button className={chartType === 'line' ? 'active' : ''} onClick={() => setChartType('line')} title={t('asset.line')}><LineChart size={15} /></button>
            <button className={chartType === 'candle' ? 'active' : ''} onClick={() => setChartType('candle')} title={t('asset.candle')}><CandlestickChart size={15} /></button>
          </div>
        </div>
        <div className={`ad-chart ${chartLoading ? 'loading' : ''}`}>
          <PriceChart
            candles={history.candles}
            line={history.line}
            type={chartType}
            color={asset.color || '#6366f1'}
            height={340}
          />
        </div>
        <p className="ad-chart-hint">{t('asset.chartHint')}</p>
      </div>

      {/* Действия */}
      <div className="ad-actions">
        <button className="ad-buy" onClick={() => { setTrade('buy'); setQty('1'); setFeedback(null) }}>{t('common.buy')}</button>
        <button className="ad-sell" onClick={() => { setTrade('sell'); setQty('1'); setFeedback(null) }} disabled={held <= 0}>{t('common.sell')}</button>
        <button className={`ad-fav-btn ${asset.isFavorite ? 'active' : ''}`} onClick={doFavorite}>
          <Star size={16} fill={asset.isFavorite ? '#fbbf24' : 'none'} /> {t('asset.favorite')}
        </button>
      </div>

      {/* Модалка сделки */}
      {trade && (
        <div className="modal-overlay" onClick={() => !busy && setTrade(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <button className="crypto-modal-close" onClick={() => setTrade(null)}><X size={18} /></button>
            <h3>{trade === 'buy' ? t('common.buy') : t('common.sell')} {asset.symbol}</h3>
            <p className="modal-price">{t('stocks.pricePerShare')}: ${formatMoney(asset.price)}</p>
            <div className="modal-quantity">
              <label>{t('common.quantity')}:</label>
              <input type="number" min={market === 'crypto' ? '0' : '1'} step={market === 'crypto' ? 'any' : '1'} value={qty} autoFocus
                onChange={e => setQty(e.target.value)} />
            </div>
            <p className="modal-total">{t('common.total')}: <strong>${formatMoney((Number(qty) || 0) * asset.price)}</strong></p>
            {feedback && (
              <div className={`transfer-feedback ${feedback.type}`}>
                {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{feedback.text}</span>
              </div>
            )}
            <div className="modal-buttons">
              <button className={`stock-btn ${trade === 'buy' ? 'buy-btn' : 'sell-btn'}`} onClick={doTrade} disabled={busy}>
                {busy ? t('bank.processing') : t('common.confirm')}
              </button>
              <button className="stock-btn cancel-btn" onClick={() => setTrade(null)} disabled={busy}>{t('common.cancel')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AssetDetail
