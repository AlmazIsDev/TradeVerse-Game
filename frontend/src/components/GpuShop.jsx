import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Monitor, Zap, DollarSign, ArrowUpDown, AlertTriangle, Check } from 'lucide-react'
import { fetchShopCatalog, buyHardware } from '../services/api'
import { formatMoney } from './TransactionsPanel'

const BRAND_COLORS = {
  CrystalCore: '#818cf8', Pyronix: '#fb923c', Archivex: '#4ade80',
}

// Статический каталог используется админ-панелью (PriceEditorTab) для управления ценами.
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

function GpuShop({ onBack, balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [brand, setBrand] = useState('')
  const [sortBy, setSortBy] = useState('price')
  const [sortOrder, setSortOrder] = useState('asc')
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await fetchShopCatalog('gpu'))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const brands = useMemo(() => [...new Set(items.map(i => i.brand).filter(Boolean))], [items])

  const filtered = useMemo(() => {
    let r = items.filter(i => !brand || i.brand === brand)
    r = [...r].sort((a, b) => {
      const va = sortBy === 'hashrate' ? (a.specs?.hashrate || 0) : a.price
      const vb = sortBy === 'hashrate' ? (b.specs?.hashrate || 0) : b.price
      return sortOrder === 'asc' ? va - vb : vb - va
    })
    return r
  }, [items, brand, sortBy, sortOrder])

  const flash = (text, type = 'success') => { setMsg({ text, type }); setTimeout(() => setMsg(null), 2200) }

  const buy = async (item) => {
    setBusyId(item.id)
    try {
      const res = await buyHardware(item.id, 1)
      onBalanceChange?.(res.balance)
      flash(t('market.bought'))
      await load()   // цены могли сдвинуться
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const toggleSort = (field) => {
    if (sortBy === field) setSortOrder(o => (o === 'asc' ? 'desc' : 'asc'))
    else { setSortBy(field); setSortOrder('asc') }
  }

  const fmtHash = (h) => (h >= 1000 ? `${(h / 1000).toFixed(1)}k` : `${h}`)

  return (
    <div className="shop-tab">
      <div className="shop-section-header">
        <button className="shop-back-btn" onClick={onBack}><ArrowLeft size={18} /><span>{t('shop.gpu')}</span></button>
        <h2 className="tab-title">{t('shop.gpuCards')}</h2>
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

      <div className="gpu-toolbar">
        <select className="admin-input" value={brand} onChange={e => setBrand(e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">{t('common.all')}</option>
          {brands.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        <button className={`gpu-sort-btn ${sortBy === 'hashrate' ? 'active' : ''}`} onClick={() => toggleSort('hashrate')}>
          <Zap size={14} /> {t('gpu.hashrate')} {sortBy === 'hashrate' && (sortOrder === 'asc' ? '↑' : '↓')}
        </button>
        <button className={`gpu-sort-btn ${sortBy === 'price' ? 'active' : ''}`} onClick={() => toggleSort('price')}>
          <DollarSign size={14} /> {t('common.price')} {sortBy === 'price' && (sortOrder === 'asc' ? '↑' : '↓')}
        </button>
      </div>

      {loading && (
        <div className="gpu-grid">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="gpu-card skeleton" style={{ height: 150 }} />)}
        </div>
      )}
      {error && <div className="error-state"><AlertTriangle size={24} className="error-icon" color="#fca5a5" /><p>{t('common.error')}: {error}</p></div>}

      {!loading && !error && (
        <div className="gpu-grid">
          {filtered.map(item => {
            const color = BRAND_COLORS[item.brand] || item.color || '#6366f1'
            const affordable = balance >= item.price
            return (
              <div key={item.id} className="gpu-card" style={{ borderColor: `${color}55` }}>
                <span className="gpu-card-icon" style={{ background: color }}><Monitor size={22} /></span>
                <span className="gpu-card-name">{item.name}</span>
                <div className="gpu-card-specs">
                  <span><Zap size={12} style={{ color }} /> {fmtHash(item.specs?.hashrate || 0)} H/s</span>
                  <span>{item.specs?.power || 0}W</span>
                </div>
                <div className="gpu-card-price"><DollarSign size={12} style={{ color }} /> ${formatMoney(item.price)}</div>
                <button
                  className="gpu-card-buy"
                  style={{ background: affordable ? color : undefined }}
                  disabled={!affordable || busyId === item.id}
                  onClick={() => buy(item)}
                >
                  {busyId === item.id ? t('bank.processing') : affordable ? t('common.buy') : t('stocks.insufficientFunds')}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export { GPU_PRODUCTS }
export default GpuShop
