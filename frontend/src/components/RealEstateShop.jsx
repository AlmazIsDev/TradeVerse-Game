import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Home, Filter, DollarSign, Bed, Zap, Box, ArrowUpDown } from 'lucide-react'
import BuyModal from './BuyModal'
import ShopCard from './ShopCard'
import { applyShopPrices } from '../utils/shopPrices'

const REAL_ESTATE_PRODUCTS = [
  // Обычный
  { id: 1, name: 'Sunny Cottage', rarity: 'common', rooms: 1, tax: null, basement: 1, price: null },
  { id: 2, name: 'Green Nest', rarity: 'common', rooms: 1, tax: null, basement: 1, price: null },
  { id: 3, name: 'Little Oak', rarity: 'common', rooms: 1, tax: null, basement: 1, price: null },
  { id: 4, name: 'Rose House', rarity: 'common', rooms: 1, tax: null, basement: 2, price: null },
  { id: 5, name: 'Maple Home', rarity: 'common', rooms: 2, tax: null, basement: 2, price: null },
  { id: 6, name: 'Silver Cottage', rarity: 'common', rooms: 2, tax: null, basement: 2, price: null },
  { id: 7, name: 'Forest View', rarity: 'common', rooms: 2, tax: null, basement: 2, price: null },
  { id: 8, name: 'Pine Residence', rarity: 'common', rooms: 2, tax: null, basement: 3, price: null },
  { id: 9, name: 'Golden Nest', rarity: 'common', rooms: 2, tax: null, basement: 3, price: null },
  { id: 10, name: 'Blue Horizon', rarity: 'common', rooms: 2, tax: null, basement: 3, price: null },
  { id: 11, name: 'Stone Cottage', rarity: 'common', rooms: 2, tax: null, basement: 3, price: null },
  { id: 12, name: 'Autumn House', rarity: 'common', rooms: 2, tax: null, basement: 4, price: null },
  { id: 13, name: 'Meadow Home', rarity: 'common', rooms: 3, tax: null, basement: 4, price: null },
  { id: 14, name: 'Oak Residence', rarity: 'common', rooms: 3, tax: null, basement: 4, price: null },
  { id: 15, name: 'Cherry Cottage', rarity: 'common', rooms: 3, tax: null, basement: 4, price: null },
  { id: 16, name: 'Birch House', rarity: 'common', rooms: 3, tax: null, basement: 4, price: null },
  { id: 17, name: 'Morning Villa', rarity: 'common', rooms: 3, tax: null, basement: 5, price: null },
  { id: 18, name: 'Hill Cottage', rarity: 'common', rooms: 3, tax: null, basement: 5, price: null },
  { id: 19, name: 'River House', rarity: 'common', rooms: 3, tax: null, basement: 5, price: null },
  { id: 20, name: 'Sunset Home', rarity: 'common', rooms: 3, tax: null, basement: 5, price: null },
  // Необычный
  { id: 21, name: 'Crystal Garden', rarity: 'uncommon', rooms: 4, tax: null, basement: 6, price: null },
  { id: 22, name: 'Lake Breeze', rarity: 'uncommon', rooms: 4, tax: null, basement: 6, price: null },
  { id: 23, name: 'Amber Villa', rarity: 'uncommon', rooms: 4, tax: null, basement: 6, price: null },
  { id: 24, name: 'Willow Manor', rarity: 'uncommon', rooms: 4, tax: null, basement: 6, price: null },
  { id: 25, name: 'Mountain Rest', rarity: 'uncommon', rooms: 4, tax: null, basement: 7, price: null },
  { id: 26, name: 'Emerald Home', rarity: 'uncommon', rooms: 4, tax: null, basement: 7, price: null },
  { id: 27, name: 'Harmony House', rarity: 'uncommon', rooms: 4, tax: null, basement: 7, price: null },
  { id: 28, name: 'Royal Cottage', rarity: 'uncommon', rooms: 5, tax: null, basement: 7, price: null },
  { id: 29, name: 'Garden Estate', rarity: 'uncommon', rooms: 5, tax: null, basement: 8, price: null },
  { id: 30, name: 'Windy Hill', rarity: 'uncommon', rooms: 5, tax: null, basement: 8, price: null },
  { id: 31, name: 'Golden Villa', rarity: 'uncommon', rooms: 5, tax: null, basement: 8, price: null },
  { id: 32, name: 'Ocean View', rarity: 'uncommon', rooms: 5, tax: null, basement: 8, price: null },
  { id: 33, name: 'Snow Peak', rarity: 'uncommon', rooms: 5, tax: null, basement: 9, price: null },
  { id: 34, name: 'Silver Lake', rarity: 'uncommon', rooms: 5, tax: null, basement: 9, price: null },
  { id: 35, name: 'Crystal Peak', rarity: 'uncommon', rooms: 5, tax: null, basement: 9, price: null },
  { id: 36, name: 'Rose Manor', rarity: 'uncommon', rooms: 5, tax: null, basement: 10, price: null },
  { id: 37, name: 'Royal Garden', rarity: 'uncommon', rooms: 6, tax: null, basement: 10, price: null },
  { id: 38, name: 'Moonlight Villa', rarity: 'uncommon', rooms: 6, tax: null, basement: 10, price: null },
  { id: 39, name: 'Green Palace', rarity: 'uncommon', rooms: 6, tax: null, basement: 10, price: null },
  { id: 40, name: 'Diamond Cottage', rarity: 'uncommon', rooms: 6, tax: null, basement: 10, price: null },
  // Редкий
  { id: 41, name: 'Imperial Home', rarity: 'rare', rooms: 6, tax: null, basement: 11, price: null },
  { id: 42, name: 'Ruby Manor', rarity: 'rare', rooms: 6, tax: null, basement: 11, price: null },
  { id: 43, name: 'Forest Palace', rarity: 'rare', rooms: 6, tax: null, basement: 11, price: null },
  { id: 44, name: 'Sunrise Estate', rarity: 'rare', rooms: 6, tax: null, basement: 12, price: null },
  { id: 45, name: 'North Residence', rarity: 'rare', rooms: 7, tax: null, basement: 12, price: null },
  { id: 46, name: 'Sky House', rarity: 'rare', rooms: 7, tax: null, basement: 12, price: null },
  { id: 47, name: 'Aurora Villa', rarity: 'rare', rooms: 7, tax: null, basement: 13, price: null },
  { id: 48, name: 'Prestige Manor', rarity: 'rare', rooms: 7, tax: null, basement: 13, price: null },
  { id: 49, name: "King's Home", rarity: 'rare', rooms: 7, tax: null, basement: 13, price: null },
  { id: 50, name: 'Elite Residence', rarity: 'rare', rooms: 7, tax: null, basement: 14, price: null },
  { id: 51, name: 'Majestic Villa', rarity: 'rare', rooms: 8, tax: null, basement: 14, price: null },
  { id: 52, name: 'Royal Heights', rarity: 'rare', rooms: 8, tax: null, basement: 14, price: null },
  { id: 53, name: 'Silver Crown', rarity: 'rare', rooms: 8, tax: null, basement: 15, price: null },
  { id: 54, name: 'Golden Ridge', rarity: 'rare', rooms: 8, tax: null, basement: 15, price: null },
  { id: 55, name: 'Crimson Estate', rarity: 'rare', rooms: 8, tax: null, basement: 15, price: null },
  { id: 56, name: 'Azure Palace', rarity: 'rare', rooms: 8, tax: null, basement: 16, price: null },
  { id: 57, name: 'Ivory Manor', rarity: 'rare', rooms: 8, tax: null, basement: 16, price: null },
  // Эпический
  { id: 58, name: 'Stormwatch Villa', rarity: 'epic', rooms: 9, tax: null, basement: 16, price: null },
  { id: 59, name: 'Dragonspire House', rarity: 'epic', rooms: 9, tax: null, basement: 17, price: null },
  { id: 60, name: 'Obsidian Hall', rarity: 'epic', rooms: 9, tax: null, basement: 17, price: null },
  { id: 61, name: 'Titan Crest', rarity: 'epic', rooms: 9, tax: null, basement: 18, price: null },
  { id: 62, name: 'Eclipse Estate', rarity: 'epic', rooms: 9, tax: null, basement: 18, price: null },
  { id: 63, name: 'Starforge Manor', rarity: 'epic', rooms: 9, tax: null, basement: 18, price: null },
  { id: 64, name: 'Celestial Home', rarity: 'epic', rooms: 10, tax: null, basement: 19, price: null },
  { id: 65, name: 'Nightfall Villa', rarity: 'epic', rooms: 10, tax: null, basement: 19, price: null },
  { id: 66, name: 'Thunder Peak', rarity: 'epic', rooms: 10, tax: null, basement: 20, price: null },
  { id: 67, name: 'Phoenix Residence', rarity: 'epic', rooms: 10, tax: null, basement: 20, price: null },
  { id: 68, name: 'Ironwind Estate', rarity: 'epic', rooms: 10, tax: null, basement: 20, price: null },
  { id: 69, name: 'Lunar Fortress', rarity: 'epic', rooms: 10, tax: null, basement: 21, price: null },
  { id: 70, name: 'Solar Mansion', rarity: 'epic', rooms: 10, tax: null, basement: 21, price: null },
  // Легендарный
  { id: 71, name: 'Astral Palace', rarity: 'legendary', rooms: 11, tax: null, basement: 21, price: null },
  { id: 72, name: 'Void Castle', rarity: 'legendary', rooms: 11, tax: null, basement: 22, price: null },
  { id: 73, name: 'Infinity House', rarity: 'legendary', rooms: 11, tax: null, basement: 22, price: null },
  { id: 74, name: 'Nebula Citadel', rarity: 'legendary', rooms: 11, tax: null, basement: 22, price: null },
  { id: 75, name: 'Quantum Villa', rarity: 'legendary', rooms: 12, tax: null, basement: 23, price: null },
  { id: 76, name: 'Godfall Residence', rarity: 'legendary', rooms: 12, tax: null, basement: 23, price: null },
  { id: 77, name: 'Eternal Palace', rarity: 'legendary', rooms: 12, tax: null, basement: 24, price: null },
  { id: 78, name: 'Supreme Nexus', rarity: 'legendary', rooms: 12, tax: null, basement: 24, price: null },
  { id: 79, name: 'Hyperion Tower Home', rarity: 'legendary', rooms: 12, tax: null, basement: 24, price: null },
  { id: 80, name: 'Omega Estate', rarity: 'legendary', rooms: 12, tax: null, basement: 24, price: null },
  { id: 81, name: 'Final Crown House', rarity: 'legendary', rooms: 12, tax: null, basement: 24, price: null },
]

