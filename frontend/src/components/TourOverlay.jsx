import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchFarms, fetchHardwareInventory, fetchMyAssets } from '../services/api'
import '../tour.css'

// Обязательные категории фермы — зеркало REQUIRED_ROLES из backend/mining.py
// (там же добавочные требования: минимум один GPU и хотя бы один БП).
// cooling и network обязательны на сервере, поэтому и тур их требует —
// иначе игрок проходит проверку с фермой, которую сервер запускать откажется.
const MINING_ROLES = ['motherboard', 'cpu', 'ram', 'ssd', 'cooling', 'network']
const PSU_ROLE = 'psu'

function farmList(data) {
  if (Array.isArray(data)) return data
  return data?.farms ?? (data?.farm ? [data.farm] : [])
}

// Слот может быть объектом детали либо массивом (вентиляторы, БП).
function hasItem(slot) {
  const one = Array.isArray(slot) ? slot[0] : slot
  return !!(one && (one.hwId || one.itemId))
}

function rolesFilled(components) {
  const c = components || {}
  const required = MINING_ROLES.every(role => hasItem(c[role]))
  // Сервер дополнительно требует хотя бы один БП (comp.psu или comp.psus[0]).
  const psu = c[PSU_ROLE] ?? c.psus?.[0]
  return required && hasItem(psu)
}

const STEP_CHECKS = {
  async hasBasementHouse() {
    const data = await fetchMyAssets('realestate')
    const list = Array.isArray(data) ? data : (data?.assets ?? data?.items ?? [])
    return list.some(a => (a.basement ?? 0) > 0)
  },
  async hasFarm() {
    return farmList(await fetchFarms()).length > 0
  },
  async hasAllRoles() {
    const inv = await fetchHardwareInventory()
    const items = Array.isArray(inv) ? inv : (inv?.items ?? [])
    const free = role => items.some(i => i.category === role && !i.farmId)
    return [...MINING_ROLES, PSU_ROLE].every(free)
  },
  async allRolesInstalled() {
    const farms = farmList(await fetchFarms())
    return farms.some(f => rolesFilled(f.components))
  },
  async farmRunning() {
    const farms = farmList(await fetchFarms())
    return farms.some(f => f.status === 'running' || f.running === true)
  },
}

// Шаг `choose` замыкает основной тур: вместо продолжения игрок выбирает отрасль,
// и тур переключается на её сценарий. Текст берётся из i18n по ключу `key`.
const CHOICE_STEP = {
  tab: 'tutorial',
  target: null,
  choose: true,
  key: 'tour.main.choice',
}

// Шаги описывают только поведение (вкладка, цель, проверка); тексты —
// в локалях под `tour.*`. Так тур переводится вместе с остальным интерфейсом.
const MAIN_TOUR = [
  { tab: 'account', target: null, key: 'tour.main.welcome' },
  { tab: 'account', target: 'account', key: 'tour.main.account' },
  { tab: 'bank', target: 'bank', key: 'tour.main.bank' },
  { tab: 'stocks', target: 'stocks', key: 'tour.main.stocks' },
  { tab: 'crypto', target: 'crypto', key: 'tour.main.crypto' },
  { tab: 'realestate', target: 'realestate', key: 'tour.main.realestate' },
  { tab: 'mining', target: 'mining', key: 'tour.main.mining' },
  { tab: 'mycompany', target: 'mycompany', key: 'tour.main.mycompany' },
  { tab: 'mycompany', target: 'mycompany', key: 'tour.main.openBusiness' },
  { tab: 'achievements', target: 'achievements', key: 'tour.main.achievements' },
  CHOICE_STEP,
]

