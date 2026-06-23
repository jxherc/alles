// money: accounts, transactions, budgets, and a couple of charts. plain SVG for
// the charts (no chart lib), api() helper for the fetches.
import { api, toast } from './util.js';
import { confirm as dlgConfirm, fields as dlgFields } from './dialog.js';
import { initCustomDropdown, getDropdownValue } from './dropdown.js';
import { initDatePicker } from './datepick.js';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function _thisMonth() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; }
function _monthFromUrl() { const m = new URLSearchParams(location.search).get('m'); return (m && /^\d{4}-\d{2}$/.test(m)) ? m : ''; }
function _setMonthUrl() { try { const u = new URL(location.href); u.searchParams.set('m', _month); history.replaceState(null, '', u); } catch {} }

let _month = _monthFromUrl() || _thisMonth();
let _accounts = [], _txns = [], _budgets = [], _sum = null, _recurring = [], _rules = [];
let _envelope = null, _aom = null;   // YNAB envelope view + age of money (4b)
let _forecast = null, _nwhist = [], _holdings = null, _alerts = null;   // Simplifi (4c)
let _goals = [];   // savings/debt goals (4d)
let _searchResults = null;   // array when a search/filter is active, else null
let _searchTimer = null;
let _cur = '$';
let _inited = false;
let _editTxn = null;   // id of the txn row currently being edited inline
let _splitTxn = null;  // id of the txn whose split editor is open (4a)
let _splitRows = [];   // working split rows in the open editor
let _tagFilter = '';   // active tag filter (4a)
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
  _setMonthUrl();
  _searchResults = null;   // month change / reload clears any active search
  try {
    // post any due recurring txns FIRST (and advance them) so the balances,
    // transactions and summary we read next all reflect them — no stale first load
    _recurring = await api('/api/money/recurring').catch(() => []);
    [_accounts, _txns, _budgets, _sum, _rules, _envelope, _aom, _forecast, _nwhist, _holdings, _alerts] = await Promise.all([
      api('/api/money/accounts'),
      api(`/api/money/transactions?month=${_month}`),
      api('/api/money/budgets'),
      api(`/api/money/summary?month=${_month}`),
      api('/api/money/rules').catch(() => []),
      api(`/api/money/envelope?month=${_month}`).catch(() => null),
      api('/api/money/age-of-money').catch(() => null),
      api(`/api/money/forecast?month=${_month}`).catch(() => null),
      api('/api/money/networth-history?months=6').catch(() => []),
      api('/api/money/holdings').catch(() => null),
      api(`/api/money/alerts?month=${_month}`).catch(() => null),
    ]);
    _goals = (await api('/api/money/goals').catch(() => null))?.goals || [];
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
    alertsStrip() +
    `<div class="money-grid">
      <section class="money-card" data-card="accounts"><h3>accounts</h3>${accountsList()}<div id="money-acct-form-wrap"></div>
        <button class="btn money-add-acct" id="money-add-acct">+ account</button></section>
      <section class="money-card" data-card="category"><h3>spending by category</h3>${catChart()}</section>
      <section class="money-card" data-card="trend"><h3>last 6 months</h3>${trendChart()}</section>
      <section class="money-card" data-card="networth"><h3>net worth over time</h3>${networthCard()}</section>
      <section class="money-card money-envelope" data-card="envelope"><h3>envelope budgeting${_aom && _aom.age != null ? ` <span class="aom" title="age of money — days between income arriving and being spent">age of money: ${_aom.age}d</span>` : ''}</h3>${envelopeCard()}</section>
      <section class="money-card" data-card="holdings"><h3>investments</h3>${holdingsCard()}</section>
      <section class="money-card" data-card="goals"><h3>goals</h3>${goalsCard()}</section>
      <section class="money-card" data-card="reports"><h3>reports</h3>${reportsCard()}</section>
      <section class="money-card" data-card="budgets"><h3>budgets</h3>${budgetsList()}${_budgetForm()}</section>
      <section class="money-card" data-card="recurring"><h3>recurring</h3>${recurringList()}${_recurringForm()}</section>
      <section class="money-card" data-card="rules"><h3>auto-categorize${_rules.length ? ` <button class="btn rules-apply" id="rules-apply" title="apply to existing uncategorized">apply</button>` : ''}</h3>${rulesList()}${_ruleForm()}</section>
     </div>` +
    `<section class="money-card money-txns">
      <h3>transactions · ${_monthLabel(_month)}
        <span class="txn-search-wrap">
          <input type="text" id="txn-search" class="settings-input" placeholder="search payee / category / notes" autocomplete="off">
          <input type="text" id="txn-min" class="settings-input" placeholder="min $" inputmode="decimal" title="min amount">
          <input type="text" id="txn-max" class="settings-input" placeholder="max $" inputmode="decimal" title="max amount">
        </span>
      </h3>
      ${addTxnRow()}${transferRow()}
      <div id="txn-rows">${txnList()}</div>
    </section>`;
  wire();
}

