import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Ticket } from 'lucide-react'
import { adminListPromos, adminCreatePromo, adminDeletePromo } from '../services/api'
import { toast } from './Toast'
import ConfirmDialog from './ConfirmDialog'

const EMPTY_FORM = {
  code: '',
  amount: '',
  businessSlug: '',
  badge: '',
  maxUses: '',
  expiresAt: '',
  active: true,
}

const BADGE_OPTIONS = [
  { value: '', label: 'Без значка' },
  { value: 'beta_tester', label: 'Бета-тестер' },
]

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—' : d.toLocaleString('ru-RU')
}

function buildPayload(form) {
  const payload = {
    code: form.code.trim().toUpperCase(),
    amount: form.amount === '' ? 0 : parseFloat(form.amount),
    business_slug: form.businessSlug.trim() || null,
    badge: form.badge || null,
    max_uses: form.maxUses === '' ? null : parseInt(form.maxUses, 10),
    // datetime-local отдаёт локальное время без зоны; считаем его московским (UTC+3).
    expires_at: form.expiresAt ? new Date(`${form.expiresAt}:00+03:00`).toISOString() : null,
    active: !!form.active,
  }
  return payload
}

function PromoCodesTab() {
  const [promos, setPromos] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [confirmId, setConfirmId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await adminListPromos()
      setPromos(res.promos || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const hasRewards = form.amount !== '' || form.businessSlug.trim() || form.badge

  const submit = async (e) => {
    e.preventDefault()
    if (!form.code.trim()) { toast('Укажите код промокода', 'error'); return }
    if (!hasRewards) { toast('Добавьте хотя бы одну награду: деньги, бизнес или значок', 'error'); return }
    setSaving(true)
    try {
      await adminCreatePromo(buildPayload(form))
      toast('Промокод создан')
      setForm(EMPTY_FORM)
      load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    const id = confirmId
    setConfirmId(null)
    try {
      await adminDeletePromo(id)
      toast('Промокод удалён')
      load()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  return (
    <div className="promo-admin">
      <h3 className="promo-admin-title"><Ticket size={18} /> Промокоды</h3>

      <form className="promo-admin-form" onSubmit={submit}>
        <div className="promo-admin-grid">
          <label>Код
            <input className="admin-input" value={form.code} maxLength={32}
              onChange={e => setForm({ ...form, code: e.target.value })} placeholder="WELCOME2026" />
          </label>
          <label>Деньги ($)
            <input className="admin-input" type="number" min="0" step="0.01" value={form.amount}
              onChange={e => setForm({ ...form, amount: e.target.value })} />
          </label>
          <label>Бизнес (slug из каталога)
            <input className="admin-input" value={form.businessSlug}
              onChange={e => setForm({ ...form, businessSlug: e.target.value })} placeholder="itstudio_basic" />
          </label>
          <label>Значок
            <select className="admin-input" value={form.badge}
              onChange={e => setForm({ ...form, badge: e.target.value })}>
              {BADGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label>Лимит использований (пусто = без лимита)
            <input className="admin-input" type="number" min="1" value={form.maxUses}
              onChange={e => setForm({ ...form, maxUses: e.target.value })} />
          </label>
          <label>Действует до (необязательно)
            <input className="admin-input" type="datetime-local" value={form.expiresAt}
              onChange={e => setForm({ ...form, expiresAt: e.target.value })} />
          </label>
        </div>
        <label className="promo-admin-active">
          <input type="checkbox" checked={form.active}
            onChange={e => setForm({ ...form, active: e.target.checked })} /> Активен
        </label>
        <button type="submit" className="submit-btn" disabled={saving}>
          <Plus size={14} /> {saving ? 'Сохранение…' : 'Создать промокод'}
        </button>
      </form>

      {loading ? (
        <div className="loading-state"><div className="spinner" /></div>
      ) : promos.length === 0 ? (
        <p className="promo-admin-empty">Промокодов пока нет</p>
      ) : (
        <table className="promo-admin-table">
          <thead>
            <tr>
              <th>Код</th><th>Деньги</th><th>Бизнес</th><th>Значок</th>
              <th>Использований</th><th>До</th><th>Статус</th><th />
            </tr>
          </thead>
          <tbody>
            {promos.map(p => (
              <tr key={p.id}>
                <td><b>{p.code}</b></td>
                <td>{p.amount ? `$${Number(p.amount).toLocaleString('ru-RU')}` : '—'}</td>
                <td>{p.businessSlug || '—'}</td>
                <td>{p.badge || '—'}</td>
                <td>{p.uses}{p.maxUses != null ? ` / ${p.maxUses}` : ''}</td>
                <td>{formatDate(p.expiresAt)}</td>
                <td>{p.active ? 'активен' : 'выключен'}</td>
                <td>
                  <button className="asset-act sell" onClick={() => setConfirmId(p.id)} title="Удалить">
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={!!confirmId}
        title="Удалить промокод?"
        message="Промокод будет удалён вместе с историей активаций."
        confirmLabel="Удалить"
        danger
        onConfirm={remove}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  )
}

export default PromoCodesTab
