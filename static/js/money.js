// money: accounts, transactions, budgets, and a couple of charts. plain SVG for
// the charts (no chart lib), api() helper for the fetches.
import { api, toast, plainError } from './util.js';
import { confirm as dlgConfirm, fields as dlgFields, choose as dlgChoose } from './dialog.js';
import { initCustomDropdown, getDropdownValue, populateDropdown } from './dropdown.js?v=213';
import { initDatePicker, calendarDateParts } from './datepick.js';
import { calendarDateKey, formatCalendarDate, formatDate, formatNumber, t, tp } from './i18n.js';
import { createFocusBoundary } from './kokuen.js?v=4';
import { bankRequest as _ownerFetch, openPlaidLink } from './finance_plaid.js';
import { replaceRouteUrl } from './route_history.js';
import { assignHues, categoryHue } from './color.js';
import { tickNumbers } from './motion.js';
import { formatDecimal } from './liveformat.js';
import { amountIn, excludedNotes, totalsCurrency, wireCurrency } from './money_currency.js';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

// one hue per category for everything on screen: the chart's categories pick first so its bars
// never share a color, then caps and transactions
let _hueFrom = [], _hues = new Map();
function hueOf(name) {
  const from = [_sum, _budgets, _txns, _searchResults];
  if (from.some((part, at) => part !== _hueFrom[at])) {
    _hueFrom = from;
    _hues = assignHues(
      (_sum?.by_category || []).slice(0, 8).map(row => row[0]),
      [..._budgets.map(b => b.category), ..._txns.map(txn => txn.category), ...(_searchResults || []).map(txn => txn.category)],
    );
  }
  return _hues.get(String(name || '').trim().toLowerCase()) || categoryHue(name);
}
const catDot = name => `<i class="cat-dot" style="--cat:var(--cat-${hueOf(name)})" aria-hidden="true"></i>`;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Require the whole entry: parseFloat("1,234.56") would silently save 1.
function _decimal(value, empty = NaN) {
  const text = String(value ?? '').trim();
  if (!text) return empty;
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return NaN;
  const amount = Number(text);
  return Number.isFinite(amount) ? amount : NaN;
}
function _validAmounts(...values) {
  if (values.every(Number.isFinite)) return true;
  toast(t('money.number_decimal_point'), 'error');
  return false;
}

function _thisMonth() { return calendarDateKey().slice(0, 7); }
function _monthFromUrl() { const m = new URLSearchParams(location.search).get('m'); return (m && /^\d{4}-\d{2}$/.test(m)) ? m : ''; }
function _setMonthUrl() { try { const u = new URL(location.href); u.searchParams.set('m', _month); replaceRouteUrl(u); } catch {} }

let _month = _monthFromUrl() || _thisMonth();
let _accounts = [], _txns = [], _budgets = [], _sum = null, _recurring = [], _rules = [];
let _recurringError = false, _canonicalLedger = false;
let _recurringStatus = '';
let _recurringEdit = null;
let _envelope = null, _aom = null;   // YNAB envelope view + age of money (4b)
const _envAssignmentBusy = new Set();
const _targetDrafts = new Map();
let _targetStatus = '';
let _forecast = null, _nwhist = [], _holdings = null, _alerts = null;   // Simplifi (4c)
let _forecastError = '';
let _goals = [];   // savings/debt goals (4d)
let _goalsCurrency = '';   // goals are saved in the ledger currency, shown in this one
let _goalSaving = false, _budgetSaving = false;
let _searchResults = null;   // array when a search/filter is active, else null
let _searchTimer = null;
let _searchSequence = 0;
let _searchStatus = '';
let _amountRangeOpen = false;
let _cur = '$';
let _currencyCodes = [];
let _currencyReadSequence = 0;
let _inited = false;
const _expandedMoneySections = new Set();
let _moneyEntryOpen = null;
let _moneyEntryDetailsOpen = false;
let _moneyPlanTask = 'accounts';
let _moneyFocusChange = 0;
let _moneyEntryChange = 0;
let _transactionSaveStatus = '';
let _transactionUncertainSnapshot = null;
let _transactionSaveRequestId = '';
let _moneyLoadSequence = 0;
let _moneyRefreshFailed = false;
let _moneyRefreshing = false;
let _moneySaved = [];
let _moneySavedExpanded = false;
let _moneySavedCurrent = null;
let _moneySavedAction = 0;
let _moneySavedActionSequence = 0;
const _moneySavedKey = 'alles:finance-saved-transactions';
let _moneyTotalsOpen = false;
let _editTxn = null;   // id of the txn row currently being edited inline
let _splitTxn = null;  // id of the txn whose split editor is open (4a)
let _splitRows = [];   // working split rows in the open editor
let _tagFilter = '';   // active tag filter (4a)
const _pendingCreateRequests = new Map();
const _createRequestKey = kind => `alles:finance-create:${kind}`;

function _newCreateRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function _canonicalCreatePayload(value) {
  if (Array.isArray(value)) return value.map(_canonicalCreatePayload);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, _canonicalCreatePayload(value[key])]),
    );
  }
  return value;
}

async function _createPayloadFingerprint(payload) {
  const canonical = JSON.stringify(_canonicalCreatePayload(payload));
  try {
    const digest = await globalThis.crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(canonical),
    );
    return {
      fingerprint: [...new Uint8Array(digest)]
        .map(value => value.toString(16).padStart(2, '0'))
        .join(''),
      persistable: true,
    };
  } catch {
    // Preserve exact retry matching only in memory. Persisting this fallback would copy private
    // Finance fields verbatim into browser storage when Web Crypto is unavailable.
    return { fingerprint: canonical, persistable: false };
  }
}

const _kindLabel = kind => ({
  account: t('money.kind_account'), transaction: t('money.kind_transaction'), transfer: t('money.kind_transfer'), recurring: t('money.kind_recurring'),
}[kind] || kind);

async function _createRequestId(kind, payload) {
  const { fingerprint, persistable } = await _createPayloadFingerprint(payload);
  const pending = _pendingCreateRequests.get(kind);
  if (pending?.active) throw new Error(t('money.creation_in_progress', { kind: _kindLabel(kind) }));
  if (pending?.fingerprint === fingerprint) {
    pending.active = true;
    return pending.requestId;
  }
  let stored = null;
  if (persistable) {
    try { stored = JSON.parse(sessionStorage.getItem(_createRequestKey(kind)) || 'null'); } catch {}
  }
  let requestId = (
    stored?.fingerprint === fingerprint
    && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(stored.request_id || '')
  ) ? stored.request_id : '';
  if (!requestId) requestId = _newCreateRequestId();
  _pendingCreateRequests.set(kind, { requestId, fingerprint, active: true });
  if (persistable) {
    try {
      sessionStorage.setItem(
        _createRequestKey(kind),
        JSON.stringify({ request_id: requestId, fingerprint }),
      );
    } catch {}
  }
  return requestId;
}

function _releaseCreateRequest(kind, requestId) {
  const pending = _pendingCreateRequests.get(kind);
  if (pending?.requestId === requestId) pending.active = false;
}

function _completeCreateRequest(kind, requestId) {
  const pending = _pendingCreateRequests.get(kind);
  if (pending?.requestId !== requestId) return;
  _pendingCreateRequests.delete(kind);
  try {
    const stored = JSON.parse(sessionStorage.getItem(_createRequestKey(kind)) || 'null');
    if (stored?.request_id === requestId) sessionStorage.removeItem(_createRequestKey(kind));
  } catch {}
}

function _today() { return calendarDateKey(); }
function _shiftMonth(m, delta) {
  let [y, mo] = m.split('-').map(Number); mo += delta;
  while (mo < 1) { mo += 12; y--; } while (mo > 12) { mo -= 12; y++; }
  return `${y}-${String(mo).padStart(2, '0')}`;
}
function _monthLabel(m) {
  return formatCalendarDate(`${m}-01`, { month: 'long', year: 'numeric' }).toLowerCase();
}
function currencyPrefix(currency = _cur) {
  return currency === 'XXX' ? t('finance.currency_not_set') + '\u00a0' : currency + (/^[A-Z]{3}$/.test(currency) ? '\u00a0' : '');
}
// a true minus before the code (−USD 12.00), the same as signed(). with no currency the label
// isn't part of the amount, so there the minus stays on the number
const fmt = (n, currency = _cur) => {
  const cents = Math.round((n || 0) * 100);
  const number = formatNumber(Math.abs(cents) / 100, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sign = cents < 0 ? '−' : '';
  return currency === 'XXX' ? `${currencyPrefix(currency)}${sign}${number}` : `${sign}${currencyPrefix(currency)}${number}`;
};
const signed = (n, currency = _cur) => (n >= 0 ? '+' : '−') + fmt(Math.abs(n), currency);
const fmtMoney = (n, currency) => fmt(n, currency);

function transactionCurrency(transaction) {
  if (_canonicalLedger) return _cur;
  // a reviewed renewal posts its converted price, so its amount isn't in original_currency_code
  return transaction.amount_currency_code || transaction.original_currency_code || 'XXX';
}

function accountCurrency(account) {
  return _canonicalLedger ? _cur : account?.currency_code || 'XXX';
}

// totals add up in one base currency; a currency with no rate stays out with a note. only a
// ledger with no currency set anywhere (old "$" accounts) has nothing to add up into
// with a base currency the summary already added everything up in it; only an older reply
// without one falls back to its single native group
function totalsUnit() {
  return (!_canonicalLedger && !_sum?.base_currency && _sum?.currency_status === 'single' && _sum.totals_by_currency?.[0]?.currency)
    || _sum?.currency || (_accounts[0]?.currency) || '$';
}

function comparableTotals() {
  return _canonicalLedger || !_sum?.currency_status || _sum.currency_status !== 'unknown';
}

function moneyCurrency() {
  if (_canonicalLedger) return `<div class="totals-currency-wrap"><div class="totals-currency"><span class="totals-currency-lbl">${t('money.totals_follow_actual', { code: `<span class="totals-currency-code">${esc(_cur)}</span>` })}</span></div></div>`;
  if (!_sum?.base_currency) return '';
  const unknown = _accounts.find(a => !a.archived && a.currency_code === 'XXX');
  return totalsCurrency(_sum, row => {
    const amount = formatNumber(row.net_worth || 0, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (row.currency === 'XXX') return row.accounts ? tp('money.excl_none', row.accounts, { amount }) : t('money.excl_none_entries', { amount });
    const spent = row.expense ? t('money.spent_this_month', { amount: amountIn(row.currency, row.expense) }) : '';
    const total = amountIn(row.currency, row.net_worth);
    return row.accounts ? tp('money.excl_currency', row.accounts, { currency: row.currency, amount: total, spent }) : t('money.excl_currency_entries', { currency: row.currency, amount: total, spent });
  }, { extra: () => unknown ? `<button type="button" class="btn" data-set-currency="${esc(unknown.id)}">${t('money.set_currency')}</button>` : '' });
}

// a cap, an assignment or a goal is a plain number saved in the ledger currency
const savedIn = () => _sum?.ledger_currency || _cur;
const capsIn = () => _sum?.budgets_currency || _cur;

// spending caps sit far from the totals note, so they say for themselves what they can't count yet
function budgetsCurrencyNote() {
  if (_canonicalLedger || !_sum?.base_currency) return '';
  const caps = capsIn(), shown = _sum.currency;
  // no rate from the ledger currency into the totals one: caps stay as saved
  const kept = caps !== shown
    ? excludedNotes({ ..._sum, excluded: [{ currency: caps }] },
      () => t('money.caps_saved_in', { code: caps }), { base: shown })
    : '';
  // with caps kept as saved, spending in the totals currency waits on that same rate: one ask
  const spending = (_sum.budgets_excluded || _sum.excluded || []).filter(row => row.expense && !(kept && row.currency === shown));
  return kept + excludedNotes({ ..._sum, excluded: spending }, row => row.currency === 'XXX'
    ? t('money.spending_no_currency', { amount: formatNumber(row.expense, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })
    : t('money.spending_not_counted', { amount: amountIn(row.currency, row.expense) }), { base: caps });
}

// the envelope adds up in the ledger currency; income with no rate into it waits, said here
function envelopeCurrencyNote() {
  const e = _envelope;
  if (_canonicalLedger || !e?.excluded_currency) return '';
  const income = (e.excluded || []).filter(row => row.income);
  const kept = e.currency !== _cur
    ? excludedNotes({ ..._sum, excluded: [{ currency: e.currency }] },
      () => t('money.envelope_saved_in', { code: e.currency }), { base: _cur })
    : '';
  return kept + excludedNotes({ ..._sum, excluded: income }, row => row.currency === 'XXX'
    ? t('money.income_no_currency')
    : t('money.income_not_counted', { amount: amountIn(row.currency, row.income) }), { base: e.excluded_currency });
}

// a field for a saved amount names its currency when the totals are shown in another one
const savedLabel = label => (savedIn() !== _cur ? `${label} (${savedIn()})` : label);

function currencyBoundary() {
  return `<p class="money-empty-sm" role="status">${t('money.combined_needs_currency')}</p>`;
}

function groupedSummaryAmount(field, showSign = false) {
  if (comparableTotals()) return summaryAmount(_sum?.[field] || 0, showSign);
  return (_sum?.totals_by_currency || []).map(row =>
    `${summaryAmount(row[field], showSign, row.currency)}${row.account_id ? `<span class="ms-label">${esc(row.account_name)}</span>` : ''}`,
  ).join('<br>');
}

function moneyField(label, control) {
  const layout = control.match(/ style="([^"]*)"/)?.[1] || '';
  const native = control.startsWith('<input');
  const tag = native ? 'label' : 'div';
  const content = control.replace(/ style="[^"]*"/, '');
  const labelled = native ? content : content.replace(/^<div /, `<div aria-label="${esc(label)}" `);
  return `<${tag} class="money-field"${layout ? ` style="${layout}"` : ''}><span class="money-field-label">${esc(label)}</span>${labelled}</${tag}>`;
}

function moneySection(id, label, cards, attention = false) {
  if (attention) _expandedMoneySections.add(id);
  const open = _expandedMoneySections.has(id);
  return `<section class="money-section">
    <button type="button" class="money-section-toggle" data-money-section="${id}" aria-expanded="${open}" aria-controls="money-section-${id}"${attention ? ' disabled' : ''}>${label}${attention ? t('money.needs_attention_suffix') : ''}</button>
    <div class="money-grid" id="money-section-${id}"${open ? '' : ' hidden'}>${cards}</div>
  </section>`;
}

function toggleMoneySection(button) {
  if (button.disabled) return;
  const id = button.dataset.moneySection;
  const content = $(`money-section-${id}`);
  if (!content) return;
  const open = !_expandedMoneySections.has(id);
  if (open) _expandedMoneySections.add(id);
  else _expandedMoneySections.delete(id);
  content.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
}

function compactMoney() {
  return globalThis.matchMedia?.('(max-width: 720px)')?.matches || false;
}

function scheduleNeedsAttention() {
  return _recurringError || _recurring.some(r => r.repair_needed || r.repair_pending || r.posting_pending || r.create_pending || r.create_needs_review || r.edit_pending || r.edit_needs_review || r.delete_pending || r.delete_needs_review);
}

function moneyTask(id, cards, attention = false) {
  return `<div class="money-task money-grid" id="money-task-${id}" data-money-task-panel="${id}"${attention ? ' data-attention="true"' : ''}${_moneyPlanTask === id || attention ? '' : ' hidden'}>${cards}</div>`;
}

function selectMoneyTask(button) {
  button.focus({ preventScroll: true });
  _moneyFocusChange++;
  _moneyPlanTask = button.dataset.moneyTask;
  $('money-section-plans').querySelectorAll('[data-money-task]').forEach(item => {
    item.setAttribute('aria-pressed', String(item.dataset.moneyTask === _moneyPlanTask));
  });
  $('money-section-plans').querySelectorAll('[data-money-task-panel]').forEach(panel => {
    panel.hidden = panel.dataset.moneyTaskPanel !== _moneyPlanTask && panel.dataset.attention !== 'true';
  });
}

function captureMoneyFocus(task) {
  return { task, panel: $(`money-task-${task}`), node: document.activeElement, version: _moneyFocusChange };
}

function ownsMoneyFocus(owner) {
  const { task, panel, node, version } = owner;
  return version === _moneyFocusChange && panel === $(`money-task-${task}`)
    && panel?.contains?.(node) && panel.getClientRects().length
    && (document.activeElement === node || (document.activeElement === document.body && node.disabled));
}

function focusMoneyTask(task, target = null) {
  const choice = $('money-body').querySelector(`[data-money-task="${task}"]`);
  (target?.getClientRects().length ? target : choice)?.focus();
}

function refreshMoneyTasks() {
  const plans = $('money-body').querySelector('[data-money-section="plans"]');
  if (!plans) return;
  const pending = { schedules: scheduleNeedsAttention(), budgets: !!_envelope?.pending_assignments?.length || !!$('env-save-status')?.textContent.trim() };
  for (const [id, attention] of Object.entries(pending)) {
    const panel = $(`money-task-${id}`);
    if (!panel) continue;
    if (panel.contains(document.activeElement)) _moneyPlanTask = id;
    panel.dataset.attention = String(attention);
    const card = panel.querySelector(`[data-card="${id === 'schedules' ? 'recurring' : 'envelope'}"]`);
    if (card) {
      card.dataset.attention = String(attention);
      const title = id === 'schedules' ? card.querySelector('h3')?.firstChild : null;
      if (title?.nodeType === 3) title.textContent = t('money.recurring') + (attention ? t('money.needs_attention_suffix') : '');
    }
  }
  const attention = Object.values(pending).some(Boolean);
  plans.textContent = t('money.plans_section') + (attention ? t('money.needs_attention_suffix') : '');
  if (attention) {
    _expandedMoneySections.add('plans');
    $('money-section-plans').hidden = false;
    plans.setAttribute('aria-expanded', 'true');
    if (document.activeElement === plans) focusMoneyTask(_moneyPlanTask);
  }
  plans.disabled = attention;
  $('money-section-plans').querySelectorAll('[data-money-task]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.moneyTask === _moneyPlanTask));
  });
  $('money-section-plans').querySelectorAll('[data-money-task-panel]').forEach(panel => {
    panel.hidden = panel.dataset.moneyTaskPanel !== _moneyPlanTask && panel.dataset.attention !== 'true';
  });
  _decorateCards();
}

function syncMoneyLayout() {
  updateTransactionSaveStatus();
  const entry = $('money-entry-fields');
  const action = $('money-entry-action');
  const totals = $('money-summary-toggle');
  if (!entry || !action || !totals) return;
  const compact = compactMoney();
  // Resizing must not hide the field or recovery control the owner is using.
  if (entry.contains(document.activeElement)) _moneyEntryOpen = true;
  const secondary = $('money-body').querySelectorAll('[data-secondary-total]');
  if ([...secondary].some(card => card.contains(document.activeElement))) _moneyTotalsOpen = true;
  entry.hidden = !!_editTxn || (_moneyEntryOpen === null ? compact : !_moneyEntryOpen);
  action.hidden = !!_editTxn;
  action.classList.toggle('primary', entry.hidden);
  action.setAttribute('aria-expanded', String(!entry.hidden));
  action.textContent = entry.hidden ? t('money.add_transaction') : t('money.close_entry');
  for (const card of secondary) card.hidden = compact && !_moneyTotalsOpen;
  if (!compact && document.activeElement === totals) action.focus();
  totals.hidden = !compact;
  totals.setAttribute('aria-expanded', String(_moneyTotalsOpen));
  totals.textContent = (_moneyTotalsOpen ? t('money.fewer_totals') : t('money.more_totals'))
    + (_forecast ? '' : t('money.forecast_unavailable_suffix'));
}

export function initMoneyPanel(fetcher = fetch) {
  if (!_inited) {
    _inited = true;
    // A disabled control losing focus to body is still ours only until a newer interaction.
    ['focusin', 'pointerdown'].forEach(event => document.addEventListener(event, () => { _moneyFocusChange++; }));
    ['input', 'change'].forEach(event => document.addEventListener(event, e => {
      if (e.target.closest?.('#money-entry-fields')) {
        _moneyEntryChange++;
        updateTransactionSaveStatus();
      }
    }));
    try {
      const pointers = JSON.parse(sessionStorage.getItem(_moneySavedKey) || '[]');
      if (Array.isArray(pointers)) _moneySaved = pointers.filter(item => item && typeof item.id === 'string' && item.id.length <= 128 && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(item.request_id || '')).map(item => ({
        id: item.id, request_id: item.request_id,
        state: ['ready', 'uncertain', 'blocked', 'undone', 'removed', 'unsupported'].includes(item.state) ? item.state : 'ready',
      }));
    } catch {}
    _moneySavedCurrent = _moneySaved.at(-1)?.id;
    try {
      const pending = JSON.parse(sessionStorage.getItem(_createRequestKey('transaction')) || 'null');
      if (pending?.request_id) transactionSaveStatus(t('money.earlier_may_be_saved'));
    } catch {}
    window.matchMedia('(max-width: 720px)').addEventListener('change', syncMoneyLayout);
    $('money-prev')?.addEventListener('click', () => { _month = _shiftMonth(_month, -1); load(fetch, true, false); });
    $('money-next')?.addEventListener('click', () => { _month = _shiftMonth(_month, 1); load(fetch, true, false); });
    $('money-manage-toggle')?.addEventListener('click', () => {
      const panel = $('money-management');
      panel.hidden = !panel.hidden;
      $('money-manage-toggle').setAttribute('aria-expanded', String(!panel.hidden));
    });
    $('money-connect')?.addEventListener('click', openBankConnections);
    $('money-import')?.addEventListener('click', () => {
      window._navigateSpecialistSection?.('finance', 'imports');
    });
  }
  return load(fetcher, !!$('money-body')?.childElementCount, false);
}

function _bankDialog() {
  const overlay = document.createElement('div');
  overlay.className = 'dialog-overlay finance-bank-overlay';
  overlay.innerHTML = `<section class="dialog-card finance-bank-dialog" role="dialog" aria-modal="true" aria-labelledby="finance-bank-title">
    <header class="finance-bank-head"><div><h2 id="finance-bank-title">${t('finance.bank_connections')}</h2><p>${t('finance.bank_readonly')}</p></div><button class="btn" type="button" data-bank-close>${t('common.close')}</button></header>
    <div class="finance-bank-status" role="status" aria-live="polite"></div>
    <button class="btn" type="button" data-bank-refresh>${t('finance.bank_refresh')}</button><div class="finance-bank-connections"></div>
    <div class="finance-bank-setup">
      <section><h3>SimpleFIN</h3><p>${t('finance.simplefin_help')}</p><label for="finance-simplefin-token">${t('finance.setup_token')}</label><textarea id="finance-simplefin-token" rows="3" autocomplete="off" spellcheck="false"></textarea><button class="btn" type="button" data-bank-simplefin>${t('finance.connect_simplefin')}</button></section>
      <section><h3>Plaid</h3><p>${t('finance.plaid_help')}</p><label for="finance-plaid-client">${t('finance.client_id')}</label><input id="finance-plaid-client" autocomplete="off"><label for="finance-plaid-secret">${t('finance.secret')}</label><input id="finance-plaid-secret" type="password" autocomplete="new-password"><div class="finance-bank-environments" role="group" aria-label="${t('finance.plaid_environment')}"><button class="btn active" type="button" aria-pressed="true" data-plaid-env="sandbox">${t('finance.env_sandbox')}</button><button class="btn" type="button" aria-pressed="false" data-plaid-env="production">${t('finance.env_production')}</button></div><button class="btn" type="button" data-bank-plaid>${t('finance.connect_plaid')}</button></section>
    </div>
  </section>`;
  return overlay;
}

let _bankOverlay = null;
let _bankActionPending = false;

function _confirmedConnection(value, provider) {
  if (!value || typeof value.id !== 'string' || !value.id || value.provider !== provider
    || value.status !== (provider === 'simplefin' ? 'connected' : 'link_required')) {
    throw new Error(t('finance.connection_unconfirmed'));
  }
  return value;
}

async function openBankConnections() {
  if (_bankOverlay?.isConnected) { _bankOverlay.querySelector('[data-bank-close]').focus(); return; }
  const overlay = _bankDialog();
  _bankOverlay = overlay;
  const prior = document.activeElement;
  document.body.append(overlay);
  const controller = new AbortController();
  const status = overlay.querySelector('.finance-bank-status');
  const setStatus = (message, error = false) => {
    if (!overlay.isConnected) return;
    status.textContent = message; status.dataset.error = error ? 'true' : 'false';
  };
  const dialog = overlay.querySelector('[role="dialog"]');
  let focusBoundary = null;
  const close = () => {
    controller.abort();
    focusBoundary?.deactivate();
    focusBoundary?.destroy();
    focusBoundary = null;
    overlay.remove();
    if (_bankOverlay === overlay) _bankOverlay = null;
  };
  overlay.querySelector('[data-bank-close]').addEventListener('click', close);
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  focusBoundary = createFocusBoundary(dialog, { trigger: prior, onEscape: close });
  focusBoundary.activate({ source: prior, focus: overlay.querySelector('[data-bank-close]') });
  let environment = 'sandbox', refreshSequence = 0;
  const updateBusy = () => {
    const target = _bankOverlay;
    if (!target?.isConnected) return;
    target.querySelector('[role="dialog"]').setAttribute('aria-busy', String(_bankActionPending));
    target.querySelectorAll('button:not([data-bank-close])').forEach(button => {
      button.disabled = _bankActionPending || button.dataset.unavailable === 'true';
    });
  };
  const action = async work => {
    if (_bankActionPending || !overlay.isConnected) return;
    _bankActionPending = true;
    updateBusy();
    try { await work(); }
    catch (error) { if (error.name !== 'AbortError') setStatus(error.message, true); }
    finally {
      _bankActionPending = false; updateBusy();
      if (overlay.isConnected && (!document.activeElement?.isConnected || document.activeElement === document.body)) {
        overlay.querySelector('[data-bank-close]').focus();
      }
    }
  };
  overlay.querySelectorAll('[data-plaid-env]').forEach(button => button.addEventListener('click', () => {
    if (_bankActionPending) return;
    environment = button.dataset.plaidEnv;
    overlay.querySelectorAll('[data-plaid-env]').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); });
  }));
  const refresh = async () => {
    const sequence = ++refreshSequence;
    const payload = await _ownerFetch('/api/finance/connections');
    if (!Array.isArray(payload?.connections)) throw new Error(t('finance.bank_read_failed'));
    if (!overlay.isConnected || sequence !== refreshSequence) return;
    const host = overlay.querySelector('.finance-bank-connections');
    host.innerHTML = payload.connections.length ? payload.connections.map(connection => `<article class="finance-bank-row" data-bank-id="${esc(connection.id)}"><div><strong>${esc(connection.label)}</strong><span>${connection.provider === 'plaid' ? `${connection.environment === 'sandbox' ? t('finance.sandbox_test') : t('finance.env_production')} · ` : ''}${esc(connection.status)}${connection.last_synced_at ? ` · ${t('finance.bank_synced', { date: esc(formatDate(connection.last_synced_at)) })}` : ''}</span>${connection.last_error ? `<small>${esc(connection.last_error)}</small>` : ''}</div><div><button class="btn" type="button" data-bank-sync${connection.status === 'link_required' ? ' disabled data-unavailable="true"' : ''}>${t('finance.bank_sync')}</button>${connection.provider === 'plaid' ? `<button class="btn" type="button" data-bank-link>${connection.item_id ? t('finance.bank_reconnect') : t('finance.bank_open_link')}</button>` : ''}<button class="btn" type="button" data-bank-disconnect>${t('finance.bank_disconnect')}</button></div></article>`).join('') : `<p class="finance-bank-empty">${t('finance.bank_none')}</p>`;
    host.querySelectorAll('[data-bank-id]').forEach(row => {
      const connection = payload.connections.find(item => item.id === row.dataset.bankId);
      row.querySelector('[data-bank-sync]')?.addEventListener('click', () => action(async () => {
        setStatus(t('finance.bank_syncing'));
        const result = await _ownerFetch(`/api/finance/connections/${encodeURIComponent(connection.id)}/sync`, { method: 'POST' });
        if (result?.id !== connection.id || !Number.isInteger(result.created) || !Number.isInteger(result.updated)) {
          throw new Error(t('finance.sync_unconfirmed'));
        }
        setStatus(t('finance.sync_complete', { created: result.created, updated: result.updated }));
        await refresh();
        await load(fetch, true);
      }));
      row.querySelector('[data-bank-link]')?.addEventListener('click', () => action(() => finishLink(connection)));
      row.querySelector('[data-bank-disconnect]')?.addEventListener('click', () => action(async () => {
        if (!await dlgConfirm(t('finance.disconnect_confirm', { label: connection.label }))) return;
        controller.signal.throwIfAborted();
        const result = await _ownerFetch(`/api/finance/connections/${encodeURIComponent(connection.id)}`, { method: 'DELETE' });
        if (result?.ok !== true || result.connection_id !== connection.id) throw new Error(t('finance.disconnect_unconfirmed'));
        setStatus(t('finance.connection_revoked'));
        await refresh();
      }));
    });
    updateBusy();
  };
  const finishLink = async connection => {
    controller.signal.throwIfAborted();
    setStatus(t('finance.opening_link'));
    try {
      const result = await openPlaidLink(connection, { signal: controller.signal });
      setStatus(result.cancelled ? t('finance.link_closed') : t('finance.link_connected'));
    } finally {
      // Configuration is already saved even if Link was cancelled or could not load.
      if (overlay.isConnected) await refresh();
    }
  };
  overlay.querySelector('[data-bank-refresh]').addEventListener('click', () => action(async () => {
    setStatus(t('finance.bank_refreshing')); await refresh(); setStatus(t('finance.bank_refreshed'));
  }));
  overlay.querySelector('[data-bank-simplefin]').addEventListener('click', () => action(async () => {
    const field = overlay.querySelector('#finance-simplefin-token'), token = field.value;
    if (!token.trim()) { setStatus(t('finance.simplefin_enter'), true); field.focus(); return; }
    setStatus(t('finance.simplefin_exchanging'));
    _confirmedConnection(await _ownerFetch('/api/finance/connections/simplefin', { method: 'POST', body: { setup_token: token.trim() } }), 'simplefin');
    if (field.value === token) field.value = '';
    setStatus(t('finance.simplefin_connected'));
    await refresh();
  }));
  overlay.querySelector('[data-bank-plaid]').addEventListener('click', () => action(async () => {
    const clientId = overlay.querySelector('#finance-plaid-client'), secret = overlay.querySelector('#finance-plaid-secret');
    const submittedSecret = secret.value;
    if (!clientId.value.trim() || !submittedSecret.trim()) { setStatus(t('finance.plaid_enter'), true); return; }
    setStatus(t('finance.plaid_saving'));
    const connection = _confirmedConnection(await _ownerFetch('/api/finance/connections/plaid', { method: 'POST', body: { client_id: clientId.value.trim(), secret: submittedSecret, environment } }), 'plaid');
    if (secret.value === submittedSecret) secret.value = '';
    controller.signal.throwIfAborted();
    await finishLink(connection);
  }));
  updateBusy();
  try { await refresh(); } catch (error) { setStatus(error.message, true); }
}