function summaryCards() {
  const s = _sum || {};
  return `<div class="money-summary">
    <div class="ms-card"><span class="ms-label">net worth</span><span class="ms-val">${fmt(s.net_worth)}</span></div>
    <div class="ms-card"><span class="ms-label">income · this month</span><span class="ms-val pos">${fmt(s.income)}</span></div>
    <div class="ms-card"><span class="ms-label">spent · this month</span><span class="ms-val neg">${fmt(s.expense)}</span></div>
    <div class="ms-card"><span class="ms-label">net</span><span class="ms-val ${s.net >= 0 ? 'pos' : 'neg'}">${signed(s.net || 0)}</span></div>
    ${_forecast ? `<div class="ms-card"><span class="ms-label">projected · month-end</span><span class="ms-val ${(_forecast.projected || 0) < 0 ? 'neg' : ''}">${fmt(_forecast.projected || 0)}</span></div>` : ''}
  </div>`;
}

function alertsStrip() {
  const a = _alerts; if (!a) return '';
  const items = [];
  (a.upcoming_bills || []).forEach(b => items.push(`<span class="alert-chip bill">📅 ${esc(b.payee)} ${signed(b.amount)} in ${b.days}d</span>`));
  (a.large_purchases || []).forEach(p => items.push(`<span class="alert-chip big">⚠ large: ${esc(p.payee) || esc(p.category) || '—'} ${signed(p.amount)}</span>`));
  (a.watch_hits || []).forEach(w => items.push(`<span class="alert-chip watch">👁 ${esc(w.watch)}: ${esc(w.payee) || '—'} ${signed(w.amount)}</span>`));
  (a.low_balance || []).forEach(l => items.push(`<span class="alert-chip big">🔻 ${esc(l.name)} low: ${fmt(l.balance)} < ${fmt(l.threshold)}</span>`));
  if (!items.length) return '';
  return `<div class="money-alerts">${items.join('')}</div>`;
}

function networthCard() {
  const h = _nwhist || [];
  if (h.length < 2) return '<div class="money-empty-sm">not enough history yet</div>';
  const vals = h.map(x => x.net_worth);
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  const W = 280, H = 110, step = W / (h.length - 1);
  const pts = h.map((x, i) => `${(i * step).toFixed(1)},${(H - ((x.net_worth - min) / span) * (H - 16) - 8).toFixed(1)}`);
  const labels = h.map((x, i) => `<span style="width:${100 / h.length}%">${x.month.slice(5)}</span>`).join('');
  return `<svg class="nw-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts.join(' ')}" fill="none" stroke="var(--accent)" stroke-width="2"></polyline></svg>
    <div class="trend-labels">${labels}</div>
    <div class="nw-now">now: ${fmt(vals[vals.length - 1])}</div>
    <div class="nw-base"><input type="text" id="nw-base-cur" class="settings-input" placeholder="base (USD/EUR…)" style="width:120px"><button class="btn" id="nw-base-go">in base ↺</button><span id="nw-base-out" class="nw-base-out"></span></div>`;
}

function goalsCard() {
  const rows = (_goals || []).map(g => {
    const pct = Math.round((g.progress || 0) * 100);
    const eta = g.eta_months === 0 ? 'reached 🎉' : (g.eta_months != null ? `~${g.eta_months}mo left` : 'set a monthly amount');
    return `<div class="goal-row" data-id="${g.id}">
      <div class="goal-head"><span class="goal-name">${esc(g.name)} <span class="goal-kind">${esc(g.kind)}</span></span>
        <span class="goal-nums">${fmt(g.current)} / ${fmt(g.target)}</span>
        <button class="tx-del" data-del-goal="${g.id}" title="remove">×</button></div>
      <div class="goal-bar-wrap"><div class="goal-bar" style="width:${pct}%"></div></div>
      <div class="goal-eta">${pct}% · ${eta}</div>
    </div>`;
  }).join('');
  return `<div class="goals">${rows || '<div class="money-empty-sm">no goals — set a savings or debt-payoff goal</div>'}</div>
    <div class="goal-form">
      <input type="text" id="gl-name" class="settings-input" placeholder="goal name" style="flex:1;min-width:100px">
      <div class="settings-input custom-select" id="gl-kind" data-value="savings" data-options="savings|savings;debt|debt payoff" style="width:120px"></div>
      <input type="text" id="gl-target" class="settings-input" placeholder="target" inputmode="decimal" style="width:80px">
      <input type="text" id="gl-current" class="settings-input" placeholder="current" inputmode="decimal" style="width:80px">
      <input type="text" id="gl-monthly" class="settings-input" placeholder="monthly" inputmode="decimal" style="width:80px">
      <button class="btn" id="gl-add">add</button>
    </div>`;
}

