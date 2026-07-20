# MiningTab + AdminPanel UI/UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the mining component installer (cart-style GPU/fan install) and refresh the admin panel's transactions, users, and stocks views for compactness and clarity.

**Architecture:** Pure frontend React changes. MiningTab replaces the select+number-input with a grouped "cart" list per model. AdminPanel gets a filterable transaction table, a side-panel user editor, and light stock polish. No backend or API changes. CSS added to existing `economy.css` (mining) and `App.css` (admin).

**Tech Stack:** React 18 (hooks), react-i18next, lucide-react icons, plain CSS with existing design tokens (`--color-*`, `--spacing-*`, `--radius-*`, `--hairline`).

## Global Constraints

- No backend changes; all API function signatures (`installComponent`, `uninstallComponent`, `adminUpdateUser`, `adminDeleteUser`, request endpoints) stay as-is.
- Do NOT rename existing CSS classes (`mining-slot`, `mslot-head`, `mslot-item`, `admin-list`, `admin-user-item`, `tx-type`) — only extend.
- Reuse existing design tokens; no hard-coded colours except within `rgba()` accents matching existing patterns.
- All user-facing strings go through `t(...)` with a sensible fallback string as the 2nd arg (matching existing code style, e.g. `t('mining.install', 'Поставить')`).
- Preserve existing behaviour: transactions refresh only via the manual Refresh button (per the comment at `AdminPanel.jsx:90-92`); do not add push-based tx refresh.
- Manual verification only — this project has no frontend test runner configured. Each task ends with a build check (`npm run build` in `frontend/`) and a described manual smoke test.

---

## Task 1: MiningTab — Cart-Style Multi-Component Installer

**Files:**
- Modify: `frontend/src/components/MiningTab.jsx` (state at line 68, `installMany` at 117-127, assembly render at 321-399)
- Modify: `frontend/src/index.css` OR `frontend/src/economy.css` — add cart CSS near existing `.mslot-*` rules (economy.css:1903-2177)

**Interfaces:**
- Consumes: `installComponent(farmId, cat, hwId)`, `uninstallComponent(farmId, hwId)` from `../services/api`; `hwName(part, t)`, `partSpec(cat, specs, t)` helpers; `farm.capacity`, `parts[cat]` shape `[{ hwId, specs, ... }]`.
- Produces: nothing consumed by other tasks (self-contained UI change).

- [ ] **Step 1: Replace the `installQty` state with model-keyed `cartQty`**

In `MiningTab.jsx`, line 68 currently reads:
```jsx
  const [installQty, setInstallQty] = useState({}) // cat -> сколько ставить оптом (gpu/fan)
```
Replace with:
```jsx
  const [cartQty, setCartQty] = useState({}) // `${cat}::${modelKey}` -> сколько ставить оптом (gpu/fan)
```

- [ ] **Step 2: Add a `removeMany` helper next to `installMany`**

After the `installMany` function (ends at line 127), add:
```jsx
  // Массовое снятие одинаковых деталей: снимаем по одной (сервер валидирует каждую).
  const removeMany = async (hwIds) => {
    setBusy(true)
    try {
      for (const hwId of hwIds) await uninstallComponent(farm.id, hwId)
    } catch (err) {
      flash(err.message, 'error')
    } finally {
      setBusy(false)
      await load()
    }
  }
```

- [ ] **Step 3: Add "remove all" button to installed multi-groups**

