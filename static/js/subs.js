// subscriptions — recurring costs with billing cycles and renewal reminders
import { api, toast } from './util.js';
import { calendarDateKey, formatNumber, t, tp } from './i18n.js';
import { initCustomDropdown } from './dropdown.js?v=215';
import { initDatePicker } from './datepick.js';
import { choose as dlgChoose, confirm as dlgConfirm } from './dialog.js';
import { amountIn, totalsCurrency, wireCurrency } from './money_currency.js';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

// "CAD 1,202.43", not "CAD1202.43": a space after the code and the reader's own separators
function _amt(currency, value, digits = 2) {
  const number = formatNumber(Number(value) || 0, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${currency ? `${currency} ` : ''}${number}`;
}

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
let _newCurrency = '';   // a currency picked for the next new subscription; else the ledger's
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
  } else _loadError = t(_loaded ? 'subs.load_failed_stale' : 'subs.load_failed');
  _analytics = analytics;
  _upcoming = upcoming;
  _forecast = forecast;
  _dupIds = new Set((dd?.groups || []).flatMap(g => (g.subs || []).map(s => s.id)));
  if (Array.isArray(accounts)) _accounts = accounts.filter(a => !a.archived);
  _unusedIds = new Set((unused?.unused || []).map(s => s.id));
  _detected = detected?.candidates || [];
  if (mainLoaded && [analytics, upcoming, forecast, dd, accounts, unused, detected].some(value => value == null)) {
    _loadError = t('subs.load_partial');
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
  if ($('sub-add-btn')) $('sub-add-btn').textContent = _creation?.uncertain ? t('subs.retry_add') : t('common.add');
  syncAddState();
}

function syncAddState() {
  const nameMissing = !$('sub-name')?.value.trim();
  const dateMissing = !$('sub-due')?.value;
  const retry = !!_creation?.uncertain;
  const add = $('sub-add-btn'), hint = $('sub-required');
  if (add) add.disabled = _busy || (!retry && (nameMissing || dateMissing));
  if (hint) hint.textContent = retry ? t('subs.hint_retry')
    : nameMissing && dateMissing ? t('subs.hint_name_and_date')
    : nameMissing ? t('subs.hint_name')
    : dateMissing ? t('subs.hint_date')
    : t('subs.hint_required');
}

function errorText(error) {
  return error?.status && error.status < 500 ? error.message : t('subs.change_unconfirmed');
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
      (row?.querySelector(`[data-act="${action}"]`) || row?.querySelector('[data-act="edit"]') || _formFocus())?.focus();
    }
  }
}

const acctName = id => _accounts.find(a => a.id === id)?.name || '';

// " + USD 15.49": what a total left out, in its own currency, so a total never quietly undercounts
function _plusText(rows, field = 'total', unit = '') {
  return (rows || []).filter(row => row.currency !== 'XXX' && row[field])
    .map(row => ` + ${amountIn(row.currency, row[field])}${unit}`).join('');
}
const _plus = (...args) => esc(_plusText(...args));

function _currencyHtml() {
  if (!_summary.base_currency) return '';
  return totalsCurrency(_summary, row => {
    if (row.currency === 'XXX') return tp('subs.excluded_no_currency', row.count, { amount: formatNumber(row.monthly_total || 0, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) });
    return tp('subs.excluded_currency', row.count, { currency: row.currency, amount: amountIn(row.currency, row.monthly_total) });
  });
}

function _upcomingHtml(u) {
  if (!u || !u.count) return '';
  const chips = u.items.map(s => {
    const when = s.days_until === 0 ? t('common.today') : s.days_until === 1 ? t('subs.tomorrow') : t('subs.days_short', { count: s.days_until });
    return `<span class="subs-up-chip" title="${t('subs.renews_on', { name: esc(s.name), date: esc(s.next_due) })}">
      <span class="subs-up-name">${esc(s.name)}</span>
      <span class="subs-up-when${s.days_until <= 1 ? ' soon' : ''}">${when}</span>
      ${s.price ? `<span class="subs-up-amt">${esc(_amt(s.currency, s.price))}</span>` : ''}
    </span>`;
  }).join('');
  return `<div class="subs-upcoming">
    <div class="subs-up-head">${t('subs.up_head', { days: u.days, total: `<strong>${esc(_amt(u.currency, u.total))}</strong>${_plus(u.excluded)}`, renewals: tp('subs.renewals', u.count) })}</div>
    <div class="subs-up-chips">${chips}</div>
  </div>`;
}

function _forecastHtml(f) {
  if (!f || !f.forecast?.length || !(f.total || f.excluded?.length)) return '';
  const max = Math.max(...f.forecast.map(m => m.total), 1);
  const cols = f.forecast.map(m => `
    <div class="subs-fc-col" title="${esc(m.month)}: ${esc(_amt(f.currency, m.total))}">
      <span class="subs-fc-amt">${m.total ? esc(_amt(f.currency, m.total, 0)) : ''}</span>
      <span class="subs-fc-bar" style="height:${Math.max(3, m.total / max * 46).toFixed(0)}px"></span>
      <span class="subs-fc-m">${esc(m.month.slice(5))}</span>
    </div>`).join('');
  return `<div class="subs-forecast">
    <div class="subs-fc-head">${t('subs.fc_head', { months: f.months, total: `<strong>${esc(_amt(f.currency, f.total))}</strong>${_plus(f.excluded)}` })}</div>
    <div class="subs-fc-bars">${cols}</div>
  </div>`;
}

function _chartHtml(a) {
  if (!a || !a.count || !a.by_category.length) return '';
  const max = Math.max(...a.by_category.map(c => c.monthly), 1);
  const bars = a.by_category.slice(0, 8).map(c => `
    <div class="subs-bar-row">
      <span class="subs-bar-label">${esc(c.name === 'uncategorized' ? t('subs.uncategorized') : c.name)}</span>
      <span class="subs-bar-track"><span class="subs-bar-fill" style="width:${(c.monthly / max * 100).toFixed(1)}%"></span></span>
      <span class="subs-bar-val">${esc(_amt(a.currency, c.monthly))}</span>
    </div>`).join('');
  return `<div class="subs-chart">
    <div class="subs-chart-title">${t('subs.chart_title', { monthly: `${esc(_amt(a.currency, a.monthly_total))}${t('subs.per_mo')}${_plus(a.excluded, 'monthly_total', t('subs.per_mo'))}`, yearly: `${esc(_amt(a.currency, a.yearly_total))}${t('subs.per_yr')}${_plus(a.excluded, 'yearly_total', t('subs.per_yr'))}` })}</div>
    ${bars}
  </div>`;
}

// on a phone the add form folds into one "+ subscription" row, so the list keeps the screen.
// the toggle only shows under 760px (revamp.css); wider, the form is always one open row
const _phoneAdd = () => !!$('sub-add-toggle')?.getClientRects().length;
const _formFocus = () => $(_phoneAdd() && $('sub-add-toggle').getAttribute('aria-expanded') === 'false' ? 'sub-add-toggle' : 'sub-name');

function _setAddOpen(open, { focus = true } = {}) {
  const toggle = $('sub-add-toggle'), form = toggle?.parentElement;
  if (!toggle) return;
  open ||= !!_creation?.uncertain || !!_creation?.error;
  form.toggleAttribute('data-collapsed', !open);
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? t('subs.close_new') : t('subs.add_one'));
  toggle.innerHTML = open ? `<span>${t('subs.new_subscription')}</span>${_si('close')}` : `${_si('plus')}<span>${t('subs.subscription')}</span>`;
  if (focus && _phoneAdd()) (open ? $('sub-name') : toggle)?.focus();
}

// a new subscription is saved in the ledger currency (where renewals post) unless picked here
const _addCurrency = () => _newCurrency || _summary.ledger_currency || '';

function _syncCurrency() {
  const button = $('sub-currency'), code = _addCurrency();
  if (!button) return;
  button.hidden = !code;
  button.innerHTML = `${esc(code)}${_si('chevron-down')}`;
  button.setAttribute('aria-label', t('subs.currency_change', { code }));
}

function _currencyControl() {
  const name = $('sub-name');
  if (!name || $('sub-currency')) return;
  const button = document.createElement('button');
  button.type = 'button'; button.id = 'sub-currency'; button.className = 'btn sub-currency';
  button.setAttribute('aria-haspopup', 'dialog');
  name.after(button);
  button.addEventListener('click', async () => {
    if (_busy || _creation?.uncertain) return;
    let codes = [];
    try { codes = (await api('/api/money/currencies')).codes || []; } catch { codes = []; }
    if (!codes.length) { toast(t('money.currency_choices_failed'), 'error'); return; }
    // the ones already in use first: the ledger's, then the subscriptions'
    const used = [_addCurrency(), _summary.ledger_currency, ..._subs.map(s => s.original_currency_code)];
    const first = [...new Set(used)].filter(code => codes.includes(code));
    const picked = await dlgChoose(t('subs.currency_for_this'), [...first, ...codes.filter(code => !first.includes(code))].map(value => ({ value, label: value })));
    if (picked) { _newCurrency = picked === _summary.ledger_currency ? '' : picked; _syncCurrency(); }
  });
  _syncCurrency();
}

function _addToggle() {
  const add = $('sub-add-btn'), form = add?.parentElement;
  if (!form || $('sub-add-toggle')) return;
  form.id ||= 'sub-add-form';
  const toggle = document.createElement('button');
  toggle.type = 'button'; toggle.id = 'sub-add-toggle'; toggle.className = 'btn sub-add-toggle';
  toggle.setAttribute('aria-controls', form.id);
  form.prepend(toggle);
  _setAddOpen(false, { focus: false });
  toggle.addEventListener('click', () => _setAddOpen(toggle.getAttribute('aria-expanded') === 'false'));
  form.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || !_phoneAdd() || form.hasAttribute('data-collapsed') || _busy || e.defaultPrevented) return;
    if (e.target.closest?.('.custom-select.open, .date-input.open')) return;
    e.preventDefault(); _setAddOpen(false);
  });
}

export function initSubsPanel(fetcher = fetch) {
  ++_navigation;
  const loading = loadSubs(fetcher);
  _addToggle();
  _currencyControl();
  const cycleEl = $('sub-cycle');
  // the markup's english options and placeholder, in the interface language
  if (cycleEl) cycleEl.dataset.options = ['weekly', 'monthly', 'quarterly', 'yearly']
    .map(c => `${c}|${t(`subs.cycle_${c}`)}`).concat(`custom|${t('subs.cycle_custom_days')}`).join(';');
  if ($('sub-due')) $('sub-due').dataset.ph = t('subs.next_billing_date');
  initCustomDropdown(cycleEl);
  initDatePicker($('sub-due'));
  syncAddState();
  cycleEl?.addEventListener('change', () => {
    $('sub-cycle-days').style.display = cycleEl.dataset.value === 'custom' ? '' : 'none';
  });
  if (!$('sub-add-btn') || $('sub-add-btn').dataset.wired) return loading;
  $('sub-add-btn').dataset.wired = '1';
  $('sub-add-btn').addEventListener('click', _add);
  $('sub-name')?.addEventListener('input', syncAddState);
  $('sub-name')?.addEventListener('change', syncAddState);
  $('sub-due')?.addEventListener('change', syncAddState);
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
    if (!name) { toast(t('subs.give_name'), 'error'); $('sub-name')?.focus(); return; }
    if (!due) { toast(t('subs.pick_date'), 'error'); $('sub-due')?.focus(); return; }
    const price = Number($('sub-price')?.value || 0);
    if (!Number.isFinite(price) || price < 0) { toast(t('subs.valid_price'), 'error'); $('sub-price')?.focus(); return; }
    _creation = { body: { name, price, cycle: $('sub-cycle')?.dataset.value || 'monthly',
      cycle_days: Number($('sub-cycle-days')?.value || 30), next_due: due.slice(0, 10),
      category: $('sub-category')?.value.trim() || '', currency: _addCurrency(), request_id: requestId() } };
  }
  const creation = _creation, navigation = _navigation;
  _busy = true; ++_generation; _loading = false; setBusy();
  try {
    const saved = await api('/api/subscriptions', { method: 'POST', body: creation.body });
    if (!saved?.id) throw new Error('invalid subscription acknowledgment');
    _subs = [..._subs.filter(s => s.id !== saved.id), saved];
    _creation = null; _newCurrency = '';
    ['sub-name', 'sub-price', 'sub-category', 'sub-cycle-days'].forEach(id => { if ($(id)) $(id).value = ''; });
    // on a phone the form folds back so the new one shows in the list
    if (_phoneAdd()) _setAddOpen(false, { focus: false });
    toast(t('subs.tracking', { name: creation.body.name }), 'success'); await loadSubs();
  } catch (error) {
    creation.uncertain ||= !error.status || error.status >= 500 || [409, 410].includes(error.status);
    creation.error = errorText(error);
  } finally {
    _busy = false; _render();
    if (_creation) _setAddOpen(true, { focus: false });
    if (navigation === _navigation && $('subs-view')?.offsetParent && (document.activeElement === document.body || $('subs-view').contains(document.activeElement))) (_creation ? $('sub-add-btn') : _formFocus())?.focus();
  }
}

async function closeCreation() {
  if (_busy || !_creation) return;
  const creation = _creation, navigation = _navigation;
  if (creation.uncertain && !await dlgConfirm(t('subs.may_be_saved'))) return;
  if (_creation !== creation) return;
  _creation = null; _busy = true; setBusy();
  ['sub-name', 'sub-price', 'sub-category', 'sub-cycle-days'].forEach(id => { if ($(id)) $(id).value = ''; });
  try { await loadSubs(); }
  finally { _busy = false; _render(); if (navigation === _navigation && $('subs-view')?.offsetParent && (document.activeElement === document.body || $('subs-view').contains(document.activeElement))) _formFocus()?.focus(); }
}

function _dueLabel(s) {
  if (!s.active) return t('subs.paused');
  if (s.days_until < 0) return t('subs.overdue');
  if (s.days_until === 0) return t('common.today');
  if (s.days_until === 1) return t('subs.tomorrow');
  return t('subs.in_days', { count: s.days_until });
}

function _cycleLabel(s) {
  if (s.cycle === 'custom') return t('subs.every_days', { count: s.cycle_days });
  return { weekly: t('subs.per_wk'), monthly: t('subs.per_mo'), quarterly: t('subs.per_qtr'), yearly: t('subs.per_yr') }[s.cycle] || s.cycle;
}

function _render() {
  _syncCurrency();
  const sum = $('subs-summary');
  if (sum) sum.textContent = _summary.active
    ? (_summary.totals_available === false ? t('subs.summary_review', { active: _summary.active })
      : t('subs.summary', { active: _summary.active, monthly: `${_amt(_summary.currency, _summary.monthly_total)}${t('subs.per_mo')}${_plusText(_summary.excluded, 'monthly_total', t('subs.per_mo'))}`, yearly: `${_amt(_summary.currency, _summary.yearly_total)}${t('subs.per_yr')}${_plusText(_summary.excluded, 'yearly_total', t('subs.per_yr'))}` }))
    : '';
  const list = $('subs-list');
  if (!list) return;
  const active = list.contains?.(document.activeElement) ? document.activeElement : null;
  const field = active?.dataset.f, record = active?.closest('.sub-item')?.dataset.id;
  const selected = active?.matches('.sub-item.record-target') ? active.dataset.id : null;
  const selection = typeof active?.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
  const notice = _loadError ? `<div class="specialist-group-note" role="alert">${esc(_loadError)} <button class="btn" data-refresh-subs>${t('common.retry')}</button></div>` : '';
  const writeErrors = [..._errors].map(([id, message]) => `<div class="specialist-group-note" role="alert">${esc(_subs.find(s => s.id === id)?.name || t('subs.subscription'))}: ${esc(message)} <button class="btn" data-refresh-subs>${t('subs.refresh')}</button>${_paidRequests.has(id) ? ` <button class="btn" data-retry-paid="${esc(id)}">${t('subs.retry_payment')}</button>` : ''}</div>`).join('');
  list.innerHTML = notice + writeErrors + (_loading ? `<div class="specialist-group-note" role="status">${t('subs.loading')}</div>` : '') + _detectedHtml()
    + (_subs.length ? _currencyHtml() + _upcomingHtml(_upcoming) + _forecastHtml(_forecast) + _chartHtml(_analytics)
      + _subs.map(s => _editing === s.id ? _editRow(_draft?.id === s.id ? { ...s, ..._draft } : s) : _row(s)).join('')
      : (!_loaded || _loading || _loadError || _creation?.uncertain ? '' : `<div class="specialist-group-note">${t('subs.empty')}</div>`));
  _wireRows(list); _wireDetected(list);
  wireCurrency(list, _summary, () => loadSubs(fetch, { clearErrors: true }));
  list.querySelectorAll('[data-refresh-subs]').forEach(button => button.addEventListener('click', () => loadSubs(fetch, { clearErrors: true })));
  list.querySelectorAll('[data-retry-paid]').forEach(button => button.addEventListener('click', () => paySubscription(button.dataset.retryPaid)));
  renderHistory();
  const status = $('sub-create-status');
  if (status) {
    status.hidden = !_creation?.error;
    status.innerHTML = _creation?.error ? `<span role="alert">${esc(_creation.error)}${_creation.uncertain ? ' ' + t('subs.input_kept') : ''}</span> <button class="btn" data-close-create>${t('subs.close_draft')}</button>` : '';
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
    return `<span class="sub-detected">${esc(c.payee || '?')} · ${amt} · ${esc(c.cycle || '')} <button class="btn" data-adopt="${i}" title="${t('subs.review_before_adding')}">${t('subs.review')}</button></span>`;
  }).join('');
  return `<div class="subs-detected"><span class="subs-detected-lbl">${t('subs.detected')}</span>${chips}</div>`;
}
function _wireDetected(list) {
  list.querySelectorAll('[data-adopt]').forEach(button => button.addEventListener('click', () => {
    if (_busy || _creation?.uncertain) return;
    const candidate = _detected[+button.dataset.adopt]; if (!candidate) return;
    $('sub-name').value = candidate.payee || t('subs.subscription');
    $('sub-price').value = String(Math.abs(candidate.amount || 0));
    $('sub-cycle').value = candidate.cycle || 'monthly';
    $('sub-due').value = calendarDateKey();
    syncAddState();
    _setAddOpen(true, { focus: false });
    $('sub-name').focus();
  }));
}

function _row(s) {
  const soon = s.active && s.days_until <= 3;
  return `
    <div class="sub-item${s.active ? '' : ' paused'}" data-id="${s.id}">
      <div class="sub-main">
        <span class="sub-name">${esc(s.name)}</span>
        ${s.url ? `<a class="sub-link" href="${esc(s.url)}" target="_blank" rel="noreferrer" title="${t('subs.manage', { name: esc(s.name) })}" aria-label="${t('subs.manage', { name: esc(s.name) })}">${_si('external')}</a>` : ''}
        ${s.category ? `<span class="sub-cat">${esc(s.category)}</span>` : ''}
        ${s.account_id && acctName(s.account_id) ? `<span class="sub-autopost" title="${t('subs.autopost_to', { account: esc(acctName(s.account_id)) })}">${_si('refresh')} ${esc(acctName(s.account_id))}</span>` : ''}
        ${s.notes ? `<span class="sub-notes" title="${esc(s.notes)}">…</span>` : ''}
        ${s.trial_days_left != null && s.trial_days_left >= 0 ? `<span class="sub-trial" title="${t('subs.trial_title', { date: esc(s.trial_end) })}">${s.trial_days_left === 0 ? t('subs.trial_ends_today') : t('subs.trial_days_left', { count: s.trial_days_left })}</span>` : ''}
        ${s.price_increased ? `<span class="sub-hike" title="${s.last_price_change ? t('subs.price_up_detail', { old: esc(_amt(s.currency, s.last_price_change.old)), new: esc(_amt(s.currency, s.last_price_change.new)), date: esc(s.last_price_change.date) }) : t('subs.price_up_title')}">${t('subs.price_up')}</span>` : ''}
        ${_dupIds.has(s.id) ? `<span class="sub-dup" title="${t('subs.duplicate_title')}">${_si('warning')} ${t('subs.duplicate')}</span>` : ''}
        ${_unusedIds.has(s.id) ? `<button class="sub-unused" data-act="edit" title="${t('subs.unused_title')}">${_si('snooze')} ${t('subs.unused')}</button>` : ''}
        ${s.cancel_url ? `<a class="sub-cancel-link" href="${esc(s.cancel_url)}" target="_blank" rel="noreferrer" title="${t('subs.how_to_cancel', { name: esc(s.name) })}">${t('subs.how_to_cancel_short')} ${_si('external')}</a>` : ''}
      </div>
      <span class="sub-price">${s.price ? esc(_amt(s.currency, s.price)) : `${esc(s.currency)} —`}<span class="sub-cycle">${_cycleLabel(s)}</span></span>
      <span class="sub-due${soon ? ' soon' : ''}" title="${esc(s.next_due)}">${s.active ? esc(s.next_due.slice(5)) + ' · ' : ''}${_dueLabel(s)}</span>
      <span class="sub-actions">
        ${s.renewal_review_required ? `<span class="sub-review-required" title="${t('subs.review_title')}">${t('subs.review_needed')}</span>`
          : s.payable ? `<button class="btn" data-act="paid" title="${t('subs.mark_paid_title')}">${t('subs.paid')}</button>`
          : (s.active ? `<span class="sub-notdue" title="${t('subs.next_charge', { date: esc(s.next_due) })}">${t('subs.not_due')}</span>` : '')}
        ${s.paid_count ? `<button class="btn" data-act="history" title="${t('subs.history_title')}" aria-label="${t('subs.history_label', { count: s.paid_count })}">${_si('history')} ${s.paid_count}</button>` : ''}
        <button class="btn" data-act="toggle">${s.active ? t('subs.pause') : t('subs.resume')}</button>
        <button class="btn" data-act="edit">${t('common.edit')}</button>
        <button class="btn danger" data-act="del">×</button>
      </span>
    </div>`;
}

function _editRow(s) {
  return `
    <div class="sub-item editing" data-id="${s.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(s.name)}" placeholder="${t('subs.ph_name')}" style="flex:2;min-width:110px">
      <input type="text" class="settings-input" data-f="currency" value="${esc(s.currency)}" style="width:40px" title="${t('subs.currency_symbol')}">
      <input type="text" class="settings-input" data-f="price" value="${s.price || ''}" placeholder="${t('subs.ph_price')}" style="width:70px" inputmode="decimal">
      <div class="settings-input custom-select" data-f="cycle" data-value="${esc(s.cycle || 'monthly')}" data-options="weekly|${t('subs.cycle_weekly')};monthly|${t('subs.cycle_monthly')};quarterly|${t('subs.cycle_quarterly')};yearly|${t('subs.cycle_yearly')};custom|${t('subs.cycle_custom')}" style="width:auto;min-width:96px"></div>
      <input type="text" class="settings-input" data-f="cycle_days" value="${s.cycle_days}" style="width:55px;${s.cycle === 'custom' ? '' : 'display:none'}" title="${t('subs.cycle_length_title')}" inputmode="numeric">
      <div class="date-input" data-f="next_due" data-type="date" data-value="${esc(s.next_due)}" data-ph="${t('subs.ph_due')}" style="width:135px"></div>
      <div class="date-input" data-f="trial_end" data-type="date" data-value="${esc(s.trial_end || '')}" data-ph="${t('subs.ph_trial_ends')}" style="width:130px"></div>
      <input type="text" class="settings-input" data-f="category" value="${esc(s.category)}" placeholder="${t('subs.ph_category')}" style="width:95px">
      <input type="text" class="settings-input" data-f="url" value="${esc(s.url || '')}" placeholder="${t('subs.ph_manage_url')}" style="width:120px">
      <input type="text" class="settings-input" data-f="cancel_url" value="${esc(s.cancel_url || '')}" placeholder="${t('subs.ph_cancel_url')}" style="width:130px" title="${t('subs.how_to_cancel_title')}">
      <input type="text" class="settings-input" data-f="remind_days" value="${s.remind_days}" style="width:45px" title="${t('subs.remind_title')}" inputmode="numeric">
      <div class="settings-input custom-select" data-f="account_id" data-value="${esc(s.account_id || '')}" data-options="${[`|${t('subs.no_autopost')}`, ..._accounts.map(a => `${a.id}|${t('subs.autopost_to_name', { name: a.name })}`)].map(esc).join(';')}" style="width:auto;min-width:120px" title="${t('subs.autopost_account_title')}"></div>
      <input type="text" class="settings-input" data-f="notes" value="${esc(s.notes)}" placeholder="${t('subs.ph_notes')}" style="flex:1;min-width:80px">
      <span class="sub-actions">
        <button class="btn primary" data-act="save">${t('common.save')}</button>
        <button class="btn" data-act="cancel">${t('common.cancel')}</button>
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
    _paidRequests.delete(id);
    if (_history?.id === id) await showHistory(id, t('subs.paid_next_due', { date: saved.next_due }));
    else toast(t('subs.next_due', { date: saved.next_due }), 'success');
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
      if (action === 'del' && !await dlgConfirm(sub?.name ? t('subs.stop_tracking', { name: sub.name }) : t('subs.stop_tracking_this'))) return;
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
          if (!body.name) throw Object.assign(new Error(t('subs.needs_name')), { status: 400 });
          if (!Number.isFinite(body.price) || body.price < 0) throw Object.assign(new Error(t('subs.valid_price')), { status: 400 });
          await api(`/api/subscriptions/${id}`, { method: 'PATCH', body });
          _editing = null; _draft = null; toast(t('common.saved'), 'success');
        }
      });
    }));
  });
}

