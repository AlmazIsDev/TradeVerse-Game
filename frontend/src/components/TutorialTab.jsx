import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BookOpen, Check, Lock, RotateCcw, ChevronDown, Sparkles,
  Wallet, TrendingUp, Coins, Cpu, Building, Building2, Boxes, Award, Trophy, LifeBuoy,
  Settings as SettingsIcon,
} from 'lucide-react'
import { fetchPortfolio, fetchMyFarm, fetchCryptoAccount, fetchCompany } from '../services/api'
import { toast } from './Toast'
import '../tutorial.css'

// Прогресс обучения хранится локально: { [topicId]: количество пройденных шагов }.
export const TUTORIAL_STORAGE_KEY = 'tradeverse.tutorial.progress'

// Темы обучения: иконка, цвет акцента и раздел теории (ключ в tutorial.theory.sections).
const TOPICS = [
  { id: 'mining', icon: Cpu, theory: 'mining' },
  { id: 'stocks', icon: TrendingUp, theory: 'market' },
  { id: 'crypto', icon: Coins, theory: 'crypto' },
  { id: 'business', icon: Building, theory: 'business' },
]

// Остальные разделы теории — справочник в конце страницы.
const REFERENCE_SECTIONS = [
  { id: 'account', icon: Wallet },
  { id: 'bank', icon: Building2 },
  { id: 'inventory', icon: Boxes },
  { id: 'achievements', icon: Award },
  { id: 'leaderboard', icon: Trophy },
  { id: 'support', icon: LifeBuoy },
  { id: 'settings', icon: SettingsIcon },
]

// Автоматическая проверка для отдельных шагов: { тема: { индекс шага: имя проверки } }.
// Если проверки нет — шаг подтверждается кнопкой «Готово».
const STEP_CHECKS = {
  mining: { 2: 'miningRunning' },
  stocks: { 1: 'hasStock' },
  crypto: { 2: 'hasCrypto' },
  business: { 1: 'hasCompany' },
}

// Непустой ли список в ответе API (поддерживаем несколько возможных имён поля).
function hasItems(data, keys) {
  for (const key of keys) {
    const list = data?.[key]
    if (Array.isArray(list) && list.length > 0) return true
  }
  return false
}

const CHECK_FNS = {
  async hasStock() {
    return hasItems(await fetchPortfolio(), ['positions', 'items', 'holdings'])
  },
  async hasCrypto() {
    return hasItems(await fetchCryptoAccount(), ['holdings', 'balances', 'positions', 'items'])
  },
  async hasCompany() {
    const data = await fetchCompany()
    return !!(data && (data.company || data.id || data.name))
  },
  async miningRunning() {
    const data = await fetchMyFarm()
    const farm = data?.farm ?? data
    if (farm?.running === true || farm?.isRunning === true) return true
    return farm?.status === 'running' || farm?.status === 'mining'
  },
}

