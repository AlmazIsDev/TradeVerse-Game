import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  createTransfer, fetchWeeklyAnalytics, fetchCryptoAccount,
  fetchUtilityAccount, utilityTopUp,
  fetchCreditOverview, takeLoan, repayLoan, openDeposit, closeDeposit,
  fetchP2POffers, fetchMyP2PLoans, createP2POffer, acceptP2POffer, repayP2PLoan,
  fetchBankAuctions, bidBankAuction, donateToBank,
} from '../services/api'
import TransactionsPanel, { formatMoney, formatCompact } from './TransactionsPanel'
import AnalyticsChart from './AnalyticsChart'
import BankModal from './BankModal'
import { toast } from './Toast'
import {
  Send, User, DollarSign, MessageSquare, TrendingUp, TrendingDown, Wallet,
  CreditCard, Copy, Coins, BarChart3, Landmark, PiggyBank, Handshake, Zap, ArrowRight, Heart,
} from 'lucide-react'

const EMPTY_OFFER = { side: 'lend', amount: '', termDays: '', dailyRate: '' }

// Перемешивание Фишера–Йетса (копия массива)
function shuffled(arr) {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

function BankTab({ balance = 0, onBalanceChange }) {
  const { t } = useTranslation()
  const transferRef = useRef(null)
  const [modal, setModal] = useState(null) // null | 'credit' | 'deposit' | 'debt'
  const [recipient, setRecipient] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localBalance, setLocalBalance] = useState(balance)
  const [refreshKey, setRefreshKey] = useState(0)
  const [analytics, setAnalytics] = useState(null)
  const [crypto, setCrypto] = useState(null)
  const [utility, setUtility] = useState(null)
  const [credit, setCredit] = useState(null)
  const [p2pOffers, setP2pOffers] = useState([])
  const [p2pMine, setP2pMine] = useState([])
  const [auctions, setAuctions] = useState([])
  const [bidInputs, setBidInputs] = useState({})
  const [donateAmount, setDonateAmount] = useState('')
  const [utilityAmount, setUtilityAmount] = useState('')
  const [loanAmount, setLoanAmount] = useState('')
  const [depositAmount, setDepositAmount] = useState('')
  const [offerForm, setOfferForm] = useState(EMPTY_OFFER)
  // Номер карты синхронизируется в localStorage хедером (Header.jsx).
  // Читаем на каждый рендер: так банк сразу подхватывает смену номера и
  // переключение видимости в шапке (card_visible), не рисуя скрытую карту.
  let storedUser = null
  try { storedUser = JSON.parse(localStorage.getItem('tradeverse_user')) } catch { /* ignore */ }
  const cardNumber = storedUser?.card_number || null
  const cardVisible = storedUser?.card_visible !== false
  const displayCard = cardNumber
    ? (cardVisible ? cardNumber : '****-****-****-' + cardNumber.slice(-5))
    : null
  const copyCard = useCallback(async () => {
    if (!cardNumber) return
    try {
      await navigator.clipboard.writeText(cardNumber)
      toast(t('header.cardCopied', 'Номер карты скопирован'))
    } catch { /* clipboard недоступен */ }
  }, [cardNumber, t])

  // 3 случайных открытых объявления; перевыбираются при обновлении списка
  const featuredOffers = useMemo(() => shuffled(p2pOffers).slice(0, 3), [p2pOffers])

  useEffect(() => { setLocalBalance(balance) }, [balance])

  const loadSummary = useCallback(async () => {
    try {
      const [a, c, u, cr, offers, mine, auc] = await Promise.all([
        fetchWeeklyAnalytics().catch(() => null),
        fetchCryptoAccount().catch(() => null),
        fetchUtilityAccount().catch(() => null),
        fetchCreditOverview().catch(() => null),
        fetchP2POffers().then(r => r.offers).catch(() => []),
        fetchMyP2PLoans().then(r => r.loans).catch(() => []),
        fetchBankAuctions().then(r => r.auctions).catch(() => []),
      ])
      setAnalytics(a)
      setCrypto(c)
      setUtility(u)
      setCredit(cr)
      setP2pOffers(offers)
      setP2pMine(mine)
      setAuctions(auc)
    } catch { /* ignore */ }
  }, [])

  const runBankAction = async (fn, successText) => {
    try {
      const result = await fn()
      if (result?.balance !== undefined) {
        setLocalBalance(result.balance)
        onBalanceChange?.(result.balance)
      }
      toast(successText, 'success')
      setRefreshKey(k => k + 1)
      return result
    } catch (err) {
      toast(err.message || t('bank.errorDefault', 'Ошибка'), 'error')
      return null
    }
  }

  useEffect(() => { loadSummary() }, [loadSummary, refreshKey])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const parsedAmount = parseFloat(amount)
    if (!recipient.trim()) { toast(t('bank.recipientNotFound'), 'error'); return }
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) { toast(t('bank.invalidAmount'), 'error'); return }
    if (parsedAmount > localBalance) { toast(t('bank.insufficientFunds'), 'error'); return }

    setSubmitting(true)
    try {
      const result = await createTransfer({ recipient: recipient.trim(), amount: parsedAmount, note: note.trim() || undefined })
      toast(t('bank.transferSuccess', { amount: formatMoney(result.amount), recipient: result.recipient }))
      setLocalBalance(result.balance)
      onBalanceChange?.(result.balance)
      setRecipient(''); setAmount(''); setNote('')
      setRefreshKey(k => k + 1)
    } catch (err) {
      const msg = err.message || ''
      let text = msg
      if (msg.includes('самому себе')) text = t('bank.selfTransfer')
      else if (msg.includes('не найден')) text = t('bank.recipientNotFound')
      else if (msg.includes('Недостаточно')) text = t('bank.insufficientFunds')
      toast(text, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCreateOffer = async (e) => {
    e.preventDefault()
    const amt = parseFloat(offerForm.amount)
    const termDays = parseInt(offerForm.termDays, 10)
    const dailyRate = parseFloat(offerForm.dailyRate) / 100
    if (!Number.isFinite(amt) || amt <= 0) { toast(t('bank.invalidAmount'), 'error'); return }
    if (!Number.isFinite(termDays) || termDays < 7 || termDays > 21) { toast(t('bank.termRange', 'Срок от 7 до 21 суток'), 'error'); return }
    if (!Number.isFinite(dailyRate) || dailyRate < 0) { toast(t('bank.invalidRate', 'Некорректный процент'), 'error'); return }
    const res = await runBankAction(
      () => createP2POffer({ side: offerForm.side, amount: amt, termDays, dailyRate }),
      t('bank.offerCreated', 'Объявление создано')
    )
    if (res) setOfferForm(EMPTY_OFFER)
  }

  const renderOffer = (o, { compact = false } = {}) => (
    <div key={o.id} className={`bank-debt-card${compact ? ' compact' : ''}`}>
      <div className="bank-debt-info">
        <span className={`bank-debt-side ${o.side}`}>{o.side === 'lend' ? t('bank.sideLend', 'Дает') : t('bank.sideBorrow', 'Берет')}</span>
        <b>{formatMoney(o.amount)} $</b>
        <span className="bank-debt-meta">{o.termDays} {t('bank.daysShort', 'сут')} · {(o.dailyRate * 100).toFixed(2)}%{t('bank.perDay', '/сут')} · {o.ownerName}</span>
      </div>
      <button type="button" className="transfer-submit" onClick={() => runBankAction(() => acceptP2POffer(o.id), t('bank.loanAccepted', 'Заём принят'))}>
        {t('bank.accept', 'Принять')}
      </button>
    </div>
  )

  return (
    <div className="bank-page">
      <h2 className="tab-title">{t('bank.title')}</h2>

      {/* ── Верх: баланс, карта, быстрые действия ── */}
      <div className="bank-hero-card">
        <div className="bank-hero-top">
          <span className="bank-hero-label"><Wallet size={15} /> {t('bank.mainAccount')}</span>
          {analytics && (
            <span className={`bank-hero-net ${analytics.net >= 0 ? 'up' : 'down'}`}>
              {analytics.net >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              {analytics.net >= 0 ? '+' : ''}{formatMoney(analytics.net)} $ / {t('common.week')}
            </span>
          )}
        </div>
        <div className="bank-hero-balance" title={`${formatMoney(localBalance)} $`}>{formatCompact(localBalance)} <span>$</span></div>
        {displayCard && (
          <button type="button" className="bank-hero-cardnum"
            title={t('header.copyCard', 'Скопировать номер карты')}
            onClick={copyCard}>
            <CreditCard size={15} />
            <span>{displayCard}</span>
            <Copy size={13} className="bank-hero-copyicon" />
          </button>
        )}
      </div>

      <div className="bank-quick">
        <button type="button" className="bank-quick-btn" onClick={() => transferRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
          <span className="bank-quick-icon"><Send size={18} /></span>
          <span>{t('bank.transfer', 'Перевод')}</span>
        </button>
        <button type="button" className="bank-quick-btn" onClick={() => setModal('credit')}>
          <span className="bank-quick-icon"><Landmark size={18} /></span>
          <span>{t('bank.quickCredit', 'Кредит')}</span>
        </button>
        <button type="button" className="bank-quick-btn" onClick={() => setModal('deposit')}>
          <span className="bank-quick-icon"><PiggyBank size={18} /></span>
          <span>{t('bank.quickDeposit', 'Депозит')}</span>
        </button>
        <button type="button" className="bank-quick-btn" onClick={() => setModal('debt')}>
          <span className="bank-quick-icon"><Handshake size={18} /></span>
          <span>{t('bank.quickDebt', 'Долг')}</span>
        </button>
        <button type="button" className="bank-quick-btn" onClick={() => setModal('donate')}>
          <span className="bank-quick-icon"><Heart size={18} /></span>
          <span>{t('bank.quickDonate', 'Пожертвовать')}</span>
        </button>
      </div>

      {/* ── Лента: статистика ── */}
      <div className="bank-mini-stats">
        <div className="bank-mini income"><TrendingUp size={18} /><div><span>{t('account.earned')}</span><b>+{formatMoney(analytics?.income)} $</b></div></div>
        <div className="bank-mini expense"><TrendingDown size={18} /><div><span>{t('account.spent')}</span><b>−{formatMoney(analytics?.expense)} $</b></div></div>
        <div className="bank-mini ops"><BarChart3 size={18} /><div><span>{t('account.operations')}</span><b>{analytics?.operations ?? 0}</b></div></div>
      </div>

      {/* ── Перевод (слева) и пополнение электричества (справа) ── */}
      <div className="bank-two-col">
      <div className="bank-section bank-transfer-card" ref={transferRef}>
        <form className="transfer-form" onSubmit={handleSubmit}>
          <h3 className="transfer-form-title">{t('bank.transferTitle')}</h3>
          <div className="bank-stack-form">
            <label className="transfer-field">
              <span><User size={14} /> {t('bank.recipient')}</span>
              <input type="text" value={recipient} onChange={e => setRecipient(e.target.value)} placeholder={t('bank.recipientPlaceholder')} autoComplete="off" />
            </label>
            <label className="transfer-field">
              <span><DollarSign size={14} /> {t('bank.amount')}</span>
              <input type="number" min="0.01" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
            </label>
            <label className="transfer-field">
              <span><MessageSquare size={14} /> {t('bank.note')}</span>
              <input type="text" value={note} onChange={e => setNote(e.target.value)} placeholder={t('bank.notePlaceholder')} maxLength={120} />
            </label>
            <button type="submit" className="transfer-submit bank-stack-submit" disabled={submitting}>
              {submitting ? t('bank.processing') : <><Send size={16} /> {t('bank.sendMoney')}</>}
            </button>
          </div>
        </form>
      </div>

      {/* ── Электричество: пополнение счёта ── */}
      <div className="bank-utility-card bank-section">
        <div className="transfer-balance-card">
          <span className="transfer-balance-label">{t('bank.utilityAccount', 'Счёт «Электричество»')}</span>
          <span className="transfer-balance-value">{formatMoney(utility?.utilityBalance)} $</span>
        </div>
        <form className="transfer-form" onSubmit={async e => {
          e.preventDefault()
          const amt = parseFloat(utilityAmount)
          if (!Number.isFinite(amt) || amt <= 0) { toast(t('bank.invalidAmount'), 'error'); return }
          const res = await runBankAction(() => utilityTopUp(amt), t('bank.utilityToppedUp', 'Счёт «Электричество» пополнен'))
          if (res) setUtilityAmount('')
        }}>
          <h3 className="transfer-form-title">{t('bank.utilityTopUpTitle', 'Пополнить с основного счёта')}</h3>
          <div className="bank-stack-form">
            <label className="transfer-field">
              <span><DollarSign size={14} /> {t('bank.amount')}</span>
              <input type="number" min="0.01" step="0.01" value={utilityAmount} onChange={e => setUtilityAmount(e.target.value)} placeholder="0.00" />
            </label>
            <button type="submit" className="transfer-submit bank-stack-submit">
              <Zap size={16} /> {t('bank.utilityTopUp', 'Пополнить')}
            </button>
          </div>
        </form>
      </div>
      </div>

      {/* ── Изъятое имущество: аукционы банка ── */}
      <div className="bank-chart-card bank-section">
        <div className="bank-section-head">
          <h3>{t('bank.seizedTitle', 'Изъятое имущество')}</h3>
        </div>
        {auctions.length === 0 && <p className="bank-empty">{t('bank.noAuctions', 'Аукционов нет')}</p>}
        <div className="bank-debt-list">
          {auctions.map(a => (
            <div key={a.id} className="bank-debt-card">
              <div className="bank-debt-info">
                <b>{a.name}{a.level > 1 ? ` (ур. ${a.level})` : ''}</b>
                <span className="bank-debt-meta">
                  {a.hasBids ? t('bank.leaderName', 'Лидер: {{name}}', { name: a.topBidderName }) : t('bank.noBids', 'Ставок нет')} · {formatMoney(a.currentPrice)} $
                  {a.isBorrower ? ` · ${t('bank.yourDebt', 'ваш долг')}` : ''}
                </span>
              </div>
              {!a.isBorrower && !a.isMine && (
                <form className="bank-bid-form" onSubmit={e => {
                  e.preventDefault()
                  const amt = parseFloat(bidInputs[a.id])
                  if (!Number.isFinite(amt)) { toast(t('bank.invalidAmount'), 'error'); return }
                  runBankAction(() => bidBankAuction(a.id, amt), t('bank.bidAccepted', 'Ставка принята'))
                    .then(res => { if (res) setBidInputs(s => ({ ...s, [a.id]: '' })) })
                }}>
                  <input type="number" step="0.01" min={a.minNextBid}
                    placeholder={t('bank.bidFrom', 'от {{amount}}', { amount: formatMoney(a.minNextBid) })}
                    value={bidInputs[a.id] ?? ''}
                    onChange={e => setBidInputs(s => ({ ...s, [a.id]: e.target.value }))} />
                  <button type="submit" className="transfer-submit">{t('bank.bid', 'Ставка')}</button>
                </form>
              )}
              {a.isMine && <span className="bank-debt-meta">{t('bank.youLead', 'Вы лидируете')}</span>}
            </div>
          ))}
        </div>
      </div>

      {/* ── Долги игроков: 3 случайных объявления ── */}
      <div className="bank-chart-card bank-section">
        <div className="bank-section-head">
          <h3>{t('bank.debtsTitle', 'Долги игроков')}</h3>
          <button type="button" className="bank-link-btn" onClick={() => setModal('debt')}>
            {t('bank.showMore', 'Смотреть больше')} <ArrowRight size={13} />
          </button>
        </div>
        {featuredOffers.length === 0 && <p className="bank-empty">{t('bank.noOffers', 'Объявлений нет')}</p>}
        <div className="bank-debt-list">
          {featuredOffers.map(o => renderOffer(o, { compact: true }))}
        </div>
      </div>

      {/* ── Аналитика ── */}
      <div className="bank-chart-card bank-section">
        <h3>{t('account.weeklyAnalytics')}</h3>
        <AnalyticsChart days={analytics?.days || []} />
      </div>

      {/* ── История операций ── */}
      <div className="bank-section">
        <TransactionsPanel refreshKey={refreshKey} />
      </div>

      {/* ── Модалка: Кредит ── */}
      {modal === 'credit' && (
        <BankModal title={t('bank.quickCredit', 'Кредит')} onClose={() => setModal(null)}>
          {!credit ? <p className="bank-empty">{t('bank.loading', 'Загрузка…')}</p> : (
            <>
              <div className="bank-stat-row">
                <div className="bank-stat">
                  <span>{t('bank.loanLimit', 'Лимит кредита')}</span>
                  <b>{formatMoney(credit.loanLimit)} $</b>
                </div>
                <div className="bank-stat">
                  <span>{t('bank.rate', 'Ставка')}</span>
                  <b>{(credit.loanRate * 100).toFixed(2)}%</b>
                </div>
                <div className="bank-stat">
                  <span>{t('bank.debt', 'Долг')}</span>
                  <b>{formatMoney(credit.debt)} $</b>
                </div>
                <div className="bank-stat">
                  <span>{t('bank.bankBalance', 'Баланс банка')}</span>
                  <b>{formatMoney(credit.stateBalance)} $</b>
                </div>
              </div>
              <form className="transfer-form" onSubmit={async e => {
                e.preventDefault()
                const amt = parseFloat(loanAmount)
                if (!Number.isFinite(amt) || amt <= 0) { toast(t('bank.invalidAmount'), 'error'); return }
                const res = await runBankAction(() => takeLoan(amt), t('bank.loanIssued', 'Кредит выдан'))
                if (res) setLoanAmount('')
              }}>
                <h3 className="transfer-form-title">{t('bank.takeLoanTitle', 'Взять кредит')}</h3>
                <label className="transfer-field">
                  <span><DollarSign size={14} /> {t('bank.amount')}</span>
                  <input type="number" min="0.01" step="0.01" value={loanAmount} onChange={e => setLoanAmount(e.target.value)} placeholder="0.00" />
                </label>
                <button type="submit" className="transfer-submit"><Landmark size={16} /> {t('bank.takeLoan', 'Взять кредит')}</button>
              </form>
              <h3 className="bank-subtitle">{t('bank.activeLoans', 'Активные кредиты')}</h3>
              {credit.loans.length === 0 && <p className="bank-empty">{t('bank.noActiveLoans', 'Нет активных кредитов')}</p>}
              {credit.loans.map(l => (
                <div key={l.id} className="bank-debt-card compact">
                  <div className="bank-debt-info">
                    <b>{formatMoney(l.amount)} $ + {formatMoney(l.interest)} $</b>
                  </div>
                  <button type="button" className="transfer-submit" onClick={() => runBankAction(() => repayLoan(l.id), t('bank.loanRepaid', 'Кредит погашен'))}>{t('bank.repay', 'Погасить')}</button>
                </div>
              ))}
            </>
          )}
        </BankModal>
      )}

      {/* ── Модалка: Депозит ── */}
      {modal === 'deposit' && (
        <BankModal title={t('bank.quickDeposit', 'Депозит')} onClose={() => setModal(null)}>
          {!credit ? <p className="bank-empty">{t('bank.loading', 'Загрузка…')}</p> : (
            <>
              <div className="bank-stat-row">
                <div className="bank-stat">
                  <span>{t('bank.dailyRate', 'Ставка в сутки')}</span>
                  <b>{(credit.depositRate ?? 0) * 100}%</b>
                </div>
              </div>
              <form className="transfer-form" onSubmit={async e => {
                e.preventDefault()
                const amt = parseFloat(depositAmount)
                if (!Number.isFinite(amt) || amt <= 0) { toast(t('bank.invalidAmount'), 'error'); return }
                const res = await runBankAction(() => openDeposit(amt), t('bank.depositOpened', 'Депозит открыт'))
                if (res) setDepositAmount('')
              }}>
                <h3 className="transfer-form-title">{t('bank.openDepositTitle', 'Открыть депозит')}</h3>
                <label className="transfer-field">
                  <span><DollarSign size={14} /> {t('bank.amount')}</span>
                  <input type="number" min="0.01" step="0.01" value={depositAmount} onChange={e => setDepositAmount(e.target.value)} placeholder="0.00" />
                </label>
                <button type="submit" className="transfer-submit"><PiggyBank size={16} /> {t('bank.open', 'Открыть')}</button>
              </form>
              <h3 className="bank-subtitle">{t('bank.myDeposits', 'Мои депозиты')}</h3>
              {credit.deposits.length === 0 && <p className="bank-empty">{t('bank.noDeposits', 'Нет открытых депозитов')}</p>}
              {credit.deposits.map(d => (
                <div key={d.id} className="bank-debt-card compact">
                  <div className="bank-debt-info">
                    <b>{formatMoney(d.amount)} $</b>
                    <span className="bank-debt-meta">{(d.rate * 100).toFixed(2)}%{t('bank.perDay', '/сут')}</span>
                  </div>
                  <button type="button" className="transfer-submit" onClick={() => runBankAction(() => closeDeposit(d.id), t('bank.depositClosed', 'Депозит закрыт'))}>{t('bank.close', 'Закрыть')}</button>
                </div>
              ))}
            </>
          )}
        </BankModal>
      )}

      {/* ── Модалка: Пожертвование банку ── */}
      {modal === 'donate' && (
        <BankModal title={t('bank.donateTitle', 'Пожертвовать банку')} onClose={() => setModal(null)}>
          <p className="bank-empty">{t('bank.donateHint', 'Деньги пойдут на счёт банка государства и откроют достижения.')}</p>
          <form className="transfer-form" onSubmit={async e => {
            e.preventDefault()
            const amt = parseFloat(donateAmount)
            if (!Number.isFinite(amt) || amt <= 0) { toast(t('bank.invalidAmount'), 'error'); return }
            const res = await runBankAction(() => donateToBank(amt), t('bank.donateThanks', 'Спасибо за пожертвование!'))
            if (res) setDonateAmount('')
          }}>
            <label className="transfer-field">
              <span><DollarSign size={14} /> {t('bank.amount')}</span>
              <input type="number" min="0.01" step="0.01" value={donateAmount} onChange={e => setDonateAmount(e.target.value)} placeholder="0.00" />
            </label>
            <button type="submit" className="transfer-submit"><Heart size={16} /> {t('bank.donate', 'Пожертвовать')}</button>
          </form>
        </BankModal>
      )}

      {/* ── Модалка: Долги игроков (P2P) ── */}
      {modal === 'debt' && (
        <BankModal title={t('bank.debtsTitle', 'Долги игроков')} wide onClose={() => setModal(null)}>
          <h3 className="bank-subtitle">{t('bank.openOffers', 'Открытые объявления')}</h3>
          {p2pOffers.length === 0 && <p className="bank-empty">{t('bank.noOffers', 'Объявлений нет')}</p>}
          <div className="bank-debt-list">
            {p2pOffers.map(o => renderOffer(o))}
          </div>

          <h3 className="bank-subtitle">{t('bank.myLoans', 'Мои займы')}</h3>
          {p2pMine.length === 0 && <p className="bank-empty">{t('bank.noLoans', 'Займов нет')}</p>}
          <div className="bank-debt-list">
            {p2pMine.map(l => (
              <div key={l.id} className="bank-debt-card">
                <div className="bank-debt-info">
                  <b>{formatMoney(l.amount)} $</b>
                  <span className="bank-debt-meta">{l.myRole === 'borrower' ? t('bank.roleBorrower', 'долг') : t('bank.roleLender', 'выдано')} · {l.status === 'frozen' ? t('bank.statusFrozen', 'имущество заморожено') : t('bank.statusActive', 'активен')}</span>
                </div>
                {l.myRole === 'borrower' && (
                  <button type="button" className="transfer-submit" onClick={() => runBankAction(() => repayP2PLoan(l.id), t('bank.loanRepaidEarly', 'Заём погашен досрочно'))}>
                    {t('bank.repayEarly', 'Погасить досрочно')}
                  </button>
                )}
              </div>
            ))}
          </div>

          <form className="transfer-form bank-offer-form" onSubmit={handleCreateOffer}>
            <h3 className="transfer-form-title">{t('bank.offerTitle', 'Объявление о займе')}</h3>
            <label className="transfer-field">
              <span>{t('bank.type', 'Тип')}</span>
              <select value={offerForm.side} onChange={e => setOfferForm({ ...offerForm, side: e.target.value })}>
                <option value="lend">{t('bank.offerLend', 'Дать в займ')}</option>
                <option value="borrow">{t('bank.offerBorrow', 'Взять в займ')}</option>
              </select>
            </label>
            <label className="transfer-field">
              <span><DollarSign size={14} /> {t('bank.amount')}</span>
              <input type="number" min="0.01" step="0.01" value={offerForm.amount} onChange={e => setOfferForm({ ...offerForm, amount: e.target.value })} />
            </label>
            <label className="transfer-field">
              <span>{t('bank.termLabel', 'Срок, суток (7–21)')}</span>
              <input type="number" min="7" max="21" value={offerForm.termDays} onChange={e => setOfferForm({ ...offerForm, termDays: e.target.value })} />
            </label>
            <label className="transfer-field">
              <span>{t('bank.rateLabel', 'Процент в сутки, %')}</span>
              <input type="number" min="0" max="50" step="0.01" value={offerForm.dailyRate} onChange={e => setOfferForm({ ...offerForm, dailyRate: e.target.value })} />
            </label>
            <button type="submit" className="transfer-submit"><Handshake size={16} /> {t('bank.place', 'Разместить')}</button>
          </form>
        </BankModal>
      )}
    </div>
  )
}

export default BankTab
