import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Monitor, Filter, Zap, DollarSign, ArrowUpDown, Gem, Diamond, Snowflake, Flame, FlameKindling, Lock, BookOpen, Sparkles } from 'lucide-react'
import BuyModal from './BuyModal'
import ShopCard from './ShopCard'
import { applyShopPrices } from '../utils/shopPrices'

const GPU_PRODUCTS = [
  { id: 1, name: 'CrystalCore Quartz Q320', hashrate: 180, price: null, company: 'CrystalCore', line: 'Quartz' },
  { id: 2, name: 'CrystalCore Quartz Q340', hashrate: 220, price: null, company: 'CrystalCore', line: 'Quartz' },
  { id: 3, name: 'CrystalCore Quartz Q360', hashrate: 270, price: null, company: 'CrystalCore', line: 'Quartz' },
  { id: 4, name: 'CrystalCore Quartz Q380', hashrate: 330, price: null, company: 'CrystalCore', line: 'Quartz' },
  { id: 5, name: 'CrystalCore Quartz Q400', hashrate: 400, price: null, company: 'CrystalCore', line: 'Quartz' },
  { id: 6, name: 'CrystalCore Quartz Q420', hashrate: 480, price: null, company: 'CrystalCore', line: 'Quartz' },
  { id: 7, name: 'CrystalCore Topaz T520', hashrate: 620, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 8, name: 'CrystalCore Topaz T540', hashrate: 760, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 9, name: 'CrystalCore Topaz T560', hashrate: 930, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 10, name: 'CrystalCore Topaz T580', hashrate: 1120, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 11, name: 'CrystalCore Topaz T600', hashrate: 1340, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 12, name: 'CrystalCore Topaz T620', hashrate: 1600, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 13, name: 'CrystalCore Topaz T640', hashrate: 1900, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 14, name: 'CrystalCore Topaz T660', hashrate: 2250, price: null, company: 'CrystalCore', line: 'Topaz' },
  { id: 15, name: 'CrystalCore Sapphire S720', hashrate: 2700, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 16, name: 'CrystalCore Sapphire S740', hashrate: 3150, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 17, name: 'CrystalCore Sapphire S760', hashrate: 3650, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 18, name: 'CrystalCore Sapphire S780', hashrate: 4200, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 19, name: 'CrystalCore Sapphire S800', hashrate: 4850, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 20, name: 'CrystalCore Sapphire S820', hashrate: 5600, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 21, name: 'CrystalCore Sapphire S840', hashrate: 6450, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 22, name: 'CrystalCore Sapphire S860', hashrate: 7350, price: null, company: 'CrystalCore', line: 'Sapphire' },
  { id: 23, name: 'CrystalCore Diamond D920', hashrate: 8400, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 24, name: 'CrystalCore Diamond D940', hashrate: 9600, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 25, name: 'CrystalCore Diamond D960', hashrate: 11000, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 26, name: 'CrystalCore Diamond D980', hashrate: 12500, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 27, name: 'CrystalCore Diamond D1000', hashrate: 14200, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 28, name: 'CrystalCore Diamond D1020', hashrate: 16000, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 29, name: 'CrystalCore Diamond D1040', hashrate: 18000, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 30, name: 'CrystalCore Diamond D1060', hashrate: 20000, price: null, company: 'CrystalCore', line: 'Diamond' },
  { id: 31, name: 'Pyronix Spark SP320', hashrate: 210, price: null, company: 'Pyronix', line: 'Spark' },
  { id: 32, name: 'Pyronix Spark SP340', hashrate: 260, price: null, company: 'Pyronix', line: 'Spark' },
  { id: 33, name: 'Pyronix Spark SP360', hashrate: 320, price: null, company: 'Pyronix', line: 'Spark' },
  { id: 34, name: 'Pyronix Spark SP380', hashrate: 390, price: null, company: 'Pyronix', line: 'Spark' },
  { id: 35, name: 'Pyronix Spark SP400', hashrate: 470, price: null, company: 'Pyronix', line: 'Spark' },
  { id: 36, name: 'Pyronix Spark SP420', hashrate: 560, price: null, company: 'Pyronix', line: 'Spark' },
  { id: 37, name: 'Pyronix Flare FL520', hashrate: 720, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 38, name: 'Pyronix Flare FL540', hashrate: 880, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 39, name: 'Pyronix Flare FL560', hashrate: 1070, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 40, name: 'Pyronix Flare FL580', hashrate: 1290, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 41, name: 'Pyronix Flare FL600', hashrate: 1550, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 42, name: 'Pyronix Flare FL620', hashrate: 1860, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 43, name: 'Pyronix Flare FL640', hashrate: 2220, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 44, name: 'Pyronix Flare FL660', hashrate: 2650, price: null, company: 'Pyronix', line: 'Flare' },
  { id: 45, name: 'Pyronix Blaze BZ720', hashrate: 3150, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 46, name: 'Pyronix Blaze BZ740', hashrate: 3700, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 47, name: 'Pyronix Blaze BZ760', hashrate: 4350, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 48, name: 'Pyronix Blaze BZ780', hashrate: 5100, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 49, name: 'Pyronix Blaze BZ800', hashrate: 5950, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 50, name: 'Pyronix Blaze BZ820', hashrate: 6900, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 51, name: 'Pyronix Blaze BZ840', hashrate: 8000, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 52, name: 'Pyronix Blaze BZ860', hashrate: 9250, price: null, company: 'Pyronix', line: 'Blaze' },
  { id: 53, name: 'Pyronix Inferno IF920', hashrate: 10700, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 54, name: 'Pyronix Inferno IF940', hashrate: 12300, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 55, name: 'Pyronix Inferno IF960', hashrate: 14100, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 56, name: 'Pyronix Inferno IF980', hashrate: 16200, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 57, name: 'Pyronix Inferno IF1000', hashrate: 18500, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 58, name: 'Pyronix Inferno IF1020', hashrate: 21000, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 59, name: 'Pyronix Inferno IF1040', hashrate: 24000, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 60, name: 'Pyronix Inferno IF1060', hashrate: 27000, price: null, company: 'Pyronix', line: 'Inferno' },
  { id: 61, name: 'Archivex Vault V320', hashrate: 170, price: null, company: 'Archivex', line: 'Vault' },
  { id: 62, name: 'Archivex Vault V340', hashrate: 210, price: null, company: 'Archivex', line: 'Vault' },
  { id: 63, name: 'Archivex Vault V360', hashrate: 260, price: null, company: 'Archivex', line: 'Vault' },
  { id: 64, name: 'Archivex Vault V380', hashrate: 320, price: null, company: 'Archivex', line: 'Vault' },
  { id: 65, name: 'Archivex Vault V400', hashrate: 390, price: null, company: 'Archivex', line: 'Vault' },
  { id: 66, name: 'Archivex Vault V420', hashrate: 470, price: null, company: 'Archivex', line: 'Vault' },
  { id: 67, name: 'Archivex Legacy L520', hashrate: 600, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 68, name: 'Archivex Legacy L540', hashrate: 730, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 69, name: 'Archivex Legacy L560', hashrate: 890, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 70, name: 'Archivex Legacy L580', hashrate: 1070, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 71, name: 'Archivex Legacy L600', hashrate: 1290, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 72, name: 'Archivex Legacy L620', hashrate: 1550, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 73, name: 'Archivex Legacy L640', hashrate: 1860, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 74, name: 'Archivex Legacy L660', hashrate: 2220, price: null, company: 'Archivex', line: 'Legacy' },
  { id: 75, name: 'Archivex Archive A720', hashrate: 2650, price: null, company: 'Archivex', line: 'Archive' },
  { id: 76, name: 'Archivex Archive A740', hashrate: 3150, price: null, company: 'Archivex', line: 'Archive' },
  { id: 77, name: 'Archivex Archive A760', hashrate: 3700, price: null, company: 'Archivex', line: 'Archive' },
  { id: 78, name: 'Archivex Archive A780', hashrate: 4350, price: null, company: 'Archivex', line: 'Archive' },
  { id: 79, name: 'Archivex Archive A800', hashrate: 5100, price: null, company: 'Archivex', line: 'Archive' },
  { id: 80, name: 'Archivex Archive A820', hashrate: 5950, price: null, company: 'Archivex', line: 'Archive' },
  { id: 81, name: 'Archivex Archive A840', hashrate: 6900, price: null, company: 'Archivex', line: 'Archive' },
  { id: 82, name: 'Archivex Archive A860', hashrate: 8000, price: null, company: 'Archivex', line: 'Archive' },
  { id: 83, name: 'Archivex Genesis G920', hashrate: 9300, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 84, name: 'Archivex Genesis G940', hashrate: 10800, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 85, name: 'Archivex Genesis G960', hashrate: 12500, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 86, name: 'Archivex Genesis G980', hashrate: 14500, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 87, name: 'Archivex Genesis G1000', hashrate: 16700, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 88, name: 'Archivex Genesis G1020', hashrate: 19200, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 89, name: 'Archivex Genesis G1040', hashrate: 22000, price: null, company: 'Archivex', line: 'Genesis' },
  { id: 90, name: 'Archivex Genesis G1060', hashrate: 25000, price: null, company: 'Archivex', line: 'Genesis' },
]