async function load(fetcher = fetch, preserveDrafts = false, preserveFilters = preserveDrafts) {
  const sequence = ++_moneyLoadSequence;
  const currencyRead = ++_currencyReadSequence;
  _moneyRefreshing = true;
  _moneyRefreshFailed = false;
  renderSavedTransactions();
  const month = _month;
  const request = (path, options = {}) => api(path, options, fetcher);
  const lbl = $('money-month-label'); if (lbl) lbl.textContent = _monthLabel(_month);
  _setMonthUrl();
  clearTimeout(_searchTimer);
  _searchSequence += 1;
  if (!preserveFilters) {
    _searchResults = null;   // month change / reload clears any active search
    _searchStatus = '';
    _tagFilter = '';
    if (preserveDrafts) for (const id of ['txn-search', 'txn-min', 'txn-max']) if ($(id)) $(id).value = '';
  }
  try {
    // Legacy reads post due entries before balances; Actual owns posting after cutover.
    const recurring = await request('/api/money/recurring').then(rows => {
      if (!Array.isArray(rows)) throw new Error('invalid schedule list');
      return rows;
    }).catch(() => null);
    const results = await Promise.all([
      request('/api/money/accounts'),
      request(`/api/money/transactions?month=${month}`),
      request('/api/money/budgets'),
      request(`/api/money/summary?month=${month}`),
      request('/api/money/rules').catch(() => []),
      request(`/api/money/envelope?month=${month}`).catch(() => null),
      request('/api/money/age-of-money').catch(() => null),
      request(`/api/money/forecast?month=${month}`).catch(error => { if (sequence === _moneyLoadSequence) _forecastError = forecastFailure(error); return null; }),
      request('/api/money/networth-history?months=6').catch(() => null),
      request('/api/money/holdings').catch(() => null),
      request(`/api/money/alerts?month=${month}`).catch(() => null),
      request('/api/money/currencies').then(result => result.codes || []).catch(() => []),
    ]);
    const goalReply = await request('/api/money/goals').catch(() => null);
    const goals = goalReply?.goals || [];
    if (sequence !== _moneyLoadSequence || month !== _month) return false;
    if (preserveDrafts && recurring === null && _recurringEdit) throw new Error('schedule refresh unavailable');
    const currencyCodes = results.pop();
    [_accounts, _txns, _budgets, _sum, _rules, _envelope, _aom, _forecast, _nwhist, _holdings, _alerts] = results;
    if (currencyRead === _currencyReadSequence) _currencyCodes = currencyCodes;
    _recurring = recurring || [];
    _recurringError = recurring === null;
    _recurringStatus = '';
    _goals = goals;
    _goalsCurrency = goalReply?.currency || '';
    _canonicalLedger = _sum?.ledger === 'actual';
    if (_recurringEdit && !_recurring.some(row => row.id === _recurringEdit.id && row.editable)) _recurringEdit = null;
    _cur = totalsUnit();
  } catch {
    if (sequence !== _moneyLoadSequence) return false;
    _moneyRefreshing = false;
    if (preserveDrafts) {
      _moneyRefreshFailed = true;
      renderSavedTransactions();
      return false;
    }
    _moneyRefreshFailed = true;
    $('money-entry-slot').replaceChildren();
    $('money-body').innerHTML = savedTransactions() + `<div class="money-empty">${t('money.load_failed')}</div>`;
    wireSavedTransactions();
    return false;
  }
  await hydrateSavedTransactions(request);
  if (sequence !== _moneyLoadSequence || month !== _month) return false;
  _moneyRefreshing = false;
  _moneyRefreshFailed = false;
  render(preserveDrafts);
  if (preserveDrafts) {
    if (_tagFilter) await filterByTag(_tagFilter);
    else await applySearch();
  }
  return true;
}

async function readRecurring(request) {
  try {
    const rows = await request('/api/money/recurring');
    if (!Array.isArray(rows)) throw new Error('invalid schedule list');
    _recurring = rows;
    _recurringError = false;
  } catch {
    _recurring = [];
    _recurringError = true;
  }
}

// ── render ────────────────────────────────────────────────────────────────────
function render(preserveDrafts = false, preserveFilters = preserveDrafts) {
  const b = $('money-body'); if (!b) return;
  const retained = preserveDrafts ? retainMoneyDrafts(b, preserveFilters) : null;
  const savedFocus = retainSavedFocus();
  const clearedFocus = b.contains(document.activeElement) ? document.activeElement.dataset.clearTxn : null;
  _snapshotRecurringEdit();
  $('money-entry-slot').innerHTML = _accounts.length
    ? `<button type="button" class="btn primary money-entry-action" id="money-entry-action" aria-controls="money-entry-fields">${t('money.add_transaction')}</button>`
    : '';
  if (!_accounts.length) {
    b.innerHTML = savedTransactions() + `<div class="money-empty">
      <div class="money-empty-title">${t('money.no_accounts')}</div>
      <div class="money-empty-sub">${t('money.add_account_to_start')}</div>
      ${_accountForm()}</div>`;
    _wireAccountForm();
    wireSavedTransactions();
    if (retained) restoreMoneyDrafts(b, retained);
    restoreSavedFocus(savedFocus);
    return;
  }
  b.innerHTML =
    savedTransactions() +
    `<section class="money-card money-entry-card" id="money-entry-fields">
      <h2>${t('money.new_transaction')}</h2>${addTxnRow()}${transferRow()}
    </section>` + summaryCards() +
    `<button type="button" class="money-section-toggle" id="money-summary-toggle" aria-controls="money-income money-net money-projection">${t('money.more_totals')}</button>` +
    `<div id="money-alerts-content" role="status" tabindex="-1">${alertsStrip()}</div>` +
    `<section class="money-card money-txns">
      <h2>${t('money.transactions_month', { month: _monthLabel(_month) })}</h2>
      <div class="txn-search-wrap" role="group" aria-label="${t('money.filter_transactions')}">
        ${moneyField(t('money.search_transactions'), `<input type="text" id="txn-search" class="settings-input" placeholder="${t('money.search_placeholder')}" autocomplete="off">`)}
        <button type="button" class="btn" id="txn-range-toggle" aria-expanded="false" aria-controls="txn-amount-range">${t('money.amount_range')}</button>
        <div id="txn-amount-range" hidden>
          ${moneyField(t('money.minimum_amount'), '<input type="text" id="txn-min" class="settings-input" placeholder="0.00" inputmode="decimal">')}
          ${moneyField(t('money.maximum_amount'), '<input type="text" id="txn-max" class="settings-input" placeholder="0.00" inputmode="decimal">')}
        </div>
      </div>
      <div id="txn-rows">${txnList()}</div>
    </section>` +
    moneySection('plans', t('money.plans_section'), `
      <div class="money-task-choices" role="group" aria-label="${t('money.manage_money')}">
        ${[['accounts', t('money.tab_accounts')], ['budgets', t('money.tab_budgets')], ['schedules', t('money.tab_schedules')], ['goals', t('money.tab_goals')]].map(([id, label]) => `<button type="button" class="btn" data-money-task="${id}" aria-pressed="${_moneyPlanTask === id}" aria-controls="money-task-${id}">${label}</button>`).join('')}
      </div>
      ${moneyTask('accounts', `
      <section class="money-card" data-card="accounts"><h3>${t('money.tab_accounts')}</h3>${accountsList()}<div id="money-acct-form-wrap"></div>
        <button class="btn money-add-acct" id="money-add-acct">${t('money.add_account')}</button></section>`)}
      ${moneyTask('budgets', `
      <section class="money-card money-envelope" data-card="envelope"${_envelope?.pending_assignments?.length ? ' data-attention="true"' : ''}>${envelopeHeading()}${envelopeCard()}</section>
      <section class="money-card" data-card="budgets"><h3>${t('money.spending_caps')}</h3>${comparableTotals() ? budgetsCurrencyNote() + budgetsList() + _budgetForm() : currencyBoundary()}</section>
      `, !!_envelope?.pending_assignments?.length)}
      ${moneyTask('schedules', `
      <section class="money-card" data-card="recurring"${scheduleNeedsAttention() ? ' data-attention="true"' : ''}><h3 tabindex="-1">${t('money.recurring')}${scheduleNeedsAttention() ? t('money.needs_attention_suffix') : ''}</h3><div id="recurring-content"><div id="recurring-list">${recurringList()}</div>${_recurringForm()}</div></section>
      `, scheduleNeedsAttention())}
      ${moneyTask('goals', `<section class="money-card" data-card="goals"><h3>${t('money.tab_goals')}</h3>${goalsCard()}</section>`)}
    `, scheduleNeedsAttention() || !!_envelope?.pending_assignments?.length) +
    moneySection('analytics', t('money.analytics_tools'), `
      <section class="money-card" data-card="category"><h3>${t('money.spending_by_category')}</h3>${catChart()}</section>
      <section class="money-card" data-card="trend"><h3>${t('money.last_6_months')}</h3>${trendChart()}</section>
      <section class="money-card" data-card="networth"><h3 tabindex="-1">${t('money.net_worth_over_time')}</h3><div id="nw-history-content">${networthCard()}</div></section>
      <section class="money-card" data-card="holdings"><h3>${t('money.investments')}</h3>${holdingsCard()}</section>
      <section class="money-card" data-card="reports"><h3>${t('money.reports')}</h3>${reportsCard()}</section>
      <section class="money-card" data-card="rules"><h3>${t('money.auto_categorize')}${_rules.length ? ` <button class="btn rules-apply" id="rules-apply" title="${t('money.apply_to_uncategorized')}">${t('money.apply')}</button>` : ''}</h3>${rulesList()}${_ruleForm()}</section>
    `);
  wire();
  tickNumbers(b, '.money-summary .ms-number');
  wireSavedTransactions();
  if (retained) restoreMoneyDrafts(b, retained);
  restoreSavedFocus(savedFocus);
  if (clearedFocus && document.activeElement === document.body) b.querySelector(`[data-clear-txn="${CSS.escape(clearedFocus)}"]`)?.focus();
}

function retainMoneyDrafts(body, preserveFilters) {
  const selectors = ['#money-entry-fields', '#money-acct-form-wrap', '#acct-form',
    '.budget-form', '#recurring-create', '#rce-panel', '.goal-form', '.hold-form', '.report-form',
    '.rule-form', '.env-add'];
  if (preserveFilters) selectors.push('.txn-search-wrap');
  const nodes = selectors.map(selector => ({ selector, node: body.querySelector?.(selector) })).filter(item => item.node);
  for (const node of body.querySelectorAll?.('.rc-panel, .txn-edit, .txn-split-editor, .env-assign') || []) {
    const selector = node.id ? `#${CSS.escape(node.id)}` : node.classList.contains('env-assign')
      ? `.env-assign[data-cat="${CSS.escape(node.dataset.cat)}"]`
      : `.${node.classList.contains('txn-edit') ? 'txn-edit' : 'txn-split-editor'}[data-id="${CSS.escape(node.dataset.id)}"]`;
    nodes.push({ selector, node });
  }
  const active = document.activeElement;
  let control = active?.id ? `#${CSS.escape(active.id)}` : null;
  if (!control && body.contains(active) && active.matches('button, [role="button"], a')) {
    const row = active.closest('.txn[data-id]');
    const scope = row ? `.txn[data-id="${CSS.escape(row.dataset.id)}"] ` : '';
    for (const attribute of active.attributes) {
      if (!attribute.name.startsWith('data-')) continue;
      const selector = `${scope}${active.localName}[${attribute.name}="${CSS.escape(attribute.value)}"]`;
      if (body.querySelectorAll(selector).length === 1) { control = selector; break; }
    }
  }
  return { nodes, active, control, focusVersion: _moneyFocusChange };
}

function restoreMoneyDrafts(body, retained) {
  for (const { selector, node } of retained.nodes) {
    const replacement = body.querySelector(selector);
    if (node.classList.contains('txn-edit') && node.dataset.id === _editTxn) {
      const context = node.querySelector('[data-edit-context]');
      if (context) context.hidden = !!replacement;
      if (!replacement) {
        const rows = body.id === 'txn-rows' ? body : body.querySelector('#txn-rows');
        rows?.prepend(node);
        continue;
      }
    }
    if (!replacement || replacement === node) continue;
    replacement.replaceWith(node);
    if (node.classList.contains('rc-panel')) node.querySelector('.rc-out')?.replaceChildren();
  }
  // Retain the draft control, but refresh choices from the latest successful read.
  const currency = body.querySelector('#af-currency');
  if (currency && _currencyCodes.length) {
    populateDropdown(currency,
      [{ value: '', label: t('money.choose_currency') }, ..._currencyCodes.map(value => ({ value, label: value }))],
      getDropdownValue(currency));
  }
  const create = $('recurring-create');
  if (create) create.hidden = !!recurringCreateUnavailable();
  syncMoneyLayout();
  if (retained.focusVersion !== _moneyFocusChange || document.activeElement !== document.body) return;
  const candidates = retained.control ? document.querySelectorAll(retained.control) : [];
  const target = retained.active?.isConnected ? retained.active
    : candidates.length === 1 ? candidates[0]
    : retained.active?.id === 'money-entry-action' ? $('af-name') : null;
  if (target && !target.disabled && !target.closest('[hidden], [inert]') && target.getClientRects().length) target.focus({ preventScroll: true });
}