function loadProgress() {
  try {
    const raw = localStorage.getItem(TUTORIAL_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveProgress(progress) {
  try {
    localStorage.setItem(TUTORIAL_STORAGE_KEY, JSON.stringify(progress))
  } catch {
    // localStorage может быть недоступен — прогресс просто не сохранится
  }
}

function useList() {
  const { t } = useTranslation()
  return (key) => {
    const v = t(key, { returnObjects: true })
    return Array.isArray(v) ? v : []
  }
}

// Одна тема: шапка с прогрессом, сворачиваемая теория и шаги миссии.
function TopicSection({ topic, done, onProgress }) {
  const { t } = useTranslation()
  const list = useList()
  const [checking, setChecking] = useState(false)

  const { id, icon: Icon, theory } = topic
  const steps = list(`tutorial.topics.${id}.steps`)
  const total = steps.length
  const doneCount = Math.min(done, total)
  const pct = total ? Math.round((doneCount / total) * 100) : 0
  const completed = total > 0 && doneCount >= total
  const base = `tutorial.theory.sections.${theory}`

  const completeStep = (index) => {
    onProgress(id, Math.max(doneCount, index + 1))
  }

  const runCheck = async (index, checkName) => {
    if (checking) return
    setChecking(true)
    try {
      const ok = await CHECK_FNS[checkName]()
      if (ok) completeStep(index)
      else toast(t('tutorial.notYet'), 'error')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setChecking(false)
    }
  }

  return (
    <section className={`tutorial-topic tutorial-topic--${id} ${completed ? 'is-completed' : ''}`}>
      <header className="tutorial-topic-header">
        <span className="tutorial-topic-icon"><Icon size={20} /></span>
        <div className="tutorial-topic-titles">
          <h3>{t(`tutorial.topics.${id}.name`)}</h3>
          <p>{t(`tutorial.topics.${id}.desc`)}</p>
        </div>
        <span className="tutorial-topic-counter">
          {completed
            ? <><Check size={14} /> {t('tutorial.completed')}</>
            : t('tutorial.stepOf', { n: doneCount, total })}
        </span>
      </header>
      <div className="tutorial-progress" aria-hidden="true">
        <span className="tutorial-progress-bar" style={{ width: `${pct}%` }} />
      </div>

      <details className="tutorial-theory-block">
        <summary>
          <BookOpen size={16} />
          <span>{t('tutorial.theory.tabTheory')}</span>
          <ChevronDown size={16} className="tutorial-chevron" />
        </summary>
        <div className="tutorial-theory-body">
          {list(`${base}.paragraphs`).map((p, i) => <p key={i}>{p}</p>)}
          <h4>{t('tutorial.theory.actionsLabel')}</h4>
          <ul>
            {list(`${base}.actions`).map((a, i) => <li key={i}>{a}</li>)}
          </ul>
          <h4>{t('tutorial.theory.termsLabel')}</h4>
          <dl>
            {list(`${base}.terms`).map((term, i) => (
              <div key={i} className="tutorial-term">
                <dt>{term.name}</dt>
                <dd>{term.desc}</dd>
              </div>
            ))}
          </dl>
        </div>
      </details>

      <ol className="tutorial-steps">
        {steps.map((step, i) => {
          const isDone = i < doneCount
          const isCurrent = i === doneCount && !completed
          const isLocked = i > doneCount
          const checkName = STEP_CHECKS[id]?.[i]
          const state = isDone ? 'done' : isCurrent ? 'current' : 'locked'
          return (
            <li key={i} className={`tutorial-step tutorial-step--${state}`}>
              <span className="tutorial-step-num">
                {isDone ? <Check size={14} /> : isLocked ? <Lock size={13} /> : i + 1}
              </span>
              <div className="tutorial-step-body">
                <div className="tutorial-step-counter">{t('tutorial.stepOf', { n: i + 1, total })}</div>
                <h4 className="tutorial-step-title">{step.title}</h4>
                <p className="tutorial-step-text">
                  <b>{t('tutorial.explainLabel')}:</b> {step.text}
                </p>
                {!isLocked && (
                  <div className="tutorial-task">
                    <span className="tutorial-task-label">{t('tutorial.taskLabel')}</span>
                    <p>{step.task}</p>
                    {isDone ? (
                      <span className="tutorial-task-done"><Check size={14} /> {t('tutorial.doneBadge')}</span>
                    ) : checkName ? (
                      <button
                        type="button"
                        className="submit-btn tutorial-action-btn"
                        disabled={checking}
                        onClick={() => runCheck(i, checkName)}
                      >
                        {checking ? t('bank.processing') : t('tutorial.check')}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="submit-btn tutorial-action-btn"
                        onClick={() => completeStep(i)}
                      >
                        <Check size={14} /> {t('tutorial.markDone')}
                      </button>
                    )}
                  </div>
                )}
                {isLocked && <span className="tutorial-task-locked">{t('tutorial.locked')}</span>}
              </div>
            </li>
          )
        })}
      </ol>

      {completed && (
        <div className="tutorial-complete">
          <Sparkles size={22} />
          <div>
            <h4>{t('tutorial.completedTitle')}</h4>
            <p>{t('tutorial.completedText')}</p>
          </div>
        </div>
      )}
    </section>
  )
}

// Вкладка «Обучение»: прогресс, миссии с теорией по темам и справочник на одной странице.
function TutorialTab() {
  const { t } = useTranslation()
  const list = useList()
  const [progress, setProgress] = useState(loadProgress)

  const updateProgress = (id, value) => {
    setProgress(prev => {
      const next = { ...prev, [id]: value }
      saveProgress(next)
      return next
    })
  }

  const resetAll = () => {
    setProgress({})
    saveProgress({})
  }

  const totals = TOPICS.map(topic => {
    const total = list(`tutorial.topics.${topic.id}.steps`).length
    const done = Math.min(progress[topic.id] || 0, total)
    return { ...topic, total, done }
  })
  const allTotal = totals.reduce((s, x) => s + x.total, 0)
  const allDone = totals.reduce((s, x) => s + x.done, 0)
  const allPct = allTotal ? Math.round((allDone / allTotal) * 100) : 0

  return (
    <div className="tutorial-tab">
      <div className="leaderboard-title-row">
        <BookOpen size={22} className="icon" />
        <h2 className="tab-title">{t('tutorial.open')}</h2>
      </div>
      <p className="tutorial-subtitle">{t('tutorial.subtitle')}</p>

      <div className="tutorial-overview">
        <div className="tutorial-overview-top">
          <span className="tutorial-overview-title">{t('tutorial.theory.tabInteractive')}</span>
          <span className="tutorial-overview-value">{allDone} / {allTotal}</span>
        </div>
        <div className="tutorial-progress tutorial-progress--lg" aria-hidden="true">
          <span className="tutorial-progress-bar" style={{ width: `${allPct}%` }} />
        </div>
        <div className="tutorial-overview-chips">
          {totals.map(topic => {
            const Icon = topic.icon
            return (
              <a key={topic.id} href={`#tutorial-${topic.id}`} className={`tutorial-chip tutorial-chip--${topic.id}`}>
                <Icon size={14} />
                <span>{t(`tutorial.topics.${topic.id}.name`)}</span>
                <b>{topic.done}/{topic.total}</b>
              </a>
            )
          })}
        </div>
      </div>

      <div className="tutorial-topics-list">
        {TOPICS.map(topic => (
          <div key={topic.id} id={`tutorial-${topic.id}`} className="tutorial-anchor">
            <TopicSection
              topic={topic}
              done={progress[topic.id] || 0}
              onProgress={updateProgress}
            />
          </div>
        ))}
      </div>

      <div className="tutorial-reference">
        <h3 className="tutorial-reference-title">{t('tutorial.theory.tabTheory')}</h3>
        <p className="tutorial-hint">{t('tutorial.theory.intro')}</p>
        <div className="tutorial-reference-grid">
          {REFERENCE_SECTIONS.map(({ id, icon: Icon }) => {
            const base = `tutorial.theory.sections.${id}`
            return (
              <details key={id} className="tutorial-theory-block tutorial-reference-card">
                <summary>
                  <span className="tutorial-topic-icon tutorial-topic-icon--sm"><Icon size={16} /></span>
                  <span>{t(`${base}.title`)}</span>
                  <ChevronDown size={16} className="tutorial-chevron" />
                </summary>
                <div className="tutorial-theory-body">
                  {list(`${base}.paragraphs`).map((p, i) => <p key={i}>{p}</p>)}
                  <h4>{t('tutorial.theory.actionsLabel')}</h4>
                  <ul>
                    {list(`${base}.actions`).map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                  <h4>{t('tutorial.theory.termsLabel')}</h4>
                  <dl>
                    {list(`${base}.terms`).map((term, i) => (
                      <div key={i} className="tutorial-term">
                        <dt>{term.name}</dt>
                        <dd>{term.desc}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </details>
            )
          })}
        </div>
      </div>

      <div className="tutorial-footer">
        <button type="button" className="tutorial-ghost-btn" onClick={resetAll}>
          <RotateCcw size={14} /> {t('tutorial.reset')}
        </button>
      </div>
    </div>
  )
}

export default TutorialTab