const COMPANIES = ['CrystalCore', 'Pyronix', 'Archivex']

const LINE_COLORS = {
  // CrystalCore
  Quartz:    { bg: 'rgba(99, 102, 241, 0.10)', border: 'rgba(99, 102, 241, 0.3)', icon: '#818cf8', accent: '#6366f1' },
  Topaz:     { bg: 'rgba(59, 130, 246, 0.10)', border: 'rgba(59, 130, 246, 0.3)', icon: '#60a5fa', accent: '#3b82f6' },
  Sapphire:  { bg: 'rgba(6, 182, 212, 0.10)', border: 'rgba(6, 182, 212, 0.3)', icon: '#22d3ee', accent: '#06b6d4' },
  Diamond:   { bg: 'rgba(168, 85, 247, 0.10)', border: 'rgba(168, 85, 247, 0.3)', icon: '#c084fc', accent: '#a855f7' },
  // Pyronix
  Spark:     { bg: 'rgba(249, 115, 22, 0.10)', border: 'rgba(249, 115, 22, 0.3)', icon: '#fb923c', accent: '#f97316' },
  Flare:     { bg: 'rgba(239, 68, 68, 0.10)', border: 'rgba(239, 68, 68, 0.3)', icon: '#f87171', accent: '#ef4444' },
  Blaze:     { bg: 'rgba(245, 158, 11, 0.10)', border: 'rgba(245, 158, 11, 0.3)', icon: '#fbbf24', accent: '#f59e0b' },
  Inferno:   { bg: 'rgba(220, 38, 38, 0.10)', border: 'rgba(220, 38, 38, 0.3)', icon: '#fca5a5', accent: '#dc2626' },
  // Archivex
  Vault:     { bg: 'rgba(34, 197, 94, 0.10)', border: 'rgba(34, 197, 94, 0.3)', icon: '#4ade80', accent: '#22c55e' },
  Legacy:    { bg: 'rgba(16, 185, 129, 0.10)', border: 'rgba(16, 185, 129, 0.3)', icon: '#34d399', accent: '#10b981' },
  Archive:   { bg: 'rgba(20, 184, 166, 0.10)', border: 'rgba(20, 184, 166, 0.3)', icon: '#2dd4bf', accent: '#14b8a6' },
  Genesis:   { bg: 'rgba(132, 204, 22, 0.10)', border: 'rgba(132, 204, 22, 0.3)', icon: '#a3e635', accent: '#84cc16' },
}