function persistSavedTransactions() {
  try {
    const chosen = _moneySaved.find(item => item.id === _moneySavedCurrent);
    const receipts = chosen ? [..._moneySaved.filter(item => item !== chosen), chosen] : _moneySaved;
    sessionStorage.setItem(_moneySavedKey, JSON.stringify(receipts.map(item => ({
      id: item.id, request_id: item.request_id, state: item.state,
    }))));
    return true;
  } catch { return false; }
}

async function hydrateSavedTransactions(request) {
  await Promise.all(_moneySaved.filter(item => !item.saved && item.state !== 'unsupported').map(async item => {
    try {
      const result = await request(`/api/money/transactions/${encodeURIComponent(item.id)}/undo?request_id=${encodeURIComponent(item.request_id)}`);
      if (!_moneySaved.includes(item)) return;
      if (result.removed) {
        if (item.state !== 'undone') item.state = 'removed';
      } else item.saved = result;
    } catch {} // Keep the pointer and explicit retry; a failed read proves no outcome.
  }));
  persistSavedTransactions();
}

function savedTransactions() {
  const focused = document.activeElement?.closest?.('[data-saved-txn]')?.dataset.savedTxn;
  const current = _moneySaved.find(item => item.id === _moneySavedCurrent) || _moneySaved.at(-1);
  const recent = item => item === current || item.id === focused || item.busy || item.state === 'uncertain';
  const receipt = item => {
    const saved = item.saved;
    const label = saved ? `${saved.payee || saved.category || t('money.kind_transaction')} · ${signed(saved.amount, saved.undo ? saved.original_currency_code || 'XXX' : _cur)} · ${saved.date}` : t('money.saved_transaction');
    const status = item.state === 'undone' ? t('money.txn_undone') : item.state === 'removed' ? t('money.txn_removed')
      : item.state === 'uncertain' ? t('money.undo_unconfirmed')
      : item.state === 'blocked' ? t('money.undo_blocked')
      : item.state === 'unsupported' ? t('money.undo_unsupported')
      : t('money.txn_saved');
    const canUndo = !['undone', 'removed', 'blocked', 'unsupported'].includes(item.state);
    return `<div class="money-saved-result" data-saved-txn="${esc(item.id)}"><p role="status">${esc(status)} <span>${esc(label)}</span></p>
      <div class="money-saved-actions">${canUndo ? `<button type="button" class="btn" data-undo-saved="${esc(item.id)}" aria-label="${item.state === 'uncertain' ? t('money.retry_undo_named', { name: esc(saved?.payee || t('money.saved_transaction')) }) : t('money.undo_named', { name: esc(saved?.payee || t('money.saved_transaction')) })}"${item.busy ? ' disabled' : ''}>${item.busy ? t('money.undoing') : item.state === 'uncertain' ? t('money.retry_undo') : t('money.undo')}</button>` : ''}
      <button type="button" class="btn" data-dismiss-saved="${esc(item.id)}"${item.busy || item.state === 'uncertain' ? ' disabled' : ''}>${t('common.dismiss')}</button></div></div>`;
  };
  const receipts = _moneySaved.filter(recent).map(receipt).join('');
  const earlier = _moneySaved.filter(item => !recent(item));
  const history = earlier.length ? `<button type="button" class="btn" id="money-saved-history" aria-controls="money-earlier-saved" aria-expanded="${_moneySavedExpanded}">${t(_moneySavedExpanded ? 'money.hide_earlier' : 'money.show_earlier', { count: earlier.length })}</button><div id="money-earlier-saved"${_moneySavedExpanded ? '' : ' hidden'}>${earlier.map(receipt).join('')}</div>` : '';
  return `<div id="money-save-results" tabindex="-1" role="region" aria-label="${t('money.saved_transactions')}">${receipts}${history}${_moneyRefreshing ? `<p role="status">${t('money.updating_list')}</p>` : _moneyRefreshFailed ? `<p role="status">${t('money.refresh_failed')}</p><button type="button" class="btn" id="money-result-retry">${t('money.retry_balances')}</button>` : ''}</div>`;
}

function wireSavedTransactions() {
  const root = $('money-save-results');
  if (!root) return;
  $('money-saved-history')?.addEventListener('click', event => {
    _moneySavedExpanded = !_moneySavedExpanded;
    if (!_moneySavedExpanded && $('money-earlier-saved')?.contains(document.activeElement)) event.currentTarget.focus();
    renderSavedTransactions();
  });
  (root.querySelectorAll?.('[data-undo-saved]') || []).forEach(button => button.addEventListener('click', () => undoSavedTransaction(button)));
  (root.querySelectorAll?.('[data-dismiss-saved]') || []).forEach(button => button.addEventListener('click', () => {
    const item = _moneySaved.find(receipt => receipt.id === button.dataset.dismissSaved);
    if (!item || item.busy || item.state === 'uncertain') return;
    _moneySaved = _moneySaved.filter(item => item.id !== button.dataset.dismissSaved);
    _completeCreateRequest('transaction', item.request_id);
    persistSavedTransactions();
    renderSavedTransactions();
    savedResultFocusTarget()?.focus();
  }));
  $('money-result-retry')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    const focusVersion = _moneyFocusChange;
    button.disabled = true;
    await load(fetch, true);
    if (_moneyFocusChange === focusVersion && (document.activeElement === button || document.activeElement === document.body)) savedResultFocusTarget()?.focus();
  });
}

function savedResultFocusTarget() {
  return _moneySaved.length || _moneyRefreshFailed ? $('money-save-results') : $('money-entry-action') || $('af-name');
}

function retainSavedFocus() {
  const active = document.activeElement;
  if (!$('money-save-results')?.contains(active)) return null;
  const selector = active.dataset.undoSaved ? `[data-undo-saved="${CSS.escape(active.dataset.undoSaved)}"]`
    : active.dataset.dismissSaved ? `[data-dismiss-saved="${CSS.escape(active.dataset.dismissSaved)}"]`
    : active.id ? `#${CSS.escape(active.id)}` : '#money-save-results';
  return { active, selector, version: _moneyFocusChange };
}

function restoreSavedFocus(retained) {
  if (!retained || retained.version !== _moneyFocusChange
      || (document.activeElement !== document.body && document.activeElement !== retained.active)) return;
  const target = document.querySelector(retained.selector);
  (target && !target.disabled && !target.closest('[hidden]') && (target.id !== 'money-save-results' || _moneySaved.length || _moneyRefreshFailed)
    ? target : savedResultFocusTarget())?.focus({ preventScroll: true });
}

function renderSavedTransactions() {
  const root = $('money-save-results');
  if (!root) return;
  const retained = retainSavedFocus();
  root.outerHTML = savedTransactions();
  wireSavedTransactions();
  restoreSavedFocus(retained);
}

async function undoSavedTransaction(button) {
  const item = _moneySaved.find(receipt => receipt.id === button.dataset.undoSaved);
  if (!item || item.busy || item.state === 'unsupported') return;
  if (_editTxn === item.id || _splitTxn === item.id) {
    toast(t('money.finish_edit_first'), 'error');
    return;
  }
  const previousState = item.state;
  const previousCurrent = _moneySavedCurrent;
  _moneySavedCurrent = item.id;
  item.state = 'uncertain';
  if (!persistSavedTransactions()) {
    item.state = previousState;
    _moneySavedCurrent = previousCurrent;
    toast(t('money.undo_recovery_failed'), 'error');
    return;
  }
  _completeCreateRequest('transaction', item.request_id);
  const focusVersion = _moneyFocusChange;
  _moneySavedAction = ++_moneySavedActionSequence;
  item.busy = true;
  button.disabled = true;
  button.textContent = t('money.undoing');
  $('money-save-results')?.querySelector(`[data-dismiss-saved="${CSS.escape(item.id)}"]`)?.setAttribute('disabled', '');
  setTransactionUndoAvailability(item.id);
  try {
    const result = await api(`/api/money/transactions/${encodeURIComponent(item.id)}/undo`, { method: 'POST', body: { request_id: item.request_id } });
    if (result?.ok !== true || !['undone', 'already_removed'].includes(result.outcome)) throw new Error('undo not confirmed');
    item.state = result.outcome === 'already_removed' ? 'removed' : 'undone';
    persistSavedTransactions();
    await load(fetch, true);
  } catch (error) {
    item.state = error.status === 409 && /Actual/.test(error.message) ? 'unsupported'
      : error.status === 400 || error.status === 409 ? 'blocked' : 'uncertain';
    persistSavedTransactions();
    if (item.state === 'blocked' || item.state === 'unsupported') await load(fetch, true);
  } finally {
    item.busy = false;
    setTransactionUndoAvailability(item.id);
    renderSavedTransactions();
    if (_moneyFocusChange === focusVersion && (document.activeElement === button || document.activeElement === document.body)) $('money-save-results')?.focus();
  }
}

function setTransactionUndoAvailability(id) {
  const blocked = _moneySaved.some(item => item.id === id && (item.busy || item.state === 'uncertain'));
  const row = $('txn-rows')?.querySelector(`[data-id="${CSS.escape(id)}"]`);
  row?.querySelectorAll('[data-edit-txn], [data-clear-txn], [data-split-txn], [data-receipt-txn], [data-del-txn]').forEach(button => { button.disabled = blocked; });
}

function summaryCards() {
  const s = _sum || {};
  return `${comparableTotals() ? moneyCurrency() : `<p class="money-empty-sm" role="status">${t('money.currency_not_set_separate')}</p>`}<div class="money-summary">
    <div class="ms-card"><span class="ms-label">${t('money.net_worth')}</span><span class="ms-val">${groupedSummaryAmount('net_worth')}</span></div>
    <div class="ms-card" id="money-income" data-secondary-total><span class="ms-label">${t('money.income_this_month')}</span><span class="ms-val pos">${groupedSummaryAmount('income')}</span></div>
    <div class="ms-card"><span class="ms-label">${t('money.spent_this_month_label')}</span><span class="ms-val neg">${groupedSummaryAmount('expense')}</span></div>
    <div class="ms-card" id="money-net" data-secondary-total><span class="ms-label">${t('money.net')}</span><span class="ms-val ${s.net >= 0 ? 'pos' : 'neg'}">${groupedSummaryAmount('net', true)}</span></div>
    ${forecastCard()}
  </div>`;
}

function summaryAmount(n, showSign = false, currency = _cur) {
  const prefix = currencyPrefix(currency);
  const amount = fmt(Math.abs(n), currency).slice(prefix.length);
  const sign = Math.round((n || 0) * 100) < 0 ? '−' : showSign ? '+' : '';
  // with no currency the figure leads and the safety label sits under it, so a sign stays on the number
  if (currency === 'XXX') return `<span class="ms-number">${esc(sign + amount)}</span><span class="ms-currency">${esc(prefix.trim())}</span>`;
  return `${esc(sign + prefix)}<wbr><span class="ms-number">${esc(amount)}</span>`;
}

function forecastCard() {
  if (!comparableTotals()) return `<div class="ms-card" id="money-projection" data-secondary-total><span class="ms-label">${t('money.projected')}</span>${currencyBoundary()}</div>`;
  return `<div class="ms-card" id="money-projection" data-secondary-total data-forecast tabindex="-1"><span class="ms-label">${t('money.projected')}</span>
    ${_forecast ? `<span class="ms-val ${_forecast.projected < 0 ? 'neg' : ''}">${summaryAmount(_forecast.projected)}</span>` : `<span class="ms-unavailable" role="status">${esc(_forecastError || t('money.forecast_failed'))}</span><button type="button" class="btn ms-retry" id="forecast-retry">${t('common.retry')}</button>`}</div>`;
}

function forecastFailure(error) {
  return error?.status === 409 && /schedule|recurrence/i.test(error.message)
    ? t('money.fix_actual_schedule')
    : t('money.forecast_failed');
}

async function retryForecast() {
  const button = $('forecast-retry');
  const ownedFocus = document.activeElement === button;
  if (ownedFocus) _moneyTotalsOpen = true;
  button.disabled = true;
  button.textContent = t('money.retrying');
  try { _forecast = await api(`/api/money/forecast?month=${_month}`); }
  catch (error) { _forecast = null; _forecastError = forecastFailure(error); }
  const card = document.querySelector('[data-forecast]');
  if (!card) return;
  const restoreFocus = card.contains(document.activeElement)
    || (ownedFocus && document.activeElement === document.body);
  card.outerHTML = forecastCard();
  wireForecast();
  syncMoneyLayout();
  if (restoreFocus && !$('money-projection').hidden && $('money-projection').getClientRects().length) {
    (_forecast ? $('money-projection') : $('forecast-retry'))?.focus();
  }
}

function wireForecast() {
  $('forecast-retry')?.addEventListener('click', retryForecast);
}

function alertsStrip() {
  if (!comparableTotals()) return '';
  const a = _alerts;
  if (!a) return `<div class="money-alerts money-history-error">${t('money.alerts_failed')} <button type="button" class="btn" id="alerts-retry">${t('common.retry')}</button></div>`;
  const items = [];
  (a.upcoming_bills || []).forEach(b => {
    const amount = b.amount == null ? t('money.amount_varies') : `${b.amount_kind === 'approx' ? '≈' : ''}${signed(b.amount, b.currency || _cur)}`;
    items.push(`<span class="alert-chip bill">${_si('calendar')} ${t('money.alert_bill', { payee: esc(b.payee), amount, days: b.days })}</span>`);
  });
  (a.large_purchases || []).forEach(p => items.push(`<span class="alert-chip big">${_si('warning')} ${t('money.alert_large', { what: esc(p.payee) || esc(p.category) || '—', amount: signed(p.amount, p.currency || _cur) })}</span>`));
  (a.watch_hits || []).forEach(w => items.push(`<span class="alert-chip watch">${_si('eye')} ${esc(w.watch)}: ${esc(w.payee) || '—'} ${signed(w.amount, w.currency || _cur)}</span>`));
  (a.low_balance || []).forEach(l => items.push(`<span class="alert-chip big">${_si('trend-down')} ${t('money.alert_low', { name: esc(l.name), balance: fmt(l.balance, l.currency || _cur), threshold: fmt(l.threshold, l.currency || _cur) })}</span>`));
  if (!items.length) return '';
  return `<div class="money-alerts">${items.join('')}</div>`;
}

async function retryAlerts() {
  const button = $('alerts-retry');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try { _alerts = await api(`/api/money/alerts?month=${_month}`); }
  catch { _alerts = null; }
  const content = $('money-alerts-content');
  if (!content) return;
  content.innerHTML = alertsStrip() || `<div class="money-empty-sm">${t('money.no_alerts')}</div>`;
  wireAlerts();
  (_alerts ? content : $('alerts-retry'))?.focus();
}

function wireAlerts() {
  $('alerts-retry')?.addEventListener('click', retryAlerts);
}

function networthCard() {
  if (!comparableTotals()) return currencyBoundary();
  if (_nwhist === null) return `<div class="money-empty-sm money-history-error" role="status">${t('money.history_failed')} <button type="button" class="btn" id="nw-history-retry">${t('common.retry')}</button></div>`;
  const h = _nwhist || [];
  if (h.length < 2) return `<div class="money-empty-sm">${t('money.not_enough_history')}</div>`;
  const vals = h.map(x => x.net_worth);
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  // center each point in its 1/n slot so the polyline lines up under the slot-centered month labels
  const W = 280, H = 110, step = W / h.length;
  const pts = h.map((x, i) => `${((i + 0.5) * step).toFixed(1)},${(H - ((x.net_worth - min) / span) * (H - 16) - 8).toFixed(1)}`);
  const labels = h.map((x, i) => `<span style="width:${100 / h.length}%">${x.month.slice(5)}</span>`).join('');
  return `<svg class="nw-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts.join(' ')}" fill="none" stroke="var(--cat-blue)" stroke-width="2"></polyline></svg>
    <div class="trend-labels">${labels}</div>
    <div class="nw-now">${t('money.now_amount', { amount: fmt(vals[vals.length - 1]) })}</div>`;
}

async function retryNetworthHistory() {
  const button = $('nw-history-retry');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try { _nwhist = await api('/api/money/networth-history?months=6'); }
  catch { _nwhist = null; }
  const content = $('nw-history-content');
  if (!content) return;
  content.innerHTML = networthCard();
  wireNetworthHistory();
  ($('nw-history-retry') || document.querySelector('.money-card[data-card="networth"] h3'))?.focus();
}

function wireNetworthHistory() {
  $('nw-history-retry')?.addEventListener('click', retryNetworthHistory);
}

const _goalKind = kind => ({ savings: t('money.goal_savings'), debt: t('money.goal_debt') }[kind] || kind);

function goalsCard() {
  if (!comparableTotals()) return currencyBoundary();
  const rows = (_goals || []).map(g => {
    const pct = Math.round((g.progress || 0) * 100);
    const eta = g.eta_months === 0 ? t('money.goal_reached') : (g.eta_months != null ? t('money.goal_months_left', { n: g.eta_months }) : t('money.goal_set_monthly'));
    return `<div class="goal-row" data-id="${g.id}">
      <div class="goal-head"><span class="goal-name">${esc(g.name)} <span class="goal-kind">${esc(_goalKind(g.kind))}</span></span>
        <span class="goal-nums">${fmt(g.current, _goalsCurrency || _cur)} / ${fmt(g.target, _goalsCurrency || _cur)}</span>
        <button class="tx-del" data-del-goal="${g.id}" aria-label="${t('money.remove_goal', { name: esc(g.name) })}" title="${t('common.remove')}">×</button></div>
      <div class="goal-bar-wrap"><div class="goal-bar" style="width:${pct}%"></div></div>
      <div class="goal-eta">${pct}% · ${eta}</div>
    </div>`;
  }).join('');
  return `<div class="goals">${rows || `<div class="money-empty-sm">${t('money.no_goals')}</div>`}</div>
    <div class="goal-form">
      ${moneyField(t('money.goal_name'), `<input type="text" id="gl-name" class="settings-input" placeholder="${t('money.goal_name')}" style="flex:1;min-width:6.25rem">`)}
      ${moneyField(t('money.goal_type'), `<div class="settings-input custom-select" id="gl-kind" data-value="savings" data-options="savings|${t('money.goal_savings')};debt|${t('money.goal_debt')}" style="width:7.5rem"></div>`)}
      ${moneyField(savedLabel(t('money.target_amount')), `<input type="text" id="gl-target" class="settings-input" placeholder="${t('money.target')}" inputmode="decimal" style="width:5rem">`)}
      ${moneyField(savedLabel(t('money.current_amount')), `<input type="text" id="gl-current" class="settings-input" placeholder="${t('money.current')}" inputmode="decimal" style="width:5rem">`)}
      ${moneyField(savedLabel(t('money.monthly_amount')), `<input type="text" id="gl-monthly" class="settings-input" placeholder="${t('money.monthly')}" inputmode="decimal" style="width:5rem">`)}
      <button class="btn" id="gl-add">${t('common.add')}</button>
    </div>`;
}

function reportsCard() {
  if (!comparableTotals()) return currencyBoundary();
  return `<div class="report-form">
      ${moneyField(t('money.start_date'), `<div class="date-input" id="rp-start" data-type="date" data-value="" data-ph="${t('money.start')}" style="flex:1 1 9.5rem;min-width:9.5rem"></div>`)}
      ${moneyField(t('money.end_date'), `<div class="date-input" id="rp-end" data-type="date" data-value="" data-ph="${t('money.end')}" style="flex:1 1 9.5rem;min-width:9.5rem"></div>`)}
      <button class="btn" id="rp-run">${t('money.run')}</button>
      <a class="btn" id="rp-export" href="#" style="display:none">${t('money.export_csv')}</a>
    </div>
    <div id="rp-out" class="report-out"></div>`;
}

function holdingsCard() {
  if (!comparableTotals()) return currencyBoundary();
  const d = _holdings;
  const fmt = (n, currency = _canonicalLedger ? _cur : savedIn()) => fmtMoney(n, currency);
  const signed = n => (n >= 0 ? '+' : '−') + fmt(Math.abs(n));
  const rows = (d?.holdings || []).map(h => `
    <div class="hold-row" data-id="${h.id}">
      <span class="hold-sym">${esc(h.symbol)}</span>
      <span class="hold-qty">${h.qty}×${fmt(h.price)}</span>
      <span class="hold-val">${fmt(h.value)}</span>
      <span class="hold-gain ${h.gain >= 0 ? 'pos' : 'neg'}">${signed(h.gain)} (${h.gain_pct}%)</span>
      <button class="tx-del" data-del-hold="${h.id}" aria-label="${t('money.remove_holding', { symbol: esc(h.symbol) })}" title="${t('common.remove')}">×</button>
    </div>`).join('');
  const tot = d?.totals || {};
  const totRow = (d?.holdings || []).length
    ? `<div class="hold-total">${t('money.holdings_total', { amount: fmt(tot.value || 0) })} · <span class="${(tot.gain || 0) >= 0 ? 'pos' : 'neg'}">${signed(tot.gain || 0)}</span></div>`
    : `<div class="money-empty-sm">${t('money.no_holdings')}</div>`;
  return `<div class="holds">${rows}</div>${totRow}
    <div class="hold-form">
      ${moneyField(t('money.symbol'), `<input type="text" id="hd-sym" class="settings-input" placeholder="${t('money.symbol')}" style="width:5rem">`)}
      ${moneyField(t('money.quantity'), `<input type="text" id="hd-qty" class="settings-input" placeholder="${t('money.qty')}" inputmode="decimal" style="width:4rem">`)}
      ${moneyField(t('money.cost_per_share'), `<input type="text" id="hd-cost" class="settings-input" placeholder="${t('money.cost_sh')}" inputmode="decimal" style="width:4.625rem">`)}
      ${moneyField(t('money.price_per_share'), `<input type="text" id="hd-price" class="settings-input" placeholder="${t('money.price')}" inputmode="decimal" style="width:4rem">`)}
      <button class="btn" id="hd-add">${t('common.add')}</button>
    </div>`;
}

