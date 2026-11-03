import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { adminListSupportTickets, adminUpdateSupportTicket } from '../services/api'
import { toast } from './Toast'

const TYPE_OPTIONS = [
  { value: 'all', label: 'Все обращения' },
  { value: 'bug', label: 'Баги' },
  { value: 'loss', label: 'Потеря имущества' },
  { value: 'suggestion', label: 'Предложения' },
]

const STATUS_OPTIONS = [
  { value: 'pending', label: 'Открыт' },
  { value: 'resolved', label: 'Закрыт' },
  { value: 'rejected', label: 'Закрыт без решения' },
]

function SupportTicketsAdmin({ initialCategory = 'all' }) {
  const { t } = useTranslation()
  const [tickets, setTickets] = useState([])
  const [selected, setSelected] = useState(null)
  const [status, setStatus] = useState('pending')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [category, setCategory] = useState(initialCategory)
  const load = () => adminListSupportTickets().then(items => {
    setTickets(items)
    setSelected(current => current ? (items.find(item => item.id === current.id) || current) : current)
  }).catch(err => toast(err.message, 'error'))
  useEffect(() => {
    load()
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => { setCategory(initialCategory) }, [initialCategory])
  const open = ticket => { setSelected(ticket); setStatus(ticket.status); setMessage('') }
  const save = async () => {
    if (!selected || (!message.trim() && status === selected.status)) return
    setSaving(true)
    try {
      const updated = await adminUpdateSupportTicket(selected.id, { status, message: message.trim() })
      setTickets(prev => prev.map(item => item.id === updated.id ? updated : item))
      setSelected(updated); setMessage('')
      toast(t('supportAdmin.saved', 'Обращение сохранено'))
    } catch (err) { toast(err.message, 'error') } finally { setSaving(false) }
  }
  if (selected) return (
    <div className="support-admin-detail">
    <button type="button" className="support-card-btn" onClick={() => setSelected(null)}>← Назад к списку</button>
    <h3>Обращение №{selected.number} — {selected.username}</h3>
    <div className="support-chat">
      {(selected.messages || []).map((item, index) => <div className={`support-message support-message--${item.author}`} key={`${item.created_at}-${index}`}>
        <b>{item.author === 'admin' ? `${item.username || 'Администратор'} 🛡️` : (item.username || 'Игрок')}</b><span>{item.text}</span>
        {(item.attachments || []).map(file => <a key={file.name} href={file.data} download={file.name}>{file.name}</a>)}
      </div>)}
    </div>
    <label className="support-label">Статус<select className="support-input" value={status} onChange={e => setStatus(e.target.value)}>{STATUS_OPTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
    <label className="support-label">Сообщение администратора<textarea className="support-input" rows={4} value={message} onChange={e => setMessage(e.target.value)} placeholder="Уточните проблему или напишите вердикт..." /></label>
    <button type="button" className="support-open-btn" disabled={saving} onClick={save}>Отправить / сохранить</button>
    </div>
  )
  const visibleTickets = category === 'all' ? tickets : tickets.filter(ticket => ticket.type === category)
  return <>
    <div className="support-admin-filters">
      {TYPE_OPTIONS.map(option => <button key={option.value} type="button" className={`support-filter-tab ${category === option.value ? 'active' : ''}`} onClick={() => setCategory(option.value)}>{option.label}</button>)}
    </div>
    <div className="support-grid">
    {visibleTickets.length === 0 && <p className="support-empty">Обращений нет.</p>}
    {visibleTickets.map(ticket => <div className="support-card" key={ticket.id}>
      <div className="support-card-top"><span className="support-reason">№{ticket.number}</span><span className={`support-status support-status--${ticket.status}`}>{STATUS_OPTIONS.find(x => x.value === ticket.status)?.label || ticket.status}</span></div>
      <span className="support-date">{ticket.username} · сообщений: {(ticket.messages || []).length}</span>
      <button type="button" className="support-card-btn" onClick={() => open(ticket)}>Открыть чат</button>
    </div>)}
    </div>
  </>
}
export default SupportTicketsAdmin
