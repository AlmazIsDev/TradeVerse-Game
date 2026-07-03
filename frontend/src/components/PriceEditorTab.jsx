import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Save, RotateCcw, Monitor, Cpu, Box, Wrench, Home, Briefcase, Search, DollarSign } from 'lucide-react'

import { GPU_PRODUCTS } from './GpuShop'
import { CPU_PRODUCTS } from './CpuShop'
import { CASE_PRODUCTS } from './CaseShop'
import { SUPPLIES_PRODUCTS } from './SuppliesShop'
import { REAL_ESTATE_PRODUCTS } from './RealEstateShop'
import { BUSINESS_PRODUCTS } from './BusinessShop'

const PRICE_CATEGORIES = [
  { id: 'gpu', labelKey: 'admin.prices.gpu', icon: Monitor, products: GPU_PRODUCTS },
  { id: 'cpu', labelKey: 'admin.prices.cpu', icon: Cpu, products: CPU_PRODUCTS },
  { id: 'case', labelKey: 'admin.prices.case', icon: Box, products: CASE_PRODUCTS },
  { id: 'supplies', labelKey: 'admin.prices.supplies', icon: Wrench, products: SUPPLIES_PRODUCTS },
  { id: 'realestate', labelKey: 'admin.prices.realestate', icon: Home, products: REAL_ESTATE_PRODUCTS },
  { id: 'business', labelKey: 'admin.prices.business', icon: Briefcase, products },
]

