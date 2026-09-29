// money: accounts, transactions, budgets, and a couple of charts. plain SVG for
// the charts (no chart lib), api() helper for the fetches.
import { api, toast } from './util.js';
import { confirm as dlgConfirm, fields as dlgFields, choose as dlgChoose } from './dialog.js';
import { initCustomDropdown, getDropdownValue } from './dropdown.js?v=212';
import { initDatePicker, calendarDateParts } from './datepick.js';
import { formatCalendarDate, formatDate, formatNumber } from './i18n.js';
import { createFocusBoundary } from './kokuen.js?v=1';
import { requestWithRecentOwner } from './recent_owner.js';
import { replaceRouteUrl } from './route_history.js';

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
  toast('enter a number using a decimal point, e.g. 1234.56', 'error');
  return false;
}

function _thisMonth() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; }
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
let _forecastError = 'couldn\'t load forecast';
let _goals = [];   // savings/debt goals (4d)
let _searchResults = null;   // array when a search/filter is active, else null
let _searchTimer = null;
let _cur = '$';
let _inited = false;
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

async function _createRequestId(kind, payload) {
  const { fingerprint, persistable } = await _createPayloadFingerprint(payload);
  const pending = _pendingCreateRequests.get(kind);
  if (pending?.active) throw new Error(`${kind} creation is already in progress`);
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

function _today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function _shiftMonth(m, delta) {
  let [y, mo] = m.split('-').map(Number); mo += delta;
  while (mo < 1) { mo += 12; y--; } while (mo > 12) { mo -= 12; y++; }
  return `${y}-${String(mo).padStart(2, '0')}`;
}
function _monthLabel(m) {
  return formatCalendarDate(`${m}-01`, { month: 'long', year: 'numeric' }).toLowerCase();
}
const fmt = n => `${_cur}${formatNumber(Math.round((n || 0) * 100) / 100, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = n => (n >= 0 ? '+' : '−') + fmt(Math.abs(n));

export function initMoneyPanel(fetcher = fetch) {
  if (!_inited) {
    _inited = true;
    $('money-prev')?.addEventListener('click', () => { _month = _shiftMonth(_month, -1); load(); });
    $('money-next')?.addEventListener('click', () => { _month = _shiftMonth(_month, 1); load(); });
    const imp = $('money-import'), fileInp = $('money-import-file');
    $('money-connect')?.addEventListener('click', openBankConnections);
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
  return load(fetcher);
}

async function _ownerFetch(path, options = {}) {
  const init = { ...options };
  if (init.body && typeof init.body !== 'string') {
    init.headers = { 'content-type': 'application/json', ...(init.headers || {}) };
    init.body = JSON.stringify(init.body);
  }
  const response = await requestWithRecentOwner(fetch, path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail?.message || payload.detail || `request failed (${response.status})`);
  return payload;
}

function _bankDialog() {
  const overlay = document.createElement('div');
  overlay.className = 'dialog-overlay finance-bank-overlay';
  overlay.innerHTML = `<section class="dialog-card finance-bank-dialog" role="dialog" aria-modal="true" aria-labelledby="finance-bank-title">
    <header class="finance-bank-head"><div><h2 id="finance-bank-title">bank connections</h2><p>read-only sync. Alles never asks for a bank password.</p></div><button class="btn" type="button" data-bank-close>close</button></header>
    <div class="finance-bank-status" role="status" aria-live="polite"></div>
    <div class="finance-bank-connections"></div>
    <div class="finance-bank-setup">
      <section><h3>SimpleFIN</h3><p>Paste a one-time setup token. It is exchanged once and never shown again.</p><label for="finance-simplefin-token">setup token</label><textarea id="finance-simplefin-token" rows="3" autocomplete="off" spellcheck="false"></textarea><button class="btn" type="button" data-bank-simplefin>connect SimpleFIN</button></section>
      <section><h3>Plaid</h3><p>Use your Plaid application credentials, then finish in official Plaid Link.</p><label for="finance-plaid-client">client id</label><input id="finance-plaid-client" autocomplete="off"><label for="finance-plaid-secret">secret</label><input id="finance-plaid-secret" type="password" autocomplete="new-password"><div class="finance-bank-environments" role="group" aria-label="Plaid environment"><button class="btn active" type="button" aria-pressed="true" data-plaid-env="sandbox">sandbox</button><button class="btn" type="button" aria-pressed="false" data-plaid-env="production">production</button></div><button class="btn" type="button" data-bank-plaid>connect Plaid</button></section>
    </div>
  </section>`;
  return overlay;
}

async function _plaidSdk() {
  if (window.Plaid?.create) return window.Plaid;
  const existing = document.querySelector('script[data-alles-plaid-link]');
  if (existing) await new Promise((resolve, reject) => { existing.addEventListener('load', resolve, { once: true }); existing.addEventListener('error', reject, { once: true }); });
  else await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js';
    script.async = true; script.dataset.allesPlaidLink = '1';
    script.onload = resolve; script.onerror = reject; document.head.append(script);
  });
  if (!window.Plaid?.create) throw new Error('Plaid Link did not load');
  return window.Plaid;
}

async function _finishPlaid(connection, setStatus) {
  const token = await _ownerFetch(`/api/finance/connections/${encodeURIComponent(connection.id)}/plaid/link-token`, { method: 'POST' });
  const Plaid = await _plaidSdk();
  await new Promise((resolve, reject) => {
    const handler = Plaid.create({
      token: token.link_token,
      onSuccess: async publicToken => {
        try {
          await _ownerFetch(`/api/finance/connections/${encodeURIComponent(connection.id)}/plaid/exchange`, { method: 'POST', body: { public_token: publicToken } });
          resolve();
        } catch (error) { reject(error); }
      },
      onExit: error => error ? reject(new Error(error.display_message || error.error_message || 'Plaid Link closed with an error')) : reject(new Error('Plaid Link was closed')),
    });
    handler.open();
  });
  setStatus('Plaid connected. Run sync when you are ready.');
}

async function openBankConnections() {
  const overlay = _bankDialog();
  const prior = document.activeElement;
  document.body.append(overlay);
  const status = overlay.querySelector('.finance-bank-status');
  const setStatus = (message, error = false) => { status.textContent = message; status.dataset.error = error ? 'true' : 'false'; };
  const dialog = overlay.querySelector('[role="dialog"]');
  let focusBoundary = null;
  const close = () => {
    focusBoundary?.deactivate();
    focusBoundary?.destroy();
    focusBoundary = null;
    overlay.remove();
  };
  overlay.querySelector('[data-bank-close]').addEventListener('click', close);
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  focusBoundary = createFocusBoundary(dialog, { trigger: prior, onEscape: close });
  focusBoundary.activate({ source: prior, focus: overlay.querySelector('[data-bank-close]') });
  let environment = 'sandbox';
  overlay.querySelectorAll('[data-plaid-env]').forEach(button => button.addEventListener('click', () => {
    environment = button.dataset.plaidEnv;
    overlay.querySelectorAll('[data-plaid-env]').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); });
  }));
  const refresh = async () => {
    const payload = await _ownerFetch('/api/finance/connections');
    const host = overlay.querySelector('.finance-bank-connections');
    host.innerHTML = payload.connections.length ? payload.connections.map(connection => `<article class="finance-bank-row" data-bank-id="${esc(connection.id)}"><div><strong>${esc(connection.label)}</strong><span>${esc(connection.status)}${connection.last_synced_at ? ` · synced ${esc(formatDate(connection.last_synced_at))}` : ''}</span>${connection.last_error ? `<small>${esc(connection.last_error)}</small>` : ''}</div><div><button class="btn" type="button" data-bank-sync>sync</button>${connection.provider === 'plaid' && connection.status === 'link_required' ? '<button class="btn" type="button" data-bank-link>open Link</button>' : ''}<button class="btn" type="button" data-bank-disconnect>disconnect</button></div></article>`).join('') : '<p class="finance-bank-empty">no bank connections</p>';
    host.querySelectorAll('[data-bank-id]').forEach(row => {
      const connection = payload.connections.find(item => item.id === row.dataset.bankId);
      row.querySelector('[data-bank-sync]')?.addEventListener('click', async () => { try { setStatus('syncing…'); const result = await _ownerFetch(`/api/finance/connections/${encodeURIComponent(connection.id)}/sync`, { method: 'POST' }); setStatus(`sync complete · ${result.created || 0} new · ${result.updated || 0} updated`); await refresh(); await load(); } catch (error) { setStatus(error.message, true); } });
      row.querySelector('[data-bank-link]')?.addEventListener('click', async () => { try { setStatus('opening Plaid Link…'); await _finishPlaid(connection, setStatus); await refresh(); } catch (error) { setStatus(error.message, true); } });
      row.querySelector('[data-bank-disconnect]')?.addEventListener('click', async () => { if (!await dlgConfirm(`disconnect ${connection.label}? imported transactions stay in Finance.`)) return; try { await _ownerFetch(`/api/finance/connections/${encodeURIComponent(connection.id)}`, { method: 'DELETE' }); setStatus('connection revoked'); await refresh(); } catch (error) { setStatus(error.message, true); } });
    });
  };
  overlay.querySelector('[data-bank-simplefin]').addEventListener('click', async () => { const token = overlay.querySelector('#finance-simplefin-token'); try { setStatus('exchanging one-time token…'); await _ownerFetch('/api/finance/connections/simplefin', { method: 'POST', body: { setup_token: token.value.trim() } }); token.value = ''; setStatus('SimpleFIN connected'); await refresh(); } catch (error) { setStatus(error.message, true); } });
  overlay.querySelector('[data-bank-plaid]').addEventListener('click', async () => { const clientId = overlay.querySelector('#finance-plaid-client'), secret = overlay.querySelector('#finance-plaid-secret'); try { setStatus('saving encrypted Plaid credentials…'); const connection = await _ownerFetch('/api/finance/connections/plaid', { method: 'POST', body: { client_id: clientId.value.trim(), secret: secret.value, environment } }); secret.value = ''; await _finishPlaid(connection, setStatus); await refresh(); } catch (error) { setStatus(error.message, true); } });
  try { await refresh(); } catch (error) { setStatus(error.message, true); }
}

async function load(fetcher = fetch) {
  const request = (path, options = {}) => api(path, options, fetcher);
  const lbl = $('money-month-label'); if (lbl) lbl.textContent = _monthLabel(_month);
  _setMonthUrl();
  _searchResults = null;   // month change / reload clears any active search
  try {
    // Legacy reads post due entries before balances; Actual owns posting after cutover.
    _recurringStatus = '';
    await readRecurring(request);
    [_accounts, _txns, _budgets, _sum, _rules, _envelope, _aom, _forecast, _nwhist, _holdings, _alerts] = await Promise.all([
      request('/api/money/accounts'),
      request(`/api/money/transactions?month=${_month}`),
      request('/api/money/budgets'),
      request(`/api/money/summary?month=${_month}`),
      request('/api/money/rules').catch(() => []),
      request(`/api/money/envelope?month=${_month}`).catch(() => null),
      request('/api/money/age-of-money').catch(() => null),
      request(`/api/money/forecast?month=${_month}`).catch(error => { _forecastError = forecastFailure(error); return null; }),
      request('/api/money/networth-history?months=6').catch(() => null),
      request('/api/money/holdings').catch(() => null),
      request(`/api/money/alerts?month=${_month}`).catch(() => null),
    ]);
    _goals = (await request('/api/money/goals').catch(() => null))?.goals || [];
    _canonicalLedger = _sum?.ledger === 'actual';
    if (_recurringEdit && !_recurring.some(row => row.id === _recurringEdit.id && row.editable)) _recurringEdit = null;
    _cur = _sum?.currency || (_accounts[0]?.currency) || '$';
  } catch { $('money-body').innerHTML = '<div class="money-empty">failed to load</div>'; return; }
  render();
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
function render() {
  const b = $('money-body'); if (!b) return;
  _snapshotRecurringEdit();
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
    `<div id="money-alerts-content" role="status" tabindex="-1">${alertsStrip()}</div>` +
    `<div class="money-grid">
      <section class="money-card" data-card="accounts"><h3>accounts</h3>${accountsList()}<div id="money-acct-form-wrap"></div>
        <button class="btn money-add-acct" id="money-add-acct">+ account</button></section>
      <section class="money-card" data-card="category"><h3>spending by category</h3>${catChart()}</section>
      <section class="money-card" data-card="trend"><h3>last 6 months</h3>${trendChart()}</section>
      <section class="money-card" data-card="networth"><h3 tabindex="-1">net worth over time</h3><div id="nw-history-content">${networthCard()}</div></section>
      <section class="money-card money-envelope" data-card="envelope">${envelopeHeading()}${envelopeCard()}</section>
      <section class="money-card" data-card="holdings"><h3>investments</h3>${holdingsCard()}</section>
      <section class="money-card" data-card="goals"><h3>goals</h3>${goalsCard()}</section>
      <section class="money-card" data-card="reports"><h3>reports</h3>${reportsCard()}</section>
      <section class="money-card" data-card="budgets"><h3>spending caps</h3>${budgetsList()}${_budgetForm()}</section>
      <section class="money-card" data-card="recurring"><h3 tabindex="-1">recurring</h3><div id="recurring-content"><div id="recurring-list">${recurringList()}</div>${_recurringForm()}</div></section>
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
    ${forecastCard()}
  </div>`;
}

function forecastCard() {
  return `<div class="ms-card" data-forecast tabindex="-1"><span class="ms-label">projected · month-end</span>
    ${_forecast ? `<span class="ms-val ${_forecast.projected < 0 ? 'neg' : ''}">${fmt(_forecast.projected)}</span>` : `<span class="ms-unavailable" role="status">${esc(_forecastError)}</span><button type="button" class="btn ms-retry" id="forecast-retry">retry</button>`}</div>`;
}

function forecastFailure(error) {
  return error?.status === 409 && /schedule|recurrence/i.test(error.message)
    ? 'fix Actual schedule'
    : 'couldn\'t load forecast';
}

async function retryForecast() {
  const button = $('forecast-retry');
  button.disabled = true;
  button.textContent = 'retrying…';
  try { _forecast = await api(`/api/money/forecast?month=${_month}`); }
  catch (error) { _forecast = null; _forecastError = forecastFailure(error); }
  const card = document.querySelector('[data-forecast]');
  if (!card) return;
  card.outerHTML = forecastCard();
  wireForecast();
  (_forecast ? document.querySelector('[data-forecast]') : $('forecast-retry'))?.focus();
}

function wireForecast() {
  $('forecast-retry')?.addEventListener('click', retryForecast);
}

function alertsStrip() {
  const a = _alerts;
  if (!a) return '<div class="money-alerts money-history-error">couldn\'t load alerts <button type="button" class="btn" id="alerts-retry">retry</button></div>';
  const items = [];
  (a.upcoming_bills || []).forEach(b => {
    const amount = b.amount == null ? 'amount varies' : `${b.amount_kind === 'approx' ? '≈' : ''}${signed(b.amount)}`;
    items.push(`<span class="alert-chip bill">📅 ${esc(b.payee)} ${amount} in ${b.days}d</span>`);
  });
  (a.large_purchases || []).forEach(p => items.push(`<span class="alert-chip big">⚠ large: ${esc(p.payee) || esc(p.category) || '—'} ${signed(p.amount)}</span>`));
  (a.watch_hits || []).forEach(w => items.push(`<span class="alert-chip watch">👁 ${esc(w.watch)}: ${esc(w.payee) || '—'} ${signed(w.amount)}</span>`));
  (a.low_balance || []).forEach(l => items.push(`<span class="alert-chip big">🔻 ${esc(l.name)} low: ${fmt(l.balance)} < ${fmt(l.threshold)}</span>`));
  if (!items.length) return '';
  return `<div class="money-alerts">${items.join('')}</div>`;
}

async function retryAlerts() {
  const button = $('alerts-retry');
  button.disabled = true;
  button.textContent = 'retrying…';
  try { _alerts = await api(`/api/money/alerts?month=${_month}`); }
  catch { _alerts = null; }
  const content = $('money-alerts-content');
  if (!content) return;
  content.innerHTML = alertsStrip() || '<div class="money-empty-sm">no alerts right now</div>';
  wireAlerts();
  (_alerts ? content : $('alerts-retry'))?.focus();
}

function wireAlerts() {
  $('alerts-retry')?.addEventListener('click', retryAlerts);
}

function networthCard() {
  if (_nwhist === null) return '<div class="money-empty-sm money-history-error" role="status">couldn\'t load history <button type="button" class="btn" id="nw-history-retry">retry</button></div>';
  const h = _nwhist || [];
  if (h.length < 2) return '<div class="money-empty-sm">not enough history yet</div>';
  const vals = h.map(x => x.net_worth);
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  // center each point in its 1/n slot so the polyline lines up under the slot-centered month labels
  const W = 280, H = 110, step = W / h.length;
  const pts = h.map((x, i) => `${((i + 0.5) * step).toFixed(1)},${(H - ((x.net_worth - min) / span) * (H - 16) - 8).toFixed(1)}`);
  const labels = h.map((x, i) => `<span style="width:${100 / h.length}%">${x.month.slice(5)}</span>`).join('');
  return `<svg class="nw-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts.join(' ')}" fill="none" stroke="var(--accent)" stroke-width="2"></polyline></svg>
    <div class="trend-labels">${labels}</div>
    <div class="nw-now">now: ${fmt(vals[vals.length - 1])}</div>
    <div class="nw-base"><input type="text" id="nw-base-cur" class="settings-input" placeholder="base (USD/EUR…)" style="width:120px"><button class="btn" id="nw-base-go">in base ↺</button><span id="nw-base-out" class="nw-base-out"></span></div>`;
}

async function retryNetworthHistory() {
  const button = $('nw-history-retry');
  button.disabled = true;
  button.textContent = 'retrying…';
  try { _nwhist = await api('/api/money/networth-history?months=6'); }
  catch { _nwhist = null; }
  const content = $('nw-history-content');
  if (!content) return;
  content.innerHTML = networthCard();
  wireNetworthHistory();
  ($('nw-history-retry') || document.querySelector('.money-card[data-card="networth"] h3'))?.focus();
}

function wireNetworthHistory() {
  $('nw-base-go')?.addEventListener('click', runBaseNw);
  $('nw-history-retry')?.addEventListener('click', retryNetworthHistory);
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
  return `<div class="goals">${rows || '<div class="money-empty-sm">no goals: set a savings or debt-payoff goal</div>'}</div>
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
    : '<div class="money-empty-sm">no holdings: add a stock/fund below</div>';
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

function ageOfMoneyStatus() {
  if (!_aom) return '<span class="aom aom-error">couldn\'t load age of money <button type="button" class="btn" id="age-retry">retry</button></span>';
  if (_aom.age == null) return '<span class="aom aom-empty">age of money: not enough data</span>';
  return `<span class="aom" title="days between income arriving and being spent">age of money: ${esc(_aom.age)}d</span>`;
}

function envelopeHeading() {
  return `<h3 tabindex="-1">envelope budgeting<span id="money-age-content" role="status">${ageOfMoneyStatus()}</span></h3>`;
}

function envelopeCard() {
  const e = _envelope;
  if (!e) return _canonicalLedger
    ? `<div class="money-empty-sm" role="status">couldn't load Actual's budget month <button type="button" class="btn" id="env-retry">retry</button></div>`
    : `<div class="money-empty-sm" role="status">couldn't load envelope data; reload Finance to try again</div>`;
  const tbb = e.to_be_budgeted || 0;
  const banner = `<div class="env-tbb ${tbb < 0 ? 'over' : (tbb > 0 ? 'pos' : '')}">
    <span class="env-tbb-num">${signed(tbb)}</span><span class="env-tbb-lbl">to be budgeted</span></div>`;
  const pending = _canonicalLedger ? (e.pending_assignments || []) : [];
  const rows = (e.categories || []).filter(c => _canonicalLedger || c.assigned || c.spent || c.available || c.target).map(c => {
    const av = c.available || 0;
    const pendingWrite = pending.find(item => item.category_id === c.category_id);
    const label = _canonicalLedger && c.group ? `${c.group} / ${c.category}` : c.category;
    const tgt = c.target ? (_canonicalLedger
      ? `<div class="env-target-note"><span>target ${fmt(c.target.amount)}${c.target.date ? ` by ${esc(c.target.date)}` : ''} · ${Math.round((c.target.funded || 0) * 100)}% funded</span>${c.target.id ? `<button type="button" class="btn env-move-target" data-target-id="${esc(c.target.id)}">change category</button>` : ''}</div>`
      : `<div class="env-target"><div class="env-target-bar" style="width:${Math.min(100, (c.target.funded || 0) * 100)}%"></div><span class="env-target-lbl">${Math.round((c.target.funded || 0) * 100)}% of ${fmt(c.target.amount)}${c.target.date ? ` by ${esc(c.target.date)}` : ''}</span></div>`) : '';
    return `<div class="env-row" data-cat="${esc(c.category)}" data-category-id="${esc(c.category_id || '')}">
      <div class="env-cat"><span class="env-cat-name" title="${esc(label)}">${esc(label)}</span><button type="button" class="env-tgt-btn" data-cat="${esc(c.category)}" data-category-id="${esc(c.category_id || '')}" aria-label="${c.target ? 'edit' : 'set'} funding target for ${esc(label)}">${c.target ? 'edit target' : 'set target'}</button></div>
      ${pendingWrite ? `<span class="env-assigned" title="save not confirmed">${fmt(c.assigned || 0)}</span>` : `<label class="env-assignment"><span class="env-input-label">assigned</span><input type="text" class="settings-input env-assign" data-cat="${esc(c.category)}" data-category-id="${esc(c.category_id || '')}" data-expected="${c.assigned || 0}" value="${c.assigned || 0}" inputmode="decimal" aria-label="assigned this month for ${esc(label)}"></label>`}
      <span class="env-spent" title="spent this month"><span class="sr-only">spent this month: </span><span class="env-stat-label" aria-hidden="true">spent </span>${fmt(c.spent || 0)}</span>
      <span class="env-avail ${av < 0 ? 'neg' : 'pos'}" title="available (rolls over)"><span class="sr-only">available: </span><span class="env-stat-label" aria-hidden="true">available </span>${fmt(av)}</span>
      ${pendingWrite ? `<div class="env-pending" role="status">save not confirmed for ${esc(label)}. <button type="button" class="btn" data-env-retry="${esc(c.category_id)}" data-amount="${pendingWrite.assigned}" data-expected="${pendingWrite.expected_assigned}">retry the same amount</button></div>` : ''}
      ${tgt}
    </div>`;
  }).join('');
  if (_canonicalLedger) {
    const unbound = (e.unbound_targets || []).map(target => `<div class="env-unbound-row" data-target-id="${esc(target.id)}"><span>${esc(target.category)} · ${fmt(target.amount)}${target.date ? ` by ${esc(target.date)}` : ''}</span><button type="button" class="btn env-bind-target" data-target-id="${esc(target.id)}">choose category</button></div>`).join('');
    return banner + `<p class="money-recurring-note">assignments use Actual. spending caps and funding targets stay separate.</p><div id="env-save-status" role="status" class="env-save-status"></div><div id="env-target-status" role="status" class="env-target-status">${esc(_targetStatus)}</div>` +
    (rows ? `<div class="env-rows"><div class="env-row env-head" aria-hidden="true"><span>category</span><span>assigned</span><span>spent</span><span>available</span></div>${rows}</div>`
      : '<div class="money-empty-sm">no spending categories yet. add a categorized transaction first</div>') +
      (unbound ? `<section class="env-unbound"><h4>targets needing a category</h4><p>these old targets are saved, but their Actual category isn't known. choose one to use each target.</p>${unbound}</section>` : '');
  }
  return banner + (rows
    ? `<div class="env-rows">${rows}</div>`
    : '<div class="money-empty-sm">assign money to a category to start budgeting</div>') +
    `<div class="env-add"><input type="text" id="env-new-cat" class="settings-input" placeholder="category" style="flex:1"><input type="text" id="env-new-amt" class="settings-input" placeholder="assign" inputmode="decimal" style="width:90px"><button class="btn" id="env-assign-btn">assign</button></div>`;
}

function budgetsList() {
  if (!_budgets.length) return '<div class="money-empty-sm">no spending caps yet</div>';
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
  if (!_rules.length) return '<div class="money-empty-sm">no rules: auto-tag a payee to a category</div>';
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

const _cycleShort = { weekly: '/wk', monthly: '/mo', quarterly: '/qtr', yearly: '/yr', custom: '·custom', actual: '·Actual' };

function _recurringChoiceLabel(options, value, empty = '') {
  if (!value) return empty;
  const row = options.find(option => option.id === value);
  if (!row) return 'unavailable';
  return options.filter(option => option.name === row.name).length > 1
    ? `${row.name} (${row.id.slice(-6)})` : row.name;
}

function _recurringEditForm(r) {
  const edit = _recurringEdit;
  if (!edit || edit.id !== r.id || !r.editable) return '';
  if (edit.loading) return '<div class="recur-edit-state" role="status">loading edit choices…</div>';
  if (!edit.options) return `<div class="recur-edit-state" role="alert">${esc(edit.status)} <button type="button" class="btn" data-retry-open-rec="${esc(r.id)}">retry</button></div>`;
  const draft = edit.draft;
  const options = edit.options;
  const choice = (field, label, list, empty = '') => `<div class="recur-field"><span id="rce-${field}-label">${label}</span><button type="button" class="btn recur-edit-choice" data-rec-choice="${field}" data-choice-id="${esc(draft[field])}" aria-labelledby="rce-${field}-label rce-${field}-choice" id="rce-${field}-choice">${esc(_recurringChoiceLabel(list, draft[field], empty))}</button></div>`;
  return `<div class="recur-edit" id="rce-panel" role="group" tabindex="-1" aria-busy="${edit.saving}" aria-label="edit ${esc(r.payee || 'recurring')} schedule">
    <div class="recur-form recur-form-canonical recur-edit-fields" ${edit.saving ? 'inert' : ''}>
      ${choice('account_id', 'account', options.accounts)}
      ${choice('payee_id', 'payee', options.payees)}
      ${choice('category_id', 'category', options.categories, 'no category')}
      <div class="recur-field"><span id="rce-sign-label">type</span><div class="settings-input custom-select" id="rce-sign" aria-labelledby="rce-sign-label" data-value="${draft.sign}" data-options="-|expense;+|income"></div></div>
      <label class="recur-field" for="rce-amount"><span>amount</span><input type="text" class="settings-input" id="rce-amount" value="${esc(draft.amountText)}" inputmode="decimal"></label>
      <div class="recur-field"><span id="rce-cycle-label">repeat</span><div class="settings-input custom-select" id="rce-cycle" aria-labelledby="rce-cycle-label" data-value="${esc(draft.cycle)}" data-options="daily|daily;weekly|weekly;monthly|monthly;quarterly|quarterly;yearly|yearly;custom|every n days"></div></div>
      <label class="recur-field" for="rce-days" ${draft.cycle === 'custom' ? '' : 'hidden'}><span>days between</span><input type="text" class="settings-input" id="rce-days" value="${esc(draft.cycle_days)}" inputmode="numeric"></label>
      <div class="recur-field"><span id="rce-date-label">next date</span><div class="date-input" id="rce-date" aria-labelledby="rce-date-label" data-type="date" data-value="${esc(draft.next_date)}" data-ph="next date"></div></div>
      <label class="recur-edit-active" for="rce-active"><span>auto-post</span><button type="button" id="rce-active" class="s-switch ${draft.active ? 'on' : ''}" role="switch" aria-checked="${draft.active}" aria-label="auto-post" ${edit.saving ? 'disabled' : ''}></button></label>
      <label class="recur-field recur-edit-notes" for="rce-notes"><span>notes</span><input type="text" class="settings-input" id="rce-notes" value="${esc(draft.notes)}"></label>
    </div>
    <div class="recur-edit-actions"><button type="button" class="btn primary" id="rce-save" ${edit.saving || edit.blocked ? 'disabled' : ''}>${edit.saving ? 'saving…' : 'save changes'}</button><button type="button" class="btn" id="rce-cancel" ${edit.saving ? 'disabled' : ''}>cancel</button>${edit.blocked ? '<button type="button" class="btn" id="rce-check">check schedule</button>' : ''}</div>
    ${edit.status ? `<p class="money-recurring-error" role="alert">${esc(edit.status)}</p>` : ''}
  </div>`;
}

function recurringList() {
  if (_recurringError) return '<div class="money-empty-sm money-history-error" role="status">couldn\'t load schedules <button type="button" class="btn" id="recurring-retry">retry</button></div>';
  const status = _recurringStatus ? `<p class="money-recurring-error" role="status">${esc(_recurringStatus)}</p>` : '';
  if (!_recurring.length) return status + `<div class="money-empty-sm">${_canonicalLedger ? 'no auto-post schedules in Actual' : 'nothing recurring: add rent, salary, a loan…'}</div>`;
  return `${status}<div class="recurs">` + _recurring.map(r => `
    <div class="recur-group" data-id="${esc(r.id)}"><div class="recur ${r.active || r.repair_pending || r.posting_pending || r.create_pending || r.edit_pending || r.delete_pending || (_canonicalLedger && r.editable) ? '' : 'paused'}">
      <span class="rc-payee">${esc(r.payee) || esc(r.category) || '—'}</span>
      <span class="rc-amt ${r.amount == null ? '' : r.amount >= 0 ? 'pos' : 'neg'}">${r.amount == null ? (r.amount_kind === 'range' ? 'range' : 'varies') : `${r.amount_kind === 'approx' ? '≈' : ''}${signed(r.amount)}`}<span class="rc-cyc">${_cycleShort[r.cycle] || ''}</span></span>
      <span class="rc-next" title="${r.create_pending ? 'creation pending' : r.edit_pending ? 'edit pending' : r.delete_pending ? 'deletion pending' : r.next_date ? `next post ${esc(r.next_date)}` : 'next date unavailable'}">${r.create_pending || r.edit_pending || r.delete_pending ? 'pending' : r.active ? (r.next_date ? esc(r.next_date.slice(5)) : 'unknown') : (_canonicalLedger ? 'inactive' : 'paused')}</span>
      ${_canonicalLedger && r.manageable && !r.edit_pending && _recurringEdit?.id !== r.id ? `<button type="button" class="btn rc-toggle" data-toggle-rec="${esc(r.id)}">${r.posting_pending ? `retry ${r.posting_target_active ? 'resume' : 'pause'}` : r.active ? 'pause' : 'resume'}</button>` : ''}
      ${_canonicalLedger && r.editable ? `<button type="button" class="btn rc-edit" data-edit-rec="${esc(r.id)}" aria-label="edit ${esc(r.payee || 'recurring')} schedule" aria-expanded="${_recurringEdit?.id === r.id}" ${_recurringEdit?.id === r.id && _recurringEdit.options ? 'aria-controls="rce-panel"' : ''} ${_recurringEdit && (_recurringEdit.id !== r.id || _recurringEdit.saving) ? 'disabled' : ''}>edit</button>` : ''}
      ${_canonicalLedger && r.editable && !_recurringEdit ? `<button type="button" class="btn rc-delete" data-del-rec="${esc(r.id)}" aria-label="delete ${esc(r.payee || 'recurring')} schedule">delete</button>` : ''}
      ${_canonicalLedger ? '' : `<button class="btn rc-toggle" data-toggle-rec="${esc(r.id)}" title="${r.active ? 'pause' : 'resume'}">${r.active ? 'pause' : 'resume'}</button>
      <button class="tx-del" data-del-rec="${esc(r.id)}" title="delete">×</button>`}
    </div>${_recurringEditForm(r)}${_canonicalLedger && r.create_pending ? `<div class="recur-repair" role="status"><span>${r.create_needs_review ? 'creation marker missing in Actual. review the schedule there before trying again.' : 'creation not confirmed. retry the saved schedule; this will not start another one.'}</span>${r.create_needs_review ? '' : `<button type="button" class="btn" data-retry-create-rec="${esc(r.id)}">retry creation</button>`}</div>` : ''}${_canonicalLedger && r.edit_pending ? `<div class="recur-repair" role="status"><span>${r.edit_needs_review ? "couldn't match this edit in Actual. review the schedule there before retrying." : 'edit not confirmed; Actual may be paused. retry the saved edit.'}</span>${r.edit_needs_review ? '' : `<button type="button" class="btn" data-retry-edit-rec="${esc(r.id)}">retry edit</button>`}</div>` : ''}${_canonicalLedger && r.delete_pending ? `<div class="recur-repair" role="status"><span>${r.delete_needs_review ? "couldn't match this schedule in Actual. review it before retrying deletion." : 'deletion not confirmed. retry the saved deletion; past transactions stay.'}</span>${r.delete_needs_review ? '' : `<button type="button" class="btn" data-retry-delete-rec="${esc(r.id)}">retry deletion</button>`}</div>` : ''}${_canonicalLedger && r.repair_needed ? `<div class="recur-repair"><span>${r.repair_pending ? 'repair incomplete; Actual may be paused. retry the saved category.' : 'this old schedule still posts without a guarded category and notes rule.'}</span><button type="button" class="btn" data-repair-rec="${esc(r.id)}">${r.repair_pending ? 'retry repair' : 'repair posting'}</button></div>` : ''}${_canonicalLedger && r.posting_pending ? `<div class="recur-repair"><span>${r.posting_target_active ? 'resume' : 'pause'} not confirmed; Actual may have changed. retry the saved action.</span></div>` : ''}</div>`).join('') + `</div>`;
}

function _recurringForm() {
  if (_recurringError) return '';
  if (!_accounts.length) return '';
  if (_canonicalLedger && _recurring.some(row => row.create_pending)) return '<p class="money-recurring-note">finish the pending schedule before adding another.</p>';
  const availableAccounts = _canonicalLedger ? _accounts.filter(a => !a.archived) : _accounts;
  if (!availableAccounts.length) return _canonicalLedger ? '<p class="money-recurring-note">open an Actual account before adding a schedule.</p>' : '';
  const acctOpts = availableAccounts.map(a => `${a.id}|${(a.name || '').replace(/[;|]/g, '')}`).join(';');
  const first = availableAccounts[0]?.id || '';
  if (_canonicalLedger) return `<div class="recur-form recur-form-canonical" role="group" aria-label="add recurring schedule">
    <label class="recur-field" for="rc-payee"><span>payee</span><input type="text" id="rc-payee" class="settings-input" placeholder="e.g. rent" autocomplete="off"></label>
    <div class="recur-field"><span id="rc-category-label">category</span><button type="button" class="btn rc-category-choice" id="rc-category-choice" aria-labelledby="rc-category-label rc-category-choice" data-category-id="">no category</button></div>
    <div class="recur-field"><span id="rc-sign-label">type</span><div class="settings-input custom-select" id="rc-sign" aria-labelledby="rc-sign-label" data-value="-" data-options="-|expense;+|income"></div></div>
    <label class="recur-field" for="rc-amt"><span>amount</span><input type="text" id="rc-amt" class="settings-input" placeholder="0.00" inputmode="decimal"></label>
    <div class="recur-field"><span id="rc-cycle-label">repeat</span><div class="settings-input custom-select" id="rc-cycle" aria-labelledby="rc-cycle-label" data-value="monthly" data-options="weekly|weekly;monthly|monthly;quarterly|quarterly;yearly|yearly"></div></div>
    <div class="recur-field"><span id="rc-next-label">first date</span><div class="date-input" id="rc-next" aria-labelledby="rc-next-label" data-type="date" data-value="${_today()}" data-ph="first date"></div></div>
    <div class="recur-field"><span id="rc-acct-label">account</span><div class="settings-input custom-select" id="rc-acct" aria-labelledby="rc-acct-label" data-value="${esc(first)}" data-options="${esc(acctOpts)}"></div></div>
    <button type="button" class="btn primary" id="rc-add">add schedule</button>
  </div><p class="money-recurring-note">new schedules post in Actual. eligible linked guarded schedules can be edited or deleted here.</p>`;
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
  const tags = (t.tags || '').split(',').filter(Boolean)
    .map(tg => `<button type="button" class="tx-tag" data-tag="${esc(tg)}" aria-label="filter by ${esc(tg)}">${esc(tg)}</button>`).join('');
  const canSplit = (t.amount || 0) < 0;  // only an expense divides across categories (matches the api)
  const actions = xf ? '' : `<span class="tx-actions">
    <button type="button" class="tx-edit" data-edit-txn="${t.id}" aria-label="edit ${esc(t.payee || 'transaction')}">edit</button>
    <button class="tx-clear ${t.cleared ? 'on' : ''}" data-clear-txn="${t.id}" title="${t.cleared ? 'cleared' : 'mark cleared'}">${t.cleared ? '✓' : '○'}</button>
    ${canSplit ? `<button class="tx-split-btn ${t.split ? 'on' : ''}" data-split-txn="${t.id}" title="split across categories">${t.split ? '⊟' : '⊞'}</button>` : ''}
    ${t.receipt_id
      ? `<a class="tx-receipt" href="/api/uploads/${esc(t.receipt_id)}" target="_blank" rel="noopener" title="view receipt">📎</a>`
      : `<button class="tx-receipt-btn" data-receipt-txn="${t.id}" title="attach receipt">📎</button>`}
  </span>`;
  return `
    <div class="txn ${xf ? 'is-transfer' : ''}" data-id="${t.id}">
      <span class="tx-date">${(t.date || '').slice(5)}</span>
      <span class="tx-payee">${esc(t.payee) || '<span class="tx-dim">—</span>'}</span>
      <span class="tx-cat">${xf ? '⇄ transfer' : (t.category ? esc(t.category) : '')}</span>
      ${xf ? '' : `<span class="tx-tags">${tags}</span>`}
      <span class="tx-acct">${esc(an[t.account_id] || '')}</span>
      <span class="tx-amt ${t.amount >= 0 ? 'pos' : 'neg'}">${signed(t.amount)}</span>
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
    <input type="text" id="bf-cat" class="settings-input" placeholder="${_canonicalLedger ? 'Actual category' : 'category'}" style="flex:1;min-width:110px">
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
  ['txn-search', 'txn-min', 'txn-max'].forEach(id => $(id)?.addEventListener('input', () => {
    clearTimeout(_searchTimer); _searchTimer = setTimeout(applySearch, 220);
  }));
  _wireTxnRows();
  $('money-body').querySelectorAll('[data-del-acct]').forEach(b => b.addEventListener('click', () => delAccount(b.dataset.delAcct)));
  $('money-body').querySelectorAll('[data-rc-acct]').forEach(b => b.addEventListener('click', () => toggleReconcile(b.dataset.rcAcct)));
  $('money-body').querySelectorAll('[data-rc-run]').forEach(b => b.addEventListener('click', () => runReconcile(b.dataset.rcRun)));
  $('money-body').querySelectorAll('[data-del-budget]').forEach(b => b.addEventListener('click', () => delBudget(b.dataset.delBudget)));
  wireRecurring();
  $('rl-add')?.addEventListener('click', addRule);
  $('rl-cat')?.addEventListener('keydown', e => { if (e.key === 'Enter') addRule(); });
  $('rules-apply')?.addEventListener('click', applyRules);
  $('money-body').querySelectorAll('[data-del-rule]').forEach(b => b.addEventListener('click', () => delRule(b.dataset.delRule)));
}

async function retryRecurring(focusId = '') {
  const button = $('recurring-retry');
  if (button) {
    button.disabled = true;
    button.textContent = 'retrying…';
  }
  await readRecurring(api);
  const content = $('recurring-content');
  if (!content) return;
  content.innerHTML = `<div id="recurring-list">${recurringList()}</div>` + _recurringForm();
  wireRecurring();
  const action = focusId ? [...content.querySelectorAll('[data-toggle-rec], [data-del-rec], [data-retry-create-rec], [data-retry-edit-rec], [data-retry-delete-rec]')].find(b => b.dataset.toggleRec === focusId || b.dataset.delRec === focusId || b.dataset.retryCreateRec === focusId || b.dataset.retryEditRec === focusId || b.dataset.retryDeleteRec === focusId) : null;
  (action || $('recurring-retry') || document.querySelector('.money-card[data-card="recurring"] h3'))?.focus();
}

function wireRecurring() {
  wireRecurringList();
  document.querySelectorAll('#recurring-content .custom-select').forEach(initCustomDropdown);
  document.querySelectorAll('#recurring-content .date-input').forEach(initDatePicker);
  $('rc-add')?.addEventListener('click', addRecurring);
  $('rc-category-choice')?.addEventListener('click', chooseRecurringCategory);
}

function wireRecurringList() {
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
    _recurringEdit.status = `couldn't load edit choices: ${error.message || 'try again'}`;
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
    ...(field === 'category_id' ? [{ value: '', label: 'no category' }] : []),
    ...list.map(row => ({ value: row.id, label: _recurringChoiceLabel(list, row.id) })),
  ];
  const picked = await dlgChoose(`choose ${field === 'category_id' ? 'category' : field === 'payee_id' ? 'payee' : 'account'}`, options);
  if (picked === null || _recurringEdit !== edit) return;
  edit.draft[field] = picked;
  button.dataset.choiceId = picked;
  button.textContent = options.find(option => option.value === picked)?.label || 'no category';
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
      edit.status = 'no pending edit found. check the values before saving again.';
      _drawRecurringEdit('#rce-save');
    }
  } catch {
    if (_recurringEdit !== edit) return;
    edit.blocked = true;
    edit.status = "couldn't check the schedule. don't save again until a check succeeds.";
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
    toast('enter an amount with at most two decimal places', 'error'); return;
  }
  if (!calendarDateParts(draft.next_date)) { toast('choose a valid next date', 'error'); return; }
  const customDays = String(draft.cycle_days).trim();
  const days = draft.cycle === 'custom'
    ? (/^\d+$/.test(customDays) ? Number(customDays) : NaN)
    : ({ daily: 1, weekly: 7, monthly: 30, quarterly: 91, yearly: 365 })[draft.cycle];
  if (!Number.isSafeInteger(days) || days < 1) { toast('enter a valid number of days', 'error'); return; }
  const payload = {
    account_id: draft.account_id, payee_id: draft.payee_id,
    amount: (draft.sign === '+' ? 1 : -1) * amount,
    category_id: draft.category_id, notes: draft.notes,
    cycle: draft.cycle, cycle_days: days, next_date: draft.next_date, active: draft.active,
  };
  edit.saving = true;
  edit.status = '';
  _drawRecurringEdit('#rce-panel');
  try {
    await api(`/api/money/recurring/${encodeURIComponent(edit.id)}/edit`, { method: 'POST', body: payload });
    if (_recurringEdit !== edit) return;
    _recurringEdit = null;
    _recurringStatus = '';
    await retryRecurring(edit.id);
  } catch (error) {
    if (_recurringEdit !== edit) return;
    edit.saving = false;
    edit.status = `edit not confirmed: ${error.message || 'check the schedule'}`;
    await checkRecurringEdit();
  }
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

