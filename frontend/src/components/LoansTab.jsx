import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Search, Filter, ChevronDown, ArrowUpDown, ArrowUp, ArrowDown, X, DollarSign, Handshake } from 'lucide-react'
import { fetchMyP2PLoans, fetchP2POffers, createP2POffer, acceptP2POffer, repayP2PLoan } from '../services/api'
import { formatMoney } from './TransactionsPanel'
import { toast } from './Toast'
import BankModal from './BankModal'

const EMPTY = { side: 'lend', amount: '', termDays: '', dailyRate: '' }

function LoansTab() {
  const { t } = useTranslation()
  const [offers, setOffers] = useState([])
  const [mine, setMine] = useState([])
  const [loading, setLoading] = useState(true)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [tab, setTab] = useState('all')
  const [search, setSearch] = useState('')
  const [minAmount, setMinAmount] = useState('')
  const [maxAmount, setMaxAmount] = useState('')
  const [minRate, setMinRate] = useState('')
  const [maxRate, setMaxRate] = useState('')
  const [minDays, setMinDays] = useState('')
  const [maxDays, setMaxDays] = useState('')
  const [sort, setSort] = useState('default')
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)

  const load = useCallback(async () => {
    setLoading(true)
    const [open, own] = await Promise.all([
      fetchP2POffers().then(r => r.offers).catch(() => []),
      fetchMyP2PLoans().then(r => r.loans).catch(() => []),
    ])
    setOffers(open); setMine(own); setLoading(false)
  }, [])
  useEffect(() => { load() }, [load])

  const action = async (fn, message) => {
    try { await fn(); toast(message, 'success'); load() }
    catch (err) { toast(err.message || t('bank.errorDefault', 'Ошибка'), 'error') }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const min = minAmount === '' ? -Infinity : Number(minAmount)
    const max = maxAmount === '' ? Infinity : Number(maxAmount)
    const minR = minRate === '' ? -Infinity : Number(minRate) / 100
    const maxR = maxRate === '' ? Infinity : Number(maxRate) / 100
    const minD = minDays === '' ? -Infinity : Number(minDays)
    const maxD = maxDays === '' ? Infinity : Number(maxDays)
    return offers.filter(o => {
      if (tab !== 'all' && o.side !== tab) return false
      if (q && !String(o.ownerName || '').toLowerCase().includes(q)) return false
      return o.amount >= min && o.amount <= max && o.dailyRate >= minR && o.dailyRate <= maxR && o.termDays >= minD && o.termDays <= maxD
    }).sort((a, b) => sort === 'amount_asc' ? a.amount - b.amount : sort === 'amount_desc' ? b.amount - a.amount : 0)
  }, [offers, tab, search, minAmount, maxAmount, minRate, maxRate, minDays, maxDays, sort])

  const submit = async e => {
    e.preventDefault()
    const amount = Number(form.amount); const termDays = Number(form.termDays); const dailyRate = Number(form.dailyRate) / 100
    if (!(amount > 0) || !(termDays >= 2 && termDays <= 21) || !(dailyRate >= 0)) { toast(t('bank.invalidAmount', 'Проверьте параметры займа'), 'error'); return }
    await action(() => createP2POffer({ side: form.side, amount, termDays, dailyRate }), t('bank.offerCreated', 'Объявление создано'))
    setForm(EMPTY); setCreateOpen(false)
  }

  return <div className="centralmarket-tab loans-page">
    <div className="centralmarket-header">
      <div><h2 className="tab-title">{t('nav.loans', 'Займы')}</h2><p className="centralmarket-subtitle">{t('loans.subtitle', 'Займы между игроками на удобный срок')}</p></div>
      <button type="button" className="centralmarket-create-btn" onClick={() => setCreateOpen(true)}><Plus size={16} /> {t('loans.create', 'Выставить своё предложение')}</button>
    </div>
    <div className="centralmarket-toolbar">
      <div className="centralmarket-toolbar-left">
        <button type="button" className={`centralmarket-filters-toggle ${filtersOpen ? 'is-open' : ''}`} onClick={() => setFiltersOpen(v => !v)}><Filter size={14} /><ChevronDown size={14} className={filtersOpen ? 'rot' : ''} /></button>
        <button type="button" className={`centralmarket-sort-btn sort-${sort}`} onClick={() => setSort(v => v === 'default' ? 'amount_asc' : v === 'amount_asc' ? 'amount_desc' : 'default')}>
          {sort === 'default' ? <><ArrowUpDown size={14} /><span>{t('common.sort', 'Сортировка')}</span></> : sort === 'amount_asc' ? <><ArrowUp size={14} /><span>{t('loans.sortAsc', 'Сумма ↑')}</span></> : <><ArrowDown size={14} /><span>{t('loans.sortDesc', 'Сумма ↓')}</span></>}
        </button>
      </div>
      <div className="centralmarket-toolbar-right"><div className="tx-search centralmarket-search"><Search size={16} className="tx-search-icon" /><input value={search} onChange={e => setSearch(e.target.value)} placeholder={t('loans.search', 'Поиск по имени')} /></div></div>
    </div>
    {filtersOpen && <div className="centralmarket-filters"><div className="centralmarket-filters-body">
      <div className="centralmarket-filter"><span className="centralmarket-filter-label"><Filter size={12} /> {t('loans.type', 'Тип предложения')}</span><div className="centralmarket-cat-pills">
        {[['all', 'Все'], ['lend', 'Дать в займ'], ['borrow', 'Взять в займ']].map(([id, label]) => <button key={id} type="button" className={`tx-pill ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</button>)}
      </div></div>
      <div className="centralmarket-filter centralmarket-filter--numeric"><span className="centralmarket-filter-label"><DollarSign size={12} /> Цена, от–до</span><div className="centralmarket-num-pair"><input type="number" min="0" value={minAmount} onChange={e => setMinAmount(e.target.value)} placeholder="От" className="centralmarket-num-input" /><span className="centralmarket-num-dash">—</span><input type="number" min="0" value={maxAmount} onChange={e => setMaxAmount(e.target.value)} placeholder="До" className="centralmarket-num-input" /></div></div>
      <div className="centralmarket-filter centralmarket-filter--numeric"><span className="centralmarket-filter-label">Процент, от–до</span><div className="centralmarket-num-pair"><input type="number" min="0" value={minRate} onChange={e => setMinRate(e.target.value)} placeholder="От" className="centralmarket-num-input" /><span className="centralmarket-num-dash">—</span><input type="number" min="0" value={maxRate} onChange={e => setMaxRate(e.target.value)} placeholder="До" className="centralmarket-num-input" /></div></div>
      <div className="centralmarket-filter centralmarket-filter--numeric"><span className="centralmarket-filter-label">Количество дней, от–до</span><div className="centralmarket-num-pair"><input type="number" min="2" value={minDays} onChange={e => setMinDays(e.target.value)} placeholder="От" className="centralmarket-num-input" /><span className="centralmarket-num-dash">—</span><input type="number" min="2" value={maxDays} onChange={e => setMaxDays(e.target.value)} placeholder="До" className="centralmarket-num-input" /></div></div>
      {(tab !== 'all' || minAmount || maxAmount || minRate || maxRate || minDays || maxDays) && <button type="button" className="centralmarket-reset" onClick={() => { setTab('all'); setMinAmount(''); setMaxAmount(''); setMinRate(''); setMaxRate(''); setMinDays(''); setMaxDays('') }}><X size={14} /> {t('centralmarket.resetFilters', 'Сбросить')}</button>}
    </div></div>}
    <div className="centralmarket-lots"><div className="centralmarket-lots-header"><span>{t('loans.offersCount', 'Предложений: {{count}}', { count: filtered.length })}</span></div>
      {loading || filtered.length === 0 ? <div className="centralmarket-empty"><div className="centralmarket-empty-icon">🤝</div><h3 className="centralmarket-empty-title">{loading ? t('bank.loading', 'Загрузка…') : t('bank.noOffers', 'Предложений нет')}</h3></div> : <div className="centralmarket-lots-grid">{filtered.map(o => <div key={o.id} className="centralmarket-lot"><div className="centralmarket-lot-icon"><Handshake size={28} /></div><div className="centralmarket-lot-main"><b className="centralmarket-lot-name">{formatMoney(o.amount)} $</b><span className="centralmarket-lot-meta">{o.side === 'lend' ? 'Дает' : 'Берет'} · {o.termDays} суток · {(o.dailyRate * 100).toFixed(2)}%/сут · {o.ownerName}</span><button type="button" className="centralmarket-lot-btn centralmarket-lot-btn--buy" onClick={() => action(() => acceptP2POffer(o.id), t('bank.loanAccepted', 'Заём принят'))}>{t('bank.accept', 'Принять')}</button></div></div>)}</div>}
    </div>
    <div className="centralmarket-lots"><div className="centralmarket-lots-header"><span>{t('bank.myLoans', 'Мои займы')}</span></div><div className="centralmarket-lots-grid">{mine.map(l => <div key={l.id} className="centralmarket-lot"><div className="centralmarket-lot-icon"><Handshake size={28} /></div><div className="centralmarket-lot-main"><b className="centralmarket-lot-name">{formatMoney(l.amount)} $</b><span className="centralmarket-lot-meta">{l.myRole === 'borrower' ? 'Ваш долг' : 'Выдано'} · {l.status}</span>{l.myRole === 'borrower' && <button type="button" className="centralmarket-lot-btn centralmarket-lot-btn--buy" onClick={() => action(() => repayP2PLoan(l.id), t('bank.loanRepaidEarly', 'Заём погашен досрочно'))}>{t('bank.repayEarly', 'Погасить')}</button>}</div></div>)}</div></div>
    {createOpen && <BankModal title={t('loans.create', 'Выставить своё предложение')} onClose={() => setCreateOpen(false)}><form className="centralmarket-modal-form" onSubmit={submit}><label className="centralmarket-field"><span>{t('bank.type', 'Тип')}</span><select value={form.side} onChange={e => setForm({ ...form, side: e.target.value })}><option value="lend">Дать в займ</option><option value="borrow">Взять в займ</option></select></label><label className="centralmarket-field"><span>{t('bank.amount', 'Сумма')}</span><input type="number" min="0.01" step="0.01" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></label><label className="centralmarket-field"><span>Срок, суток (2–21)</span><input type="number" min="2" max="21" value={form.termDays} onChange={e => setForm({ ...form, termDays: e.target.value })} /></label><label className="centralmarket-field"><span>Процент в сутки, %</span><input type="number" min="0" max="50" step="0.01" value={form.dailyRate} onChange={e => setForm({ ...form, dailyRate: e.target.value })} /></label><button type="submit" className="centralmarket-create-btn"><Plus size={16} /> Разместить</button></form></BankModal>}
  </div>
}
export default LoansTab
