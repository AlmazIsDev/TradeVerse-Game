import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { updateProfile, changePassword, uploadAvatar, deleteAvatar, toggleLeaderboardVisibility } from '../services/api'
import ConfirmDialog from './ConfirmDialog'
import {
  Settings as SettingsIcon, User, Lock, Globe,
  Save, Trash2, Check, AlertTriangle, Upload,
} from 'lucide-react'

// Итоговый размер аватара — сжимается на клиенте через canvas (cover-crop до
// квадрата), поэтому на сервер уходит небольшая data URL-строка без нужды в
// отдельной инфраструктуре файлового хранилища (см. backend/user_profile.py).
const AVATAR_SIZE = 256
const AVATAR_QUALITY = 0.85

const LANGUAGES = [
  { code: 'ru', label: 'Русский', flag: '🇷🇺' },
  { code: 'en', label: 'English', flag: '🇬🇧' },
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

function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return isNaN(d.getTime()) ? null : d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })
}

function SettingsPage({ user, onUserUpdate }) {
  const { t, i18n } = useTranslation()
  const [msg, setMsg] = useState(null)
  const flash = (text, type = 'success') => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 2600)
  }

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
      flash(t('settings.profileSaved'))
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setSavingProfile(false)
    }
  }

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
      flash(err.message, 'error')
    } finally {
      setSavingLbVisibility(false)
    }
  }

  // ── Пароль ─────────────────────────────────────────────────────────────────
  const [pwd, setPwd] = useState({ current: '', next: '', confirm: '' })
  const [savingPwd, setSavingPwd] = useState(false)

  const savePassword = async () => {
    if (!pwd.current || !pwd.next || !pwd.confirm) { flash(t('auth.fillAllFields'), 'error'); return }
    if (pwd.next.length < 6) { flash(t('auth.passwordTooShort'), 'error'); return }
    if (pwd.next !== pwd.confirm) { flash(t('auth.passwordsMismatch'), 'error'); return }
    setSavingPwd(true)
    try {
      await changePassword({
        current_password: pwd.current, new_password: pwd.next, confirm_password: pwd.confirm,
      })
      setPwd({ current: '', next: '', confirm: '' })
      flash(t('settings.passwordSaved'))
    } catch (err) {
      flash(err.message, 'error')
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
    if (!file.type.startsWith('image/')) { flash(t('settings.avatarInvalidType'), 'error'); return }
    try {
      const dataUrl = await readAndResizeImage(file)
      setStagedAvatar(dataUrl)
    } catch {
      flash(t('settings.avatarInvalidType'), 'error')
    }
  }

  const saveAvatar = async () => {
    if (!stagedAvatar) return
    setSavingAvatar(true)
    try {
      const res = await uploadAvatar(stagedAvatar)
      onUserUpdate?.({ avatar: res.avatar })
      setStagedAvatar(null)
      flash(t('settings.avatarSaved'))
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setSavingAvatar(false)
    }
  }

  const removeAvatar = async () => {
    setSavingAvatar(true)
    try {
      await deleteAvatar()
      onUserUpdate?.({ avatar: null })
      flash(t('settings.avatarRemoved'))
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setSavingAvatar(false)
      setConfirmRemove(false)
    }
  }

  // ── Локализация ────────────────────────────────────────────────────────────
  const changeLanguage = (code) => {
    if (code === i18n.language) return
    i18n.changeLanguage(code)
    localStorage.setItem('language', code)
  }

  const currentAvatar = stagedAvatar || user?.avatar || null
  const initials = (user?.username || '?').slice(0, 2).toUpperCase()
  const since = formatDate(user?.created_at)

  return (
    <div className="settings-page">
      <div className="settings-title-row">
        <SettingsIcon size={22} className="icon" />
        <h2 className="tab-title">{t('nav.settings')}</h2>
      </div>

      {msg && (
        <div className={`transfer-feedback ${msg.type}`} style={{ marginBottom: 'var(--spacing-md)' }}>
          {msg.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}<span>{msg.text}</span>
        </div>
      )}

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

          <div className="settings-current-info">
            <span>{t('profile.name')}: <b>{user?.username}</b></span>
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
