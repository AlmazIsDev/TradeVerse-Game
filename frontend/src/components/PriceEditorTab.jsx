// ─────────────────────────────────────────────────────────────────────────────
// PriceEditorTab · редактор цен для админ-панели.
// Поддерживает все секции каталога:
//   - базовые: gpu / cpu / case / supplies (shopCatalog)
//   - недвижимость и бизнесы: realestate / business (adminCatalog, 81+12)
//   - рынок: factory / source / warehouse (adminCatalog)
//   - автосалон: cars (carsCatalog, 5 машин + 3 фуры + 4 прицепа)
//
// У каждой позиции есть строковый или числовой `id` (для gpu/cpu/case/supplies
// — это productId, для остальных — slug вида `admin-fac-gpu-1`). Цены
// отправляются в /api/admin/shop-prices как `{ [id]: number }`.
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Save, RotateCcw, Monitor, Cpu, Box, Wrench,
  Home, Briefcase, Factory, Mountain, Warehouse, Car,
  Search, DollarSign,
} from 'lucide-react'

// Базовые каталоги (числовые productId).
import {
  GPU_PRODUCTS, CPU_PRODUCTS, CASE_PRODUCTS,
  SUPPLIES_PRODUCTS, REAL_ESTATE_PRODUCTS, BUSINESS_PRODUCTS,
} from '../utils/shopCatalog'
// Дефолтные цены из adminCatalog.js: для старых категорий ключи = productId,
// для новых — slug-строки (admin-fac-*, admin-src-*, admin-wh-*, car-*, ...).
import { ADMIN_DEFAULT_PRICES } from '../utils/adminCatalog'
// Каталог машин/фур/прицепов.
import { CARS_CATALOG } from '../utils/carsCatalog'

// Преобразуем запись каталога в формат «продукт для редактора» с полями
// { id, name, rarity?, meta?, category? }.
function _toEditorProduct(p) {
  return {
    id: p.slug || p.id,           // id (ключ цены) — всегда строка для совместимости
    name: p.name,
    rarity: p.rarity,
    // Доп. поля для подписи под именем.
    meta: p.specs?.areaSqm != null
      ? `${p.specs.areaSqm.toLocaleString('ru-RU')} м²`
      : p.specs?.outputPerHour != null
        ? `${p.specs.outputPerHour}/ч`
        : p.specs?.resource
          ? p.specs.resource
          : null,
    category: p.category || null,
    type: p.type || null,
  }
}

const PRICE_CATEGORIES = [
  { id: 'gpu',        labelKey: 'admin.prices.gpu',        icon: Monitor,  products: GPU_PRODUCTS },
  { id: 'cpu',        labelKey: 'admin.prices.cpu',        icon: Cpu,      products: CPU_PRODUCTS },
  { id: 'case',       labelKey: 'admin.prices.case',       icon: Box,      products: CASE_PRODUCTS },
  { id: 'supplies',   labelKey: 'admin.prices.supplies',   icon: Wrench,   products: SUPPLIES_PRODUCTS },
  { id: 'realestate', labelKey: 'admin.prices.realestate', icon: Home,     products: REAL_ESTATE_PRODUCTS },
  { id: 'business',   labelKey: 'admin.prices.business',   icon: Briefcase,products: BUSINESS_PRODUCTS },
  // Рынок.
  { id: 'factory',    labelKey: 'admin.prices.factory',    icon: Factory,  products: null /* см. buildFactoryProducts() */ },
  { id: 'source',     labelKey: 'admin.prices.source',     icon: Mountain, products: null },
  { id: 'warehouse',  labelKey: 'admin.prices.warehouse',  icon: Warehouse,products: null },
  // Автосалон.
  { id: 'cars',       labelKey: 'admin.prices.cars',       icon: Car,      products: CARS_CATALOG },
]

