import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { acceptInvite, declineInvite, acceptApplication, declineApplication } from '../services/api'
import { Building2, UserPlus, Check, X, Globe } from 'lucide-react'

const ACTIONABLE = new Set(['company_invite', 'company_application'])
const EVENT_POPUP_TTL_MS = 7000

/**
 * Глобальный центр realtime-уведомлений.
 * Слушает window-событие 'tv:realtime' (его диспатчит Dashboard на каждое
 * WS-сообщение) и для важных уведомлений (приглашение/заявка) показывает
 * красивый всплывающий pop-up без перезагрузки страницы.
 *
 * Кнопки: Принять / Отклонить / крестик.
 *  - Принять/Отклонить — вызывают API и убирают pop-up.
 *  - Крестик — только скрывает pop-up; уведомление уже сохранено на сервере
 *    и остаётся в колокольчике (разделе уведомлений).
 */
function NotificationCenter() {
  const { t } = useTranslation()
  const [popups, setPopups] = useState([])   // [{ id, type, title, body, data }]
  const [busyId, setBusyId] = useState(null)

  const dismiss = useCallback((id) => {
    setPopups(prev => prev.filter(p => p.id !== id))
  }, [])

  useEffect(() => {
    const onRealtime = (ev) => {
      const data = ev.detail
      if (!data) return
      // Мировое экономическое событие (backend/market_events.py) — шлётся всем
      // игрокам broadcast'ом, раньше нигде не показывалось на фронте.
      if (data.type === 'event' || data.type === 'event_ended') {
        const started = data.type === 'event'
        const popup = {
          id: `${data.type}-${data.name}-${Date.now()}`,
          kind: 'event',
          icon: data.icon,
          title: started
            ? t('notifications.worldEventStarted', { name: data.name })
            : t('notifications.worldEventEnded', { name: data.name }),
        }
        setPopups(prev => [popup, ...prev].slice(0, 4))
        setTimeout(() => dismiss(popup.id), EVENT_POPUP_TTL_MS)
        return
      }
      if (data.type !== 'notification' || !data.notification) return
      const n = data.notification
      // Мгновенно обновляем ленту в шапке (без debounce 1.2с).
      window.dispatchEvent(new CustomEvent('tv:notif'))
      if (!ACTIONABLE.has(n.type)) return
      setPopups(prev => (prev.some(p => p.id === n.id) ? prev : [{ ...n, kind: 'action' }, ...prev].slice(0, 4)))
    }
    window.addEventListener('tv:realtime', onRealtime)
    return () => window.removeEventListener('tv:realtime', onRealtime)
  }, [t, dismiss])

  const act = async (popup, accept) => {
    setBusyId(popup.id)
    try {
      if (popup.type === 'company_application') {
        const appId = popup.data?.applicationId
        if (appId) accept ? await acceptApplication(appId) : await declineApplication(appId)
      } else {
        const inviteId = popup.data?.inviteId
        if (inviteId) accept ? await acceptInvite(inviteId) : await declineInvite(inviteId)
      }
      // Обновляем ленту уведомлений и данные компании у обоих игроков.
      window.dispatchEvent(new CustomEvent('tv:notif'))
      window.dispatchEvent(new CustomEvent('tv:company-refresh'))
    } catch { /* ignore — уведомление останется в колокольчике */ }
    finally {
      setBusyId(null)
      dismiss(popup.id)
    }
  }

  if (popups.length === 0) return null

  return (
    <div className="tv-popup-stack">
      {popups.map(p => {
        const isEvent = p.kind === 'event'
        const isInvite = p.type === 'company_invite'
        const busy = busyId === p.id
        return (
          <div key={p.id} className={`tv-popup-card ${isEvent ? 'tv-popup-event' : ''}`}>
            <button className="tv-popup-close" onClick={() => dismiss(p.id)} disabled={busy} title={t('common.close')}>
              <X size={16} />
            </button>
            <div className="tv-popup-icon">
              {isEvent ? (p.icon || <Globe size={22} />) : isInvite ? <UserPlus size={22} /> : <Building2 size={22} />}
            </div>
            <div className="tv-popup-body">
              <span className="tv-popup-title">{p.title}</span>
              {p.body && <span className="tv-popup-text">{p.body}</span>}
              {isInvite && p.data && (
                <div className="tv-popup-meta">
                  {p.data.role && <span>{t(`company.roles.${p.data.role}`, p.data.role)}</span>}
                  {p.data.salary != null && <span>${Number(p.data.salary).toLocaleString('ru-RU')}/ч</span>}
                </div>
              )}
              {!isEvent && (
                <div className="tv-popup-actions">
                  <button className="tv-popup-btn accept" disabled={busy} onClick={() => act(p, true)}>
                    <Check size={14} /> {t('company.accept')}
                  </button>
                  <button className="tv-popup-btn decline" disabled={busy} onClick={() => act(p, false)}>
                    <X size={14} /> {t('company.decline')}
                  </button>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default NotificationCenter
