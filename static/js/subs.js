// subscriptions — recurring costs with billing cycles and renewal reminders
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { initDatePicker } from './datepick.js';
import { confirm as dlgConfirm } from './dialog.js';

const $ = id => document.getElementById(id);
let _subs = [];
let _summary = {};
let _analytics = null;
let _upcoming = null;  // renewals due in the next N days + summed cost
let _forecast = null;  // per-month projected spend (cash-flow)
let _dupIds = new Set(); // ids flagged as possible duplicates
let _accounts = [];    // money accounts, for the optional auto-post link
let _editing = null;   // id of the row currently in edit mode
let _unusedIds = new Set();   // subs with no recent matching charge (4e)
let _detected = [];    // recurring-charge candidates not yet tracked (4e)

export async function loadSubs() {
  try {
    const d = await fetch('/api/subscriptions').then(r => r.json());
    _subs = d.subscriptions || [];
    _summary = d.summary || {};
  } catch { _subs = []; _summary = {}; }
  try { _analytics = await fetch('/api/subscriptions/analytics').then(r => r.json()); }
  catch { _analytics = null; }
  try { _upcoming = await fetch('/api/subscriptions/upcoming?days=7').then(r => r.json()); }
  catch { _upcoming = null; }
  try { _forecast = await fetch('/api/subscriptions/forecast?months=6').then(r => r.json()); }
  catch { _forecast = null; }
  try {
    const dd = await fetch('/api/subscriptions/duplicates').then(r => r.json());
    _dupIds = new Set((dd.groups || []).flatMap(g => g.subs.map(s => s.id)));
  } catch { _dupIds = new Set(); }
  try { _accounts = (await fetch('/api/money/accounts').then(r => r.json())).filter(a => !a.archived); }
  catch { _accounts = []; }
  try { _unusedIds = new Set(((await fetch('/api/subscriptions/unused?cycles=2').then(r => r.json())).unused || []).map(s => s.id)); }
  catch { _unusedIds = new Set(); }
  try { _detected = (await fetch('/api/subscriptions/detect').then(r => r.json())).candidates || []; }
  catch { _detected = []; }
  _render();
}

const acctName = id => _accounts.find(a => a.id === id)?.name || '';

function _upcomingHtml(u) {
  if (!u || !u.count) return '';
  const chips = u.items.map(s => {
    const when = s.days_until === 0 ? 'today' : s.days_until === 1 ? 'tomorrow' : `${s.days_until}d`;
    return `<span class="subs-up-chip" title="${esc(s.name)} renews ${esc(s.next_due)}">
      <span class="subs-up-name">${esc(s.name)}</span>
      <span class="subs-up-when${s.days_until <= 1 ? ' soon' : ''}">${when}</span>
      ${s.price ? `<span class="subs-up-amt">${esc(s.currency)}${s.price.toFixed(2)}</span>` : ''}
    </span>`;
  }).join('');
  return `<div class="subs-upcoming">
    <div class="subs-up-head">next ${u.days} days · <strong>${esc(u.currency)}${u.total.toFixed(2)}</strong> · ${u.count} renewal${u.count === 1 ? '' : 's'}</div>
    <div class="subs-up-chips">${chips}</div>
  </div>`;
}

function _forecastHtml(f) {
  if (!f || !f.forecast?.length || !f.total) return '';
  const max = Math.max(...f.forecast.map(m => m.total), 1);
  const cols = f.forecast.map(m => `
    <div class="subs-fc-col" title="${esc(m.month)}: ${esc(f.currency)}${m.total.toFixed(2)}">
      <span class="subs-fc-amt">${m.total ? esc(f.currency) + m.total.toFixed(0) : ''}</span>
      <span class="subs-fc-bar" style="height:${Math.max(3, m.total / max * 46).toFixed(0)}px"></span>
      <span class="subs-fc-m">${esc(m.month.slice(5))}</span>
    </div>`).join('');
  return `<div class="subs-forecast">
    <div class="subs-fc-head">next ${f.months} months · <strong>${esc(f.currency)}${f.total.toFixed(2)}</strong> projected</div>
    <div class="subs-fc-bars">${cols}</div>
  </div>`;
}

