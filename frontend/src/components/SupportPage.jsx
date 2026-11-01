import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { LifeBuoy, Plus, X } from 'lucide-react'
import { createSupportTicket, fetchMySupportTickets } from '../services/api'
import { toast } from './Toast'
import '../support.css'

const TYPES = {
  bug: { key: 'support.typeBug', label: 'Баг' },
  loss: { key: 'support.typeLoss', label: 'Потеря имущества' },
  suggestion: { key: 'support.typeSuggestion', label: 'Предложение по улучшению' },
}

const STATUS_LABELS = {
  pending: { key: 'support.statusPending', label: 'На рассмотрении' },
  rejected: { key: 'support.statusRejected', label: 'Отказано' },
  resolved: { key: 'support.statusResolved', label: 'Рассмотрено' },
}

const EMPTY_FORM = {
  type: 'bug',
  description: '',
  lostItem: '',
  method: '',
  time: '',
  suggestion: '',
}

const EMPTY_VALUE = '—'

// Текст обращения, который показывается в карточке (2–3 строки через CSS-обрезку).
// Любое отсутствующее поле подменяется прочерком: сервер может вернуть тип, о
// котором фронтенд ещё не знает, и пустая карточка выглядит как баг вёрстки.
function ticketPreview(ticket) {
  if (ticket.type === 'loss') {
    return [ticket.lost_item, ticket.method].filter(Boolean).join(' — ') || EMPTY_VALUE
  }
  if (ticket.type === 'suggestion') return ticket.suggestion || EMPTY_VALUE
  return ticket.description || EMPTY_VALUE
}

// Полные поля обращения для модального окна просмотра.
function ticketFields(ticket, t) {
  const value = (v) => (v == null || v === '' ? EMPTY_VALUE : v)
  if (ticket.type === 'loss') {
    return [
      { label: t('support.lostItem', 'Что потерялось'), value: value(ticket.lost_item) },
      { label: t('support.method', 'Каким способом'), value: value(ticket.method) },
      { label: t('support.approxTime', 'Примерное время'), value: value(ticket.time) },
    ]
  }
  if (ticket.type === 'suggestion') {
    return [{ label: t('support.suggestion', 'Предложение'), value: value(ticket.suggestion) }]
  }
  return [{ label: t('support.bugDescription', 'Описание бага'), value: value(ticket.description) }]
}

function isFormValid(form) {
  if (form.type === 'bug') return form.description.trim() !== ''
  if (form.type === 'loss') {
    return form.lostItem.trim() && form.method.trim() && form.time.trim()
  }
  return form.suggestion.trim() !== ''
}

function buildPayload(form) {
  if (form.type === 'bug') return { type: 'bug', description: form.description.trim() }
  if (form.type === 'loss') {
    return {
      type: 'loss',
      lost_item: form.lostItem.trim(),
      method: form.method.trim(),
      time: form.time.trim(),
    }
  }
  return { type: 'suggestion', suggestion: form.suggestion.trim() }
}