In the assembly render, the installed-groups `map` (lines 352-359) currently is:
```jsx
                  {groups.map(g => (
                    <div key={g.key} className="mslot-item">
                      <span>{g.label}{g.items.length > 1 && <b className="mslot-item-qty"> ×{g.items.length}</b>}</span>
                      <button className="mslot-rm" disabled={busy}
                        title={g.items.length > 1 ? t('mining.removeOne') : ''}
                        onClick={() => run(() => uninstallComponent(farm.id, g.items[g.items.length - 1].hwId))}><X size={12} /></button>
                    </div>
                  ))}
```
Replace with:
```jsx
                  {groups.map(g => (
                    <div key={g.key} className="mslot-item">
                      <span>{g.label}{g.items.length > 1 && <b className="mslot-item-qty"> ×{g.items.length}</b>}</span>
                      <span className="mslot-item-actions">
                        {multi && g.items.length > 1 && (
                          <button className="mslot-rm mslot-rm-all" disabled={busy}
                            title={t('mining.removeAll', 'Удалить все')}
                            onClick={() => removeMany(g.items.map(it => it.hwId))}>
                            <X size={12} />{g.items.length}
                          </button>
                        )}
                        <button className="mslot-rm" disabled={busy}
                          title={g.items.length > 1 ? t('mining.removeOne') : ''}
                          onClick={() => run(() => uninstallComponent(farm.id, g.items[g.items.length - 1].hwId))}><X size={12} /></button>
                      </span>
                    </div>
                  ))}
```

- [ ] **Step 4: Replace the picker block — cart for multi, plain select for single**

The current picker block (lines 364-395), from `canAdd && (` through the closing, is:
```jsx
                  ) : canAdd && (
                    avail.length > 0 ? (
                      <div className="mslot-pick-row">
                        <select className="mslot-pick" disabled={busy} value=""
                          onChange={e => {
                            if (!e.target.value) return
                            const picked = avail.find(p => p.hwId === e.target.value)
                            if (multi) {
                              const want = Math.max(1, Math.min(installQty[cat] || 1, capLeft ?? Infinity))
                              const key = hwName(picked, t) + partSpec(cat, picked.specs, t)
                              const ids = avail.filter(p => hwName(p, t) + partSpec(cat, p.specs, t) === key).slice(0, want).map(p => p.hwId)
                              installMany(cat, ids.length ? ids : [picked.hwId])
                            } else {
                              run(() => installComponent(farm.id, cat, e.target.value))
                            }
                          }}>
                          <option value="">{t('mining.pickPart')}</option>
                          {avail.map(p => <option key={p.hwId} value={p.hwId}>{hwName(p, t)}{partSpec(cat, p.specs, t)}</option>)}
                        </select>
                        {multi && (
                          <span className="mslot-qty">
                            <input type="number" min="1" max={capLeft ?? 999} disabled={busy}
                              value={installQty[cat] || 1}
                              onChange={e => setInstallQty(q => ({ ...q, [cat]: Math.max(1, Math.min(capLeft ?? 999, parseInt(e.target.value, 10) || 1)) }))} />
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="mslot-empty">{t('mining.noParts')}</span>
                    )
                  )}
```
Replace the whole `) : canAdd && ( ... )}` block with:
```jsx
                  ) : canAdd && (
                    avail.length > 0 ? (
                      multi ? (
                        <div className="mslot-cart">
                          {(() => {
                            // Группируем доступные детали по модели (имя+спека), чтобы
                            // показать одну строку на модель с полем количества.
                            const availGroups = []
                            for (const p of avail) {
                              const key = hwName(p, t) + partSpec(cat, p.specs, t)
                              const g = availGroups.find(x => x.key === key)
                              if (g) g.items.push(p)
                              else availGroups.push({ key, label: hwName(p, t), spec: partSpec(cat, p.specs, t), items: [p] })
                            }
                            return availGroups.map(g => {
                              const qtyKey = `${cat}::${g.key}`
                              const maxQty = Math.min(g.items.length, capLeft ?? Infinity)
                              const qty = cartQty[qtyKey] ?? maxQty
                              return (
                                <div key={g.key} className="mslot-cart-row">
                                  <span className="mslot-cart-label">{g.label}{g.spec}</span>
                                  <span className="mslot-cart-stock" title={t('mining.inStock', 'В наличии')}>{g.items.length}</span>
                                  <input className="mslot-cart-qty" inputMode="numeric" disabled={busy}
                                    value={qty}
                                    onChange={e => {
                                      const v = parseInt(e.target.value, 10)
                                      setCartQty(q => ({ ...q, [qtyKey]: isNaN(v) ? 1 : Math.max(1, Math.min(maxQty, v)) }))
                                    }} />
                                  <button className="mslot-cart-btn" disabled={busy}
                                    onClick={() => {
                                      const want = Math.max(1, Math.min(cartQty[qtyKey] ?? maxQty, maxQty))
                                      installMany(cat, g.items.slice(0, want).map(p => p.hwId))
                                    }}>
                                    {t('mining.install', 'Поставить')}
                                  </button>
                                </div>
                              )
                            })
                          })()}
                        </div>
                      ) : (
                        <select className="mslot-pick" disabled={busy} value=""
                          onChange={e => { if (e.target.value) run(() => installComponent(farm.id, cat, e.target.value)) }}>
                          <option value="">{t('mining.pickPart')}</option>
                          {avail.map(p => <option key={p.hwId} value={p.hwId}>{hwName(p, t)}{partSpec(cat, p.specs, t)}</option>)}
                        </select>
                      )
                    ) : (
                      <span className="mslot-empty">{t('mining.noParts')}</span>
                    )
                  )}
```

