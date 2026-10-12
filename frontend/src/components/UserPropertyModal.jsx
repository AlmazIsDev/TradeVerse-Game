import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  adminFetchUserProperty,
  adminUpdateAsset, adminDeleteAsset, adminTransferAsset,
  adminUpdateFarm, adminDeleteFarm, adminTransferFarm, adminUninstallFarm,
  adminUpdateCompany, adminDeleteCompany, adminTransferCompany,
  adminListCompanyMembers, adminRemoveCompanyMember,
  adminUpdateBusiness, adminVacateBusiness, adminTransferBusiness,
  adminFetchInventory, adminUninstallHardware, adminDeleteHardware,
} from '../services/api'
import ConfirmDialog from './ConfirmDialog'
import { toast } from './Toast'
import {
  X, Package, Cpu, Briefcase, Building2, Edit3, Trash2, ArrowLeftRight, Save,
  HardDrive, Wrench, UserMinus, ChevronDown, ChevronUp,
} from 'lucide-react'

const TABS = [
  { id: 'assets', icon: Package },
  { id: 'farms', icon: Cpu },
  { id: 'inventory', icon: HardDrive },
  { id: 'company', icon: Briefcase },
  { id: 'businesses', icon: Building2 },
]

// Порядок отображения компонентов фермы: одиночные слоты + массивы.
const COMP_ROLES = ['motherboard', 'cpu', 'ram', 'ssd', 'cooling', 'case', 'rack', 'ups', 'network']
const COMP_LISTS = ['gpus', 'fans', 'psus']

/**
 * Модалка полного управления имуществом игрока из админ-панели: активы,
 * майнинг-фермы (вплоть до полного разбора), инвентарь железа, компания
 * (с сотрудниками) и бизнесы «Крыши города». Правки/удаление/передача
 * владения выполняются через админ-эндпоинты (см. services/api.js) и
 * обходят обычные игровые ограничения (см. backend
 * AdminAssetUpdate/AdminFarmUpdate/AdminCompanyUpdate/AdminBusinessUpdate).
 */
