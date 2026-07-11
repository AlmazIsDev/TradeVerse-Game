import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  TrendingUp,
  Bitcoin,
  Building2,
  Briefcase,
  Cpu,
  Trophy,
  Swords,
  Landmark,
} from 'lucide-react'
import LanguageSwitcher from './LanguageSwitcher'

const FEATURE_ICONS = {
  stocks: TrendingUp,
  crypto: Bitcoin,
  realestate: Building2,
  companies: Briefcase,
  mining: Cpu,
  leaderboard: Trophy,
  cityroof: Swords,
  bank: Landmark,
}

function Landing() {
  const { t } = useTranslation()

  // Порядок карточек фич — ключи совпадают с секцией landing.features.* в locales
  const featureKeys = [
    'stocks',
    'crypto',
    'realestate',
    'companies',
    'mining',
    'leaderboard',
    'cityroof',
    'bank',
  ]

  const steps = ['step1', 'step2', 'step3']
  const stats = ['markets', 'assets', 'players', 'currency']

  return (
    <div className="landing">
      {/* ── Top nav ─────────────────────────────────────────── */}
      <header className="lp-nav">
        <div className="lp-nav-inner">
          <Link to="/" className="lp-brand" aria-label="TradeVerse">
            <span className="lp-brand-logo">T</span>
            <span className="lp-brand-name">TradeVerse</span>
          </Link>
          <div className="lp-nav-actions">
            <LanguageSwitcher />
            <Link to="/login" className="lp-btn lp-btn-ghost">
              {t('landing.nav.login')}
            </Link>
            <Link to="/login" className="lp-btn lp-btn-primary">
              {t('landing.nav.play')}
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero ────────────────────────────────────────────── */}
      <section className="lp-hero">
        <div className="lp-hero-glow" aria-hidden="true" />
        <div className="lp-hero-inner">
          <span className="lp-eyebrow">{t('landing.hero.eyebrow')}</span>
          <h1 className="lp-hero-title">{t('landing.hero.title')}</h1>
          <p className="lp-hero-subtitle">{t('landing.hero.subtitle')}</p>
          <div className="lp-hero-cta">
            <Link to="/login" className="lp-btn lp-btn-primary lp-btn-lg">
              {t('landing.hero.ctaPrimary')}
            </Link>
            <Link to="/login" className="lp-btn lp-btn-ghost lp-btn-lg">
              {t('landing.hero.ctaSecondary')}
            </Link>
          </div>

          <div className="lp-stats">
            {stats.map((key) => (
              <div key={key} className="lp-stat">
                <div className="lp-stat-value">{t(`landing.stats.${key}.value`)}</div>
                <div className="lp-stat-label">{t(`landing.stats.${key}.label`)}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ────────────────────────────────────────── */}
      <section className="lp-section" id="features">
        <div className="lp-section-head">
          <span className="lp-eyebrow">{t('landing.features.eyebrow')}</span>
          <h2 className="lp-section-title">{t('landing.features.title')}</h2>
          <p className="lp-section-sub">{t('landing.features.subtitle')}</p>
        </div>

        <div className="lp-features-grid">
          {featureKeys.map((key) => {
            const Icon = FEATURE_ICONS[key]
            return (
              <article key={key} className="lp-feature-card">
                <div className="lp-feature-icon">{Icon && <Icon size={22} />}</div>
                <h3 className="lp-feature-title">{t(`landing.features.${key}.title`)}</h3>
                <p className="lp-feature-desc">{t(`landing.features.${key}.desc`)}</p>
              </article>
            )
          })}
        </div>
      </section>

      {/* ── How it works ────────────────────────────────────── */}
      <section className="lp-section lp-how" id="how">
        <div className="lp-section-head">
          <span className="lp-eyebrow">{t('landing.how.eyebrow')}</span>
          <h2 className="lp-section-title">{t('landing.how.title')}</h2>
          <p className="lp-section-sub">{t('landing.how.subtitle')}</p>
        </div>

        <div className="lp-steps">
          {steps.map((key, idx) => (
            <div key={key} className="lp-step">
              <div className="lp-step-num">{idx + 1}</div>
              <h3 className="lp-step-title">{t(`landing.how.${key}.title`)}</h3>
              <p className="lp-step-desc">{t(`landing.how.${key}.desc`)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────── */}
      <section className="lp-cta-band">
        <div className="lp-cta-inner">
          <h2 className="lp-cta-title">{t('landing.finalCta.title')}</h2>
          <p className="lp-cta-sub">{t('landing.finalCta.subtitle')}</p>
          <Link to="/login" className="lp-btn lp-btn-primary lp-btn-lg">
            {t('landing.finalCta.button')}
          </Link>
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────── */}
      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <div className="lp-footer-brand">
            <span className="lp-brand-logo">T</span>
            <div>
              <div className="lp-brand-name">TradeVerse</div>
              <p className="lp-footer-tagline">{t('landing.footer.tagline')}</p>
            </div>
          </div>
          <nav className="lp-footer-links" aria-label="footer">
            <a href="#features">{t('landing.footer.linkFeatures')}</a>
            <a href="#how">{t('landing.footer.linkHow')}</a>
            <Link to="/login">{t('landing.footer.linkLogin')}</Link>
          </nav>
        </div>
        <div className="lp-footer-bottom">
          <p>{t('landing.footer.copyright')}</p>
          <p className="lp-footer-disclaimer">{t('landing.footer.disclaimer')}</p>
        </div>
      </footer>
    </div>
  )
}

export default Landing
