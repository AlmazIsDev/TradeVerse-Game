// Проверка: сколько slug-ов в adminCatalog.js
import {
  ADMIN_REAL_ESTATE_CATALOG,
  ADMIN_BUSINESS_CATALOG,
} from './frontend/src/utils/adminCatalog.js'

const re = ADMIN_REAL_ESTATE_CATALOG
const bz = ADMIN_BUSINESS_CATALOG
console.log('ADMIN_REAL_ESTATE_CATALOG:', re.length, 'items')
console.log('  first:', re[0]?.slug, '|', re[0]?.name, '|', re[0]?.price, '|', re[0]?.rarity)
console.log('  last:', re[re.length-1]?.slug, '|', re[re.length-1]?.name, '|', re[re.length-1]?.price, '|', re[re.length-1]?.rarity)
console.log('  unique slugs:', new Set(re.map(x=>x.slug)).size)
console.log()
console.log('ADMIN_BUSINESS_CATALOG:', bz.length, 'items')
for (const b of bz) console.log('  ', b.slug, '|', b.name, '|', b.price, '|', b.category_business, '|', b.employees, 'emp')
console.log('  unique slugs:', new Set(bz.map(x=>x.slug)).size)
console.log()
console.log('Total: ', re.length + bz.length, 'items (expected 93)')
