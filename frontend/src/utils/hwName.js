// Локализованное имя товара из магазина оборудования.
// GPU уже имеют брендовое (латинское) имя — не переводим. Остальные категории
// собираются из category + specs через i18n-шаблон, чтобы не хранить
// переведённые строки на бэкенде.
const COOLING_BY_CAP = { 400: 'air', 800: 'tower', 1600: 'liquid', 4000: 'immersion' }
const CASE_BY_SLOTS = { 2: 'mini', 4: 'midi', 8: 'full' }
const FAN_BY_CAP = { 200: 'set120', 320: 'set140', 700: 'industrial' }
// Стойки (rack) вернулись: имя из каталога показывается как есть (default).
const NETWORK_BY_SPEED = { 1000: 'router', 10000: 'switch' }

export function hwName(item, t) {
  const { category, specs = {}, name } = item || {}
  // Реальное (брендовое) имя приоритетнее шаблона: раньше шаблон подменял
  // названия всех категорий, кроме GPU («Процессор N ядер» вместо модели).
  // Шаблон используется только когда имени нет совсем.
  if (name) return name
  switch (category) {
    case 'psu': return t('shop.psuName', { w: specs.power, defaultValue: '' })
    case 'cpu': return t('shop.cpuName', { cores: specs.cores, defaultValue: '' })
    case 'motherboard': return t('shop.mbName', { slots: specs.gpuSlots, defaultValue: '' })
    case 'ram': return t('shop.ramName', { gb: specs.gb, defaultValue: '' })
    case 'ssd': return t('shop.ssdName', { gb: specs.gb, defaultValue: '' })
    case 'ups': return t('shop.upsName', { w: specs.backup, defaultValue: '' })
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