const SCRIPTS = {
  main: MAIN_TOUR,
  mining: [
    { tab: 'realestate', target: null, key: 'tour.miningTour.s1' },
    { tab: 'realestate', target: 'realestate', key: 'tour.miningTour.s2' },
    { tab: 'realestate', target: 'realestate', key: 'tour.miningTour.s3' },
    { tab: 'realestate', target: 'realestate', key: 'tour.miningTour.s4' },
    { tab: 'realestate', target: null, key: 'tour.miningTour.s5' },
    { tab: 'account', target: 'account', key: 'tour.miningTour.s6' },
    { tab: 'realestate', target: 'tour-buy', interactive: true, on: 'buy-open', key: 'tour.miningTour.s7' },
    { tab: 'realestate', target: null, interactive: true, on: 'buy-done', key: 'tour.miningTour.s8' },
    { tab: 'realestate', target: 'realestate', key: 'tour.miningTour.s9', check: 'hasBasementHouse', auto: true },
    { tab: 'myhomes', target: 'myhomes', key: 'tour.miningTour.s10' },
    { tab: 'myhomes', target: null, key: 'tour.miningTour.s11' },
    { tab: 'myhomes', target: null, key: 'tour.miningTour.s12' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s13' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s14' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s15' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s16', check: 'hasFarm' },
    { tab: 'shop', target: 'shop', key: 'tour.miningTour.s17' },
    { tab: 'shop', target: 'shop', key: 'tour.miningTour.s18' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s191' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s192' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s193' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s194' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s195' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s196' },
    { tab: 'shop', target: null, key: 'tour.miningTour.s197' },
    { tab: 'shop', target: 'tour-cheapest', key: 'tour.miningTour.s198' },
    { tab: 'shop', target: 'shop', key: 'tour.miningTour.s199', check: 'hasAllRoles' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s20' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s21', check: 'allRolesInstalled' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s22' },
    { tab: 'mining', target: 'mining', key: 'tour.miningTour.s23', check: 'farmRunning' },
  ],
  stocks: [
    { tab: 'stocks', target: 'stocks', key: 'tour.stocksTour.market' },
    { tab: 'stocks', target: null, key: 'tour.stocksTour.fee' },
    { tab: 'account', target: 'account', key: 'tour.stocksTour.portfolio' },
  ],
  crypto: [
    { tab: 'crypto', target: 'crypto', key: 'tour.crypto.tab' },
    { tab: 'crypto', target: null, key: 'tour.crypto.xp' },
    { tab: 'achievements', target: 'achievements', key: 'tour.crypto.achievements' },
  ],
  realestate: [
    { tab: 'realestate', target: 'realestate', key: 'tour.realestateTour.market' },
    { tab: 'myhomes', target: 'myhomes', key: 'tour.realestateTour.myhomes' },
    { tab: 'myhomes', target: null, key: 'tour.realestateTour.limit' },
  ],
  business: [
    { tab: 'mycompany', target: 'mycompany', key: 'tour.businessTour.company' },
    { tab: 'mycompany', target: null, key: 'tour.businessTour.budget' },
    { tab: 'playerbusinesses', target: 'playerbusinesses', key: 'tour.businessTour.players' },
  ],
}

const CHOICES = [
  { key: 'mining', labelKey: 'tour.choices.mining' },
  { key: 'stocks', labelKey: 'tour.choices.stocks' },
  { key: 'crypto', labelKey: 'tour.choices.crypto' },
  { key: 'realestate', labelKey: 'tour.choices.realestate' },
  { key: 'business', labelKey: 'tour.choices.business' },
]

const CARD_WIDTH = 320

// startKey: 'main' — полный тур; иначе ключ отрасли (mining, stocks, …).
function TourOverlay({ startKey = 'main', onTabChange, onClose }) {
  const { t } = useTranslation()
  const [scriptKey, setScriptKey] = useState(startKey)
  const [index, setIndex] = useState(0)
  const [rect, setRect] = useState(null)
  const steps = SCRIPTS[scriptKey] || MAIN_TOUR
  const step = steps[index]
  const isLast = index === steps.length - 1
  const isChoice = !!step.choose
  // Тексты шага лежат в локалях по ключу; если ключа нет — показываем сам ключ,
  // чтобы пропуск перевода был виден при отладке, а не молча пустой карточкой.
  const stepTitle = step.key ? t(`${step.key}.title`) : ''
  const stepText = step.key ? t(`${step.key}.text`) : ''

  useEffect(() => {
    onTabChange?.(step.tab)
  }, [step.tab, onTabChange])

  // Замер цели шага. Вкладка переключается эффектом выше, то есть уже ПОСЛЕ
  // этого layout-эффекта, поэтому сразу замерить нельзя: целевого элемента
  // ещё нет в DOM. Ждём кадр и, если не нашли, доискиваемся до появления узла.
  useLayoutEffect(() => {
    let frame = 0
    let observer = null

    const apply = (el) => {
      const r = el.getBoundingClientRect()
      setRect({ top: r.top - 6, left: r.left - 6, width: r.width + 12, height: r.height + 12 })
    }

    const measure = () => {
      if (!step.target) { setRect(null); return true }
      const el = document.querySelector(`[data-tour="${step.target}"]`)
      if (!el) { setRect(null); return false }
      apply(el)
      return true
    }

    if (!measure()) {
      // Вкладка ещё монтируется — дожидаемся узла в следующем кадре.
      frame = requestAnimationFrame(() => {
        if (measure()) return
        observer = new MutationObserver(() => { if (measure()) observer?.disconnect() })
        observer.observe(document.body, { childList: true, subtree: true })
      })
    }

    const onResize = () => measure()
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', onResize)
    }
  }, [step.target, step.tab, index])

  // Подсветка самого элемента шага (например, кнопки «Купить» на шаге 7):
  // добавляем класс tour-pulse, он снимается при смене шага или размонтировании.
  // Целевой узел может появиться только после переключения вкладки, поэтому
  // при отсутствии элемента ждём следующий кадр, а затем мутации DOM.
  useEffect(() => {
    if (!step.target) return undefined
    let el = document.querySelector(`[data-tour="${step.target}"]`)
    let observer = null
    let frame = 0

    const attach = () => {
      el = document.querySelector(`[data-tour="${step.target}"]`)
      if (!el) return false
      el.classList.add('tour-pulse')
      observer?.disconnect()
      observer = null
      return true
    }

    if (!attach()) {
      frame = requestAnimationFrame(() => {
        if (attach()) return
        observer = new MutationObserver(() => { attach() })
        observer.observe(document.body, { childList: true, subtree: true })
      })
    }

    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      el?.classList.remove('tour-pulse')
    }
  }, [step.target, step.tab, index])

  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState(null)
  // Шаги, на которые игрок вернулся кнопкой «Назад»: их авто-проверка
  // отключена, иначе шаг с auto:true мгновенно прыгает вперёд и назад
  // вернуться невозможно.
  const skippedAuto = useRef(new Set())

  // Зависимости у next стабильны: функция пересоздаётся только на смену шага,
  // а не на каждый рендер, чтобы её можно было класть в списки зависимостей.
  const next = useCallback(async () => {
    if (step.check) {
      setChecking(true)
      setCheckError(null)
      try {
        const ok = await STEP_CHECKS[step.check]()
        if (!ok) { setCheckError(t('tour.stepNotDone')); return }
      } catch (err) {
        setCheckError(err.message)
        return
      } finally {
        setChecking(false)
      }
    }
    setIndex(i => Math.min(i + 1, steps.length - 1))
  }, [step, steps.length, t])

  const back = useCallback(() => {
    const target = Math.max(index - 1, 0)
    skippedAuto.current.add(target)
    setIndex(target)
  }, [index])

  const choose = (key) => {
    // Смена сценария всегда начинается с первого шага, а авто-проверки
    // прошлого сценария к новому не относятся.
    skippedAuto.current = new Set()
    setScriptKey(key)
    setIndex(0)
  }

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
      else if (e.key === 'ArrowRight' && !isChoice && !isLast && !step.on) next()
      else if (e.key === 'ArrowLeft' && index > 0) back()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, isChoice, isLast, onClose, step.on, next, back])

  // Автопереход по событию приложения (tv:tour): шаг засчитан после реального действия.
  useEffect(() => {
    if (!step.on) return undefined
    const onEvt = (e) => {
      if (e.detail?.type === step.on) setIndex(i => Math.min(i + 1, steps.length - 1))
    }
    window.addEventListener('tv:tour', onEvt)
    return () => window.removeEventListener('tv:tour', onEvt)
  }, [step.on, steps.length])

  // Авто-проверка шага при входе (например, шаг 9 после покупки).
  // Шаг, на который вернулись «Назад», не проверяем — это и есть смысл возврата.
  useEffect(() => {
    if (!step.auto || !step.check) return
    if (skippedAuto.current.has(index)) {
      skippedAuto.current.delete(index)
      return
    }
    next()
  }, [index, step, next])

  const cardRef = useRef(null)

  // Карточка с подсветкой уходит в правый нижний угол: прикреплённая к элементу,
  // она закрывала рабочую область (кнопки установки комплектующих на шаге 20).
  const cardStyle = rect
    ? {
        top: 'auto',
        left: 'auto',
        bottom: 16,
        right: 16,
        width: CARD_WIDTH,
        maxHeight: 'calc(100vh - 32px)',
        overflowY: 'auto',
      }
    : undefined

  return (
    <div className="tour-root" role="dialog" aria-modal="true" aria-label={t('tour.ariaLabel')}>
      <div className={`tour-blocker ${rect || step.interactive ? 'tour-blocker--passthrough' : 'tour-blocker--dim'}`} />
      {rect && (
        <div
          className="tour-hole"
          style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
        />
      )}
      <div ref={cardRef} className={`tour-card ${rect ? 'tour-card--anchored' : 'tour-card--center'}`} style={cardStyle}>
        <div className="tour-counter">
          {t('tour.progress', { current: index + 1, total: steps.length })}
        </div>
        <h3>{stepTitle}</h3>
        <p>{stepText}</p>
        {isChoice && (
          <div className="tour-choices">
            {CHOICES.map(c => (
              <button
                key={c.key}
                type="button"
                className={`tour-choice tour-choice--${c.key}`}
                onClick={() => choose(c.key)}
              >
                {t(c.labelKey)}
              </button>
            ))}
          </div>
        )}
        {checkError && <p className="tour-check-error">{checkError}</p>}
        <div className="tour-progress" aria-hidden="true">
          <span style={{ width: `${((index + 1) / steps.length) * 100}%` }} />
        </div>
        <div className="tour-actions">
          <button type="button" className="tour-ghost" onClick={onClose}>{t('tour.skip')}</button>
          {index > 0 && (
            <button type="button" className="tour-ghost" onClick={back}>{t('tour.back')}</button>
          )}
          {!isChoice && !step.on && (
            <button
              type="button"
              className="tour-primary"
              disabled={checking}
              onClick={isLast ? onClose : next}
            >
              {checking
                ? t('tour.checking')
                : step.check
                  ? t('tour.check')
                  : isLast ? t('tour.finish') : t('tour.next')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default TourOverlay