function reportsCard() {
  return `<div class="report-form">
      <div class="date-input" id="rp-start" data-type="date" data-value="" data-ph="start" style="width:128px"></div>
      <div class="date-input" id="rp-end" data-type="date" data-value="" data-ph="end" style="width:128px"></div>
      <button class="btn" id="rp-run">run</button>
      <a class="btn" id="rp-export" href="#" style="display:none">export csv</a>
    </div>
    <div id="rp-out" class="report-out"></div>`;
}

function holdingsCard() {
  const d = _holdings;
  const rows = (d?.holdings || []).map(h => `
    <div class="hold-row" data-id="${h.id}">
      <span class="hold-sym">${esc(h.symbol)}</span>
      <span class="hold-qty">${h.qty}×${fmt(h.price)}</span>
      <span class="hold-val">${fmt(h.value)}</span>
      <span class="hold-gain ${h.gain >= 0 ? 'pos' : 'neg'}">${signed(h.gain)} (${h.gain_pct}%)</span>
      <button class="tx-del" data-del-hold="${h.id}" title="remove">×</button>
    </div>`).join('');
  const tot = d?.totals || {};
  const totRow = (d?.holdings || []).length
    ? `<div class="hold-total">total ${fmt(tot.value || 0)} · <span class="${(tot.gain || 0) >= 0 ? 'pos' : 'neg'}">${signed(tot.gain || 0)}</span></div>`
    : '<div class="money-empty-sm">no holdings — add a stock/fund below</div>';
  return `<div class="holds">${rows}</div>${totRow}
    <div class="hold-form">
      <input type="text" id="hd-sym" class="settings-input" placeholder="symbol" style="width:80px">
      <input type="text" id="hd-qty" class="settings-input" placeholder="qty" inputmode="decimal" style="width:64px">
      <input type="text" id="hd-cost" class="settings-input" placeholder="cost/sh" inputmode="decimal" style="width:74px">
      <input type="text" id="hd-price" class="settings-input" placeholder="price" inputmode="decimal" style="width:64px">
      <button class="btn" id="hd-add">add</button>
    </div>`;
}

