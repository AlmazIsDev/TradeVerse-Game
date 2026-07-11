import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Wrench, Filter, DollarSign, ArrowUpDown } from 'lucide-react'
import BuyModal from './BuyModal'
import ShopCard from './ShopCard'
import { applyShopPrices } from '../utils/shopPrices'

const SUPPLIES_PRODUCTS = [
  { id: 1, name: 'Охлаждающая жидкость', price: null, category: 'cooling' },
  { id: 2, name: 'Чип для улучшения видеокарты', price: null, category: 'upgrade' },
]

const CATEGORIES = [
  { id: 'cooling', labelKey: 'supplies.cooling' },
  { id: 'upgrade', labelKey: 'supplies.upgrade' },
]

function SuppliesShop({ onBack }) {
  const { t } = useTranslation()
  const [selectedCategory, setSelectedCategory] = useState('')
  const [priceFrom, setPriceFrom] = useState('')
  const [priceTo, setPriceTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState(null)
  const [sortOrder, setSortOrder] = useState('asc')
  const [selectedProduct, setSelectedProduct] = useState(null)

  const filteredProducts = useMemo(() => {
    let result = applyShopPrices(SUPPLIES_PRODUCTS).filter(product => {
      if (selectedCategory && product.category !== selectedCategory) return false
      if (priceFrom && product.price !== null && product.price < Number(priceFrom)) return false
      if (priceTo && product.price !== null && product.price > Number(priceTo)) return false
      return true
    })

    if (sortBy) {
      result.sort((a, b) => {
        let compare = 0
        if (sortBy === 'price') {
          const priceA = a.price ?? 0
          const priceB = b.price ?? 0
          compare = priceA - priceB
        } else if (sortBy === 'name') {
          compare = a.name.localeCompare(b.name)
        } else {
          compare = a.category.localeCompare(b.category)
        }
        return sortOrder === 'asc' ? compare : -compare
      })
    }

    return result
  }, [selectedCategory, priceFrom, priceTo, sortBy, sortOrder])

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
          <span>{t('shop.gpu')}</span>
        </button>
        <h2 className="tab-title">{t('shop.gpuSupplies')}</h2>
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
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} />
          <span>{t('common.price')}</span>
          {sortBy === 'price' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'category' ? 'active' : ''}`} onClick={() => toggleSort('category')}>
          <ArrowUpDown size={14} />
          <span>{t('supplies.category')}</span>
          {sortBy === 'category' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        {showFilters && (
          <div className="gpu-filter-panel">
            <div className="gpu-filter-row">
              <label>{t('supplies.category')}</label>
              <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {CATEGORIES.map(c => <option key={c.id} value={c.id}>{t(c.labelKey)}</option>)}
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
          </div>
        )}
      </div>

      <div className="shop-grid">
        {filteredProducts.map(product => (
          <ShopCard
            key={product.id}
            icon={Wrench}
            name={product.name}
            specs={[]}
            price={product.price}
            colors={{ bg: 'rgba(168, 85, 247, 0.10)', border: 'rgba(168, 85, 247, 0.3)', icon: '#c084fc', accent: '#a855f7' }}
            onBuy={() => setSelectedProduct(product)}
          />
        ))}
      </div>

      {selectedProduct && (
        <BuyModal product={selectedProduct} onClose={() => setSelectedProduct(null)} />
      )}
    </div>
  )
}

export { SUPPLIES_PRODUCTS }
export default SuppliesShop
