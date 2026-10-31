import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { updateProfile, changePassword, uploadAvatar, deleteAvatar, uploadBanner, deleteBanner, toggleLeaderboardVisibility, updateBio, fetchMyStats, updateCountry, redeemPromo } from '../services/api'
import { getTheme, applyTheme } from '../utils/theme'
import ConfirmDialog from './ConfirmDialog'
import { COUNTRIES, flagUrl } from '../utils/countries'
import StatusBadge from './StatusBadge'
import { toast } from './Toast'
import {
  Settings as SettingsIcon, User, Lock, Globe,
  Save, Trash2, Check, Upload, Moon, Award, BarChart3, Ticket, MapPin, ChevronDown,
} from 'lucide-react'

// Итоговый размер аватара — сжимается на клиенте через canvas (cover-crop до
// квадрата), поэтому на сервер уходит небольшая data URL-строка без нужды в
// отдельной инфраструктуре файлового хранилища (см. backend/user_profile.py).
const AVATAR_SIZE = 256
const AVATAR_QUALITY = 0.85
// Баннер («шапка») — широкий формат 4:1, сжимается на клиенте в JPEG.
const BANNER_WIDTH = 1200
const BANNER_HEIGHT = 300
const BANNER_QUALITY = 0.8

const LANGUAGES = [
  { code: 'ru', label: 'Русский', flag: '🇷🇺' },
  { code: 'en', label: 'English', flag: '🇬🇧' },
  { code: 'es', label: 'Español', flag: '🇪🇸' },
  { code: 'ja', label: '日本語', flag: '🇯🇵' },
]

/** Сжимает выбранное изображение до квадрата AVATAR_SIZE×AVATAR_SIZE (cover-crop). */
function readAndResizeImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('read-failed'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('decode-failed'))
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = AVATAR_SIZE
        canvas.height = AVATAR_SIZE
        const ctx = canvas.getContext('2d')
        const scale = Math.max(AVATAR_SIZE / img.width, AVATAR_SIZE / img.height)
        const w = img.width * scale
        const h = img.height * scale
        ctx.drawImage(img, (AVATAR_SIZE - w) / 2, (AVATAR_SIZE - h) / 2, w, h)
        resolve(canvas.toDataURL('image/jpeg', AVATAR_QUALITY))
      }
      img.src = reader.result
    }
    reader.readAsDataURL(file)
  })
}

/** Сжимает изображение до BANNER_WIDTH×BANNER_HEIGHT (cover-crop по центру). */
function readAndResizeBanner(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('read-failed'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('decode-failed'))
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = BANNER_WIDTH
        canvas.height = BANNER_HEIGHT
        const ctx = canvas.getContext('2d')
        const scale = Math.max(BANNER_WIDTH / img.width, BANNER_HEIGHT / img.height)
        const w = img.width * scale
        const h = img.height * scale
        ctx.drawImage(img, (BANNER_WIDTH - w) / 2, (BANNER_HEIGHT - h) / 2, w, h)
        resolve(canvas.toDataURL('image/jpeg', BANNER_QUALITY))
      }
      img.src = reader.result
    }
    reader.readAsDataURL(file)
  })
}

function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return isNaN(d.getTime()) ? null : d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })
}