function _chartHtml(a) {
  if (!a || !a.count || !a.by_category.length) return '';
  const max = Math.max(...a.by_category.map(c => c.monthly), 1);
  const bars = a.by_category.slice(0, 8).map(c => `
    <div class="subs-bar-row">
      <span class="subs-bar-label">${esc(c.name)}</span>
      <span class="subs-bar-track"><span class="subs-bar-fill" style="width:${(c.monthly / max * 100).toFixed(1)}%"></span></span>
      <span class="subs-bar-val">${esc(a.currency)}${c.monthly.toFixed(2)}</span>
    </div>`).join('');
  return `<div class="subs-chart">
    <div class="subs-chart-title">${esc(a.currency)}${(a.monthly_total || 0).toFixed(2)}/mo · ${esc(a.currency)}${(a.yearly_total || 0).toFixed(2)}/yr · spend by category</div>
    ${bars}
  </div>`;
}

export function initSubsPanel() {
  loadSubs();
  const cycleEl = $('sub-cycle');
  initCustomDropdown(cycleEl);
  initDatePicker($('sub-due'));
  cycleEl?.addEventListener('change', () => {
    $('sub-cycle-days').style.display = cycleEl.dataset.value === 'custom' ? '' : 'none';
  });
  if (!$('sub-add-btn') || $('sub-add-btn').dataset.wired) return;
  $('sub-add-btn').dataset.wired = '1';
  $('sub-add-btn').addEventListener('click', _add);
  $('sub-name')?.addEventListener('keydown', e => { if (e.key === 'Enter') _add(); });
}

async function _add() {
  const name = $('sub-name')?.value.trim();
  const due = $('sub-due')?.value;
  if (!name) { toast('give it a name', 'error'); return; }
  if (!due) { toast('pick the next billing date', 'error'); return; }
  const body = {
    name,
    price: parseFloat($('sub-price')?.value) || 0,
    cycle: $('sub-cycle')?.dataset.value || 'monthly',
    cycle_days: parseInt($('sub-cycle-days')?.value) || 30,
    next_due: due.slice(0, 10),
    category: $('sub-category')?.value.trim() || '',
  };
  const r = await fetch('/api/subscriptions', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) { toast((await r.json()).detail || 'failed to add', 'error'); return; }
  ['sub-name', 'sub-price', 'sub-category', 'sub-cycle-days'].forEach(id => { if ($(id)) $(id).value = ''; });
  toast(`tracking ${name}`, 'success');
  loadSubs();
}

function _dueLabel(s) {
  if (!s.active) return 'paused';
  if (s.days_until < 0) return 'overdue';
  if (s.days_until === 0) return 'today';
  if (s.days_until === 1) return 'tomorrow';
  return `in ${s.days_until}d`;
}

function _cycleLabel(s) {
  if (s.cycle === 'custom') return `every ${s.cycle_days}d`;
  return { weekly: '/wk', monthly: '/mo', quarterly: '/qtr', yearly: '/yr' }[s.cycle] || s.cycle;
}

function _render() {
  const sum = $('subs-summary');
  if (sum) {
    sum.textContent = _summary.active
      ? `${_summary.active} active · ${_summary.currency}${_summary.monthly_total}/mo · ${_summary.currency}${_summary.yearly_total}/yr`
      : '';
  }
  const list = $('subs-list');
  if (!list) return;
  const detected = _detectedHtml();
  if (!_subs.length) {
    list.innerHTML = detected + '<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">nothing tracked yet — add your first subscription below</div>';
    _wireDetected(list);
    return;
  }
  list.innerHTML = detected + _upcomingHtml(_upcoming) + _forecastHtml(_forecast) + _chartHtml(_analytics) + _subs.map(s => _editing === s.id ? _editRow(s) : _row(s)).join('');
  _wireRows(list);
  _wireDetected(list);
}

function _detectedHtml() {
  if (!_detected || !_detected.length) return '';
  const chips = _detected.slice(0, 6).map((c, i) => {
    const amt = Math.abs(c.amount || 0).toFixed(2);
    return `<span class="sub-detected">${esc(c.payee || '?')} · ${amt} · ${esc(c.cycle || '')} <button class="btn" data-adopt="${i}" title="track this as a subscription">+ track</button></span>`;
  }).join('');
  return `<div class="subs-detected"><span class="subs-detected-lbl">detected recurring charges</span>${chips}</div>`;
}
function _wireDetected(list) {
  list.querySelectorAll('[data-adopt]').forEach(b => b.addEventListener('click', async () => {
    const c = _detected[+b.dataset.adopt]; if (!c) return;
    const due = new Date().toISOString().slice(0, 10);
    await fetch('/api/subscriptions', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: c.payee || 'subscription', price: Math.abs(c.amount || 0), cycle: c.cycle || 'monthly', next_due: due }),
    });
    toast(`now tracking ${c.payee || ''}`, 'success');
    loadSubs();
  }));
}

