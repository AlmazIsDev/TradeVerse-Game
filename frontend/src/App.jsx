import { useState } from 'react'
import './App.css'

function App() {
  const [tab, setTab] = useState('login')
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    confirmPassword: ''
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
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
      : { username: formData.username, password: formData.password }

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      const data = await response.json()

      if (!response.ok) {
        setError(data.detail || 'Ошибка при авторизации')
        return
      }

      setSuccess(true)
    } catch {
      setError('Не удалось подключиться к серверу')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="auth-container">
        <div className="auth-left">
          <div className="brand-logo">T</div>
          <h2>TradeVerse</h2>
          <p className="brand-tagline">Экономическая игра нового поколения</p>
        </div>
        <div className="auth-right">
          <div className="auth-card success-card">
            <div className="success-icon">✓</div>
            <h1>{tab === 'login' ? 'Добро пожаловать!' : 'Регистрация успешна!'}</h1>
            <p>{tab === 'login' ? 'Вы успешно вошли в систему.' : `Аккаунт ${formData.username} создан.`}</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-container">
      <div className="auth-left">
        <div className="brand-logo">T</div>
        <h2>TradeVerse</h2>
        <p className="brand-tagline">Экономическая игра нового поколения</p>

        <div className="features">
          <div className="feature">
            <div className="feature-icon">📈</div>
            <div>
              <h3>Торгуй акциями</h3>
              <p>Создавай и продавай виртуальные акции, конкурируй с другими игроками на бирже.</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🪙</div>
            <div>
              <h3>Создавай криптовалюту</h3>
              <p>Запусти свою крипромонету и стань первым майнером в мире TradeVerse.</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🏢</div>
            <div>
              <h3>Открой бизнес</h3>
              <p>Построй свою бизнес-империю — от маленького стартапа до корпорации.</p>
            </div>
          </div>
          <div className="feature">
            <div className="feature-icon">🤝</div>
            <div>
              <h3>Торгуйся с игроками</h3>
              <p>Заключай сделки, договаривайся о ценах и обменивайся активами.</p>
            </div>
          </div>
        </div>

        <p className="brand-footer">Уже более 0 игроков строят свою экономику.</p>
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

export default App
