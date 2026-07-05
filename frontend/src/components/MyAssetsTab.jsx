import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchMyAssets, collectAsset, upgradeAsset, sellAsset } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  Home, Briefcase, ArrowUpCircle, HandCoins, Trash2, AlertTriangle,
  TrendingUp, Users, Wallet,
} from 'lucide-react'

/**
 * Универсальный экран владения активами. Используется для «Мои дома»
 * (types=['realestate','car']) и «Мои бизнесы» (types=['business']).
 */
function MyAssetsTab({ types, titleKey, icon: TitleIcon = Home, balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchMyAssets()
      const filtered = (data.assets || []).filter(a => types.includes(a.type))
      setAssets(filtered)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [types])

  useEffect(() => { load() }, [load])

  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 2200)
  }

  const act = async (id, fn, successKey) => {
    setBusyId(id)
    try {
      const res = await fn(id)
      if (res.balance != null) onBalanceChange?.(res.balance)
      flash(t(successKey))
      await load()
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const totalValue = assets.reduce((s, a) => s + (a.value || 0), 0)
  const totalProfit = assets.reduce((s, a) => s + (a.profitPerHour || 0), 0)
  const totalAccrued = assets.reduce((s, a) => s + (a.accrued || 0), 0)
  const isBusiness = types.includes('business')

  return (
    <div className="myassets-tab">
      <div className="leaderboard-title-row">
        <TitleIcon size={22} className="icon" />
        <h2 className="tab-title">{t(titleKey)}</h2>
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <TrendingUp size={16} /> : <AlertTriangle size={16} />}
          <span>{msg.text}</span>
        </div>
      )}

      {!loading && !error && assets.length > 0 && (
        <div className="asset-summary">
          <div className="asset-summary-card"><span>{t('myassets.totalValue')}</span><b>${formatMoney(totalValue)}</b></div>
          <div className="asset-summary-card"><span>{t('myassets.profitPerHour')}</span><b className="up">${formatMoney(totalProfit)}</b></div>
          <div className="asset-summary-card"><span>{t('myassets.readyToCollect')}</span><b className="up">${formatMoney(totalAccrued)}</b></div>
        </div>
      )}

      {loading && (
        <div className="asset-grid">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="asset-card skeleton" style={{ height: 200 }} />)}
        </div>
      )}

      {error && (
        <div className="error-state">
          <AlertTriangle size={24} className="error-icon" color="#fca5a5" />
          <p>{t('common.error')}: {error}</p>
        </div>
      )}

      {!loading && !error && assets.length === 0 && (
        <div className="empty-state">
          <span className="placeholder-icon"><TitleIcon size={48} /></span>
          <p>{t('myassets.empty')}</p>
        </div>
      )}

      {!loading && !error && assets.length > 0 && (
        <div className="asset-grid">
          {assets.map(a => {
            const busy = busyId === a.id
            return (
              <div key={a.id} className="asset-card owned">
                <div className="asset-card-head">
                  <span className="asset-name">{a.name}</span>
                  <span className="asset-level">{t('myassets.level')} {a.level}</span>
                </div>
                <div className="asset-stats">
                  <div className="asset-stat"><span>{t('myassets.value')}</span><b>${formatMoney(a.value)}</b></div>
                  {a.profitPerHour !== 0 && (
                    <div className="asset-stat"><span>{t('market.profitPerHour')}</span>
                      <b className={a.profitPerHour >= 0 ? 'up' : 'down'}>${formatMoney(a.profitPerHour)}</b></div>
                  )}
                  {isBusiness && (
                    <>
                      <div className="asset-stat"><span><Users size={12} /> {t('market.employees')}</span><b>{a.employees}</b></div>
                      <div className="asset-stat"><span>{t('myassets.upkeep')}</span><b className="down">${formatMoney(a.upkeepPerHour)}/ч</b></div>
                    </>
                  )}
                  {a.rooms != null && <div className="asset-stat"><span>{t('realestate.rooms')}</span><b>{a.rooms}</b></div>}
                  {a.meta?.tax != null && <div className="asset-stat"><span>{t('myassets.tax')}</span><b className="down">${a.meta.tax}/ч</b></div>}
                  {a.meta?.prestige != null && <div className="asset-stat"><span>{t('market.prestige')}</span><b>{a.meta.prestige}</b></div>}
                </div>

                {a.profitPerHour > 0 && (
                  <div className="asset-accrued">
                    <Wallet size={14} /> {t('myassets.accrued')}: <b>${formatMoney(a.accrued)}</b>
                  </div>
                )}

                <div className="asset-actions">
                  {a.profitPerHour > 0 && (
                    <button className="asset-act collect" disabled={busy || a.accrued <= 0} onClick={() => act(a.id, collectAsset, 'myassets.collected')}>
                      <HandCoins size={15} /> {t('myassets.collect')}
                    </button>
                  )}
                  <button className="asset-act upgrade" disabled={busy} onClick={() => act(a.id, upgradeAsset, 'myassets.upgraded')}>
                    <ArrowUpCircle size={15} /> {t('myassets.upgrade')} (${formatMoney(a.upgradeCost)})
                  </button>
                  <button className="asset-act sell" disabled={busy} onClick={() => act(a.id, sellAsset, 'myassets.sold')}>
                    <Trash2 size={15} /> {t('myassets.sell')}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default MyAssetsTab
