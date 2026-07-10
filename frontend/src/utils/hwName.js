// Локализованное имя товара из магазина оборудования.
// GPU уже имеют брендовое (латинское) имя — не переводим. Остальные категории
// собираются из category + specs через i18n-шаблон, чтобы не хранить
// переведённые строки на бэкенде.
const COOLING_BY_CAP = { 400: 'air', 800: 'tower', 1600: 'liquid', 4000: 'immersion' }
const CASE_BY_SLOTS = { 2: 'mini', 4: 'midi', 8: 'full' }
const FAN_BY_CAP = { 200: 'set120', 320: 'set140', 700: 'industrial' }
const NETWORK_BY_SPEED = { 1000: 'router', 10000: 'switch', 40000: 'rack' }

export function hwName(item, t) {
  const { category, specs = {}, name } = item || {}
  switch (category) {
    case 'psu': return t('shop.psuName', { w: specs.power, defaultValue: name })
    case 'cpu': return t('shop.cpuName', { cores: specs.cores, defaultValue: name })
    case 'motherboard': return t('shop.mbName', { slots: specs.gpuSlots, defaultValue: name })
    case 'ram': return t('shop.ramName', { gb: specs.gb, defaultValue: name })
    case 'ssd': return t('shop.ssdName', { gb: specs.gb, defaultValue: name })
    case 'ups': return t('shop.upsName', { w: specs.backup, defaultValue: name })
    case 'rack': return t(specs.industrial ? 'shop.rackIndName' : 'shop.rackName', { slots: specs.slots, defaultValue: name })
    case 'cooling': {
      const key = COOLING_BY_CAP[specs.cooling]
      return key ? t(`shop.coolingName.${key}`, name) : name
    }
    case 'case': {
      const key = CASE_BY_SLOTS[specs.slots]
      return key ? t(`shop.caseName.${key}`, name) : name
    }
    case 'fan': {
      const key = FAN_BY_CAP[specs.cooling]
      return key ? t(`shop.fanName.${key}`, name) : name
    }
    case 'network': {
      const key = NETWORK_BY_SPEED[specs.speed]
      return key ? t(`shop.networkName.${key}`, name) : name
    }
    default: return name
  }
}
