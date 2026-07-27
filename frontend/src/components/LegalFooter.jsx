import { useTranslation } from 'react-i18next'

const REPO_URL = 'https://github.com/AlmazIsDev/TradeVerse'

// lucide-react больше не поставляет бренд-иконки — путь взят из GitHub Octicons.
function GithubMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-2.91-.88-2.91-2.9 0-.9.32-1.64.85-2.22-.08-.21-.37-1.05.08-2.18 0 0 .69-.22 2.26.85a5.6 5.6 0 0 1 3.04 0c1.57-1.07 2.26-.85 2.26-.85.45 1.13.16 1.97.08 2.18.53.58.85 1.32.85 2.22 0 2.03-1.14 2.7-2.92 2.9.3.26.56.76.56 1.54 0 1.11-.01 2.02-.01 2.3 0 .21.15.46.55.38A7.995 7.995 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

function LegalFooter() {
  const { t } = useTranslation()

  return (
    <footer className="legal-footer">
      <a
        className="legal-footer-icon"
        href={REPO_URL}
        target="_blank"
        rel="noreferrer"
        aria-label="GitHub"
      >
        <GithubMark />
      </a>
      <div className="legal-footer-links">
        <a href={`${REPO_URL}/blob/main/docs/TERMS.md`} target="_blank" rel="noreferrer">
          {t('legal.terms')}
        </a>
        <span>{t('legal.copyright')}</span>
        <a href={`${REPO_URL}/blob/main/docs/PRIVACY.md`} target="_blank" rel="noreferrer">
          {t('legal.privacy')}
        </a>
      </div>
    </footer>
  )
}

export default LegalFooter
