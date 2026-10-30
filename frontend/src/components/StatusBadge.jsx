import { ShieldCheck, FlaskConical } from 'lucide-react'

/**
 * Значки статуса игрока рядом с аватаром.
 * - admin: выводится из роли (role === 'admin'), не хранится отдельно;
 * - beta_tester: выдаётся администратором через поле badges.
 * Возвращает null, если значков нет.
 */
export function getStatusBadges(user) {
  if (!user) return []
  const list = []
  if (user.role === 'admin') list.push('admin')
  if (Array.isArray(user.badges) && user.badges.includes('beta_tester')) list.push('beta_tester')
  return list
}

const BADGE_META = {
  admin: { Icon: ShieldCheck, label: 'Администратор', className: 'status-badge-admin' },
  beta_tester: { Icon: FlaskConical, label: 'Бета-тестер', className: 'status-badge-beta' },
}

function StatusBadge({ user, size = 14, className = '' }) {
  const badges = getStatusBadges(user)
  if (!badges.length) return null
  return (
    <span className={`status-badges ${className}`}>
      {badges.map(key => {
        const { Icon, label, className: cls } = BADGE_META[key]
        return (
          <span key={key} className={`status-badge ${cls}`} title={label} aria-label={label}>
            <Icon size={size} />
          </span>
        )
      })}
    </span>
  )
}

export default StatusBadge
