import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { request } from '../services/api'

function AuthPage({ onLogin }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState('login')
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    confirmPassword: ''
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (!formData.username || !formData.password) {
      setError(t('auth.fillAllFields'))
      return
    }

    if (tab === 'register') {
      if (!formData.confirmPassword) {
        setError(t('auth.confirmYourPassword'))
        return
      }
      if (formData.password !== formData.confirmPassword) {
        setError(t('auth.passwordsMismatch'))
        return
      }
    }

    if (formData.password.length < 6) {
      setError(t('auth.passwordTooShort'))
      return
    }

    setLoading(true)

    const endpoint = tab === 'login' ? '/api/login' : '/api/register'
    const body = tab === 'login'
      ? { username: formData.username, password: formData.password }
      : { username: formData.username, password: formData.password, confirm_password: formData.confirmPassword }

    try {
      const data = await request(endpoint, {
        method: 'POST',
        body: JSON.stringify(body),
      })

      // Передаём полный объект пользователя (id, username, role, card_number, card_visible, token, refresh_token)
      onLogin({
        id: data.id,
        username: data.username || formData.username,
        role: data.role || 'user',
        card_number: data.card_number || null,
        card_visible: data.card_visible !== undefined ? data.card_visible : true,
        token: data.token || null,
        refresh_token: data.refresh_token || null,
      })
    } catch (err) {
      // Показываем ошибку сервера пользователю
      setError(err.message || t('auth.loginError'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-left">
        <div className="brand-logo"><img src="/favicon.svg" alt="TradeVerse" className="logo-glyph" /></div>
        <h2>TradeVerse</h2>
        <p className="brand-tagline">{t('auth.tagline')}</p>

        <div className="features">
          <div className="feature">
            <div className="feature-icon">📈</div>
            <div>
              <h3>{t('auth.featureStocksTitle')}</h3>
              <p>{t('auth.featureStocksDesc')}</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🪙</div>
            <div>
              <h3>{t('auth.featureCryptoTitle')}</h3>
              <p>{t('auth.featureCryptoDesc')}</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">⚔️</div>
            <div>
              <h3>{t('auth.featureWarTitle')}</h3>
              <p>{t('auth.featureWarDesc')}</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🏛️</div>
            <div>
              <h3>{t('auth.featureEmpireTitle')}</h3>
              <p>{t('auth.featureEmpireDesc')}</p>
            </div>
          </div>
        </div>

        <p className="brand-footer">{t('auth.footerText')}</p>
      </div>

      <div className="auth-right">
        <div className="auth-card">
          <div className="tab-switcher">
            <button
              className={`tab-btn ${tab === 'login' ? 'active' : ''}`}
              onClick={() => { setTab('login'); setError(''); }}
            >
              {t('auth.login')}
            </button>
            <button
              className={`tab-btn ${tab === 'register' ? 'active' : ''}`}
              onClick={() => { setTab('register'); setError(''); }}
            >
              {t('auth.register')}
            </button>
          </div>

          <div className="auth-header">
            <h1>{tab === 'login' ? t('auth.loginTitle') : t('auth.registerTitle')}</h1>
            <p>{tab === 'login' ? t('auth.loginSubtitle') : t('auth.registerSubtitle')}</p>
          </div>

          {error && <div className="error-message">{error}</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label htmlFor="username">{t('auth.username')}</label>
              <input
                type="text"
                id="username"
                name="username"
                placeholder={t('auth.enterUsername')}
                value={formData.username}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">{t('auth.password')}</label>
              <input
                type="password"
                id="password"
                name="password"
                placeholder={t('auth.enterPassword')}
                value={formData.password}
                onChange={handleChange}
              />
            </div>

            {tab === 'register' && (
              <div className="form-group">
                <label htmlFor="confirmPassword">{t('auth.confirmPassword')}</label>
                <input
                  type="password"
                  id="confirmPassword"
                  name="confirmPassword"
                  placeholder={t('auth.repeatPassword')}
                  value={formData.confirmPassword}
                  onChange={handleChange}
                />
              </div>
            )}

            <button type="submit" className="submit-btn" disabled={loading}>
              {loading
                ? t('common.loading')
                : tab === 'login'
                  ? t('auth.loginButton')
                  : t('auth.registerButton')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

export default AuthPage