function PriceEditorTab() {
  const { t } = useTranslation()
  const [activeCategory, setActiveCategory] = useState('gpu')
  const [prices, setPrices] = useState({})
  const [searchQuery, setSearchQuery] = useState('')
  const [hasChanges, setHasChanges] = useState(false)
  const [savedMessage, setSavedMessage] = useState(false)
  const [loading, setLoading] = useState(true)

  const currentCategory = PRICE_CATEGORIES.find(c => c.id === activeCategory)
  const products = currentCategory?.products || []

  useEffect(() => {
    let cancelled = false
    async function loadPrices() {
      try {
        const storedUser = localStorage.getItem('tradeverse_user')
        const token = storedUser ? JSON.parse(storedUser).token : null
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {}
        const resp = await fetch('/api/admin/shop-prices', { headers })
        if (!cancelled && resp.ok) {
          const data = await resp.json()
          if (!cancelled) {
            setPrices(data.prices || {})
          }
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadPrices()
    return () => { cancelled = true }
  }, [])

  const filteredProducts = searchQuery
    ? products.filter(p => p.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : products

  const handlePriceChange = useCallback((productId, value) => {
    setPrices(prev => {
      const updated = { ...prev, [productId]: value === '' ? null : parseFloat(value) || null }
      return updated
    })
    setHasChanges(true)
  }, [])

  const handleSave = useCallback(async () => {
    try {
      const storedUser = localStorage.getItem('tradeverse_user')
      const token = storedUser ? JSON.parse(storedUser).token : null
      const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      }
      await fetch('/api/admin/shop-prices', {
        method: 'POST',
        headers,
        body: JSON.stringify({ prices }),
      })
      setHasChanges(false)
      setSavedMessage(true)
      setTimeout(() => setSavedMessage(false), 2000)
    } catch {
      // ignore
    }
  }, [prices])

  const handleReset = useCallback(() => {
    if (!confirm(t('admin.prices.resetConfirm'))) return
    setPrices({})
    setHasChanges(true)
  }, [t])

  const handleResetCategory = useCallback(() => {
    if (!confirm(t('admin.prices.resetCategoryConfirm'))) return
    setPrices(prev => {
      const updated = { ...prev }
      products.forEach(p => {
        delete updated[p.id]
      })
      return updated
    })
    setHasChanges(true)
  }, [products, t])

  const getPrice = (productId) => {
    const val = prices[productId]
    return val !== undefined && val !== null ? val : ''
  }

  const formatPrice = (val) => {
    if (val === '' || val === null || val === undefined) return t('common.notSet')
    return `$${Number(val).toLocaleString()}`
  }

  const getCategoryStats = (cat) => {
    const setCount = cat.products.filter(p => prices[p.id] !== undefined && prices[p.id] !== null).length
    return { set: setCount, total: cat.products.length }
  }

  if (loading) {
    return <div className="price-editor">{t('common.loading')}</div>
  }

  return (
    <div className="price-editor">
      <div className="price-editor-categories">
        {PRICE_CATEGORIES.map(cat => {
          const stats = getCategoryStats(cat)
          const Icon = cat.icon
          return (
            <button
              key={cat.id}
              className={`price-editor-category-btn ${activeCategory === cat.id ? 'active' : ''}`}
              onClick={() => { setActiveCategory(cat.id); setSearchQuery('') }}
            >
              <Icon size={16} />
              <span>{t(cat.labelKey)}</span>
              <span className="price-editor-category-stats">
                {stats.set}/{stats.total}
              </span>
            </button>
          )
        })}
      </div>

      <div className="price-editor-toolbar">
        <div className="price-editor-search">
          <Search size={16} />
          <input
            type="text"
            placeholder={t('admin.prices.searchPlaceholder')}
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="price-editor-search-input"
          />
        </div>
        <div className="price-editor-actions">
          <button className="admin-btn" onClick={handleResetCategory}>
            <RotateCcw size={14} />
            <span>{t('admin.prices.resetCategory')}</span>
          </button>
          <button className="admin-btn" onClick={handleReset}>
            <RotateCcw size={14} />
            <span>{t('admin.prices.resetAll')}</span>
          </button>
          <button
            className={`admin-btn admin-btn-primary ${!hasChanges ? 'disabled' : ''}`}
            onClick={handleSave}
            disabled={!hasChanges}
          >
            <Save size={14} />
            <span>{t('admin.save')}</span>
          </button>
        </div>
      </div>

      {savedMessage && (
        <div className="price-editor-saved-msg">
          {t('admin.prices.saved')}
        </div>
      )}

      <div className="price-editor-table-wrapper">
        <table className="price-editor-table">
          <thead>
            <tr>
              <th className="price-editor-th-id">ID</th>
              <th className="price-editor-th-name">{t('common.name')}</th>
              <th className="price-editor-th-price">{t('common.price')}</th>
              <th className="price-editor-th-current">{t('admin.prices.currentPrice')}</th>
            </tr>
          </thead>
          <tbody>
            {filteredProducts.map(product => {
              const currentPrice = getPrice(product.id)
              const hasPrice = currentPrice !== '' && currentPrice !== null && currentPrice !== undefined
              return (
                <tr key={product.id} className={`price-editor-row ${hasPrice ? 'has-price' : 'no-price'}`}>
                  <td className="price-editor-td-id">{product.id}</td>
                  <td className="price-editor-td-name">
                    <span className="price-editor-product-name">{product.name}</span>
                    {product.company && (
                      <span className="price-editor-product-meta">{product.company} · {product.line}</span>
                    )}
                  </td>
                  <td className="price-editor-td-price">
                    <div className="price-editor-input-wrapper">
                      <DollarSign size={14} className="price-editor-input-icon" />
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={currentPrice}
                        onChange={e => handlePriceChange(product.id, e.target.value)}
                        placeholder="0"
                        className="price-editor-input"
                      />
                    </div>
                  </td>
                  <td className="price-editor-td-current">
                    <span className={`price-editor-current-value ${hasPrice ? 'set' : 'not-set'}`}>
                      {formatPrice(currentPrice)}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {filteredProducts.length === 0 && (
          <div className="price-editor-empty">
            {t('admin.prices.noProducts')}
          </div>
        )}
      </div>

      <div className="price-editor-footer">
        <span>{t('admin.prices.totalProducts', { count: filteredProducts.length })}</span>
        <span>
          {t('admin.prices.pricesSet', {
            count: filteredProducts.filter(p => prices[p.id] !== undefined && prices[p.id] !== null).length
          })}
        </span>
      </div>
    </div>
  )
}

export default PriceEditorTab
