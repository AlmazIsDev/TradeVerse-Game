import { useState } from 'react'

function AuthPage({ onLogin }) {
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
      setError('Пожалуйста, заполните все поля')
      return
    }

    if (tab === 'register') {
      if (!formData.confirmPassword) {
        setError('Пожалуйста, подтвердите пароль')
        return
      }
      if (formData.password !== formData.confirmPassword) {
        setError('Пароли не совпадают')
        return
      }
    }

    if (formData.password.length < 6) {
      setError('Пароль должен содержать минимум 6 символов')
      return
    }

    setLoading(true)

    const endpoint = tab === 'login' ? '/api/login' : '/api/register'
    const body = tab === 'login'
      ? { username: formData.username, password: formData.password }
      : { username: formData.username, password: formData.password, confirm_password: formData.confirmPassword }

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      const data = await response.json()

      if (!response.ok) {
        // FastAPI может вернуть detail как строку или массив объектов
        if (Array.isArray(data.detail)) {
          setError(data.detail.map(err => err.msg).join(', '))
        } else {
          setError(data.detail || 'Ошибка при авторизации')
        }
        return
      }

      onLogin(data.username || formData.username)
    } catch {
      // Моковый режим: если сервер недоступен, всё равно пускаем
      onLogin(formData.username)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-left">
        <div className="brand-logo">T</div>
        <h2>TradeVerse</h2>
        <p className="brand-tagline">Экономическая война в браузере</p>

        <div className="features">
          <div className="feature">
            <div className="feature-icon">📈</div>
            <div>
              <h3>Акции реальных компаний</h3>
              <p>Торгуй акциями компаний внутри игры, скупай доли конкурентов и обрушивай их капитализацию.</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🪙</div>
            <div>
              <h3>Своя криптовалюта</h3>
              <p>Создай монету, задай дефляционную модель, привяжи к показателям компании — и наблюдай, как другие охотятся за твоим токеном.</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">⚔️</div>
            <div>
              <h3>Война инструментами</h3>
              <p>Каждый ход влияет на общий рынок. Это не просто экономика — это война всеми доступными способами.</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🏛️</div>
            <div>
              <h3>Финансовая империя</h3>
              <p>Возводи свою империю, скупай акции соперников и стань главным магнатом TradeVerse.</p>
            </div>
          </div>
        </div>

        <p className="brand-footer">Два класса активов. Одна цель. Ты решаешь, кому принадлежит рынок.</p>
      </div>

      <div className="auth-right">
        <div className="auth-card">
          <div className="tab-switcher">
            <button
              className={`tab-btn ${tab === 'login' ? 'active' : ''}`}
              onClick={() => { setTab('login'); setError(''); }}
            >
              Вход
            </button>
            <button
              className={`tab-btn ${tab === 'register' ? 'active' : ''}`}
              onClick={() => { setTab('register'); setError(''); }}
            >
              Регистрация
            </button>
          </div>

          <div className="auth-header">
            <h1>{tab === 'login' ? 'Войти в аккаунт' : 'Создать аккаунт'}</h1>
            <p>{tab === 'login' ? 'Введите данные для входа' : 'Заполните форму для регистрации'}</p>
          </div>

          {error && <div className="error-message">{error}</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label htmlFor="username">Имя пользователя</label>
              <input
                type="text"
                id="username"
                name="username"
                placeholder="Введите имя"
                value={formData.username}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">Пароль</label>
              <input
                type="password"
                id="password"
                name="password"
                placeholder="Минимум 6 символов"
                value={formData.password}
                onChange={handleChange}
              />
            </div>

            {tab === 'register' && (
              <div className="form-group">
                <label htmlFor="confirmPassword">Подтвердите пароль</label>
                <input
                  type="password"
                  id="confirmPassword"
                  name="confirmPassword"
                  placeholder="Повторите пароль"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                />
              </div>
            )}

            <button type="submit" className="submit-btn" disabled={loading}>
              {loading
                ? 'Загрузка...'
                : tab === 'login'
                  ? 'Войти'
                  : 'Зарегистрироваться'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

export default AuthPage
