import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Save, Home, Briefcase, Car, Search, RefreshCw } from 'lucide-react'
import { adminFetchAssetCatalog, adminUpdateCatalogItem } from '../services/api'
import { formatMoney } from './TransactionsPanel'

const CATEGORIES = [
  { id: 'realestate', icon: Home },
  { id: 'business', icon: Briefcase },
  { id: 'car', icon: Car },
]

function PriceEditorTab() {
  const { t } = useTranslation()
  const [category, setCategory] = useState('realestate')
  const [items, setItems] = useState([])
  const [forms, setForms] = useState({})
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await adminFetchAssetCatalog()
      setItems(rows)
      setForms(Object.fromEntries(rows.map(row => [row.slug, {
        price: String(row.price),
        income_per_hour: String(row.incomePerHour),
        upkeep_per_hour: String(row.upkeepPerHour),
        sell_rate: String(row.sellRate),
      }])))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const visible = useMemo(() => items.filter(item =>
    item.type === category && (!search || item.name.toLowerCase().includes(search.toLowerCase()) || item.slug.includes(search.toLowerCase()))
  ), [category, items, search])

  const change = (slug, key, value) => setForms(old => ({
    ...old, [slug]: { ...old[slug], [key]: value },
  }))

  const save = async (item) => {
    const form = forms[item.slug]
    setBusy(item.slug)
    setMessage('')
    try {
      await adminUpdateCatalogItem(item.slug, {
        price: Number(form.price),
        income_per_hour: Number(form.income_per_hour),
        upkeep_per_hour: Number(form.upkeep_per_hour),
        sell_rate: Number(form.sell_rate),
      })
      setMessage(t('admin.prices.saved'))
      await load()
    } catch (err) {
      setMessage(err.message)
    } finally {
      setBusy('')
    }
  }

  if (loading) return <div className="loading-state"><div className="spinner" /></div>

  return (
    <div className="price-editor asset-catalog-editor">
      <div className="price-editor-categories">
        {CATEGORIES.map(row => {
          const Icon = row.icon
          const count = items.filter(item => item.type === row.id).length
          return (
            <button key={row.id} className={`price-editor-category-btn ${category === row.id ? 'active' : ''}`}
              onClick={() => setCategory(row.id)}>
              <Icon size={16} />
              <span>{t(`market.cat_${row.id}`)}</span>
              <span className="price-editor-category-stats">{count}</span>
            </button>
          )
        })}
      </div>

      <div className="price-editor-toolbar">
        <div className="price-editor-search">
          <Search size={16} />
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder={t('admin.prices.searchPlaceholder')} />
        </div>
        <button className="admin-btn" onClick={load}><RefreshCw size={14} /></button>
      </div>

      {message && <div className="price-editor-saved-msg">{message}</div>}

      <div className="catalog-admin-list">
        {visible.map(item => {
          const form = forms[item.slug] || {}
          const price = Number(form.price) || 0
          const sellRate = Number(form.sell_rate) || 0
          const rarityRentPct = { common: .024, uncommon: .033, rare: .039, epic: .057, legendary: .078 }[item.rarity] || 0
          return (
            <div key={item.slug} className="catalog-admin-row">
              <div className="catalog-admin-name">
                <strong>{item.name}</strong>
                <span>{item.slug} · {item.rarity}</span>
                {item.mechanic && <span>{item.metric}</span>}
              </div>
              <label>{t('common.price')}
                <input type="number" min="0" value={form.price}
                  onChange={e => change(item.slug, 'price', e.target.value)} />
              </label>
              <label>{t('admin.property.fieldIncome')}
                <input type="number" min="0" value={form.income_per_hour}
                  onChange={e => change(item.slug, 'income_per_hour', e.target.value)} />
              </label>
              <label>{t('admin.property.fieldUpkeep')}
                <input type="number" min="0" value={form.upkeep_per_hour}
                  onChange={e => change(item.slug, 'upkeep_per_hour', e.target.value)} />
              </label>
              <label>{t('admin.prices.sellRate')}
                <input type="number" min=".01" max="1" step=".01" value={form.sell_rate}
                  onChange={e => change(item.slug, 'sell_rate', e.target.value)} />
              </label>
              <div className="catalog-admin-impact">
                <span>{t('admin.prices.sale')}: <b>${formatMoney(price * sellRate)}</b></span>
                <span>{t('admin.prices.rent')}: <b>${formatMoney(item.type === 'business' && !item.slug.startsWith('itstudio_') && item.slug !== 'media_holding' ? 0 : price * rarityRentPct)}</b></span>
                <span>{t('admin.prices.upgrade')}: <b>${formatMoney(price * .4)}</b></span>
              </div>
              <button className="admin-btn admin-btn-primary" disabled={busy === item.slug}
                onClick={() => save(item)}><Save size={14} /></button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default PriceEditorTab
