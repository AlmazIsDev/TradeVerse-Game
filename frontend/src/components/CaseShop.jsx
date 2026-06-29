import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Box, Filter, DollarSign, Layers, ArrowUpDown } from 'lucide-react'
import BuyModal from './BuyModal'

const CASE_PRODUCTS = [
  { id: 1, name: 'TitanFrame Mini M100', maxGpus: 1, price: null, company: 'TitanFrame', line: 'Mini' },
  { id: 2, name: 'TitanFrame Mini M110', maxGpus: 1, price: null, company: 'TitanFrame', line: 'Mini' },
  { id: 3, name: 'TitanFrame Mini M120', maxGpus: 2, price: null, company: 'TitanFrame', line: 'Mini' },
  { id: 4, name: 'TitanFrame Mini M130', maxGpus: 2, price: null, company: 'TitanFrame', line: 'Mini' },
  { id: 5, name: 'TitanFrame Mini M140', maxGpus: 3, price: null, company: 'TitanFrame', line: 'Mini' },
  { id: 6, name: 'TitanFrame Mini M150', maxGpus: 3, price: null, company: 'TitanFrame', line: 'Mini' },
  { id: 7, name: 'TitanFrame Air A200', maxGpus: 4, price: null, company: 'TitanFrame', line: 'Air' },
  { id: 8, name: 'TitanFrame Air A210', maxGpus: 4, price: null, company: 'TitanFrame', line: 'Air' },
  { id: 9, name: 'TitanFrame Air A220', maxGpus: 5, price: null, company: 'TitanFrame', line: 'Air' },
  { id: 10, name: 'TitanFrame Air A230', maxGpus: 5, price: null, company: 'TitanFrame', line: 'Air' },
  { id: 11, name: 'TitanFrame Air A240', maxGpus: 6, price: null, company: 'TitanFrame', line: 'Air' },
  { id: 12, name: 'TitanFrame Air A250', maxGpus: 6, price: null, company: 'TitanFrame', line: 'Air' },
  { id: 13, name: 'TitanFrame Pro P300', maxGpus: 7, price: null, company: 'TitanFrame', line: 'Pro' },
  { id: 14, name: 'TitanFrame Pro P310', maxGpus: 8, price: null, company: 'TitanFrame', line: 'Pro' },
  { id: 15, name: 'TitanFrame Pro P320', maxGpus: 9, price: null, company: 'TitanFrame', line: 'Pro' },
  { id: 16, name: 'TitanFrame Pro P330', maxGpus: 10, price: null, company: 'TitanFrame', line: 'Pro' },
  { id: 17, name: 'TitanFrame Pro P340', maxGpus: 11, price: null, company: 'TitanFrame', line: 'Pro' },
  { id: 18, name: 'TitanFrame Pro P350', maxGpus: 12, price: null, company: 'TitanFrame', line: 'Pro' },
  { id: 19, name: 'TitanFrame Ultra U400', maxGpus: 13, price: null, company: 'TitanFrame', line: 'Ultra' },
  { id: 20, name: 'TitanFrame Ultra U410', maxGpus: 14, price: null, company: 'TitanFrame', line: 'Ultra' },
  { id: 21, name: 'TitanFrame Ultra U420', maxGpus: 15, price: null, company: 'TitanFrame', line: 'Ultra' },
  { id: 22, name: 'TitanFrame Ultra U430', maxGpus: 16, price: null, company: 'TitanFrame', line: 'Ultra' },
  { id: 23, name: 'TitanFrame Ultra U440', maxGpus: 17, price: null, company: 'TitanFrame', line: 'Ultra' },
  { id: 24, name: 'TitanFrame Ultra U450', maxGpus: 18, price: null, company: 'TitanFrame', line: 'Ultra' },
  { id: 25, name: 'TitanFrame Titan T500', maxGpus: 19, price: null, company: 'TitanFrame', line: 'Titan' },
  { id: 26, name: 'TitanFrame Titan T510', maxGpus: 20, price: null, company: 'TitanFrame', line: 'Titan' },
  { id: 27, name: 'TitanFrame Titan T520', maxGpus: 22, price: null, company: 'TitanFrame', line: 'Titan' },
  { id: 28, name: 'TitanFrame Titan T530', maxGpus: 24, price: null, company: 'TitanFrame', line: 'Titan' },
  { id: 29, name: 'TitanFrame Titan T540', maxGpus: 27, price: null, company: 'TitanFrame', line: 'Titan' },
  { id: 30, name: 'TitanFrame Titan T550', maxGpus: 30, price: null, company: 'TitanFrame', line: 'Titan' },
  { id: 31, name: 'NovaCase Nano N100', maxGpus: 1, price: null, company: 'NovaCase', line: 'Nano' },
  { id: 32, name: 'NovaCase Nano N110', maxGpus: 1, price: null, company: 'NovaCase', line: 'Nano' },
  { id: 33, name: 'NovaCase Nano N120', maxGpus: 2, price: null, company: 'NovaCase', line: 'Nano' },
  { id: 34, name: 'NovaCase Nano N130', maxGpus: 2, price: null, company: 'NovaCase', line: 'Nano' },
  { id: 35, name: 'NovaCase Nano N140', maxGpus: 3, price: null, company: 'NovaCase', line: 'Nano' },
  { id: 36, name: 'NovaCase Nano N150', maxGpus: 4, price: null, company: 'NovaCase', line: 'Nano' },
  { id: 37, name: 'NovaCase Flow F200', maxGpus: 4, price: null, company: 'NovaCase', line: 'Flow' },
  { id: 38, name: 'NovaCase Flow F210', maxGpus: 5, price: null, company: 'NovaCase', line: 'Flow' },
  { id: 39, name: 'NovaCase Flow F220', maxGpus: 5, price: null, company: 'NovaCase', line: 'Flow' },
  { id: 40, name: 'NovaCase Flow F230', maxGpus: 6, price: null, company: 'NovaCase', line: 'Flow' },
  { id: 41, name: 'NovaCase Flow F240', maxGpus: 6, price: null, company: 'NovaCase', line: 'Flow' },
  { id: 42, name: 'NovaCase Flow F250', maxGpus: 7, price: null, company: 'NovaCase', line: 'Flow' },
  { id: 43, name: 'NovaCase Prime P300', maxGpus: 8, price: null, company: 'NovaCase', line: 'Prime' },
  { id: 44, name: 'NovaCase Prime P310', maxGpus: 9, price: null, company: 'NovaCase', line: 'Prime' },
  { id: 45, name: 'NovaCase Prime P320', maxGpus: 10, price: null, company: 'NovaCase', line: 'Prime' },
  { id: 46, name: 'NovaCase Prime P330', maxGpus: 11, price: null, company: 'NovaCase', line: 'Prime' },
  { id: 47, name: 'NovaCase Prime P340', maxGpus: 12, price: null, company: 'NovaCase', line: 'Prime' },
  { id: 48, name: 'NovaCase Prime P350', maxGpus: 13, price: null, company: 'NovaCase', line: 'Prime' },
  { id: 49, name: 'NovaCase Elite E400', maxGpus: 14, price: null, company: 'NovaCase', line: 'Elite' },
  { id: 50, name: 'NovaCase Elite E410', maxGpus: 15, price: null, company: 'NovaCase', line: 'Elite' },
  { id: 51, name: 'NovaCase Elite E420', maxGpus: 16, price: null, company: 'NovaCase', line: 'Elite' },
  { id: 52, name: 'NovaCase Elite E430', maxGpus: 17, price: null, company: 'NovaCase', line: 'Elite' },
  { id: 53, name: 'NovaCase Elite E440', maxGpus: 18, price: null, company: 'NovaCase', line: 'Elite' },
  { id: 54, name: 'NovaCase Elite E450', maxGpus: 19, price: null, company: 'NovaCase', line: 'Elite' },
  { id: 55, name: 'NovaCase Apex X500', maxGpus: 20, price: null, company: 'NovaCase', line: 'Apex' },
  { id: 56, name: 'NovaCase Apex X510', maxGpus: 22, price: null, company: 'NovaCase', line: 'Apex' },
  { id: 57, name: 'NovaCase Apex X520', maxGpus: 24, price: null, company: 'NovaCase', line: 'Apex' },
  { id: 58, name: 'NovaCase Apex X530', maxGpus: 26, price: null, company: 'NovaCase', line: 'Apex' },
  { id: 59, name: 'NovaCase Apex X540', maxGpus: 28, price: null, company: 'NovaCase', line: 'Apex' },
  { id: 60, name: 'NovaCase Apex X550', maxGpus: 30, price: null, company: 'NovaCase', line: 'Apex' },
  { id: 61, name: 'IronNest Base B100', maxGpus: 1, price: null, company: 'IronNest', line: 'Base' },
  { id: 62, name: 'IronNest Base B110', maxGpus: 2, price: null, company: 'IronNest', line: 'Base' },
  { id: 63, name: 'IronNest Base B120', maxGpus: 2, price: null, company: 'IronNest', line: 'Base' },
  { id: 64, name: 'IronNest Base B130', maxGpus: 3, price: null, company: 'IronNest', line: 'Base' },
  { id: 65, name: 'IronNest Base B140', maxGpus: 3, price: null, company: 'IronNest', line: 'Base' },
  { id: 66, name: 'IronNest Base B150', maxGpus: 4, price: null, company: 'IronNest', line: 'Base' },
  { id: 67, name: 'IronNest Forge F200', maxGpus: 4, price: null, company: 'IronNest', line: 'Forge' },
  { id: 68, name: 'IronNest Forge F210', maxGpus: 5, price: null, company: 'IronNest', line: 'Forge' },
  { id: 69, name: 'IronNest Forge F220', maxGpus: 6, price: null, company: 'IronNest', line: 'Forge' },
  { id: 70, name: 'IronNest Forge F230', maxGpus: 6, price: null, company: 'IronNest', line: 'Forge' },
  { id: 71, name: 'IronNest Forge F240', maxGpus: 7, price: null, company: 'IronNest', line: 'Forge' },
  { id: 72, name: 'IronNest Forge F250', maxGpus: 8, price: null, company: 'IronNest', line: 'Forge' },
  { id: 73, name: 'IronNest Steel S300', maxGpus: 9, price: null, company: 'IronNest', line: 'Steel' },
  { id: 74, name: 'IronNest Steel S310', maxGpus: 10, price: null, company: 'IronNest', line: 'Steel' },
  { id: 75, name: 'IronNest Steel S320', maxGpus: 11, price: null, company: 'IronNest', line: 'Steel' },
  { id: 76, name: 'IronNest Steel S330', maxGpus: 12, price: null, company: 'IronNest', line: 'Steel' },
  { id: 77, name: 'IronNest Steel S340', maxGpus: 13, price: null, company: 'IronNest', line: 'Steel' },
  { id: 78, name: 'IronNest Steel S350', maxGpus: 14, price: null, company: 'IronNest', line: 'Steel' },
  { id: 79, name: 'IronNest Fortress R400', maxGpus: 15, price: null, company: 'IronNest', line: 'Fortress' },
  { id: 80, name: 'IronNest Fortress R410', maxGpus: 16, price: null, company: 'IronNest', line: 'Fortress' },
  { id: 81, name: 'IronNest Fortress R420', maxGpus: 17, price: null, company: 'IronNest', line: 'Fortress' },
  { id: 82, name: 'IronNest Fortress R430', maxGpus: 18, price: null, company: 'IronNest', line: 'Fortress' },
  { id: 83, name: 'IronNest Fortress R440', maxGpus: 19, price: null, company: 'IronNest', line: 'Fortress' },
  { id: 84, name: 'IronNest Fortress R450', maxGpus: 20, price: null, company: 'IronNest', line: 'Fortress' },
  { id: 85, name: 'IronNest Colossus C500', maxGpus: 21, price: null, company: 'IronNest', line: 'Colossus' },
  { id: 86, name: 'IronNest Colossus C510', maxGpus: 23, price: null, company: 'IronNest', line: 'Colossus' },
  { id: 87, name: 'IronNest Colossus C520', maxGpus: 25, price: null, company: 'IronNest', line: 'Colossus' },
  { id: 88, name: 'IronNest Colossus C530', maxGpus: 27, price: null, company: 'IronNest', line: 'Colossus' },
  { id: 89, name: 'IronNest Colossus C540', maxGpus: 29, price: null, company: 'IronNest', line: 'Colossus' },
  { id: 90, name: 'IronNest Colossus C550', maxGpus: 32, price: null, company: 'IronNest', line: 'Colossus' },
]

