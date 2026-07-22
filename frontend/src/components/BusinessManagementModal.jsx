import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchBusinessDashboard, fetchBusinessHistory, hireBusinessEmployee,
  fireBusinessEmployee, updateBusinessEmployee, withdrawBusinessBalance,
  buyTaxiVehicle, attachTaxiVehicle, assignTaxiVehicle, repairTaxiVehicle,
  refuelTaxiVehicle, fetchMyAssets, upgradeAsset,
} from '../services/api'
import { formatMoney } from './TransactionsPanel'
import {
  X, LayoutDashboard, Wallet, Users, Car, History, ArrowUpCircle,
  UserPlus, Trash2, Wrench, Fuel, Download, RefreshCw,
} from 'lucide-react'

function BusinessManagementModal({ asset, onClose, onBalanceChange, onChanged }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState('overview')
  const [data, setData] = useState(null)
  const [history, setHistory] = useState([])
  const [personalCars, setPersonalCars] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [employee, setEmployee] = useState({ name: '', role: asset.slug === 'taxi_fleet' ? 'driver' : 'worker', salary: '20' })

  const load = useCallback(async () => {
    try {
      const dashboard = await fetchBusinessDashboard(asset.id)
      setData(dashboard)
      setError('')
      if (asset.slug === 'taxi_fleet') {
        const mine = await fetchMyAssets('car')
        setPersonalCars(mine.assets || [])
      }
    } catch (err) {
      setError(err.message)
    }
  }, [asset.id, asset.slug])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (tab === 'history') fetchBusinessHistory(asset.id).then(setHistory).catch(err => setError(err.message))
  }, [asset.id, tab])

  const run = async (fn) => {
    setBusy(true)
    setError('')
    try {
      const result = await fn()
      if (result?.balance != null) onBalanceChange?.(result.balance)
      await load()
      onChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-content business-manager" onClick={e => e.stopPropagation()}>
          <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
          {error ? <div className="error-state"><p>{error}</p></div> : <div className="loading-state"><div className="spinner" /></div>}
        </div>
      </div>
    )
  }

  const business = data.business
  const isTaxi = business.slug === 'taxi_fleet'
  const tabs = [
    ['overview', LayoutDashboard, t('businessManager.overview')],
    ['finance', Wallet, t('businessManager.finance')],
    ['employees', Users, t('businessManager.employees')],
    ...(isTaxi ? [['fleet', Car, t('businessManager.fleet')]] : []),
    ['history', History, t('businessManager.history')],
  ]

  return (
    <div className="modal-overlay" onClick={() => !busy && onClose()}>
      <div className="modal-content business-manager" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <div className="business-manager-head">
          <div>
            <span className="business-manager-kicker">{t('businessManager.management')}</span>
            <h3>{business.name}</h3>
          </div>
          <span className="business-manager-level">Lv.{business.level}</span>
        </div>

        <div className="business-manager-tabs">
          {tabs.map(([id, Icon, label]) => (
            <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>

        {error && <div className="transfer-feedback error">{error}</div>}

        {tab === 'overview' && (
          <div className="business-manager-section">
            <div className="business-kpis">
              <div><span>{t('businessManager.income')}</span><b className="up">${formatMoney(data.stats.incomePerHour)}/h</b></div>
              <div><span>{t('businessManager.expenses')}</span><b className="down">${formatMoney(data.stats.upkeepPerHour)}/h</b></div>
              <div><span>{t('businessManager.netProfit')}</span><b>${formatMoney(data.stats.profitPerHour)}/h</b></div>
              <div><span>{t('businessManager.staffing')}</span><b>{data.employees.length}/{data.employeeCapacity}</b></div>
            </div>
            <div className="business-mechanic">
              <span>{data.stats.metric || t('businessManager.specialization')}</span>
              <b>{isTaxi ? data.vehicles.filter(v => v.driver).length : Math.round(Math.min(100, 35 + business.level * 12))}%</b>
            </div>
            {Object.keys(business.effect || {}).length > 0 && (
              <div className="business-effects">
                {Object.entries(business.effect).map(([key, value]) => (
                  <span key={key}>{t(`businessEffects.${key}`, key)}: <b>{value < 1 ? `${Math.round(value * 100)}%` : value}</b></span>
                ))}
              </div>
            )}
            <button className="stock-btn buy-btn" disabled={busy}
              onClick={() => run(() => upgradeAsset(asset.id))}>
              <ArrowUpCircle size={15} /> {t('myassets.upgrade')} · ${formatMoney(business.upgradeCost)}
            </button>
          </div>
        )}

        {tab === 'finance' && (
          <div className="business-manager-section">
            <div className="business-balance">
              <span>{t('businessManager.enterpriseBalance')}</span>
              <strong>${formatMoney(data.balance)}</strong>
              <small>{t('businessManager.lifetimeProfit')}: ${formatMoney(data.lifetimeProfit)}</small>
            </div>
            <div className="business-finance-grid">
              <div><span>{t('businessManager.hourlyRevenue')}</span><b>${formatMoney(data.stats.incomePerHour)}</b></div>
              <div><span>{t('businessManager.hourlyCosts')}</span><b>${formatMoney(data.stats.upkeepPerHour)}</b></div>
            </div>
            <button className="stock-btn buy-btn" disabled={busy || data.balance <= 0}
              onClick={() => run(() => withdrawBusinessBalance(asset.id))}>
              <Download size={15} /> {t('businessManager.withdraw')}
            </button>
          </div>
        )}

        {tab === 'employees' && (
          <div className="business-manager-section">
            <div className="business-hire-form">
              <input value={employee.name} placeholder={t('businessManager.employeeName')}
                onChange={e => setEmployee({ ...employee, name: e.target.value })} />
              <select value={employee.role} onChange={e => setEmployee({ ...employee, role: e.target.value })}>
                <option value="worker">{t('businessManager.worker')}</option>
                <option value="manager">{t('businessManager.manager')}</option>
                {isTaxi && <option value="driver">{t('businessManager.driver')}</option>}
              </select>
              <input type="number" min="1" value={employee.salary}
                onChange={e => setEmployee({ ...employee, salary: e.target.value })} />
              <button disabled={busy || employee.name.trim().length < 2}
                onClick={() => run(async () => {
                  await hireBusinessEmployee(asset.id, { ...employee, salary: Number(employee.salary) })
                  setEmployee({ ...employee, name: '' })
                })}><UserPlus size={15} /></button>
            </div>
            <div className="business-employee-list">
              {data.employees.map(row => (
                <div key={row.id}>
                  <div><b>{row.name}</b><span>{t(`businessManager.${row.role}`, row.role)}</span></div>
                  <label>
                    $<input type="number" defaultValue={row.salary}
                      onBlur={e => {
                        const salary = Number(e.target.value)
                        if (salary > 0 && salary !== row.salary) run(() => updateBusinessEmployee(asset.id, row.id, salary))
                      }} />/h
                  </label>
                  <button disabled={busy} onClick={() => run(() => fireBusinessEmployee(asset.id, row.id))}><Trash2 size={14} /></button>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === 'fleet' && (
          <div className="business-manager-section">
            <div className="business-fleet-buy">
              {(data.vehicleCatalog || []).map(car => (
                <button key={car.slug} disabled={busy} onClick={() => run(() => buyTaxiVehicle(asset.id, car.slug))}>
                  <Car size={14} /> {t(`assetNames.${car.slug}`, car.name)} · ${formatMoney(car.price)}
                </button>
              ))}
            </div>
            {personalCars.length > 0 && (
              <div className="business-attach">
                <span>{t('businessManager.attachOwned')}</span>
                {personalCars.map(car => (
                  <button key={car.id} disabled={busy} onClick={() => run(() => attachTaxiVehicle(asset.id, car.id))}>
                    {t(`assetNames.${car.slug}`, car.name)}
                  </button>
                ))}
              </div>
            )}
            <div className="business-fleet-list">
              {data.vehicles.map(vehicle => (
                <div key={vehicle.id}>
                  <div className="fleet-car-title"><b>{vehicle.name}</b><span>${formatMoney(vehicle.incomePerHour)}/h</span></div>
                  <div className="fleet-bars">
                    <span>{t('car.condition')} <b>{vehicle.condition}%</b></span>
                    <span>{t('businessManager.fuel')} <b>{vehicle.fuel}%</b></span>
                    <span>{t('businessManager.totalEarnings')} <b>${formatMoney(vehicle.totalEarnings)}</b></span>
                  </div>
                  <select value={vehicle.driver?.id || ''} disabled={busy}
                    onChange={e => e.target.value && run(() => assignTaxiVehicle(asset.id, vehicle.id, e.target.value))}>
                    <option value="">{t('businessManager.noDriver')}</option>
                    {data.employees.filter(x => x.role === 'driver' || x.role === 'worker').map(driver => (
                      <option key={driver.id} value={driver.id}>{driver.name}</option>
                    ))}
                  </select>
                  <div className="fleet-actions">
                    <button disabled={busy || vehicle.condition >= 100}
                      onClick={() => run(() => repairTaxiVehicle(asset.id, vehicle.id))}><Wrench size={14} /> {t('businessManager.repair')}</button>
                    <button disabled={busy || vehicle.fuel >= 100}
                      onClick={() => run(() => refuelTaxiVehicle(asset.id, vehicle.id))}><Fuel size={14} /> {t('businessManager.refuel')}</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === 'history' && (
          <div className="business-manager-section">
            <button className="business-refresh" onClick={() => fetchBusinessHistory(asset.id).then(setHistory)}><RefreshCw size={14} /></button>
            <div className="business-history">
              {history.map(row => (
                <div key={row.id}>
                  <span>{t(`businessOperations.${row.type}`, row.type)}</span>
                  <b className={(row.amount || 0) >= 0 ? 'up' : 'down'}>{row.amount != null ? `$${formatMoney(row.amount)}` : ''}</b>
                  <time>{row.createdAt ? new Date(row.createdAt).toLocaleString() : ''}</time>
                </div>
              ))}
              {history.length === 0 && <p className="empty-state">{t('businessManager.noOperations')}</p>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default BusinessManagementModal