function accountsList() {
  return `<div class="money-accts">` + _accounts.map(a => `
    <div class="money-acct ${a.archived ? 'arch' : ''}" data-id="${a.id}">
      <div class="ma-top"><span class="ma-name">${esc(a.name)}</span>
        <button class="ma-rc" data-rc-acct="${a.id}" aria-label="${t('money.reconcile_named', { name: esc(a.name) })}" title="${t('money.reconcile_title')}">${_si('scale')}</button>
        <button class="ma-del" data-del-acct="${a.id}" aria-label="${t('money.delete_account_named', { name: esc(a.name) })}" title="${t('common.delete')}">×</button></div>
      <div class="ma-bal ${a.balance < 0 ? 'neg' : ''}">${(!_canonicalLedger && a.balance_by_currency?.length ? a.balance_by_currency : [{ currency: accountCurrency(a), balance: a.balance }]).map(row => esc(fmt(row.balance, row.currency))).join('<br>')}</div>
      <div class="ma-kind">${esc(a.kind)} · ${esc(accountCurrency(a))}</div>
      ${_canonicalLedger ? '' : `<button type="button" class="btn" data-currency-acct="${a.id}"${a.currency_edit_reason ? ' disabled' : ''}>${t('money.change_currency')}</button>${a.currency_edit_reason ? `<p class="money-empty-sm">${esc(a.currency_edit_reason)}</p>` : ''}<p id="acct-currency-status-${a.id}" class="money-field-error" role="status"></p>`}
      <div class="rc-panel" id="rc-panel-${a.id}" style="display:none">
        ${moneyField(t('money.statement_balance'), `<input type="text" class="settings-input" id="rc-stmt-${a.id}" placeholder="${t('money.statement_balance')}" inputmode="decimal">`)}
        <button class="btn" data-rc-run="${a.id}">${t('money.check')}</button>
        <div class="rc-out" id="rc-out-${a.id}"></div>
      </div>
    </div>`).join('') + `</div>`;
}

function catChart() {
  if (!comparableTotals()) return currencyBoundary();
  const cats = (_sum?.by_category || []).slice(0, 8);
  if (!cats.length) return `<div class="money-empty-sm">${t('money.no_spending')}</div>`;
  const max = Math.max(...cats.map(c => c[1])) || 1;
  return `<div class="cat-chart">` + cats.map(([name, amt]) => `
    <div class="cat-row">
      <span class="cat-name">${esc(name)}</span>
      <div class="cat-bar-wrap"><div class="cat-bar" style="width:${Math.max(3, amt / max * 100)}%;--cat:var(--cat-${hueOf(name)})"></div></div>
      <span class="cat-amt">${fmt(amt)}</span>
    </div>`).join('') + `</div>`;
}

function trendChart() {
  if (!comparableTotals()) return currencyBoundary();
  const trend = _sum?.trend || [];
  if (!trend.length) return `<div class="money-empty-sm">${t('money.no_data')}</div>`;
  const max = Math.max(1, ...trend.map(m => Math.max(m.income, m.expense)));
  const W = 280, H = 110, bw = W / trend.length, gap = 5;
  let bars = '';
  trend.forEach((m, i) => {
    const x = i * bw;
    const ih = m.income / max * H, eh = m.expense / max * H;
    const half = (bw - gap * 2) / 2;
    bars += `<rect x="${x + gap}" y="${H - ih}" width="${half}" height="${ih}" class="tr-inc"><title>${t('money.trend_income', { month: m.month, amount: fmt(m.income) })}</title></rect>`;
    bars += `<rect x="${x + gap + half}" y="${H - eh}" width="${half}" height="${eh}" class="tr-exp"><title>${t('money.trend_spent', { month: m.month, amount: fmt(m.expense) })}</title></rect>`;
  });
  const labels = trend.map((m, i) => `<span style="width:${100 / trend.length}%">${m.month.slice(5)}</span>`).join('');
  return `<svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bars}</svg>
    <div class="trend-labels">${labels}</div>
    <div class="trend-legend"><span class="lg-inc">${t('money.income')}</span><span class="lg-exp">${t('money.spent')}</span></div>`;
}

function ageOfMoneyStatus() {
  if (!comparableTotals()) return '';
  if (!_aom) return `<span class="aom aom-error">${t('money.aom_failed')} <button type="button" class="btn" id="age-retry">${t('common.retry')}</button></span>`;
  if (_aom.age == null) return `<span class="aom aom-empty">${t('money.aom_empty')}</span>`;
  return `<span class="aom" title="${t('money.aom_title')}">${t('money.aom_value', { n: esc(_aom.age) })}</span>`;
}

function envelopeHeading() {
  return `<h3 tabindex="-1">${t('money.envelope_budgeting')}<span id="money-age-content" role="status">${ageOfMoneyStatus()}</span></h3>`;
}

function envelopeCard() {
  if (!comparableTotals()) return currencyBoundary();
  const e = _envelope;
  if (!e) return _canonicalLedger
    ? `<div class="money-empty-sm" role="status">${t('money.env_actual_failed')} <button type="button" class="btn" id="env-retry">${t('common.retry')}</button></div>`
    : `<div class="money-empty-sm" role="status">${t('money.env_failed')}</div>`;
  const tbb = e.to_be_budgeted || 0;
  // a local envelope is saved in the ledger currency and shown in e.currency
  const cur = _canonicalLedger ? _cur : e.currency || _cur;
  const fmtIn = n => fmt(n, cur);
  const signedIn = n => signed(n, cur);
  const assignedLabel = !_canonicalLedger && cur !== savedIn() ? t('money.assigned_in', { code: savedIn() }) : t('money.assigned');
  const banner = envelopeCurrencyNote() + `<div class="env-tbb ${tbb < 0 ? 'over' : (tbb > 0 ? 'pos' : '')}">
    <span class="env-tbb-num">${signedIn(tbb)}</span><span class="env-tbb-lbl">${t('money.to_be_budgeted')}</span></div>`;
  const pending = _canonicalLedger ? (e.pending_assignments || []) : [];
  const rows = (e.categories || []).filter(c => _canonicalLedger || c.assigned || c.spent || c.available || c.target).map(c => {
    const av = c.available || 0;
    const pendingWrite = pending.find(item => item.category_id === c.category_id);
    const label = _canonicalLedger && c.group ? `${c.group} / ${c.category}` : c.category;
    const tgt = c.target ? (_canonicalLedger
      ? `<div class="env-target-note"><span>${c.target.date ? t('money.target_by_funded', { amount: fmtIn(c.target.amount), date: esc(c.target.date), pct: Math.round((c.target.funded || 0) * 100) }) : t('money.target_funded', { amount: fmtIn(c.target.amount), pct: Math.round((c.target.funded || 0) * 100) })}</span>${c.target.id ? `<button type="button" class="btn env-move-target" data-target-id="${esc(c.target.id)}">${t('money.change_category')}</button>` : ''}</div>`
      : `<div class="env-target"><div class="env-target-bar" style="width:${Math.min(100, (c.target.funded || 0) * 100)}%"></div><span class="env-target-lbl">${c.target.date ? t('money.pct_of_by', { pct: Math.round((c.target.funded || 0) * 100), amount: fmtIn(c.target.amount), date: esc(c.target.date) }) : t('money.pct_of', { pct: Math.round((c.target.funded || 0) * 100), amount: fmtIn(c.target.amount) })}</span></div>`) : '';
    return `<div class="env-row" data-cat="${esc(c.category)}" data-category-id="${esc(c.category_id || '')}">
      <div class="env-cat"><span class="env-cat-name" title="${esc(label)}">${esc(label)}</span><button type="button" class="env-tgt-btn" data-cat="${esc(c.category)}" data-category-id="${esc(c.category_id || '')}" aria-label="${c.target ? t('money.edit_target_for', { name: esc(label) }) : t('money.set_target_for', { name: esc(label) })}">${c.target ? t('money.edit_target') : t('money.set_target')}</button></div>
      ${pendingWrite ? `<span class="env-assigned" title="${t('money.save_not_confirmed')}">${fmtIn(c.assigned || 0)}</span>` : `<label class="env-assignment"><span class="env-input-label">${assignedLabel}</span><input type="text" class="settings-input env-assign" data-cat="${esc(c.category)}" data-category-id="${esc(c.category_id || '')}" data-expected="${c.assigned_saved ?? c.assigned ?? 0}" value="${c.assigned_saved ?? c.assigned ?? 0}" inputmode="decimal" aria-label="${t('money.assigned_this_month_for', { name: esc(label) })}"></label>`}
      <span class="env-spent" title="${t('money.spent_this_month_title')}"><span class="sr-only">${t('money.spent_this_month_sr')}</span><span class="env-stat-label" aria-hidden="true">${t('money.spent_label')}</span>${fmtIn(c.spent || 0)}</span>
      <span class="env-avail ${av < 0 ? 'neg' : 'pos'}" title="${t('money.available_title')}"><span class="sr-only">${t('money.available_sr')}</span><span class="env-stat-label" aria-hidden="true">${t('money.available_label')}</span>${fmtIn(av)}</span>
      ${pendingWrite ? `<div class="env-pending" role="status">${t('money.save_not_confirmed_for', { name: esc(label) })} <button type="button" class="btn" data-env-retry="${esc(c.category_id)}" data-amount="${pendingWrite.assigned}" data-expected="${pendingWrite.expected_assigned}">${t('money.retry_same_amount')}</button></div>` : ''}
      ${tgt}
    </div>`;
  }).join('');
  if (_canonicalLedger) {
    const unbound = (e.unbound_targets || []).map(target => `<div class="env-unbound-row" data-target-id="${esc(target.id)}"><span>${esc(target.category)} · ${fmtIn(target.amount)}${target.date ? ` ${t('money.by_date', { date: esc(target.date) })}` : ''}</span><button type="button" class="btn env-bind-target" data-target-id="${esc(target.id)}">${t('money.choose_category')}</button></div>`).join('');
    return banner + `<p class="money-recurring-note">${t('money.assignments_use_actual')}</p><div id="env-save-status" role="status" class="env-save-status"></div><div id="env-target-status" role="status" class="env-target-status">${esc(_targetStatus)}</div>` +
    (rows ? `<div class="env-rows"><div class="env-row env-head" aria-hidden="true"><span>${t('money.category')}</span><span>${t('money.assigned')}</span><span>${t('money.spent')}</span><span>${t('money.available')}</span></div>${rows}</div>`
      : `<div class="money-empty-sm">${t('money.no_categories')}</div>`) +
      (unbound ? `<section class="env-unbound"><h4>${t('money.targets_need_category')}</h4><p>${t('money.targets_need_category_help')}</p>${unbound}</section>` : '');
  }
  return banner + (rows
    ? `<div class="env-rows">${rows}</div>`
    : `<div class="money-empty-sm">${t('money.assign_to_start')}</div>`) +
    `<div class="env-add">${moneyField(t('money.category'), `<input type="text" id="env-new-cat" class="settings-input" placeholder="${t('money.category')}" style="flex:1">`)}${moneyField(savedLabel(t('money.assignment_amount')), `<input type="text" id="env-new-amt" class="settings-input" placeholder="${t('money.assign')}" inputmode="decimal" style="width:5.625rem">`)}<button class="btn" id="env-assign-btn">${t('money.assign')}</button></div>`;
}

function budgetsList() {
  if (!_budgets.length) return `<div class="money-empty-sm">${t('money.no_caps')}</div>`;
  const byCat = {}; (_sum?.budgets || []).forEach(b => byCat[b.category] = b);
  // the summary shows each cap in the totals currency when a rate allows (saved in the ledger one)
  const cur = _canonicalLedger ? _cur : capsIn();
  return `<div class="budgets">` + _budgets.map(b => {
    const spent = byCat[b.category]?.spent || 0;
    const limit = _canonicalLedger ? b.limit_amt : byCat[b.category]?.limit ?? b.limit_amt;
    const pct = limit > 0 ? Math.min(100, spent / limit * 100) : 0;
    const over = limit > 0 && spent > limit;
    return `<div class="budget-row" data-id="${b.id}">
      <div class="bg-head"><span class="bg-cat">${catDot(b.category)}${esc(b.category)}</span>
        <span class="bg-nums ${over ? 'over' : ''}">${fmt(spent, cur)} / ${fmt(limit, cur)}</span>
        <button class="bg-del" data-del-budget="${b.id}" aria-label="${t('money.remove_cap_for', { name: esc(b.category) })}" title="${t('common.remove')}">×</button></div>
      <div class="bg-bar-wrap"><div class="bg-bar ${over ? 'over' : ''}" style="width:${pct}%;--cat:var(--cat-${hueOf(b.category)})"></div></div>
    </div>`;
  }).join('') + `</div>`;
}

function rulesList() {
  if (!_rules.length) return `<div class="money-empty-sm">${t('money.no_rules')}</div>`;
  return `<div class="rules">` + _rules.map(r => `
    <div class="rule" data-id="${r.id}">
      <span class="rl-match">${esc(r.match)}</span>
      <span class="rl-arrow" aria-hidden="true">${_si('arrow-right')}</span>
      <span class="rl-cat">${esc(r.category) || `<span class="tx-dim">${t('money.clear_paren')}</span>`}</span>
      <button class="tx-del" data-del-rule="${r.id}" aria-label="${t('money.delete_rule_for', { name: esc(r.match) })}" title="${t('common.delete')}">×</button>
    </div>`).join('') + `</div>`;
}

function _ruleForm() {
  return `<div class="rule-form">
    ${moneyField(t('money.payee_contains'), `<input type="text" id="rl-match" class="settings-input" placeholder="${t('money.if_payee_contains')}" style="flex:1.2;min-width:7.5rem">`)}
    <span class="rl-arrow" aria-hidden="true">${_si('arrow-right')}</span>
    ${moneyField(t('money.category'), `<input type="text" id="rl-cat" class="settings-input" placeholder="${t('money.category')}" style="flex:1;min-width:5.625rem">`)}
    <button class="btn" id="rl-add">${t('common.add')}</button>
  </div>`;
}

const _cycleShort = () => ({ weekly: t('subs.per_wk'), monthly: t('subs.per_mo'), quarterly: t('subs.per_qtr'), yearly: t('subs.per_yr'), custom: t('money.cycle_custom_short'), actual: '·Actual' });

function _recurringChoiceLabel(options, value, empty = '') {
  if (!value) return empty;
  const row = options.find(option => option.id === value);
  if (!row) return t('common.unavailable');
  return options.filter(option => option.name === row.name).length > 1
    ? `${row.name} (${row.id.slice(-6)})` : row.name;
}

function _recurringEditForm(r) {
  const edit = _recurringEdit;
  if (!edit || edit.id !== r.id || !r.editable) return '';
  if (edit.loading) return `<div class="recur-edit-state" role="status">${t('money.loading_edit_choices')}</div>`;
  if (!edit.options) return `<div class="recur-edit-state" role="alert">${esc(edit.status)} <button type="button" class="btn" data-retry-open-rec="${esc(r.id)}">${t('common.retry')}</button></div>`;
  const draft = edit.draft;
  const options = edit.options;
  const choice = (field, label, list, empty = '') => `<div class="recur-field"><span id="rce-${field}-label">${label}</span><button type="button" class="btn recur-edit-choice" data-rec-choice="${field}" data-choice-id="${esc(draft[field])}" aria-labelledby="rce-${field}-label rce-${field}-choice" id="rce-${field}-choice">${esc(_recurringChoiceLabel(list, draft[field], empty))}</button></div>`;
  return `<div class="recur-edit" id="rce-panel" role="group" tabindex="-1" aria-busy="${edit.saving}" aria-label="${t('money.edit_schedule_named', { name: esc(r.payee || t('money.recurring')) })}">
    <div class="recur-form recur-form-canonical recur-edit-fields" ${edit.saving ? 'inert' : ''}>
      ${choice('account_id', t('money.account'), options.accounts)}
      ${choice('payee_id', t('money.payee'), options.payees)}
      ${choice('category_id', t('money.category'), options.categories, t('money.no_category'))}
      <div class="recur-field"><span id="rce-sign-label">${t('money.type')}</span><div class="settings-input custom-select" id="rce-sign" aria-labelledby="rce-sign-label" data-value="${draft.sign}" data-options="-|${t('money.expense')};+|${t('money.income')}"></div></div>
      <label class="recur-field" for="rce-amount"><span>${t('money.amount')}</span><input type="text" class="settings-input" id="rce-amount" value="${esc(draft.amountText)}" inputmode="decimal"></label>
      <div class="recur-field"><span id="rce-cycle-label">${t('money.repeat')}</span><div class="settings-input custom-select" id="rce-cycle" aria-labelledby="rce-cycle-label" data-value="${esc(draft.cycle)}" data-options="daily|${t('money.cycle_daily')};weekly|${t('subs.cycle_weekly')};monthly|${t('subs.cycle_monthly')};quarterly|${t('subs.cycle_quarterly')};yearly|${t('subs.cycle_yearly')};custom|${t('money.cycle_every_n')}"></div></div>
      <label class="recur-field" for="rce-days" ${draft.cycle === 'custom' ? '' : 'hidden'}><span>${t('money.days_between')}</span><input type="text" class="settings-input" id="rce-days" value="${esc(draft.cycle_days)}" inputmode="numeric"></label>
      <div class="recur-field"><span id="rce-date-label">${t('money.next_date')}</span><div class="date-input" id="rce-date" aria-labelledby="rce-date-label" data-type="date" data-value="${esc(draft.next_date)}" data-ph="${t('money.next_date')}"></div></div>
      <label class="recur-edit-active" for="rce-active"><span>${t('money.auto_post')}</span><button type="button" id="rce-active" class="s-switch ${draft.active ? 'on' : ''}" role="switch" aria-checked="${draft.active}" aria-label="${t('money.auto_post')}" ${edit.saving ? 'disabled' : ''}></button></label>
      <label class="recur-field recur-edit-notes" for="rce-notes"><span>${t('money.notes')}</span><input type="text" class="settings-input" id="rce-notes" value="${esc(draft.notes)}"></label>
    </div>
    <div class="recur-edit-actions"><button type="button" class="btn primary" id="rce-save" ${edit.saving || edit.blocked ? 'disabled' : ''}>${edit.saving ? t('common.saving') : t('money.save_changes')}</button><button type="button" class="btn" id="rce-cancel" ${edit.saving ? 'disabled' : ''}>${t('common.cancel')}</button>${edit.blocked ? `<button type="button" class="btn" id="rce-check">${t('money.check_schedule')}</button>` : ''}</div>
    ${edit.status ? `<p class="money-recurring-error" role="alert">${esc(edit.status)}</p>` : ''}
  </div>`;
}

function recurringList() {
  if (_recurringError) return `<div class="money-empty-sm money-history-error" role="status">${t('money.schedules_failed')} <button type="button" class="btn" id="recurring-retry">${t('common.retry')}</button></div>`;
  const status = _recurringStatus ? `<p class="money-recurring-error" role="status">${esc(_recurringStatus)}</p>` : '';
  if (!_recurring.length) return status + `<div class="money-empty-sm">${_canonicalLedger ? t('money.no_schedules_actual') : t('money.no_recurring')}</div>`;
  return `${status}<div class="recurs">` + _recurring.map(r => `
    <div class="recur-group" data-id="${esc(r.id)}"><div class="recur ${r.active || r.repair_pending || r.posting_pending || r.create_pending || r.edit_pending || r.delete_pending || (_canonicalLedger && r.editable) ? '' : 'paused'}">
      <span class="rc-payee">${esc(r.payee) || esc(r.category) || '—'}</span>
      <span class="rc-amt ${r.amount == null ? '' : r.amount >= 0 ? 'pos' : 'neg'}">${r.amount == null ? (r.amount_kind === 'range' ? t('money.range') : t('money.varies')) : `${r.amount_kind === 'approx' ? '≈' : ''}${signed(r.amount, accountCurrency(_accounts.find(a => a.id === r.account_id)))}`}<span class="rc-cyc">${_cycleShort()[r.cycle] || ''}</span></span>
      <span class="rc-next" title="${r.create_pending ? t('money.creation_pending') : r.edit_pending ? t('money.edit_pending') : r.delete_pending ? t('money.deletion_pending') : r.next_date ? t('money.next_post', { date: esc(r.next_date) }) : t('money.next_date_unavailable')}">${r.create_pending || r.edit_pending || r.delete_pending ? t('money.pending') : r.active ? (r.next_date ? esc(r.next_date.slice(5)) : t('common.unknown')) : (_canonicalLedger ? t('money.inactive') : t('subs.paused'))}</span>
      ${_canonicalLedger && r.manageable && !r.edit_pending && _recurringEdit?.id !== r.id ? `<button type="button" class="btn rc-toggle" data-toggle-rec="${esc(r.id)}">${r.posting_pending ? (r.posting_target_active ? t('money.retry_resume') : t('money.retry_pause')) : r.active ? t('subs.pause') : t('subs.resume')}</button>` : ''}
      ${_canonicalLedger && r.editable ? `<button type="button" class="btn rc-edit" data-edit-rec="${esc(r.id)}" aria-label="${t('money.edit_schedule_named', { name: esc(r.payee || t('money.recurring')) })}" aria-expanded="${_recurringEdit?.id === r.id}" ${_recurringEdit?.id === r.id && _recurringEdit.options ? 'aria-controls="rce-panel"' : ''} ${_recurringEdit && (_recurringEdit.id !== r.id || _recurringEdit.saving) ? 'disabled' : ''}>${t('common.edit')}</button>` : ''}
      ${_canonicalLedger && r.editable && !_recurringEdit ? `<button type="button" class="btn rc-delete" data-del-rec="${esc(r.id)}" aria-label="${t('money.delete_schedule_named', { name: esc(r.payee || t('money.recurring')) })}">${t('common.delete')}</button>` : ''}
      ${_canonicalLedger ? '' : `<button class="btn rc-toggle" data-toggle-rec="${esc(r.id)}" title="${r.active ? t('subs.pause') : t('subs.resume')}">${r.active ? t('subs.pause') : t('subs.resume')}</button>
      <button class="tx-del" data-del-rec="${esc(r.id)}" aria-label="${t('money.delete_schedule_named', { name: esc(r.payee || r.category || t('money.recurring')) })}" title="${t('common.delete')}">×</button>`}
    </div>${_recurringEditForm(r)}${_canonicalLedger && r.create_pending ? `<div class="recur-repair" role="status"><span>${r.create_needs_review ? t('money.create_marker_missing') : t('money.create_unconfirmed')}</span>${r.create_needs_review ? '' : `<button type="button" class="btn" data-retry-create-rec="${esc(r.id)}">${t('money.retry_creation')}</button>`}</div>` : ''}${_canonicalLedger && r.edit_pending ? `<div class="recur-repair" role="status"><span>${r.edit_needs_review ? t('money.edit_no_match') : t('money.edit_unconfirmed')}</span>${r.edit_needs_review ? '' : `<button type="button" class="btn" data-retry-edit-rec="${esc(r.id)}">${t('money.retry_edit')}</button>`}</div>` : ''}${_canonicalLedger && r.delete_pending ? `<div class="recur-repair" role="status"><span>${r.delete_needs_review ? t('money.delete_no_match') : t('money.delete_unconfirmed')}</span>${r.delete_needs_review ? '' : `<button type="button" class="btn" data-retry-delete-rec="${esc(r.id)}">${t('money.retry_deletion')}</button>`}</div>` : ''}${_canonicalLedger && r.repair_needed ? `<div class="recur-repair"><span>${r.repair_pending ? t('money.repair_incomplete') : t('money.repair_old')}</span><button type="button" class="btn" data-repair-rec="${esc(r.id)}">${r.repair_pending ? t('money.retry_repair') : t('money.repair_posting')}</button></div>` : ''}${_canonicalLedger && r.posting_pending ? `<div class="recur-repair"><span>${r.posting_target_active ? t('money.resume_not_confirmed') : t('money.pause_not_confirmed')}</span></div>` : ''}</div>`).join('') + `</div>`;
}

