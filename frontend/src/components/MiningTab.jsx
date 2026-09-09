import { useTranslation } from 'react-i18next'

export default function MiningTab() {
  const { t } = useTranslation()
  return (
    <div className="tab-empty">
      <p>{t('mining.empty', 'Раздел майнинга временно пуст')}</p>
    </div>
  )
}