function _row(s) {
  const soon = s.active && s.days_until <= 3;
  return `
    <div class="sub-item${s.active ? '' : ' paused'}" data-id="${s.id}">
      <div class="sub-main">
        <span class="sub-name">${esc(s.name)}</span>
        ${s.url ? `<a class="sub-link" href="${esc(s.url)}" target="_blank" rel="noreferrer" title="manage ${esc(s.name)}">↗</a>` : ''}
        ${s.category ? `<span class="sub-cat">${esc(s.category)}</span>` : ''}
        ${s.account_id && acctName(s.account_id) ? `<span class="sub-autopost" title="auto-posts the charge to ${esc(acctName(s.account_id))}">↻ ${esc(acctName(s.account_id))}</span>` : ''}
        ${s.notes ? `<span class="sub-notes" title="${esc(s.notes)}">…</span>` : ''}
        ${s.trial_days_left != null && s.trial_days_left >= 0 ? `<span class="sub-trial" title="free trial / cancel by ${esc(s.trial_end)}">trial: ${s.trial_days_left === 0 ? 'ends today' : s.trial_days_left + 'd left'}</span>` : ''}
        ${s.price_increased ? `<span class="sub-hike" title="price went up${s.last_price_change ? ` (${esc(s.currency)}${s.last_price_change.old} → ${esc(s.currency)}${s.last_price_change.new} on ${esc(s.last_price_change.date)})` : ''}">↑ price up</span>` : ''}
        ${_dupIds.has(s.id) ? `<span class="sub-dup" title="possible duplicate — another tracked subscription matches this name or site">⚠ dup?</span>` : ''}
        ${_unusedIds.has(s.id) ? `<button class="sub-unused" data-act="edit" title="no matching charge in the last 2 cycles — click to review / cancel">💤 unused?</button>` : ''}
        ${s.cancel_url ? `<a class="sub-cancel-link" href="${esc(s.cancel_url)}" target="_blank" rel="noreferrer" title="how to cancel ${esc(s.name)}">✕ cancel</a>` : ''}
      </div>
      <span class="sub-price">${esc(s.currency)}${s.price ? s.price.toFixed(2) : '—'}<span class="sub-cycle">${_cycleLabel(s)}</span></span>
      <span class="sub-due${soon ? ' soon' : ''}" title="${esc(s.next_due)}">${s.active ? esc(s.next_due.slice(5)) + ' · ' : ''}${_dueLabel(s)}</span>
      <span class="sub-actions">
        ${s.payable ? `<button class="btn" data-act="paid" title="mark this renewal paid">paid</button>`
          : (s.active ? `<span class="sub-notdue" title="next charge ${esc(s.next_due)}">not due</span>` : '')}
        ${s.paid_count ? `<button class="btn" data-act="history" title="payment history + undo">⤺ ${s.paid_count}</button>` : ''}
        <button class="btn" data-act="toggle">${s.active ? 'pause' : 'resume'}</button>
        <button class="btn" data-act="edit">edit</button>
        <button class="btn danger" data-act="del">×</button>
      </span>
    </div>`;
}

function _editRow(s) {
  return `
    <div class="sub-item editing" data-id="${s.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(s.name)}" placeholder="name" style="flex:2;min-width:110px">
      <input type="text" class="settings-input" data-f="currency" value="${esc(s.currency)}" style="width:40px" title="currency symbol">
      <input type="text" class="settings-input" data-f="price" value="${s.price || ''}" placeholder="price" style="width:70px" inputmode="decimal">
      <div class="settings-input custom-select" data-f="cycle" data-value="${esc(s.cycle || 'monthly')}" data-options="weekly|weekly;monthly|monthly;quarterly|quarterly;yearly|yearly;custom|custom" style="width:auto;min-width:96px"></div>
      <input type="text" class="settings-input" data-f="cycle_days" value="${s.cycle_days}" style="width:55px;${s.cycle === 'custom' ? '' : 'display:none'}" title="cycle length in days" inputmode="numeric">
      <div class="date-input" data-f="next_due" data-type="date" data-value="${esc(s.next_due)}" data-ph="due" style="width:135px"></div>
      <div class="date-input" data-f="trial_end" data-type="date" data-value="${esc(s.trial_end || '')}" data-ph="trial ends" style="width:130px"></div>
      <input type="text" class="settings-input" data-f="category" value="${esc(s.category)}" placeholder="category" style="width:95px">
      <input type="text" class="settings-input" data-f="url" value="${esc(s.url || '')}" placeholder="manage url" style="width:120px">
      <input type="text" class="settings-input" data-f="cancel_url" value="${esc(s.cancel_url || '')}" placeholder="cancel url / how-to" style="width:130px" title="how to cancel">
      <input type="text" class="settings-input" data-f="remind_days" value="${s.remind_days}" style="width:45px" title="push reminder N days before (0 = off)" inputmode="numeric">
      <div class="settings-input custom-select" data-f="account_id" data-value="${esc(s.account_id || '')}" data-options="${['|no auto-post', ..._accounts.map(a => `${a.id}|↻ ${a.name}`)].map(esc).join(';')}" style="width:auto;min-width:120px" title="auto-post the charge to a money account"></div>
      <input type="text" class="settings-input" data-f="notes" value="${esc(s.notes)}" placeholder="notes" style="flex:1;min-width:80px">
      <span class="sub-actions">
        <button class="btn primary" data-act="save">save</button>
        <button class="btn" data-act="cancel">cancel</button>
      </span>
    </div>`;
}