function recurringCreateUnavailable() {
  if (_recurringError) return t('money.retry_loading_schedules');
  if (_canonicalLedger && _recurring.some(row => row.create_pending)) return t('money.finish_pending_schedule');
  if (!_accounts.length) return t('money.add_account_first');
  if (_canonicalLedger && !_accounts.some(a => !a.archived)) return t('money.open_actual_account');
  return '';
}

function _recurringForm() {
  const reason = recurringCreateUnavailable();
  return `<p id="recurring-create-status" class="money-recurring-note" role="status"${reason ? '' : ' hidden'}>${esc(reason)}</p><div id="recurring-create"${reason ? ' hidden' : ''}>${_recurringFields()}</div>`;
}

function _recurringFields() {
  const availableAccounts = _canonicalLedger ? _accounts.filter(a => !a.archived) : _accounts;
  if (!availableAccounts.length) return _canonicalLedger ? `<p class="money-recurring-note">${t('money.open_actual_account')}</p>` : '';
  const acctOpts = availableAccounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const first = availableAccounts[0]?.id || '';
  if (_canonicalLedger) return `<div class="recur-form recur-form-canonical" role="group" aria-label="${t('money.add_recurring_schedule')}">
    <label class="recur-field" for="rc-payee"><span>${t('money.payee')}</span><input type="text" id="rc-payee" class="settings-input" placeholder="${t('money.eg_rent')}" autocomplete="off"></label>
    <div class="recur-field"><span id="rc-category-label">${t('money.category')}</span><button type="button" class="btn rc-category-choice" id="rc-category-choice" aria-labelledby="rc-category-label rc-category-choice" data-category-id="">${t('money.no_category')}</button></div>
    <div class="recur-field"><span id="rc-sign-label">${t('money.type')}</span><div class="settings-input custom-select" id="rc-sign" aria-labelledby="rc-sign-label" data-value="-" data-options="-|${t('money.expense')};+|${t('money.income')}"></div></div>
    <label class="recur-field" for="rc-amt"><span>${t('money.amount')}</span><input type="text" id="rc-amt" class="settings-input" placeholder="0.00" inputmode="decimal"></label>
    <div class="recur-field"><span id="rc-cycle-label">${t('money.repeat')}</span><div class="settings-input custom-select" id="rc-cycle" aria-labelledby="rc-cycle-label" data-value="monthly" data-options="weekly|${t('subs.cycle_weekly')};monthly|${t('subs.cycle_monthly')};quarterly|${t('subs.cycle_quarterly')};yearly|${t('subs.cycle_yearly')}"></div></div>
    <div class="recur-field"><span id="rc-next-label">${t('money.first_date')}</span><div class="date-input" id="rc-next" aria-labelledby="rc-next-label" data-type="date" data-value="${_today()}" data-ph="${t('money.first_date')}"></div></div>
    <div class="recur-field"><span id="rc-acct-label">${t('money.account')}</span><div class="settings-input custom-select" id="rc-acct" aria-labelledby="rc-acct-label" data-value="${esc(first)}" data-options="${esc(acctOpts)}"></div></div>
    <button type="button" class="btn primary" id="rc-add">${t('money.add_schedule')}</button>
  </div><p class="money-recurring-note">${t('money.new_schedules_note')}</p>`;
  return `<div class="recur-form">
    ${moneyField(t('money.payee'), `<input type="text" id="rc-payee" class="settings-input" placeholder="${t('money.payee_eg_rent')}" style="flex:1.3;min-width:6.25rem">`)}
    ${moneyField(t('money.category'), `<input type="text" id="rc-cat" class="settings-input" placeholder="${t('money.category')}" style="flex:1;min-width:5rem">`)}
    ${moneyField(t('money.type'), `<div class="settings-input custom-select" id="rc-sign" data-value="-" data-options="-|${t('money.expense')};+|${t('money.income')}" style="width:6.5rem"></div>`)}
    ${moneyField(t('money.amount'), `<input type="text" id="rc-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="width:5.25rem">`)}
    ${moneyField(t('money.repeat'), `<div class="settings-input custom-select" id="rc-cycle" data-value="monthly" data-options="weekly|${t('subs.cycle_weekly')};monthly|${t('subs.cycle_monthly')};quarterly|${t('subs.cycle_quarterly')};yearly|${t('subs.cycle_yearly')}" style="width:7.5rem"></div>`)}
    ${moneyField(t('money.next_date'), `<div class="date-input" id="rc-next" data-type="date" data-value="${_today()}" data-ph="${t('money.next_date')}" style="width:8rem"></div>`)}
    ${moneyField(t('money.account'), `<div class="settings-input custom-select" id="rc-acct" data-value="${esc(first)}" data-options="${esc(acctOpts)}" style="width:8rem"></div>`)}
    <button class="btn primary" id="rc-add">${t('common.add')}</button>
  </div>`;
}

function addTxnRow() {
  const acctOpts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const first = _accounts[0]?.id || '';
  return `<div class="txn-add">
    ${moneyField(t('money.date'), `<div class="date-input" id="tx-date" data-type="date" data-value="${_today()}" data-ph="${t('money.date')}" style="flex:1 1 9.5rem"></div>`)}
    ${moneyField(t('money.account'), `<div class="settings-input custom-select" id="tx-acct" data-value="${esc(first)}" data-options="${esc(acctOpts)}" style="flex:1 1 11rem"></div>`)}
    ${moneyField(t('money.type'), `<div class="settings-input custom-select" id="tx-sign" data-value="-" data-options="-|${t('money.expense')};+|${t('money.income')}" style="width:6.625rem"></div>`)}
    ${moneyField(t('money.amount'), `<input type="text" id="tx-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="width:6rem">`)}
    ${moneyField(t('money.payee'), `<input type="text" id="tx-payee" class="settings-input" placeholder="${t('money.payee_what')}" style="flex:1.4;min-width:7.5rem;grid-column:1 / -1">`)}
  </div><p id="tx-amt-error" class="money-field-error" role="status"></p>
  <button type="button" class="money-section-toggle money-entry-details-toggle" id="tx-details-toggle" aria-expanded="${_moneyEntryDetailsOpen}" aria-controls="tx-details">${t('money.category_and_tags')}</button>
  <div class="money-entry-details" id="tx-details"${_moneyEntryDetailsOpen ? '' : ' hidden'}>
    ${moneyField(t('money.category'), `<input type="text" id="tx-cat" class="settings-input" placeholder="${t('money.category')}">`)}
    ${moneyField(t('money.tags_comma_separated'), `<input type="text" id="tx-tags" class="settings-input" placeholder="${t('money.tags_comma')}">`)}
  </div>
  <div class="money-entry-actions">
    <button class="btn primary" id="tx-add">${t('money.add_transaction')}</button>
    ${_accounts.length >= 2 ? `<button class="btn" id="tx-transfer-toggle" title="${t('money.move_between_accounts')}">${_si('swap')} ${t('money.transfer')}</button>` : ''}
  </div>
  <p id="tx-save-status" class="money-field-error" role="status" ${_transactionSaveStatus ? '' : 'hidden'}>${esc(_transactionSaveStatus)}</p>`;
}

function toggleTransactionDetails() {
  const details = $('tx-details'), toggle = $('tx-details-toggle');
  if (!details || !toggle) return;
  _moneyEntryDetailsOpen = !_moneyEntryDetailsOpen;
  details.hidden = !_moneyEntryDetailsOpen;
  toggle.setAttribute('aria-expanded', String(_moneyEntryDetailsOpen));
}

// the two accounts take up to half the row each, so at tablet width they fill the first line
// (long names fit) and date, amount and the button share the second instead of the button
// wrapping alone. wide screens still fit it all on one line
function transferRow() {
  if (_accounts.length < 2) return '';
  const opts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const a0 = _accounts[0]?.id || '', a1 = _accounts[1]?.id || '';
  return `<div class="txn-transfer" id="txn-transfer" style="display:none">
    <span class="tr-lbl">${t('money.move')}</span>
    ${moneyField(t('money.from_account'), `<div class="settings-input custom-select" id="tr-from" data-value="${esc(a0)}" data-options="${esc(opts)}" style="flex:1 1 clamp(11rem, calc(50% - 3rem), 18rem);min-width:11rem"></div>`)}
    <span class="tr-arrow" aria-hidden="true">${_si('arrow-right')}</span>
    ${moneyField(t('money.to_account'), `<div class="settings-input custom-select" id="tr-to" data-value="${esc(a1)}" data-options="${esc(opts)}" style="flex:1 1 clamp(11rem, calc(50% - 3rem), 18rem);min-width:11rem"></div>`)}
    ${moneyField(t('money.date'), `<div class="date-input" id="tr-date" data-type="date" data-value="${_today()}" data-ph="${t('money.date')}" style="flex:1 1 9.5rem;min-width:9.5rem"></div>`)}
    ${moneyField(t('money.amount'), `<input type="text" id="tr-amt" class="settings-input" placeholder="0.00" inputmode="decimal" style="flex:1 1 7rem;min-width:7rem">`)}
    <button class="btn primary" id="tr-do">${t('money.transfer')}</button>
  </div>`;
}

function txnList() {
  const rows = _searchResults !== null ? _searchResults : _txns;
  let banner = _tagFilter
    ? `<div class="txn-tagfilter">${t('money.filtered_by_tag')} <span class="tx-tag">${esc(_tagFilter)}</span><button class="btn" id="tag-clear">${t('money.clear')}</button></div>`
    : '';
  if (_searchStatus) {
    const loading = _searchStatus === 'loading';
    banner += `<div class="money-empty-sm" role="status">${loading ? t('money.loading_matches') : t('money.matches_failed')}${rows.length ? ` ${t('money.previous_remain')}` : ''}
      <button type="button" class="btn" id="txn-search-retry" aria-disabled="${loading}">${t('common.retry')}</button>
      <button type="button" class="btn" id="txn-search-clear">${t('money.clear_filters')}</button></div>`;
    if (!rows.length) return banner;
  }
  if (!rows.length) return banner + `<div class="money-empty-sm">${(_searchResults !== null || _tagFilter) ? t('money.no_matches') : t('money.no_transactions')}</div>`;
  const an = {}; _accounts.forEach(a => an[a.id] = a.name);
  return banner + `<div class="txns">` + rows.map(txn => {
    const main = _renderTxnMain(txn, an);
    return main + (_splitTxn === txn.id ? splitEditorRow(txn) : '');
  }).join('') + `</div>`;
}

function _renderTxnMain(txn, an) {
  if (_editTxn === txn.id && !txn.transfer_id) return editTxnRow(txn);
  // transfer legs aren't inline-editable (editing one would desync the pair) and
  // their × removes the whole transfer, not just this leg
  const xf = !!txn.transfer_id;
  const tags = (txn.tags || '').split(',').filter(Boolean)
    .map(tg => `<button type="button" class="tx-tag" data-tag="${esc(tg)}" aria-label="${t('money.filter_by', { name: esc(tg) })}">${esc(tg)}</button>`).join('');
  const canSplit = (txn.amount || 0) < 0;  // only an expense divides across categories (matches the api)
  const currency = transactionCurrency(txn);
  const label = esc(t('money.txn_label', { payee: txn.payee || t('money.kind_transaction'), date: txn.date || t('money.undated'), amount: signed(txn.amount, currency), account: an[txn.account_id] || t('money.kind_account') }));
  const actions = xf ? '' : `<span class="tx-actions">
    <button type="button" class="tx-edit" data-edit-txn="${txn.id}" aria-label="${t('money.edit_named', { label })}">${t('common.edit')}</button>
    <button class="tx-clear ${txn.cleared ? 'on' : ''}" data-clear-txn="${txn.id}" aria-label="${t('money.cleared_named', { label })}" aria-pressed="${!!txn.cleared}"><span aria-hidden="true">${_si(txn.cleared ? 'check-circle' : 'circle')}</span> ${t('money.cleared')}</button>
    ${canSplit ? `<button class="tx-split-btn ${txn.split ? 'on' : ''}" data-split-txn="${txn.id}" aria-label="${t('money.split_named', { label })}" aria-expanded="${_splitTxn === txn.id}" title="${t('money.split_title')}">${t('money.split')}</button>` : ''}
    ${txn.receipt_id
      ? `<a class="tx-receipt" href="/api/uploads/${esc(txn.receipt_id)}" target="_blank" rel="noopener" aria-label="${t('money.view_receipt_for', { label })}" title="${t('money.view_receipt')}">${t('money.view_receipt')}</a>`
      : `<button class="tx-receipt-btn" data-receipt-txn="${txn.id}" aria-label="${t('money.attach_receipt_to', { label })}" title="${t('money.attach_receipt')}">${t('money.attach_receipt')}</button>`}
  </span>`;
  return `
    <div class="txn ${xf ? 'is-transfer' : ''}" data-id="${txn.id}">
      <span class="tx-date">${esc((txn.date || '').slice(5))}</span>
      <span class="tx-payee">${esc(txn.payee) || '<span class="tx-dim">—</span>'}</span>
      <span class="tx-cat">${xf ? `${_si('swap')} ${t('money.transfer')}` : (txn.category ? `${catDot(txn.category)}${esc(txn.category)}` : '')}</span>
      ${xf ? '' : `<span class="tx-tags">${tags}</span>`}
      <span class="tx-acct">${esc(an[txn.account_id] || '')}</span>
      <span class="tx-amt ${txn.amount >= 0 ? 'pos' : 'neg'}">${signed(txn.amount, currency)}</span>
      ${actions}
      ${xf
        ? `<button class="tx-del" data-del-transfer="${txn.transfer_id}" aria-label="${t('money.delete_transfer_named', { label })}" title="${t('money.delete_transfer_title')}">${t('money.delete_transfer')}</button>`
        : `<button class="tx-del" data-del-txn="${txn.id}" aria-label="${t('money.delete_named', { label })}" title="${t('common.delete')}">${t('common.delete')}</button>`}
    </div>`;
}

function splitEditorRow(txn) {
  const rows = (_splitRows.length ? _splitRows : [{ category: '', amount: '' }]).map((s, i) => `
    <div class="split-row" data-i="${i}">
      ${moneyField(t('money.category'), `<input type="text" class="settings-input split-cat" value="${esc(s.category || '')}" placeholder="${t('money.category')}" style="flex:1">`)}
      ${moneyField(t('money.amount'), `<input type="text" class="settings-input split-amt" value="${esc(String(s.amount || ''))}" placeholder="${t('money.amount')}" inputmode="decimal" style="width:5.625rem">`)}
      <button class="btn split-row-del" data-i="${i}" aria-label="${t('money.remove_split_row', { n: i + 1 })}" title="${t('common.remove')}">×</button>
    </div>`).join('');
  return `<div class="txn-split-editor" data-id="${txn.id}">
    <div class="split-head">${t('money.split_head', { amount: fmt(Math.abs(txn.amount || 0), transactionCurrency(txn)) })}</div>
    ${rows}
    <div class="split-actions">
      <button class="btn" id="split-add-row">${t('money.add_row')}</button>
      <button class="btn primary" id="split-save" data-id="${txn.id}">${t('common.save')}</button>
      <button class="btn" id="split-cancel">${t('common.cancel')}</button>
    </div>
  </div>`;
}

function editTxnRow(txn) {
  const acctOpts = _accounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const neg = (txn.amount || 0) < 0;
  return `<div class="txn txn-edit" data-id="${txn.id}" data-original-account="${esc(txn.account_id)}" data-original-amount="${esc(String(txn.amount))}" role="group" aria-label="${t('money.edit_named', { label: esc(txn.payee || t('money.kind_transaction')) })}">
    <h3>${t('money.edit_named', { label: esc(txn.payee || t('money.kind_transaction')) })}<span data-edit-context hidden>${t('money.outside_list')}</span></h3>
    ${moneyField(t('money.date'), `<div class="date-input" data-f="date" data-type="date" data-value="${esc(txn.date || _today())}" data-ph="${t('money.date')}" style="flex:1 1 9.5rem;min-width:9.5rem"></div>`)}
    ${moneyField(t('money.account'), `<div class="settings-input custom-select" data-f="account_id" data-value="${esc(txn.account_id)}" data-options="${esc(acctOpts)}" style="flex:1 1 11rem;min-width:11rem"></div>`)}
    ${moneyField(t('money.payee'), `<input type="text" class="settings-input" data-f="payee" value="${esc(txn.payee || '')}" placeholder="${t('money.payee')}" style="flex:1.4 1 9.5rem;min-width:9.5rem">`)}
    ${moneyField(t('money.category'), `<input type="text" class="settings-input" data-f="category" value="${esc(txn.category || '')}" placeholder="${t('money.category')}" style="flex:1;min-width:5rem">`)}
    ${moneyField(t('money.type'), `<div class="settings-input custom-select" data-f="sign" data-value="${neg ? '-' : '+'}" data-options="-|${t('money.expense')};+|${t('money.income')}" style="width:6.25rem"></div>`)}
    ${moneyField(t('money.amount'), `<input type="text" class="settings-input" data-f="amount" value="${Math.abs(txn.amount || 0)}" inputmode="decimal" style="width:5.25rem">`)}
    <button class="btn primary" data-save-txn="${txn.id}">${t('money.save_changes')}</button>
    <button class="btn" data-cancel-txn="${txn.id}" aria-label="${t('money.cancel_editing', { name: esc(txn.payee || t('money.kind_transaction')) })}">${t('common.cancel')}</button>
  </div>`;
}

// ── inline forms ──────────────────────────────────────────────────────────────
function _accountForm() {
  return `<div class="acct-form" id="acct-form">
    ${moneyField(t('money.account_name'), `<input type="text" id="af-name" class="settings-input" placeholder="${t('money.account_name_eg')}" style="flex:1;min-width:13rem">`)}
    ${moneyField(t('money.account_type'), `<div class="settings-input custom-select" id="af-kind" data-value="checking" data-options="checking|${t('money.kind_checking')};savings|${t('money.kind_savings')};cash|${t('money.kind_cash')};credit|${t('money.kind_credit')};investment|${t('money.kind_investment')}" style="width:9.375rem"></div>`)}
    ${moneyField(t('money.currency'), `<div class="settings-input custom-select" id="af-currency" data-value="" data-options="|${t('money.choose_currency')};${_currencyCodes.map(code => `${code}|${code}`).join(';')}" aria-describedby="af-currency-error" style="width:10.5rem"></div>`)}
    ${moneyField(t('money.opening_balance'), `<input type="text" id="af-open" class="settings-input" placeholder="${t('money.opening_balance')}" inputmode="decimal" style="width:8.75rem">`)}
    ${moneyField(t('money.low_balance_alert'), `<input type="text" id="af-low" class="settings-input" placeholder="${t('money.low_bal_alert')}" inputmode="decimal" style="width:9rem" title="${t('money.low_balance_title')}">`)}
    <button class="btn primary" id="af-add">${t('money.add_account_btn')}</button>
  </div><p id="af-currency-error" class="money-field-error" role="status">${_currencyCodes.length ? '' : t('money.currency_choices_unloaded')}</p>${_currencyCodes.length ? '' : `<button type="button" class="btn" id="af-currency-retry">${t('money.retry_currency_choices')}</button>`}`;
}
function _budgetForm() {
  return `<div class="budget-form">
    ${moneyField(t('money.category'), `<input type="text" id="bf-cat" class="settings-input" placeholder="${_canonicalLedger ? t('money.actual_category') : t('money.category')}" style="flex:1;min-width:6.875rem">`)}
    ${moneyField(_canonicalLedger ? t('money.monthly_cap') : savedLabel(t('money.monthly_cap')), `<input type="text" id="bf-amt" class="settings-input" placeholder="${t('money.monthly_cap')}" inputmode="decimal" style="width:7.5rem">`)}
    <button class="btn" id="bf-add">${t('money.set')}</button>
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
  $('af-currency-retry')?.addEventListener('click', retryCurrencyChoices);
  $('af-currency')?.addEventListener('change', () => {
    if (!_currencyCodes.includes(getDropdownValue($('af-currency')))) return;
    $('af-currency-error').textContent = '';
    $('af-currency').removeAttribute('aria-invalid');
  });
}

