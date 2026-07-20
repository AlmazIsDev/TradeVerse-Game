# UI/UX Redesign: MiningTab + AdminPanel
**Date:** 2026-07-20  
**Scope:** MiningTab GPU/Fan installer · AdminPanel transactions · AdminPanel users · AdminPanel stocks (light)  
**Files:** `frontend/src/components/MiningTab.jsx` · `frontend/src/components/AdminPanel.jsx`

---

## 1. MiningTab — Cart-style Multi-Component Installer

### Problem
For `multi: true` categories (GPU, fan), the current UI uses a `<select>` listing every individual `hwId` plus a small `<input type="number">` next to it. Installing 200 fans requires typing a number into a disconnected tiny input while picking from a dropdown that shows duplicate entries. The UX is unclear and slow.

### Solution: Grouped Model List ("cart")
Replace `mslot-pick-row` (the select + qty input row) for `multi` categories with a grouped list of **available models**. Each distinct model (grouped by `hwName + partSpec`) gets one row:

```
Model name · spec          [in stock: N]  [qty input]  [Install]
```

**Behaviour:**
- `avail` (already fetched as `parts[cat]`) is grouped client-side by `hwName(p, t) + partSpec(cat, p.specs, t)` — same key logic already used in `installMany`.
- Each group row shows: model name, spec summary, count of identical items in inventory.
- **Qty input** is a `<input type="text" inputMode="numeric">` (not `type="number"` to avoid spinners). Default value: `min(groupCount, capLeft ?? Infinity)` — pre-filled to the maximum installable.
- The user can type any number; on "Install" click it clamps to `min(typed, groupCount, capLeft ?? Infinity)` before calling `installMany`.
- **Install button** calls `installMany(cat, ids)` where `ids` = first N `hwId`s from that group.
- Qty state lives in a `Map<modelKey, number>` (replaces the current `installQty` object which is already keyed by `cat`; now keyed by `cat + modelKey`).

**Removing:**
- Existing `×` button on installed groups removes the last item of that group (unchanged).
- Add a secondary "remove all of this model" button (`×N`) next to the count badge when `g.items.length > 1`.

**What does NOT change:**
- Single-slot categories (motherboard, cpu, psu, ram, ssd, cooling, case, rack, ups, network) keep the existing `<select>`.
- `installMany`, `capLeft`, `capFull`, slot header, grouping of installed items — logic untouched.
- CSS class names for `mining-slot`, `mslot-head`, `mslot-item` — extend, don't rename.

### New CSS classes needed
- `.mslot-cart` — wrapper for the model-list rows
- `.mslot-cart-row` — one model row (flex, align-center)
- `.mslot-cart-stock` — "in stock: N" label (muted colour)
- `.mslot-cart-qty` — text input for quantity (narrow, ~52px)
- `.mslot-cart-btn` — install button (small, primary style)
- `.mslot-rm-all` — "×N" remove-all button (danger, ghost)

---

## 2. AdminPanel — Transactions: Table + Filter Bar

### Problem
Transaction list is a flat unstyled `div` stream with no search, no type filter, and bot orders rendered in a separate section below. Difficult to find a specific trade or understand the volume at a glance.

### Solution: Combined table with filter bar

**Filter bar** (replaces current `admin-toolbar`):
```
[🔍 search by symbol...]  [ALL] [BUY] [SELL] [BOT]     [↻ Refresh]   Shown: N / Total: M
```
- Search filters on `tx.symbol` (case-insensitive).
- Type chips are toggle buttons; `ALL` resets others. Active chip gets `.active` styling.
- Bot orders and user transactions merged into one array before rendering; bot items carry `source: 'bot'`.
- "Shown / Total" counter updates reactively with filters.

**Table** (replaces the two separate `admin-list` divs):

| Type | Symbol | Qty | Price | Total | Time | ✕ |
|------|--------|-----|-------|-------|------|---|

- `Type` cell: coloured badge — `BUY` green, `SELL` red, `BOT` blue-grey.
- `Total` = `amount × price` (or `quantity × pricePerShare` for bot), computed client-side.
- `Time` column: formatted as `DD.MM.YY HH:mm`.
- `✕` column: delete button for user transactions; em-dash `—` for bot orders (no delete).
- Table uses CSS `table` or `display: grid` with fixed column widths — no horizontal scroll on desktop.
- Row height: compact (~34px).

### New CSS classes
- `.admin-tx-table` — table container
- `.admin-tx-row` — one data row
- `.tx-filter-bar` — filter + search row
- `.tx-chip` / `.tx-chip.active` — type toggle chips
- `.tx-total` — total cell (monospace, right-aligned)

---

## 3. AdminPanel — Users: Side Panel Edit

### Problem
Clicking Edit on a user expands an inline form that pushes all other list items down and occupies the full width. The form is visually heavy and loses context (you can't see other users while editing).

### Solution: Side panel within admin-content

When Edit is clicked, the `admin-list` enters a "split" mode:

```
[ admin-list (flex: 1, min-width 220px) ] [ user-edit-panel (width: 320px, fixed) ]
```

- `admin-content` switches to `display: flex; flex-direction: row; gap: 12px` when `editingUser !== null`.
- `user-edit-panel` slides in (CSS `transform: translateX` + `transition: 200ms ease`); slides out on close.
- Panel header: "Edit: {username}" + `×` close button.
- All existing fields (username, balance, role, card_number, hidden_from_leaderboard, leaderboard_lock) + validation errors — same logic, just moved into the panel.
- Save / Cancel buttons at the bottom of the panel.
- Clicking a different user while panel is open switches the form to that user (saves `editingUser` to new id, re-populates `editForm`).
- The list row for the currently-edited user gets a subtle highlight (`.editing` class).

**What does NOT change:**
- `handleStartEditUser`, `handleSaveUser`, `handleCancelEditUser`, `validateEditForm` — same logic.
- `adminUpdateUser` API call — unchanged.
- Delete and property (Briefcase) buttons — unchanged.

### New CSS classes
- `.admin-content.has-panel` — triggers `display: flex; flex-direction: row` on the content area (class toggled when `editingUser !== null`)
- `.user-edit-panel` — the side panel (fixed width 320px, border-left); sibling of `.admin-list`
- `.user-edit-panel-header` — title + close button
- `.admin-user-item.editing` — highlight for active row

---

## 4. AdminPanel — Stocks: Light Polish

Minor improvements, no structural changes:

- **Price colouring:** `changePercent > 0` → green, `< 0` → red, `= 0` → neutral. Applied to `.stock-price` cell.
- **Collapsible add form:** "Add Stock" form is hidden by default behind an `+ Add Stock` button in `admin-toolbar`. Clicking toggles `showAddForm` local state. Reduces visual noise when just browsing stocks.
- No changes to edit-in-place, config modal, or `handleAddStock` logic.

---

## 5. Notes & Future Work

- The user mentioned: *"if anything, redesign the rest of the admin panel"*. This is noted as a follow-up task but is **out of scope** for this implementation plan. Economy, Config, and Prices tabs are untouched.
- No backend changes required for any of the above.
- i18n keys already exist for all labels; no new translation strings needed except potentially `mining.removeAllOf` for the ×N button.
