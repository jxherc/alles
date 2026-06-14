// money: accounts, transactions, budgets, and a couple of charts. plain SVG for
// the charts (no chart lib), api() helper for the fetches.
import { api, toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';

let _month = _thisMonth();
let _accounts = [], _txns = [], _budgets = [], _sum = null;
let _cur = '$';
let _inited = false;

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
  }
  load();
}

async function load() {
  const lbl = $('money-month-label'); if (lbl) lbl.textContent = _monthLabel(_month);
  try {
    [_accounts, _txns, _budgets, _sum] = await Promise.all([
      api('/api/money/accounts'),
      api(`/api/money/transactions?month=${_month}`),
      api('/api/money/budgets'),
      api(`/api/money/summary?month=${_month}`),
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
     </div>` +
    `<section class="money-card money-txns"><h3>transactions · ${_monthLabel(_month)}</h3>${addTxnRow()}${txnList()}</section>`;
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

function _catOptions() {
  const cats = [...new Set([..._txns.map(t => t.category), ...(_sum?.by_category || []).map(c => c[0]), ..._budgets.map(b => b.category)].filter(Boolean))];
  return cats.map(c => `<option value="${esc(c)}">`).join('');
}

function addTxnRow() {
  const opts = _accounts.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
  return `<div class="txn-add">
    <input type="date" id="tx-date" class="settings-input" value="${_today()}">
    <select id="tx-acct" class="settings-input">${opts}</select>
    <input type="text" id="tx-payee" class="settings-input" placeholder="payee / what" style="flex:1.4">
    <input type="text" id="tx-cat" class="settings-input" placeholder="category" list="tx-cats" style="flex:1"><datalist id="tx-cats">${_catOptions()}</datalist>
    <select id="tx-sign" class="settings-input" style="width:90px"><option value="-">expense</option><option value="+">income</option></select>
    <input type="text" id="tx-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="width:90px">
    <button class="btn primary" id="tx-add">add</button>
  </div>`;
}

function txnList() {
  if (!_txns.length) return '<div class="money-empty-sm">no transactions this month</div>';
  const an = {}; _accounts.forEach(a => an[a.id] = a.name);
  return `<div class="txns">` + _txns.map(t => `
    <div class="txn" data-id="${t.id}">
      <span class="tx-date">${(t.date || '').slice(5)}</span>
      <span class="tx-payee">${esc(t.payee) || '<span class="tx-dim">—</span>'}</span>
      <span class="tx-cat">${t.category ? esc(t.category) : ''}</span>
      <span class="tx-acct">${esc(an[t.account_id] || '')}</span>
      <span class="tx-amt ${t.amount >= 0 ? 'pos' : 'neg'}">${signed(t.amount)}</span>
      <button class="tx-del" data-del-txn="${t.id}" title="delete">×</button>
    </div>`).join('') + `</div>`;
}

// ── inline forms ──────────────────────────────────────────────────────────────
function _accountForm() {
  return `<div class="acct-form" id="acct-form">
    <input type="text" id="af-name" class="settings-input" placeholder="account name (e.g. checking)">
    <select id="af-kind" class="settings-input"><option value="checking">checking</option><option value="savings">savings</option><option value="cash">cash</option><option value="credit">credit card</option><option value="investment">investment</option></select>
    <input type="text" id="af-open" class="settings-input" placeholder="opening balance" inputmode="decimal" style="width:130px">
    <button class="btn primary" id="af-add">add account</button>
  </div>`;
}
function _budgetForm() {
  return `<div class="budget-form">
    <input type="text" id="bf-cat" class="settings-input" placeholder="category" list="tx-cats" style="flex:1">
    <input type="text" id="bf-amt" class="settings-input" placeholder="monthly cap" inputmode="decimal" style="width:110px">
    <button class="btn" id="bf-add">set</button>
  </div>`;
}

// ── wiring ──────────────────────────────────────────────────────────────────
function _wireAccountForm() {
  $('af-add')?.addEventListener('click', addAccount);
}
function wire() {
  $('tx-add')?.addEventListener('click', addTxn);
  $('tx-amt')?.addEventListener('keydown', e => { if (e.key === 'Enter') addTxn(); });
  $('money-add-acct')?.addEventListener('click', () => {
    const wrap = $('money-acct-form-wrap');
    if (wrap.innerHTML) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = _accountForm();
    _wireAccountForm();
    $('af-name')?.focus();
  });
  $('bf-add')?.addEventListener('click', addBudget);
  $('money-body').querySelectorAll('[data-del-txn]').forEach(b => b.addEventListener('click', () => delTxn(b.dataset.delTxn)));
  $('money-body').querySelectorAll('[data-del-acct]').forEach(b => b.addEventListener('click', () => delAccount(b.dataset.delAcct)));
  $('money-body').querySelectorAll('[data-del-budget]').forEach(b => b.addEventListener('click', () => delBudget(b.dataset.delBudget)));
}

// ── actions ────────────────────────────────────────────────────────────────
async function addAccount() {
  const name = $('af-name')?.value.trim();
  if (!name) { toast('name the account', 'error'); return; }
  const opening = parseFloat($('af-open')?.value) || 0;
  try {
    await api('/api/money/accounts', { method: 'POST', body: { name, kind: $('af-kind').value, opening } });
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
  const sign = $('tx-sign').value === '+' ? 1 : -1;
  try {
    await api('/api/money/transactions', { method: 'POST', body: {
      account_id: $('tx-acct').value, date: $('tx-date').value || _today(),
      amount: sign * amtRaw, category: $('tx-cat').value.trim(), payee: $('tx-payee').value.trim(),
    } });
    await load();
  } catch { toast('couldn\'t add transaction', 'error'); }
}
async function delTxn(id) {
  try { await api(`/api/money/transactions/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
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