async function retryCurrencyChoices() {
  const control = $('af-currency'), button = $('af-currency-retry');
  if (!control || !button) return;
  const currencyRead = ++_currencyReadSequence;
  const focusVersion = _moneyFocusChange;
  const ownedFocus = document.activeElement === button;
  button.disabled = true;
  try {
    const result = await api('/api/money/currencies');
    if (currencyRead !== _currencyReadSequence || control !== $('af-currency')) return;
    _currencyCodes = result.codes || [];
    if (!_currencyCodes.length) throw new Error('currency choices unavailable');
    populateDropdown(control, [{ value: '', label: t('money.choose_currency') }, ..._currencyCodes.map(value => ({ value, label: value }))], '');
    control.removeAttribute('aria-invalid');
    $('af-currency-error').textContent = '';
    const currentButton = $('af-currency-retry');
    const focused = document.activeElement;
    const ownsFocus = ownedFocus && (focused === button || focused === currentButton
      || (focused === document.body && focusVersion === _moneyFocusChange));
    currentButton?.remove();
    if (ownsFocus) control.focus();
  } catch {
    if (currencyRead === _currencyReadSequence && control === $('af-currency')) $('af-currency-error').textContent = t('money.currency_choices_retry');
  } finally { button.disabled = false; }
}
function wire() {
  _initControls();
  wireCurrency($('money-body'), _sum || {}, () => load(fetch, true));
  $('money-body').querySelectorAll('[data-money-section]').forEach(button => button.addEventListener('click', () => toggleMoneySection(button)));
  $('money-body').querySelectorAll('[data-money-task]').forEach(button => button.addEventListener('click', () => selectMoneyTask(button)));
  $('money-entry-action')?.addEventListener('click', () => {
    _moneyEntryOpen = $('money-entry-fields').hidden;
    if (!_moneyEntryOpen) $('money-entry-action').focus({ preventScroll: true });
    syncMoneyLayout();
    if (_moneyEntryOpen) {
      $('tx-payee')?.focus();
      $('tx-payee')?.scrollIntoView({ block: 'center' });
    }
  });
  $('money-summary-toggle')?.addEventListener('click', () => {
    _moneyTotalsOpen = !_moneyTotalsOpen;
    syncMoneyLayout();
  });
  syncMoneyLayout();
  $('tx-details-toggle')?.addEventListener('click', toggleTransactionDetails);
  $('tx-add')?.addEventListener('click', addTxn);
  $('tx-amt')?.addEventListener('input', () => transactionAmountError(''));
  $('tx-amt')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addTxn(); } });
  $('money-add-acct')?.addEventListener('click', () => {
    const wrap = $('money-acct-form-wrap');
    if (wrap.innerHTML) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = _accountForm();
    _wireAccountForm();
    $('af-name')?.focus();
  });
  $('bf-add')?.addEventListener('click', addBudget);
  if ($('bf-add')) $('bf-add').disabled = _budgetSaving;
  _wireEnvelope();
  $('hd-add')?.addEventListener('click', addHolding);
  $('money-body').querySelectorAll('[data-del-hold]').forEach(b => b.addEventListener('click', () => delHolding(b.dataset.delHold)));
  $('gl-add')?.addEventListener('click', addGoal);
  if ($('gl-add')) $('gl-add').disabled = _goalSaving;
  $('money-body').querySelectorAll('[data-del-goal]').forEach(b => b.addEventListener('click', () => delGoal(b.dataset.delGoal)));
  $('rp-run')?.addEventListener('click', runReport);
  wireForecast();
  wireAlerts();
  wireNetworthHistory();
  _decorateCards();
  $('tx-transfer-toggle')?.addEventListener('click', () => {
    const f = $('txn-transfer'); if (!f) return;
    f.style.display = f.style.display === 'none' ? 'flex' : 'none';
    if (f.style.display !== 'none') $('tr-amt')?.focus();
  });
  $('tr-do')?.addEventListener('click', doTransfer);
  $('tr-amt')?.addEventListener('keydown', e => { if (e.key === 'Enter') doTransfer(); });
  $('txn-range-toggle')?.addEventListener('click', toggleAmountRange);
  syncAmountRange();
  ['txn-search', 'txn-min', 'txn-max'].forEach(id => $(id)?.addEventListener('input', () => {
    syncAmountRange();
    _searchSequence += 1;
    clearTimeout(_searchTimer); _searchTimer = setTimeout(applySearch, 220);
  }));
  _wireTxnRows();
  $('money-body').querySelectorAll('[data-del-acct]').forEach(b => b.addEventListener('click', () => delAccount(b.dataset.delAcct)));
  $('money-body').querySelectorAll('[data-currency-acct]').forEach(b => b.addEventListener('click', () => editAccountCurrency(b.dataset.currencyAcct)));
  $('money-body').querySelectorAll('[data-set-currency]').forEach(b => b.addEventListener('click', () => {
    const plans = $('money-body').querySelector('[data-money-section="plans"]');
    if (plans && plans.getAttribute('aria-expanded') !== 'true') toggleMoneySection(plans);
    const task = $('money-body').querySelector('[data-money-task="accounts"]');
    if (task) selectMoneyTask(task);
    const target = $('money-body').querySelector(`[data-currency-acct="${CSS.escape(b.dataset.setCurrency)}"]`);
    target?.scrollIntoView({ block: 'center' });
    target?.focus();
  }));
  $('money-body').querySelectorAll('[data-rc-acct]').forEach(b => b.addEventListener('click', () => toggleReconcile(b.dataset.rcAcct)));
  $('money-body').querySelectorAll('[data-rc-run]').forEach(b => b.addEventListener('click', () => runReconcile(b.dataset.rcRun)));
  $('money-body').querySelectorAll('[data-del-budget]').forEach(b => b.addEventListener('click', () => delBudget(b.dataset.delBudget)));
  wireRecurring();
  $('rl-add')?.addEventListener('click', addRule);
  $('rl-cat')?.addEventListener('keydown', e => { if (e.key === 'Enter') addRule(); });
  $('rules-apply')?.addEventListener('click', applyRules);
  $('money-body').querySelectorAll('[data-del-rule]').forEach(b => b.addEventListener('click', () => delRule(b.dataset.delRule)));
}

async function retryRecurring(focusId = '', focusOwner = captureMoneyFocus('schedules')) {
  const button = $('recurring-retry');
  if (button) {
    button.disabled = true;
    button.textContent = t('money.retrying');
  }
  await readRecurring(api);
  const content = $('recurring-content');
  if (!content) return;
  const list = $('recurring-list');
  const restoreFocus = ownsMoneyFocus(focusOwner);
  if (restoreFocus) _moneyPlanTask = 'schedules';
  else if (list?.contains(document.activeElement) || (recurringCreateUnavailable() && content.contains(document.activeElement))) focusMoneyTask(_moneyPlanTask);
  _snapshotRecurringEdit();
  if (list) list.innerHTML = recurringList();
  wireRecurringList();
  const action = focusId ? [...content.querySelectorAll('[data-toggle-rec], [data-del-rec], [data-retry-create-rec], [data-retry-edit-rec], [data-retry-delete-rec]')].find(b => b.dataset.toggleRec === focusId || b.dataset.delRec === focusId || b.dataset.retryCreateRec === focusId || b.dataset.retryEditRec === focusId || b.dataset.retryDeleteRec === focusId) : null;
  if (restoreFocus) focusMoneyTask('schedules', action || $('recurring-retry') || document.querySelector('.money-card[data-card="recurring"] h3'));
  refreshMoneyTasks();
}

function wireRecurring() {
  wireRecurringList();
  document.querySelectorAll('#recurring-content .custom-select').forEach(initCustomDropdown);
  document.querySelectorAll('#recurring-content .date-input').forEach(initDatePicker);
  $('rc-add')?.addEventListener('click', addRecurring);
  $('rc-category-choice')?.addEventListener('click', chooseRecurringCategory);
}

function wireRecurringList() {
  const reason = recurringCreateUnavailable();
  const create = $('recurring-create');
  if (create) create.hidden = !!reason;
  const status = $('recurring-create-status');
  if (status) { status.textContent = reason; status.hidden = !reason; }
  refreshMoneyTasks();
  $('recurring-retry')?.addEventListener('click', () => retryRecurring());
  document.querySelectorAll('#recurring-list [data-edit-rec]').forEach(b => b.addEventListener('click', () => openRecurringEdit(b.dataset.editRec)));
  document.querySelectorAll('#recurring-list [data-retry-open-rec]').forEach(b => b.addEventListener('click', () => openRecurringEdit(b.dataset.retryOpenRec, true)));
  document.querySelectorAll('#recurring-content [data-retry-create-rec]').forEach(b => b.addEventListener('click', () => retryRecurringCreate(b)));
  document.querySelectorAll('#recurring-content [data-retry-edit-rec]').forEach(b => b.addEventListener('click', () => retryRecurringEdit(b)));
  document.querySelectorAll('#recurring-content [data-retry-delete-rec]').forEach(b => b.addEventListener('click', () => retryRecurringDelete(b)));
  document.querySelectorAll('#recurring-content [data-del-rec]').forEach(b => b.addEventListener('click', () => delRecurring(b.dataset.delRec)));
  document.querySelectorAll('#recurring-content [data-toggle-rec]').forEach(b => b.addEventListener('click', () => toggleRecurring(b)));
  document.querySelectorAll('#recurring-content [data-repair-rec]').forEach(b => b.addEventListener('click', () => repairRecurring(b)));
  const editor = document.querySelector?.('#recurring-list .recur-edit');
  if (!editor) return;
  editor.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  editor.querySelectorAll('.date-input').forEach(initDatePicker);
  $('rce-cycle')?.addEventListener('change', () => {
    _snapshotRecurringEdit();
    const days = $('rce-days')?.closest('.recur-field');
    if (days) days.hidden = getDropdownValue($('rce-cycle')) !== 'custom';
    if (days && !days.hidden) $('rce-days')?.focus();
  });
  $('rce-active')?.addEventListener('click', event => {
    if (_recurringEdit?.saving) return;
    const button = event.currentTarget;
    const active = button.getAttribute('aria-checked') !== 'true';
    button.setAttribute('aria-checked', String(active));
    button.classList.toggle('on', active);
    _snapshotRecurringEdit();
  });
  editor.querySelectorAll('[data-rec-choice]').forEach(b => b.addEventListener('click', () => chooseRecurringEditValue(b)));
  $('rce-save')?.addEventListener('click', saveRecurringEdit);
  $('rce-cancel')?.addEventListener('click', cancelRecurringEdit);
  $('rce-check')?.addEventListener('click', checkRecurringEdit);
  editor.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.target.closest('.custom-select, .date-input')) return;
    event.preventDefault();
    cancelRecurringEdit();
  });
}

function _snapshotRecurringEdit() {
  const draft = _recurringEdit?.draft;
  if (!draft || !$('rce-amount')) return;
  for (const field of ['account_id', 'payee_id', 'category_id']) {
    draft[field] = $(`rce-${field}-choice`)?.dataset.choiceId ?? draft[field];
  }
  draft.amountText = $('rce-amount').value;
  draft.sign = getDropdownValue($('rce-sign'));
  draft.cycle = getDropdownValue($('rce-cycle'));
  draft.cycle_days = $('rce-days')?.value ?? draft.cycle_days;
  draft.next_date = $('rce-date')?.dataset.value || '';
  draft.active = $('rce-active')?.getAttribute('aria-checked') === 'true';
  draft.notes = $('rce-notes')?.value ?? draft.notes;
}

function _drawRecurringEdit(focus = '') {
  _snapshotRecurringEdit();
  const list = $('recurring-list');
  if (!list) return;
  list.innerHTML = recurringList();
  wireRecurringList();
  const target = focus ? list.querySelector(focus) : null;
  (target || (_recurringEdit && list.querySelector(`[data-edit-rec="${CSS.escape(_recurringEdit.id)}"]`)) || document.querySelector('.money-card[data-card="recurring"] h3'))?.focus();
}

async function openRecurringEdit(id, retry = false) {
  const row = _recurring.find(item => item.id === id);
  if (!_canonicalLedger || !row?.editable) return;
  if (_recurringEdit?.id === id && !retry) { cancelRecurringEdit(); return; }
  _recurringEdit = { id, loading: true, options: null, draft: null, status: '', saving: false, blocked: false };
  const edit = _recurringEdit;
  _drawRecurringEdit();
  try {
    const options = await api(`/api/money/recurring/${encodeURIComponent(id)}/edit-options`);
    if (_recurringEdit !== edit) return;
    if (!options?.current || !Array.isArray(options.accounts) || !Array.isArray(options.payees) || !Array.isArray(options.categories)) throw new Error('invalid edit choices');
    const current = options.current;
    _recurringEdit.options = options;
    _recurringEdit.draft = { ...current, sign: current.amount < 0 ? '-' : '+', amountText: String(Math.abs(current.amount)) };
    _recurringEdit.loading = false;
    _drawRecurringEdit('#rce-account_id-choice');
  } catch (error) {
    if (_recurringEdit !== edit) return;
    _recurringEdit.loading = false;
    _recurringEdit.status = t('money.edit_choices_failed', { error: error.message || t('money.try_again') });
    _drawRecurringEdit('[data-retry-open-rec]');
  }
}

function cancelRecurringEdit() {
  if (!_recurringEdit || _recurringEdit.saving) return;
  const id = _recurringEdit.id;
  _recurringEdit = null;
  _drawRecurringEdit(`[data-edit-rec="${CSS.escape(id)}"]`);
}

async function chooseRecurringEditValue(button) {
  const edit = _recurringEdit;
  if (!edit?.options || edit.saving) return;
  _snapshotRecurringEdit();
  const field = button.dataset.recChoice;
  const list = { account_id: edit.options.accounts, payee_id: edit.options.payees, category_id: edit.options.categories }[field];
  if (!list) return;
  const options = [
    ...(field === 'category_id' ? [{ value: '', label: t('money.no_category') }] : []),
    ...list.map(row => ({ value: row.id, label: _recurringChoiceLabel(list, row.id) })),
  ];
  const picked = await dlgChoose(field === 'category_id' ? t('money.choose_category_title') : field === 'payee_id' ? t('money.choose_payee') : t('money.choose_account'), options);
  if (picked === null || _recurringEdit !== edit) return;
  edit.draft[field] = picked;
  button.dataset.choiceId = picked;
  button.textContent = options.find(option => option.value === picked)?.label || t('money.no_category');
  button.focus();
}

async function checkRecurringEdit() {
  const edit = _recurringEdit;
  if (!edit) return;
  try {
    const rows = await api('/api/money/recurring');
    if (!Array.isArray(rows)) throw new Error('invalid schedule list');
    if (_recurringEdit !== edit) return;
    _recurring = rows;
    _recurringError = false;
    const row = rows.find(item => item.id === edit.id);
    if (row?.edit_pending || !row?.editable) {
      _recurringEdit = null;
      _drawRecurringEdit(row?.edit_pending && !row.edit_needs_review ? `[data-retry-edit-rec="${CSS.escape(edit.id)}"]` : '');
    } else {
      edit.blocked = false;
      edit.status = t('money.no_pending_edit');
      _drawRecurringEdit('#rce-save');
    }
  } catch {
    if (_recurringEdit !== edit) return;
    edit.blocked = true;
    edit.status = t('money.check_failed');
    _drawRecurringEdit('#rce-check');
  }
}

async function saveRecurringEdit() {
  const edit = _recurringEdit;
  if (!edit?.draft || edit.saving || edit.blocked) return;
  _snapshotRecurringEdit();
  const draft = edit.draft;
  const raw = draft.amountText.trim();
  const amount = _decimal(raw);
  if (!/^(?:\d+(?:\.\d{0,2})?|\.\d{1,2})$/.test(raw) || !_validAmounts(amount)) {
    toast(t('money.amount_two_decimals'), 'error'); return;
  }
  if (!calendarDateParts(draft.next_date)) { toast(t('money.valid_next_date'), 'error'); return; }
  const customDays = String(draft.cycle_days).trim();
  const days = draft.cycle === 'custom'
    ? (/^\d+$/.test(customDays) ? Number(customDays) : NaN)
    : ({ daily: 1, weekly: 7, monthly: 30, quarterly: 91, yearly: 365 })[draft.cycle];
  if (!Number.isSafeInteger(days) || days < 1) { toast(t('money.valid_days'), 'error'); return; }
  const payload = {
    account_id: draft.account_id, payee_id: draft.payee_id,
    amount: (draft.sign === '+' ? 1 : -1) * amount,
    category_id: draft.category_id, notes: draft.notes,
    cycle: draft.cycle, cycle_days: days, next_date: draft.next_date, active: draft.active,
  };
  edit.saving = true;
  edit.status = '';
  _drawRecurringEdit('#rce-panel');
  const focusOwner = captureMoneyFocus('schedules');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(edit.id)}/edit`, { method: 'POST', body: payload });
    if (_recurringEdit !== edit) return;
    _recurringEdit = null;
    _recurringStatus = '';
    await retryRecurring(edit.id, focusOwner);
  } catch (error) {
    if (_recurringEdit !== edit) return;
    edit.saving = false;
    edit.status = t('money.edit_not_confirmed', { error: error.message || t('money.check_the_schedule') });
    await checkRecurringEdit();
  }
}

// wire the txn row buttons within a root (the whole #txn-rows list); called on full
// render and again after a search replaces just the list
function _wireTxnRows() {
  for (const item of _moneySaved) setTransactionUndoAvailability(item.id);
  const root = $('txn-rows'); if (!root) return;
  root.querySelectorAll('.txn-edit .custom-select').forEach(initCustomDropdown);
  root.querySelectorAll('.txn-edit .date-input').forEach(initDatePicker);
  root.querySelectorAll('[data-del-transfer]').forEach(b => b.addEventListener('click', () => delTransfer(b.dataset.delTransfer)));
  root.querySelectorAll('[data-del-txn]').forEach(b => b.addEventListener('click', () => delTxn(b.dataset.delTxn)));
  root.querySelectorAll('[data-edit-txn]').forEach(el => el.addEventListener('click', () => {
    _editTxn = el.dataset.editTxn; render(true);
    $('txn-rows').querySelector(`.txn-edit[data-id="${CSS.escape(_editTxn)}"] [data-f="payee"]`)?.focus();
  }));
  root.querySelectorAll('[data-save-txn]').forEach(b => b.addEventListener('click', () => saveTxn(b.dataset.saveTxn)));
  root.querySelectorAll('[data-cancel-txn]').forEach(b => b.addEventListener('click', () => {
    const id = b.dataset.cancelTxn; _editTxn = null; render(true);
    ($('txn-rows').querySelector(`[data-edit-txn="${CSS.escape(id)}"]`) || $('txn-search'))?.focus();
  }));
  // escape is cancel. an open menu or date picker keeps its escape to itself (it stops it)
  root.querySelectorAll('.txn-edit').forEach(row => row.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    event.preventDefault();
    row.querySelector('[data-cancel-txn]')?.click();
  }));
  // 4a actions
  root.querySelectorAll('[data-clear-txn]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); toggleCleared(b.dataset.clearTxn); }));
  root.querySelectorAll('[data-split-txn]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); toggleSplit(b.dataset.splitTxn); }));
  root.querySelectorAll('[data-receipt-txn]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); attachReceipt(b.dataset.receiptTxn); }));
  root.querySelectorAll('.tx-tag[data-tag]').forEach(c => c.addEventListener('click', e => { e.stopPropagation(); filterByTag(c.dataset.tag); }));
  $('tag-clear')?.addEventListener('click', clearTagFilter);
  $('txn-search-retry')?.addEventListener('click', () => {
    if (_searchStatus === 'loading') return;
    return _tagFilter ? filterByTag(_tagFilter) : applySearch();
  });
  $('txn-search-clear')?.addEventListener('click', () => {
    for (const id of ['txn-search', 'txn-min', 'txn-max']) if ($(id)) $(id).value = '';
    syncAmountRange();
    clearTagFilter();
  });
  $('split-add-row')?.addEventListener('click', () => {
    _splitRows = _readSplitRows();
    _splitRows.push({ category: '', amount: '' });
    renderTxns(true);
    $('txn-rows')?.querySelectorAll('.split-cat')[_splitRows.length - 1]?.focus();
  });
  $('split-save')?.addEventListener('click', b => saveSplits($('split-save').dataset.id));
  $('split-cancel')?.addEventListener('click', () => { _splitTxn = null; _splitRows = []; renderTxns(); });
  root.querySelectorAll('.split-row-del').forEach(b => b.addEventListener('click', () => {
    const index = Number(b.dataset.i);
    _splitRows = _readSplitRows();
    _splitRows.splice(index, 1);
    if (!_splitRows.length) _splitRows = [{ category: '', amount: '' }];
    renderTxns(true);
    $('txn-rows')?.querySelectorAll('.split-row-del')[Math.min(index, _splitRows.length - 1)]?.focus();
  }));
}

function syncAmountRange() {
  const panel = $('txn-amount-range'), button = $('txn-range-toggle');
  if (!panel || !button) return;
  const hasAmount = Boolean($('txn-min')?.value.trim() || $('txn-max')?.value.trim());
  panel.hidden = !_amountRangeOpen;
  button.setAttribute('aria-expanded', String(_amountRangeOpen));
  button.textContent = hasAmount ? t('money.clear_range') : _amountRangeOpen ? t('money.hide_range') : t('money.amount_range');
}

function toggleAmountRange() {
  if (_amountRangeOpen) {
    $('txn-range-toggle').focus();
    $('txn-min').value = '';
    $('txn-max').value = '';
    clearTimeout(_searchTimer);
    _amountRangeOpen = false;
    syncAmountRange();
    void applySearch();
  } else {
    _amountRangeOpen = true;
    syncAmountRange();
    $('txn-min').focus();
  }
}

// the range filters run while you type, and typing keeps a lone decimal comma (12,5) until
// the field is left. read it the way it will settle instead of toasting mid-typing. anything
// else (1,234.56) is still _decimal's to refuse
function _rangeAmount(id) {
  const text = $(id)?.value.trim() || '';
  return /^[^.,]*,[^.,]*$/.test(text) ? formatDecimal(text) : text;
}

export async function applySearch() {
  const sequence = ++_searchSequence;
  const q = $('txn-search')?.value.trim() || '';
  const mn = _rangeAmount('txn-min');
  const mx = _rangeAmount('txn-max');
  if (!q && !mn && !mx) {   // nothing to filter → back to the plain month list
    _searchResults = null;
    _searchStatus = '';
    _tagFilter = '';
    renderTxns();
    return;
  }
  _tagFilter = '';
  const p = new URLSearchParams({ month: _month });
  if (q) p.set('q', q);
  if (!_validAmounts(_decimal(mn, 0), _decimal(mx, 0))) {
    if (_searchStatus) {
      _searchStatus = '';
      renderTxns();
    }
    return;
  }
  if (mn) p.set('min_amt', _decimal(mn));
  if (mx) p.set('max_amt', _decimal(mx));
  await readTransactionFilter(`/api/money/transactions/search?${p}`, sequence);
}

async function readTransactionFilter(path, sequence) {
  _searchStatus = 'loading';
  renderTxns();
  try {
    const results = await api(path);
    if (!Array.isArray(results)) throw new Error('invalid transaction list');
    if (sequence !== _searchSequence) return;
    _searchResults = results;
    _searchStatus = '';
  } catch {
    if (sequence !== _searchSequence) return;
    _searchStatus = 'error';
  }
  renderTxns();
}

// ── actions ────────────────────────────────────────────────────────────────
async function addAccount() {
  const name = $('af-name')?.value.trim();
  if (!name) { toast(t('money.name_account'), 'error'); return; }
  const opening = _decimal($('af-open')?.value, 0);
  const low_balance = _decimal($('af-low')?.value, 0);
  if (!_validAmounts(opening, low_balance)) return;
  const currency = getDropdownValue($('af-currency'));
  if (!_currencyCodes.includes(currency)) {
    const error = $('af-currency-error');
    if (error) error.textContent = _currencyCodes.length ? t('money.choose_account_currency') : t('money.currency_choices_retry');
    $('af-currency')?.setAttribute?.('aria-invalid', 'true');
    $('af-currency')?.focus?.();
    return;
  }
  let requestId = '';
  try {
    const accountPayload = { name, kind: getDropdownValue($('af-kind')), currency, opening, low_balance };
    requestId = await _createRequestId('account', accountPayload);
    accountPayload.request_id = requestId;
    await api('/api/money/accounts', { method: 'POST', body: accountPayload });
    _completeCreateRequest('account', requestId);
    await load();
  } catch {
    if (requestId) _releaseCreateRequest('account', requestId);
    toast(t('money.add_account_failed'), 'error');
  }
}
async function delAccount(id) {
  if (!await dlgConfirm(t('money.delete_account_confirm'))) return;
  try { await api(`/api/money/accounts/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast(t('money.delete_failed'), 'error'); }
}
function transactionAmountError(message) {
  const field = $('tx-amt'), error = $('tx-amt-error');
  if (error) error.textContent = message;
  if (message) {
    field?.setAttribute?.('aria-invalid', 'true');
    field?.setAttribute?.('aria-describedby', 'tx-amt-error');
    field?.focus?.();
    error?.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
  } else {
    field?.removeAttribute?.('aria-invalid');
    field?.removeAttribute?.('aria-describedby');
  }
}