const LINE_ICONS = {
  // CrystalCore
  Quartz: Gem,
  Topaz: Snowflake,
  Sapphire: Diamond,
  Diamond: Sparkles,
  // Pyronix
  Spark: Zap,
  Flare: Flame,
  Blaze: FlameKindling,
  Inferno: Flame,
  // Archivex
  Vault: Lock,
  Legacy: BookOpen,
  Archive: Monitor,
  Genesis: Sparkles,
}

const COMPANY_COLORS = {
  CrystalCore: LINE_COLORS.Quartz,
  Pyronix: LINE_COLORS.Spark,
  Archivex: LINE_COLORS.Vault,
}

function GpuShop({ onBack }) {
  const { t } = useTranslation()
  const [selectedCompany, setSelectedCompany] = useState('')
  const [priceFrom, setPriceFrom] = useState('')
  const [priceTo, setPriceTo] = useState('')
  const [hashrateFrom, setHashrateFrom] = useState('')
  const [hashrateTo, setHashrateTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState(null)
  const [sortOrder, setSortOrder] = useState('asc')
  const [selectedProduct, setSelectedProduct] = useState(null)

  const filteredProducts = useMemo(() => {
    let result = applyShopPrices(GPU_PRODUCTS).filter(product => {
      if (selectedCompany && product.company !== selectedCompany) return false
      if (priceFrom && product.price !== null && product.price < Number(priceFrom)) return false
      if (priceTo && product.price !== null && product.price > Number(priceTo)) return false
      if (hashrateFrom && product.hashrate < Number(hashrateFrom)) return false
      if (hashrateTo && product.hashrate > Number(hashrateTo)) return false
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
          compare = a.hashrate - b.hashrate
        }
        return sortOrder === 'asc' ? compare : -compare
      })
    }

    return result
  }, [selectedCompany, priceFrom, priceTo, hashrateFrom, hashrateTo, sortBy, sortOrder])

  const formatHashrate = (h) => {
    if (h >= 1000) return `${(h / 1000).toFixed(1)}k`
    return `${h}`
  }

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
        <h2 className="tab-title">{t('shop.gpuCards')}</h2>
      </div>

      <div className="gpu-toolbar">
        <button className="gpu-filter-toggle" onClick={() => setShowFilters(!showFilters)}>
          <Filter size={16} />
          <span>{t('common.filter')}</span>
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'hashrate' ? 'active' : ''}`} onClick={() => toggleSort('hashrate')}>
          <Zap size={14} />
          <span>{t('gpu.hashrate')}</span>
          {sortBy === 'hashrate' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
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
              <label>{t('gpu.hashrate')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={hashrateFrom} onChange={(e) => setHashrateFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={hashrateTo} onChange={(e) => setHashrateTo(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="shop-grid">
        {filteredProducts.map(product => {
          const colors = LINE_COLORS[product.line] || COMPANY_COLORS[product.company] || LINE_COLORS.Quartz
          const LineIcon = LINE_ICONS[product.line] || Monitor
          return (
            <ShopCard
              key={product.id}
              icon={LineIcon}
              name={product.name}
              subtitle={product.line}
              specs={[{ icon: Zap, label: `${formatHashrate(product.hashrate)} H/s` }]}
              price={product.price}
              colors={colors}
              onBuy={() => setSelectedProduct(product)}
            />
          )
        })}
      </div>

      {selectedProduct && (
        <BuyModal product={selectedProduct} onClose={() => setSelectedProduct(null)} />
      )}
    </div>
  )
}

export { GPU_PRODUCTS }
export default GpuShop
