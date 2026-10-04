// subscriptions — recurring costs with billing cycles and renewal reminders
import { api, toast } from './util.js';
import { calendarDateKey } from './i18n.js';
import { initCustomDropdown } from './dropdown.js?v=212';
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

let _loaded = false, _loading = false, _busy = false;
let _loadError = '', _generation = 0, _navigation = 0;
let _draft = null, _creation = null, _history = null;
const _errors = new Map(), _paidRequests = new Map();

function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(v => v.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function captureDraft() {
  const row = document.querySelector?.('#subs-list .sub-item.editing');
  if (!row) return;
  _draft = { id: row.dataset.id };
  row.querySelectorAll('[data-f]').forEach(el => { _draft[el.dataset.f] = el.value; });
}

export async function loadSubs(fetcher = fetch, { clearErrors = false } = {}) {
  captureDraft();
  const generation = ++_generation;
  _loading = true; _loadError = ''; _render();
  const get = path => api(path, {}, fetcher).catch(() => null);
  const [d, analytics, upcoming, forecast, dd, accounts, unused, detected] = await Promise.all([
    get('/api/subscriptions'),
    get('/api/subscriptions/analytics'),
    get('/api/subscriptions/upcoming?days=7'),
    get('/api/subscriptions/forecast?months=6'),
    get('/api/subscriptions/duplicates'),
    get('/api/money/accounts'),
    get('/api/subscriptions/unused?cycles=2'),
    get('/api/subscriptions/detect'),
  ]);
  if (generation !== _generation) return false;
  const mainLoaded = Array.isArray(d?.subscriptions);
  if (mainLoaded) {
    _subs = d.subscriptions; _summary = d.summary || {}; _loaded = true;
    if (clearErrors) { _errors.clear(); _paidRequests.clear(); }
  } else _loadError = 'could not load subscriptions. ' + (_loaded ? 'the last loaded list is still shown.' : 'retry to see your subscriptions.');
  _analytics = analytics;
  _upcoming = upcoming;
  _forecast = forecast;
  _dupIds = new Set((dd?.groups || []).flatMap(g => (g.subs || []).map(s => s.id)));
  if (Array.isArray(accounts)) _accounts = accounts.filter(a => !a.archived);
  _unusedIds = new Set((unused?.unused || []).map(s => s.id));
  _detected = detected?.candidates || [];
  if (mainLoaded && [analytics, upcoming, forecast, dd, accounts, unused, detected].some(value => value == null)) {
    _loadError = 'subscriptions loaded, but some totals and account details could not load. retry to refresh them.';
  }
  _loading = false; _render();
  return mainLoaded;
}

function setBusy() {
  const view = $('subs-view');
  view?.setAttribute('aria-busy', String(_busy));
  view?.querySelectorAll('button, input, .custom-select, .date-input').forEach(el => {
    const frozen = !!_creation?.uncertain && !!el.closest('.page-view-footer') && el.id !== 'sub-add-btn' && !el.matches('[data-close-create]');
    const disabled = _busy || frozen;
    el.disabled = disabled;
    if (el.matches('.date-input')) { el.setAttribute('aria-disabled', String(disabled)); el.tabIndex = disabled ? -1 : 0; }
  });
  if ($('sub-add-btn')) $('sub-add-btn').textContent = _creation?.uncertain ? 'retry add' : 'add';
}

function errorText(error) {
  return error?.status && error.status < 500 ? error.message : 'could not confirm the change. retry safely or refresh to check.';
}

async function writeSubscription(id, action, change) {
  if (_busy) return;
  const navigation = _navigation;
  captureDraft(); ++_generation; _loading = false; _busy = true; setBusy();
  try {
    await change(); _errors.delete(id);
    await loadSubs();
  } catch (error) { _errors.set(id, errorText(error)); }
  finally {
    _busy = false; _render();
    if (navigation === _navigation && $('subs-view')?.offsetParent && (!document.activeElement || document.activeElement === document.body || $('subs-view').contains(document.activeElement))) {
      const row = $('subs-list')?.querySelector(`[data-id="${CSS.escape(id)}"]`);
      (row?.querySelector(`[data-act="${action}"]`) || row?.querySelector('[data-act="edit"]') || $('sub-name'))?.focus();
    }
  }
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

export function initSubsPanel(fetcher = fetch) {
  ++_navigation;
  const loading = loadSubs(fetcher);
  const cycleEl = $('sub-cycle');
  initCustomDropdown(cycleEl);
  initDatePicker($('sub-due'));
  cycleEl?.addEventListener('change', () => {
    $('sub-cycle-days').style.display = cycleEl.dataset.value === 'custom' ? '' : 'none';
  });
  if (!$('sub-add-btn') || $('sub-add-btn').dataset.wired) return loading;
  $('sub-add-btn').dataset.wired = '1';
  $('sub-add-btn').addEventListener('click', _add);
  $('sub-name')?.addEventListener('keydown', e => { if (e.key === 'Enter') _add(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _history && !_busy) { e.preventDefault(); closeHistory(); }
  });
  return loading;
}

async function _add() {
  if (_busy) return;
  const name = $('sub-name')?.value.trim();
  const due = $('sub-due')?.value;
  if (!_creation?.uncertain) {
    if (!name) { toast('give it a name', 'error'); $('sub-name')?.focus(); return; }
    if (!due) { toast('pick the next billing date', 'error'); $('sub-due')?.focus(); return; }
    const price = Number($('sub-price')?.value || 0);
    if (!Number.isFinite(price) || price < 0) { toast('enter a valid price', 'error'); $('sub-price')?.focus(); return; }
    _creation = { body: { name, price, cycle: $('sub-cycle')?.dataset.value || 'monthly',
      cycle_days: Number($('sub-cycle-days')?.value || 30), next_due: due.slice(0, 10),
      category: $('sub-category')?.value.trim() || '', request_id: requestId() } };
  }
  const creation = _creation, navigation = _navigation;
  _busy = true; ++_generation; _loading = false; setBusy();
  try {
    const saved = await api('/api/subscriptions', { method: 'POST', body: creation.body });
    if (!saved?.id) throw new Error('invalid subscription acknowledgment');
    _subs = [..._subs.filter(s => s.id !== saved.id), saved];
    _creation = null;
    ['sub-name', 'sub-price', 'sub-category', 'sub-cycle-days'].forEach(id => { if ($(id)) $(id).value = ''; });
    toast(`tracking ${creation.body.name}`, 'success'); await loadSubs();
  } catch (error) {
    creation.uncertain ||= !error.status || error.status >= 500 || [409, 410].includes(error.status);
    creation.error = errorText(error);
  } finally {
    _busy = false; _render();
    if (navigation === _navigation && $('subs-view')?.offsetParent && (document.activeElement === document.body || $('subs-view').contains(document.activeElement))) ($(_creation ? 'sub-add-btn' : 'sub-name'))?.focus();
  }
}

async function closeCreation() {
  if (_busy || !_creation) return;
  const creation = _creation, navigation = _navigation;
  if (creation.uncertain && !await dlgConfirm('this subscription may already be saved. close the draft and refresh?')) return;
  if (_creation !== creation) return;
  _creation = null; _busy = true; setBusy();
  ['sub-name', 'sub-price', 'sub-category', 'sub-cycle-days'].forEach(id => { if ($(id)) $(id).value = ''; });
  try { await loadSubs(); }
  finally { _busy = false; _render(); if (navigation === _navigation && $('subs-view')?.offsetParent && (document.activeElement === document.body || $('subs-view').contains(document.activeElement))) $('sub-name')?.focus(); }
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
  if (sum) sum.textContent = _summary.active
    ? (_summary.totals_available === false ? `${_summary.active} active · totals need currency review`
      : `${_summary.active} active · ${_summary.currency}${_summary.monthly_total}/mo · ${_summary.currency}${_summary.yearly_total}/yr`)
    : '';
  const list = $('subs-list');
  if (!list) return;
  const active = list.contains?.(document.activeElement) ? document.activeElement : null;
  const field = active?.dataset.f, record = active?.closest('.sub-item')?.dataset.id;
  const selected = active?.matches('.sub-item.record-target') ? active.dataset.id : null;
  const selection = typeof active?.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
  const notice = _loadError ? `<div class="specialist-group-note" role="alert">${esc(_loadError)} <button class="btn" data-refresh-subs>retry</button></div>` : '';
  const writeErrors = [..._errors].map(([id, message]) => `<div class="specialist-group-note" role="alert">${esc(_subs.find(s => s.id === id)?.name || 'subscription')}: ${esc(message)} <button class="btn" data-refresh-subs>refresh</button>${_paidRequests.has(id) ? ` <button class="btn" data-retry-paid="${esc(id)}">retry payment</button>` : ''}</div>`).join('');
  list.innerHTML = notice + writeErrors + (_loading ? '<div class="specialist-group-note" role="status">loading subscriptions…</div>' : '') + _detectedHtml()
    + (_subs.length ? _upcomingHtml(_upcoming) + _forecastHtml(_forecast) + _chartHtml(_analytics)
      + _subs.map(s => _editing === s.id ? _editRow(_draft?.id === s.id ? { ...s, ..._draft } : s) : _row(s)).join('')
      : (!_loaded || _loading || _loadError || _creation?.uncertain ? '' : '<div class="specialist-group-note">nothing tracked yet: add your first subscription below</div>'));
  _wireRows(list); _wireDetected(list);
  list.querySelectorAll('[data-refresh-subs]').forEach(button => button.addEventListener('click', () => loadSubs(fetch, { clearErrors: true })));
  list.querySelectorAll('[data-retry-paid]').forEach(button => button.addEventListener('click', () => paySubscription(button.dataset.retryPaid)));
  renderHistory();
  const status = $('sub-create-status');
  if (status) {
    status.hidden = !_creation?.error;
    status.innerHTML = _creation?.error ? `<span role="alert">${esc(_creation.error)}${_creation.uncertain ? ' the original input is kept for this retry.' : ''}</span> <button class="btn" data-close-create>close draft</button>` : '';
    status.querySelector('[data-close-create]')?.addEventListener('click', closeCreation);
  }
  setBusy();
  if (field && record) {
    const input = list.querySelector(`[data-id="${CSS.escape(record)}"] [data-f="${CSS.escape(field)}"]`);
    input?.focus(); if (selection && input?.setSelectionRange) input.setSelectionRange(...selection);
  } else if (selected) {
    const row = list.querySelector(`[data-id="${CSS.escape(selected)}"]`);
    if (row) { row.tabIndex = -1; row.classList.add('record-target'); row.focus({ preventScroll: true }); }
  }
}

function _detectedHtml() {
  if (!_detected || !_detected.length) return '';
  const chips = _detected.slice(0, 6).map((c, i) => {
    const amt = Math.abs(c.amount || 0).toFixed(2);
    return `<span class="sub-detected">${esc(c.payee || '?')} · ${amt} · ${esc(c.cycle || '')} <button class="btn" data-adopt="${i}" title="review this subscription before adding">review</button></span>`;
  }).join('');
  return `<div class="subs-detected"><span class="subs-detected-lbl">detected recurring charges</span>${chips}</div>`;
}
function _wireDetected(list) {
  list.querySelectorAll('[data-adopt]').forEach(button => button.addEventListener('click', () => {
    if (_busy || _creation?.uncertain) return;
    const candidate = _detected[+button.dataset.adopt]; if (!candidate) return;
    $('sub-name').value = candidate.payee || 'subscription';
    $('sub-price').value = String(Math.abs(candidate.amount || 0));
    $('sub-cycle').value = candidate.cycle || 'monthly';
    $('sub-due').value = calendarDateKey();
    $('sub-name').focus();
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
        ${_dupIds.has(s.id) ? `<span class="sub-dup" title="possible duplicate: another tracked subscription matches this name or site">⚠ dup?</span>` : ''}
        ${_unusedIds.has(s.id) ? `<button class="sub-unused" data-act="edit" title="no matching charge in the last 2 cycles. click to review / cancel">💤 unused?</button>` : ''}
        ${s.cancel_url ? `<a class="sub-cancel-link" href="${esc(s.cancel_url)}" target="_blank" rel="noreferrer" title="how to cancel ${esc(s.name)}">✕ cancel</a>` : ''}
      </div>
      <span class="sub-price">${esc(s.currency)}${s.price ? s.price.toFixed(2) : '—'}<span class="sub-cycle">${_cycleLabel(s)}</span></span>
      <span class="sub-due${soon ? ' soon' : ''}" title="${esc(s.next_due)}">${s.active ? esc(s.next_due.slice(5)) + ' · ' : ''}${_dueLabel(s)}</span>
      <span class="sub-actions">
        ${s.renewal_review_required ? '<span class="sub-review-required" title="review this subscription currency before posting the renewal">currency review needed</span>'
          : s.payable ? `<button class="btn" data-act="paid" title="mark this renewal paid">paid</button>`
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

async function paySubscription(id) {
  if (_busy) return;
  const sub = _subs.find(s => s.id === id); if (!sub) return;
  if (!_paidRequests.has(id)) _paidRequests.set(id, { next_due: sub.next_due, request_id: requestId() });
  await writeSubscription(id, 'paid', async () => {
    const saved = await api(`/api/subscriptions/${id}/paid`, { method: 'POST', body: _paidRequests.get(id) });
    if (saved?.id !== id) throw new Error('invalid payment acknowledgment');
    _paidRequests.delete(id); toast(`next due ${saved.next_due}`, 'success');
    if (_history?.id === id) await showHistory(id);
  });
}

function _wireRows(list) {
  list.querySelectorAll('.sub-item.editing .custom-select').forEach(initCustomDropdown);
  list.querySelectorAll('.sub-item.editing .date-input').forEach(initDatePicker);
  list.querySelectorAll('.sub-item').forEach(row => {
    const id = row.dataset.id;
    for (const event of ['input', 'change']) row.addEventListener(event, captureDraft);
    const cycle = row.querySelector('[data-f="cycle"]');
    cycle?.addEventListener('change', () => { row.querySelector('[data-f="cycle_days"]').style.display = cycle.value === 'custom' ? '' : 'none'; });
    row.querySelectorAll('[data-act]').forEach(button => button.addEventListener('click', async () => {
      const action = button.dataset.act;
      if (_busy) return;
      if (action === 'history') { await showHistory(id); return; }
      if (action === 'edit') { _history = null; _editing = id; _draft = null; _render(); $('subs-list').querySelector('.editing [data-f="name"]')?.focus(); return; }
      if (action === 'cancel') { _editing = null; _draft = null; _render(); return; }
      if (action === 'paid') { await paySubscription(id); return; }
      const sub = _subs.find(s => s.id === id);
      if (action === 'del' && !await dlgConfirm(`stop tracking ${sub?.name || 'this subscription'}?`)) return;
      await writeSubscription(id, action, async () => {
        if (action === 'del') {
          await api(`/api/subscriptions/${id}`, { method: 'DELETE' });
          _subs = _subs.filter(s => s.id !== id); _paidRequests.delete(id);
          if (_history?.id === id) _history = null;
        } else if (action === 'toggle') {
          await api(`/api/subscriptions/${id}`, { method: 'PATCH', body: { active: !sub.active } });
        } else if (action === 'save') {
          const value = field => _draft?.[field];
          const body = { name: value('name')?.trim(), currency: value('currency') || '',
            price: Number(value('price') || 0), cycle: value('cycle'), cycle_days: Number(value('cycle_days') || 30),
            next_due: value('next_due'), category: value('category')?.trim() || '',
            url: value('url')?.trim() || '', cancel_url: value('cancel_url')?.trim() || '', account_id: value('account_id') || '',
            remind_days: Number(value('remind_days') || 0), notes: value('notes') || '', trial_end: (value('trial_end') || '').slice(0, 10) };
          if (!Number.isFinite(body.price) || body.price < 0) throw Object.assign(new Error('enter a valid price'), { status: 400 });
          await api(`/api/subscriptions/${id}`, { method: 'PATCH', body });
          _editing = null; _draft = null; toast('saved', 'success');
        }
      });
    }));
  });
}

function closeHistory() {
  if (_busy) return;
  const id = _history?.id; _history = null;
  document.querySelectorAll('.sub-hist-pop').forEach(pop => pop.remove());
  if (id) $('subs-list')?.querySelector(`[data-id="${CSS.escape(id)}"] [data-act="history"]`)?.focus();
}

async function showHistory(id) {
  const state = { id, loading: true, pays: [], error: '' };
  _history = state; renderHistory();
  try {
    const pays = await api(`/api/subscriptions/${id}/payments`);
    if (!Array.isArray(pays)) throw new Error('invalid history response');
    state.pays = pays;
  } catch { state.error = 'could not load payments. retry to see the history.'; }
  if (_history !== state) return;
  const focused = document.activeElement;
  const ownsFocus = focused?.closest('.sub-item')?.dataset.id === id
    && (focused.matches('[data-act="history"]') || !!focused.closest('.sub-hist-pop'));
  state.loading = false; renderHistory();
  if (ownsFocus && $('subs-view')?.offsetParent) (document.querySelector('.sub-hist-pop [data-history-retry]') || document.querySelector('.sub-hist-pop [data-act="undo-last"]') || document.querySelector('.sub-hist-pop [data-history-close]'))?.focus();
}

function renderHistory() {
  document.querySelectorAll?.('.sub-hist-pop').forEach(pop => pop.remove());
  const state = _history; if (!state) return;
  const row = $('subs-list')?.querySelector(`[data-id="${CSS.escape(state.id)}"]`); if (!row) return;
  const sub = _subs.find(s => s.id === state.id), payment = state.pays.find(p => p.can_undo);
  const pop = document.createElement('div'); pop.className = 'sub-hist-pop'; pop.setAttribute('aria-label', 'payment history'); pop.setAttribute('role', 'region');
  pop.innerHTML = '<div class="sub-hist-head">payments</div><button class="btn" data-history-close>close</button>'
    + (state.loading ? '<div role="status">loading payments…</div>' : '')
    + (state.error ? `<div role="alert">${esc(state.error)}</div><button class="btn" data-history-retry>refresh history</button>` : '')
    + state.pays.map(p => `<div class="sub-hist-row"><span>${esc(p.date)}</span><span>${esc(p.currency || sub?.currency || '')}${(p.amount || 0).toFixed(2)}</span></div>`).join('')
    + (!state.loading && !state.error && !state.pays.length ? '<div class="sub-hist-empty">no payments yet</div>' : '')
    + (payment ? `<button class="btn" data-act="undo-last">undo ${esc(payment.date)}</button>` : '');
  row.appendChild(pop);
  pop.querySelector('[data-history-close]').addEventListener('click', closeHistory);
  pop.querySelector('[data-history-retry]')?.addEventListener('click', () => showHistory(state.id));
  pop.querySelector('[data-act="undo-last"]')?.addEventListener('click', async () => {
    if (_busy) return;
    const navigation = _navigation;
    if (_loading) _loadError = 'subscriptions were not refreshed. retry to check the current list.';
    _loading = false; _busy = true; ++_generation; _render();
    try {
      await api(`/api/subscriptions/${state.id}/payments/undo`, { method: 'POST', body: { payment_id: payment.id } });
      state.pays = state.pays.filter(p => p.id !== payment.id); state.error = '';
      toast('payment undone', 'success'); await loadSubs();
      if (_history === state) await showHistory(state.id);
    } catch (error) {
      state.error = errorText(error);
      if (error.status === 404) { state.pays = state.pays.filter(p => p.id !== payment.id); await loadSubs(); }
    } finally {
      const focused = document.activeElement;
      const ownsFocus = !focused || focused === document.body || !!focused.closest('.sub-hist-pop');
      _busy = false; _render();
      if (ownsFocus && navigation === _navigation && _history === state && $('subs-view')?.offsetParent) document.querySelector('.sub-hist-pop [data-act="undo-last"], .sub-hist-pop [data-history-retry]')?.focus();
    }
  });
  setBusy();
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
