import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import ru from './locales/ru.json';
import es from './locales/es.json';
import ja from './locales/ja.json';

// Поддерживаются русский, английский, испанский и японский языки. Выбор языка сохраняется
// в localStorage (см. SettingsPage) и должен переживать перезагрузку страницы.
const SUPPORTED_LANGUAGES = ['ru', 'en', 'es', 'ja'];
// Язык по navigator.languages (порядок предпочтений): первый ru* -> 'ru',
// первый en* -> 'en', первый es* -> 'es', первый ja* -> 'ja'; если ничего не подошло — 'en'. Без navigator — 'ru' (прежний дефолт).
function detectBrowserLanguage() {
  if (typeof navigator === 'undefined') return 'ru';
  const list = (navigator.languages && navigator.languages.length)
    ? navigator.languages
    : [navigator.language || ''];
  for (const l of list) {
    const code = String(l || '').toLowerCase();
    if (code.startsWith('ru')) return 'ru';
    if (code.startsWith('en')) return 'en';
    if (code.startsWith('es')) return 'es';
    if (code.startsWith('ja')) return 'ja';
  }
  return 'en';
}

const storedLanguage = typeof window !== 'undefined' ? window.localStorage.getItem('language') : null;
const initialLanguage = SUPPORTED_LANGUAGES.includes(storedLanguage) ? storedLanguage : detectBrowserLanguage();

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    ru: { translation: ru },
    es: { translation: es },
    ja: { translation: ja },
  },
  lng: initialLanguage,
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export default i18n;