function closeHistory() {
  if (_busy) return;
  const id = _history?.id; _history = null;
  document.querySelectorAll('.sub-hist-pop').forEach(pop => pop.remove());
  if (id) _rowFocus(id)?.focus();
}

// the row's history button, or edit once undo took the last payment and history went away
function _rowFocus(id) {
  const row = $('subs-list')?.querySelector(`[data-id="${CSS.escape(id)}"]`);
  return row?.querySelector('[data-act="history"]') || row?.querySelector('.sub-actions [data-act="edit"]');
}

async function showHistory(id, status = '') {
  const state = { id, loading: true, pays: [], error: '', status };
  const historyFocus = document.activeElement?.closest('.sub-hist-pop');
  const retainFocus = historyFocus?.closest('.sub-item')?.dataset.id === id;
  _history = state; renderHistory();
  if (retainFocus && $('subs-view')?.offsetParent) document.querySelector('.sub-hist-pop [data-history-close]')?.focus();
  try {
    const pays = await api(`/api/subscriptions/${id}/payments`);
    if (!Array.isArray(pays)) throw new Error('invalid history response');
    state.pays = pays;
  } catch { state.error = t('subs.payments_failed'); }
  if (_history !== state) return;
  const focused = document.activeElement;
  // safari doesn't focus a tapped or clicked button, so opening by pointer leaves <body> focused
  const ownsFocus = !focused || focused === document.body || (focused.closest('.sub-item')?.dataset.id === id
    && (focused.matches('[data-act="history"]') || !!focused.closest('.sub-hist-pop')));
  state.loading = false; renderHistory();
  // a row near the bottom opened its payments past the screen edge, hiding undo
  document.querySelector?.('.sub-hist-pop')?.scrollIntoView?.({ block: 'nearest' });
  if (ownsFocus && $('subs-view')?.offsetParent) (document.querySelector('.sub-hist-pop [data-history-retry]') || document.querySelector('.sub-hist-pop [data-act="undo-last"]') || document.querySelector('.sub-hist-pop [data-history-close]'))?.focus();
}

