import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import ru from './locales/ru.json';

// Поддерживаются только русский и английский языки. Выбор языка сохраняется
// в localStorage (см. SettingsPage) и должен переживать перезагрузку страницы.
const SUPPORTED_LANGUAGES = ['ru', 'en'];
const storedLanguage = typeof window !== 'undefined' ? window.localStorage.getItem('language') : null;
const initialLanguage = SUPPORTED_LANGUAGES.includes(storedLanguage) ? storedLanguage : 'ru';

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    ru: { translation: ru },
  },
  lng: initialLanguage,
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export default i18n;
