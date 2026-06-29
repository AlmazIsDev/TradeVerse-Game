import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Cpu, Filter, DollarSign, Layers, ArrowUpDown } from 'lucide-react'
import BuyModal from './BuyModal'
import { applyShopPrices } from '../utils/shopPrices'

const CPU_PRODUCTS = [
  { id: 1, name: 'CrystalChip Stone S210', maxGpus: 1, multiplier: 1.00, price: null, company: 'CrystalChip', line: 'Stone' },
  { id: 2, name: 'CrystalChip Stone S220', maxGpus: 2, multiplier: 1.01, price: null, company: 'CrystalChip', line: 'Stone' },
  { id: 3, name: 'CrystalChip Stone S230', maxGpus: 2, multiplier: 1.02, price: null, company: 'CrystalChip', line: 'Stone' },
  { id: 4, name: 'CrystalChip Stone S240', maxGpus: 3, multiplier: 1.03, price: null, company: 'CrystalChip', line: 'Stone' },
  { id: 5, name: 'CrystalChip Stone S250', maxGpus: 4, multiplier: 1.04, price: null, company: 'CrystalChip', line: 'Stone' },
  { id: 6, name: 'CrystalChip Stone S260', maxGpus: 5, multiplier: 1.05, price: null, company: 'CrystalChip', line: 'Stone' },
  { id: 7, name: 'CrystalChip Crystal C310', maxGpus: 6, multiplier: 1.07, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 8, name: 'CrystalChip Crystal C320', maxGpus: 7, multiplier: 1.09, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 9, name: 'CrystalChip Crystal C330', maxGpus: 8, multiplier: 1.11, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 10, name: 'CrystalChip Crystal C340', maxGpus: 9, multiplier: 1.13, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 11, name: 'CrystalChip Crystal C350', maxGpus: 10, multiplier: 1.15, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 12, name: 'CrystalChip Crystal C360', maxGpus: 11, multiplier: 1.17, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 13, name: 'CrystalChip Crystal C370', maxGpus: 12, multiplier: 1.19, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 14, name: 'CrystalChip Crystal C380', maxGpus: 13, multiplier: 1.21, price: null, company: 'CrystalChip', line: 'Crystal' },
  { id: 15, name: 'CrystalChip Diamond D410', maxGpus: 14, multiplier: 1.24, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 16, name: 'CrystalChip Diamond D420', maxGpus: 15, multiplier: 1.27, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 17, name: 'CrystalChip Diamond D430', maxGpus: 16, multiplier: 1.30, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 18, name: 'CrystalChip Diamond D440', maxGpus: 17, multiplier: 1.33, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 19, name: 'CrystalChip Diamond D450', maxGpus: 18, multiplier: 1.36, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 20, name: 'CrystalChip Diamond D460', maxGpus: 19, multiplier: 1.39, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 21, name: 'CrystalChip Diamond D470', maxGpus: 20, multiplier: 1.42, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 22, name: 'CrystalChip Diamond D480', maxGpus: 21, multiplier: 1.45, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 23, name: 'CrystalChip Diamond D490', maxGpus: 22, multiplier: 1.48, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 24, name: 'CrystalChip Diamond D500', maxGpus: 23, multiplier: 1.52, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 25, name: 'CrystalChip Diamond D510', maxGpus: 24, multiplier: 1.56, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 26, name: 'CrystalChip Diamond D520', maxGpus: 25, multiplier: 1.60, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 27, name: 'CrystalChip Diamond D530', maxGpus: 26, multiplier: 1.65, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 28, name: 'CrystalChip Diamond D540', maxGpus: 27, multiplier: 1.70, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 29, name: 'CrystalChip Diamond D550', maxGpus: 28, multiplier: 1.75, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 30, name: 'CrystalChip Diamond D560', maxGpus: 30, multiplier: 1.80, price: null, company: 'CrystalChip', line: 'Diamond' },
  { id: 31, name: 'PyroCore Ember E210', maxGpus: 2, multiplier: 1.02, price: null, company: 'PyroCore', line: 'Ember' },
  { id: 32, name: 'PyroCore Ember E220', maxGpus: 3, multiplier: 1.03, price: null, company: 'PyroCore', line: 'Ember' },
  { id: 33, name: 'PyroCore Ember E230', maxGpus: 4, multiplier: 1.05, price: null, company: 'PyroCore', line: 'Ember' },
  { id: 34, name: 'PyroCore Ember E240', maxGpus: 5, multiplier: 1.07, price: null, company: 'PyroCore', line: 'Ember' },
  { id: 35, name: 'PyroCore Ember E250', maxGpus: 6, multiplier: 1.09, price: null, company: 'PyroCore', line: 'Ember' },
  { id: 36, name: 'PyroCore Ember E260', maxGpus: 7, multiplier: 1.11, price: null, company: 'PyroCore', line: 'Ember' },
  { id: 37, name: 'PyroCore Blaze B310', maxGpus: 8, multiplier: 1.14, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 38, name: 'PyroCore Blaze B320', maxGpus: 9, multiplier: 1.17, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 39, name: 'PyroCore Blaze B330', maxGpus: 10, multiplier: 1.20, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 40, name: 'PyroCore Blaze B340', maxGpus: 11, multiplier: 1.23, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 41, name: 'PyroCore Blaze B350', maxGpus: 12, multiplier: 1.26, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 42, name: 'PyroCore Blaze B360', maxGpus: 13, multiplier: 1.29, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 43, name: 'PyroCore Blaze B370', maxGpus: 14, multiplier: 1.32, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 44, name: 'PyroCore Blaze B380', maxGpus: 15, multiplier: 1.35, price: null, company: 'PyroCore', line: 'Blaze' },
  { id: 45, name: 'PyroCore Inferno I410', maxGpus: 16, multiplier: 1.39, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 46, name: 'PyroCore Inferno I420', maxGpus: 17, multiplier: 1.43, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 47, name: 'PyroCore Inferno I430', maxGpus: 18, multiplier: 1.47, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 48, name: 'PyroCore Inferno I440', maxGpus: 19, multiplier: 1.51, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 49, name: 'PyroCore Inferno I450', maxGpus: 20, multiplier: 1.55, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 50, name: 'PyroCore Inferno I460', maxGpus: 21, multiplier: 1.59, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 51, name: 'PyroCore Inferno I470', maxGpus: 22, multiplier: 1.63, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 52, name: 'PyroCore Inferno I480', maxGpus: 23, multiplier: 1.67, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 53, name: 'PyroCore Inferno I490', maxGpus: 24, multiplier: 1.72, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 54, name: 'PyroCore Inferno I500', maxGpus: 25, multiplier: 1.77, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 55, name: 'PyroCore Inferno I510', maxGpus: 26, multiplier: 1.82, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 56, name: 'PyroCore Inferno I520', maxGpus: 27, multiplier: 1.87, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 57, name: 'PyroCore Inferno I530', maxGpus: 28, multiplier: 1.92, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 58, name: 'PyroCore Inferno I540', maxGpus: 29, multiplier: 1.97, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 59, name: 'PyroCore Inferno I550', maxGpus: 30, multiplier: 2.03, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 60, name: 'PyroCore Inferno I560', maxGpus: 32, multiplier: 2.10, price: null, company: 'PyroCore', line: 'Inferno' },
  { id: 61, name: 'ArchiveCore Legacy L210', maxGpus: 1, multiplier: 1.01, price: null, company: 'ArchiveCore', line: 'Legacy' },
  { id: 62, name: 'ArchiveCore Legacy L220', maxGpus: 2, multiplier: 1.02, price: null, company: 'ArchiveCore', line: 'Legacy' },
  { id: 63, name: 'ArchiveCore Legacy L230', maxGpus: 3, multiplier: 1.03, price: null, company: 'ArchiveCore', line: 'Legacy' },
  { id: 64, name: 'ArchiveCore Legacy L240', maxGpus: 4, multiplier: 1.05, price: null, company: 'ArchiveCore', line: 'Legacy' },
  { id: 65, name: 'ArchiveCore Legacy L250', maxGpus: 5, multiplier: 1.07, price: null, company: 'ArchiveCore', line: 'Legacy' },
  { id: 66, name: 'ArchiveCore Legacy L260', maxGpus: 6, multiplier: 1.09, price: null, company: 'ArchiveCore', line: 'Legacy' },
  { id: 67, name: 'ArchiveCore Archive A310', maxGpus: 7, multiplier: 1.11, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 68, name: 'ArchiveCore Archive A320', maxGpus: 8, multiplier: 1.13, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 69, name: 'ArchiveCore Archive A330', maxGpus: 9, multiplier: 1.15, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 70, name: 'ArchiveCore Archive A340', maxGpus: 10, multiplier: 1.17, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 71, name: 'ArchiveCore Archive A350', maxGpus: 11, multiplier: 1.19, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 72, name: 'ArchiveCore Archive A360', maxGpus: 12, multiplier: 1.21, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 73, name: 'ArchiveCore Archive A370', maxGpus: 13, multiplier: 1.23, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 74, name: 'ArchiveCore Archive A380', maxGpus: 14, multiplier: 1.25, price: null, company: 'ArchiveCore', line: 'Archive' },
  { id: 75, name: 'ArchiveCore Genesis G410', maxGpus: 15, multiplier: 1.28, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 76, name: 'ArchiveCore Genesis G420', maxGpus: 16, multiplier: 1.31, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 77, name: 'ArchiveCore Genesis G430', maxGpus: 17, multiplier: 1.34, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 78, name: 'ArchiveCore Genesis G440', maxGpus: 18, multiplier: 1.37, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 79, name: 'ArchiveCore Genesis G450', maxGpus: 19, multiplier: 1.40, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 80, name: 'ArchiveCore Genesis G460', maxGpus: 20, multiplier: 1.43, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 81, name: 'ArchiveCore Genesis G470', maxGpus: 21, multiplier: 1.46, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 82, name: 'ArchiveCore Genesis G480', maxGpus: 22, multiplier: 1.49, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 83, name: 'ArchiveCore Genesis G490', maxGpus: 23, multiplier: 1.53, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 84, name: 'ArchiveCore Genesis G500', maxGpus: 24, multiplier: 1.57, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 85, name: 'ArchiveCore Genesis G510', maxGpus: 25, multiplier: 1.61, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 86, name: 'ArchiveCore Genesis G520', maxGpus: 26, multiplier: 1.65, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 87, name: 'ArchiveCore Genesis G530', maxGpus: 27, multiplier: 1.70, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 88, name: 'ArchiveCore Genesis G540', maxGpus: 28, multiplier: 1.75, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 89, name: 'ArchiveCore Genesis G550', maxGpus: 29, multiplier: 1.80, price: null, company: 'ArchiveCore', line: 'Genesis' },
  { id: 90, name: 'ArchiveCore Genesis G560', maxGpus: 30, multiplier: 1.85, price: null, company: 'ArchiveCore', line: 'Genesis' },
]

