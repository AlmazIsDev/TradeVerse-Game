import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Briefcase, Filter, DollarSign, ArrowUpDown, Store } from 'lucide-react'
import BuyModal from './BuyModal'
import { applyShopPrices } from '../utils/shopPrices'

const BUSINESS_PRODUCTS = [
  { id: 1, name: 'Pixel Store', category: 'retail', price: null, income: null },
  { id: 2, name: 'GPU Market', category: 'tech', price: null, income: null },
  { id: 3, name: 'CoreTech Shop', category: 'tech', price: null, income: null },
  { id: 4, name: 'Neon Hardware', category: 'tech', price: null, income: null },
  { id: 5, name: 'Quantum GPUs', category: 'tech', price: null, income: null },
  { id: 6, name: 'Street Kiosk', category: 'retail', price: null, income: null },
  { id: 7, name: 'Mini Market', category: 'retail', price: null, income: null },
  { id: 8, name: 'Urban Shop', category: 'retail', price: null, income: null },
  { id: 9, name: 'Fashion Store', category: 'retail', price: null, income: null },
  { id: 10, name: 'Tech Repair', category: 'service', price: null, income: null },
  { id: 11, name: 'Overclock Lab', category: 'service', price: null, income: null },
  { id: 12, name: 'Crypto Office', category: 'office', price: null, income: null },
]

const CATEGORIES = ['retail', 'tech', 'service', 'office']

const CATEGORY_COLORS = {
  retail: { bg: 'rgba(34, 197, 94, 0.10)', border: 'rgba(34, 197, 94, 0.3)', icon: '#4ade80', accent: '#22c55e' },
  tech: { bg: 'rgba(59, 130, 246, 0.10)', border: 'rgba(59, 130, 246, 0.3)', icon: '#60a5fa', accent: '#3b82f6' },
  service: { bg: 'rgba(249, 115, 22, 0.10)', border: 'rgba(249, 115, 22, 0.3)', icon: '#fb923c', accent: '#f97316' },
  office: { bg: 'rgba(168, 85, 247, 0.10)', border: 'rgba(168, 85, 247, 0.3)', icon: '#c084fc', accent: '#a855f7' },
}

function BusinessShop({ onBack }) {
  const { t } = useTranslation()
  const [selectedCategory, setSelectedCategory] = useState('')
  const [priceFrom, setPriceFrom] = useState('')
  const [priceTo, setPriceTo] = useState('')
  const [incomeFrom, setIncomeFrom] = useState('')
  const [incomeTo, setIncomeTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState(null)
  const [sortOrder, setSortOrder] = useState('asc')
  const [selectedProduct, setSelectedProduct] = useState(null)

  const filteredProducts = useMemo(() => {
    let result = applyShopPrices(BUSINESS_PRODUCTS).filter(product => {
      if (selectedCategory && product.category !== selectedCategory) return false
      if (priceFrom && product.price !== null && product.price < Number(priceFrom)) return false
      if (priceTo && product.price !== null && product.price > Number(priceTo)) return false
      if (incomeFrom && product.income !== null && product.income < Number(incomeFrom)) return false
      if (incomeTo && product.income !== null && product.income > Number(incomeTo)) return false
      return true
    })

    if (sortBy) {
      result.sort((a, b) => {
        let compare = 0
        if (sortBy === 'price') {
          compare = (a.price ?? 0) - (b.price ?? 0)
        } else if (sortBy === 'name') {
          compare = a.name.localeCompare(b.name)
        } else if (sortBy === 'income') {
          compare = (a.income ?? 0) - (b.income ?? 0)
        } else {
          compare = a.category.localeCompare(b.category)
        }
        return sortOrder === 'asc' ? compare : -compare
      })
    }

    return result
  }, [selectedCategory, priceFrom, priceTo, incomeFrom, incomeTo, sortBy, sortOrder])

  const toggleSort = (field) => {
    if (sortBy === field) {
      if (sortOrder === 'asc') {
        setSortOrder('desc')
      } else {
        setSortBy(null)
        setSortOrder('asc')
      }
    } else {
      setSortBy(field)
      setSortOrder('asc')
    }
  }

  return (
    <div className="shop-tab">
      <div className="shop-section-header">
        <button className="shop-back-btn" onClick={onBack}>
          <ArrowLeft size={18} />
          <span>{t('nav.shop')}</span>
        </button>
        <h2 className="tab-title">{t('shop.business')}</h2>
      </div>

      <div className="gpu-toolbar">
        <button className="gpu-filter-toggle" onClick={() => setShowFilters(!showFilters)}>
          <Filter size={16} />
          <span>{t('common.filter')}</span>
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'name' ? 'active' : ''}`} onClick={() => toggleSort('name')}>
          <ArrowUpDown size={14} />
          <span>{t('common.name')}</span>
          {sortBy === 'name' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'category' ? 'active' : ''}`} onClick={() => toggleSort('category')}>
          <Briefcase size={14} />
          <span>{t('business.category')}</span>
          {sortBy === 'category' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'income' ? 'active' : ''}`} onClick={() => toggleSort('income')}>
          <DollarSign size={14} />
          <span>{t('business.income')}</span>
          {sortBy === 'income' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} />
          <span>{t('common.price')}</span>
          {sortBy === 'price' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        {showFilters && (
          <div className="gpu-filter-panel">
            <div className="gpu-filter-row">
              <label>{t('business.category')}</label>
              <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{t(`business.categories.${c}`)}</option>)}
              </select>
            </div>
            <div className="gpu-filter-row">
              <label>{t('common.price')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={priceFrom} onChange={(e) => setPriceFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={priceTo} onChange={(e) => setPriceTo(e.target.value)} />
              </div>
            </div>
            <div className="gpu-filter-row">
              <label>{t('business.income')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={incomeFrom} onChange={(e) => setIncomeFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={incomeTo} onChange={(e) => setIncomeTo(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="gpu-grid">
        {filteredProducts.map(product => {
          const colors = CATEGORY_COLORS[product.category] || CATEGORY_COLORS.retail
          return (
            <div
              key={product.id}
              className="gpu-card"
              style={{ background: colors.bg, borderColor: colors.border }}
            >
              <div className="re-card-header">
                <span className="gpu-card-icon" style={{ background: colors.accent }}><Store size={24} /></span>
                <span className="gpu-card-name">{product.name}</span>
              </div>
              <div className="gpu-card-specs">
                <Briefcase size={12} style={{ color: colors.icon }} />
                <span>{t(`business.categories.${product.category}`)}</span>
              </div>
              <div className="gpu-card-price">
                <DollarSign size={12} style={{ color: colors.icon }} />
                <span>{product.price !== null ? `$${product.price.toLocaleString()}` : t('common.notSet')}</span>
              </div>
              <div className="gpu-card-price">
                <DollarSign size={12} style={{ color: colors.icon }} />
                <span>{t('business.income')}: {product.income !== null ? `$${product.income.toLocaleString()}` : t('common.notSet')}</span>
              </div>
              <button className="gpu-card-buy" style={{ background: colors.accent }} onClick={() => setSelectedProduct(product)}>
                {t('common.buy')}
              </button>
            </div>
          )
        })}
      </div>

      {selectedProduct && (
        <BuyModal product={selectedProduct} onClose={() => setSelectedProduct(null)} />
      )}
    </div>
  )
}

export { BUSINESS_PRODUCTS }
export default BusinessShop