function SettingsPage({ user, onUserUpdate }) {
  const { t, i18n } = useTranslation()
  // ── Профиль (никнейм) ──────────────────────────────────────────────────────
  const [username, setUsername] = useState(user?.username || '')
  const [savingProfile, setSavingProfile] = useState(false)
  const usernameChanged = username.trim() && username.trim() !== user?.username

  const saveProfile = async () => {
    const trimmed = username.trim()
    if (!trimmed) return
    setSavingProfile(true)
    try {
      const res = await updateProfile({ username: trimmed })
      onUserUpdate?.({ username: res.username })
      toast(t('settings.profileSaved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingProfile(false)
    }
  }

  // ── Описание («о себе») ──────────────────────────────────────────────────────
  const [bio, setBio] = useState(user?.bio || '')
  const [savingBio, setSavingBio] = useState(false)
  const bioChanged = (bio || '').trim() !== (user?.bio || '')

  const saveBio = async () => {
    setSavingBio(true)
    try {
      const res = await updateBio(bio.trim())
      onUserUpdate?.({ bio: res.bio })
      toast(t('settings.bioSaved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingBio(false)
    }
  }

  // ── Статистика + ачивки (профиль) ────────────────────────────────────────────
  const [profile, setProfile] = useState(null)
  useEffect(() => {
    let alive = true
    fetchMyStats().then(res => { if (alive) setProfile(res) }).catch(() => {})
    return () => { alive = false }
  }, [])

  // ── Видимость в таблице лидеров ──────────────────────────────────────────────
  const [hideFromLeaderboard, setHideFromLeaderboard] = useState(!!user?.hideFromLeaderboard)
  const [savingLbVisibility, setSavingLbVisibility] = useState(false)

  const toggleLbVisibility = async () => {
    setSavingLbVisibility(true)
    try {
      const res = await toggleLeaderboardVisibility()
      setHideFromLeaderboard(res.hideFromLeaderboard)
      onUserUpdate?.({ hideFromLeaderboard: res.hideFromLeaderboard })
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingLbVisibility(false)
    }
  }

  // ── Страна (флаг слева от ника) ─────────────────────────────────────────────
  const [country, setCountry] = useState(user?.country || '')
  const [savingCountry, setSavingCountry] = useState(false)
  const countryChanged = (country || '') !== (user?.country || '')
  const [countryOpen, setCountryOpen] = useState(false)
  const selectedCountry = COUNTRIES.find(c => c.code === country) || null

  const saveCountry = async () => {
    setSavingCountry(true)
    try {
      const res = await updateCountry(country || null)
      onUserUpdate?.({ country: res.country })
      toast(t('settings.countrySaved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingCountry(false)
    }
  }

  // ── Промокод ───────────────────────────────────────────────────────────────
  const [promoCode, setPromoCode] = useState('')
  const [redeemingPromo, setRedeemingPromo] = useState(false)

  const applyPromo = async () => {
    const code = promoCode.trim()
    if (!code) return
    setRedeemingPromo(true)
    try {
      const res = await redeemPromo(code)
      setPromoCode('')
      const parts = []
      if (res.amount) parts.push(`$${Number(res.amount).toLocaleString('ru-RU')}`)
      if (res.business) parts.push(res.business)
      if (res.badge === 'beta_tester') parts.push('значок «Бета-тестер»')
      onUserUpdate?.({
        balance: res.balance,
        ...(res.badge ? { badges: [...new Set([...(user?.badges || []), res.badge])] } : {}),
      })
      toast(parts.length ? `Промокод применён: ${parts.join(', ')}` : 'Промокод применён')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setRedeemingPromo(false)
    }
  }

  // ── Пароль ─────────────────────────────────────────────────────────────────
  const [pwd, setPwd] = useState({ current: '', next: '', confirm: '' })
  const [savingPwd, setSavingPwd] = useState(false)

  const savePassword = async () => {
    if (!pwd.current || !pwd.next || !pwd.confirm) { toast(t('auth.fillAllFields'), 'error'); return }
    if (pwd.next.length < 6) { toast(t('auth.passwordTooShort'), 'error'); return }
    if (pwd.next !== pwd.confirm) { toast(t('auth.passwordsMismatch'), 'error'); return }
    setSavingPwd(true)
    try {
      await changePassword({
        current_password: pwd.current, new_password: pwd.next, confirm_password: pwd.confirm,
      })
      setPwd({ current: '', next: '', confirm: '' })
      toast(t('settings.passwordSaved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingPwd(false)
    }
  }

  // ── Аватар ─────────────────────────────────────────────────────────────────
  const fileInputRef = useRef(null)
  const [stagedAvatar, setStagedAvatar] = useState(null)   // предпросмотр до сохранения
  const [savingAvatar, setSavingAvatar] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const onPickFile = () => fileInputRef.current?.click()

  const onFileChange = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) { toast(t('settings.avatarInvalidType'), 'error'); return }
    try {
      const dataUrl = await readAndResizeImage(file)
      setStagedAvatar(dataUrl)
    } catch {
      toast(t('settings.avatarInvalidType'), 'error')
    }
  }

  const saveAvatar = async () => {
    if (!stagedAvatar) return
    setSavingAvatar(true)
    try {
      const res = await uploadAvatar(stagedAvatar)
      onUserUpdate?.({ avatar: res.avatar })
      setStagedAvatar(null)
      toast(t('settings.avatarSaved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingAvatar(false)
    }
  }

  const removeAvatar = async () => {
    setSavingAvatar(true)
    try {
      await deleteAvatar()
      onUserUpdate?.({ avatar: null })
      toast(t('settings.avatarRemoved'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingAvatar(false)
      setConfirmRemove(false)
    }
  }

  // ── Баннер («шапка» профиля) ───────────────────────────────────────────────
  const bannerInputRef = useRef(null)
  const [stagedBanner, setStagedBanner] = useState(null)
  const [savingBanner, setSavingBanner] = useState(false)

  const onBannerFileChange = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) { toast(t('settings.avatarInvalidType'), 'error'); return }
    try {
      setStagedBanner(await readAndResizeBanner(file))
    } catch {
      toast(t('settings.avatarInvalidType'), 'error')
    }
  }

  const saveBanner = async () => {
    if (!stagedBanner) return
    setSavingBanner(true)
    try {
      const res = await uploadBanner(stagedBanner)
      onUserUpdate?.({ banner: res.banner })
      setStagedBanner(null)
      toast(t('settings.bannerSaved', 'Баннер сохранён'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingBanner(false)
    }
  }

  const removeBanner = async () => {
    setSavingBanner(true)
    try {
      await deleteBanner()
      onUserUpdate?.({ banner: null })
      toast(t('settings.bannerRemoved', 'Баннер удалён'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSavingBanner(false)
    }
  }

  // ── Локализация ────────────────────────────────────────────────────────────
  const changeLanguage = (code) => {
    if (code === i18n.language) return
    i18n.changeLanguage(code)
    localStorage.setItem('language', code)
  }

  // ── Оформление (тёмная тема) ─────────────────────────────────────────────────
  // Тема управляется атрибутом <html data-theme> через theme.js, чтобы весь слой
  // токенов дизайн-системы переключался разом. Хранится локально.
  const [theme, setTheme] = useState(getTheme())
  const toggleDark = () => setTheme(applyTheme(theme === 'dark' ? 'light' : 'dark'))

  const currentAvatar = stagedAvatar || user?.avatar || null
  const initials = (user?.username || '?').slice(0, 2).toUpperCase()
  const since = formatDate(user?.created_at)

  return (
    <div className="settings-page">
      <div className="settings-title-row">
        <SettingsIcon size={22} className="icon" />
        <h2 className="tab-title">{t('nav.settings')}</h2>
      </div>

      <div className="settings-grid">
        {/* Профиль (аватар + никнейм + видимость в лидерборде) */}
        <div className="settings-card settings-avatar-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><User size={18} /></span>
            <h3>{t('settings.profileTitle')}</h3>
          </div>

          <div className="settings-avatar-body">
            <div className="settings-avatar-preview">
              {currentAvatar ? (
                <img src={currentAvatar} alt={user?.username} />
              ) : (
                <span>{initials}</span>
              )}
            </div>
            <div className="settings-avatar-actions">
              <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={onFileChange} />
              <button className="asset-act upgrade" onClick={onPickFile}>
                <Upload size={14} /> {t('settings.chooseImage')}
              </button>
              {stagedAvatar && (
                <button className="submit-btn settings-save-btn" disabled={savingAvatar} onClick={saveAvatar}>
                  <Save size={14} /> {savingAvatar ? t('bank.processing') : t('settings.saveAvatar')}
                </button>
              )}
              {user?.avatar && !stagedAvatar && (
                <button className="asset-act sell" disabled={savingAvatar} onClick={() => setConfirmRemove(true)}>
                  <Trash2 size={14} /> {t('settings.removeAvatar')}
                </button>
              )}
            </div>
          </div>
          <p className="settings-hint">{t('settings.avatarHint')}</p>

          <div className="settings-banner-block">
            <div className="settings-banner-preview">
              {(stagedBanner || user?.banner) ? (
                <img src={stagedBanner || user?.banner} alt="" />
              ) : (
                <span>{t('settings.bannerEmpty', 'Баннер не задан')}</span>
              )}
            </div>
            <div className="settings-avatar-actions">
              <input ref={bannerInputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={onBannerFileChange} />
              <button className="asset-act upgrade" onClick={() => bannerInputRef.current?.click()}>
                <Upload size={14} /> {t('settings.chooseBanner', 'Выбрать баннер')}
              </button>
              {stagedBanner && (
                <button className="submit-btn settings-save-btn" disabled={savingBanner} onClick={saveBanner}>
                  <Save size={14} /> {savingBanner ? t('bank.processing') : t('settings.saveBanner', 'Сохранить баннер')}
                </button>
              )}
              {user?.banner && !stagedBanner && (
                <button className="asset-act sell" disabled={savingBanner} onClick={removeBanner}>
                  <Trash2 size={14} /> {t('settings.removeBanner', 'Удалить баннер')}
                </button>
              )}
            </div>
          </div>
          <p className="settings-hint">{t('settings.bannerHint', 'Широкое изображение, будет обрезано до пропорций 4:1')}</p>

          <div className="settings-current-info">
            <span>{t('profile.name')}: <b>{user?.username}</b> <StatusBadge user={user} size={13} /></span>
            {since && <span>{t('profile.since')}: {since}</span>}
          </div>

          <div className="form-group">
            <label>{t('settings.newNickname')}</label>
            <input
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder={t('auth.enterUsername')}
              maxLength={32}
            />
          </div>
          <button
            className="submit-btn settings-save-btn"
            disabled={savingProfile || !usernameChanged}
            onClick={saveProfile}
          >
            <Save size={15} /> {savingProfile ? t('bank.processing') : t('settings.saveProfile')}
          </button>

          <div className="form-group">
            <label>{t('settings.bio')}</label>
            <div className="settings-bio-field">
              <textarea
                className="settings-bio-input"
                value={bio}
                onChange={e => setBio(e.target.value)}
                placeholder={t('settings.bioPlaceholder')}
                maxLength={280}
                rows={3}
              />
              <span className="settings-bio-count">{(bio || '').length}/280</span>
            </div>
          </div>
          <button
            className="submit-btn settings-save-btn"
            disabled={savingBio || !bioChanged}
            onClick={saveBio}
          >
            <Save size={15} /> {savingBio ? t('bank.processing') : t('settings.saveBio')}
          </button>

          <div className="settings-toggle-block">
            <label className={`settings-toggle-row ${user?.leaderboardLock ? 'disabled' : ''}`}>
              <span className="settings-toggle-text">{t('settings.hideFromLeaderboard')}</span>
              <span className="settings-switch">
                <input
                  type="checkbox"
                  checked={hideFromLeaderboard}
                  disabled={savingLbVisibility || !!user?.leaderboardLock}
                  onChange={toggleLbVisibility}
                />
                <span className="settings-switch-track"><span className="settings-switch-thumb" /></span>
              </span>
            </label>
            <p className="settings-hint">
              {user?.leaderboardLock ? t('settings.leaderboardLocked') : t('settings.hideFromLeaderboardHint')}
            </p>
          </div>
        </div>

        {/* Страна (флаг слева от ника) */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><MapPin size={18} /></span>
            <h3>{t('settings.countryTitle')}</h3>
          </div>
          <div className="settings-country-select">
            <button
              type="button"
              className="settings-country-trigger"
              onClick={() => setCountryOpen(o => !o)}
            >
              {selectedCountry
                ? <img className="settings-country-flag" src={flagUrl(selectedCountry.code)} alt={selectedCountry.code} />
                : <span className="settings-lang-flag">🏳️</span>}
              <span className="settings-lang-label">
              {selectedCountry ? `${selectedCountry.code} · ${selectedCountry.name}` : t('settings.countryNone')}
            </span>
              <ChevronDown size={16} className={`settings-country-chevron ${countryOpen ? 'open' : ''}`} />
            </button>
            {countryOpen && (
              <div className="settings-country-panel">
                {COUNTRIES.map(c => (
                  <button
                    type="button"
                    key={c.code}
                    className={`settings-country-option ${country === c.code ? 'active' : ''}`}
                    onClick={() => { setCountry(c.code); setCountryOpen(false) }}
                  >
                    <img className="settings-country-flag" src={flagUrl(c.code)} alt={c.code} />
                    <span className="settings-country-code">{c.code}</span>
                    <span className="settings-country-name">{c.name}</span>
                    {country === c.code && <Check size={16} className="settings-lang-check" />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            className="submit-btn settings-save-btn"
            disabled={savingCountry || !countryChanged}
            onClick={saveCountry}
          >
            <Save size={15} /> {savingCountry ? t('bank.processing') : t('settings.saveCountry')}
          </button>
        </div>

        {/* Промокод */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><Ticket size={18} /></span>
            <h3>{t('settings.promoTitle')}</h3>
          </div>
          <div className="form-group">
            <label>{t('settings.promoLabel')}</label>
            <input
              value={promoCode}
              onChange={e => setPromoCode(e.target.value)}
              placeholder={t('settings.promoPlaceholder')}
              maxLength={32}
            />
          </div>
          <button
            className="submit-btn settings-save-btn"
            disabled={redeemingPromo || !promoCode.trim()}
            onClick={applyPromo}
          >
            <Ticket size={15} /> {redeemingPromo ? t('bank.processing') : t('settings.promoApply')}
          </button>
        </div>

        {/* Пароль */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><Lock size={18} /></span>
            <h3>{t('settings.securityTitle')}</h3>
          </div>

          <div className="form-group">
            <label>{t('settings.currentPassword')}</label>
            <input type="password" value={pwd.current} onChange={e => setPwd({ ...pwd, current: e.target.value })} />
          </div>
          <div className="form-group">
            <label>{t('settings.newPassword')}</label>
            <input type="password" value={pwd.next} onChange={e => setPwd({ ...pwd, next: e.target.value })} placeholder={t('auth.enterPassword')} />
          </div>
          <div className="form-group">
            <label>{t('auth.confirmPassword')}</label>
            <input type="password" value={pwd.confirm} onChange={e => setPwd({ ...pwd, confirm: e.target.value })} />
          </div>
          <button
            className="submit-btn settings-save-btn"
            disabled={savingPwd || !pwd.current || !pwd.next || !pwd.confirm}
            onClick={savePassword}
          >
            <Save size={15} /> {savingPwd ? t('bank.processing') : t('settings.savePassword')}
          </button>
        </div>

        {/* Локализация */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><Globe size={18} /></span>
            <h3>{t('settings.localizationTitle')}</h3>
          </div>
          <div className="settings-lang-grid">
            {LANGUAGES.map(l => (
              <button
                key={l.code}
                className={`settings-lang-card ${i18n.language === l.code ? 'active' : ''}`}
                onClick={() => changeLanguage(l.code)}
              >
                <span className="settings-lang-flag">{l.flag}</span>
                <span className="settings-lang-label">{l.label}</span>
                {i18n.language === l.code && <Check size={16} className="settings-lang-check" />}
              </button>
            ))}
          </div>
        </div>

        {/* Оформление (тёмная тема) */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><Moon size={18} /></span>
            <h3>{t('settings.appearanceTitle')}</h3>
          </div>
          <div className="settings-toggle-block settings-appearance-block">
            <label className="settings-toggle-row">
              <span className="settings-toggle-text">{t('settings.darkMode')}</span>
              <span className="settings-switch">
                <input
                  type="checkbox"
                  checked={theme === 'dark'}
                  onChange={toggleDark}
                />
                <span className="settings-switch-track"><span className="settings-switch-thumb" /></span>
              </span>
            </label>
            <p className="settings-hint">{t('settings.darkModeHint')}</p>
          </div>
        </div>

        {/* Статистика игрока */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-icon"><BarChart3 size={18} /></span>
            <h3>{t('settings.statsTitle')}</h3>
          </div>
          <div className="settings-stats-grid">
            {[
              ['netWorth', profile?.stats?.netWorth],
              ['cash', profile?.stats?.cash],
              ['stocks', profile?.stats?.stocks],
              ['crypto', profile?.stats?.crypto],
              ['assets', profile?.stats?.assets],
              ['company', profile?.stats?.company],
              ['warcoin', profile?.stats?.warcoin],
              ['profit', profile?.stats?.profit],
            ].map(([key, val]) => (
              <div className="settings-stat" key={key}>
                <span className="settings-stat-label">{t(`settings.stat.${key}`)}</span>
                <span className={`settings-stat-value ${key === 'profit' && (val || 0) < 0 ? 'neg' : ''}`}>
                  ${Number(val || 0).toLocaleString('ru-RU', { maximumFractionDigits: 0 })}
                </span>
              </div>
            ))}
          </div>
        </div>

      </div>

      <ConfirmDialog
        open={confirmRemove}
        title={t('settings.removeAvatarConfirmTitle')}
        message={t('settings.removeAvatarConfirmMsg')}
        confirmLabel={t('settings.removeAvatar')}
        danger
        busy={savingAvatar}
        onConfirm={removeAvatar}
        onCancel={() => setConfirmRemove(false)}
      />
    </div>
  )
}

export default SettingsPage
