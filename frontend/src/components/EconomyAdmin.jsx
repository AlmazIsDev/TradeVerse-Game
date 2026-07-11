import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchEconomyAnalytics, fetchEconomyConfig, updateEconomyConfig,
  fetchEconomyEvents, startEconomyEvent, stopEconomyEvent,
} from '../services/api'
import { formatCompact } from './TransactionsPanel'
import {
  DollarSign, Users, Home, Briefcase, Car, Building2, Coins, LineChart,
  Activity, Save, Check, AlertTriangle, Wallet, Zap, Square,
} from 'lucide-react'

const CONFIG_FIELDS = [
  { key: 'economy_mult', step: 0.05 },
  { key: 'income_mult', step: 0.05 },
  { key: 'rent_mult', step: 0.05 },
  { key: 'tax_rate', step: 0.01 },
  { key: 'inflation', step: 0.01 },
  { key: 'energy_cost', step: 0.01 },
  { key: 'wc_price', step: 1 },
]

function EconomyAdmin() {
  const { t } = useTranslation()
  const [analytics, setAnalytics] = useState(null)
  const [config, setConfig] = useState(null)
  const [events, setEvents] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [a, c, e] = await Promise.all([
        fetchEconomyAnalytics(), fetchEconomyConfig(), fetchEconomyEvents().catch(() => null),
      ])
      setAnalytics(a)
      setConfig(c)
      setEvents(e)
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    } finally {
      setLoading(false)
    }
  }, [])

  const runEvent = async (fn) => {
    try {
      await fn()
      setEvents(await fetchEconomyEvents())
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    }
  }

  useEffect(() => { load() }, [load])

  // Живые обновления: аналитика приходит периодическим пушем только админам
  // (см. push_to_admins в scheduler.py), события — тем же broadcast, что и
  // NotificationCenter, но здесь мы ещё и обновляем список активных/историю.
  useEffect(() => {
    const onRealtime = (ev) => {
      const d = ev.detail
      if (d?.type === 'economy_stats' && d.stats) {
        setAnalytics(d.stats)
      } else if (d?.type === 'event' || d?.type === 'event_ended') {
        fetchEconomyEvents().then(setEvents).catch(() => {})
      }
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [])

  const save = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const payload = {}
      CONFIG_FIELDS.forEach(f => { payload[f.key] = Number(config[f.key]) })
      const updated = await updateEconomyConfig(payload)
      setConfig(updated)
      setMsg({ type: 'success', text: t('econ.saved') })
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="asset-card skeleton" style={{ height: 260 }} />

  const A = analytics || {}
  const stats = [
    { icon: DollarSign, label: t('econ.moneySupply'), value: '$' + formatCompact(A.moneySupply) },
    { icon: Wallet, label: t('econ.totalCapital'), value: '$' + formatCompact(A.totalCapital) },
    { icon: Users, label: t('econ.avgCapital'), value: '$' + formatCompact(A.avgCapital) },
    { icon: Users, label: t('econ.players'), value: A.users ?? 0 },
    { icon: Activity, label: t('econ.dailyVolume'), value: '$' + formatCompact(A.dailyVolume) },
    { icon: LineChart, label: t('econ.stocksValue'), value: '$' + formatCompact(A.stocks?.value) },
    { icon: Coins, label: t('econ.cryptoValue'), value: '$' + formatCompact(A.crypto?.value) },
    { icon: Home, label: t('econ.realestate'), value: A.assets?.realestate ?? 0 },
    { icon: Briefcase, label: t('econ.business'), value: A.assets?.business ?? 0 },
    { icon: Car, label: t('econ.cars'), value: A.assets?.cars ?? 0 },
    { icon: Building2, label: t('econ.companies'), value: A.companies?.count ?? 0 },
    { icon: Coins, label: 'WarCoin', value: formatCompact(A.warcoin) },
  ]

  return (
    <div className="econ-admin">
      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <h3 className="econ-title"><Activity size={16} /> {t('econ.analytics')}</h3>
      <div className="econ-grid">
        {stats.map((s, i) => {
          const Icon = s.icon
          return (
            <div key={i} className="econ-stat">
              <Icon size={18} />
              <div><span>{s.label}</span><b title={String(s.value)}>{s.value}</b></div>
            </div>
          )
        })}
      </div>

      <h3 className="econ-title"><Save size={16} /> {t('econ.coefficients')}</h3>
      <div className="econ-config">
        {config && CONFIG_FIELDS.map(f => (
          <label key={f.key} className="econ-field">
            <span>{t(`econ.${f.key}`)}</span>
            <input
              type="number" step={f.step}
              value={config[f.key] ?? 0}
              onChange={e => setConfig({ ...config, [f.key]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <button className="admin-btn admin-btn-primary" onClick={save} disabled={saving}>
        <Save size={15} /> {saving ? t('bank.processing') : t('econ.save')}
      </button>

      {events && (
        <>
          <h3 className="econ-title"><Zap size={16} /> {t('econ.events')}</h3>
          {events.active.length > 0 && (
            <div className="econ-events-active">
              {events.active.map(ev => (
                <div key={ev.id} className="econ-event active">
                  <span className="econ-event-icon">{ev.icon}</span>
                  <div className="econ-event-info"><b>{ev.name}</b><span>{t('econ.eventActive')}</span></div>
                  <button className="asset-act sell" onClick={() => runEvent(() => stopEconomyEvent(ev.id))}>
                    <Square size={13} /> {t('econ.stop')}
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="econ-event-types">
            {events.types.map(ty => (
              <button key={ty.type} className="econ-event-type" onClick={() => runEvent(() => startEconomyEvent(ty.type))}>
                <span>{ty.icon}</span> {ty.name}
              </button>
            ))}
          </div>
          {events.history.length > 0 && (
            <div className="econ-event-history">
              <span className="econ-hist-title">{t('econ.eventHistory')}</span>
              {events.history.map(ev => (
                <div key={ev.id} className="econ-hist-row">
                  <span>{ev.icon} {ev.name}</span>
                  <span className="econ-hist-src">{ev.source}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default EconomyAdmin