function transactionSaveStatus(message) {
  _transactionSaveStatus = message;
  const status = $('tx-save-status');
  if (!status) return;
  status.textContent = message;
  status.hidden = !message;
}

function updateTransactionSaveStatus() {
  if (_transactionUncertainSnapshot === null) return transactionSaveStatus(_transactionSaveStatus);
  transactionSaveStatus(transactionEntrySnapshot() === _transactionUncertainSnapshot
    ? t('money.save_not_confirmed_kept')
    : t('money.earlier_not_confirmed'));
}

async function addTxn() {
  const amtRaw = _decimal($('tx-amt')?.value);
  if (!Number.isFinite(amtRaw)) {
    transactionAmountError(t('money.use_decimal_point'));
    return;
  }
  if (!amtRaw || amtRaw <= 0) {
    transactionAmountError(t('money.amount_gt_zero'));
    return;
  }
  transactionAmountError('');
  const sign = getDropdownValue($('tx-sign')) === '+' ? 1 : -1;
  const focusAtSubmit = document.activeElement;
  const ownedEntryFocus = $('money-entry-fields')?.contains?.(focusAtSubmit);
  const entryVersion = _moneyEntryChange;
  const entrySnapshot = transactionEntrySnapshot();
  const action = ++_moneySavedActionSequence;
  let requestId = '';
  try {
    const transactionPayload = {
      account_id: getDropdownValue($('tx-acct')), date: $('tx-date')?.dataset.value || _today(),
      amount: sign * amtRaw, category: $('tx-cat').value.trim(), payee: $('tx-payee').value.trim(),
      tags: $('tx-tags')?.value.trim() || '',
    };
    requestId = await _createRequestId('transaction', transactionPayload);
    _moneySavedAction = Math.max(_moneySavedAction, action);
    _transactionSaveRequestId = requestId;
    _transactionUncertainSnapshot = null;
    transactionSaveStatus(t('money.saving_transaction'));
    transactionPayload.request_id = requestId;
    const saved = await api('/api/money/transactions', { method: 'POST', body: transactionPayload });
    const restoreFocus = action === _moneySavedAction && ownedEntryFocus && document.activeElement === focusAtSubmit;
    if (saved?.id && !_moneySaved.some(item => item.id === saved.id)) {
      _moneySaved.push({ id: saved.id, request_id: requestId, saved, state: saved.undo ? 'ready' : _canonicalLedger ? 'unsupported' : 'blocked' });
    }
    if (saved?.id && action === _moneySavedAction) _moneySavedCurrent = saved.id;
    if (!persistSavedTransactions()) {
      _releaseCreateRequest('transaction', requestId);
      if (requestId === _transactionSaveRequestId) {
        _transactionSaveRequestId = '';
        _transactionUncertainSnapshot = null;
        transactionSaveStatus(t('money.saved_no_undo_storage'));
      }
      await load(fetch, true);
      return;
    }
    _completeCreateRequest('transaction', requestId);
    if (requestId === _transactionSaveRequestId) {
      _transactionSaveRequestId = '';
      _transactionUncertainSnapshot = null;
      transactionSaveStatus('');
    }
    if (entryVersion === _moneyEntryChange && entrySnapshot === transactionEntrySnapshot()) {
      for (const id of ['tx-payee', 'tx-cat', 'tx-amt', 'tx-tags']) if ($(id)) $(id).value = '';
      if (!$('tr-amt')?.value.trim() && (restoreFocus || !$('money-entry-fields')?.contains(document.activeElement))) {
        _moneyEntryOpen = false;
        if (restoreFocus) {
          renderSavedTransactions();
          const undo = saved?.id && $('money-save-results')?.querySelector(`[data-undo-saved="${CSS.escape(saved.id)}"]`);
          (undo || savedResultFocusTarget())?.focus();
        }
        syncMoneyLayout();
      }
    }
    const focusVersion = _moneyFocusChange;
    await load(fetch, true);
    if (restoreFocus && _moneyFocusChange === focusVersion && document.activeElement === document.body) {
      const undo = $('money-save-results')?.querySelector(`[data-undo-saved="${CSS.escape(saved.id)}"]`);
      (undo || $('money-save-results'))?.focus();
    }
  } catch (error) {
    if (requestId) _releaseCreateRequest('transaction', requestId);
    if (requestId && requestId === _transactionSaveRequestId) {
      const refused = [400, 401, 403, 404, 409, 410, 422].includes(error.status);
      _transactionUncertainSnapshot = refused ? null : entrySnapshot;
      if (refused) transactionSaveStatus(t('money.transaction_refused', { reason: error.message || t('money.review_entry') }));
      else updateTransactionSaveStatus();
    }
    toast(requestId ? t('money.check_entry_status') : error.message || t('money.could_not_start'), 'error');
  }
}

function transactionEntrySnapshot() {
  return JSON.stringify(['tx-payee', 'tx-cat', 'tx-amt', 'tx-tags', 'tx-acct', 'tx-sign', 'tx-date',
    'tr-from', 'tr-to', 'tr-amt', 'tr-date', 'tr-notes'].map(id => [$(id)?.value, $(id)?.dataset?.value]));
}
async function delTxn(id) {
  if (!await dlgConfirm(t('money.delete_transaction_confirm'))) return;
  const next = _rowAfter(id), focusVersion = _moneyFocusChange;
  try { await api(`/api/money/transactions/${id}`, { method: 'DELETE' }); }
  catch { toast(t('money.delete_failed'), 'error'); return; }
  // gone at once, even if the refresh fails. load(fetch, true) keeps an active search (load()
  // alone drops back to the month); then focus lands on the next row
  _dropRows(row => row.id === id);
  await load(fetch, true);
  _focusAfterRowDelete(next, focusVersion);
}

// take deleted rows out of what's on screen, so the redraw before the fresh read doesn't bring
// them back (and hand focus to a row that's gone)
function _dropRows(gone) {
  _txns = _txns.filter(row => !gone(row));
  if (_searchResults) _searchResults = _searchResults.filter(row => !gone(row));
  renderTxns();
}

// the row the user meets next once this one is gone: the one below, else the one above
function _rowAfter(id) {
  const rows = _searchResults !== null ? _searchResults : _txns;
  const at = rows.findIndex(row => row.id === id || (id && row.transfer_id === id));
  if (at < 0) return '';
  const rest = rows.filter((row, i) => i !== at && !(id && row.transfer_id === id));
  return (rest[at] || rest[at - 1])?.id || '';
}

function _focusAfterRowDelete(next, focusVersion) {
  if (focusVersion !== _moneyFocusChange || (document.activeElement && document.activeElement !== document.body)) return;
  const rows = $('txn-rows');
  (next && rows?.querySelector(`.txn[data-id="${CSS.escape(next)}"] .tx-del`) || $('txn-search'))?.focus();
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
    amount: r.querySelector('.split-amt')?.value || '',
  }));
}
async function saveSplits(id) {
  const draft = _readSplitRows();
  const amounts = draft.map(s => _decimal(s.amount, 0));
  if (!_validAmounts(...amounts)) return;
  const splits = draft.map((s, i) => ({ ...s, amount: amounts[i] })).filter(s => s.category && s.amount > 0);
  try {
    await api(`/api/money/transactions/${id}/splits`, { method: 'PUT', body: { splits } });
    _splitTxn = null; _splitRows = [];
    await load();
  } catch (e) { toast(e?.message?.includes('exceed') ? t('money.splits_exceed') : t('money.save_failed_short'), 'error'); }
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
      const up = await api('/api/uploads', { method: 'POST', body: fd });
      if (typeof up?.id !== 'string' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(up.id)) {
        throw new Error('invalid upload acknowledgment');
      }
      const saved = await api(`/api/money/transactions/${id}`, { method: 'PATCH', body: { receipt_id: up.id } });
      if (saved?.id !== id || saved.receipt_id !== up.id) throw new Error('attachment not confirmed');
      toast(t('money.receipt_attached'), 'success');
      await load(fetch, true);
    } catch { toast(t('money.receipt_not_confirmed'), 'error'); }
  };
  inp.click();
}
async function toggleCleared(id) {
  const rows = _searchResults !== null ? _searchResults : _txns;
  const txn = rows.find(x => x.id === id);
  try {
    await api(`/api/money/transactions/${id}`, { method: 'PATCH', body: { cleared: !(txn && txn.cleared) } });
    await load();
  } catch { toast(t('money.failed'), 'error'); }
}
export async function filterByTag(tag) {
  clearTimeout(_searchTimer);
  const sequence = ++_searchSequence;
  _tagFilter = tag;
  await readTransactionFilter(`/api/money/transactions?tag=${encodeURIComponent(tag)}`, sequence);
}
function clearTagFilter() {
  clearTimeout(_searchTimer);
  _searchSequence += 1;
  _tagFilter = '';
  _searchResults = null;
  _searchStatus = '';
  renderTxns();
}
function renderTxns(rebuildSplit = false) {
  const rows = $('txn-rows');
  if (!rows) return;
  const retained = retainMoneyDrafts(rows, false);
  // An explicit row change replaces the editor; background reads retain its live draft.
  if (rebuildSplit) retained.nodes = retained.nodes.filter(({ node }) => !node.classList.contains('txn-split-editor'));
  rows.innerHTML = txnList();
  _wireTxnRows();
  restoreMoneyDrafts(rows, retained);
  if (['txn-search-retry', 'txn-search-clear', 'tag-clear'].includes(retained.active?.id)
      && retained.focusVersion === _moneyFocusChange && document.activeElement === document.body) {
    $('txn-search')?.focus();
  }
}
function toggleReconcile(aid) {
  const wrap = $(`rc-panel-${aid}`); if (!wrap) return;
  wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
}
async function runReconcile(aid) {
  const v = _decimal($(`rc-stmt-${aid}`)?.value);
  const out = $(`rc-out-${aid}`); if (!out) return;
  if (!Number.isFinite(v)) { out.className = 'rc-out bad'; out.textContent = t('money.statement_decimal'); return; }
  try {
    const d = await api(`/api/money/accounts/${aid}/reconcile?statement=${v}`);
    out.className = 'rc-out ' + (d.reconciled ? 'ok' : 'bad');
    out.textContent = d.reconciled
      ? t('money.reconciled', { amount: fmt(d.cleared_balance) })
      : t('money.off_by', { amount: fmt(d.cleared_balance), diff: fmt(Math.abs(d.difference)) });
  } catch { out.textContent = t('money.failed'); }
}
let _transferBusy = false;
async function doTransfer() {
  // a second click while the first is out would only meet "already in progress" for a transfer
  // that worked
  if (_transferBusy) return;
  const from = getDropdownValue($('tr-from')), to = getDropdownValue($('tr-to'));
  const amt = _decimal($('tr-amt')?.value);
  if (!_validAmounts(amt)) return;
  if (!amt || amt <= 0) { toast(t('money.enter_amount'), 'error'); return; }
  if (from === to) { toast(t('money.pick_two_accounts'), 'error'); return; }
  let requestId = '';
  _transferBusy = true;
  try {
    const transferPayload = {
      from_account: from, to_account: to, amount: amt, date: $('tr-date')?.dataset.value || _today(),
    };
    requestId = await _createRequestId('transfer', transferPayload);
    transferPayload.request_id = requestId;
    await api('/api/money/transfer', { method: 'POST', body: transferPayload });
    _completeCreateRequest('transfer', requestId);
    toast(t('money.transferred'), 'success');
    await load();
  } catch (error) {
    if (requestId) _releaseCreateRequest('transfer', requestId);
    toast(error.message || t('money.transfer_failed'), 'error');
  } finally {
    _transferBusy = false;
  }
}
async function delTransfer(tid) {
  if (!await dlgConfirm(t('money.delete_transfer_confirm'))) return;
  const next = _rowAfter(tid), focusVersion = _moneyFocusChange;
  try { await api(`/api/money/transfer/${tid}`, { method: 'DELETE' }); }
  catch { toast(t('money.delete_failed'), 'error'); return; }
  _dropRows(row => row.transfer_id === tid);
  await load(fetch, true);
  _focusAfterRowDelete(next, focusVersion);
}
async function saveTxn(id) {
  const row = $('money-body').querySelector(`.txn-edit[data-id="${id}"]`);
  if (!row) return;
  const f = name => row.querySelector(`[data-f="${name}"]`);
  const amtRaw = _decimal(f('amount')?.value);
  if (!_validAmounts(amtRaw)) return;
  if (!amtRaw || amtRaw <= 0) { toast(t('money.enter_amount'), 'error'); return; }
  const sign = getDropdownValue(f('sign')) === '+' ? 1 : -1;
  const existing = (_searchResults || _txns).find(transaction => transaction.id === id)
    || { account_id: row.dataset.originalAccount, amount: Number(row.dataset.originalAmount) };
  const payload = {
    account_id: getDropdownValue(f('account_id')), date: f('date')?.dataset.value || _today(),
    amount: sign * amtRaw, category: f('category').value.trim(), payee: f('payee').value.trim(),
  };
  if (existing) {
    if (payload.account_id === existing.account_id) delete payload.account_id;
    if (payload.amount === existing.amount) delete payload.amount;
  }
  const focused = document.activeElement, focusVersion = _moneyFocusChange;
  try {
    const saved = await api(`/api/money/transactions/${id}`, { method: 'PATCH', body: payload });
    for (const transactions of [_txns, _searchResults]) {
      const baseline = transactions?.find(transaction => transaction.id === id);
      if (baseline) Object.assign(baseline, saved);
    }
    row.dataset.originalAccount = saved.account_id;
    row.dataset.originalAmount = String(saved.amount);
    if (_editTxn === id) _editTxn = null;
    await load(fetch, true);
    // safari doesn't focus a tapped button, so a tap on save leaves focus on <body> already
    const owned = !focused || focused === document.body || row.contains(focused);
    if (owned && focusVersion === _moneyFocusChange && document.activeElement === document.body) {
      ($('txn-rows').querySelector(`[data-edit-txn="${CSS.escape(id)}"]`) || $('txn-search'))?.focus();
    }
  } catch { toast(t('money.save_failed_short'), 'error'); }
}

