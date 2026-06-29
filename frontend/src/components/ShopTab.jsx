import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Monitor, Building2, Briefcase, Clock, ArrowLeft, Cpu, Box, Wrench } from 'lucide-react'
import GpuShop from './GpuShop'
import CpuShop from './CpuShop'
import CaseShop from './CaseShop'
import SuppliesShop from './SuppliesShop'
import RealEstateShop from './RealEstateShop'
import BusinessShop from './BusinessShop'

const SHOP_SECTIONS = [
  {
    id: 'gpu',
    labelKey: 'shop.gpu',
    descKey: 'shop.gpuDesc',
    icon: Monitor,
  },
  {
    id: 'realestate',
    labelKey: 'shop.realestate',
    descKey: 'shop.realestateDesc',
    icon: Building2,
  },
  {
    id: 'business',
    labelKey: 'shop.business',
    descKey: 'shop.businessDesc',
    icon: Briefcase,
  },
]

const GPU_SUBSECTIONS = [
  {
    id: 'gpu-cards',
    labelKey: 'shop.gpuCards',
    descKey: 'shop.gpuCardsDesc',
    icon: Monitor,
  },
  {
    id: 'gpu-cpus',
    labelKey: 'shop.gpuCpus',
    descKey: 'shop.gpuCpusDesc',
    icon: Cpu,
  },
  {
    id: 'gpu-cases',
    labelKey: 'shop.gpuCases',
    descKey: 'shop.gpuCasesDesc',
    icon: Box,
  },
  {
    id: 'gpu-supplies',
    labelKey: 'shop.gpuSupplies',
    descKey: 'shop.gpuSuppliesDesc',
    icon: Wrench,
  },
]

function ShopTab() {
  const { t } = useTranslation()
  const [selectedSection, setSelectedSection] = useState(null)
  const [selectedSubsection, setSelectedSubsection] = useState(null)

  if (selectedSection && selectedSection.id === 'gpu' && selectedSubsection && selectedSubsection.id === 'gpu-cards') {
    return <GpuShop onBack={() => setSelectedSubsection(null)} />
  }

  if (selectedSection && selectedSection.id === 'gpu' && selectedSubsection && selectedSubsection.id === 'gpu-cpus') {
    return <CpuShop onBack={() => setSelectedSubsection(null)} />
  }

  if (selectedSection && selectedSection.id === 'gpu' && selectedSubsection && selectedSubsection.id === 'gpu-cases') {
    return <CaseShop onBack={() => setSelectedSubsection(null)} />
  }

  if (selectedSection && selectedSection.id === 'gpu' && selectedSubsection && selectedSubsection.id === 'gpu-supplies') {
    return <SuppliesShop onBack={() => setSelectedSubsection(null)} />
  }

  if (selectedSection && selectedSection.id === 'realestate') {
    return <RealEstateShop onBack={() => setSelectedSection(null)} />
  }

  if (selectedSection && selectedSection.id === 'business') {
    return <BusinessShop onBack={() => setSelectedSection(null)} />
  }

  if (selectedSubsection) {
    return (
      <div className="shop-tab">
        <div className="shop-section-header">
          <button className="shop-back-btn" onClick={() => setSelectedSubsection(null)}>
            <ArrowLeft size={18} />
            <span>{t(selectedSection.labelKey)}</span>
          </button>
          <h2 className="tab-title">{t(selectedSubsection.labelKey)}</h2>
        </div>
        <div className="placeholder-content">
          <span className="placeholder-icon"><Clock size={48} /></span>
          <p>{t('dashboard.comingSoon', { title: t(selectedSubsection.labelKey) })}</p>
        </div>
      </div>
    )
  }

  if (selectedSection) {
    const subsections = selectedSection.id === 'gpu' ? GPU_SUBSECTIONS : null

    if (subsections) {
      return (
        <div className="shop-tab">
          <div className="shop-section-header">
            <button className="shop-back-btn" onClick={() => setSelectedSection(null)}>
              <ArrowLeft size={18} />
              <span>{t('nav.shop')}</span>
            </button>
            <h2 className="tab-title">{t(selectedSection.labelKey)}</h2>
          </div>
          <div className="shop-sections">
            {subsections.map(subsection => {
              const Icon = subsection.icon
              return (
                <button
                  key={subsection.id}
                  className="shop-section-button"
                  onClick={() => setSelectedSubsection(subsection)}
                >
                  <span className="shop-section-icon"><Icon size={32} /></span>
                  <span className="shop-section-label">{t(subsection.labelKey)}</span>
                  <span className="shop-section-desc">{t(subsection.descKey)}</span>
                </button>
              )
            })}
          </div>
        </div>
      )
    }

    return (
      <div className="shop-tab">
        <div className="shop-section-header">
          <button className="shop-back-btn" onClick={() => setSelectedSection(null)}>
            <ArrowLeft size={18} />
            <span>{t('nav.shop')}</span>
          </button>
          <h2 className="tab-title">{t(selectedSection.labelKey)}</h2>
        </div>
        <div className="placeholder-content">
          <span className="placeholder-icon"><Clock size={48} /></span>
          <p>{t('dashboard.comingSoon', { title: t(selectedSection.labelKey) })}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="shop-tab">
      <h2 className="tab-title">{t('nav.shop')}</h2>
      <div className="shop-sections">
        {SHOP_SECTIONS.map(section => {
          const Icon = section.icon
          return (
            <button
              key={section.id}
              className="shop-section-button"
              onClick={() => setSelectedSection(section)}
            >
              <span className="shop-section-icon"><Icon size={32} /></span>
              <span className="shop-section-label">{t(section.labelKey)}</span>
              <span className="shop-section-desc">{t(section.descKey)}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default ShopTab
