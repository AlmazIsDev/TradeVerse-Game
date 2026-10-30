import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import './economy.css'
import './settings.css'
import './farm.css'
import App from './App.jsx'
import { watchSystemTheme } from './utils/theme'

// Подписка на смену системной темы (активна только без ручного выбора).
watchSystemTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