function SupportPage() {
  const { t, i18n } = useTranslation()
  const [tickets, setTickets] = useState([])
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [selected, setSelected] = useState(null)
  // Ref, а не state: второй submit в том же тике (двойной Enter) читает ещё
  // не обновлённое значение and успевает создать дубликат обращения.
  const submitLock = useRef(false)

  useEffect(() => {
    fetchMySupportTickets().then(setTickets).catch(err => toast(err.message, 'error'))
  }, [])

  const setField = (key, value) => setForm(prev => ({ ...prev, [key]: value }))

  const closeCreate = () => {
    setCreateOpen(false)
    setForm(EMPTY_FORM)
  }

  const submitTicket = async (e) => {
    e.preventDefault()
    if (!isFormValid(form) || submitLock.current) return
    submitLock.current = true
    setSubmitting(true)
    try {
      const ticket = await createSupportTicket(buildPayload(form))
      setTickets(prev => [ticket, ...prev])
      closeCreate()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      submitLock.current = false
      setSubmitting(false)
    }
  }

  // Неизвестный тип приходит, если бэкенд добавил категорию раньше фронтенда:
  // показываем сырой идентификатор, а не пустой заголовок карточки.
  const typeLabel = (type) => (TYPES[type] ? t(TYPES[type].key, TYPES[type].label) : type)
  const statusLabel = (status) => (STATUS_LABELS[status] ? t(STATUS_LABELS[status].key, STATUS_LABELS[status].label) : status)

  // Дата — по активной локали интерфейса, а не жёстко по ru-RU.
  const locale = i18n?.language || 'ru'
  const formatDate = (iso) => {
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? EMPTY_VALUE : d.toLocaleString(locale)
  }

  return (
    <div className="support-page">
      <div className="support-header">
        <h1 className="support-page-title">
          <LifeBuoy size={22} /> {t('support.title', 'Техническая поддержка')}
        </h1>
        <div className="support-header-actions">
          <button type="button" className="support-open-btn" onClick={() => setCreateOpen(true)}>
            <Plus size={16} /> {t('support.openTicket', 'Открыть обращение')}
          </button>
        </div>
      </div>

      {tickets.length === 0 ? (
        <p className="support-empty">{t('support.empty', 'Обращений пока нет.')}</p>
      ) : (
        <div className="support-grid">
          {tickets.map(ticket => (
            <div className="support-card" key={ticket.id}>
              <div className="support-card-top">
                <span className="support-reason">{typeLabel(ticket.type)}</span>
                <span className={`support-status support-status--${ticket.status}`}>{statusLabel(ticket.status)}</span>
              </div>
              <p className="support-card-text">{ticketPreview(ticket)}</p>
              <button type="button" className="support-card-btn" onClick={() => setSelected(ticket)}>
                {t('support.openFull', 'Открыть полное обращение')}
              </button>
            </div>
          ))}
        </div>
      )}

      {createOpen && (
        <div className="support-overlay" onClick={closeCreate}>
          <form className="support-modal" onClick={e => e.stopPropagation()} onSubmit={submitTicket}>
            <div className="support-modal-head">
              <h2>{t('support.newTicket', 'Новое обращение')}</h2>
              <button type="button" className="support-icon-btn" onClick={closeCreate}><X size={18} /></button>
            </div>

            <label className="support-label">
              {t('support.ticketType', 'Тип обращения')}
              <select className="support-input" value={form.type} onChange={e => setField('type', e.target.value)}>
                {Object.entries(TYPES).map(([value, { key, label }]) => (
                  <option key={value} value={value}>{t(key, label)}</option>
                ))}
              </select>
            </label>

            {form.type === 'bug' && (
              <label className="support-label">
                {t('support.describeBug', 'Опишите баг')}
                <textarea className="support-input" rows={5} value={form.description}
                  onChange={e => setField('description', e.target.value)} />
              </label>
            )}

            {form.type === 'loss' && (
              <>
                <label className="support-label">
                  {t('support.lostItem', 'Что потерялось')}
                  <input className="support-input" value={form.lostItem}
                    onChange={e => setField('lostItem', e.target.value)} />
                </label>
                <label className="support-label">
                  {t('support.method', 'Каким способом')}
                  <input className="support-input" value={form.method}
                    onChange={e => setField('method', e.target.value)} />
                </label>
                <label className="support-label">
                  {t('support.approxTime', 'Примерное время')}
                  <input className="support-input" value={form.time}
                    onChange={e => setField('time', e.target.value)} />
                </label>
              </>
            )}

            {form.type === 'suggestion' && (
              <label className="support-label">
                {t('support.yourSuggestion', 'Ваше предложение')}
                <textarea className="support-input" rows={5} value={form.suggestion}
                  onChange={e => setField('suggestion', e.target.value)} />
              </label>
            )}

            <div className="support-modal-actions">
              <button type="button" className="support-cancel-btn" onClick={closeCreate}>{t('support.cancel', 'Отмена')}</button>
              <button type="submit" className="support-open-btn" disabled={!isFormValid(form) || submitting}>
                {t('support.submit', 'Отправить')}
              </button>
            </div>
          </form>
        </div>
      )}

      {selected && (
        <div className="support-overlay" onClick={() => setSelected(null)}>
          <div className="support-modal" onClick={e => e.stopPropagation()}>
            <div className="support-modal-head">
              <h2>{typeLabel(selected.type)}</h2>
              <button type="button" className="support-icon-btn" onClick={() => setSelected(null)}><X size={18} /></button>
            </div>
            <div className="support-card-top">
              <span className="support-status">{statusLabel(selected.status)}</span>
              <span className="support-date">{formatDate(selected.created_at)}</span>
            </div>
            {ticketFields(selected, t).map(field => (
              <div className="support-field" key={field.label}>
                <span className="support-field-label">{field.label}</span>
                <p className="support-field-value">{field.value}</p>
              </div>
            ))}
            {selected.reply && (
              <div className="support-field">
                <span className="support-field-label">{t('support.adminReply', 'Ответ администрации')}</span>
                <p className="support-field-value">{selected.reply}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default SupportPage