function UserPropertyModal({ username, userId, onClose }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState('assets')
  const [data, setData] = useState(null)
  const [inventory, setInventory] = useState([])
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null) // { kind, id, form }
  const [transferring, setTransferring] = useState(null) // { kind, id, name }
  const [transferTo, setTransferTo] = useState('')
  const [confirmTarget, setConfirmTarget] = useState(null) // { kind, id, name, companyId? }
  const [expandedFarm, setExpandedFarm] = useState(null) // id фермы с раскрытым составом
  const [busy, setBusy] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [prop, inv] = await Promise.all([
        adminFetchUserProperty(userId),
        adminFetchInventory(userId).catch(() => []),
      ])
      setData(prop)
      setInventory(inv.items || [])
      if (prop.company) {
        adminListCompanyMembers(prop.company.id)
          .then(r => setMembers(r.members || []))
          .catch(() => setMembers([]))
      } else {
        setMembers([])
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [userId])

  const startEdit = (kind, item) => {
    if (kind === 'assets') {
      setEditing({ kind, id: item.id, form: {
        level: String(item.level ?? ''), price: String(item.price ?? ''),
        income_per_hour: String(item.incomePerHour ?? ''), upkeep_per_hour: String(item.upkeepPerHour ?? ''),
      } })
    } else if (kind === 'farms') {
      setEditing({ kind, id: item.id, form: {
        condition: String(item.condition ?? ''), overclock: String(item.overclock ?? ''),
        electricity_owed: String(item.electricityOwed ?? ''), status: item.status || 'idle',
      } })
    } else if (kind === 'company') {
      setEditing({ kind, id: item.id, form: {
        name: item.name || '', budget: String(item.budget ?? ''),
        isOpen: !!item.isOpen, visibleInSearch: !!item.visibleInSearch,
      } })
    } else if (kind === 'businesses') {
      setEditing({ kind, id: item.id, form: {
        name: item.name || '', reward: String(item.reward ?? ''),
        protection_level: String(item.protectionLevel ?? ''),
      } })
    }
  }

  const cancelEdit = () => setEditing(null)

  const saveEdit = async () => {
    if (!editing) return
    setBusy(true)
    try {
      const { kind, id, form } = editing
      if (kind === 'assets') {
        await adminUpdateAsset(id, {
          level: form.level !== '' ? parseInt(form.level) : undefined,
          price: form.price !== '' ? parseFloat(form.price) : undefined,
          income_per_hour: form.income_per_hour !== '' ? parseFloat(form.income_per_hour) : undefined,
          upkeep_per_hour: form.upkeep_per_hour !== '' ? parseFloat(form.upkeep_per_hour) : undefined,
        })
      } else if (kind === 'farms') {
        await adminUpdateFarm(id, {
          condition: form.condition !== '' ? parseFloat(form.condition) : undefined,
          overclock: form.overclock !== '' ? parseFloat(form.overclock) : undefined,
          electricity_owed: form.electricity_owed !== '' ? parseFloat(form.electricity_owed) : undefined,
          status: form.status || undefined,
        })
      } else if (kind === 'company') {
        await adminUpdateCompany(id, {
          name: form.name || undefined,
          budget: form.budget !== '' ? parseFloat(form.budget) : undefined,
          isOpen: form.isOpen,
          visibleInSearch: form.visibleInSearch,
        })
      } else if (kind === 'businesses') {
        await adminUpdateBusiness(id, {
          name: form.name || undefined,
          reward: form.reward !== '' ? parseInt(form.reward) : undefined,
          protection_level: form.protection_level !== '' ? parseInt(form.protection_level) : undefined,
        })
      }
      setEditing(null)
      toast(t('admin.property.saved'))
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doDelete = async () => {
    if (!confirmTarget) return
    setBusy(true)
    try {
      const { kind, id, companyId } = confirmTarget
      if (kind === 'assets') await adminDeleteAsset(id)
      else if (kind === 'farms') await adminDeleteFarm(id)
      else if (kind === 'company') await adminDeleteCompany(id)
      else if (kind === 'businesses') await adminVacateBusiness(id)
      else if (kind === 'hardware') await adminDeleteHardware(id)
      else if (kind === 'member') await adminRemoveCompanyMember(companyId, id)
      else if (kind === 'farmUninstall') await adminUninstallFarm(id)
      setConfirmTarget(null)
      toast(t(kind === 'farmUninstall' ? 'admin.property.dismantled' : 'admin.property.deleted'))
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const doUninstallHw = async (h) => {
    setBusy(true)
    try {
      await adminUninstallHardware(h.id)
      toast(t('admin.property.hwUninstalled'))
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const submitTransfer = async () => {
    if (!transferring || !transferTo.trim()) return
    setBusy(true)
    try {
      const { kind, id } = transferring
      if (kind === 'assets') await adminTransferAsset(id, transferTo.trim())
      else if (kind === 'farms') await adminTransferFarm(id, transferTo.trim())
      else if (kind === 'company') await adminTransferCompany(id, transferTo.trim())
      else if (kind === 'businesses') await adminTransferBusiness(id, transferTo.trim())
      setTransferring(null)
      setTransferTo('')
      toast(t('admin.property.transferred'))
      await load()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const renderActions = (kind, item, deleteLabelKey = 'admin.property.delete', extra = null) => (
    <div className="user-actions">
      {extra}
      <button className="admin-btn" onClick={() => startEdit(kind, item)}><Edit3 size={14} /></button>
      <button className="admin-btn" onClick={() => { setTransferring({ kind, id: item.id, name: item.name }); setTransferTo('') }}>
        <ArrowLeftRight size={14} />
      </button>
      <button className="admin-btn admin-btn-danger" onClick={() => setConfirmTarget({ kind, id: item.id, name: item.name })}>
        <Trash2 size={14} />
      </button>
    </div>
  )

  // Чипы установленного железа фермы: одиночные слоты + массивы (GPU ×N).
  const renderComponents = (farm) => {
    const comp = farm.components || {}
    const chips = []
    for (const role of COMP_ROLES) {
      const node = comp[role]
      if (node?.hwId) chips.push({ key: role, label: t(`admin.property.comp_${role}`), name: node.name, count: 1 })
    }
    for (const key of COMP_LISTS) {
      const arr = comp[key] || []
      if (arr.length) chips.push({
        key, count: arr.length,
        label: t(`admin.property.comp_${key}`),
        name: arr.map(x => x.name).filter(Boolean).join(', '),
      })
    }
    if (!chips.length) return <span className="uprop-empty-comp">{t('admin.property.noComponents')}</span>
    return (
      <div className="uprop-comps">
        {chips.map(c => (
          <span key={c.key} className="uprop-comp" title={c.name}>
            <b>{c.label}{c.count > 1 ? ` ×${c.count}` : ''}:</b> {c.name}
          </span>
        ))}
      </div>
    )
  }

  const assets = data?.assets || []
  const farms = data?.farms || []
  const company = data?.company || null
  const businesses = data?.businesses || []
  const farmNameById = Object.fromEntries(farms.map(f => [f.id, f.name]))

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content user-property-modal" onClick={e => e.stopPropagation()}>
        <button className="crypto-modal-close" onClick={onClose}><X size={18} /></button>
        <h3><Briefcase size={18} /> {t('admin.property.title')}: {username}</h3>

        <div className="market-cats" style={{ margin: 'var(--spacing-md) 0' }}>
          {TABS.map(tb => {
            const Icon = tb.icon
            const count = tb.id === 'assets' ? assets.length : tb.id === 'farms' ? farms.length
              : tb.id === 'inventory' ? inventory.length
              : tb.id === 'company' ? (company ? 1 : 0) : businesses.length
            return (
              <button key={tb.id} className={`tx-pill ${tab === tb.id ? 'active' : ''}`} onClick={() => setTab(tb.id)}>
                <Icon size={14} /> {t(`admin.property.tab_${tb.id}`)} ({count})
              </button>
            )
          })}
        </div>

        {loading && <div className="loading-state"><div className="spinner" /><p>{t('common.loading')}</p></div>}

        {!loading && tab === 'assets' && (
          <div className="admin-list">
            {assets.length === 0 && <p className="empty-state">{t('admin.property.emptyAssets')}</p>}
            {assets.map(a => (
              <div key={a.id} className="admin-user-item">
                {editing?.kind === 'assets' && editing.id === a.id ? (
                  <div className="admin-user-edit-form">
                    <div className="admin-user-edit-header"><strong>{a.name}</strong></div>
                    <div className="admin-user-edit-fields">
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldLevel')}</label>
                        <input type="number" className="admin-input" value={editing.form.level}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, level: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldPrice')}</label>
                        <input type="number" className="admin-input" value={editing.form.price}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, price: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldIncome')}</label>
                        <input type="number" className="admin-input" value={editing.form.income_per_hour}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, income_per_hour: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldUpkeep')}</label>
                        <input type="number" className="admin-input" value={editing.form.upkeep_per_hour}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, upkeep_per_hour: e.target.value } })} />
                      </div>
                    </div>
                    <div className="admin-user-edit-actions">
                      <button className="admin-btn admin-btn-primary" disabled={busy} onClick={saveEdit}><Save size={14} /> {t('admin.save')}</button>
                      <button className="admin-btn" disabled={busy} onClick={cancelEdit}><X size={14} /> {t('admin.cancel')}</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="admin-user-info">
                      <div className="uprop-title-row"><strong>{t(`assetNames.${a.slug}`, a.name)}</strong> <span className="user-role user">{a.type}</span></div>
                      <div className="admin-user-meta">
                        <span>{t('admin.property.fieldLevel')}: {a.level}</span>
                        <span>${a.price}</span>
                        <span className="up">+${a.incomePerHour}/h</span>
                        <span className="down">-${a.upkeepPerHour}/h</span>
                      </div>
                    </div>
                    {renderActions('assets', a)}
                  </>
                )}
              </div>
            ))}
          </div>
        )}

        {!loading && tab === 'farms' && (
          <div className="admin-list">
            {farms.length === 0 && <p className="empty-state">{t('admin.property.emptyFarms')}</p>}
            {farms.map(f => (
              <div key={f.id} className="admin-user-item">
                {editing?.kind === 'farms' && editing.id === f.id ? (
                  <div className="admin-user-edit-form">
                    <div className="admin-user-edit-header"><strong>{f.name}</strong></div>
                    <div className="admin-user-edit-fields">
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldCondition')}</label>
                        <input type="number" className="admin-input" value={editing.form.condition}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, condition: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldOverclock')}</label>
                        <input type="number" step="0.01" className="admin-input" value={editing.form.overclock}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, overclock: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldElectricity')}</label>
                        <input type="number" className="admin-input" value={editing.form.electricity_owed}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, electricity_owed: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldStatus')}</label>
                        <select className="admin-input" value={editing.form.status}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, status: e.target.value } })}>
                          <option value="idle">idle</option>
                          <option value="mining">mining</option>
                          <option value="broken">broken</option>
                        </select>
                      </div>
                    </div>
                    <div className="admin-user-edit-actions">
                      <button className="admin-btn admin-btn-primary" disabled={busy} onClick={saveEdit}><Save size={14} /> {t('admin.save')}</button>
                      <button className="admin-btn" disabled={busy} onClick={cancelEdit}><X size={14} /> {t('admin.cancel')}</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="admin-user-info">
                      <div className="uprop-title-row">
                        <strong>{f.name}</strong> <span className="user-role user">{f.status}</span>
                        <button className="admin-btn uprop-expand" onClick={() => setExpandedFarm(expandedFarm === f.id ? null : f.id)}
                          title={t('admin.property.showComponents')}>
                          {expandedFarm === f.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </button>
                      </div>
                      <div className="admin-user-meta">
                        <span>{t('admin.property.fieldCondition')}: {f.condition}%</span>
                        <span>{t('admin.property.fieldOverclock')}: ×{f.overclock}</span>
                        <span>{t('admin.property.fieldElectricity')}: ${f.electricityOwed}</span>
                        {f.houseId && <span className="user-role user">{t('admin.property.inHouse')}</span>}
                      </div>
                      {expandedFarm === f.id && renderComponents(f)}
                    </div>
                    {renderActions('farms', f, 'admin.property.delete', (
                      <button className="admin-btn" title={t('admin.property.dismantle')}
                        onClick={() => setConfirmTarget({ kind: 'farmUninstall', id: f.id, name: f.name })}>
                        <Wrench size={14} />
                      </button>
                    ))}
                  </>
                )}
              </div>
            ))}
          </div>
        )}

        {!loading && tab === 'inventory' && (
          <div className="admin-list">
            {inventory.length === 0 && <p className="empty-state">{t('admin.property.emptyInventory')}</p>}
            {inventory.map(h => (
              <div key={h.id} className="admin-user-item">
                <div className="admin-user-info">
                  <div className="uprop-title-row">
                    <strong>{h.name}</strong>
                    <span className="user-role user">{h.category}</span>
                    {h.farmId && (
                      <span className="user-role admin" title={farmNameById[h.farmId] || h.farmId}>
                        {t('admin.property.installedOn')}: {farmNameById[h.farmId] || '…'}
                      </span>
                    )}
                  </div>
                  <div className="admin-user-meta">
                    <span>{t('admin.property.fieldCondition')}: {h.condition}%</span>
                    {h.purchasePrice != null && <span>${h.purchasePrice}</span>}
                  </div>
                </div>
                <div className="user-actions">
                  {h.farmId && (
                    <button className="admin-btn" title={t('admin.property.hwUninstall')}
                      disabled={busy} onClick={() => doUninstallHw(h)}>
                      <Wrench size={14} />
                    </button>
                  )}
                  <button className="admin-btn admin-btn-danger" title={t('admin.property.delete')}
                    onClick={() => setConfirmTarget({ kind: 'hardware', id: h.id, name: h.name })}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && tab === 'company' && (
          <div className="admin-list">
            {!company && <p className="empty-state">{t('admin.property.emptyCompany')}</p>}
            {company && (
              <>
                <div className="admin-user-item">
                  {editing?.kind === 'company' && editing.id === company.id ? (
                    <div className="admin-user-edit-form">
                      <div className="admin-user-edit-header"><strong>{company.name}</strong></div>
                      <div className="admin-user-edit-fields">
                        <div className="admin-field-group">
                          <label>{t('admin.property.fieldName')}</label>
                          <input type="text" className="admin-input" value={editing.form.name}
                            onChange={e => setEditing({ ...editing, form: { ...editing.form, name: e.target.value } })} />
                        </div>
                        <div className="admin-field-group">
                          <label>{t('admin.property.fieldBudget')}</label>
                          <input type="number" className="admin-input" value={editing.form.budget}
                            onChange={e => setEditing({ ...editing, form: { ...editing.form, budget: e.target.value } })} />
                        </div>
                        <div className="admin-field-checkbox">
                          <label>
                            <input type="checkbox" checked={editing.form.isOpen}
                              onChange={e => setEditing({ ...editing, form: { ...editing.form, isOpen: e.target.checked } })} />
                            {t('admin.property.fieldIsOpen')}
                          </label>
                        </div>
                        <div className="admin-field-checkbox">
                          <label>
                            <input type="checkbox" checked={editing.form.visibleInSearch}
                              onChange={e => setEditing({ ...editing, form: { ...editing.form, visibleInSearch: e.target.checked } })} />
                            {t('admin.property.fieldVisibleInSearch')}
                          </label>
                        </div>
                      </div>
                      <div className="admin-user-edit-actions">
                        <button className="admin-btn admin-btn-primary" disabled={busy} onClick={saveEdit}><Save size={14} /> {t('admin.save')}</button>
                        <button className="admin-btn" disabled={busy} onClick={cancelEdit}><X size={14} /> {t('admin.cancel')}</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="admin-user-info">
                        <div className="uprop-title-row"><strong>{company.name}</strong> <span className={`user-role ${company.isOpen ? 'user' : 'admin'}`}>{company.isOpen ? t('admin.property.open') : t('admin.property.closed')}</span></div>
                        <div className="admin-user-meta">
                          <span>{t('admin.property.fieldBudget')}: ${company.budget}</span>
                          <span>{t('admin.property.fieldMembers')}: {company.memberCount}</span>
                          <span>{t('admin.property.fieldAssets')}: {company.assetCount}</span>
                        </div>
                      </div>
                      {renderActions('company', company)}
                    </>
                  )}
                </div>
                <div className="uprop-members">
                  <h4>{t('admin.property.membersTitle')} ({members.length})</h4>
                  {members.length === 0 && <p className="empty-state">{t('admin.property.noMembers')}</p>}
                  {members.map(m => (
                    <div key={m.userId} className="uprop-member-row">
                      <span className="uprop-member-name">{m.username}</span>
                      <span className="user-role user">{m.role || '—'}</span>
                      <span className="admin-user-meta"><span>${m.salary ?? 0}/h</span></span>
                      <button className="admin-btn admin-btn-danger" title={t('admin.property.kick')}
                        onClick={() => setConfirmTarget({ kind: 'member', id: m.userId, name: m.username, companyId: company.id })}>
                        <UserMinus size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {!loading && tab === 'businesses' && (
          <div className="admin-list">
            {businesses.length === 0 && <p className="empty-state">{t('admin.property.emptyBusinesses')}</p>}
            {businesses.map(b => (
              <div key={b.id} className="admin-user-item">
                {editing?.kind === 'businesses' && editing.id === b.id ? (
                  <div className="admin-user-edit-form">
                    <div className="admin-user-edit-header"><strong>{b.name}</strong></div>
                    <div className="admin-user-edit-fields">
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldName')}</label>
                        <input type="text" className="admin-input" value={editing.form.name}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, name: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldReward')}</label>
                        <input type="number" className="admin-input" value={editing.form.reward}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, reward: e.target.value } })} />
                      </div>
                      <div className="admin-field-group">
                        <label>{t('admin.property.fieldProtectionLevel')}</label>
                        <input type="number" min="0" max="5" className="admin-input" value={editing.form.protection_level}
                          onChange={e => setEditing({ ...editing, form: { ...editing.form, protection_level: e.target.value } })} />
                      </div>
                    </div>
                    <div className="admin-user-edit-actions">
                      <button className="admin-btn admin-btn-primary" disabled={busy} onClick={saveEdit}><Save size={14} /> {t('admin.save')}</button>
                      <button className="admin-btn" disabled={busy} onClick={cancelEdit}><X size={14} /> {t('admin.cancel')}</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="admin-user-info">
                      <div className="uprop-title-row"><strong>{b.name}</strong> <span className="user-role user">Lv.{b.protectionLevel}</span></div>
                      <div className="admin-user-meta">
                        <span>{t('admin.property.fieldReward')}: {b.reward}</span>
                      </div>
                    </div>
                    {renderActions('businesses', b, 'admin.property.vacate')}
                  </>
                )}
              </div>
            ))}
          </div>
        )}

        {transferring && (
          <div className="modal-overlay" onClick={() => setTransferring(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <button className="crypto-modal-close" onClick={() => setTransferring(null)}><X size={18} /></button>
              <h3>{t('admin.property.transferTitle')}: {transferring.name}</h3>
              <div className="admin-field-group">
                <label>{t('admin.property.transferToUsername')}</label>
                <input type="text" className="admin-input" value={transferTo} autoFocus
                  onChange={e => setTransferTo(e.target.value)} placeholder={t('admin.property.transferToPlaceholder')} />
              </div>
              <div className="modal-buttons">
                <button className="admin-btn admin-btn-primary" disabled={busy || !transferTo.trim()} onClick={submitTransfer}>
                  <ArrowLeftRight size={14} /> {t('admin.property.transferConfirm')}
                </button>
                <button className="admin-btn" disabled={busy} onClick={() => setTransferring(null)}>{t('admin.cancel')}</button>
              </div>
            </div>
          </div>
        )}

        <ConfirmDialog
          open={!!confirmTarget}
          title={t('admin.property.deleteConfirmTitle')}
          message={confirmTarget
            ? (confirmTarget.kind === 'farmUninstall'
                ? t('admin.property.dismantleConfirm', { name: confirmTarget.name })
                : t('admin.property.deleteConfirmMessage', { name: confirmTarget.name }))
            : ''}
          danger
          busy={busy}
          onConfirm={doDelete}
          onCancel={() => setConfirmTarget(null)}
        />
      </div>
    </div>
  )
}

export default UserPropertyModal