const COMPANIES = ['TitanFrame', 'NovaCase', 'IronNest']

const COMPANY_COLORS = {
  TitanFrame: { bg: 'rgba(99, 102, 241, 0.10)', border: 'rgba(99, 102, 241, 0.3)', icon: '#818cf8', accent: '#6366f1' },
  NovaCase: { bg: 'rgba(249, 115, 22, 0.10)', border: 'rgba(249, 115, 22, 0.3)', icon: '#fb923c', accent: '#f97316' },
  IronNest: { bg: 'rgba(34, 197, 94, 0.10)', border: 'rgba(34, 197, 94, 0.3)', icon: '#4ade80', accent: '#22c55e' },
}

function CaseShop({ onBack }) {
  const { t } = useTranslation()
  const [selectedCompany, setSelectedCompany] = useState('')
  const [priceFrom, setPriceFrom] = useState('')
  const [priceTo, setPriceTo] = useState('')
  const [maxGpusFrom, setMaxGpusFrom] = useState('')
  const [maxGpusTo, setMaxGpusTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState(null)
  const [sortOrder, setSortOrder] = useState('asc')
  const [selectedProduct, setSelectedProduct] = useState(null)

  const filteredProducts = useMemo(() => {
    let result = CASE_PRODUCTS.filter(product => {
      if (selectedCompany && product.company !== selectedCompany) return false
      if (priceFrom && product.price !== null && product.price < Number(priceFrom)) return false
      if (priceTo && product.price !== null && product.price > Number(priceTo)) return false
      if (maxGpusFrom && product.maxGpus < Number(maxGpusFrom)) return false
      if (maxGpusTo && product.maxGpus > Number(maxGpusTo)) return false
      return true
    })

    if (sortBy) {
      result.sort((a, b) => {
        let compare = 0
        if (sortBy === 'price') {
          const priceA = a.price ?? 0
          const priceB = b.price ?? 0
          compare = priceA - priceB
        } else if (sortBy === 'company') {
          compare = a.company.localeCompare(b.company)
        } else {
          compare = a.maxGpus - b.maxGpus
        }
        return sortOrder === 'asc' ? compare : -compare
      })
    }

    return result
  }, [selectedCompany, priceFrom, priceTo, maxGpusFrom, maxGpusTo, sortBy, sortOrder])

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
        <h2 className="tab-title">{t('shop.gpuCases')}</h2>
      </div>

      <div className="gpu-toolbar">
        <button className="gpu-filter-toggle" onClick={() => setShowFilters(!showFilters)}>
          <Filter size={16} />
          <span>{t('common.filter')}</span>
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'maxGpus' ? 'active' : ''}`} onClick={() => toggleSort('maxGpus')}>
          <Layers size={14} />
          <span>{t('case.maxGpus')}</span>
          {sortBy === 'maxGpus' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} />
          <span>{t('common.price')}</span>
          {sortBy === 'price' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'company' ? 'active' : ''}`} onClick={() => toggleSort('company')}>
          <ArrowUpDown size={14} />
          <span>{t('case.company')}</span>
          {sortBy === 'company' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        {showFilters && (
          <div className="gpu-filter-panel">
            <div className="gpu-filter-row">
              <label>{t('case.company')}</label>
              <select value={selectedCompany} onChange={(e) => setSelectedCompany(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {COMPANIES.map(c => <option key={c} value={c}>{c}</option>)}
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
              <label>{t('case.maxGpus')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={maxGpusFrom} onChange={(e) => setMaxGpusFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={maxGpusTo} onChange={(e) => setMaxGpusTo(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="gpu-grid">
        {filteredProducts.map(product => {
          const colors = COMPANY_COLORS[product.company] || COMPANY_COLORS.TitanFrame
          return (
            <div
              key={product.id}
              className="gpu-card"
              style={{ background: colors.bg, borderColor: colors.border }}
            >
              <span className="gpu-card-icon" style={{ background: colors.accent }}><Box size={24} /></span>
              <span className="gpu-card-name">{product.name}</span>
              <div className="gpu-card-specs">
                <Layers size={12} style={{ color: colors.icon }} />
                <span>{product.maxGpus} GPU</span>
              </div>
              <div className="gpu-card-price">
                <DollarSign size={12} style={{ color: colors.icon }} />
                <span>{product.price !== null ? `$${product.price.toLocaleString()}` : t('common.notSet')}</span>
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

export default CaseShop