// Строим «продукты» для рыночных категорий из adminCatalog-экспортов
// (берём из ADMIN_DEFAULT_PRICES нельзя — нужны ещё name/rarity). Поэтому
// импортируем исходные массивы через модуль adminCatalog: они не лежат в
// нём отдельно, поэтому собираем напрямую из дефолтных ключей:
// так как имена хранятся в slug-ключах, проще собрать плоский список
// вручную из adminCatalog.
import {
  ADMIN_FACTORIES_CATALOG,
  ADMIN_SOURCES_CATALOG,
  ADMIN_WAREHOUSES_CATALOG,
} from '../utils/adminCatalog'

const FACTORY_PRODUCTS = ADMIN_FACTORIES_CATALOG.map(_toEditorProduct)
const SOURCE_PRODUCTS = ADMIN_SOURCES_CATALOG.map(_toEditorProduct)
const WAREHOUSE_PRODUCTS = ADMIN_WAREHOUSES_CATALOG.map(_toEditorProduct)
const CAR_PRODUCTS = CARS_CATALOG.map(_toEditorProduct)

// Привязка категорий к подготовленным спискам.
const CATALOG_BY_ID = {
  factory:   FACTORY_PRODUCTS,
  source:    SOURCE_PRODUCTS,
  warehouse: WAREHOUSE_PRODUCTS,
  cars:      CAR_PRODUCTS,
}