const COMPANIES = ['CrystalChip', 'PyroCore', 'ArchiveCore']

const COMPANY_COLORS = {
  CrystalChip: { bg: 'rgba(99, 102, 241, 0.10)', border: 'rgba(99, 102, 241, 0.3)', icon: '#818cf8', accent: '#6366f1' },
  PyroCore: { bg: 'rgba(249, 115, 22, 0.10)', border: 'rgba(249, 115, 22, 0.3)', icon: '#fb923c', accent: '#f97316' },
  ArchiveCore: { bg: 'rgba(34, 197, 94, 0.10)', border: 'rgba(34, 197, 94, 0.3)', icon: '#4ade80', accent: '#22c55e' },
}

function CpuShop({ onBack }) {
  const { t } = useTranslation()
  const [selectedCompany, setSelectedCompany] = useState('')
  const [priceFrom, setPriceFrom] = useState('')
  const [priceTo, setPriceTo] = useState('')
  const [maxGpusFrom, setMaxGpusFrom] = useState('')
  const [maxGpusTo, setMaxGpusTo] = useState('')
  const [multiplierFrom, setMultiplierFrom] = useState('')
  const [multiplierTo, setMultiplierTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState(null)
  const [sortOrder, setSortOrder] = useState('asc')
  const [selectedProduct, setSelectedProduct] = useState(null)

  const filteredProducts = useMemo(() => {
    let result = applyShopPrices(CPU_PRODUCTS).filter(product => {
      if (selectedCompany && product.company !== selectedCompany) return false
      if (priceFrom && product.price !== null && product.price < Number(priceFrom)) return false
      if (priceTo && product.price !== null && product.price > Number(priceTo)) return false
      if (maxGpusFrom && product.maxGpus < Number(maxGpusFrom)) return false
      if (maxGpusTo && product.maxGpus > Number(maxGpusTo)) return false
      if (multiplierFrom && product.multiplier < Number(multiplierFrom)) return false
      if (multiplierTo && product.multiplier > Number(multiplierTo)) return false
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
        } else if (sortBy === 'maxGpus') {
          compare = a.maxGpus - b.maxGpus
        } else {
          compare = a.multiplier - b.multiplier
        }
        return sortOrder === 'asc' ? compare : -compare
      })
    }

    return result
  }, [selectedCompany, priceFrom, priceTo, maxGpusFrom, maxGpusTo, multiplierFrom, multiplierTo, sortBy, sortOrder])

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
        <h2 className="tab-title">{t('shop.gpuCpus')}</h2>
      </div>

      <div className="gpu-toolbar">
        <button className="gpu-filter-toggle" onClick={() => setShowFilters(!showFilters)}>
          <Filter size={16} />
          <span>{t('common.filter')}</span>
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'maxGpus' ? 'active' : ''}`} onClick={() => toggleSort('maxGpus')}>
          <Layers size={14} />
          <span>{t('cpu.maxGpus')}</span>
          {sortBy === 'maxGpus' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'multiplier' ? 'active' : ''}`} onClick={() => toggleSort('multiplier')}>
          <ArrowUpDown size={14} />
          <span>{t('cpu.multiplier')}</span>
          {sortBy === 'multiplier' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} />
          <span>{t('common.price')}</span>
          {sortBy === 'price' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'company' ? 'active' : ''}`} onClick={() => toggleSort('company')}>
          <ArrowUpDown size={14} />
          <span>{t('gpu.company')}</span>
          {sortBy === 'company' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        {showFilters && (
          <div className="gpu-filter-panel">
            <div className="gpu-filter-row">
              <label>{t('gpu.company')}</label>
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
              <label>{t('cpu.maxGpus')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={maxGpusFrom} onChange={(e) => setMaxGpusFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={maxGpusTo} onChange={(e) => setMaxGpusTo(e.target.value)} />
              </div>
            </div>
            <div className="gpu-filter-row">
              <label>{t('cpu.multiplier')}</label>
              <div className="gpu-filter-range">
                <input type="number" step="0.01" placeholder={t('common.from')} value={multiplierFrom} onChange={(e) => setMultiplierFrom(e.target.value)} />
                <span>—</span>
                <input type="number" step="0.01" placeholder={t('common.to')} value={multiplierTo} onChange={(e) => setMultiplierTo(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="gpu-grid">
        {filteredProducts.map(product => {
          const colors = COMPANY_COLORS[product.company] || COMPANY_COLORS.CrystalChip
          return (
            <div
              key={product.id}
              className="gpu-card"
              style={{ background: colors.bg, borderColor: colors.border }}
            >
              <span className="gpu-card-icon" style={{ background: colors.accent }}><Cpu size={24} /></span>
              <span className="gpu-card-name">{product.name}</span>
              <div className="gpu-card-specs">
                <Layers size={12} style={{ color: colors.icon }} />
                <span>{product.maxGpus} GPU</span>
              </div>
              <div className="gpu-card-multiplier">
                <span>{product.multiplier}x</span>
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

export { CPU_PRODUCTS }
export default CpuShop