- [ ] **Step 5: Add cart CSS**

Append to `frontend/src/economy.css` (after the existing `.mslot-pick-row` rule at line 2177):
```css
/* ── Cart-style multi-component installer (GPU/fan) ─────────────────────── */
.mslot-cart { display: flex; flex-direction: column; gap: 5px; margin-top: 6px; }
.mslot-cart-row {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 7px; background: var(--color-bg-secondary);
  border: 1px solid var(--hairline); border-radius: 6px;
}
.mslot-cart-label { flex: 1 1 auto; font-size: 11.5px; color: var(--color-text-primary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mslot-cart-stock {
  flex-shrink: 0; font-size: 10.5px; font-weight: 600; color: var(--color-text-secondary);
  background: var(--color-bg-tertiary); border-radius: 8px; padding: 1px 7px; min-width: 20px; text-align: center;
}
.mslot-cart-qty {
  flex-shrink: 0; width: 46px; padding: 4px 6px; font-size: 12px; text-align: center;
  background: var(--color-bg-tertiary); border: 1px solid var(--hairline);
  border-radius: 6px; color: var(--color-text-primary);
}
.mslot-cart-btn {
  flex-shrink: 0; padding: 4px 10px; font-size: 11px; font-weight: 600;
  background: var(--color-accent); color: #fff; border: none;
  border-radius: 6px; cursor: pointer;
}
.mslot-cart-btn:hover:not(:disabled) { background: var(--color-accent-hover); }
.mslot-cart-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mslot-item-actions { display: inline-flex; align-items: center; gap: 4px; }
.mslot-rm-all { display: inline-flex; align-items: center; gap: 1px; font-size: 10px; font-weight: 700; }
```

- [ ] **Step 6: Build and verify**

Run: `cd frontend && npm run build`
Expected: build succeeds, no errors referencing `installQty` (all usages replaced by `cartQty`).

Run: `cd frontend && npm run lint`
Expected: no new lint errors in `MiningTab.jsx`.

- [ ] **Step 7: Manual smoke test**

Start dev server (`cd frontend && npm run dev`), open Mining tab with a farm that has GPU/fan capacity and inventory:
1. GPU/fan slots show a cart list, one row per model, with stock count and a pre-filled qty input.
2. Type `200` into a fan qty input → clamps to `min(available, capLeft)`.
3. Click "Поставить" → installs that many; slot count updates.
4. On an installed group with ×N, the `×N` remove-all button removes all of that model; single `×` removes one.
5. Single-slot categories (cpu, psu, etc.) still show a plain dropdown.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/MiningTab.jsx frontend/src/economy.css
git commit -m "feat(mining): cart-style installer for GPU/fan multi-components"
```

---

## Task 2: AdminPanel — Transactions Table + Filter Bar

**Files:**
- Modify: `frontend/src/components/AdminPanel.jsx` (add state near line 55; replace transactions render at lines 712-762)
- Modify: `frontend/src/App.css` (add table + filter CSS near existing `.admin-tx-item` at line 2417)

**Interfaces:**
- Consumes: existing `transactions` state (shape `{ id, type, symbol, amount, price, timestamp }`), `botOrders` state (shape `{ id, action, symbol, quantity, pricePerShare, timestamp }`), `handleDeleteTransaction(txId)`, `loadData()`.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Add filter/search state**

In `AdminPanel.jsx`, after the `const [botOrders, setBotOrders] = useState([])` line (line 55), add:
```jsx
  const [txFilter, setTxFilter] = useState('all') // 'all' | 'buy' | 'sell' | 'bot'
  const [txSearch, setTxSearch] = useState('')
