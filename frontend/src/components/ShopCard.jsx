import { useTranslation } from 'react-i18next'
import { DollarSign, ShoppingCart } from 'lucide-react'

function ShopCard({ icon: Icon, name, subtitle, specs, price, priceLabel, colors, onBuy }) {
  const { t } = useTranslation()

  return (
    <div className="shop-card" style={{ '--card-accent': colors.accent, '--card-border': colors.border, '--card-bg': colors.bg, '--card-icon': colors.icon }}>
      <div className="shop-card-glow" />
      <div className="shop-card-accent-bar" style={{ background: `linear-gradient(90deg, ${colors.accent}, transparent)` }} />
      <div className="shop-card-header">
        <div className="shop-card-icon-wrap">
          <Icon size={22} />
        </div>
        <div className="shop-card-title">
          <span className="shop-card-name">{name}</span>
          {subtitle && <span className="shop-card-subtitle" style={{ color: colors.icon }}>{subtitle}</span>}
        </div>
      </div>

      {specs && specs.length > 0 && (
        <div className="shop-card-specs">
          {specs.map((spec, i) => (
            <div key={i} className="shop-card-spec" style={{ borderColor: `${colors.icon}22`, background: `${colors.icon}0a` }}>
              {spec.icon && <spec.icon size={12} style={{ color: colors.icon }} />}
              <span>{spec.label}</span>
            </div>
          ))}
        </div>
      )}

      <div className="shop-card-footer">
        <div className="shop-card-price">
          <DollarSign size={13} style={{ color: colors.icon }} />
          <span className="shop-card-price-value">
            {price !== null && price !== undefined ? `$${price.toLocaleString()}` : t('common.notSet')}
          </span>
          {priceLabel && <span className="shop-card-price-label">{priceLabel}</span>}
        </div>
        <button className="shop-card-buy" style={{ background: colors.accent }} onClick={onBuy}>
          <ShoppingCart size={13} />
          <span>{t('common.buy')}</span>
        </button>
      </div>
    </div>
  )
}

export default ShopCard
