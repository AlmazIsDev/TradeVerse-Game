import { useEffect, useState } from 'react'
import { X, Plus, Bug, CheckCircle2 } from 'lucide-react'
import { request } from '../services/api'
import { toast } from './Toast'

const STATUS = [{ value: 'new', label: 'Новый' }, { value: 'in_progress', label: 'В работе' }, { value: 'fixed', label: 'Исправлено' }]

export default function AdminBugs() {
  const [bugs, setBugs] = useState([])
  const [formOpen, setFormOpen] = useState(false)
  const [selected, setSelected] = useState(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const load = () => request('/api/admin/bugs').then(setBugs).catch(err => toast(err.message, 'error'))
  useEffect(() => { load() }, [])
  const create = async e => {
    e.preventDefault()
    if (!title.trim() || !description.trim()) return
    try { const item = await request('/api/admin/bugs', { method: 'POST', body: JSON.stringify({ title: title.trim(), description: description.trim() }) }); setBugs(prev => [item, ...prev]); setTitle(''); setDescription(''); setFormOpen(false) } catch (err) { toast(err.message, 'error') }
  }
  const setStatus = async (bug, status) => {
    try { const item = await request(`/api/admin/bugs/${bug.id}`, { method: 'PATCH', body: JSON.stringify({ status }) }); setBugs(prev => prev.map(x => x.id === item.id ? item : x)); setSelected(item) } catch (err) { toast(err.message, 'error') }
  }
  return <div className="admin-bugs">
    <div className="admin-bugs-head"><div><h2><Bug size={21} /> Баги</h2><p>Внутренний список проблем от игроков</p></div><button className="support-open-btn" onClick={() => setFormOpen(true)}><Plus size={16} /> Добавить баг</button></div>
    <div className="admin-bug-list">{bugs.length === 0 && <p className="support-empty">Багов пока нет.</p>}{bugs.map(bug => <button className="admin-bug-card" key={bug.id} onClick={() => setSelected(bug)}><span className={`admin-bug-icon admin-bug-icon--${bug.status}`}>{bug.status === 'fixed' ? <CheckCircle2 size={20} /> : <Bug size={20} />}</span><span className="admin-bug-card-body"><b>{bug.title}</b><small>{bug.description}</small><em>Добавил: {bug.created_by}</em></span><span className={`support-status support-status--${bug.status}`}>{STATUS.find(x => x.value === bug.status)?.label}</span></button>)}</div>
    {formOpen && <div className="support-overlay" onClick={() => setFormOpen(false)}><form className="support-modal" onClick={e => e.stopPropagation()} onSubmit={create}><div className="support-modal-head"><h2>Новый баг</h2><button type="button" className="support-icon-btn" onClick={() => setFormOpen(false)}><X size={18} /></button></div><label className="support-label">Название<input className="support-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="Например: не начисляется награда" /></label><label className="support-label">Описание<textarea className="support-input" value={description} onChange={e => setDescription(e.target.value)} placeholder="Опишите проблему игрока подробно" rows={6} /></label><div className="support-modal-actions"><button type="button" className="support-cancel-btn" onClick={() => setFormOpen(false)}>Отмена</button><button className="support-open-btn" disabled={!title.trim() || !description.trim()}>Добавить баг</button></div></form></div>}
    {selected && <div className="support-overlay" onClick={() => setSelected(null)}><div className="support-modal" onClick={e => e.stopPropagation()}><div className="support-modal-head"><h2>{selected.title}</h2><button className="support-icon-btn" onClick={() => setSelected(null)}><X size={18} /></button></div><div className="admin-bug-detail"><span className="support-field-label">Описание проблемы</span><p>{selected.description}</p><small>Добавил: {selected.created_by}</small></div><label className="support-label">Статус<select className="support-input" value={selected.status} onChange={e => setStatus(selected, e.target.value)}>{STATUS.map(x => <option value={x.value} key={x.value}>{x.label}</option>)}</select></label></div></div>}
  </div>
}
