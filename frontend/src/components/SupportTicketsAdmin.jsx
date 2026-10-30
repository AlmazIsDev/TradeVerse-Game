import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { adminListSupportTickets, adminUpdateSupportTicket } from '../services/api'
import { toast } from './Toast'

const TYPE_LABELS = {
  bug: { key: 'support.typeBug', fallback: 'Баг' },
  loss: { key: 'support.typeLoss', fallback: 'Потеря имущества' },
  suggestion: { key: 'support.typeSuggestion', fallback: 'Предложение по улучшению' },
}

const STATUS_OPTIONS = [
  { value: 'pending', key: 'supportAdmin.statusPending', label: 'На рассмотрение' },
  { value: 'rejected', key: 'supportAdmin.statusRejected', label: 'Отказано' },
  { value: 'resolved', key: 'supportAdmin.statusResolved', label: 'Рассмотрено' },
]

function ticketBody(ticket, t) {
  if (ticket.type === 'loss') {
    return [
      [t('support.lostItem', 'Что потерялось'), ticket.lost_item],
      [t('support.method', 'Каким способом'), ticket.method],
      [t('support.approxTime', 'Примерное время'), ticket.time],
    ]
  }
  if (ticket.type === 'suggestion') return [[t('support.suggestion', 'Предложение'), ticket.suggestion]]
  return [[t('support.bugDescription', 'Описание бага'), ticket.description]]
}

function SupportTicketsAdmin() {
  const { t } = useTranslation()
  const [tickets, setTickets] = useState([])
  const [selected, setSelected] = useState(null)
  const [status, setStatus] = useState('pending')
  const [reply, setReply] = useState('')
  const [saving, setSaving] = useState(false)

  const load = () => adminListSupportTickets().then(setTickets).catch(err => toast(err.message, 'error'))

  useEffect(() => { load() }, [])

  const open = (ticket) => {
    setSelected(ticket)
    setStatus(ticket.status)
    setReply(ticket.reply || '')
  }

  const save = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const updated = await adminUpdateSupportTicket(selected.id, { status, reply })
      setTickets(prev => prev.map(t => (t.id === updated.id ? updated : t)))
      setSelected(updated)
      toast(t('supportAdmin.saved', 'Обращение сохранено'))
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  if (selected) {
    return (
      <div className="support-admin-detail">
        <button type="button" className="support-card-btn" onClick={() => setSelected(null)}>{t('supportAdmin.back', '← Назад к списку')}</button>
        <h3>{TYPE_LABELS[selected.type] ? t(TYPE_LABELS[selected.type].key, TYPE_LABELS[selected.type].fallback) : ''} — {selected.username}</h3>
        {ticketBody(selected, t).map(([label, value]) => (
          <div className="support-field" key={label}>
            <span className="support-field-label">{label}</span>
            <p className="support-field-value">{value}</p>
          </div>
        ))}
        <label className="support-label">
          {t('supportAdmin.statusLabel', 'Статус')}
          <select className="support-input" value={status} onChange={e => setStatus(e.target.value)}>
            {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{t(o.key, o.label)}</option>)}
          </select>
        </label>
        <label className="support-label">
          {t('support.adminReply', 'Ответ администрации')}
          <textarea className="support-input" rows={4} value={reply} onChange={e => setReply(e.target.value)} />
        </label>
        <button type="button" className="support-open-btn" disabled={saving} onClick={save}>{t('supportAdmin.save', 'Сохранить')}</button>
      </div>
    )
  }

  return (
    <div className="support-grid">
      {tickets.length === 0 && <p className="support-empty">{t('supportAdmin.empty', 'Обращений нет.')}</p>}
      {tickets.map(ticket => (
        <div className="support-card" key={ticket.id}>
          <div className="support-card-top">
            <span className="support-reason">{TYPE_LABELS[ticket.type] ? t(TYPE_LABELS[ticket.type].key, TYPE_LABELS[ticket.type].fallback) : ticket.type}</span>
            <span className={`support-status support-status--${ticket.status}`}>{(() => { const o = STATUS_OPTIONS.find(x => x.value === ticket.status); return o ? t(o.key, o.label) : ticket.status })()}</span>
          </div>
          <span className="support-date">{ticket.username}</span>
          <button type="button" className="support-card-btn" onClick={() => open(ticket)}>{t('supportAdmin.open', 'Открыть')}</button>
        </div>
      ))}
    </div>
  )
}

export default SupportTicketsAdmin