const RARITIES = ['common', 'uncommon', 'rare', 'epic', 'legendary']

const RARITY_COLORS = {
  common: { bg: 'rgba(156, 163, 175, 0.10)', border: 'rgba(156, 163, 175, 0.3)', icon: '#9ca3af', accent: '#6b7280' },
  uncommon: { bg: 'rgba(34, 197, 94, 0.10)', border: 'rgba(34, 197, 94, 0.3)', icon: '#4ade80', accent: '#22c55e' },
  rare: { bg: 'rgba(59, 130, 246, 0.10)', border: 'rgba(59, 130, 246, 0.3)', icon: '#60a5fa', accent: '#3b82f6' },
  epic: { bg: 'rgba(168, 85, 247, 0.10)', border: 'rgba(168, 85, 247, 0.3)', icon: '#c084fc', accent: '#a855f7' },
  legendary: { bg: 'rgba(245, 158, 11, 0.10)', border: 'rgba(245, 158, 11, 0.3)', icon: '#fbbf24', accent: '#f59e0b' },
}

function RealEstateShop({ onBack }) {
  const { t } = useTranslation()
  const [selectedRarity, setSelectedRarity] = useState('')
  const [priceFrom, setPriceFrom] = useState('')
  const [priceTo, setPriceTo] = useState('')
  const [roomsFrom, setRoomsFrom] = useState('')
  const [roomsTo, setRoomsTo] = useState('')
  const [basementFrom, setBasementFrom] = useState('')
  const [basementTo, setBasementTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [sortBy, setSortBy] = useState(null)
  const [sortOrder, setSortOrder] = useState('asc')
  const [selectedProduct, setSelectedProduct] = useState(null)

  const filteredProducts = useMemo(() => {
    let result = applyShopPrices(REAL_ESTATE_PRODUCTS).filter(product => {
      if (selectedRarity && product.rarity !== selectedRarity) return false
      if (priceFrom && product.price !== null && product.price < Number(priceFrom)) return false
      if (priceTo && product.price !== null && product.price > Number(priceTo)) return false
      if (roomsFrom && product.rooms < Number(roomsFrom)) return false
      if (roomsTo && product.rooms > Number(roomsTo)) return false
      if (basementFrom && product.basement < Number(basementFrom)) return false
      if (basementTo && product.basement > Number(basementTo)) return false
      return true
    })

    if (sortBy) {
      result.sort((a, b) => {
        let compare = 0
        if (sortBy === 'price') {
          compare = (a.price ?? 0) - (b.price ?? 0)
        } else if (sortBy === 'name') {
          compare = a.name.localeCompare(b.name)
        } else if (sortBy === 'rooms') {
          compare = a.rooms - b.rooms
        } else if (sortBy === 'basement') {
          compare = a.basement - b.basement
        } else {
          compare = a.rarity.localeCompare(b.rarity)
        }
        return sortOrder === 'asc' ? compare : -compare
      })
    }

    return result
  }, [selectedRarity, priceFrom, priceTo, roomsFrom, roomsTo, basementFrom, basementTo, sortBy, sortOrder])

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
        <h2 className="tab-title">{t('shop.realestate')}</h2>
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
        <button className={`gpu-sort-btn ${sortBy === 'rarity' ? 'active' : ''}`} onClick={() => toggleSort('rarity')}>
          <ArrowUpDown size={14} />
          <span>{t('realestate.rarity')}</span>
          {sortBy === 'rarity' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'rooms' ? 'active' : ''}`} onClick={() => toggleSort('rooms')}>
          <Bed size={14} />
          <span>{t('realestate.rooms')}</span>
          {sortBy === 'rooms' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'basement' ? 'active' : ''}`} onClick={() => toggleSort('basement')}>
          <Box size={14} />
          <span>{t('realestate.basement')}</span>
          {sortBy === 'basement' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} />
          <span>{t('common.price')}</span>
          {sortBy === 'price' && <span className="sort-arrow">{sortOrder === 'asc' ? '↑' : '↓'}</span>}
        </button>
        {showFilters && (
          <div className="gpu-filter-panel">
            <div className="gpu-filter-row">
              <label>{t('realestate.rarity')}</label>
              <select value={selectedRarity} onChange={(e) => setSelectedRarity(e.target.value)}>
                <option value="">{t('common.all')}</option>
                {RARITIES.map(r => <option key={r} value={r}>{t(`realestate.rarities.${r}`)}</option>)}
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
              <label>{t('realestate.rooms')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={roomsFrom} onChange={(e) => setRoomsFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={roomsTo} onChange={(e) => setRoomsTo(e.target.value)} />
              </div>
            </div>
            <div className="gpu-filter-row">
              <label>{t('realestate.basement')}</label>
              <div className="gpu-filter-range">
                <input type="number" placeholder={t('common.from')} value={basementFrom} onChange={(e) => setBasementFrom(e.target.value)} />
                <span>—</span>
                <input type="number" placeholder={t('common.to')} value={basementTo} onChange={(e) => setBasementTo(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="shop-grid">
        {filteredProducts.map(product => {
          const colors = RARITY_COLORS[product.rarity] || RARITY_COLORS.common
          return (
            <ShopCard
              key={product.id}
              icon={Home}
              name={product.name}
              subtitle={t(`realestate.rarities.${product.rarity}`)}
              specs={[
                { icon: Bed, label: `${product.rooms} ${t('realestate.roomsShort')}` },
                { icon: Box, label: `${product.basement} ${t('realestate.basementShort')}` },
                { icon: Zap, label: product.tax !== null ? product.tax : t('common.notSet') },
              ]}
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

export { REAL_ESTATE_PRODUCTS }
export default RealEstateShop