```

- [ ] **Step 2: Replace the transactions render block**

The current block (lines 712-762) starts at `{!loading && activeSection === 'transactions' && (` and ends before `{!loading && activeSection === 'config' && (`. Replace the entire transactions block with:
```jsx
        {!loading && activeSection === 'transactions' && (() => {
          // Объединяем пользовательские сделки и ордера ботов в один поток.
          const allTx = [
            ...transactions.map(tx => ({
              key: `u-${tx.id}`, id: tx.id, source: 'user', type: tx.type,
              symbol: tx.symbol, qty: tx.amount, price: tx.price, timestamp: tx.timestamp,
            })),
            ...botOrders.map(tx => ({
              key: `b-${tx.id}`, id: tx.id, source: 'bot', type: 'bot',
              symbol: tx.symbol, qty: tx.quantity, price: tx.pricePerShare, timestamp: tx.timestamp,
            })),
          ]
          const q = txSearch.trim().toLowerCase()
          const filtered = allTx.filter(tx => {
            if (txFilter !== 'all' && tx.type !== txFilter) return false
            if (q && !(tx.symbol || '').toLowerCase().includes(q)) return false
            return true
          })
          return (
            <>
              <div className="tx-filter-bar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={txSearch} onChange={e => setTxSearch(e.target.value)} placeholder={t('admin.searchTx', 'Поиск по тикеру...')} /></div>
                <div className="tx-chips">
                  {['all', 'buy', 'sell', 'bot'].map(f => (
                    <button key={f} className={`tx-chip ${txFilter === f ? 'active' : ''}`} onClick={() => setTxFilter(f)}>
                      {f.toUpperCase()}
                    </button>
                  ))}
                </div>
                <button className="admin-btn" onClick={loadData} title={t('admin.refresh')}>
                  <RefreshCw size={14} />
                </button>
                <span className="admin-count">{filtered.length} / {allTx.length}</span>
              </div>
              <div className="admin-tx-table">
                <div className="admin-tx-row admin-tx-head">
                  <span>{t('admin.txType', 'Тип')}</span>
                  <span>{t('admin.txSymbol', 'Тикер')}</span>
                  <span>{t('admin.txQty', 'Кол-во')}</span>
                  <span>{t('admin.txPrice', 'Цена')}</span>
                  <span>{t('admin.txTotal', 'Итого')}</span>
                  <span>{t('admin.txTime', 'Время')}</span>
                  <span></span>
                </div>
                {filtered.map(tx => {
                  const total = (Number(tx.qty) || 0) * (Number(tx.price) || 0)
                  return (
                    <div key={tx.key} className={`admin-tx-row ${tx.source === 'bot' ? 'bot' : ''}`}>
                      <span><span className={`tx-type ${tx.type}`}>{tx.type.toUpperCase()}</span></span>
                      <span><strong>{tx.symbol}</strong></span>
                      <span>{tx.qty}</span>
                      <span>${(Number(tx.price) || 0).toFixed(2)}</span>
                      <span className="tx-total">${total.toFixed(2)}</span>
                      <span className="tx-time">{tx.timestamp}</span>
                      <span className="tx-act">
                        {tx.source === 'user'
                          ? <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteTransaction(tx.id)}><Trash2 size={14} /></button>
                          : <span className="tx-dash">—</span>}
                      </span>
                    </div>
                  )
                })}
                {filtered.length === 0 && <p className="empty-state">{t('admin.noTransactions')}</p>}
              </div>
            </>
          )
        })()}
```

- [ ] **Step 3: Add table + filter CSS**

Append to `frontend/src/App.css` (after `.tx-right` block ending line 2646):
```css
/* ── Transactions table + filter bar ───────────────────────────────────── */
.tx-filter-bar {
  display: flex; align-items: center; gap: var(--spacing-sm);
  flex-wrap: wrap; margin-bottom: var(--spacing-md);
}
.tx-filter-bar .tx-search { flex: 1 1 180px; }
.tx-chips { display: flex; gap: 4px; }
.tx-chip {
  padding: 4px 12px; font-size: 11px; font-weight: 600;
  background: var(--color-bg-secondary); color: var(--color-text-secondary);
  border: 1px solid var(--hairline); border-radius: 14px; cursor: pointer;
  text-transform: uppercase; transition: all 0.15s ease;
}
.tx-chip:hover { color: var(--color-text-primary); }
.tx-chip.active { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }
.admin-tx-table { display: flex; flex-direction: column; }
.admin-tx-row {
  display: grid;
  grid-template-columns: 68px 1fr 70px 90px 100px 1fr 44px;
  align-items: center; gap: var(--spacing-sm);
  padding: 6px 10px; border-bottom: 1px solid var(--hairline);
  font-size: 13px; color: var(--color-text-primary);
}
.admin-tx-head {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  color: var(--color-text-secondary); border-bottom: 1px solid var(--hairline);
  position: sticky; top: 0; background: var(--color-bg-primary); z-index: 1;
}
.admin-tx-row.bot { opacity: 0.85; }
.admin-tx-row .tx-total { font-family: monospace; text-align: right; color: var(--color-accent-hover); }
.admin-tx-row .tx-time { font-size: 12px; color: var(--color-text-secondary); }
.admin-tx-row .tx-act { display: flex; justify-content: flex-end; }
.tx-type.bot { background: rgba(94, 92, 230, 0.14); color: #a5a3f5; }
.tx-dash { color: var(--color-text-secondary); }
```

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npm run build`
Expected: build succeeds. No unused-variable warnings for the removed inline `admin-section-divider` bot section.

- [ ] **Step 5: Manual smoke test**

Open Admin → Transactions:
1. Filter bar shows search + `ALL/BUY/SELL/BOT` chips + refresh + `N / M` counter.
2. Clicking `BUY` shows only buy rows; `BOT` shows only bot rows; `ALL` resets.
3. Typing a ticker filters rows; counter updates.
4. Table columns align; `Total = qty × price`; bot rows show `—` instead of delete.
5. Delete button on a user row removes it after confirm.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AdminPanel.jsx frontend/src/App.css
git commit -m "feat(admin): transactions table with type filter and search"
```

---

## Task 3: AdminPanel — Users Side Panel Editor

**Files:**
- Modify: `frontend/src/components/AdminPanel.jsx` (content wrapper at line 393; users render at 584-710)
- Modify: `frontend/src/App.css` (add side-panel CSS near `.admin-user-edit-form` at line 2520)

**Interfaces:**
- Consumes: `editingUser`, `editForm`, `editErrors`, `handleStartEditUser(u)`, `handleSaveUser()`, `handleCancelEditUser()`, `setEditForm`, `users` state, `setPropertyUser`, `handleDeleteUser`.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Toggle `has-panel` on the content wrapper**

At line 393, `<div className="admin-content">` becomes conditional on the user editor being open:
```jsx
        <div className={`admin-content${editingUser && activeSection === 'users' ? ' has-panel' : ''}`}>
```

- [ ] **Step 2: Replace the users render block — list becomes read-only, edit moves to panel**

The current users block (lines 584-710) is `{!loading && activeSection === 'users' && ( ... )}`. Replace the whole block with:
```jsx
        {!loading && activeSection === 'users' && (
          <>
            <div className="admin-list">
              <div className="admin-toolbar">
                <div className="tx-search"><Search size={15} className="tx-search-icon" />
                  <input value={userSearch} onChange={e => setUserSearch(e.target.value)} placeholder={t('admin.searchUsers')} /></div>
                <span className="admin-count">{t('admin.totalUsers')}: {users.length}</span>
              </div>
              {users.filter(u => !userSearch || (u.username || '').toLowerCase().includes(userSearch.toLowerCase())).map(u => (
                <div key={u.id} className={`admin-user-item${editingUser === u.id ? ' editing' : ''}`}>
                  <div className="admin-user-info">
                    <div>
                      <strong>{u.username}</strong>
                      <span className={`user-role ${u.role || 'user'}`}>{u.role || 'user'}</span>
                      {u.hidden_from_leaderboard && (
                        <span className="user-role admin" title={t('admin.fieldHiddenFromLeaderboard')}>
                          <EyeOff size={12} />
                        </span>
                      )}
                    </div>
                    <div className="admin-user-meta">
                      <span className="user-balance">${u.balance != null ? u.balance.toFixed(2) : '0.00'}</span>
                      <span className="user-date">{u.created_at}</span>
                    </div>
                  </div>
                  <div className="user-actions">
                    <button className="admin-btn" onClick={() => setPropertyUser(u)} title={t('admin.property.title')}>
                      <Briefcase size={14} />
                    </button>
                    <button className="admin-btn" onClick={() => handleStartEditUser(u)}>
                      <Edit3 size={14} />
                    </button>
                    <button className="admin-btn admin-btn-danger" onClick={() => handleDeleteUser(u.id, u.username)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
              {users.length === 0 && <p className="empty-state">{t('admin.noUsers')}</p>}
            </div>
            {editingUser && (() => {
              const u = users.find(x => x.id === editingUser)
              return (
                <aside className="user-edit-panel">
                  <div className="user-edit-panel-header">
                    <strong>{t('admin.editUser')}: {u?.username}</strong>
                    <button className="admin-btn" onClick={handleCancelEditUser}><X size={16} /></button>
                  </div>
                  <div className="user-edit-panel-body">
                    <div className="admin-field-group">
                      <label>{t('admin.fieldUsername')}</label>
                      <input type="text" value={editForm.username}
                        onChange={e => setEditForm({ ...editForm, username: e.target.value })}
                        className={`admin-input${editErrors.username ? ' admin-input-error' : ''}`} />
                      {editErrors.username && <span className="admin-field-error">{editErrors.username}</span>}
                    </div>
                    <div className="admin-field-group">
                      <label>{t('admin.fieldBalance')}</label>
                      <input type="number" step="0.01" min="0" value={editForm.balance}
                        onChange={e => setEditForm({ ...editForm, balance: e.target.value })}
                        className={`admin-input${editErrors.balance ? ' admin-input-error' : ''}`} />
                      {editErrors.balance && <span className="admin-field-error">{editErrors.balance}</span>}
                    </div>
                    <div className="admin-field-group">
                      <label>{t('admin.fieldRole')}</label>
                      <select value={editForm.role}
                        onChange={e => setEditForm({ ...editForm, role: e.target.value })}
                        className={`admin-input${editErrors.role ? ' admin-input-error' : ''}`}>
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                      {editErrors.role && <span className="admin-field-error">{editErrors.role}</span>}
                    </div>
                    <div className="admin-field-group">
                      <label>{t('admin.fieldCardNumber')}</label>
                      <input type="text" value={editForm.card_number}
                        onChange={e => setEditForm({ ...editForm, card_number: e.target.value })}
                        className={`admin-input${editErrors.card_number ? ' admin-input-error' : ''}`}
                        placeholder="XXXX-XXXX-XXXX-XXXXX" maxLength={20} />
                      {editErrors.card_number && <span className="admin-field-error">{editErrors.card_number}</span>}
                    </div>
                    <div className="admin-field-checkbox">
                      <label>
                        <input type="checkbox" checked={editForm.hidden_from_leaderboard}
                          onChange={e => setEditForm({ ...editForm, hidden_from_leaderboard: e.target.checked })} />
                        {t('admin.fieldHiddenFromLeaderboard')}
                      </label>
                    </div>
                    <div className="admin-field-checkbox">
                      <label>
                        <input type="checkbox" checked={editForm.leaderboard_lock}
                          onChange={e => setEditForm({ ...editForm, leaderboard_lock: e.target.checked })} />
                        {t('admin.fieldLeaderboardLock')}
                      </label>
                    </div>
                  </div>
                  <div className="user-edit-panel-actions">
                    <button className="admin-btn admin-btn-primary" onClick={handleSaveUser}>
                      <Save size={14} /> {t('admin.save')}
                    </button>
                    <button className="admin-btn" onClick={handleCancelEditUser}>
                      <X size={14} /> {t('admin.cancel')}
                    </button>
                  </div>
                </aside>
              )
            })()}
          </>
        )}
```

- [ ] **Step 3: Add side-panel CSS**

Append to `frontend/src/App.css` (after `.admin-user-edit-actions` block ending line 2600):
```css
/* ── Users: split list + side edit panel ───────────────────────────────── */
.admin-content.has-panel { display: flex; flex-direction: row; gap: var(--spacing-md); align-items: flex-start; }
.admin-content.has-panel .admin-list { flex: 1 1 auto; min-width: 220px; }
.user-edit-panel {
  flex: 0 0 320px; align-self: stretch;
  display: flex; flex-direction: column; gap: var(--spacing-md);
  padding: var(--spacing-md); background: var(--color-bg-secondary);
  border: 1px solid var(--hairline); border-left: 2px solid var(--color-accent);
  border-radius: var(--radius-md);
  animation: panel-slide-in 0.2s ease;
}
@keyframes panel-slide-in { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: translateX(0); } }
.user-edit-panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding-bottom: var(--spacing-sm); border-bottom: 1px solid var(--hairline);
}
.user-edit-panel-header strong { font-size: 14px; color: var(--color-text-primary); }
.user-edit-panel-body { display: flex; flex-direction: column; gap: var(--spacing-md); }
.user-edit-panel-actions {
  display: flex; gap: var(--spacing-sm);
  padding-top: var(--spacing-sm); border-top: 1px solid var(--hairline);
}
.admin-user-item.editing { border-color: var(--color-accent); box-shadow: 0 0 0 1px var(--color-accent); }
@media (max-width: 720px) {
  .admin-content.has-panel { flex-direction: column; }
  .user-edit-panel { flex-basis: auto; width: 100%; }
}
```

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npm run build`
Expected: build succeeds. The old inline-edit JSX (`admin-user-edit-form`, `admin-user-edit-header`, etc.) is no longer referenced from users render — those CSS classes remain in App.css unused, which is fine (no removal required).

- [ ] **Step 5: Manual smoke test**

Open Admin → Users:
1. Click Edit on a user → list narrows, side panel slides in on the right.
2. Edited row shows a highlighted border.
3. Clicking Edit on a different user swaps the panel to that user.
4. Invalid input (username < 3 chars, negative balance) shows inline field errors.
5. Save persists and closes panel; Cancel / `×` closes without saving.
6. Narrow window (< 720px): panel stacks below the list.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AdminPanel.jsx frontend/src/App.css
git commit -m "feat(admin): side-panel user editor replacing inline expand"
```

---

## Task 4: AdminPanel — Stocks Light Polish

**Files:**
- Modify: `frontend/src/components/AdminPanel.jsx` (add state near line 67; stocks render at 398-486)
- Modify: `frontend/src/App.css` (extend `.stock-price` at line 2446)

**Interfaces:**
- Consumes: `newStock`, `setNewStock`, `handleAddStock`, `stocks` state (shape includes `symbol, name, price, changePercent`), `stockSearch`.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Add `showAddForm` state**

In `AdminPanel.jsx`, after the `newStock` state (line 67), add:
```jsx
  const [showAddForm, setShowAddForm] = useState(false)
```

- [ ] **Step 2: Make the add form collapsible**

The current stocks block opens (line 398-426) with the `admin-add-form` div always visible. Replace this opening portion:
```jsx
        {!loading && activeSection === 'stocks' && (
          <div>
            <div className="admin-add-form">
              <h3>{t('admin.addStock')}</h3>
              <div className="form-row">
                <input
                  placeholder={t('admin.tickerPlaceholder')}
                  value={newStock.symbol}
                  onChange={e => setNewStock({ ...newStock, symbol: e.target.value })}
                  className="admin-input"
                />
                <input
                  placeholder={t('admin.namePlaceholder')}
                  value={newStock.name}
                  onChange={e => setNewStock({ ...newStock, name: e.target.value })}
                  className="admin-input"
                />
                <input
                  placeholder={t('admin.pricePlaceholder')}
                  type="number"
                  value={newStock.price}
                  onChange={e => setNewStock({ ...newStock, price: e.target.value })}
                  className="admin-input"
                />
                <button className="admin-btn admin-btn-primary" onClick={handleAddStock}>
                  <Plus size={16} /> {t('admin.addButton')}
                </button>
              </div>
            </div>
```
with:
```jsx
        {!loading && activeSection === 'stocks' && (
          <div>
            <div className="admin-toolbar">
              <button className="admin-btn admin-btn-primary" onClick={() => setShowAddForm(v => !v)}>
                <Plus size={16} /> {t('admin.addStock')}
              </button>
            </div>
            {showAddForm && (
              <div className="admin-add-form">
                <div className="form-row">
                  <input
                    placeholder={t('admin.tickerPlaceholder')}
                    value={newStock.symbol}
                    onChange={e => setNewStock({ ...newStock, symbol: e.target.value })}
                    className="admin-input"
                  />
                  <input
                    placeholder={t('admin.namePlaceholder')}
                    value={newStock.name}
                    onChange={e => setNewStock({ ...newStock, name: e.target.value })}
                    className="admin-input"
                  />
                  <input
                    placeholder={t('admin.pricePlaceholder')}
                    type="number"
                    value={newStock.price}
                    onChange={e => setNewStock({ ...newStock, price: e.target.value })}
                    className="admin-input"
                  />
                  <button className="admin-btn admin-btn-primary" onClick={handleAddStock}>
                    <Plus size={16} /> {t('admin.addButton')}
                  </button>
                </div>
              </div>
            )}
```
Note: the `admin-section-divider` block and everything after it (stock config heading, `admin-list`, etc.) stays unchanged. Only the leading `admin-add-form` is wrapped/replaced as above.

- [ ] **Step 3: Colour the stock price by change direction**

In the stock list item (line 464-468), the read-only info block is:
```jsx
                      <div className="stock-info">
                        <strong>{stock.symbol}</strong>
                        <span>{stock.name}</span>
                        <span className="stock-price">${stock.price?.toFixed(2)}</span>
                      </div>
```
Replace the `stock-price` span with a direction-aware class:
```jsx
                      <div className="stock-info">
                        <strong>{stock.symbol}</strong>
                        <span>{stock.name}</span>
                        <span className={`stock-price ${stock.changePercent > 0 ? 'up' : stock.changePercent < 0 ? 'down' : ''}`}>${stock.price?.toFixed(2)}</span>
                      </div>
```

- [ ] **Step 4: Add price-direction CSS**

Append to `frontend/src/App.css` (after the `.stock-price` rule at line 2449):
```css
.stock-price.up { color: var(--color-success) !important; }
.stock-price.down { color: var(--color-danger) !important; }
```

- [ ] **Step 5: Build and verify**

Run: `cd frontend && npm run build`
Expected: build succeeds. `showAddForm` used; no unused-var warning.

- [ ] **Step 6: Manual smoke test**

Open Admin → Stocks:
1. Add form is hidden; "Add Stock" button in the toolbar toggles it open/closed.
2. Adding a stock still works while the form is open.
3. Stock prices render green when `changePercent > 0`, red when `< 0`, neutral at `0`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AdminPanel.jsx frontend/src/App.css
git commit -m "feat(admin): collapsible add-stock form and price direction colours"
```

---

## Final Verification

- [ ] **Full build:** `cd frontend && npm run build` → succeeds.
- [ ] **Lint:** `cd frontend && npm run lint` → no new errors in `MiningTab.jsx` or `AdminPanel.jsx`.
- [ ] **Regression pass:** Mining install/remove, admin transactions filter, admin user edit, admin stock add — all functional per each task's smoke test.

