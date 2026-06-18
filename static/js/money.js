// money: accounts, transactions, budgets, and a couple of charts. plain SVG for
// the charts (no chart lib), api() helper for the fetches.
import { api, toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';
import { initCustomDropdown, getDropdownValue } from './dropdown.js';
import { initDatePicker } from './datepick.js';

let _month = _thisMonth();
let _accounts = [], _txns = [], _budgets = [], _sum = null, _recurring = [], _rules = [];
let _cur = '$';
let _inited = false;
let _editTxn = null;   // id of the txn row currently being edited inline

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function _thisMonth() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; }
function _today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function _shiftMonth(m, delta) {
  let [y, mo] = m.split('-').map(Number); mo += delta;
  while (mo < 1) { mo += 12; y--; } while (mo > 12) { mo -= 12; y++; }
  return `${y}-${String(mo).padStart(2, '0')}`;
}
function _monthLabel(m) {
  const [y, mo] = m.split('-').map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }).toLowerCase();
}
const fmt = n => `${_cur}${(Math.round((n || 0) * 100) / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = n => (n >= 0 ? '+' : '−') + fmt(Math.abs(n));

export function initMoneyPanel() {
  if (!_inited) {
    _inited = true;
    $('money-prev')?.addEventListener('click', () => { _month = _shiftMonth(_month, -1); load(); });
    $('money-next')?.addEventListener('click', () => { _month = _shiftMonth(_month, 1); load(); });
    const imp = $('money-import'), fileInp = $('money-import-file');
    imp?.addEventListener('click', () => {
      if (!_accounts.length) { toast('add an account first', 'error'); return; }
      fileInp?.click();
    });
    fileInp?.addEventListener('change', async e => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const r = await api('/api/money/transactions/import.csv', {
          method: 'POST', body: { csv: await f.text(), account_id: _accounts[0].id } });
        const dup = r.skipped ? `, skipped ${r.skipped} duplicate${r.skipped === 1 ? '' : 's'}` : '';
        toast(`imported ${r.imported} txn${r.imported === 1 ? '' : 's'} into ${_accounts[0].name}${dup}`, 'success');
        load();
      } catch { toast('import failed', 'error'); }
      fileInp.value = '';
    });
  }
  load();
}

async function load() {
  const lbl = $('money-month-label'); if (lbl) lbl.textContent = _monthLabel(_month);
  try {
    // post any due recurring txns FIRST (and advance them) so the balances,
    // transactions and summary we read next all reflect them — no stale first load
    _recurring = await api('/api/money/recurring').catch(() => []);
    [_accounts, _txns, _budgets, _sum, _rules] = await Promise.all([
      api('/api/money/accounts'),
      api(`/api/money/transactions?month=${_month}`),
      api('/api/money/budgets'),
      api(`/api/money/summary?month=${_month}`),
      api('/api/money/rules').catch(() => []),
    ]);
    _cur = _sum?.currency || (_accounts[0]?.currency) || '$';
  } catch { $('money-body').innerHTML = '<div class="money-empty">failed to load</div>'; return; }
  render();
}

// ── render ────────────────────────────────────────────────────────────────────
function render() {
  const b = $('money-body'); if (!b) return;
  if (!_accounts.length) {
    b.innerHTML = `<div class="money-empty">
      <div class="money-empty-title">no accounts yet</div>
      <div class="money-empty-sub">add an account to start tracking your money</div>
      ${_accountForm()}</div>`;
    _wireAccountForm();
    return;
  }
  b.innerHTML =
    summaryCards() +
    `<div class="money-grid">
      <section class="money-card"><h3>accounts</h3>${accountsList()}<div id="money-acct-form-wrap"></div>
        <button class="btn money-add-acct" id="money-add-acct">+ account</button></section>
      <section class="money-card"><h3>spending by category</h3>${catChart()}</section>
      <section class="money-card"><h3>last 6 months</h3>${trendChart()}</section>
      <section class="money-card"><h3>budgets</h3>${budgetsList()}${_budgetForm()}</section>
      <section class="money-card"><h3>recurring</h3>${recurringList()}${_recurringForm()}</section>
      <section class="money-card"><h3>auto-categorize${_rules.length ? ` <button class="btn rules-apply" id="rules-apply" title="apply to existing uncategorized">apply</button>` : ''}</h3>${rulesList()}${_ruleForm()}</section>
     </div>` +
    `<section class="money-card money-txns"><h3>transactions · ${_monthLabel(_month)}</h3>${addTxnRow()}${transferRow()}${txnList()}</section>`;
  wire();
}

function summaryCards() {
  const s = _sum || {};
  return `<div class="money-summary">
    <div class="ms-card"><span class="ms-label">net worth</span><span class="ms-val">${fmt(s.net_worth)}</span></div>
    <div class="ms-card"><span class="ms-label">income · this month</span><span class="ms-val pos">${fmt(s.income)}</span></div>
    <div class="ms-card"><span class="ms-label">spent · this month</span><span class="ms-val neg">${fmt(s.expense)}</span></div>
    <div class="ms-card"><span class="ms-label">net</span><span class="ms-val ${s.net >= 0 ? 'pos' : 'neg'}">${signed(s.net || 0)}</span></div>
  </div>`;
}

function accountsList() {
  return `<div class="money-accts">` + _accounts.map(a => `
    <div class="money-acct ${a.archived ? 'arch' : ''}" data-id="${a.id}">
      <div class="ma-top"><span class="ma-name">${esc(a.name)}</span><button class="ma-del" data-del-acct="${a.id}" title="delete">×</button></div>
      <div class="ma-bal ${a.balance < 0 ? 'neg' : ''}">${fmt(a.balance)}</div>
      <div class="ma-kind">${esc(a.kind)}</div>
    </div>`).join('') + `</div>`;
}

function catChart() {
  const cats = (_sum?.by_category || []).slice(0, 8);
  if (!cats.length) return '<div class="money-empty-sm">no spending this month</div>';
  const max = Math.max(...cats.map(c => c[1])) || 1;
  return `<div class="cat-chart">` + cats.map(([name, amt]) => `
    <div class="cat-row">
      <span class="cat-name">${esc(name)}</span>
      <div class="cat-bar-wrap"><div class="cat-bar" style="width:${Math.max(3, amt / max * 100)}%"></div></div>
      <span class="cat-amt">${fmt(amt)}</span>
    </div>`).join('') + `</div>`;
}

function trendChart() {
  const t = _sum?.trend || [];
  if (!t.length) return '<div class="money-empty-sm">no data</div>';
  const max = Math.max(1, ...t.map(m => Math.max(m.income, m.expense)));
  const W = 280, H = 110, bw = W / t.length, gap = 5;
  let bars = '';
  t.forEach((m, i) => {
    const x = i * bw;
    const ih = m.income / max * H, eh = m.expense / max * H;
    const half = (bw - gap * 2) / 2;
    bars += `<rect x="${x + gap}" y="${H - ih}" width="${half}" height="${ih}" class="tr-inc"><title>${m.month} income ${fmt(m.income)}</title></rect>`;
    bars += `<rect x="${x + gap + half}" y="${H - eh}" width="${half}" height="${eh}" class="tr-exp"><title>${m.month} spent ${fmt(m.expense)}</title></rect>`;
  });
  const labels = t.map((m, i) => `<span style="width:${100 / t.length}%">${m.month.slice(5)}</span>`).join('');
  return `<svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bars}</svg>
    <div class="trend-labels">${labels}</div>
    <div class="trend-legend"><span class="lg-inc">income</span><span class="lg-exp">spent</span></div>`;
}

function budgetsList() {
  if (!_budgets.length) return '<div class="money-empty-sm">no budgets — cap a category\'s monthly spend</div>';
  const byCat = {}; (_sum?.budgets || []).forEach(b => byCat[b.category] = b);
  return `<div class="budgets">` + _budgets.map(b => {
    const spent = byCat[b.category]?.spent || 0;
    const pct = b.limit_amt > 0 ? Math.min(100, spent / b.limit_amt * 100) : 0;
    const over = b.limit_amt > 0 && spent > b.limit_amt;
    return `<div class="budget-row" data-id="${b.id}">
      <div class="bg-head"><span class="bg-cat">${esc(b.category)}</span>
        <span class="bg-nums ${over ? 'over' : ''}">${fmt(spent)} / ${fmt(b.limit_amt)}</span>
        <button class="bg-del" data-del-budget="${b.id}" title="remove">×</button></div>
      <div class="bg-bar-wrap"><div class="bg-bar ${over ? 'over' : ''}" style="width:${pct}%"></div></div>
    </div>`;
  }).join('') + `</div>`;
}

function rulesList() {
  if (!_rules.length) return '<div class="money-empty-sm">no rules — auto-tag a payee to a category</div>';
  return `<div class="rules">` + _rules.map(r => `
    <div class="rule" data-id="${r.id}">
      <span class="rl-match">${esc(r.match)}</span>
      <span class="rl-arrow">→</span>
      <span class="rl-cat">${esc(r.category) || '<span class="tx-dim">(clear)</span>'}</span>
      <button class="tx-del" data-del-rule="${r.id}" title="delete">×</button>
    </div>`).join('') + `</div>`;
}

function _ruleForm() {
  return `<div class="rule-form">
    <input type="text" id="rl-match" class="settings-input" placeholder="if payee contains…" style="flex:1.2;min-width:120px">
    <span class="rl-arrow">→</span>
    <input type="text" id="rl-cat" class="settings-input" placeholder="category" style="flex:1;min-width:90px">
    <button class="btn" id="rl-add">add</button>
  </div>`;
}

const _cycleShort = { weekly: '/wk', monthly: '/mo', quarterly: '/qtr', yearly: '/yr', custom: '·custom' };

function recurringList() {
  if (!_recurring.length) return '<div class="money-empty-sm">nothing recurring — add rent, salary, a loan…</div>';
  const an = {}; _accounts.forEach(a => an[a.id] = a.name);
  return `<div class="recurs">` + _recurring.map(r => `
    <div class="recur ${r.active ? '' : 'paused'}" data-id="${r.id}">
      <span class="rc-payee">${esc(r.payee) || esc(r.category) || '—'}</span>
      <span class="rc-amt ${r.amount >= 0 ? 'pos' : 'neg'}">${signed(r.amount)}<span class="rc-cyc">${_cycleShort[r.cycle] || ''}</span></span>
      <span class="rc-next" title="next post">${r.active ? esc((r.next_date || '').slice(5)) : 'paused'}</span>
      <button class="btn rc-toggle" data-toggle-rec="${r.id}" title="${r.active ? 'pause' : 'resume'}">${r.active ? 'pause' : 'resume'}</button>
      <button class="tx-del" data-del-rec="${r.id}" title="delete">×</button>
    </div>`).join('') + `</div>`;
}

function _recurringForm() {
  if (!_accounts.length) return '';
  const acctOpts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const first = _accounts[0]?.id || '';
  return `<div class="recur-form">
    <input type="text" id="rc-payee" class="settings-input" placeholder="payee (e.g. rent)" style="flex:1.3;min-width:100px">
    <input type="text" id="rc-cat" class="settings-input" placeholder="category" style="flex:1;min-width:80px">
    <div class="settings-input custom-select" id="rc-sign" data-value="-" data-options="-|expense;+|income" style="width:104px"></div>
    <input type="text" id="rc-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="width:84px">
    <div class="settings-input custom-select" id="rc-cycle" data-value="monthly" data-options="weekly|weekly;monthly|monthly;quarterly|quarterly;yearly|yearly" style="width:120px"></div>
    <div class="date-input" id="rc-next" data-type="date" data-value="${_today()}" data-ph="next date" style="width:128px"></div>
    <div class="settings-input custom-select" id="rc-acct" data-value="${esc(first)}" data-options="${esc(acctOpts)}" style="width:128px"></div>
    <button class="btn primary" id="rc-add">add</button>
  </div>`;
}

function addTxnRow() {
  const acctOpts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const first = _accounts[0]?.id || '';
  return `<div class="txn-add">
    <div class="date-input" id="tx-date" data-type="date" data-value="${_today()}" data-ph="date" style="width:128px"></div>
    <div class="settings-input custom-select" id="tx-acct" data-value="${esc(first)}" data-options="${esc(acctOpts)}" style="width:128px"></div>
    <input type="text" id="tx-payee" class="settings-input" placeholder="payee / what" style="flex:1.4;min-width:120px">
    <input type="text" id="tx-cat" class="settings-input" placeholder="category" style="flex:1;min-width:90px">
    <div class="settings-input custom-select" id="tx-sign" data-value="-" data-options="-|expense;+|income" style="width:106px"></div>
    <input type="text" id="tx-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="width:96px">
    <button class="btn primary" id="tx-add">add</button>
    ${_accounts.length >= 2 ? '<button class="btn" id="tx-transfer-toggle" title="move money between accounts">⇄ transfer</button>' : ''}
  </div>`;
}

function transferRow() {
  if (_accounts.length < 2) return '';
  const opts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const a0 = _accounts[0]?.id || '', a1 = _accounts[1]?.id || '';
  return `<div class="txn-transfer" id="txn-transfer" style="display:none">
    <span class="tr-lbl">move</span>
    <div class="settings-input custom-select" id="tr-from" data-value="${esc(a0)}" data-options="${esc(opts)}" style="width:130px"></div>
    <span class="tr-arrow">→</span>
    <div class="settings-input custom-select" id="tr-to" data-value="${esc(a1)}" data-options="${esc(opts)}" style="width:130px"></div>
    <div class="date-input" id="tr-date" data-type="date" data-value="${_today()}" data-ph="date" style="width:128px"></div>
    <input type="text" id="tr-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="width:96px">
    <button class="btn primary" id="tr-do">transfer</button>
  </div>`;
}

function txnList() {
  if (!_txns.length) return '<div class="money-empty-sm">no transactions this month</div>';
  const an = {}; _accounts.forEach(a => an[a.id] = a.name);
  return `<div class="txns">` + _txns.map(t => {
    if (_editTxn === t.id && !t.transfer_id) return editTxnRow(t);
    // transfer legs aren't inline-editable (editing one would desync the pair) and
    // their × removes the whole transfer, not just this leg
    const xf = !!t.transfer_id;
    const ed = xf ? '' : `data-edit-txn="${t.id}"`;
    return `
    <div class="txn ${xf ? 'is-transfer' : ''}" data-id="${t.id}">
      <span class="tx-date">${(t.date || '').slice(5)}</span>
      <span class="tx-payee" ${ed}>${esc(t.payee) || '<span class="tx-dim">—</span>'}</span>
      <span class="tx-cat" ${ed}>${xf ? '⇄ transfer' : (t.category ? esc(t.category) : '')}</span>
      <span class="tx-acct">${esc(an[t.account_id] || '')}</span>
      <span class="tx-amt ${t.amount >= 0 ? 'pos' : 'neg'}" ${ed}>${signed(t.amount)}</span>
      ${xf
        ? `<button class="tx-del" data-del-transfer="${t.transfer_id}" title="delete transfer (both legs)">×</button>`
        : `<button class="tx-del" data-del-txn="${t.id}" title="delete">×</button>`}
    </div>`;
  }).join('') + `</div>`;
}

function editTxnRow(t) {
  const acctOpts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const neg = (t.amount || 0) < 0;
  return `<div class="txn txn-edit" data-id="${t.id}">
    <div class="date-input" data-f="date" data-type="date" data-value="${esc(t.date || _today())}" data-ph="date" style="width:124px"></div>
    <div class="settings-input custom-select" data-f="account_id" data-value="${esc(t.account_id)}" data-options="${esc(acctOpts)}" style="width:120px"></div>
    <input type="text" class="settings-input" data-f="payee" value="${esc(t.payee || '')}" placeholder="payee" style="flex:1.4;min-width:90px">
    <input type="text" class="settings-input" data-f="category" value="${esc(t.category || '')}" placeholder="category" style="flex:1;min-width:80px">
    <div class="settings-input custom-select" data-f="sign" data-value="${neg ? '-' : '+'}" data-options="-|expense;+|income" style="width:100px"></div>
    <input type="text" class="settings-input" data-f="amount" value="${Math.abs(t.amount || 0)}" inputmode="decimal" style="width:84px">
    <button class="btn primary" data-save-txn="${t.id}">save</button>
    <button class="btn" data-cancel-txn="${t.id}">×</button>
  </div>`;
}

// ── inline forms ──────────────────────────────────────────────────────────────
function _accountForm() {
  return `<div class="acct-form" id="acct-form">
    <input type="text" id="af-name" class="settings-input" placeholder="account name (e.g. checking)" style="flex:1;min-width:150px">
    <div class="settings-input custom-select" id="af-kind" data-value="checking" data-options="checking|checking;savings|savings;cash|cash;credit|credit card;investment|investment" style="width:150px"></div>
    <input type="text" id="af-open" class="settings-input" placeholder="opening balance" inputmode="decimal" style="width:140px">
    <button class="btn primary" id="af-add">add account</button>
  </div>`;
}
function _budgetForm() {
  return `<div class="budget-form">
    <input type="text" id="bf-cat" class="settings-input" placeholder="category" style="flex:1;min-width:110px">
    <input type="text" id="bf-amt" class="settings-input" placeholder="monthly cap" inputmode="decimal" style="width:120px">
    <button class="btn" id="bf-add">set</button>
  </div>`;
}

// init the app's custom dropdowns + date pickers in the money panel (both self-guard)
function _initControls() {
  document.querySelectorAll('#money-body .custom-select').forEach(initCustomDropdown);
  document.querySelectorAll('#money-body .date-input').forEach(initDatePicker);
}

// ── wiring ──────────────────────────────────────────────────────────────────
function _wireAccountForm() {
  _initControls();
  $('af-add')?.addEventListener('click', addAccount);
}
function wire() {
  _initControls();
  $('tx-add')?.addEventListener('click', addTxn);
  $('tx-amt')?.addEventListener('keydown', e => { if (e.key === 'Enter') addTxn(); });
  $('money-add-acct')?.addEventListener('click', () => {
    const wrap = $('money-acct-form-wrap');
    if (wrap.innerHTML) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = _accountForm();
    _initControls();
    $('af-add')?.addEventListener('click', addAccount);
    $('af-name')?.focus();
  });
  $('bf-add')?.addEventListener('click', addBudget);
  $('tx-transfer-toggle')?.addEventListener('click', () => {
    const f = $('txn-transfer'); if (!f) return;
    f.style.display = f.style.display === 'none' ? 'flex' : 'none';
    if (f.style.display !== 'none') $('tr-amt')?.focus();
  });
  $('tr-do')?.addEventListener('click', doTransfer);
  $('tr-amt')?.addEventListener('keydown', e => { if (e.key === 'Enter') doTransfer(); });
  $('money-body').querySelectorAll('[data-del-transfer]').forEach(b => b.addEventListener('click', () => delTransfer(b.dataset.delTransfer)));
  $('money-body').querySelectorAll('[data-del-txn]').forEach(b => b.addEventListener('click', () => delTxn(b.dataset.delTxn)));
  $('money-body').querySelectorAll('[data-edit-txn]').forEach(el => el.addEventListener('click', () => { _editTxn = el.dataset.editTxn; render(); }));
  $('money-body').querySelectorAll('[data-save-txn]').forEach(b => b.addEventListener('click', () => saveTxn(b.dataset.saveTxn)));
  $('money-body').querySelectorAll('[data-cancel-txn]').forEach(b => b.addEventListener('click', () => { _editTxn = null; render(); }));
  $('money-body').querySelectorAll('[data-del-acct]').forEach(b => b.addEventListener('click', () => delAccount(b.dataset.delAcct)));
  $('money-body').querySelectorAll('[data-del-budget]').forEach(b => b.addEventListener('click', () => delBudget(b.dataset.delBudget)));
  $('rc-add')?.addEventListener('click', addRecurring);
  $('money-body').querySelectorAll('[data-del-rec]').forEach(b => b.addEventListener('click', () => delRecurring(b.dataset.delRec)));
  $('money-body').querySelectorAll('[data-toggle-rec]').forEach(b => b.addEventListener('click', () => toggleRecurring(b.dataset.toggleRec)));
  $('rl-add')?.addEventListener('click', addRule);
  $('rl-cat')?.addEventListener('keydown', e => { if (e.key === 'Enter') addRule(); });
  $('rules-apply')?.addEventListener('click', applyRules);
  $('money-body').querySelectorAll('[data-del-rule]').forEach(b => b.addEventListener('click', () => delRule(b.dataset.delRule)));
}

// ── actions ────────────────────────────────────────────────────────────────
async function addAccount() {
  const name = $('af-name')?.value.trim();
  if (!name) { toast('name the account', 'error'); return; }
  const opening = parseFloat($('af-open')?.value) || 0;
  try {
    await api('/api/money/accounts', { method: 'POST', body: { name, kind: getDropdownValue($('af-kind')), opening } });
    await load();
  } catch { toast('couldn\'t add account', 'error'); }
}
async function delAccount(id) {
  if (!await dlgConfirm('delete this account and all its transactions?')) return;
  try { await api(`/api/money/accounts/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function addTxn() {
  const amtRaw = parseFloat($('tx-amt')?.value);
  if (!amtRaw || amtRaw <= 0) { toast('enter an amount', 'error'); return; }
  const sign = getDropdownValue($('tx-sign')) === '+' ? 1 : -1;
  try {
    await api('/api/money/transactions', { method: 'POST', body: {
      account_id: getDropdownValue($('tx-acct')), date: $('tx-date')?.dataset.value || _today(),
      amount: sign * amtRaw, category: $('tx-cat').value.trim(), payee: $('tx-payee').value.trim(),
    } });
    await load();
  } catch { toast('couldn\'t add transaction', 'error'); }
}
async function delTxn(id) {
  try { await api(`/api/money/transactions/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function doTransfer() {
  const from = getDropdownValue($('tr-from')), to = getDropdownValue($('tr-to'));
  const amt = parseFloat($('tr-amt')?.value);
  if (!amt || amt <= 0) { toast('enter an amount', 'error'); return; }
  if (from === to) { toast('pick two different accounts', 'error'); return; }
  try {
    await api('/api/money/transfer', { method: 'POST', body: {
      from_account: from, to_account: to, amount: amt, date: $('tr-date')?.dataset.value || _today(),
    } });
    toast('transferred', 'success');
    await load();
  } catch { toast('transfer failed', 'error'); }
}
async function delTransfer(tid) {
  if (!await dlgConfirm('delete this transfer (removes both legs)?')) return;
  try { await api(`/api/money/transfer/${tid}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function saveTxn(id) {
  const row = $('money-body').querySelector(`.txn-edit[data-id="${id}"]`);
  if (!row) return;
  const f = name => row.querySelector(`[data-f="${name}"]`);
  const amtRaw = parseFloat(f('amount')?.value);
  if (!amtRaw || amtRaw <= 0) { toast('enter an amount', 'error'); return; }
  const sign = getDropdownValue(f('sign')) === '+' ? 1 : -1;
  try {
    await api(`/api/money/transactions/${id}`, { method: 'PATCH', body: {
      account_id: getDropdownValue(f('account_id')), date: f('date')?.dataset.value || _today(),
      amount: sign * amtRaw, category: f('category').value.trim(), payee: f('payee').value.trim(),
    } });
    _editTxn = null;
    await load();
  } catch { toast('save failed', 'error'); }
}
async function addBudget() {
  const category = $('bf-cat')?.value.trim();
  const limit_amt = parseFloat($('bf-amt')?.value) || 0;
  if (!category) { toast('pick a category', 'error'); return; }
  try { await api('/api/money/budgets', { method: 'POST', body: { category, limit_amt } }); await load(); }
  catch { toast('couldn\'t set budget', 'error'); }
}
async function delBudget(id) {
  try { await api(`/api/money/budgets/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function addRecurring() {
  const payee = $('rc-payee')?.value.trim();
  const amtRaw = parseFloat($('rc-amt')?.value);
  if (!payee && !$('rc-cat')?.value.trim()) { toast('give it a payee or category', 'error'); return; }
  if (!amtRaw || amtRaw <= 0) { toast('enter an amount', 'error'); return; }
  const sign = getDropdownValue($('rc-sign')) === '+' ? 1 : -1;
  try {
    await api('/api/money/recurring', { method: 'POST', body: {
      account_id: getDropdownValue($('rc-acct')), amount: sign * amtRaw,
      category: $('rc-cat').value.trim(), payee, cycle: getDropdownValue($('rc-cycle')),
      next_date: $('rc-next')?.dataset.value || _today(),
    } });
    await load();
  } catch { toast('couldn\'t add recurring', 'error'); }
}
async function delRecurring(id) {
  if (!await dlgConfirm('stop this recurring transaction?')) return;
  try { await api(`/api/money/recurring/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function toggleRecurring(id) {
  const r = _recurring.find(x => x.id === id);
  try { await api(`/api/money/recurring/${id}`, { method: 'PATCH', body: { active: !r.active } }); await load(); }
  catch { toast('update failed', 'error'); }
}
async function addRule() {
  const match = $('rl-match')?.value.trim();
  if (!match) { toast('what should it match?', 'error'); return; }
  try {
    await api('/api/money/rules', { method: 'POST', body: { match, category: $('rl-cat').value.trim() } });
    await load();
  } catch { toast('couldn\'t add rule', 'error'); }
}
async function delRule(id) {
  try { await api(`/api/money/rules/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function applyRules() {
  try {
    const r = await api('/api/money/rules/apply', { method: 'POST' });
    toast(r.updated ? `categorized ${r.updated} transaction${r.updated === 1 ? '' : 's'}` : 'nothing to categorize', 'success');
    await load();
  } catch { toast('apply failed', 'error'); }
}