function _wireRows(list) {
  list.querySelectorAll('.sub-item.editing .custom-select').forEach(initCustomDropdown);
  list.querySelectorAll('.sub-item.editing .date-input').forEach(initDatePicker);
  list.querySelectorAll('.sub-item').forEach(row => {
    const id = row.dataset.id;
    const cycleSel = row.querySelector('[data-f="cycle"]');
    cycleSel?.addEventListener('change', () => {
      row.querySelector('[data-f="cycle_days"]').style.display = cycleSel.value === 'custom' ? '' : 'none';
    });
    row.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'edit') { _editing = id; _render(); return; }
      if (act === 'cancel') { _editing = null; _render(); return; }
      if (act === 'del') {
        const s = _subs.find(x => x.id === id);
        if (!await dlgConfirm(`stop tracking ${s?.name || 'this subscription'}?`)) return;
        await fetch(`/api/subscriptions/${id}`, { method: 'DELETE' });
        loadSubs(); return;
      }
      if (act === 'paid') {
        const r = await fetch(`/api/subscriptions/${id}/paid`, { method: 'POST' });
        if (r.ok) toast(`next due ${(await r.json()).next_due}`, 'success');
        else toast((await r.json()).detail || 'not due yet', 'error');
        loadSubs(); return;
      }
      if (act === 'history') { await _showHistory(id, row, btn); return; }
      if (act === 'toggle') {
        const s = _subs.find(x => x.id === id);
        await fetch(`/api/subscriptions/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ active: !s.active }),
        });
        loadSubs(); return;
      }
      if (act === 'save') {
        const v = f => row.querySelector(`[data-f="${f}"]`)?.value;
        const body = {
          name: v('name')?.trim(), currency: v('currency') || '$',
          price: parseFloat(v('price')) || 0,
          cycle: v('cycle'), cycle_days: parseInt(v('cycle_days')) || 30,
          next_due: v('next_due'), category: v('category')?.trim() || '',
          url: v('url')?.trim() || '', cancel_url: v('cancel_url')?.trim() || '',
          account_id: v('account_id') || '',
          remind_days: parseInt(v('remind_days')) || 0,
          notes: v('notes') || '',
          trial_end: (v('trial_end') || '').slice(0, 10),
        };
        const r = await fetch(`/api/subscriptions/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) { toast((await r.json()).detail || 'save failed', 'error'); return; }
        _editing = null;
        toast('saved', 'success');
        loadSubs(); return;
      }
    }));
  });
}

async function _showHistory(id, row, btn) {
  document.querySelectorAll('.sub-hist-pop').forEach(p => p.remove());
  let pays = [];
  try { pays = await fetch(`/api/subscriptions/${id}/payments`).then(r => r.json()); } catch {}
  const cur = _subs.find(x => x.id === id)?.currency || '$';
  const pop = document.createElement('div');
  pop.className = 'sub-hist-pop';
  pop.innerHTML = `<div class="sub-hist-head">payments</div>`
    + (pays.length
      ? pays.map(p => `<div class="sub-hist-row"><span>${esc(p.date)}</span><span>${esc(cur)}${(p.amount || 0).toFixed(2)}</span></div>`).join('')
        + `<button class="btn" data-act="undo-last">undo last</button>`
      : '<div class="sub-hist-empty">no payments yet</div>');
  row.appendChild(pop);
  pop.querySelector('[data-act="undo-last"]')?.addEventListener('click', async () => {
    const r = await fetch(`/api/subscriptions/${id}/payments/undo`, { method: 'POST' });
    toast(r.ok ? 'payment undone' : 'nothing to undo', r.ok ? 'success' : 'error');
    loadSubs();
  });
  setTimeout(() => document.addEventListener('click', function h(e) {
    if (!pop.contains(e.target) && e.target !== btn) { pop.remove(); document.removeEventListener('click', h); }
  }), 0);
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