export async function applySearch() {
  const q = $('txn-search')?.value.trim() || '';
  const mn = $('txn-min')?.value.trim() || '';
  const mx = $('txn-max')?.value.trim() || '';
  if (!q && !mn && !mx) {   // nothing to filter → back to the plain month list
    _searchResults = null;
    _tagFilter = '';
    const rows = $('txn-rows'); if (rows) { rows.innerHTML = txnList(); _wireTxnRows(); }
    return;
  }
  _tagFilter = '';
  const p = new URLSearchParams({ month: _month });
  if (q) p.set('q', q);
  if (!_validAmounts(_decimal(mn, 0), _decimal(mx, 0))) return;
  if (mn) p.set('min_amt', _decimal(mn));
  if (mx) p.set('max_amt', _decimal(mx));
  try {
    _searchResults = await api(`/api/money/transactions/search?${p}`);
  } catch { _searchResults = []; }
  const rows = $('txn-rows'); if (rows) { rows.innerHTML = txnList(); _wireTxnRows(); }
}

// ── actions ────────────────────────────────────────────────────────────────
async function addAccount() {
  const name = $('af-name')?.value.trim();
  if (!name) { toast('name the account', 'error'); return; }
  const opening = _decimal($('af-open')?.value, 0);
  const low_balance = _decimal($('af-low')?.value, 0);
  if (!_validAmounts(opening, low_balance)) return;
  let requestId = '';
  try {
    const accountPayload = { name, kind: getDropdownValue($('af-kind')), opening, low_balance };
    requestId = await _createRequestId('account', accountPayload);
    accountPayload.request_id = requestId;
    await api('/api/money/accounts', { method: 'POST', body: accountPayload });
    _completeCreateRequest('account', requestId);
    await load();
  } catch {
    if (requestId) _releaseCreateRequest('account', requestId);
    toast('couldn\'t add account', 'error');
  }
}
async function delAccount(id) {
  if (!await dlgConfirm('delete this account and all its transactions?')) return;
  try { await api(`/api/money/accounts/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function addTxn() {
  const amtRaw = _decimal($('tx-amt')?.value);
  if (!_validAmounts(amtRaw)) return;
  if (!amtRaw || amtRaw <= 0) { toast('enter an amount', 'error'); return; }
  const sign = getDropdownValue($('tx-sign')) === '+' ? 1 : -1;
  let requestId = '';
  try {
    const transactionPayload = {
      account_id: getDropdownValue($('tx-acct')), date: $('tx-date')?.dataset.value || _today(),
      amount: sign * amtRaw, category: $('tx-cat').value.trim(), payee: $('tx-payee').value.trim(),
      tags: $('tx-tags')?.value.trim() || '',
    };
    requestId = await _createRequestId('transaction', transactionPayload);
    transactionPayload.request_id = requestId;
    await api('/api/money/transactions', { method: 'POST', body: transactionPayload });
    _completeCreateRequest('transaction', requestId);
    await load();
  } catch {
    if (requestId) _releaseCreateRequest('transaction', requestId);
    toast('couldn\'t add transaction', 'error');
  }
}
async function delTxn(id) {
  if (!await dlgConfirm('delete this transaction?')) return;
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
export async function filterByTag(tag) {
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
  const v = _decimal($(`rc-stmt-${aid}`)?.value);
  const out = $(`rc-out-${aid}`); if (!out) return;
  if (!Number.isFinite(v)) { out.className = 'rc-out bad'; out.textContent = 'enter a statement balance using a decimal point, e.g. 1234.56'; return; }
  try {
    const d = await api(`/api/money/accounts/${aid}/reconcile?statement=${v}`);
    out.className = 'rc-out ' + (d.reconciled ? 'ok' : 'bad');
    out.textContent = d.reconciled
      ? `✓ reconciled: cleared ${fmt(d.cleared_balance)}`
      : `cleared ${fmt(d.cleared_balance)} · off by ${fmt(Math.abs(d.difference))}`;
  } catch { out.textContent = 'failed'; }
}
async function doTransfer() {
  const from = getDropdownValue($('tr-from')), to = getDropdownValue($('tr-to'));
  const amt = _decimal($('tr-amt')?.value);
  if (!_validAmounts(amt)) return;
  if (!amt || amt <= 0) { toast('enter an amount', 'error'); return; }
  if (from === to) { toast('pick two different accounts', 'error'); return; }
  let requestId = '';
  try {
    const transferPayload = {
      from_account: from, to_account: to, amount: amt, date: $('tr-date')?.dataset.value || _today(),
    };
    requestId = await _createRequestId('transfer', transferPayload);
    transferPayload.request_id = requestId;
    await api('/api/money/transfer', { method: 'POST', body: transferPayload });
    _completeCreateRequest('transfer', requestId);
    toast('transferred', 'success');
    await load();
  } catch {
    if (requestId) _releaseCreateRequest('transfer', requestId);
    toast('transfer failed', 'error');
  }
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
  const amtRaw = _decimal(f('amount')?.value);
  if (!_validAmounts(amtRaw)) return;
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
  const target = _decimal($('gl-target')?.value, 0);
  const current = _decimal($('gl-current')?.value, 0);
  const monthly = _decimal($('gl-monthly')?.value, 0);
  if (!_validAmounts(target, current, monthly)) return;
  try {
    await api('/api/money/goals', { method: 'POST', body: {
      name, kind: getDropdownValue($('gl-kind')) || 'savings',
      target, current, monthly,
    } });
    await load();
  } catch { toast('add failed', 'error'); }
}
async function delGoal(id) {
  if (!await dlgConfirm('delete this goal?')) return;
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
    out.textContent = `${formatNumber(d.net_worth, { minimumFractionDigits: 2 })} ${d.base}`;
  } catch { out.textContent = 'fx failed'; }
}
async function addHolding() {
  const symbol = $('hd-sym')?.value.trim();
  if (!symbol) { toast('enter a symbol', 'error'); return; }
  const qty = _decimal($('hd-qty')?.value, 0);
  const cost_basis = _decimal($('hd-cost')?.value, 0);
  const price = _decimal($('hd-price')?.value, 0);
  if (!_validAmounts(qty, cost_basis, price)) return;
  try {
    await api('/api/money/holdings', { method: 'POST', body: {
      symbol, qty, cost_basis, price,
    } });
    await load();
  } catch { toast('add failed', 'error'); }
}
async function delHolding(id) {
  if (!await dlgConfirm('delete this holding?')) return;
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
async function assignEnvelope(category, amount, categoryId = '', expectedAmount = null) {
  category = (category || '').trim();
  if (!category && !_canonicalLedger) { toast('name a category', 'error'); return false; }
  amount = _decimal(amount, 0);
  if (!_validAmounts(amount)) return false;
  const key = `${_month}:${categoryId || category}`;
  if (_envAssignmentBusy.has(key)) return false;
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
      card.innerHTML = envelopeHeading() + envelopeCard(); _wireEnvelope();
      [...card.querySelectorAll('.env-assign')]
        .find(input => input.dataset.categoryId === categoryId)?.focus();
      if (!_envelope) card.querySelector('#env-retry')?.focus();
    }
    return true;
  } catch (error) {
    const status = $('env-save-status');
    if (status) {
      const stale = error?.message?.includes('changed; reload');
      status.textContent = stale
        ? 'assignment changed. reload Finance before saving again.'
        : 'save not confirmed. keep this amount and retry the same save.';
      if (!stale) {
        status.insertAdjacentHTML('beforeend', '<button type="button" class="btn" data-env-retry-save>retry same amount</button>');
        status.querySelector('[data-env-retry-save]').addEventListener(
          'click', () => assignEnvelope(category, amount, categoryId, expectedAmount),
        );
      }
    } else toast('assign failed', 'error');
    return false;
  } finally { _envAssignmentBusy.delete(key); }
}

async function retryAgeOfMoney() {
  const button = $('age-retry');
  button.disabled = true;
  button.textContent = 'retrying…';
  try { _aom = await api('/api/money/age-of-money'); }
  catch { _aom = null; }
  const content = $('money-age-content');
  if (!content) return;
  content.innerHTML = ageOfMoneyStatus();
  (_aom ? content.closest('h3') : $('age-retry'))?.focus();
}

async function retryEnvelope() {
  const button = $('env-retry');
  button.disabled = true;
  button.textContent = 'retrying…';
  try { _envelope = await api(`/api/money/envelope?month=${_month}`); }
  catch { _envelope = null; }
  const card = $('money-body').querySelector('.money-envelope');
  if (!card) return;
  card.innerHTML = envelopeHeading() + envelopeCard();
  _wireEnvelope();
  (_envelope ? card.querySelector('h3') : $('env-retry'))?.focus();
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
  const v = await dlgFields(`funding target for ${label} (0 clears it)`, [
    { id: 'amount', label: 'target amount', value: draft.amount ?? current?.target?.amount ?? '' },
    { id: 'date', label: 'by date (YYYY-MM-DD, optional)', value: draft.date ?? current?.target?.date ?? '' },
  ]);
  if (!v) return;
  const amount = _decimal(v.amount, 0);
  if (!_validAmounts(amount)) return;
  if (_canonicalLedger && amount < 0) { toast('use 0 to clear a target', 'error'); return; }
  try {
    await api('/api/money/envelope/target', { method: 'PUT', body: { category, category_id: categoryId, amount, target_date: (v.date || '').trim() } });
    _targetDrafts.delete(draftKey);
    _targetStatus = '';
    await load();
    [...document.querySelectorAll('.env-tgt-btn')].find(button => _canonicalLedger
      ? button.dataset.categoryId === categoryId : button.dataset.cat === category)?.focus();
  } catch {
    _targetDrafts.set(draftKey, { amount: v.amount, date: v.date });
    _targetStatus = `couldn't save the target for ${label}. reopen it to retry; your values are kept.`;
    if ($('env-target-status')) $('env-target-status').textContent = _targetStatus;
    else toast('couldn\'t save target', 'error');
  }
}
async function bindEnvTarget(targetId) {
  const unbound = (_envelope?.unbound_targets || []).find(row => row.id === targetId);
  const bound = (_envelope?.categories || []).find(row => row.target?.id === targetId);
  if (!unbound && !bound) return;
  const label = unbound ? unbound.category : (bound.group ? `${bound.group} / ${bound.category}` : bound.category);
  const categories = (_envelope?.categories || []).filter(row => !row.target);
  if (!categories.length) { toast('no unused spending category is available', 'error'); return; }
  const names = categories.map(row => row.group ? `${row.group} / ${row.category}` : row.category);
  const selected = await dlgChoose(`choose the category for ${label}`, categories.map((row, index) => ({
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
    _targetStatus = `couldn't change the category for ${label}. the target is still saved; try again.`;
    if ($('env-target-status')) $('env-target-status').textContent = _targetStatus;
  }
}
async function addBudget() {
  const category = $('bf-cat')?.value.trim();
  const limit_amt = _decimal($('bf-amt')?.value, 0);
  if (!_validAmounts(limit_amt)) return;
  if (!category) { toast('pick a category', 'error'); return; }
  try { await api('/api/money/budgets', { method: 'POST', body: { category, limit_amt } }); await load(); }
  catch (error) { toast(error.message?.includes('budget cap requires one existing spending category') ? 'use one existing spending category in Actual' : 'couldn\'t set spending cap', 'error'); }
}
async function delBudget(id) {
  if (!await dlgConfirm('remove this spending cap?')) return;
  try { await api(`/api/money/budgets/${id}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function addRecurring() {
  const payee = $('rc-payee')?.value.trim();
  const amtRaw = _decimal($('rc-amt')?.value);
  if (!_validAmounts(amtRaw)) return;
  if (!payee && _canonicalLedger) { toast('give it a payee', 'error'); return; }
  if (!payee && !$('rc-cat')?.value.trim()) { toast('give it a payee or category', 'error'); return; }
  if (!amtRaw || amtRaw <= 0) { toast('enter an amount', 'error'); return; }
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
  if (button) { button.disabled = true; button.textContent = 'saving…'; }
  try {
    if (_canonicalLedger) {
      requestId = await _createRequestId('recurring', payload);
      payload.request_id = requestId;
    }
    await api('/api/money/recurring', { method: 'POST', body: payload });
    if (requestId) _completeCreateRequest('recurring', requestId);
    await load();
  } catch (error) {
    if (requestId) _releaseCreateRequest('recurring', requestId);
    if (_canonicalLedger) {
      _recurringStatus = `creation not confirmed: ${error.message || 'retry the saved schedule'}`;
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
    } else toast('couldn\'t add recurring', 'error');
    if (button) { button.disabled = false; button.textContent = _canonicalLedger ? 'add schedule' : 'add'; }
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
    _recurringStatus = 'could not load Actual categories. retry when Actual is available.';
    const list = $('recurring-list');
    if (list) { list.innerHTML = recurringList(); wireRecurringList(); }
    return;
  }
  const names = categories.map(row => row.group ? `${row.group} / ${row.category}` : row.category);
  const options = [{ value: '', label: 'no category' }, ...categories.map((row, index) => ({
    value: row.category_id,
    label: names.filter(name => name === names[index]).length > 1
      ? `${names[index]} (${row.category_id.slice(-6)})` : names[index],
  }))];
  const selected = await dlgChoose('choose a spending category', options);
  if (selected === null) return;
  button.dataset.categoryId = selected;
  button.textContent = options.find(option => option.value === selected)?.label || 'no category';
  button.focus();
}
async function retryRecurringCreate(button) {
  const r = _recurring.find(row => row.id === button.dataset.retryCreateRec);
  if (!_canonicalLedger || !r?.create_pending || r.create_needs_review || button.disabled) return;
  button.disabled = true;
  button.textContent = 'retrying…';
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/retry`, { method: 'POST' });
    _recurringStatus = '';
  } catch (error) {
    _recurringStatus = `creation not confirmed for ${r.payee}: ${error.message || 'review the schedule in Actual'}`;
  }
  await retryRecurring(r.id);
}
async function retryRecurringEdit(button) {
  const r = _recurring.find(row => row.id === button.dataset.retryEditRec);
  if (!_canonicalLedger || !r?.edit_pending || r.edit_needs_review || button.disabled) return;
  button.disabled = true;
  button.textContent = 'retrying…';
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/edit/retry`, { method: 'POST' });
    _recurringStatus = '';
  } catch (error) {
    _recurringStatus = `edit not confirmed for ${r.payee}: ${error.message || 'review the schedule in Actual'}`;
  }
  await retryRecurring(r.id);
}
async function retryRecurringDelete(button) {
  const r = _recurring.find(row => row.id === button.dataset.retryDeleteRec);
  if (!_canonicalLedger || !r?.delete_pending || r.delete_needs_review || button.disabled) return;
  button.disabled = true;
  button.textContent = 'retrying…';
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/delete/retry`, { method: 'POST' });
    _recurringStatus = '';
  } catch (error) {
    _recurringStatus = `deletion not confirmed for ${r.payee}: ${error.message || 'review the schedule in Actual'}`;
  }
  await retryRecurring(r.id);
}
async function delRecurring(id) {
  if (_canonicalLedger) {
    const r = _recurring.find(row => row.id === id);
    if (!r?.editable || _recurringEdit) return;
    if (!await dlgConfirm(`delete the ${r.payee || 'recurring'} schedule? future posts stop; past transactions stay. a backup is saved first.`)) return;
    try {
      await api(`/api/money/recurring/${encodeURIComponent(id)}/delete`, {
        method: 'POST', body: { confirm_id: id },
      });
      _recurringStatus = '';
    } catch (error) {
      _recurringStatus = `deletion not confirmed for ${r.payee}: ${error.message || 'retry the saved deletion'}`;
    }
    await retryRecurring(id);
    return;
  }
  if (!await dlgConfirm('stop this recurring transaction?')) return;
  try { await api(`/api/money/recurring/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  catch { toast('delete failed', 'error'); }
}
async function toggleRecurring(button) {
  const r = _recurring.find(x => x.id === button.dataset.toggleRec);
  if (!r || button.disabled || (_canonicalLedger && !r.manageable)) return;
  const active = r.posting_pending ? r.posting_target_active : !r.active;
  button.disabled = true;
  button.textContent = 'saving…';
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}`, { method: 'PATCH', body: { active } });
    _recurringStatus = '';
    if (_canonicalLedger) await retryRecurring(r.id);
    else await load();
  } catch (error) {
    if (_canonicalLedger) {
      _recurringStatus = `${active ? 'resume' : 'pause'} not confirmed for ${r.payee}: ${error.message || 'retry the saved action'}`;
      await retryRecurring(r.id);
    } else {
      button.disabled = false;
      button.textContent = r.active ? 'pause' : 'resume';
      toast('update failed', 'error');
    }
  }
}
async function repairRecurring(button) {
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
      _recurringStatus = 'could not load Actual categories. retry when Actual is available.';
      await retryRecurring();
      return;
    }
    const names = categories.map(row => row.group ? `${row.group} / ${row.category}` : row.category);
    const options = categories.map((row, index) => ({
      value: row.category_id,
      label: names.filter(name => name === names[index]).length > 1
        ? `${names[index]} (${row.category_id.slice(-6)})` : names[index],
    }));
    if (!r.category) options.unshift({ value: '', label: 'leave uncategorized' });
    if (!options.length) {
      _recurringStatus = 'add a spending category in Actual before repairing this schedule.';
      await retryRecurring();
      return;
    }
    categoryId = await dlgChoose(`choose the Actual category for ${r.payee}`, options);
    if (categoryId === null) return;
  }
  button.disabled = true;
  button.textContent = 'repairing…';
  try {
    await api(`/api/money/recurring/${encodeURIComponent(r.id)}/repair`, {
      method: 'POST', body: { category_id: categoryId },
    });
    _recurringStatus = '';
    await retryRecurring();
    toast('posting repaired', 'success');
  } catch (error) {
    _recurringStatus = `repair not confirmed for ${r.payee}: ${error.message || 'retry the saved choice'}`;
    await retryRecurring();
  }
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
  if (!await dlgConfirm('delete this categorization rule?')) return;
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