function PriceEditorTab() {
  const { t } = useTranslation()
  const [activeCategory, setActiveCategory] = useState('gpu')
  const [prices, setPrices] = useState({})
  const [searchQuery, setSearchQuery] = useState('')
  const [hasChanges, setHasChanges] = useState(false)
  const [savedMessage, setSavedMessage] = useState(false)
  const [saveError, setSaveError] = useState(false)
  const [loading, setLoading] = useState(true)

  // Текущая категория и её продукты. Для gpu/cpu/case/supplies/realestate/
  // business — берём исходные объекты (с числовым id). Для новых — нормализованные.
  const currentCategory = PRICE_CATEGORIES.find(c => c.id === activeCategory)
  const rawProducts = currentCategory?.products
  // Нормализуем в формат «id/name/rarity/meta/category». Дома/бизнесы
  // ключуются slug'ом (admin-re-N / admin-biz-N), как их хранит бэкенд:
  // голые числа коллидировали между вкладками — правка цены дома «2»
  // перезаписывала и цену бизнеса «2».
  const products = rawProducts
    ? rawProducts.map(p => ({
        id: activeCategory === 'realestate' ? `admin-re-${p.id}`
          : activeCategory === 'business' ? `admin-biz-${p.id}`
          : p.id,
        name: p.name, rarity: p.rarity,
        meta: null, category: p.category || null, type: null,
      }))
    : (CATALOG_BY_ID[activeCategory] || [])

  // Загрузка цен из API.
  useEffect(() => {
    let cancelled = false
    async function loadPrices() {
      try {
        const storedUser = localStorage.getItem('tradeverse_user')
        const token = storedUser ? JSON.parse(storedUser).token : null
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {}
        const resp = await fetch('/api/admin/shop/prices', { headers })
        if (!cancelled && resp.ok) {
          const data = await resp.json()
          if (!cancelled) {
            // Бэкенд хранит только ИЗМЕНЁННЫЕ админом цены. Для всех id,
            // которых нет в ответе, подмешиваем дефолт из adminCatalog.
            const stored = data.prices || {}
            const merged = { ...ADMIN_DEFAULT_PRICES }
            for (const k of Object.keys(stored)) {
              if (stored[k] !== undefined) merged[k] = stored[k]
            }
            setPrices(merged)
          }
        } else {
          // Нет бэкенда / не админ — используем дефолты, чтобы редактор был полезен.
          setPrices({ ...ADMIN_DEFAULT_PRICES })
        }
      } catch {
        setPrices({ ...ADMIN_DEFAULT_PRICES })
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadPrices()
    return () => { cancelled = true }
  }, [])

  // Фильтрация по поиску.
  const filteredProducts = searchQuery
    ? products.filter(p =>
        (p.name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        String(p.id).toLowerCase().includes(searchQuery.toLowerCase()),
      )
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
      // Шлём только реальные оверрайды ТЕКУЩЕЙ вкладки: бэкенд хранит
      // изменённые админом цены, а null — сброс к формуле. Дефолты из
      // adminCatalog отправлять нельзя, иначе фронтовый хардкод станет
      // источником истины и затрёт БД. Без фильтра по вкладке числовые ключи
      // чужих категорий бэкенд пере-мапил бы в текущую категорию.
      const validIds = new Set(products.map(p => String(p.id)))
      const overrides = {}
      for (const [id, value] of Object.entries(prices)) {
        if (!validIds.has(id)) continue
        const def = ADMIN_DEFAULT_PRICES[id]
        if (value === null || value === undefined) {
          if (def !== undefined) overrides[id] = null
        } else if (def === undefined || Math.abs(Number(value) - def) > 1e-9) {
          overrides[id] = value
        }
      }
      const storedUser = localStorage.getItem('tradeverse_user')
      const token = storedUser ? JSON.parse(storedUser).token : null
      const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      }
      const resp = await fetch('/api/admin/shop/prices', {
        method: 'POST',
        headers,
        body: JSON.stringify({ prices: overrides, category: activeCategory }),
      })
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      setHasChanges(false)
      setSaveError(false)
      setSavedMessage(true)
      setTimeout(() => setSavedMessage(false), 2000)
    } catch (err) {
      console.error('Не удалось сохранить цены:', err)
      setSavedMessage(false)
      setSaveError(true)
      setTimeout(() => setSaveError(false), 3000)
    }
  }, [prices, activeCategory, products])

  const handleReset = useCallback(() => {
    if (!confirm(t('admin.prices.resetConfirm'))) return
    // null = сброс к формуле на бэкенде, поэтому ключи не удаляем, а зануляем.
    const reset = {}
    Object.keys(ADMIN_DEFAULT_PRICES).forEach(k => { reset[k] = null })
    setPrices(reset)
    setHasChanges(true)
  }, [t])

  const handleResetCategory = useCallback(() => {
    if (!confirm(t('admin.prices.resetCategoryConfirm'))) return
    setPrices(prev => {
      const updated = { ...prev }
      products.forEach(p => { updated[p.id] = null })
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

  // Подсчёт установленных цен для каждой категории.
  const getCategoryStats = (cat) => {
    const list = cat.products
      ? cat.products.map(p => ({ id: p.id }))
      : (CATALOG_BY_ID[cat.id] || [])
    const setCount = list.filter(p => prices[p.id] !== undefined && prices[p.id] !== null).length
    return { set: setCount, total: list.length }
  }

  if (loading) {
    return <div className="price-editor">{t('common.loading')}</div>
  }

  return (
    <div className="price-editor">
      {/* Категории-вкладки */}
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

      {/* Панель инструментов */}
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

      {saveError && (
        <div className="price-editor-saved-msg price-editor-save-error">
          {t('admin.prices.saveFailed', 'Не удалось сохранить цены')}
        </div>
      )}

      {/* Таблица товаров */}
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
                    {product.rarity && (
                      <span className="price-editor-product-meta">{t(`realestate.rarities.${product.rarity}`, product.rarity)}</span>
                    )}
                    {product.meta && (
                      <span className="price-editor-product-meta">{product.meta}</span>
                    )}
                    {product.category && activeCategory === 'supplies' && (
                      <span className="price-editor-product-meta">{t(`supplies.${product.category}`, product.category)}</span>
                    )}
                    {product.category && activeCategory === 'business' && (
                      <span className="price-editor-product-meta">{t(`business.categories.${product.category}`, product.category)}</span>
                    )}
                    {product.category && activeCategory === 'cars' && (
                      <span className="price-editor-product-meta">{t(`cars.cat_${product.category}`, product.category)}</span>
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

      {/* Итого */}
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