async function editAccountCurrency(id) {
  const account = _accounts.find(row => row.id === id);
  if (!account || _canonicalLedger || account.currency_edit_reason) return;
  const status = $(`acct-currency-status-${id}`);
  if (!_currencyCodes.length) { status.textContent = t('money.currency_choices_reload'); return; }
  const selected = await dlgChoose(t('money.currency_for', { name: account.name }), _currencyCodes.map(value => ({ value, label: value })));
  if (selected === null || selected === account.currency_code) return;
  if (account.currency_code === 'XXX' && (account.balance || account.opening)
    && !await dlgConfirm(t('money.count_as', { name: account.name, code: selected }), { confirmLabel: t('money.use_code', { code: selected }), danger: false })) return;
  const button = document.querySelector(`[data-currency-acct="${CSS.escape(id)}"]`);
  if (!button || !_currencyCodes.includes(selected)) return;
  const focused = document.activeElement, focusVersion = _moneyFocusChange;
  button.disabled = true;
  try {
    await api(`/api/money/accounts/${id}`, { method: 'PATCH', body: { currency: selected } });
    await load(fetch, true);
    if (focused === button && focusVersion === _moneyFocusChange && document.activeElement === document.body) {
      document.querySelector(`[data-currency-acct="${CSS.escape(id)}"]`)?.focus();
    }
  } catch (error) { status.textContent = plainError(error.message || t('money.currency_save_failed')); }
  finally { button.disabled = false; }
}
async function addGoal() {
  if (_goalSaving) return;
  const name = $('gl-name')?.value.trim();
  if (!name) { toast(t('money.name_goal'), 'error'); return; }
  const target = _decimal($('gl-target')?.value, 0);
  const current = _decimal($('gl-current')?.value, 0);
  const monthly = _decimal($('gl-monthly')?.value, 0);
  if (!_validAmounts(target, current, monthly)) return;
  const kind = getDropdownValue($('gl-kind')) || 'savings';
  const fields = ['gl-name', 'gl-target', 'gl-current', 'gl-monthly'].map(id => [id, $(id), $(id)?.value]);
  const button = $('gl-add');
  _goalSaving = true;
  if (button) button.disabled = true;
  try {
    const saved = await api('/api/money/goals', { method: 'POST', body: { name, kind, target, current, monthly } });
    if (!saved?.id || saved.name !== name || saved.kind !== kind
      || saved.target !== target || saved.current !== current || saved.monthly !== monthly) {
      throw Object.assign(new Error(t('money.goal_unconfirmed')), { unconfirmed: true });
    }
    if (fields.every(([id, field, value]) => $(id) === field && field.value === value)
      && getDropdownValue($('gl-kind')) === kind) fields.forEach(([, field]) => { field.value = ''; });
    await load(fetch, true);
  } catch (error) { toast(error.unconfirmed ? error.message : t('money.add_failed'), 'error'); }
  finally {
    _goalSaving = false;
    if ($('gl-add')) $('gl-add').disabled = false;
  }
}
async function delGoal(id) {
  if (!await dlgConfirm(t('money.delete_goal_confirm'))) return;
  try { await api(`/api/money/goals/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast(t('money.delete_failed'), 'error'); }
}
async function runReport() {
  const start = $('rp-start')?.dataset.value || '', end = $('rp-end')?.dataset.value || '';
  const out = $('rp-out'); if (!out) return;
  const p = new URLSearchParams(); if (start) p.set('start', start); if (end) p.set('end', end);
  try {
    const d = await api(`/api/money/report?${p}`);
    const cur = d.currency || _cur;
    const cats = (d.by_category || []).map(c => `<div class="rp-cat"><span>${esc(c[0])}</span><span>${fmt(c[1], cur)}</span></div>`).join('');
    const left = excludedNotes({ ..._sum, ...d }, row => {
      if (row.currency === 'XXX') return t('money.report_no_currency');
      const income = row.income && amountIn(row.currency, row.income), expense = row.expense && amountIn(row.currency, row.expense);
      if (income && expense) return t('money.report_both', { income, expense });
      if (income) return t('money.report_income', { income });
      if (expense) return t('money.report_expense', { expense });
      return t('money.report_currency', { code: row.currency });
    });
    out.innerHTML = `${left}<div class="rp-tot">${t('money.report_totals', { income: `<span class="pos">${fmt(d.income, cur)}</span>`, spent: `<span class="neg">${fmt(d.expense, cur)}</span>`, net: signed(d.net, cur) })}</div>${cats}`;
    wireCurrency(out, { ..._sum, ...d }, () => load(fetch, true));
    const link = $('rp-export');
    if (link) { link.href = `/api/money/report/export.csv?${p}`; link.style.display = ''; }
  } catch { out.textContent = t('money.report_failed'); }
}
async function addHolding() {
  const symbol = $('hd-sym')?.value.trim();
  if (!symbol) { toast(t('money.enter_symbol'), 'error'); return; }
  const qty = _decimal($('hd-qty')?.value, 0);
  const cost_basis = _decimal($('hd-cost')?.value, 0);
  const price = _decimal($('hd-price')?.value, 0);
  if (!_validAmounts(qty, cost_basis, price)) return;
  try {
    await api('/api/money/holdings', { method: 'POST', body: {
      symbol, qty, cost_basis, price,
    } });
    await load();
  } catch { toast(t('money.add_failed'), 'error'); }
}
async function delHolding(id) {
  if (!await dlgConfirm(t('money.delete_holding_confirm'))) return;
  try { await api(`/api/money/holdings/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast(t('money.delete_failed'), 'error'); }
}

// dashboard: hide/show cards, persisted in localStorage (4c)
function _hiddenCards() { try { return new Set(JSON.parse(localStorage.getItem('money-hidden-cards') || '[]')); } catch { return new Set(); } }
function _saveHidden(set) { try { localStorage.setItem('money-hidden-cards', JSON.stringify([...set])); } catch {} }
function _decorateCards() {
  const hidden = _hiddenCards();
  let hiddenCount = 0;
  $('money-body').querySelectorAll('.money-card[data-card]').forEach(card => {
    const id = card.dataset.card;
    const h3 = card.querySelector('h3');
    if (h3 && !h3.querySelector('.card-hide')) {
      const x = document.createElement('button');
      x.className = 'card-hide'; x.textContent = '×'; x.title = t('money.hide_card');
      x.setAttribute('aria-label', t('money.hide_card_named', { name: h3.firstChild?.textContent.trim() || id }));
      x.addEventListener('click', () => { const s = _hiddenCards(); s.add(id); _saveHidden(s); _decorateCards(); });
      h3.appendChild(x);
    }
    const attention = card.dataset.attention === 'true';
    const hide = h3?.querySelector('.card-hide');
    if (hide) {
      if (attention && document.activeElement === hide) focusMoneyTask(_moneyPlanTask);
      hide.disabled = attention;
      hide.title = attention ? t('money.resolve_before_hiding') : t('money.hide_card');
    }
    const conceal = hidden.has(id) && !attention;
    if (conceal) {
      hiddenCount++;
      if (card.contains(document.activeElement)) {
        const task = card.closest('[data-money-task-panel]')?.dataset.moneyTaskPanel;
        if (task) focusMoneyTask(task);
        else card.closest('.money-section')?.querySelector('[data-money-section]')?.focus();
      }
    }
    card.style.display = conceal ? 'none' : '';
  });
  // a restore chip when anything is hidden
  let chip = $('money-restore-cards');
  if (hiddenCount) {
    if (!chip) {
      chip = document.createElement('button');
      chip.id = 'money-restore-cards'; chip.className = 'btn money-restore-cards';
      chip.addEventListener('click', () => {
        _saveHidden(new Set()); _decorateCards(); focusMoneyTask(_moneyPlanTask);
      });
      $('money-body').querySelector('.money-grid')?.appendChild(chip);
    }
    chip.textContent = tp('money.restore_cards', hiddenCount);
    chip.style.display = '';
  } else if (chip) {
    if (document.activeElement === chip) focusMoneyTask(_moneyPlanTask);
    chip.style.display = 'none';
  }
}
async function assignEnvelope(category, amount, categoryId = '', expectedAmount = null) {
  category = (category || '').trim();
  if (!category && !_canonicalLedger) { toast(t('money.name_category'), 'error'); return false; }
  amount = _decimal(amount, 0);
  if (!_validAmounts(amount)) return false;
  const key = `${_month}:${categoryId || category}`;
  if (_envAssignmentBusy.has(key)) return false;
  const focusOwner = captureMoneyFocus('budgets');
  _envAssignmentBusy.add(key);
  try {
    const body = _canonicalLedger
      ? { category_id: categoryId, month: _month, amount, expected_amount: _decimal(expectedAmount) }
      : { category, month: _month, amount };
    if (_canonicalLedger && (!categoryId || !_validAmounts(body.expected_amount))) return false;
    await api('/api/money/envelope/assign', { method: 'PUT', body });
    _envelope = await api(`/api/money/envelope?month=${_month}`).catch(() => null);
    const card = $('money-body').querySelector('.money-envelope');
    if (card) {
      const restoreFocus = ownsMoneyFocus(focusOwner);
      if (restoreFocus) _moneyPlanTask = 'budgets';
      else if (card.contains(document.activeElement)) focusMoneyTask(_moneyPlanTask);
      card.innerHTML = envelopeHeading() + envelopeCard(); _wireEnvelope();
      refreshMoneyTasks();
      const target = _envelope
        ? [...card.querySelectorAll('.env-assign')].find(input => input.dataset.categoryId === categoryId)
        : card.querySelector('#env-retry');
      if (restoreFocus) focusMoneyTask('budgets', target || card.querySelector('h3'));
    }
    return true;
  } catch (error) {
    const status = $('env-save-status');
    if (status) {
      const stale = error?.message?.includes('changed; reload');
      status.textContent = stale
        ? t('money.assignment_changed')
        : t('money.keep_amount_retry');
      if (!stale) {
        status.insertAdjacentHTML('beforeend', `<button type="button" class="btn" data-env-retry-save>${t('money.retry_same_amount_btn')}</button>`);
        status.querySelector('[data-env-retry-save]').addEventListener(
          'click', () => assignEnvelope(category, amount, categoryId, expectedAmount),
        );
      }
    } else toast(t('money.assign_failed'), 'error');
    return false;
  } finally { _envAssignmentBusy.delete(key); refreshMoneyTasks(); }
}

async function retryAgeOfMoney() {
  const button = $('age-retry');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try { _aom = await api('/api/money/age-of-money'); }
  catch { _aom = null; }
  const content = $('money-age-content');
  if (!content) return;
  content.innerHTML = ageOfMoneyStatus();
  (_aom ? content.closest('h3') : $('age-retry'))?.focus();
}

async function retryEnvelope() {
  const button = $('env-retry');
  const focusOwner = captureMoneyFocus('budgets');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try { _envelope = await api(`/api/money/envelope?month=${_month}`); }
  catch { _envelope = null; }
  const card = $('money-body').querySelector('.money-envelope');
  if (!card) return;
  const restoreFocus = ownsMoneyFocus(focusOwner);
  if (restoreFocus) _moneyPlanTask = 'budgets';
  else if (card.contains(document.activeElement)) focusMoneyTask(_moneyPlanTask);
  card.innerHTML = envelopeHeading() + envelopeCard();
  _wireEnvelope();
  refreshMoneyTasks();
  if (restoreFocus) focusMoneyTask('budgets', _envelope ? card.querySelector('h3') : $('env-retry'));
}

function _wireEnvelope() {
  $('money-age-content')?.addEventListener('click', event => {
    if (event.target.closest('#age-retry')) retryAgeOfMoney();
  });
  $('env-retry')?.addEventListener('click', retryEnvelope);
  $('money-body').querySelectorAll('.env-assign').forEach(inp =>
    inp.addEventListener('change', () => assignEnvelope(
      inp.dataset.cat, inp.value, inp.dataset.categoryId, inp.dataset.expected,
    )));
  $('money-body').querySelectorAll('[data-env-retry]').forEach(button =>
    button.addEventListener('click', () => assignEnvelope(
      '', button.dataset.amount, button.dataset.envRetry, button.dataset.expected,
    )));
  $('env-assign-btn')?.addEventListener('click', async () => {
    if (!await assignEnvelope($('env-new-cat')?.value, $('env-new-amt')?.value)) return;
    if ($('env-new-cat')) $('env-new-cat').value = '';
    if ($('env-new-amt')) $('env-new-amt').value = '';
  });
  $('money-body').querySelectorAll('.env-tgt-btn').forEach(b =>
    b.addEventListener('click', () => setEnvTarget(b.dataset.cat, b.dataset.categoryId)));
  $('money-body').querySelectorAll('.env-bind-target').forEach(b =>
    b.addEventListener('click', () => bindEnvTarget(b.dataset.targetId)));
  $('money-body').querySelectorAll('.env-move-target').forEach(b =>
    b.addEventListener('click', () => bindEnvTarget(b.dataset.targetId)));
}
async function setEnvTarget(category, categoryId = '') {
  const current = _canonicalLedger
    ? (_envelope?.categories || []).find(row => row.category_id === categoryId) : null;
  const label = current?.group ? `${current.group} / ${current.category}` : category;
  const draftKey = categoryId || `legacy:${category}`;
  const draft = _targetDrafts.get(draftKey) || {};
  const v = await dlgFields(t('money.funding_target_for', { name: label }), [
    { id: 'amount', label: t('money.target_amount'), value: draft.amount ?? current?.target?.amount ?? '' },
    { id: 'date', label: t('money.by_date_optional'), value: draft.date ?? current?.target?.date ?? '' },
  ]);
  if (!v) return;
  const amount = _decimal(v.amount, 0);
  if (!_validAmounts(amount)) return;
  if (_canonicalLedger && amount < 0) { toast(t('money.use_zero_clear'), 'error'); return; }
  try {
    await api('/api/money/envelope/target', { method: 'PUT', body: { category, category_id: categoryId, amount, target_date: (v.date || '').trim() } });
    _targetDrafts.delete(draftKey);
    _targetStatus = '';
    await load();
    [...document.querySelectorAll('.env-tgt-btn')].find(button => _canonicalLedger
      ? button.dataset.categoryId === categoryId : button.dataset.cat === category)?.focus();
  } catch {
    _targetDrafts.set(draftKey, { amount: v.amount, date: v.date });
    _targetStatus = t('money.target_save_failed', { name: label });
    if ($('env-target-status')) $('env-target-status').textContent = _targetStatus;
    else toast(t('money.target_save_failed_short'), 'error');
  }
}
async function bindEnvTarget(targetId) {
  const unbound = (_envelope?.unbound_targets || []).find(row => row.id === targetId);
  const bound = (_envelope?.categories || []).find(row => row.target?.id === targetId);
  if (!unbound && !bound) return;
  const label = unbound ? unbound.category : (bound.group ? `${bound.group} / ${bound.category}` : bound.category);
  const categories = (_envelope?.categories || []).filter(row => !row.target);
  if (!categories.length) { toast(t('money.no_unused_category'), 'error'); return; }
  const names = categories.map(row => row.group ? `${row.group} / ${row.category}` : row.category);
  const selected = await dlgChoose(t('money.choose_category_for', { name: label }), categories.map((row, index) => ({
    value: row.category_id,
    label: names.filter(name => name === names[index]).length > 1 ? `${names[index]} (${row.category_id.slice(-6)})` : names[index],
  })));
  if (!selected) return;
  try {
    await api('/api/money/envelope/target/bind', { method: 'POST', body: { target_id: targetId, category_id: selected } });
    _targetStatus = '';
    await load();
    [...document.querySelectorAll('.env-tgt-btn')].find(button => button.dataset.categoryId === selected)?.focus();
  } catch {
    _targetStatus = t('money.category_change_failed', { name: label });
    if ($('env-target-status')) $('env-target-status').textContent = _targetStatus;
  }
}
async function addBudget() {
  if (_budgetSaving) return;
  const category = $('bf-cat')?.value.trim();
  const limit_amt = _decimal($('bf-amt')?.value, 0);
  if (!_validAmounts(limit_amt)) return;
  if (!category) { toast(t('money.pick_category'), 'error'); return; }
  const fields = ['bf-cat', 'bf-amt'].map(id => [id, $(id), $(id)?.value]);
  const button = $('bf-add');
  _budgetSaving = true;
  if (button) button.disabled = true;
  try {
    const saved = await api('/api/money/budgets', { method: 'POST', body: { category, limit_amt } });
    if (!saved?.id || saved.category !== category || saved.limit_amt !== limit_amt) {
      throw Object.assign(new Error(t('money.cap_unconfirmed')), { unconfirmed: true });
    }
    if (fields.every(([id, field, value]) => $(id) === field && field.value === value)) {
      fields.forEach(([, field]) => { field.value = ''; });
    }
    await load(fetch, true);
  } catch (error) {
    toast(error.unconfirmed ? error.message
      : error.message?.includes('budget cap requires one existing spending category') ? t('money.use_existing_category') : t('money.cap_failed'), 'error');
  } finally {
    _budgetSaving = false;
    if ($('bf-add')) $('bf-add').disabled = false;
  }
}
async function delBudget(id) {
  if (!await dlgConfirm(t('money.remove_cap_confirm'))) return;
  try { await api(`/api/money/budgets/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast(t('money.delete_failed'), 'error'); }
}
async function addRecurring() {
  const payee = $('rc-payee')?.value.trim();
  const amtRaw = _decimal($('rc-amt')?.value);
  if (!_validAmounts(amtRaw)) return;
  if (!payee && _canonicalLedger) { toast(t('money.give_payee'), 'error'); return; }
  if (!payee && !$('rc-cat')?.value.trim()) { toast(t('money.give_payee_or_category'), 'error'); return; }
  if (!amtRaw || amtRaw <= 0) { toast(t('money.enter_amount'), 'error'); return; }
  const sign = getDropdownValue($('rc-sign')) === '+' ? 1 : -1;
  const payload = {
    account_id: getDropdownValue($('rc-acct')), amount: sign * amtRaw,
    payee, cycle: getDropdownValue($('rc-cycle')),
    next_date: $('rc-next')?.dataset.value || _today(),
  };
  if (_canonicalLedger) payload.category_id = $('rc-category-choice')?.dataset.categoryId || '';
  else payload.category = $('rc-cat').value.trim();
  const button = $('rc-add');
  let requestId = '';
  if (button) { button.disabled = true; button.textContent = t('common.saving'); }
  try {
    if (_canonicalLedger) {
      requestId = await _createRequestId('recurring', payload);
      payload.request_id = requestId;
    }
    await api('/api/money/recurring', { method: 'POST', body: payload });
    if (requestId) _completeCreateRequest('recurring', requestId);
    await load();
    // a first date of today or earlier posts its charge right away; say so, or it looks like a
    // stray transaction (and a rent already logged by hand gets counted twice)
    toast(payload.next_date <= _today() ? t('money.schedule_added_now')
      : t('money.schedule_added_on', { date: payload.next_date }), 'success');
  } catch (error) {
    if (requestId) _releaseCreateRequest('recurring', requestId);
    if (_canonicalLedger) {
      _recurringStatus = t('money.creation_not_confirmed', { error: error.message || t('money.retry_saved_schedule') });
      await readRecurring(api);
      const content = $('recurring-content');
      if (_recurring.some(row => row.create_pending) && content) {
        content.innerHTML = `<div id="recurring-list">${recurringList()}</div>` + _recurringForm();
        wireRecurring();
        content.querySelector('[data-retry-create-rec]')?.focus();
      } else {
        const list = $('recurring-list');
        if (list) { list.innerHTML = recurringList(); wireRecurringList(); }
      }
    } else toast(t('money.add_recurring_failed'), 'error');
    if (button) { button.disabled = false; button.textContent = _canonicalLedger ? t('money.add_schedule') : t('common.add'); }
  }
}
async function chooseRecurringCategory() {
  const button = $('rc-category-choice');
  if (!button) return;
  let categories = _envelope?.categories;
  if (!Array.isArray(categories)) {
    try { categories = (await api(`/api/money/envelope?month=${_month}`)).categories; }
    catch { categories = null; }
  }
  if (!Array.isArray(categories)) {
    _recurringStatus = t('money.categories_failed');
    const list = $('recurring-list');
    if (list) { list.innerHTML = recurringList(); wireRecurringList(); }
    return;
  }
  const names = categories.map(row => row.group ? `${row.group} / ${row.category}` : row.category);
  const options = [{ value: '', label: t('money.no_category') }, ...categories.map((row, index) => ({
    value: row.category_id,
    label: names.filter(name => name === names[index]).length > 1
      ? `${names[index]} (${row.category_id.slice(-6)})` : names[index],
  }))];
  const selected = await dlgChoose(t('money.choose_spending_category'), options);
  if (selected === null) return;
  button.dataset.categoryId = selected;
  button.textContent = options.find(option => option.value === selected)?.label || t('money.no_category');
  button.focus();
}
async function retryRecurringCreate(button) {
  const r = _recurring.find(row => row.id === button.dataset.retryCreateRec);
  if (!_canonicalLedger || !r?.create_pending || r.create_needs_review || button.disabled) return;
  const focusOwner = captureMoneyFocus('schedules');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/retry`, { method: 'POST' });
    _recurringStatus = '';
  } catch (error) {
    _recurringStatus = t('money.creation_not_confirmed_for', { payee: r.payee, error: error.message || t('money.review_in_actual') });
  }
  await retryRecurring(r.id, focusOwner);
}
async function retryRecurringEdit(button) {
  const r = _recurring.find(row => row.id === button.dataset.retryEditRec);
  if (!_canonicalLedger || !r?.edit_pending || r.edit_needs_review || button.disabled) return;
  const focusOwner = captureMoneyFocus('schedules');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/edit/retry`, { method: 'POST' });
    _recurringStatus = '';
  } catch (error) {
    _recurringStatus = t('money.edit_not_confirmed_for', { payee: r.payee, error: error.message || t('money.review_in_actual') });
  }
  await retryRecurring(r.id, focusOwner);
}
async function retryRecurringDelete(button) {
  const r = _recurring.find(row => row.id === button.dataset.retryDeleteRec);
  if (!_canonicalLedger || !r?.delete_pending || r.delete_needs_review || button.disabled) return;
  const focusOwner = captureMoneyFocus('schedules');
  button.disabled = true;
  button.textContent = t('money.retrying');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/delete/retry`, { method: 'POST' });
    _recurringStatus = '';
  } catch (error) {
    _recurringStatus = t('money.deletion_not_confirmed_for', { payee: r.payee, error: error.message || t('money.review_in_actual') });
  }
  await retryRecurring(r.id, focusOwner);
}
async function delRecurring(id) {
  let focusOwner = captureMoneyFocus('schedules');
  if (_canonicalLedger) {
    const r = _recurring.find(row => row.id === id);
    if (!r?.editable || _recurringEdit) return;
    if (!await dlgConfirm(t('money.delete_schedule_confirm', { name: r.payee || t('money.recurring') }))) return;
    focusOwner = captureMoneyFocus('schedules');
    try {
      await api(`/api/money/recurring/${encodeURIComponent(id)}/delete`, {
        method: 'POST', body: { confirm_id: id },
      });
      _recurringStatus = '';
    } catch (error) {
      _recurringStatus = t('money.deletion_not_confirmed_for', { payee: r.payee, error: error.message || t('money.retry_saved_deletion') });
    }
    await retryRecurring(id, focusOwner);
    return;
  }
  if (!await dlgConfirm(t('money.stop_recurring_confirm'))) return;
  try { await api(`/api/money/recurring/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  catch { toast(t('money.delete_failed'), 'error'); }
}
async function toggleRecurring(button) {
  const focusOwner = captureMoneyFocus('schedules');
  const r = _recurring.find(x => x.id === button.dataset.toggleRec);
  if (!r || button.disabled || (_canonicalLedger && !r.manageable)) return;
  const active = r.posting_pending ? r.posting_target_active : !r.active;
  button.disabled = true;
  button.textContent = t('common.saving');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}`, { method: 'PATCH', body: { active } });
    _recurringStatus = '';
    if (_canonicalLedger) await retryRecurring(r.id, focusOwner);
    else await load();
  } catch (error) {
    if (_canonicalLedger) {
      _recurringStatus = t(active ? 'money.resume_not_confirmed_for' : 'money.pause_not_confirmed_for', { payee: r.payee, error: error.message || t('money.retry_saved_action') });
      await retryRecurring(r.id, focusOwner);
    } else {
      button.disabled = false;
      button.textContent = r.active ? t('subs.pause') : t('subs.resume');
      toast(t('money.update_failed'), 'error');
    }
  }
}
async function repairRecurring(button) {
  let focusOwner = captureMoneyFocus('schedules');
  const r = _recurring.find(row => row.id === button.dataset.repairRec);
  if (!r?.repair_needed || !_canonicalLedger || button.disabled) return;
  let categoryId = r.repair_category_id;
  if (!r.repair_pending) {
    let categories = _envelope?.categories;
    if (!Array.isArray(categories)) {
      try { categories = (await api(`/api/money/envelope?month=${_month}`)).categories; }
      catch { categories = null; }
    }
    if (!Array.isArray(categories)) {
      _recurringStatus = t('money.categories_failed');
      await retryRecurring('', focusOwner);
      return;
    }
    const names = categories.map(row => row.group ? `${row.group} / ${row.category}` : row.category);
    const options = categories.map((row, index) => ({
      value: row.category_id,
      label: names.filter(name => name === names[index]).length > 1
        ? `${names[index]} (${row.category_id.slice(-6)})` : names[index],
    }));
    if (!r.category) options.unshift({ value: '', label: t('money.leave_uncategorized') });
    if (!options.length) {
      _recurringStatus = t('money.add_category_first');
      await retryRecurring('', focusOwner);
      return;
    }
    categoryId = await dlgChoose(t('money.choose_actual_category_for', { name: r.payee }), options);
    if (categoryId === null) return;
    focusOwner = captureMoneyFocus('schedules');
  }
  button.disabled = true;
  button.textContent = t('money.repairing');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/repair`, {
      method: 'POST', body: { category_id: categoryId },
    });
    _recurringStatus = '';
    await retryRecurring('', focusOwner);
    toast(t('money.posting_repaired'), 'success');
  } catch (error) {
    _recurringStatus = t('money.repair_not_confirmed_for', { payee: r.payee, error: error.message || t('money.retry_saved_choice') });
    await retryRecurring('', focusOwner);
  }
}
async function addRule() {
  const match = $('rl-match')?.value.trim();
  if (!match) { toast(t('money.what_match'), 'error'); return; }
  try {
    await api('/api/money/rules', { method: 'POST', body: { match, category: $('rl-cat').value.trim() } });
    await load();
  } catch { toast(t('money.add_rule_failed'), 'error'); }
}
async function delRule(id) {
  if (!await dlgConfirm(t('money.delete_rule_confirm'))) return;
  try { await api(`/api/money/rules/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast(t('money.delete_failed'), 'error'); }
}
async function applyRules() {
  try {
    const r = await api('/api/money/rules/apply', { method: 'POST' });
    toast(r.updated ? tp('money.categorized', r.updated) : t('money.nothing_to_categorize'), 'success');
    await load();
  } catch { toast(t('money.apply_failed'), 'error'); }
}