function accountsList() {
  return `<div class="money-accts">` + _accounts.map(a => `
    <div class="money-acct ${a.archived ? 'arch' : ''}" data-id="${a.id}">
      <div class="ma-top"><span class="ma-name">${esc(a.name)}</span>
        <button class="ma-rc" data-rc-acct="${a.id}" title="reconcile to a statement">⚖</button>
        <button class="ma-del" data-del-acct="${a.id}" title="delete">×</button></div>
      <div class="ma-bal ${a.balance < 0 ? 'neg' : ''}">${fmt(a.balance)}</div>
      <div class="ma-kind">${esc(a.kind)}</div>
      <div class="rc-panel" id="rc-panel-${a.id}" style="display:none">
        <input type="text" class="settings-input" id="rc-stmt-${a.id}" placeholder="statement balance" inputmode="decimal">
        <button class="btn" data-rc-run="${a.id}">check</button>
        <div class="rc-out" id="rc-out-${a.id}"></div>
      </div>
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

function envelopeCard() {
  const e = _envelope;
  if (!e) return '<div class="money-empty-sm">no envelope data</div>';
  const tbb = e.to_be_budgeted || 0;
  const banner = `<div class="env-tbb ${tbb < 0 ? 'over' : (tbb > 0 ? 'pos' : '')}">
    <span class="env-tbb-num">${signed(tbb)}</span><span class="env-tbb-lbl">to be budgeted</span></div>`;
  const rows = (e.categories || []).filter(c => c.assigned || c.spent || c.available || c.target).map(c => {
    const av = c.available || 0;
    const tgt = c.target
      ? `<div class="env-target"><div class="env-target-bar" style="width:${Math.min(100, (c.target.funded || 0) * 100)}%"></div><span class="env-target-lbl">${Math.round((c.target.funded || 0) * 100)}% of ${fmt(c.target.amount)}${c.target.date ? ` by ${esc(c.target.date)}` : ''}</span></div>`
      : '';
    return `<div class="env-row" data-cat="${esc(c.category)}">
      <span class="env-cat">${esc(c.category)} <button class="env-tgt-btn" data-cat="${esc(c.category)}" title="set a funding target">🎯</button></span>
      <input type="text" class="settings-input env-assign" data-cat="${esc(c.category)}" value="${c.assigned || 0}" inputmode="decimal" title="assigned this month">
      <span class="env-spent" title="spent this month">${fmt(c.spent || 0)}</span>
      <span class="env-avail ${av < 0 ? 'neg' : 'pos'}" title="available (rolls over)">${fmt(av)}</span>
      ${tgt}
    </div>`;
  }).join('');
  return banner + (rows
    ? `<div class="env-rows">${rows}</div>`
    : '<div class="money-empty-sm">assign money to a category to start budgeting</div>') +
    `<div class="env-add"><input type="text" id="env-new-cat" class="settings-input" placeholder="category" style="flex:1"><input type="text" id="env-new-amt" class="settings-input" placeholder="assign" inputmode="decimal" style="width:90px"><button class="btn" id="env-assign-btn">assign</button></div>`;
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
    <input type="text" id="tx-tags" class="settings-input" placeholder="tags (comma)" style="flex:1;min-width:90px">
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
  const rows = _searchResults !== null ? _searchResults : _txns;
  const banner = _tagFilter
    ? `<div class="txn-tagfilter">filtered by tag <span class="tx-tag">${esc(_tagFilter)}</span><button class="btn" id="tag-clear">clear</button></div>`
    : '';
  if (!rows.length) return banner + `<div class="money-empty-sm">${(_searchResults !== null || _tagFilter) ? 'no matches' : 'no transactions this month'}</div>`;
  const an = {}; _accounts.forEach(a => an[a.id] = a.name);
  return banner + `<div class="txns">` + rows.map(t => {
    const main = _renderTxnMain(t, an);
    return main + (_splitTxn === t.id ? splitEditorRow(t) : '');
  }).join('') + `</div>`;
}

function _renderTxnMain(t, an) {
  if (_editTxn === t.id && !t.transfer_id) return editTxnRow(t);
  // transfer legs aren't inline-editable (editing one would desync the pair) and
  // their × removes the whole transfer, not just this leg
  const xf = !!t.transfer_id;
  const ed = xf ? '' : `data-edit-txn="${t.id}"`;
  const tags = (t.tags || '').split(',').filter(Boolean)
    .map(tg => `<span class="tx-tag" data-tag="${esc(tg)}" title="filter by ${esc(tg)}">${esc(tg)}</span>`).join('');
  const canSplit = (t.amount || 0) < 0;  // only an expense divides across categories (matches the api)
  const actions = xf ? '' : `<span class="tx-actions">
    <button class="tx-clear ${t.cleared ? 'on' : ''}" data-clear-txn="${t.id}" title="${t.cleared ? 'cleared' : 'mark cleared'}">${t.cleared ? '✓' : '○'}</button>
    ${canSplit ? `<button class="tx-split-btn ${t.split ? 'on' : ''}" data-split-txn="${t.id}" title="split across categories">${t.split ? '⊟' : '⊞'}</button>` : ''}
    ${t.receipt_id
      ? `<a class="tx-receipt" href="/api/uploads/${esc(t.receipt_id)}" target="_blank" rel="noopener" title="view receipt">📎</a>`
      : `<button class="tx-receipt-btn" data-receipt-txn="${t.id}" title="attach receipt">📎</button>`}
  </span>`;
  return `
    <div class="txn ${xf ? 'is-transfer' : ''}" data-id="${t.id}">
      <span class="tx-date">${(t.date || '').slice(5)}</span>
      <span class="tx-payee" ${ed}>${esc(t.payee) || '<span class="tx-dim">—</span>'}</span>
      <span class="tx-cat" ${ed}>${xf ? '⇄ transfer' : (t.category ? esc(t.category) : '')}</span>
      ${xf ? '' : `<span class="tx-tags">${tags}</span>`}
      <span class="tx-acct">${esc(an[t.account_id] || '')}</span>
      <span class="tx-amt ${t.amount >= 0 ? 'pos' : 'neg'}" ${ed}>${signed(t.amount)}</span>
      ${actions}
      ${xf
        ? `<button class="tx-del" data-del-transfer="${t.transfer_id}" title="delete transfer (both legs)">×</button>`
        : `<button class="tx-del" data-del-txn="${t.id}" title="delete">×</button>`}
    </div>`;
}

function splitEditorRow(t) {
  const rows = (_splitRows.length ? _splitRows : [{ category: '', amount: '' }]).map((s, i) => `
    <div class="split-row" data-i="${i}">
      <input type="text" class="settings-input split-cat" value="${esc(s.category || '')}" placeholder="category" style="flex:1">
      <input type="text" class="settings-input split-amt" value="${esc(String(s.amount || ''))}" placeholder="amount" inputmode="decimal" style="width:90px">
      <button class="btn split-row-del" data-i="${i}" title="remove">×</button>
    </div>`).join('');
  return `<div class="txn-split-editor" data-id="${t.id}">
    <div class="split-head">split ${fmt(Math.abs(t.amount || 0))} across categories</div>
    ${rows}
    <div class="split-actions">
      <button class="btn" id="split-add-row">+ row</button>
      <button class="btn primary" id="split-save" data-id="${t.id}">save</button>
      <button class="btn" id="split-cancel">cancel</button>
    </div>
  </div>`;
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
    <input type="text" id="af-low" class="settings-input" placeholder="low-bal alert" inputmode="decimal" style="width:110px" title="alert when balance drops below this (0 = off)">
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
  _wireEnvelope();
  $('hd-add')?.addEventListener('click', addHolding);
  $('money-body').querySelectorAll('[data-del-hold]').forEach(b => b.addEventListener('click', () => delHolding(b.dataset.delHold)));
  $('gl-add')?.addEventListener('click', addGoal);
  $('money-body').querySelectorAll('[data-del-goal]').forEach(b => b.addEventListener('click', () => delGoal(b.dataset.delGoal)));
  $('rp-run')?.addEventListener('click', runReport);
  $('nw-base-go')?.addEventListener('click', runBaseNw);
  _decorateCards();
  $('tx-transfer-toggle')?.addEventListener('click', () => {
    const f = $('txn-transfer'); if (!f) return;
    f.style.display = f.style.display === 'none' ? 'flex' : 'none';
    if (f.style.display !== 'none') $('tr-amt')?.focus();
  });
  $('tr-do')?.addEventListener('click', doTransfer);
  $('tr-amt')?.addEventListener('keydown', e => { if (e.key === 'Enter') doTransfer(); });
  ['txn-search', 'txn-min', 'txn-max'].forEach(id => $(id)?.addEventListener('input', () => {
    clearTimeout(_searchTimer); _searchTimer = setTimeout(applySearch, 220);
  }));
  _wireTxnRows();
  $('money-body').querySelectorAll('[data-del-acct]').forEach(b => b.addEventListener('click', () => delAccount(b.dataset.delAcct)));
  $('money-body').querySelectorAll('[data-rc-acct]').forEach(b => b.addEventListener('click', () => toggleReconcile(b.dataset.rcAcct)));
  $('money-body').querySelectorAll('[data-rc-run]').forEach(b => b.addEventListener('click', () => runReconcile(b.dataset.rcRun)));
  $('money-body').querySelectorAll('[data-del-budget]').forEach(b => b.addEventListener('click', () => delBudget(b.dataset.delBudget)));
  $('rc-add')?.addEventListener('click', addRecurring);
  $('money-body').querySelectorAll('[data-del-rec]').forEach(b => b.addEventListener('click', () => delRecurring(b.dataset.delRec)));
  $('money-body').querySelectorAll('[data-toggle-rec]').forEach(b => b.addEventListener('click', () => toggleRecurring(b.dataset.toggleRec)));
  $('rl-add')?.addEventListener('click', addRule);
  $('rl-cat')?.addEventListener('keydown', e => { if (e.key === 'Enter') addRule(); });
  $('rules-apply')?.addEventListener('click', applyRules);
  $('money-body').querySelectorAll('[data-del-rule]').forEach(b => b.addEventListener('click', () => delRule(b.dataset.delRule)));
}

// wire the txn row buttons within a root (the whole #txn-rows list); called on full
// render and again after a search replaces just the list
function _wireTxnRows() {
  const root = $('txn-rows'); if (!root) return;
  root.querySelectorAll('.txn-edit .custom-select').forEach(initCustomDropdown);
  root.querySelectorAll('.txn-edit .date-input').forEach(initDatePicker);
  root.querySelectorAll('[data-del-transfer]').forEach(b => b.addEventListener('click', () => delTransfer(b.dataset.delTransfer)));
  root.querySelectorAll('[data-del-txn]').forEach(b => b.addEventListener('click', () => delTxn(b.dataset.delTxn)));
  root.querySelectorAll('[data-edit-txn]').forEach(el => el.addEventListener('click', () => { _editTxn = el.dataset.editTxn; render(); }));
  root.querySelectorAll('[data-save-txn]').forEach(b => b.addEventListener('click', () => saveTxn(b.dataset.saveTxn)));
  root.querySelectorAll('[data-cancel-txn]').forEach(b => b.addEventListener('click', () => { _editTxn = null; render(); }));
  // 4a actions
  root.querySelectorAll('[data-clear-txn]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); toggleCleared(b.dataset.clearTxn); }));
  root.querySelectorAll('[data-split-txn]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); toggleSplit(b.dataset.splitTxn); }));
  root.querySelectorAll('[data-receipt-txn]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); attachReceipt(b.dataset.receiptTxn); }));
  root.querySelectorAll('.tx-tag[data-tag]').forEach(c => c.addEventListener('click', e => { e.stopPropagation(); filterByTag(c.dataset.tag); }));
  $('tag-clear')?.addEventListener('click', clearTagFilter);
  $('split-add-row')?.addEventListener('click', () => { _splitRows = _readSplitRows(); _splitRows.push({ category: '', amount: '' }); renderTxns(); });
  $('split-save')?.addEventListener('click', b => saveSplits($('split-save').dataset.id));
  $('split-cancel')?.addEventListener('click', () => { _splitTxn = null; _splitRows = []; renderTxns(); });
  root.querySelectorAll('.split-row-del').forEach(b => b.addEventListener('click', () => { _splitRows = _readSplitRows(); _splitRows.splice(+b.dataset.i, 1); if (!_splitRows.length) _splitRows = [{ category: '', amount: '' }]; renderTxns(); }));
}

async function applySearch() {
  const q = $('txn-search')?.value.trim() || '';
  const mn = $('txn-min')?.value.trim() || '';
  const mx = $('txn-max')?.value.trim() || '';
  if (!q && !mn && !mx) {   // nothing to filter → back to the plain month list
    _searchResults = null;
    const rows = $('txn-rows'); if (rows) { rows.innerHTML = txnList(); _wireTxnRows(); }
    return;
  }
  const p = new URLSearchParams({ month: _month });
  if (q) p.set('q', q);
  if (mn && !isNaN(parseFloat(mn))) p.set('min_amt', parseFloat(mn));
  if (mx && !isNaN(parseFloat(mx))) p.set('max_amt', parseFloat(mx));
  try {
    _searchResults = await api(`/api/money/transactions/search?${p}`);
  } catch { _searchResults = []; }
  const rows = $('txn-rows'); if (rows) { rows.innerHTML = txnList(); _wireTxnRows(); }
}

// ── actions ────────────────────────────────────────────────────────────────
async function addAccount() {
  const name = $('af-name')?.value.trim();
  if (!name) { toast('name the account', 'error'); return; }
  const opening = parseFloat($('af-open')?.value) || 0;
  const low_balance = parseFloat($('af-low')?.value) || 0;
  try {
    await api('/api/money/accounts', { method: 'POST', body: { name, kind: getDropdownValue($('af-kind')), opening, low_balance } });
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
      tags: $('tx-tags')?.value.trim() || '',
    } });
    await load();
  } catch { toast('couldn\'t add transaction', 'error'); }
}
async function delTxn(id) {
  try { await api(`/api/money/transactions/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}

// ── 4a: splits, tags, receipts, cleared, reconcile ────────────────────────────
async function toggleSplit(id) {
  if (_splitTxn === id) { _splitTxn = null; _splitRows = []; renderTxns(); return; }
  _splitTxn = id; _splitRows = [];
  try {
    const d = await api(`/api/money/transactions/${id}/splits`);
    _splitRows = (d.splits || []).map(s => ({ category: s.category, amount: s.amount }));
  } catch {}
  if (!_splitRows.length) _splitRows = [{ category: '', amount: '' }];
  renderTxns();
}
function _readSplitRows() {
  const ed = $('money-body').querySelector('.txn-split-editor'); if (!ed) return [];
  return [...ed.querySelectorAll('.split-row')].map(r => ({
    category: r.querySelector('.split-cat')?.value.trim() || '',
    amount: parseFloat(r.querySelector('.split-amt')?.value) || 0,
  }));
}
async function saveSplits(id) {
  const splits = _readSplitRows().filter(s => s.category && s.amount > 0);
  try {
    await api(`/api/money/transactions/${id}/splits`, { method: 'PUT', body: { splits } });
    _splitTxn = null; _splitRows = [];
    await load();
  } catch (e) { toast(e?.message?.includes('exceed') ? 'splits exceed the amount' : 'save failed', 'error'); }
}
function attachReceipt(id) {
  let inp = document.getElementById('money-receipt-input');
  if (!inp) {
    inp = document.createElement('input');
    inp.type = 'file'; inp.id = 'money-receipt-input'; inp.accept = 'image/*,.pdf'; inp.style.display = 'none';
    document.body.appendChild(inp);
  }
  inp.value = '';
  inp.onchange = async () => {
    const f = inp.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const up = await fetch('/api/uploads', { method: 'POST', body: fd }).then(r => r.json());
      await api(`/api/money/transactions/${id}`, { method: 'PATCH', body: { receipt_id: up.id } });
      toast('receipt attached', 'success');
      await load();
    } catch { toast('upload failed', 'error'); }
  };
  inp.click();
}
async function toggleCleared(id) {
  const rows = _searchResults !== null ? _searchResults : _txns;
  const t = rows.find(x => x.id === id);
  try {
    await api(`/api/money/transactions/${id}`, { method: 'PATCH', body: { cleared: !(t && t.cleared) } });
    await load();
  } catch { toast('failed', 'error'); }
}
async function filterByTag(tag) {
  _tagFilter = tag;
  try { _searchResults = await api(`/api/money/transactions?tag=${encodeURIComponent(tag)}`); }
  catch { _searchResults = []; }
  renderTxns();
}
function clearTagFilter() { _tagFilter = ''; _searchResults = null; renderTxns(); }
function renderTxns() {
  const rows = $('txn-rows'); if (rows) { rows.innerHTML = txnList(); _wireTxnRows(); }
}
function toggleReconcile(aid) {
  const wrap = $(`rc-panel-${aid}`); if (!wrap) return;
  wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
}
async function runReconcile(aid) {
  const v = parseFloat($(`rc-stmt-${aid}`)?.value);
  const out = $(`rc-out-${aid}`); if (!out) return;
  if (isNaN(v)) { out.textContent = 'enter a statement balance'; return; }
  try {
    const d = await api(`/api/money/accounts/${aid}/reconcile?statement=${v}`);
    out.className = 'rc-out ' + (d.reconciled ? 'ok' : 'bad');
    out.textContent = d.reconciled
      ? `✓ reconciled — cleared ${fmt(d.cleared_balance)}`
      : `cleared ${fmt(d.cleared_balance)} · off by ${fmt(Math.abs(d.difference))}`;
  } catch { out.textContent = 'failed'; }
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
async function addGoal() {
  const name = $('gl-name')?.value.trim();
  if (!name) { toast('name the goal', 'error'); return; }
  try {
    await api('/api/money/goals', { method: 'POST', body: {
      name, kind: getDropdownValue($('gl-kind')) || 'savings',
      target: parseFloat($('gl-target')?.value) || 0, current: parseFloat($('gl-current')?.value) || 0,
      monthly: parseFloat($('gl-monthly')?.value) || 0,
    } });
    await load();
  } catch { toast('add failed', 'error'); }
}
async function delGoal(id) {
  try { await api(`/api/money/goals/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function runReport() {
  const start = $('rp-start')?.dataset.value || '', end = $('rp-end')?.dataset.value || '';
  const out = $('rp-out'); if (!out) return;
  const p = new URLSearchParams(); if (start) p.set('start', start); if (end) p.set('end', end);
  try {
    const d = await api(`/api/money/report?${p}`);
    const cats = (d.by_category || []).map(c => `<div class="rp-cat"><span>${esc(c[0])}</span><span>${fmt(c[1])}</span></div>`).join('');
    out.innerHTML = `<div class="rp-tot">income <span class="pos">${fmt(d.income)}</span> · spent <span class="neg">${fmt(d.expense)}</span> · net ${signed(d.net)}</div>${cats}`;
    const link = $('rp-export');
    if (link) { link.href = `/api/money/report/export.csv?${p}`; link.style.display = ''; }
  } catch { out.textContent = 'report failed'; }
}
async function runBaseNw() {
  const base = ($('nw-base-cur')?.value || 'USD').trim() || 'USD';
  const out = $('nw-base-out'); if (!out) return;
  try {
    const d = await api(`/api/money/networth-base?base=${encodeURIComponent(base)}`);
    out.textContent = `${d.net_worth.toLocaleString('en-US', { minimumFractionDigits: 2 })} ${d.base}`;
  } catch { out.textContent = 'fx failed'; }
}
async function addHolding() {
  const symbol = $('hd-sym')?.value.trim();
  if (!symbol) { toast('enter a symbol', 'error'); return; }
  try {
    await api('/api/money/holdings', { method: 'POST', body: {
      symbol, qty: parseFloat($('hd-qty')?.value) || 0,
      cost_basis: parseFloat($('hd-cost')?.value) || 0, price: parseFloat($('hd-price')?.value) || 0,
    } });
    await load();
  } catch { toast('add failed', 'error'); }
}
async function delHolding(id) {
  try { await api(`/api/money/holdings/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}

// dashboard: hide/show cards, persisted in localStorage (4c)
function _hiddenCards() { try { return new Set(JSON.parse(localStorage.getItem('money-hidden-cards') || '[]')); } catch { return new Set(); } }
function _saveHidden(set) { try { localStorage.setItem('money-hidden-cards', JSON.stringify([...set])); } catch {} }
function _decorateCards() {
  const hidden = _hiddenCards();
  $('money-body').querySelectorAll('.money-card[data-card]').forEach(card => {
    const id = card.dataset.card;
    const h3 = card.querySelector('h3');
    if (h3 && !h3.querySelector('.card-hide')) {
      const x = document.createElement('button');
      x.className = 'card-hide'; x.textContent = '×'; x.title = 'hide this card';
      x.addEventListener('click', () => { const s = _hiddenCards(); s.add(id); _saveHidden(s); _decorateCards(); });
      h3.appendChild(x);
    }
    card.style.display = hidden.has(id) ? 'none' : '';
  });
  // a restore chip when anything is hidden
  let chip = $('money-restore-cards');
  if (hidden.size) {
    if (!chip) {
      chip = document.createElement('button');
      chip.id = 'money-restore-cards'; chip.className = 'btn money-restore-cards';
      chip.addEventListener('click', () => { _saveHidden(new Set()); _decorateCards(); });
      $('money-body').querySelector('.money-grid')?.appendChild(chip);
    }
    chip.textContent = `+ ${hidden.size} hidden card${hidden.size > 1 ? 's' : ''}`;
    chip.style.display = '';
  } else if (chip) { chip.style.display = 'none'; }
}
async function assignEnvelope(category, amount) {
  category = (category || '').trim();
  if (!category) { toast('name a category', 'error'); return; }
  try {
    await api('/api/money/envelope/assign', { method: 'PUT', body: { category, month: _month, amount: parseFloat(amount) || 0 } });
    _envelope = await api(`/api/money/envelope?month=${_month}`).catch(() => _envelope);
    const card = $('money-body').querySelector('.money-envelope');
    if (card) { card.innerHTML = `<h3>envelope budgeting${_aom && _aom.age != null ? ` <span class="aom">age of money: ${_aom.age}d</span>` : ''}</h3>` + envelopeCard(); _wireEnvelope(); }
  } catch { toast('assign failed', 'error'); }
}
function _wireEnvelope() {
  $('money-body').querySelectorAll('.env-assign').forEach(inp =>
    inp.addEventListener('change', () => assignEnvelope(inp.dataset.cat, inp.value)));
  $('env-assign-btn')?.addEventListener('click', () => {
    assignEnvelope($('env-new-cat')?.value, $('env-new-amt')?.value);
    if ($('env-new-cat')) $('env-new-cat').value = '';
    if ($('env-new-amt')) $('env-new-amt').value = '';
  });
  $('money-body').querySelectorAll('.env-tgt-btn').forEach(b =>
    b.addEventListener('click', () => setEnvTarget(b.dataset.cat)));
}
async function setEnvTarget(category) {
  const v = await dlgFields(`funding target for "${category}" (amount 0 clears it)`, [
    { id: 'amount', label: 'target amount', value: '' },
    { id: 'date', label: 'by date (YYYY-MM-DD, optional)', value: '' },
  ]);
  if (!v) return;
  try {
    await api('/api/money/envelope/target', { method: 'PUT', body: { category, amount: parseFloat(v.amount) || 0, target_date: (v.date || '').trim() } });
    await load();
  } catch { toast('failed to set target', 'error'); }
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