function renderHistory() {
  document.querySelectorAll?.('.sub-hist-pop').forEach(pop => pop.remove());
  const state = _history; if (!state) return;
  const row = $('subs-list')?.querySelector(`[data-id="${CSS.escape(state.id)}"]`); if (!row) return;
  // a refreshing list may still hold a stale undo, so it waits for the server's answer
  const sub = _subs.find(s => s.id === state.id), payment = !state.loading && state.pays.find(p => p.can_undo);
  const pop = document.createElement('div'); pop.className = 'sub-hist-pop'; pop.setAttribute('aria-label', t('subs.payment_history')); pop.setAttribute('role', 'region');
  pop.innerHTML = `<div class="sub-hist-head">${t('subs.payments')}</div><button class="btn" data-history-close>${t('common.close')}</button>`
    + (state.status ? '<div class="sub-hist-status" role="status"></div>' : '')
    + (state.loading ? `<div role="status">${t('subs.payments_loading')}</div>` : '')
    + (state.error ? `<div role="alert">${esc(state.error)}</div><button class="btn" data-history-retry>${t('subs.refresh_history')}</button>` : '')
    + state.pays.map(p => `<div class="sub-hist-row"><span>${esc(p.date)}</span><span>${esc(_amt(p.currency || sub?.currency || '', p.amount))}</span></div>`).join('')
    + (!state.loading && !state.error && !state.pays.length ? `<div class="sub-hist-empty">${t('subs.no_payments')}</div>` : '')
    + (payment ? `<button class="btn" data-act="undo-last">${t('subs.undo_date', { date: esc(payment.date) })}</button>` : '');
  row.appendChild(pop);
  // filled a frame after the live region exists, so a screen reader hears it once
  const status = pop.querySelector('.sub-hist-status');
  if (status && state.announced) status.textContent = state.status;
  else if (status) requestAnimationFrame(() => { if (status.isConnected) { status.textContent = state.status; state.announced = true; } });
  pop.querySelector('[data-history-close]').addEventListener('click', closeHistory);
  pop.querySelector('[data-history-retry]')?.addEventListener('click', () => showHistory(state.id));
  pop.querySelector('[data-act="undo-last"]')?.addEventListener('click', async () => {
    if (_busy) return;
    const navigation = _navigation;
    if (_loading) _loadError = t('subs.not_refreshed');
    _loading = false; _busy = true; ++_generation; _render();
    try {
      await api(`/api/subscriptions/${state.id}/payments/undo`, { method: 'POST', body: { payment_id: payment.id } });
      // still refreshing: "no payments yet" here would read as done while every button is still disabled
      state.pays = state.pays.filter(p => p.id !== payment.id); state.error = ''; state.loading = true;
      await loadSubs();
      if (_history === state) await showHistory(state.id, t('subs.payment_undone'));
      else toast(t('subs.payment_undone'), 'success');
    } catch (error) {
      state.error = errorText(error);
      if (error.status === 404) { state.pays = state.pays.filter(p => p.id !== payment.id); await loadSubs(); }
    } finally {
      const focused = document.activeElement;
      const ownsFocus = !focused || focused === document.body || !!focused.closest('.sub-hist-pop');
      _busy = false; _render();
      if (ownsFocus && navigation === _navigation && $('subs-view')?.offsetParent) {
        // undoing the last payment leaves no undo: close is next, else the row itself
        const pop = _history?.id === state.id ? document.querySelector('.sub-hist-pop') : null;
        (pop?.querySelector('[data-act="undo-last"], [data-history-retry]') || pop?.querySelector('[data-history-close]') || _rowFocus(state.id))?.focus();
      }
    }
  });
  setBusy();
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
