import { toast } from './util.js';
import { openCaptureReview, showPendingCapture } from './capture.js';
import { readRecordTarget } from './recordlinks.js';
import { replaceRouteUrl } from './route_history.js';
import { confirm as dlgConfirm, prompt as dlgPrompt, fields as dlgFields } from './dialog.js';
import { populateDropdown, getDropdownValue } from './dropdown.js?v=212';
import { initDatePicker as _dpInit } from './datepick.js';
import { formatDate, formatTime, resolvedTimeZone } from './i18n.js';
import { reminderTimeFromWall } from './reminders.js';

// monochrome ui icons (same global as files/etc) — keeps the row controls matching the app
const _si = n => (window.icon ? window.icon(n) : '');

// ── compose recipient chips + address autocomplete (4d) ──────────────────────
const _validEmail = s => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s);
let _addrBook = null;
async function _loadAddrBook() {
  if (_addrBook) return _addrBook;
  const book = [];
  try {
    const cs = await fetch('/api/contacts').then(r => r.json());
    (Array.isArray(cs) ? cs : cs.contacts || []).forEach(c => {
      const e0 = c.email || (c.emails && c.emails[0] && (c.emails[0].value || c.emails[0])) || '';
      if (e0) book.push({ email: String(e0), name: c.name || c.full_name || '' });
    });
  } catch (e) { console.error(e); }
  try {
    const rs = (await fetch('/api/mail/recipients?limit=300').then(r => r.json())).recipients || [];
    rs.forEach(r => book.push({ email: r.email, name: r.name || '' }));
  } catch (e) { console.error(e); }
  const seen = new Set(); _addrBook = [];
  for (const e of book) { const k = (e.email || '').toLowerCase(); if (k && !seen.has(k)) { seen.add(k); _addrBook.push(e); } }
  return _addrBook;
}
let _acEl = null, _acIdx = -1, _acAdd = null;
function _hideAc() { _acEl?.remove(); _acEl = null; _acIdx = -1; _acAdd = null; }
async function _showAc(input, addFn) {
  const q = input.value.trim().toLowerCase();
  if (!q) { _hideAc(); return; }
  const book = await _loadAddrBook();
  if (!input.isConnected || document.activeElement !== input || input.value.trim().toLowerCase() !== q) return;
  const m = book.filter(e => e.email.toLowerCase().includes(q) || (e.name || '').toLowerCase().includes(q)).slice(0, 6);
  _hideAc();
  if (!m.length) return;
  _acAdd = addFn;
  _acEl = document.createElement('div'); _acEl.className = 'mc-ac';
  _acEl.innerHTML = m.map((x, i) => `<div class="mc-ac-item" data-email="${esc(x.email)}" data-i="${i}">${x.name ? `<b>${esc(x.name)}</b> ` : ''}<span>${esc(x.email)}</span></div>`).join('');
  document.body.appendChild(_acEl);
  const r = input.getBoundingClientRect();
  _acEl.style.left = r.left + 'px'; _acEl.style.top = (r.bottom + 3) + 'px'; _acEl.style.minWidth = Math.max(220, r.width) + 'px';
  _acEl.querySelectorAll('.mc-ac-item').forEach(it => it.addEventListener('mousedown', e => { e.preventDefault(); addFn(it.dataset.email); input.value = ''; _hideAc(); input.focus(); }));
}
function _acNav(e) {
  if (!_acEl) return false; e.preventDefault();
  const items = [..._acEl.querySelectorAll('.mc-ac-item')];
  _acIdx = e.key === 'ArrowDown' ? Math.min(_acIdx + 1, items.length - 1) : Math.max(_acIdx - 1, 0);
  items.forEach((it, i) => it.classList.toggle('active', i === _acIdx));
  return true;
}
function _acPick(e) {
  if (!_acEl || _acIdx < 0 || !_acAdd) return false;
  const it = _acEl.querySelectorAll('.mc-ac-item')[_acIdx];
  if (!it) return false;
  e.preventDefault(); _acAdd(it.dataset.email); _hideAc(); return true;
}
function _initChipField(wrap) {
  const chipsBox = wrap.querySelector('.mc-chips');
  const input = wrap.querySelector('.mc-chip-input');
  const hidden = wrap.querySelector('input[type=hidden]');
  let chips = [];
  const sync = () => { hidden.value = chips.join(', '); hidden.dispatchEvent(new Event('input', { bubbles: true })); };
  const render = () => {
    chipsBox.innerHTML = chips.map((c, i) => `<span class="mc-chip${_validEmail(c) ? '' : ' bad'}" title="${esc(c)}">${esc(c)}<button type="button" class="mc-chip-x" data-i="${i}">×</button></span>`).join('');
    chipsBox.querySelectorAll('.mc-chip-x').forEach(b => b.addEventListener('mousedown', e => { e.preventDefault(); chips.splice(+b.dataset.i, 1); render(); sync(); }));
  };
  const add = raw => { (raw || '').split(/[,;]+/).map(s => s.trim()).filter(Boolean).forEach(a => { if (!chips.some(c => c.toLowerCase() === a.toLowerCase())) chips.push(a); }); render(); sync(); };
  const commit = () => { const v = input.value.trim(); if (v) { add(v); input.value = ''; } _hideAc(); };
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { _acNav(e); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { if (_acPick(e)) return; if (input.value.trim()) { if (e.key !== 'Tab') e.preventDefault(); commit(); } return; }
    if (e.key === ' ' || e.key === ',' || e.key === ';') { if (input.value.trim()) { e.preventDefault(); commit(); } }
    else if (e.key === 'Backspace' && !input.value && chips.length) { input.value = chips.pop(); render(); sync(); _hideAc(); }
    else if (e.key === 'Escape') _hideAc();
  });
  input.addEventListener('blur', () => setTimeout(commit, 160));
  input.addEventListener('input', () => _showAc(input, add));
  wrap._chips = () => chips;
  wrap._add = add;
}

let _accounts = [];
let _active = localStorage.getItem('alles-mail-account-mode') || 'all';
let _filter = 'inbox';        // inbox | unread | sent
let _threads = false;   // group by conversation — driven by the mail_threads setting (4a)
const _sentFolders = {};      // account_id -> detected sent folder name
const _expanded = new Set();  // thread keys currently expanded
let _mailErrors = [];
let _lastMsgs = [];           // last rendered message set (for re-render on toggle)
let _lastSearch = '';         // last advanced-search query (5a, for the save-search button)
let _searchView = '';         // active search results view, if any
let _labelFilter = '';        // active label chip view, if any

// mirror services.mail.normalize_subject — strip re:/fwd:/aw:… so a conversation collapses
const _subjPrefix = /^(?:\s*(?:re|fwd|fw|aw|wg)\s*:\s*)+/i;
const threadKey = s => (String(s ?? '').replace(_subjPrefix, '').trim() || '(no subject)').toLowerCase();

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const MAIL_BODY_CSP = "default-src 'none'; img-src data: cid:; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; form-action 'none'";
function stripAutomaticMailNavigation(html = '') {
  const source = String(html);
  if (typeof document === 'undefined' || typeof document.createElement !== 'function') {
    return source.replace(/<meta\b[^>]*>/gi, '');
  }
  const template = document.createElement('template');
  template.innerHTML = source;
  template.content.querySelectorAll('meta[http-equiv]').forEach(meta => {
    if (meta.getAttribute('http-equiv')?.trim().toLowerCase() === 'refresh') meta.remove();
  });
  return template.innerHTML;
}
export function mailBodySrcdoc(html = '') {
  return `<meta http-equiv="Content-Security-Policy" content="${MAIL_BODY_CSP}"><style>body{font-family:system-ui,sans-serif;color:#111;background:#fff;font-size:14px;padding:8px;margin:0}</style>${stripAutomaticMailNavigation(html)}`;
}
const catchErr = msg => e => { console.error(msg || 'Error:', e); if (msg) toast(msg, 'error'); };
const fromName = f => {
  const m = /^(.*?)\s*<([^>]+)>/.exec(f || '');
  return (m ? (m[1].replace(/"/g, '').trim() || m[2]) : f) || '(unknown)';
};
const shortDate = d => { try { return formatDate(d, { month: 'short', day: 'numeric' }); } catch (e) { console.error(e); return ''; } };
const acctName = id => {
  const a = _accounts.find(x => x.id === id);
  return a ? (a.name || a.email || 'mail') : 'mail';
};

// stale-while-revalidate: IMAP is a network round-trip to your provider, so the
// first hit is never instant. cache the last list per account+folder and show it
// immediately while the fresh fetch runs in the background.
const cacheKey = () => `mail-cache-${_active}-${_filter === 'sent' ? 'sent' : 'inbox'}`;
const readCache = () => { try { return JSON.parse(localStorage.getItem(cacheKey()) || 'null'); } catch (e) { console.error(e); return null; } };
const writeCache = msgs => { try { localStorage.setItem(cacheKey(), JSON.stringify(msgs.slice(0, 40))); } catch (e) { console.error(e); } };

const PRESETS = [
  { key: 'gmail', label: 'Gmail', re: /@gmail\.com$/i, imap: 'imap.gmail.com', smtp: 'smtp.gmail.com', apppw: 'https://myaccount.google.com/apppasswords', help: 'https://support.google.com/mail/answer/7126229', note: 'Gmail needs an app password (not your normal one), and 2-step verification must be on.' },
  { key: 'outlook', label: 'Outlook', re: /@(outlook|hotmail|live)\.com$/i, imap: 'outlook.office365.com', smtp: 'smtp.office365.com', apppw: 'https://account.live.com/proofs/AppPassword', help: 'https://support.microsoft.com/office/pop-imap-and-smtp-settings', note: 'Outlook/Hotmail/Live need an app password (turn it on under account security).' },
  { key: 'icloud', label: 'iCloud', re: /@(icloud|me|mac)\.com$/i, imap: 'imap.mail.me.com', smtp: 'smtp.mail.me.com', apppw: 'https://account.apple.com/account/manage', help: 'https://support.apple.com/102525', note: 'iCloud needs an app-specific password from your Apple ID.' },
  { key: 'yahoo', label: 'Yahoo', re: /@yahoo\.com$/i, imap: 'imap.mail.yahoo.com', smtp: 'smtp.mail.yahoo.com', apppw: 'https://login.yahoo.com/account/security/app-passwords', help: 'https://help.yahoo.com/kb/SLN4075.html', note: 'Yahoo needs an app password from account security.' },
  { key: 'fastmail', label: 'Fastmail', re: /@fastmail\.com$/i, imap: 'imap.fastmail.com', smtp: 'smtp.fastmail.com', apppw: 'https://app.fastmail.com/settings/security/apppassword', help: 'https://www.fastmail.help/hc/en-us/articles/1500000278342', note: 'Create an app password in Fastmail settings (custom domains work too).' },
  { key: 'domain', label: 'Own domain', re: /@[^@\s]+\.[^@\s]+$/i, imap: '', smtp: '', apppw: '', help: '', note: 'Use your domain mailbox or self-hosted IMAP/SMTP server.' },
];

function domainFromEmail(email) {
  const m = /@([^@\s]+)$/.exec(email || '');
  return m ? m[1].toLowerCase() : '';
}

function providerForEmail(email) {
  return PRESETS.find(p => p.key !== 'domain' && p.re.test(email || '')) || null;
}

function providerHelpHtml() {
  return PRESETS.filter(p => p.key !== 'domain').map(p =>
    `<a class="mail-service-link" href="${esc(p.help)}" target="_blank" rel="noreferrer">${esc(p.label)}</a>`
  ).join('');
}

let _messageGeneration = 0;
let _mailEditor = null, _mailLeave = null, _openingDraft = null;
const _deletingDrafts = new Set();
function mailEditor() {
  if (_mailEditor?.root.isConnected) return _mailEditor;
  _mailEditor = null;
  return null;
}
function clearMailEditor(editor) {
  if (mailEditor() !== editor) return;
  _hideAc();
  editor.root.remove();
  _mailEditor = null;
}
export async function prepareMailNavigation() {
  const generation = ++_messageGeneration;
  const account = _accountEditor?.root.isConnected ? _accountEditor : null;
  if (account && ((account.snapshot() !== account.initial && account.snapshot() !== account.pendingSnapshot) || account.extraSnapshot() !== account.extraInitial)) {
    const snapshot = () => JSON.stringify([account.snapshot(), account.extraSnapshot()]);
    const leaving = snapshot();
    if (!await dlgConfirm('discard unsaved account changes?')) return false;
    if (generation !== _messageGeneration || snapshot() !== leaving) return false;
  }
  _accountEditor = null;
  const editor = mailEditor();
  if (!editor) return true;
  if (!_mailLeave) {
    const snapshot = editor.snapshot();
    _mailLeave = (async () => {
      if (snapshot !== editor.initial && !await dlgConfirm('discard unsaved draft changes?')) return false;
      if (mailEditor() !== editor || editor.snapshot() !== snapshot) return false;
      clearMailEditor(editor);
      return true;
    })().finally(() => { _mailLeave = null; });
  }
  return await _mailLeave && generation === _messageGeneration;
}
let _inited = false;
export function initMail() {
  if (_inited) return;
  _inited = true;
  window.addEventListener('beforeunload', event => {
    const editor = mailEditor();
    const account = _accountEditor?.root.isConnected ? _accountEditor : null;
    if ((editor && editor.snapshot() !== editor.initial) || (account && (account.snapshot() !== account.initial || account.extraSnapshot() !== account.extraInitial)) || _accountRecovery.pending || _oauthRecovery.pending) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  $('mail-account')?.addEventListener('change', e => {
    _active = e.target.value;
    localStorage.setItem('alles-mail-account-mode', _active);
    _reloadCurrent({ force: true });
  });
  $('mail-refresh-btn')?.addEventListener('click', () => { _renderScheduled(); _reloadCurrent({ force: true }); });
  // conversation grouping is a mail-settings toggle now (4a) — not a toolbar button
  _applyThreadsSetting();
  window._reloadMail = () => { _applyThreadsSetting().then(() => { _expanded.clear(); renderInbox(_lastMsgs); }); };
  $('mail-compose-btn')?.addEventListener('click', () => compose());
  // accounts + rules live in mail settings now (4e) — exposed for the cog popover's action buttons
  window._mailAccounts = () => accountsPanel();
  window._mailRules = () => rulesPanel();
  _initMailSidebar();
  // live search — filters as you type (Enter still works immediately)
  let _searchT;
  const _doSearch = () => { const q = ($('mail-search')?.value || '').trim(); if (q) searchMail(q); else loadInbox(); };
  $('mail-search')?.addEventListener('input', () => { clearTimeout(_searchT); _searchT = setTimeout(_doSearch, 250); });
  $('mail-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') { clearTimeout(_searchT); _doSearch(); } });
}

async function _applyThreadsSetting() {
  try { _threads = (await fetch('/api/settings').then(r => r.json())).mail_threads === 'group'; } catch (e) { console.error(e); }
}

let _listGeneration = 0, _mailLoadGeneration = 0, _listContext = '';
async function mailJson(url, options = {}, fetcher = fetch) {
  const response = await fetcher(url, options);
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data?.message || data?.detail?.message || (typeof data?.detail === 'string' ? data.detail : 'mail is unavailable')), { status: response.status });
  return data;
}
function preserveMailReadFocus(list) {
  const label = node => node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent.trim();
  const describe = node => {
    if (!list.contains(node)) return null;
    const row = node.closest('.mail-row');
    return { id: node.id, label: label(node), row: row && Object.fromEntries(['aid', 'uid', 'folder', 'id', 'thread'].map(key => [key, row.dataset[key] || ''])) };
  };
  const initial = describe(document.activeElement);
  return render => {
    const focus = describe(document.activeElement) || (document.activeElement === document.body ? initial : null);
    render();
    if (!focus || document.activeElement !== document.body) return;
    let target = focus.id && list.querySelector(`#${CSS.escape(focus.id)}`);
    if (!target && focus.row) {
      const row = [...list.querySelectorAll('.mail-row')].find(node => Object.entries(focus.row).every(([key, value]) => (node.dataset[key] || '') === value));
      target = row && ([...row.querySelectorAll('button')].find(node => label(node) === focus.label) || row.querySelector('.mail-open'));
    }
    target ||= list.querySelector('#mail-read-retry, .mail-open, [role="status"]');
    if (target) { if (!target.matches('button')) target.tabIndex = -1; target.focus(); }
  };
}
function beginMailRead(key, label) {
  const generation = ++_listGeneration;
  const list = $('mail-list');
  const context = `${_active}:${key}`;
  const previous = _listContext === context ? [..._lastMsgs] : [];
  _listContext = context;
  if (!previous.length) _lastMsgs = [];
  const renderWithFocus = preserveMailReadFocus(list);
  if (!previous.length) list.innerHTML = `<div class="mail-empty" role="status">${esc(label)}</div>`;
  list.setAttribute('aria-busy', 'true');
  return {
    previous,
    current: () => generation === _listGeneration && Boolean($('mail-view')?.getClientRects().length),
    finish: render => {
      renderWithFocus(render);
      list.setAttribute('aria-busy', 'false');
    },
  };
}
async function loadCachedMail(key, label, urlFor, empty = 'no mail here', fetcher = fetch) {
  const owner = beginMailRead(key, label);
  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const results = await Promise.allSettled(accts.map(async account => {
    const data = await mailJson(urlFor(account), {}, fetcher);
    if (!Array.isArray(data?.messages) || data.error) throw new Error(data?.error || 'could not read messages');
    return data.messages.map(message => ({ ...message, account_id: account.id, account_name: account.name || account.email }));
  }));
  if (!owner.current()) return;
  const messages = [], errors = [];
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') messages.push(...result.value);
    else {
      const account = accts[index];
      errors.push(`${acctName(account.id)}: ${result.reason?.message || 'could not read messages'}`);
      messages.push(...owner.previous.filter(message => message.account_id === account.id));
    }
  });
  owner.finish(() => {
    if (!messages.length && !errors.length) {
      _lastMsgs = [];
      $('mail-list').innerHTML = `<div class="mail-empty" role="status">${esc(empty)}</div>`;
    } else renderInbox(messages, errors);
  });
}
async function searchMail(q, fetcher = fetch) {
  _searchView = q;
  _labelFilter = '';
  _lastSearch = q;
  _renderSavedBar();
  return loadCachedMail(`search:${q}`, 'searching…', a => `/api/mail/adv-search/${a.id}?q=${encodeURIComponent(q)}&limit=40`, `no mail matches “${q}”`, fetcher);
}

function _reloadCurrent({ force = false, silent = false, fetcher = fetch } = {}) {
  if (_searchView) return searchMail(_searchView, fetcher);
  if (_labelFilter) return loadByLabel(_labelFilter, { preserveReader: true });
  if (_filter === 'flagged') return loadSmart('flagged', { preserveReader: true });
  if (['vip', 'muted', 'snoozed'].includes(_filter)) return loadSmart(_filter, { preserveReader: true });
  if (_filter === 'drafts') return loadDrafts({ preserveReader: true });
  if (_filter.startsWith('cat:')) return loadCategory(_filter.slice(4), { preserveReader: true });
  return loadInbox(force, silent, fetcher);
}

const SAVED_SEARCH_PREFIX = 'alles-mail-search:';
let _savedRows = [], _savedScopes = [], _savedPending = null;
let _savedRead = 0, _savedReady = false, _savedBusy = false, _savedConfirmed = false;
let _savedReadError = '', _savedRecoveryError = '', _savedNotice = '';
let _savedSave = null;
const _savedRemovals = new Set();
// Match Python str.strip() used by the saved-search API, including U+0085.
const savedText = value => value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, '');
const savedLabel = value => value.name.trim() || value.query.trim() || 'saved search';
const savedKey = scope => SAVED_SEARCH_PREFIX + scope;
const savedMatches = (row, pending) => row.id === pending.request_id && row.name === pending.name && row.query === pending.query;
const savedIntentMatches = (a, b) => a?.request_id === b?.request_id && a?.recovery_scope === b?.recovery_scope && a?.name === b?.name && a?.query === b?.query;

function savedRequestId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function readPendingSearch() {
  _savedRecoveryError = '';
  try {
    let pending = null;
    for (const scope of _savedScopes) {
      const raw = sessionStorage.getItem(savedKey(scope));
      if (!raw) continue;
      const value = JSON.parse(raw);
      if (!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value?.request_id || '') || typeof value.name !== 'string' || !savedText(value.name) || typeof value.query !== 'string' || value.recovery_scope !== scope) throw new Error('invalid pending search');
      pending ||= value;
    }
    _savedPending = pending;
    _savedConfirmed = false;
  } catch {
    _savedRecoveryError = 'could not read the pending search. retry, or clear its recovery data.';
  }
}
function clearPendingSearch(pending) {
  for (const scope of _savedScopes) {
    const key = savedKey(scope), raw = sessionStorage.getItem(key);
    if (raw && JSON.parse(raw).request_id === pending.request_id) {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error('could not clear recovery data');
    }
  }
  if (_savedPending?.request_id === pending.request_id) _savedPending = null;
}
function confirmSavedSearch(row, pending) {
  if (!savedMatches(row, pending)) throw new Error('could not confirm the saved search');
  if (_savedSave?.pending.request_id === pending.request_id && _savedSave.pending.recovery_scope === pending.recovery_scope) _savedSave.confirmed = true;
  _savedConfirmed = true;
  _savedNotice = 'search saved';
  try { clearPendingSearch(pending); }
  catch { _savedNotice = 'search saved. its recovery data could not be cleared; retry cleanup.'; }
}
function paintSavedBar() {
  const bar = $('mail-saved'); if (!bar) return;
  const focused = bar.contains(document.activeElement) ? document.activeElement.id : '';
  const blocked = _savedBusy || !_savedReady || Boolean(_savedReadError || _savedRecoveryError || _savedPending);
  const query = savedText(_lastSearch);
  const existing = _savedRows.find(row => row.query === query);
  const chips = _savedRows.map(row => `<span class="mail-saved-item"><button type="button" class="mail-saved-chip" id="mail-saved-open-${esc(row.id)}" data-open="${esc(row.id)}">${esc(savedLabel(row))}</button><button type="button" class="mail-saved-del" id="mail-saved-delete-${esc(row.id)}" data-del="${esc(row.id)}" aria-label="remove saved search ${esc(savedLabel(row))}" aria-disabled="${_savedBusy || Boolean(_savedPending)}">×</button></span>`).join('');
  const save = query && !existing ? `<button type="button" class="btn mail-saved-save" id="mail-saved-save" aria-disabled="${blocked || Boolean(existing)}">${existing ? 'saved' : 'save'} “${esc([...savedLabel({ name: query, query })].slice(0, 20).join(''))}”</button>` : '';
  const removalNotice = [..._savedRemovals].filter(value => value.error && value.scopes.some(scope => _savedScopes.includes(scope))).map(value => `could not confirm removal of “${value.name}”: ${value.error}. retry removing this search.`).join(' ');
  let message = _savedReadError || _savedRecoveryError || removalNotice || _savedNotice;
  if (_savedBusy) message = 'saving changes…';
  else if (_savedPending && !_savedConfirmed && !_savedReadError && !_savedRecoveryError) message = _savedNotice || `saving “${savedLabel(_savedPending)}” is unconfirmed. retry checks the same save.`;
  let actions = '';
  if (_savedReadError || _savedRecoveryError) actions += '<button type="button" class="btn" id="mail-saved-load-retry">retry loading saved searches</button>';
  if (_savedRecoveryError) actions += '<button type="button" class="btn" id="mail-saved-clear">clear recovery data</button>';
  else if (_savedPending) actions += _savedConfirmed
    ? `<button type="button" class="btn" id="mail-saved-cleanup" aria-disabled="${_savedBusy}">retry cleanup</button>`
    : `<button type="button" class="btn" id="mail-saved-retry" aria-disabled="${_savedBusy || Boolean(_savedReadError)}">retry saving search</button><button type="button" class="btn" id="mail-saved-discard" aria-disabled="${_savedBusy}">dismiss</button>`;
  bar.innerHTML = chips + save + (message || actions ? `<div class="mail-saved-status"><p id="mail-saved-status" role="status" tabindex="-1">${esc(message)}</p>${actions}</div>` : '');
  bar.querySelectorAll('[data-open]').forEach(button => button.onclick = () => {
    const row = _savedRows.find(value => value.id === button.dataset.open);
    if (!row) return;
    $('mail-search').value = row.query;
    searchMail(row.query);
  });
  bar.querySelectorAll('[data-del]').forEach(button => button.onclick = () => deleteSavedSearch(button.dataset.del));
  $('mail-saved-save')?.addEventListener('click', () => {
    if (blocked || existing) return;
    const pending = { request_id: savedRequestId(), name: savedText([...query].slice(0, 40).join('')), query, recovery_scope: _savedScopes[0] };
    try {
      const raw = JSON.stringify(pending), key = savedKey(pending.recovery_scope);
      sessionStorage.setItem(key, raw);
      if (sessionStorage.getItem(key) !== raw) throw new Error('could not retain search');
      _savedPending = pending; _savedConfirmed = false; _savedNotice = '';
      savePendingSearch();
    } catch {
      _savedRecoveryError = 'could not keep this save for recovery. no save was sent. retry loading saved searches.';
      paintSavedBar();
    }
  });
  $('mail-saved-load-retry')?.addEventListener('click', () => _renderSavedBar());
  $('mail-saved-retry')?.addEventListener('click', savePendingSearch);
  $('mail-saved-discard')?.addEventListener('click', () => discardPendingSearch(false));
  $('mail-saved-clear')?.addEventListener('click', () => discardPendingSearch(true));
  $('mail-saved-cleanup')?.addEventListener('click', () => {
    if (_savedBusy || !_savedPending) return;
    try { clearPendingSearch(_savedPending); _savedNotice = 'search saved'; readPendingSearch(); }
    catch { _savedNotice = 'search saved. recovery data still could not be cleared.'; }
    paintSavedBar();
  });
  if (focused && bar.getClientRects().length && document.activeElement === document.body) {
    (document.getElementById(focused) || bar.querySelector('.mail-saved-chip, #mail-saved-save, #mail-saved-status'))?.focus();
  }
}
async function _renderSavedBar() {
  const generation = ++_savedRead;
  paintSavedBar();
  try {
    const data = await mailJson('/api/mail/saved-searches', { cache: 'no-store' });
    if (generation !== _savedRead) return;
    if (!Array.isArray(data?.searches) || data.searches.some(row => !row || typeof row.id !== 'string' || typeof row.name !== 'string' || typeof row.query !== 'string') || !Array.isArray(data.recovery_scopes) || !data.recovery_scopes.length || data.recovery_scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error('could not confirm saved searches');
    if (_savedScopes.length && !data.recovery_scopes.some(scope => _savedScopes.includes(scope))) {
      _savedPending = null; _savedConfirmed = false; _savedNotice = '';
    }
    _savedRows = data.searches; _savedScopes = data.recovery_scopes;
    _savedReady = true; _savedReadError = '';
    readPendingSearch();
    for (const removal of _savedRemovals) {
      if (removal.scopes.some(scope => _savedScopes.includes(scope)) && !_savedRows.some(row => row.id === removal.id)) {
        removal.confirmed = true;
        _savedRemovals.delete(removal);
        if (!_savedPending && !_savedNotice) _savedNotice = 'saved search removed';
      }
    }
    if (_savedPending && !_savedRecoveryError) {
      const row = _savedRows.find(value => value.id === _savedPending.request_id);
      if (row && savedMatches(row, _savedPending)) confirmSavedSearch(row, _savedPending);
      else if (row) _savedNotice = 'the saved search differs from the pending values. dismiss this pending save to keep it.';
    }
  } catch (error) {
    if (generation !== _savedRead) return;
    _savedReadError = `could not load saved searches: ${error.message}`;
  }
  paintSavedBar();
}
async function savePendingSearch() {
  if (_savedBusy || !_savedPending || _savedReadError || _savedRecoveryError || _savedConfirmed) return;
  const pending = _savedPending;
  const operation = { pending, confirmed: false };
  _savedSave = operation;
  _savedBusy = true; _savedNotice = ''; paintSavedBar();
  try {
    const row = await mailJson('/api/mail/saved-searches', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pending),
    });
    if (operation.confirmed || !_savedScopes.includes(pending.recovery_scope)) return;
    if (!savedMatches(row, pending)) throw new Error('could not confirm the saved search');
    _savedNotice = `saving “${savedLabel(pending)}” is unconfirmed. retry checks the same save.`;
    await _renderSavedBar();
  } catch (error) {
    if (!_savedScopes.includes(pending.recovery_scope)) return;
    if (error.status === 410) {
      _savedRows = _savedRows.filter(row => row.id !== pending.request_id);
      _savedConfirmed = false;
      _savedNotice = _savedPending?.request_id === pending.request_id
        ? 'this saved search was deleted. dismiss the pending save to start again.'
        : 'this saved search was deleted.';
    } else {
      if (operation.confirmed && error.status !== 403) return;
      _savedNotice = `could not confirm saving “${savedLabel(pending)}”: ${error.message}. retry checks the same save.`;
    }
    await _renderSavedBar();
  } finally { _savedSave = null; _savedBusy = false; paintSavedBar(); }
}

async function discardPendingSearch(clearUnreadable) {
  if (_savedBusy) return;
  const pending = _savedPending, scopes = [..._savedScopes];
  if (!await dlgConfirm('stop checking this save? it may already be saved. this does not remove a saved search.')) return;
  if (_savedBusy || !savedIntentMatches(pending, _savedPending) || scopes.join() !== _savedScopes.join()) return;
  try {
    if (clearUnreadable) {
      for (const scope of scopes) {
        const key = savedKey(scope); sessionStorage.removeItem(key);
        if (sessionStorage.getItem(key) !== null) throw new Error('could not clear recovery data');
      }
    } else if (pending) clearPendingSearch(pending);
    _savedNotice = ''; _savedRecoveryError = ''; readPendingSearch();
  } catch { _savedRecoveryError = 'could not clear the pending search. its recovery data was kept.'; }
  paintSavedBar();
}
async function deleteSavedSearch(id) {
  if (_savedBusy || _savedPending) return;
  const scopes = [..._savedScopes], row = _savedRows.find(value => value.id === id);
  const name = row ? savedLabel(row) : 'this search';
  for (const previous of _savedRemovals) {
    if (previous.id === id && previous.scopes.some(scope => scopes.includes(scope))) _savedRemovals.delete(previous);
  }
  const operation = { id, name, scopes, confirmed: false, error: '' };
  _savedRemovals.add(operation);
  _savedBusy = true; _savedNotice = ''; paintSavedBar();
  try {
    const result = await mailJson(`/api/mail/saved-searches/${encodeURIComponent(id)}?recovery_scope=${encodeURIComponent(scopes[0])}`, { method: 'DELETE' });
    if (result?.ok !== true) throw new Error('could not confirm removal');
    if (operation.confirmed) return;
    operation.confirmed = true;
    _savedRemovals.delete(operation);
    if (!scopes.some(scope => _savedScopes.includes(scope))) return;
    _savedRows = _savedRows.filter(row => row.id !== id);
    _savedNotice = 'saved search removed';
    await _renderSavedBar();
  } catch (error) {
    if (operation.confirmed && error.status !== 403) return;
    if (!operation.confirmed) operation.error = error.message;
    await _renderSavedBar();
  } finally { _savedBusy = false; paintSavedBar(); }
}

const DRAFT_PENDING_PREFIX = 'alles-mail-draft:';
const DRAFT_FIELDS = ['account_id', 'to', 'cc', 'bcc', 'subject', 'body', 'in_reply_to', 'references'];
let _draftScopes = [], _draftRows = [], _draftPending = null, _draftConfirmed = null;
let _draftRead = 0, _draftReady = false, _draftBusy = false, _draftSave = null;
let _draftReadError = '', _draftStorageError = '', _draftNotice = '', _draftConflict = '';
const draftKey = scope => DRAFT_PENDING_PREFIX + scope;
const draftIdentity = value => value.id || value.request_id;
const draftIntentKey = value => value && JSON.stringify([value.id || '', value.request_id || '', value.expected_revision || '', value.recovery_scope, ...DRAFT_FIELDS.map(field => value[field])]);
const sameDraftIntent = (a, b) => Boolean(a && b && draftIntentKey(a) === draftIntentKey(b));
const draftMatches = (row, pending) => row?.id === draftIdentity(pending) && DRAFT_FIELDS.every(field => row[field] === pending[field]);
const validDraft = row => row && typeof row.id === 'string' && row.id && /^[a-f0-9]{64}$/.test(row.revision || '') && DRAFT_FIELDS.every(field => typeof row[field] === 'string');

function readPendingDraft() {
  _draftStorageError = '';
  try {
    let pending = null;
    for (const scope of _draftScopes) {
      const raw = sessionStorage.getItem(draftKey(scope));
      if (!raw) continue;
      const value = JSON.parse(raw);
      const identity = value?.id
        ? typeof value.id === 'string' && /^[a-f0-9]{64}$/.test(value.expected_revision || '') && !value.request_id
        : /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value?.request_id || '') && !value.expected_revision;
      if (!identity || value.recovery_scope !== scope || !DRAFT_FIELDS.every(field => typeof value[field] === 'string')) throw new Error('invalid pending draft');
      pending ||= value;
    }
    if (!sameDraftIntent(pending, _draftPending)) _draftConfirmed = null;
    _draftPending = pending;
  } catch { _draftStorageError = 'could not read draft recovery data. retry loading, or clear the unreadable data.'; }
}
function storePendingDraft(pending, editor, snapshot) {
  ++_draftRead;
  const key = draftKey(pending.recovery_scope), raw = JSON.stringify(pending);
  sessionStorage.setItem(key, raw);
  _draftPending = pending; _draftConfirmed = null; _draftConflict = ''; _draftNotice = '';
  if (editor) {
    editor.scope = pending.recovery_scope; editor.pending = pending; editor.pendingSnapshot = snapshot;
  }
  if (sessionStorage.getItem(key) !== raw) throw new Error('could not retain this draft');
}
function clearPendingDraft(pending) {
  for (const scope of _draftScopes) {
    const key = draftKey(scope), raw = sessionStorage.getItem(key);
    if (raw && sameDraftIntent(JSON.parse(raw), pending)) {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error('could not clear draft recovery data');
    }
  }
  if (sameDraftIntent(_draftPending, pending)) _draftPending = null;
}
function retireDraftSave(pending) {
  if (!sameDraftIntent(_draftSave?.pending, pending)) return;
  _draftSave.retired = true; _draftSave = null; _draftBusy = false;
}
function confirmDraft(row, pending) {
  if (!validDraft(row) || !draftMatches(row, pending)) throw new Error('could not confirm the saved draft');
  const already = sameDraftIntent(_draftConfirmed?.pending, pending);
  _draftConfirmed = { pending, row };
  retireDraftSave(pending);
  const editor = mailEditor();
  if (editor && sameDraftIntent(editor.pending, pending)) editor.accept(row);
  // Only our confirmed save advances an already listed delete action. A refresh
  // from another writer must still conflict with the revision the owner saw.
  $('mail-list')?.querySelectorAll('.mail-draft-del').forEach(button => {
    if (button.dataset.id === row.id && _draftScopes.includes(button.dataset.draftScope)
        && _draftScopes.includes(pending.recovery_scope)) button.dataset.revision = row.revision;
  });
  if (!already) toast('draft saved', 'success');
  _draftNotice = 'draft saved'; _draftConflict = '';
  try { clearPendingDraft(pending); _draftNotice = ''; }
  catch { _draftNotice = 'draft saved. recovery data could not be cleared; retry cleanup.'; }
}
function paintDraftRecovery() {
  const bar = $('mail-draft-recovery'); if (!bar) return;
  const focused = bar.contains(document.activeElement) ? document.activeElement.id : '';
  const pending = _draftPending;
  let message = _draftReadError || _draftStorageError || _draftNotice;
  if (pending && !message) message = `saving “${pending.subject.trim() || 'untitled draft'}” is unconfirmed. retry checks the same save.`;
  if (_draftBusy && !_draftConfirmed) message = 'saving draft…';
  let actions = '';
  const button = (id, label, blocked = _draftBusy) => `<button type="button" class="btn" id="${id}" aria-disabled="${blocked}">${label}</button>`;
  if (_draftReadError || _draftStorageError) actions += button('mail-draft-load-retry', 'retry loading drafts', false);
  if (_draftStorageError) actions += button('mail-draft-clear', 'clear recovery data');
  else if (pending) {
    if (_draftConfirmed) actions += button('mail-draft-cleanup', 'retry cleanup');
    else {
      if (!_draftConflict) actions += button('mail-draft-retry', 'retry saving draft', _draftBusy || Boolean(_draftReadError));
      actions += button('mail-draft-pending', 'open pending draft', false);
      if (_draftConflict === 'changed') actions += button('mail-draft-current', 'open saved draft', false);
      if (_draftConflict) actions += button('mail-draft-copy', 'save pending as new draft');
      actions += button('mail-draft-dismiss', 'dismiss');
    }
  }
  bar.hidden = !message && !actions;
  bar.innerHTML = message || actions ? `<div class="mail-saved-status"><p id="mail-draft-status" role="status" tabindex="-1">${esc(message)}</p>${actions}</div>` : '';
  $('mail-draft-load-retry')?.addEventListener('click', () => loadDraftRecovery());
  $('mail-draft-clear')?.addEventListener('click', () => dismissPendingDraft(true));
  $('mail-draft-dismiss')?.addEventListener('click', () => dismissPendingDraft(false));
  $('mail-draft-retry')?.addEventListener('click', () => savePendingDraft());
  $('mail-draft-pending')?.addEventListener('click', () => { if (_draftPending) compose({ ..._draftPending, _pending: _draftPending }); });
  $('mail-draft-current')?.addEventListener('click', () => openCurrentDraft());
  $('mail-draft-copy')?.addEventListener('click', () => copyPendingDraft());
  $('mail-draft-cleanup')?.addEventListener('click', () => {
    if (_draftBusy || !_draftPending || !_draftConfirmed) return;
    try { clearPendingDraft(_draftPending); _draftNotice = ''; readPendingDraft(); }
    catch { _draftNotice = 'draft saved. recovery data still could not be cleared.'; }
    paintDraftRecovery();
  });
  const editor = mailEditor(), save = editor?.root.querySelector('#mc-save');
  if (save) {
    const owned = sameDraftIntent(editor.pending, pending);
    save.textContent = owned && !_draftConfirmed ? 'retry saving draft' : (editor.deleted ? 'save as new draft' : 'save draft');
    const status = editor.root.querySelector('#mc-status');
    const recoveryMessage = editor.scope && !_draftScopes.includes(editor.scope) ? 'this editor belongs to a different mail store. your text is still here.' : (editor.deleted ? 'this saved draft was deleted. your text is still here; save it as a new draft.' : '');
    if (recoveryMessage) { status.textContent = recoveryMessage; status.dataset.draftRecovery = '1'; }
    else if (status.dataset.draftRecovery) { status.textContent = ''; delete status.dataset.draftRecovery; }
    save.setAttribute('aria-disabled', String(_draftBusy || !_draftReady || Boolean(editor.scope && !_draftScopes.includes(editor.scope)) || Boolean(_draftReadError || _draftStorageError || (pending && (!owned || _draftConflict || _draftConfirmed)))));
  }
  if (focused && document.activeElement === document.body) {
    const target = bar.hidden ? save || $('mail-compose-btn') : document.getElementById(focused) || $('mail-draft-status');
    if (target?.getClientRects().length) target.focus();
  }
}
async function loadDraftRecovery() {
  const generation = ++_draftRead;
  try {
    const data = await mailJson('/api/mail/drafts?context=true', { cache: 'no-store' });
    if (!Array.isArray(data?.drafts) || data.drafts.some(row => !validDraft(row)) || !Array.isArray(data.recovery_scopes) || !data.recovery_scopes.length || data.recovery_scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error('could not confirm draft recovery');
    if (generation !== _draftRead) return data;
    if (_draftScopes.length && !data.recovery_scopes.some(scope => _draftScopes.includes(scope))) {
      _draftPending = null; _draftConfirmed = null; _draftNotice = ''; _draftConflict = '';
      if (_draftSave) _draftSave.retired = true;
      _draftSave = null; _draftBusy = false;
    }
    _draftRows = data.drafts; _draftScopes = data.recovery_scopes; _draftReady = true; _draftReadError = '';
    readPendingDraft();
    if (_draftPending && !_draftStorageError) {
      const pending = _draftPending, row = _draftRows.find(value => value.id === draftIdentity(pending));
      if (row && draftMatches(row, pending)) confirmDraft(row, pending);
      else if (!_draftConfirmed) {
        const knownDeleted = _draftConflict === 'deleted' && !row;
        _draftConflict = row && (!pending.id || row.revision !== pending.expected_revision) ? 'changed' : (!row && (pending.id || knownDeleted) ? 'deleted' : '');
        if (_draftConflict === 'changed') _draftNotice = 'the saved draft has changed. your pending version is kept; review the saved draft or save a separate copy.';
        else if (_draftConflict === 'deleted') _draftNotice = 'the saved draft is no longer available. your pending version is kept; save a separate copy or dismiss it.';
        if (_draftConflict) retireDraftSave(pending);
      }
    }
    const editor = mailEditor();
    if (editor?.draftId && _draftScopes.includes(editor.scope) && !_draftRows.some(row => row.id === editor.draftId) && !_deletingDrafts.has(editor.draftId)) { editor.deleted = true; editor.initial = null; }
    paintDraftRecovery();
    return data;
  } catch (error) {
    if (generation === _draftRead) { _draftReadError = `could not load draft recovery: ${error.message}`; paintDraftRecovery(); }
    return null;
  }
}
async function savePendingDraft() {
  if (_draftBusy || !_draftPending || _draftConfirmed || _draftReadError || _draftStorageError || _draftConflict) return;
  const pending = _draftPending, operation = { pending, retired: false };
  if (!_draftScopes.includes(pending.recovery_scope)) return;
  ++_draftRead;
  _draftSave = operation; _draftBusy = true; _draftNotice = ''; paintDraftRecovery();
  try {
    const row = await mailJson('/api/mail/drafts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pending) });
    if (operation.retired || !_draftScopes.includes(pending.recovery_scope)) return;
    if (!validDraft(row) || !draftMatches(row, pending)) throw new Error('could not confirm the saved draft');
  } catch (error) {
    if (operation.retired || !_draftScopes.includes(pending.recovery_scope)) return;
    if (error.status === 410 || error.status === 404) {
      _draftConflict = 'deleted'; _draftNotice = 'this draft was deleted. your pending version is kept; save a separate copy or dismiss it.';
    } else if (error.status === 409) {
      _draftConflict = 'changed'; _draftNotice = 'the saved draft has changed. your pending version is kept; review it before saving a separate copy.';
    } else _draftNotice = `save is unconfirmed: ${error.message}. retry checks the same draft.`;
    toast('save unconfirmed', 'error');
  } finally {
    if (_draftSave === operation) { _draftSave = null; _draftBusy = false; }
    paintDraftRecovery();
  }
  await loadDraftRecovery();
}
async function dismissPendingDraft(unreadable) {
  if (_draftBusy) return;
  const pending = _draftPending, scopes = [..._draftScopes];
  if (!await dlgConfirm('stop checking this draft save? it may already be saved. this does not delete a saved draft.')) return;
  if (_draftBusy || scopes.join() !== _draftScopes.join() || (!unreadable && !sameDraftIntent(pending, _draftPending))) return;
  try {
    if (unreadable) for (const scope of scopes) {
      const key = draftKey(scope); sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error('could not clear recovery data');
    }
    else if (pending) clearPendingDraft(pending);
    const editor = mailEditor();
    if (editor && sameDraftIntent(editor.pending, pending)) editor.pending = null;
    _draftConfirmed = null; _draftConflict = ''; _draftNotice = ''; readPendingDraft();
  } catch { _draftStorageError = 'could not clear draft recovery data. the pending save was kept.'; }
  paintDraftRecovery();
}
async function copyPendingDraft() {
  if (_draftBusy || !_draftPending || !_draftConflict) return;
  const pending = _draftPending;
  if (!await dlgConfirm('save the pending version as a separate draft? the current saved draft stays unchanged. newer editor changes stay unsaved.')) return;
  if (_draftBusy || !sameDraftIntent(pending, _draftPending) || !_draftScopes.includes(pending.recovery_scope)) return;
  const copy = { ...pending, id: '', expected_revision: '', request_id: savedRequestId() };
  try {
    const current = mailEditor(), editor = current && sameDraftIntent(current.pending, pending) ? current : null;
    storePendingDraft(copy, editor, editor?.pendingSnapshot);
    await savePendingDraft();
  } catch { _draftStorageError = 'could not keep the new draft for recovery. no new save was sent.'; paintDraftRecovery(); }
}
async function openCurrentDraft() {
  const pending = _draftPending;
  if (!pending || !_draftScopes.includes(pending.recovery_scope)) return;
  if (!await prepareMailNavigation()) return;
  const generation = _messageGeneration;
  try {
    const row = await mailJson(`/api/mail/drafts/${encodeURIComponent(draftIdentity(pending))}?recovery_scope=${encodeURIComponent(pending.recovery_scope)}`, { cache: 'no-store' });
    if (generation !== _messageGeneration || !sameDraftIntent(pending, _draftPending) || !validDraft(row) || row.id !== draftIdentity(pending)) return;
    await compose({ ...row, recovery_scope: pending.recovery_scope }, generation);
  } catch (error) { toast(error.message || 'could not open saved draft', 'error'); }
}

export async function loadMail(fetcher = fetch) {
  initMail();
  ++_messageGeneration;
  showPendingCapture($('mail-view'));
  startMailPoll(fetcher).catch(error => console.error(error));
  const generation = ++_mailLoadGeneration;
  ++_listGeneration;
  const accounts = await mailJson('/api/mail/accounts', {}, fetcher);
  if (generation !== _mailLoadGeneration) return;
  if (!Array.isArray(accounts)) throw new Error('could not read mail accounts');
  _accounts = accounts;
  if (_accounts.length > 1 && !localStorage.getItem('alles-mail-account-mode')) _active = 'all';
  syncAccountSelect();
  loadDraftRecovery();
  _renderScheduled();
  if (!_accounts.length) {
    $('mail-list').innerHTML = '';
    if (mailEditor()) toast('the mail account is unavailable; your draft is still open', 'error');
    else accountsPanel(true);
    return;
  }
  _renderSavedBar();
  const query = $('mail-search')?.value.trim();
  return query ? searchMail(query, fetcher) : _reloadCurrent({ fetcher });
}

function syncAccountSelect() {
  const sel = $('mail-account');
  if (!sel) return;
  if (!_accounts.length) {
    populateDropdown(sel, [{ value: '', label: 'no accounts' }], '');
    return;
  }
  const ids = new Set(_accounts.map(a => a.id));
  if (_active !== 'all' && !ids.has(_active)) _active = _accounts.length > 1 ? 'all' : _accounts[0].id;
  if (_accounts.length > 1 && !_active) _active = 'all';
  if (_accounts.length === 1 && _active === 'all') _active = _accounts[0].id;
  const opts = [];
  if (_accounts.length > 1) opts.push({ value: 'all', label: 'all inboxes' });
  _accounts.forEach(a => opts.push({ value: a.id, label: a.name || a.email }));
  populateDropdown(sel, opts, _active);
}

async function fetchInboxFor(account, limit = 35, folder = 'INBOX', quick = false, fetcher = fetch) {
  // quick=1 lets the server skip the full header re-fetch when the mailbox tip
  // hasn't moved — keeps the 30s background poll cheap on slow connections
  const url = `/api/mail/inbox/${account.id}?folder=${encodeURIComponent(folder)}&limit=${limit}${quick ? '&quick=1' : ''}`;
  const d = await mailJson(url, {}, fetcher);
  if (!Array.isArray(d?.messages)) throw new Error('could not read messages');
  const map = ms => ms.map(m => ({ ...m, account_id: account.id, account_name: account.name || account.email, folder }));
  // IMAP failed but the server handed back the cached copy → show it (offline-friendly) instead of erroring
  if (d.error && !d.messages.length) throw new Error(d.error);
  return { messages: map(d.messages), warning: d.error ? `showing saved mail; ${d.error}` : '' };
}

// providers don't agree on a sent-folder name; sniff it once per account
async function sentFolderFor(account, fetcher = fetch) {
  if (_sentFolders[account.id]) return _sentFolders[account.id];
  const d = await mailJson(`/api/mail/folders/${account.id}`, {}, fetcher);
  if (!Array.isArray(d?.folders) || d.error) throw new Error(d?.error || 'could not read mail folders');
  const f = (d.folders || []).find(x => /sent/i.test(x)) || 'Sent';
  _sentFolders[account.id] = f;
  return f;
}

const applyFilter = msgs => _filter === 'unread' ? msgs.filter(m => !m.seen) : msgs;

const mailIdentity = (aid, uid, folder) => JSON.stringify([aid, folder || 'INBOX', String(uid)]);
const sameMail = (message, aid, uid, folder) => mailIdentity(message.account_id, message.uid, message.folder) === mailIdentity(aid, uid, folder);
const _mailChanges = new Map();
function paintMailChanges() {
  const unread = $('mail-unread');
  if (unread?.dataset.mailIdentity) unread.setAttribute('aria-disabled', String(_mailChanges.has(unread.dataset.mailIdentity)));
  $('mail-list')?.querySelectorAll('.mail-row[data-aid]').forEach(row => {
    const busy = _mailChanges.has(mailIdentity(row.dataset.aid, row.dataset.uid, row.dataset.folder));
    row.querySelectorAll('[data-flag], [data-mute], [data-archive], [data-label], [data-snooze]').forEach(button => button.setAttribute('aria-disabled', String(busy)));
  });
}
function updateMailRows(matches, changes, remove = false) {
  const update = rows => remove ? rows.filter(row => !matches(row)) : rows.map(row => matches(row) ? { ...row, ...changes } : row);
  const cached = readCache();
  if (Array.isArray(cached)) writeCache(update(cached));
  if (!_lastMsgs.some(matches)) return;
  _lastMsgs = update(_lastMsgs);
  if (!_searchView && !_labelFilter) {
    if (_filter === 'unread') _lastMsgs = _lastMsgs.filter(row => !row.seen);
    if (_filter === 'flagged') _lastMsgs = _lastMsgs.filter(row => row.flagged);
  }
  const list = $('mail-list');
  if (list?.querySelector('.mail-row[data-aid]')) preserveMailReadFocus(list)(() => renderInbox(_lastMsgs, _mailErrors));
}
async function changeMail(button, key, request, valid, apply, success, failure, waitWhileCurrent = null) {
  while (_mailChanges.has(key)) {
    if (!waitWhileCurrent || !waitWhileCurrent()) return;
    button?.setAttribute('aria-disabled', 'true');
    await _mailChanges.get(key);
  }
  if (waitWhileCurrent && !waitWhileCurrent()) return;
  let release;
  _mailChanges.set(key, new Promise(resolve => { release = resolve; }));
  button?.setAttribute('aria-disabled', 'true'); paintMailChanges();
  try {
    const result = await request();
    if (!valid(result)) throw new Error(result?.error || 'the saved result could not be confirmed');
    apply(result);
    if (success) toast(success, 'success');
  } catch (error) {
    toast(`${failure}. ${error.message || 'check the mailbox before trying again'}`, 'error');
  } finally {
    _mailChanges.delete(key); release(); button?.setAttribute('aria-disabled', 'false'); paintMailChanges();
  }
}
const mailPost = (url, body) => mailJson(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

// Gmail-style left sidebar (4b): folders/categories as icon+label rows
const _MAIL_NAV = [
  { f: 'inbox', label: 'inbox', icon: 'mail' },
  { f: 'cat:primary', label: 'primary', icon: 'user' },
  { f: 'cat:social', label: 'social', icon: 'comment' },
  { f: 'cat:promotions', label: 'promotions', icon: 'tag' },
  { f: 'unread', label: 'unread', icon: 'bell' },
  { f: 'flagged', label: 'flagged', icon: 'bookmark' },
  { f: 'vip', label: 'vip', icon: 'star' },
  { f: 'muted', label: 'muted', icon: 'mute' },
  { f: 'snoozed', label: 'snoozed', icon: 'snooze' },
  { f: 'sent', label: 'sent', icon: 'send' },
  { f: 'drafts', label: 'drafts', icon: 'edit' },
];
function _renderMailSidebar() {
  const nav = $('mail-sidebar'); if (!nav) return;
  const ic = window.icon || (() => '');
  nav.innerHTML = _MAIL_NAV.map(n =>
    `<button class="mail-nav-item${n.f === _filter ? ' active' : ''}" data-filter="${n.f}" title="${n.label}"><span class="mail-nav-ic">${ic(n.icon)}</span><span class="mail-nav-label">${n.label}</span></button>`).join('');
  nav.querySelectorAll('.mail-nav-item').forEach(b => b.addEventListener('click', () => setFilter(b.dataset.filter)));
}
function _initMailSidebar() {
  _renderMailSidebar();
  const collapsed = localStorage.getItem('mail-sidebar-collapsed') === '1';
  $('mail-view')?.classList.toggle('sidebar-collapsed', collapsed);
  $('mail-sidebar-toggle')?.addEventListener('click', () => {
    const on = $('mail-view').classList.toggle('sidebar-collapsed');
    localStorage.setItem('mail-sidebar-collapsed', on ? '1' : '0');
  });
}

function setFilter(f) {
  if (_filter === f && !_searchView && !_labelFilter) return;
  _searchView = '';
  _labelFilter = '';
  _filter = f;
  if ($('mail-search')) $('mail-search').value = '';
  document.querySelectorAll('.mail-nav-item').forEach(t => t.classList.toggle('active', t.dataset.filter === f));
  if (f === 'drafts') loadDrafts();
  else if (f === 'flagged') loadSmart('flagged');
  else if (['vip', 'muted', 'snoozed'].includes(f)) loadSmart(f);
  else if (f.startsWith('cat:')) loadCategory(f.slice(4));
  else loadInbox();
}

async function loadCategory(cat, { preserveReader = false } = {}) {
  _searchView = ''; _labelFilter = '';
  if (!preserveReader) { ++_messageGeneration; if (!mailEditor()) $('mail-main').innerHTML = ''; }
  return loadCachedMail(`category:${cat}`, `loading ${cat}…`, a => `/api/mail/category/${a.id}?cat=${encodeURIComponent(cat)}`);
}
async function loadByLabel(label, { preserveReader = false } = {}) {
  _searchView = ''; _labelFilter = label;
  if (!preserveReader) { ++_messageGeneration; if (!mailEditor()) $('mail-main').innerHTML = ''; }
  return loadCachedMail(`label:${label}`, `label “${label}”…`, a => `/api/mail/by-label/${a.id}?label=${encodeURIComponent(label)}`);
}
async function loadSmart(filter, { preserveReader = false } = {}) {
  _searchView = ''; _labelFilter = '';
  if (!preserveReader) { ++_messageGeneration; if (!mailEditor()) $('mail-main').innerHTML = ''; }
  return loadCachedMail(`smart:${filter}`, `loading ${filter}…`, a => `/api/mail/smart/${a.id}?filter=${encodeURIComponent(filter)}`);
}

function draftPreview(html) {
  const template = document.createElement('template');
  template.innerHTML = String(html || '');
  template.content.querySelectorAll('script, style').forEach(node => node.remove());
  template.content.querySelectorAll('br, p, div, li, blockquote, h1, h2, h3, h4, h5, h6, tr').forEach(node => node.after(document.createTextNode(' ')));
  return [...template.content.textContent.replace(/\s+/g, ' ').trim()].slice(0, 80).join('');
}
function draftHtml(element) {
  if (!element) return '';
  const copy = element.cloneNode(true);
  // Control decoration is transient UI state, not authored message content.
  for (const attribute of ['data-kokuen-primitive', 'data-kokuen-state', 'data-kokuen-state-message']) {
    copy.querySelectorAll(`[${attribute}]`).forEach(node => node.removeAttribute(attribute));
  }
  return copy.innerHTML;
}

async function loadDrafts({ preserveReader = false } = {}) {
  const generation = ++_listGeneration;
  const current = () => generation === _listGeneration && Boolean($('mail-view')?.getClientRects().length);
  _listContext = ''; _lastMsgs = [];
  _searchView = '';
  _labelFilter = '';
  const list = $('mail-list'); const main = $('mail-main');
  if (!preserveReader) { ++_messageGeneration; if (!mailEditor()) main.innerHTML = ''; }
  list.setAttribute('aria-busy', 'true');
  list.innerHTML = '<div class="mail-empty">loading drafts…</div>';
  let drafts = [];
  try {
    const data = await loadDraftRecovery();
    if (!current()) return;
    if (!data || !data.recovery_scopes.some(scope => _draftScopes.includes(scope))) throw new Error('drafts unavailable');
    drafts = data.drafts.filter(draft => !_active || _active === 'all' || draft.account_id === _active);
    list.setAttribute('aria-busy', 'false');
  } catch {
    if (!current()) return;
    list.setAttribute('aria-busy', 'false');
    list.innerHTML = '<div class="mail-empty" role="alert">could not load drafts. <button class="btn" id="mail-drafts-retry">retry</button></div>';
    list.querySelector('#mail-drafts-retry').addEventListener('click', () => loadDrafts({ preserveReader: true }));
    return;
  }
  if (!drafts.length) { list.innerHTML = '<div class="mail-empty">no drafts</div>'; return; }
  list.innerHTML = drafts.map(d => `
    <div class="mail-row mail-draft-row" data-id="${esc(d.id)}">
      <span class="mail-from">${esc(d.to || '(no recipient)')}</span>
      <button type="button" class="mail-open mail-subj" ${_deletingDrafts.has(d.id) ? 'disabled' : ''}>${esc(d.subject || '(no subject)')}</button>
      <button type="button" class="mail-draft-del icon-btn" data-id="${esc(d.id)}" data-revision="${esc(d.revision)}" data-draft-scope="${esc(_draftScopes[0])}" aria-label="delete draft: ${esc(d.subject || '(no subject)')}" ${_deletingDrafts.has(d.id) ? 'disabled' : ''}>${_si('trash')}</button>
      <div class="mail-snippet">${esc(draftPreview(d.body))}</div>
    </div>`).join('');
  const draftScope = _draftScopes[0];
  list.querySelectorAll('.mail-draft-row').forEach(row => {
    row.addEventListener('click', async e => {
      if (e.target.closest('.mail-draft-del') || _deletingDrafts.has(row.dataset.id)) return;
      if (!await prepareMailNavigation() || _deletingDrafts.has(row.dataset.id)) return;
      const generation = _messageGeneration, opening = { id: row.dataset.id, canceled: false, generation };
      _openingDraft = opening;
      try {
        const d = await mailJson(`/api/mail/drafts/${encodeURIComponent(row.dataset.id)}?recovery_scope=${encodeURIComponent(draftScope)}`);
        if (generation !== _messageGeneration || opening.canceled) return;
        if (d?.id !== row.dataset.id || typeof d.body !== 'string' || typeof d.subject !== 'string') throw new Error('could not confirm this draft');
        await compose({ ...d, recovery_scope: draftScope }, generation);
      } catch (error) { if (generation === _messageGeneration && !opening.canceled) toast(error.message || 'could not open draft', 'error'); }
      finally { if (_openingDraft === opening) _openingDraft = null; }
    });
  });
  list.querySelectorAll('.mail-draft-del').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    if (b.disabled) return;
    const id = b.dataset.id, editor = mailEditor(), listed = drafts.find(draft => draft.id === id);
    if (!listed || !_draftScopes.includes(draftScope)) return;
    if (_deletingDrafts.has(id)) return;
    const revision = b.dataset.revision || listed.revision;
    const snapshot = editor?.draftId === id ? editor.snapshot() : null;
    if (snapshot !== null && snapshot !== editor.initial) {
      if (!await dlgConfirm('delete the saved draft and discard these changes?')) return;
      if (mailEditor() !== editor || editor.snapshot() !== snapshot) return;
    }
    if (_deletingDrafts.has(id)) return;
    const hadFocus = document.activeElement === b, account = _active;
    const listGeneration = _listGeneration;
    let focusGeneration = listGeneration;
    _deletingDrafts.add(id);
    b.disabled = true;
    b.closest('.mail-draft-row')?.querySelector('.mail-open')?.setAttribute('disabled', '');
    if (_openingDraft?.id === id) {
      _openingDraft.canceled = true;
      if (_openingDraft.generation === _messageGeneration) ++_messageGeneration;
    }
    try {
      const result = await mailJson(`/api/mail/drafts/${encodeURIComponent(id)}?expected_revision=${encodeURIComponent(revision)}&recovery_scope=${encodeURIComponent(draftScope)}`, { method: 'DELETE' });
      if (result?.ok !== true) throw new Error('could not confirm draft deletion');
      if (mailEditor() === editor && editor?.draftId === id) {
        if (editor.snapshot() === snapshot) clearMailEditor(editor);
        else editor.detach();
      }
      if (_filter === 'drafts') {
        if (_listGeneration === listGeneration) focusGeneration = listGeneration + 1;
        await loadDrafts({ preserveReader: true });
      }
    } catch (error) { toast(error.message || 'could not delete draft', 'error'); }
    finally {
      _deletingDrafts.delete(id); b.disabled = false;
      $('mail-list').querySelectorAll(`.mail-draft-row[data-id="${CSS.escape(id)}"] button`).forEach(button => { button.disabled = false; });
      if (hadFocus && document.activeElement === document.body && _filter === 'drafts'
          && _active === account && _listGeneration === focusGeneration && list.getClientRects().length) {
        (b.isConnected ? b : list.querySelector('#mail-drafts-retry, .mail-open:not(:disabled)') || $('mail-compose-btn'))?.focus();
      }
    }
  }));
}

async function loadInbox(force = false, silent = false, fetcher = fetch) {
  silent = silent && !force;
  _searchView = '';
  _labelFilter = '';
  const list = $('mail-list');
  const generation = ++_listGeneration;
  const account = _active, filter = _filter;
  _listContext = `${account}:inbox:${filter}`;
  if (!_accounts.length) { list.setAttribute('aria-busy', 'false'); return; }
  list.setAttribute('aria-busy', 'true');
  const cached = readCache();
  const renderWithFocus = preserveMailReadFocus(list);
  if (!silent) {
    if (cached?.length) renderInbox(applyFilter(cached), []);   // instant, stale
    else list.innerHTML = `<div class="mail-empty">loading ${_filter}...</div>`;
  }

  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const results = await Promise.allSettled(accts.map(async a => {
    const folder = filter === 'sent' ? await sentFolderFor(a, fetcher) : 'INBOX';
    return fetchInboxFor(a, account === 'all' ? 30 : 45, folder, silent, fetcher);   // silent poll → cheap quick fetch
  }));
  if (generation !== _listGeneration || account !== _active || filter !== _filter || !$('mail-view')?.getClientRects().length) return;
  list.setAttribute('aria-busy', 'false');
  const messages = [], errors = [];
  results.forEach((result, index) => {
    const id = accts[index].id;
    if (result.status === 'fulfilled') {
      messages.push(...result.value.messages);
      if (result.value.warning) errors.push(`${acctName(id)}: ${result.value.warning}`);
    } else {
      errors.push(`${acctName(id)}: ${result.reason?.message || 'could not read messages'}`);
      if (Array.isArray(cached)) messages.push(...cached.filter(message => message.account_id === id));
    }
  });
  const newest = _newestKey(messages);
  if (silent && !errors.length && !list.querySelector('.mail-error-strip') && _lastNewest && newest === _lastNewest) return;
  if (silent && _lastNewest && newest !== _lastNewest) {
    const top = [...messages].sort((a, b) => _msgTime(b) - _msgTime(a))[0];
    if (top && !top.seen) toast(`new mail: ${fromName(top.from)}: ${(top.subject || '').slice(0, 60)}`, 'success');
  }
  _lastNewest = newest;
  renderWithFocus(() => renderInbox(applyFilter(messages), errors));
  writeCache(messages);

}

// ── live inbox: poll while the mail view is visible ─────────────────────────
let _pollTimer = null;
let _lastNewest = '';
const _msgTime = m => Number(m.date_ts || 0) || Math.floor((Date.parse(m.date || '') || 0) / 1000);
const _newestKey = msgs => [...msgs].sort((a, b) => _msgTime(b) - _msgTime(a))
  .slice(0, 5).map(m => `${m.account_id || ''}:${m.uid}`).join('|');

let _pollWired = false;
let _pollGen = 0;
export async function startMailPoll(fetcher = fetch) {
  const gen = ++_pollGen;   // newer call wins the await race so a stale one can't leak a 2nd interval
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  let ms = 30000;
  try { ms = Math.max(10, Number((await fetcher('/api/settings').then(r => r.json())).mail_poll_seconds) || 30) * 1000; } catch (e) { console.error(e); }
  if (gen !== _pollGen) return;   // superseded while awaiting
  _pollTimer = setInterval(() => {
    const view = $('mail-view');
    if (!view || view.style.display === 'none' || document.hidden) return;
    // only the plain inbox/unread views are what loadInbox renders; polling while on flagged/
    // vip/drafts/a category/a label would silently clobber that view with the full inbox
    if (!_accounts.length || _searchView || _labelFilter || (_filter !== 'inbox' && _filter !== 'unread')) return;
    loadInbox(false, true).catch(console.error);
  }, ms);
  if (_pollWired) return;
  _pollWired = true;
  document.addEventListener('visibilitychange', () => {
    // catch up immediately when the tab comes back
    if (!document.hidden && $('mail-view')?.style.display !== 'none' && _accounts.length) {
      _reloadCurrent({ silent: true })?.catch(console.error);
    }
  });
}

function _unsubLink(raw) {
  if (!raw) return '';
  const http = (raw.match(/<(https?:[^>]+)>/i) || [])[1];
  const mailto = (raw.match(/<(mailto:[^>]+)>/i) || [])[1];
  return http || mailto || '';
}

const _msgRow = (m, indent = false) => {
  // Match the cache filter's UTC comparison, including timestamps without a suffix.
  const snoozed = (m.snoozed_until || '') > new Date().toISOString().slice(0, -1);
  const unsub = _unsubLink(m.list_unsubscribe);
  return `
    <div class="mail-row${m.seen ? '' : ' unread'}${indent ? ' mail-row-child' : ''}" data-aid="${esc(m.account_id)}" data-uid="${esc(m.uid)}" data-folder="${esc(m.folder || 'INBOX')}" data-subject="${esc(m.subject)}">
      <div class="mail-row-top">
        <span class="mail-from">${esc(fromName(m.from))}</span>
        <span class="mail-date">${esc(shortDate(m.date))}</span>
      </div>
      <div class="mail-subject"><button type="button" class="mail-open">${esc(m.subject || '(no subject)')}</button>${(m.labels || []).map(l => `<button type="button" class="mail-label-chip" data-labelfilter="${esc(l)}">${esc(l)}</button>`).join('')}</div>
      <span class="mail-row-acts">
        ${unsub ? `<button class="mail-act" data-unsub="${esc(unsub)}" title="unsubscribe">${_si('x-circle')}</button>` : ''}
        <button class="mail-act" data-label title="add a label">${_si('tag')}</button>
        <button class="mail-act" data-snooze data-snoozed="${snoozed}" title="${snoozed ? 'end snooze' : 'snooze until tomorrow'}">${_si('snooze')}</button>
        <button class="mail-act" data-mute data-muted="${Boolean(m.muted)}" title="${m.muted ? 'unmute thread' : 'mute thread'}">${_si('mute')}</button>
        <button class="mail-act" data-archive title="archive">${_si('archive')}</button>
        <button class="mail-flag${m.flagged ? ' on' : ''}" data-flag title="flag">${_si(m.flagged ? 'star-fill' : 'star')}</button>
      </span>
      ${_active === 'all' ? `<div class="mail-account-badge">${esc(m.account_name || acctName(m.account_id))}</div>` : ''}
    </div>`;
};

function renderInbox(messages, errors = []) {
  const list = $('mail-list');
  const msgTime = m => Number(m.date_ts || 0) || Math.floor((Date.parse(m.date || '') || 0) / 1000);
  messages = [...messages].sort((a, b) => msgTime(b) - msgTime(a));
  _lastMsgs = messages; _mailErrors = errors;
  if (!messages.length && !errors.length) {
    list.innerHTML = `<div class="mail-empty" role="status">nothing in ${esc(_filter)}</div>`;
    return;
  }
  const errHtml = errors.length
    ? `<div class="mail-error-strip" role="alert">${errors.map(esc).join('<br>')} <button type="button" class="btn" id="mail-read-retry">retry</button></div>`
    : '';
  list.innerHTML = errHtml + (_threads ? _renderThreads(messages, msgTime) : messages.map(m => _msgRow(m)).join(''));
  _wireRows(list);
  list.querySelector('#mail-read-retry')?.addEventListener('click', () => _reloadCurrent({ force: true }));
}

function _renderThreads(messages, msgTime) {
  const groups = new Map();
  for (const m of messages) {
    const k = threadKey(m.subject);
    (groups.get(k) || groups.set(k, []).get(k)).push(m);
  }
  const threads = [...groups.entries()].map(([k, msgs]) => {
    msgs.sort((a, b) => msgTime(b) - msgTime(a));
    return { k, msgs, top: msgs[0], unseen: msgs.filter(x => !x.seen).length };
  }).sort((a, b) => msgTime(b.top) - msgTime(a.top));

  return threads.map(t => {
    if (t.msgs.length === 1) return _msgRow(t.top);
    const open = _expanded.has(t.k);
    const head = `
      <div class="mail-row mail-thread-head${t.unseen ? ' unread' : ''}${open ? ' open' : ''}" data-thread="${esc(t.k)}">
        <div class="mail-row-top">
          <span class="mail-from">${esc(fromName(t.top.from))}</span>
          <span class="mail-date">${esc(shortDate(t.top.date))}</span>
        </div>
        <button type="button" class="mail-open mail-subject" aria-expanded="${open}"><span class="mail-thread-caret" aria-hidden="true">${open ? '▾' : '▸'}</span> ${esc(t.top.subject || '(no subject)')} <span class="mail-thread-count">${t.msgs.length}</span></button>
        ${_active === 'all' ? `<div class="mail-account-badge">${esc(t.top.account_name || acctName(t.top.account_id))}</div>` : ''}
      </div>`;
    const kids = open ? t.msgs.map(m => _msgRow(m, true)).join('') : '';
    return head + kids;
  }).join('');
}

function hideRemovesRow(view, hidden) {
  if (_searchView || _labelFilter || !['muted', 'snoozed'].includes(_filter)) return hidden;
  return _filter === view && !hidden;
}

function _wireRows(list) {
  list.querySelectorAll('.mail-thread-head').forEach(h => h.addEventListener('click', () => {
    const k = h.dataset.thread;
    if (_expanded.has(k)) _expanded.delete(k); else _expanded.add(k);
    renderInbox(_lastMsgs);
  }));
  list.querySelectorAll('.mail-row:not(.mail-thread-head)').forEach(r => r.addEventListener('click', () => {
    list.querySelectorAll('.mail-row').forEach(x => x.classList.remove('sel'));
    r.classList.add('sel');
    openMessage(r.dataset.aid, r.dataset.uid, r.dataset.folder);
  }));
  list.querySelectorAll('.mail-flag').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const { aid, uid, folder } = btn.closest('.mail-row').dataset;
    const on = !btn.classList.contains('on');
    changeMail(btn, mailIdentity(aid, uid, folder),
      () => mailJson(`/api/mail/flag/${aid}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(folder)}&flagged=${on}`, { method: 'POST' }),
      result => result?.ok === true && result.flagged === on,
      () => updateMailRows(message => sameMail(message, aid, uid, folder), { flagged: on }),
      on ? 'flag saved' : 'flag removed', 'could not confirm flag change');
  }));
  // 5a triage row actions
  list.querySelectorAll('[data-unsub]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const link = btn.dataset.unsub;
    if (link.startsWith('mailto:')) location.href = link;
    else window.open(link, '_blank', 'noopener');
    toast('opened unsubscribe', '');
  }));
  list.querySelectorAll('[data-mute]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const { aid, uid, folder, subject } = btn.closest('.mail-row').dataset;
    const muted = btn.dataset.muted !== 'true';
    changeMail(btn, mailIdentity(aid, uid, folder), () => mailPost(`/api/mail/mute/${aid}`, { subject, muted }),
      result => Number.isInteger(result?.muted) && result.muted > 0,
      () => updateMailRows(message => message.account_id === aid && threadKey(message.subject) === threadKey(subject), { muted }, hideRemovesRow('muted', muted)),
      muted ? 'thread muted' : 'thread unmuted', `could not confirm ${muted ? 'mute' : 'unmute'}`);
  }));
  list.querySelectorAll('[data-archive]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const { aid, uid, folder } = btn.closest('.mail-row').dataset;
    changeMail(btn, mailIdentity(aid, uid, folder), () => mailPost(`/api/mail/archive/${aid}`, { uid, folder, require_server: true }),
      result => result?.moved_on_server === true,
      () => updateMailRows(message => sameMail(message, aid, uid, folder), {}, true),
      'archived', 'archive is unconfirmed; refresh the mailbox before trying again');
  }));
  list.querySelectorAll('[data-label]').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const { aid, uid, folder } = btn.closest('.mail-row').dataset;
    if (_mailChanges.has(mailIdentity(aid, uid, folder))) return;
    const label = await dlgPrompt('label this message:'); if (!label || !label.trim()) return;
    const target = [...list.querySelectorAll('.mail-row[data-aid]')].find(row => mailIdentity(row.dataset.aid, row.dataset.uid, row.dataset.folder) === mailIdentity(aid, uid, folder))?.querySelector('[data-label]');
    changeMail(target, mailIdentity(aid, uid, folder), () => mailPost(`/api/mail/labels/${aid}`, { uid, folder, add_label: label.trim() }),
      result => result?.ok === true && Array.isArray(result.labels) && result.labels.every(value => typeof value === 'string'),
      result => updateMailRows(row => sameMail(row, aid, uid, folder), { labels: result.labels }),
      'labeled', 'could not confirm label', () => true);
  }));
  list.querySelectorAll('[data-labelfilter]').forEach(c => c.addEventListener('click', e => {
    e.stopPropagation();
    loadByLabel(c.dataset.labelfilter);
  }));
  list.querySelectorAll('[data-snooze]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const { aid, uid, folder } = btn.closest('.mail-row').dataset;
    const until = btn.dataset.snoozed === 'true' ? '' : new Date(Date.now() + 864e5).toISOString();
    changeMail(btn, mailIdentity(aid, uid, folder), () => mailPost(`/api/mail/snooze/${aid}`, { uid, folder, until }),
      result => Number.isInteger(result?.snoozed) && result.snoozed > 0,
      () => updateMailRows(row => sameMail(row, aid, uid, folder), { snoozed_until: until }, hideRemovesRow('snoozed', Boolean(until))),
      until ? 'snoozed until tomorrow' : 'snooze ended', `could not confirm ${until ? 'snooze' : 'ending snooze'}`);
  }));
  paintMailChanges();
}

export async function openMailSource(id, isCurrent = () => true) {
  const match = /^(task|event)-([a-zA-Z0-9_-]+)$/.exec(id);
  if (!match || !isCurrent() || !await prepareMailNavigation()) return false;
  if (!isCurrent()) return false;
  const generation = _messageGeneration;
  const main = $('mail-main');
  main.innerHTML = '<div class="mail-empty" role="status">loading original message…</div>';
  const current = () => generation === _messageGeneration && isCurrent();
  let data;
  try {
    const response = await fetch(`/api/mail/source/${match[1]}/${encodeURIComponent(match[2])}`, { cache: 'no-store' });
    data = await response.json();
    if (!current()) return false;
    if (!response.ok) throw new Error(data.detail?.message || (typeof data.detail === 'string' ? data.detail : 'could not open the original message'));
    if (!data.message || data.source?.kind !== 'mail') throw new Error('could not confirm the original message');
    await openMessage(data.source.account_id, data.source.uid, data.source.folder, data.message, isCurrent);
    if (isCurrent()) {
      const heading = main.querySelector('.mail-reader-subject');
      if (heading) { heading.tabIndex = -1; heading.focus(); }
    }
    return true;
  } catch (error) {
    if (!current()) return false;
    const source = data?.detail?.source;
    main.innerHTML = `<div class="mail-source-error"><p role="status" tabindex="-1">${esc(error.message)}</p>${source ? `<details open><summary>saved excerpt: ${esc(source.label)}</summary><pre>${esc(source.excerpt)}</pre></details>` : ''}<button class="btn" type="button">retry original message</button></div>`;
    main.querySelector('button').onclick = () => openMailSource(id, isCurrent);
    main.querySelector('[role="status"]').focus();
    return true;
  }
}

async function openMessage(aid, uid, folder = 'INBOX', verified = null, isCurrent = () => true) {
  if (!await prepareMailNavigation() || !isCurrent()) return;
  const generation = _messageGeneration;
  if (!verified && readRecordTarget(location.href)?.view === 'mail') {
    const url = new URL(location.href);
    for (const key of ['record', 'record_view', 'occurrence']) url.searchParams.delete(key);
    replaceRouteUrl(url.pathname + url.search + url.hash);
  }
  let reader = null;
  const current = () => Boolean($('mail-view')?.getClientRects().length)
    && (reader ? reader.isConnected : generation === _messageGeneration && isCurrent());
  const main = $('mail-main');
  const hadFocus = main.contains(document.activeElement);
  const restoreFocus = () => {
    if (!hadFocus || document.activeElement !== document.body) return;
    const target = main.querySelector('#mail-message-retry, .mail-reader-subject');
    if (target) { if (!target.matches('button')) target.tabIndex = -1; target.focus(); }
  };
  main.innerHTML = '<div class="mail-empty" role="status">loading message...</div>';
  let m;
  try {
    m = verified || await mailJson(`/api/mail/message/${aid}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(folder)}`);
    if (!current()) return;
    if (m?.error) throw new Error(m.error);
    if (typeof m?.from !== 'string' || typeof m.subject !== 'string' || typeof m.text !== 'string' || typeof m.html !== 'string' || (m.uid != null && String(m.uid) !== String(uid))) throw new Error('could not confirm this message');
  } catch (error) {
    if (current()) {
      main.innerHTML = `<div class="mail-empty" role="alert">could not load message: ${esc(error.message)} <button type="button" class="btn" id="mail-message-retry">retry</button></div>`;
      main.querySelector('button').onclick = () => {
        const target = verified && readRecordTarget(location.href);
        if (target?.view === 'mail') return openMailSource(target.id, isCurrent);
        return openMessage(aid, uid, folder, null, isCurrent);
      };
      restoreFocus();
    }
    return;
  }
  const bodyHtml = m.html
    ? `<div class="mail-reader-meta">remote images are blocked for privacy</div><iframe class="mail-body-frame" sandbox></iframe>`
    : `<pre class="mail-body-text">${esc(m.text || '(no content)')}</pre>`;
  main.innerHTML = `<div class="mail-reader">
    <div class="mail-reader-head">
      <div class="mail-reader-kicker">${esc(acctName(aid))}</div>
      <div class="mail-reader-subject">${esc(m.subject)}</div>
      <div class="mail-reader-meta"><b>${esc(fromName(m.from))}</b> &lt;${esc((/<([^>]+)>/.exec(m.from) || [, m.from])[1])}&gt;</div>
      <div class="mail-reader-meta">to ${esc(m.to)} - ${esc(m.date)}</div>
      <div style="display:flex;gap:0.4rem;flex-wrap:wrap">
        <button class="btn" id="mail-reply">reply</button>
        <button class="btn" id="mail-unread" title="mark as unread">unread</button>
        <button class="btn" id="mail-vip" title="VIP sender">+ VIP</button>
        <button class="btn" id="mail-to-task" title="review a task from this mail">→ task</button>
        <button class="btn" id="mail-to-cal" title="extract and review an event from this mail">→ calendar</button>
        <button class="btn" id="mail-summarize" title="AI summary + action items">summarize</button>
      </div>
    </div>
    <div class="mail-summary" id="mail-summary" style="display:none"></div>
    <div class="mail-reader-body">${bodyHtml}</div>
  </div>`;
  if (m.html) {
    const f = main.querySelector('.mail-body-frame');
    f.srcdoc = mailBodySrcdoc(m.html);
  }
  reader = main.querySelector('.mail-reader');
  // attachment chips — backend lists/serves them, the reader just never showed them
  loadAttachments(aid, uid, folder, current);
  const senderAddr = ((/<([^>]+)>/.exec(m.from) || [, m.from])[1] || '').trim().toLowerCase();
  const unread = $('mail-unread'), vip = $('mail-vip');
  unread.dataset.mailIdentity = mailIdentity(aid, uid, folder);
  const changeRead = seen => changeMail(unread, mailIdentity(aid, uid, folder),
    () => mailJson(`/api/mail/read/${aid}?uid=${encodeURIComponent(uid)}&seen=${seen}&folder=${encodeURIComponent(folder)}`, { method: 'POST' }),
    result => result?.ok === true && result.seen === seen,
    () => {
      const matches = row => sameMail(row, aid, uid, folder);
      const missing = !_lastMsgs.some(matches);
      updateMailRows(matches, { seen });
      if (!seen && missing && _filter === 'unread' && !_searchView && !_labelFilter && folder === 'INBOX' && (_active === 'all' || _active === aid)) loadInbox(true).catch(console.error);
    },
    seen ? '' : 'marked unread', `could not confirm ${seen ? 'read' : 'unread'} status`, seen ? current : null);
  unread.addEventListener('click', () => { if (current() && unread.getAttribute('aria-disabled') !== 'true') changeRead(false); });
  changeRead(true);
  let vipState = null, vipLoading = false;
  const paintVip = on => { vipState = on; vip.classList.toggle('on', on); vip.textContent = on ? 'VIP ★' : '+ VIP'; };
  const loadVip = async () => {
    if (vipLoading || !current()) return;
    vipLoading = true; vip.setAttribute('aria-disabled', 'true');
    try {
      while (_mailChanges.has('vip:' + senderAddr)) {
        await _mailChanges.get('vip:' + senderAddr);
        if (!current()) return;
      }
      const result = await mailJson('/api/mail/vips', { cache: 'no-store' });
      if (!Array.isArray(result?.vips) || result.vips.some(value => typeof value !== 'string')) throw new Error('could not read VIP senders');
      if (current()) paintVip(result.vips.some(value => value.toLowerCase() === senderAddr));
    } catch (error) {
      if (current()) { vip.textContent = 'retry VIP status'; toast(error.message || 'could not read VIP senders', 'error'); }
    } finally { vipLoading = false; vip.setAttribute('aria-disabled', 'false'); }
  };
  loadVip();
  vip.addEventListener('click', () => {
    if (!current() || vipLoading) return;
    if (vipState === null) { loadVip(); return; }
    const adding = !vipState;
    changeMail(vip, 'vip:' + senderAddr, () => mailPost('/api/mail/vips', { email: senderAddr, add: adding }),
      result => Array.isArray(result?.vips) && result.vips.every(value => typeof value === 'string') && result.vips.some(value => value.toLowerCase() === senderAddr) === adding,
      () => { if (current()) paintVip(adding); },
      adding ? 'added to VIP' : 'removed from VIP', 'could not confirm VIP change');
  });
  $('mail-reply')?.addEventListener('click', () => {
    const addr = (/<([^>]+)>/.exec(m.from) || [, m.from])[1];
    compose({
      account_id: aid, to: addr,
      subject: /^re:/i.test(m.subject) ? m.subject : 'Re: ' + m.subject,
      body: `\n\n-- on ${m.date}, ${fromName(m.from)} wrote --\n${(m.text || '').split('\n').map(l => '> ' + l).join('\n')}`,
      in_reply_to: m.message_id || '', references: m.references || '',
    });
  });
  const origin = { account_id: aid, folder, uid: String(uid), ...Object.fromEntries(['message_id', 'from', 'to', 'subject', 'date', 'text', 'html'].map(key => [key, m[key] || ''])) };
  async function reviewCapture(kind, button) {
    const originalLabel = button.textContent;
    button.disabled = true; button.textContent = kind === 'event' ? 'extracting…' : 'preparing…';
    try {
      const response = await fetch(kind === 'task' ? '/api/mail/make-task' : '/api/mail/extract-event', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ preview: true, source: origin, ...(kind === 'task' ? { title: m.subject || `mail from ${fromName(m.from)}` } : { subject: m.subject || '', body: m.text || '', date: m.date || '' }) }),
      });
      const proposal = await response.json();
      if (!current()) return;
      if (!response.ok) throw new Error(typeof proposal.detail === 'string' ? proposal.detail : 'could not prepare the capture');
      if (kind === 'event' && !proposal.found) { toast('no event found in this mail', ''); return; }
      await openCaptureReview(proposal, button);
    } catch (error) { if (current()) toast(error.message || 'could not prepare the capture; try again', 'error'); }
    finally { button.disabled = false; button.textContent = originalLabel; }
  }
  $('mail-to-task')?.addEventListener('click', event => reviewCapture('task', event.currentTarget));
  $('mail-summarize')?.addEventListener('click', async () => {
    const btn = $('mail-summarize');
    const box = $('mail-summary');
    btn.disabled = true; btn.textContent = 'summarizing...';
    try {
      const r = await fetch('/api/mail/summarize', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ subject: m.subject || '', body: m.text || '' }),
      });
      const d = await r.json();
      if (!r.ok) toast(d.detail || 'summarize failed', 'error');
      else { box.textContent = d.summary; box.style.display = 'block'; }
    } catch (e) { console.error(e); toast('summarize failed', 'error'); }
    btn.disabled = false; btn.textContent = 'summarize';
  });
  $('mail-to-cal')?.addEventListener('click', event => reviewCapture('event', event.currentTarget));
  restoreFocus();
}

const fmtBytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;

async function loadAttachments(aid, uid, folder, isCurrent = () => true) {
  let d;
  try {
    d = await fetch(`/api/mail/attachments/${aid}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(folder)}`).then(r => r.json());
  } catch (e) { console.error(e); return; }
  if (!isCurrent()) return;
  const atts = d?.attachments || [];
  if (!atts.length) return;
  const head = $('mail-main')?.querySelector('.mail-reader-head');
  if (!head) return;
  const row = document.createElement('div');
  row.className = 'mail-attach-row';
  row.innerHTML = atts.map(a => {
    const url = `/api/mail/attachment/${aid}?uid=${encodeURIComponent(uid)}&index=${a.index}&folder=${encodeURIComponent(folder)}`;
    return `<a class="mail-attach-chip" href="${esc(url)}" download="${esc(a.filename)}" title="${esc(a.content_type)} · ${fmtBytes(a.size)}">
      <span class="mail-attach-clip">📎</span><span class="mail-attach-name">${esc(a.filename)}</span><span class="mail-attach-size">${fmtBytes(a.size)}</span></a>`;
  }).join('');
  head.appendChild(row);
}

async function compose(pre = {}, generation = null) {
  const outgoingCurrent = () => !pre._outgoing || (sameOutgoing(pre._outgoing, _outboxPending) && _outboxOperation?.action !== 'cleanup');
  if (!outgoingCurrent()) return;
  if (generation === null) {
    if (!await prepareMailNavigation()) return;
    generation = _messageGeneration;
  }
  const currentRead = () => outgoingCurrent() && generation === _messageGeneration && Boolean(document.getElementById('mail-view')?.getClientRects().length);
  if (!currentRead()) return;
  if (!_draftReady) await loadDraftRecovery();
  if (!_outboxReady) await _renderScheduled();
  if (!currentRead()) return;
  // blank new message picks up the saved signature; replies keep their quote untouched
  if (!pre.id && !pre._pending && !pre._outgoing && !pre.body) {
    try {
      const sig = (await fetch('/api/settings').then(r => r.json())).mail_signature;
      if (sig) pre = { ...pre, body: '\n\n' + sig };
    } catch (e) { console.error(e); }
  }
  if (!currentRead()) return;
  const main = document.getElementById('mail-main');
  const defaultAid = pre.account_id || (_active !== 'all' ? _active : _accounts[0]?.id);
  const missingAccount = Boolean(defaultAid && !_accounts.some(account => account.id === defaultAid));
  main.innerHTML = `<div class="mail-compose">
    <div class="mail-form-head">
      <div>
        <div class="mail-compose-head">new message</div>
        <div class="mail-form-sub">from ${esc(acctName(defaultAid))}</div>
      </div>
      <div class="mail-form-actions">
        <button class="btn" id="mc-close">close</button>
        <button class="btn" id="mc-save">save draft</button>
        <button class="btn" id="mc-schedule" title="schedule for later">schedule</button>
        <button class="btn primary" id="mc-send">send</button>
      </div>
    </div>
    <div class="mc-sched-wrap" id="mc-sched-wrap" style="display:none">
      <span class="mc-sched-zone">send at · ${esc(resolvedTimeZone())}</span>
      <input class="settings-input date-input mc-sched-date" id="mc-sched-date" data-type="date" placeholder="date" aria-label="scheduled date">
      <input class="settings-input mc-sched-time" id="mc-sched-time" placeholder="HH:MM" value="09:00" maxlength="5" aria-label="scheduled time">
    </div>
    ${_accounts.length > 1 || missingAccount ? `<div class="settings-input custom-select" id="mc-account" aria-label="sending account"></div>` : ''}
    <div class="mc-chipfield" data-role="to">
      <span class="mc-chip-label">to</span><div class="mc-chips"></div>
      <input class="mc-chip-input" autocomplete="off" placeholder="recipients…">
      <span class="mc-ccbcc"><button type="button" id="mc-add-cc">Cc</button><button type="button" id="mc-add-bcc">Bcc</button></span>
      <input type="hidden" id="mc-to">
    </div>
    <div class="mc-chipfield" data-role="cc" id="mc-cc-row" style="display:none">
      <span class="mc-chip-label">cc</span><div class="mc-chips"></div>
      <input class="mc-chip-input" autocomplete="off"><input type="hidden" id="mc-cc">
    </div>
    <div class="mc-chipfield" data-role="bcc" id="mc-bcc-row" style="display:none">
      <span class="mc-chip-label">bcc</span><div class="mc-chips"></div>
      <input class="mc-chip-input" autocomplete="off"><input type="hidden" id="mc-bcc">
    </div>
    <input class="settings-input" id="mc-subj" placeholder="subject" value="${esc(pre.subject || '')}">
    <div class="mail-richbar" id="mc-richbar">
      <button class="btn mc-rt" data-cmd="bold" title="bold"><b>B</b></button>
      <button class="btn mc-rt" data-cmd="italic" title="italic"><i>I</i></button>
      <button class="btn mc-rt" data-cmd="insertUnorderedList" title="bullet list">•</button>
      <button class="btn mc-rt" data-cmd="createLink" title="link">🔗</button>
      <button class="btn" id="mc-image" title="inline image">🖼</button>
      <button class="btn" id="mc-suggest" title="AI reply suggestions">✨ suggest</button>
      <span class="mail-sig-wrap" id="mc-sig-list"></span>
      <button class="btn" id="mc-sig-add" title="save a new signature">＋ sig</button>
      <button class="btn" type="button" id="mc-sig-manage" aria-expanded="false" aria-controls="mc-sig-manager">manage signatures</button>
      <button class="btn" id="mc-sig-retry" style="display:none">retry signatures</button>
      <span id="mc-sig-status" class="mail-status" role="status"></span>
    </div>
    <section id="mc-sig-manager" aria-label="saved signatures" hidden></section>
    <div class="settings-input mail-compose-body mail-rich-body" id="mc-html" contenteditable="true" role="textbox" aria-label="message" aria-multiline="true" data-ph="write your message…">${pre.body || ''}</div>
    <div id="mc-suggest-box" class="mail-suggest-box"></div>
    <input type="file" id="mc-image-input" accept="image/*" style="display:none">
    <div id="mc-status" class="mail-status"></div>
  </div>`;
  const root = main.querySelector('.mail-compose');
  const $ = id => root.querySelector('#' + id);
  if ($('mc-account')) populateDropdown($('mc-account'), [
    ...(missingAccount ? [{ value: defaultAid, label: 'unavailable account' }] : []),
    ..._accounts.map(a => ({ value: a.id, label: a.name || a.email })),
  ], defaultAid);
  // recipient chip fields + address autocomplete (4d)
  main.querySelectorAll('.mc-chipfield').forEach(f => _initChipField(f));
  if (pre.to) main.querySelector('.mc-chipfield[data-role="to"]')._add(pre.to);
  if (pre.cc) { $('mc-cc-row').style.display = ''; main.querySelector('.mc-chipfield[data-role="cc"]')._add(pre.cc); }
  if (pre.bcc) { $('mc-bcc-row').style.display = ''; main.querySelector('.mc-chipfield[data-role="bcc"]')._add(pre.bcc); }
  $('mc-add-cc')?.addEventListener('click', () => { $('mc-cc-row').style.display = ''; $('mc-cc-row').querySelector('.mc-chip-input').focus(); });
  $('mc-add-bcc')?.addEventListener('click', () => { $('mc-bcc-row').style.display = ''; $('mc-bcc-row').querySelector('.mc-chip-input').focus(); });
  _loadAddrBook();   // warm the autocomplete cache
  let _draftId = pre.id || '';
  const editor = {
    outboxScope: _outboxScopes[0] || '', outgoing: pre._outgoing || null,
    root, draftId: _draftId, scope: pre.recovery_scope || _draftScopes[0] || '', revision: pre.revision || pre.expected_revision || '', pending: pre._pending || null, deleted: false,
    snapshot: () => JSON.stringify([serializeForm(root), getDropdownValue($('mc-account')) || defaultAid]),
    detach: () => { _draftId = ''; editor.draftId = ''; editor.revision = ''; editor.deleted = false; editor.initial = null; },
    accept: row => {
      _draftId = row.id; editor.draftId = row.id; editor.revision = row.revision; editor.deleted = false;
      editor.initial = editor.pendingSnapshot; editor.pending = null;
    },
  };
  editor.initial = editor.snapshot();
  if (editor.pending) { editor.pendingSnapshot = editor.initial; editor.initial = null; }
  if (editor.outgoing) { editor.outgoingSnapshot = editor.initial; editor.initial = null; }
  _mailEditor = editor;
  const current = () => mailEditor() === editor;
  const _draftBody = () => ({
    id: _draftId, account_id: $('mc-account')?.value || defaultAid || '',
    to: $('mc-to').value.trim(), cc: $('mc-cc').value.trim(), bcc: $('mc-bcc').value.trim(),
    subject: $('mc-subj').value, body: draftHtml($('mc-html')),
    in_reply_to: pre.in_reply_to || '', references: pre.references || '',
  });
  // rich-compose toolbar + signatures (5c)
  _wireRichCompose(defaultAid, root, current);
  (pre.id ? $('mc-subj') : main.querySelector('.mc-chip-input'))?.focus();
  $('mc-save').addEventListener('click', async () => {
    if (_draftBusy || !_draftReady || _draftReadError || _draftStorageError) { paintDraftRecovery(); return; }
    if (editor.scope && !_draftScopes.includes(editor.scope)) { paintDraftRecovery(); return; }
    if (_draftPending) {
      if (sameDraftIntent(editor.pending, _draftPending)) await savePendingDraft();
      else toast('resolve the pending draft save first', 'error');
      return;
    }
    if (editor.deleted) {
      const snapshot = editor.snapshot();
      if (!await dlgConfirm('this saved draft was deleted. save this text as a new draft?')) return;
      if (!current() || editor.snapshot() !== snapshot || _draftPending || _draftBusy) return;
      editor.detach();
    }
    if (_draftId && !/^[a-f0-9]{64}$/.test(editor.revision)) { toast('reopen this draft before saving changes', 'error'); return; }
    const pending = { ..._draftBody(), recovery_scope: editor.scope || _draftScopes[0], ...(_draftId ? { expected_revision: editor.revision } : { request_id: savedRequestId() }) };
    try {
      storePendingDraft(pending, editor, editor.snapshot());
      await savePendingDraft();
    } catch {
      _draftStorageError = 'could not keep this save for recovery. no save was sent. retry loading drafts.';
      paintDraftRecovery();
    }
  });
  paintDraftRecovery();
  $('mc-close').addEventListener('click', async () => {
    if (!await prepareMailNavigation()) return;
    document.getElementById('mail-list').querySelector(`.mail-draft-row[data-id="${CSS.escape(_draftId)}"] .mail-open`)?.focus();
  });
  const _composeBody = () => {
    const el = $('mc-html');
    return {
      to: $('mc-to').value.trim(), cc: $('mc-cc').value.trim(), bcc: $('mc-bcc').value.trim(),
      subject: $('mc-subj').value, body: el?.innerText || '', html: draftHtml(el),
      in_reply_to: pre.in_reply_to || '', references: pre.references || '',
    };
  };
  const queueCompose = async (action, send_at = '') => {
    if (!_outboxReady || _outboxOperation || _outboxPending || _outboxReadError || _outboxStorageError) { paintOutbox(); return; }
    if (editor.outboxScope && !_outboxScopes.includes(editor.outboxScope)) { toast('reopen the editor for this mail store; your text is still here', 'error'); return; }
    if (_draftPending) { toast('resolve the pending draft save before sending', 'error'); paintDraftRecovery(); return; }
    const account_id = $('mc-account')?.value || defaultAid;
    if (!_accounts.some(account => account.id === account_id)) { toast('choose an available sending account', 'error'); return; }
    if (!$('mc-to').value.trim()) { toast('recipient required', 'error'); return; }
    const pending = {
      version: 1, action, request_id: savedRequestId(), recovery_scope: _outboxScopes[0], account_id,
      subject: $('mc-subj').value,
      message: { ..._composeBody(), ...(action === 'send' ? { delay: 8 } : { send_at }) },
      ...(_draftId ? { draft: { id: _draftId, revision: editor.revision, scope: editor.scope } } : {}),
    };
    try { storePendingOutgoing(pending, editor, editor.snapshot()); }
    catch { _outboxStorageError = 'could not retain this delivery for recovery. no new delivery request was sent.'; paintOutbox(); return; }
    await submitOutgoing();
  };
  $('mc-schedule').addEventListener('click', async () => {
    if ($('mc-schedule').getAttribute('aria-disabled') === 'true') return;
    const wrap = $('mc-sched-wrap');
    if (wrap.style.display === 'none') {
      wrap.style.display = ''; _dpInit($('mc-sched-date'));
      $('mc-schedule').textContent = 'schedule send'; $('mc-sched-date').focus(); return;
    }
    try {
      const date = $('mc-sched-date').value.trim(), time = $('mc-sched-time').value.trim();
      const instant = reminderTimeFromWall(`${date}T${time}`);
      if (instant.getTime() <= Date.now()) throw new Error('choose a future date and time');
      await queueCompose('schedule', instant.toISOString());
    } catch (error) { toast(error.message || 'choose a valid date and time', 'error'); }
  });
  $('mc-send').addEventListener('click', () => queueCompose('send'));
  paintOutbox();
  return editor;
}

async function _wireRichCompose(defaultAid, root, current) {
  const $ = id => root.querySelector('#' + id);
  const toolbar = $('mc-richbar');
  if (!toolbar.dataset.bound) {
    toolbar.dataset.bound = '1';
    toolbar.querySelectorAll('.mc-rt').forEach(button => {
      button.addEventListener('mousedown', event => event.preventDefault());
      button.addEventListener('click', async () => {
        if (!current()) return;
        const editor = $('mc-html'), selection = window.getSelection();
        const range = selection?.rangeCount && editor.contains(selection.getRangeAt(0).commonAncestorContainer)
          ? selection.getRangeAt(0).cloneRange() : null;
        const command = button.dataset.cmd;
        const value = command === 'createLink' ? await dlgPrompt('link URL:') : null;
        if (!current() || (command === 'createLink' && !value)) return;
        editor.focus();
        if (range && editor.contains(range.commonAncestorContainer)) {
          selection.removeAllRanges(); selection.addRange(range);
        }
        document.execCommand(command, false, value);
      });
    });
    $('mc-suggest')?.addEventListener('click', async () => {
      const box = $('mc-suggest-box'); if (!box) return;
      box.innerHTML = '<span class="mail-suggest-off">thinking…</span>';
      const ctx = $('mc-html')?.innerText || $('mc-subj')?.value || '';
      let d;
      try { d = await fetch('/api/mail/smart-reply', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: ctx }) }).then(r => r.json()); }
      catch (e) { console.error(e); d = { enabled: false, suggestions: [] }; }
      if (!current()) return;
      if (!d.enabled) { box.innerHTML = '<span class="mail-suggest-off">configure a model in aide to get reply suggestions</span>'; return; }
      if (!d.suggestions.length) { box.innerHTML = '<span class="mail-suggest-off">no suggestions</span>'; return; }
      box.innerHTML = d.suggestions.map((s, i) => `<button class="btn mc-suggest-chip" data-i="${i}">${esc(s.slice(0, 80))}</button>`).join('');
      box.querySelectorAll('.mc-suggest-chip').forEach((bn, i) => bn.addEventListener('click', () => {
        const ed = $('mc-html'); if (ed) ed.innerHTML += esc(d.suggestions[i]).replace(/\n/g, '<br>');
      }));
    });
    $('mc-image')?.addEventListener('click', () => $('mc-image-input')?.click());
    $('mc-image-input')?.addEventListener('change', async e => {
      const f = e.target.files?.[0]; if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      try {
        const up = await fetch('/api/uploads', { method: 'POST', body: fd }).then(r => r.json());
        if (!current()) return;
        const ed = $('mc-html'); ed?.focus();
        document.execCommand('insertHTML', false, `<img src="/api/uploads/${up.id}" alt="${esc(up.name || '')}" style="max-width:100%">`);
      } catch (e) { console.error(e); toast('image upload failed', 'error'); }
    });
  }
  const list = $('mc-sig-list'), status = $('mc-sig-status'), retry = $('mc-sig-retry');
  const manage = $('mc-sig-manage'), panel = $('mc-sig-manager');
  let sigs = [], readGeneration = 0, managerOpen = false, signatureBusy = false, pendingRemoval = null;
  const validSignature = signature => signature && ['id', 'name', 'body'].every(key => typeof signature[key] === 'string') && signature.id;
  const revisionOf = signature => signature.revision === undefined ? 0 : signature.revision;
  const readSignatures = async () => {
    const data = await mailJson('/api/mail/signatures', { cache: 'no-store', signal: AbortSignal.timeout(15000) });
    if (!Array.isArray(data?.signatures) || !data.signatures.every(validSignature)) throw new Error('could not confirm the signature list');
    return data.signatures;
  };
  const renderSignatures = () => {
    if (!current()) return;
    const active = document.activeElement;
    const focused = [list, panel].some(node => node.contains(active)) ? { ...active.dataset } : null;
    list.innerHTML = sigs.map(s => `<button class="btn mc-sig-chip" data-sig="${esc(s.id)}" title="insert signature">✎ ${esc(s.name)}</button>`).join('');
    list.querySelectorAll('.mc-sig-chip').forEach(button => button.addEventListener('click', () => {
      if (!current()) return;
      const signature = sigs.find(row => row.id === button.dataset.sig);
      if (!signature) return;
      $('mc-html').innerHTML += `<div class="mail-sig" data-sig>--<br>${esc(signature.body).replace(/\n/g, '<br>')}</div>`;
    }));
    manage.setAttribute('aria-expanded', String(managerOpen)); panel.hidden = !managerOpen;
    $('mc-sig-add').setAttribute('aria-disabled', String(signatureBusy));
    panel.innerHTML = sigs.length ? sigs.map(s => `<div class="mail-rule-row"><span>${esc(s.name || 'signature')}</span><div class="mail-rule-actions">
      <button class="btn" type="button" data-sig-edit="${esc(s.id)}" aria-label="edit ${esc(s.name || 'signature')}" aria-disabled="${signatureBusy}">edit</button>
      <button class="btn" type="button" data-sig-remove="${esc(s.id)}" aria-label="remove ${esc(s.name || 'signature')}" aria-disabled="${signatureBusy || Boolean(pendingRemoval)}">remove</button>
    </div></div>`).join('') : '<p class="mail-status">no saved signatures</p>';
    panel.querySelectorAll('[data-sig-edit]').forEach(button => button.addEventListener('click', () => {
      const signature = sigs.find(row => row.id === button.dataset.sigEdit);
      if (signature) editSignature(signature);
    }));
    panel.querySelectorAll('[data-sig-remove]').forEach(button => button.addEventListener('click', async () => {
      if (!current() || signatureBusy || pendingRemoval) return;
      const signature = sigs.find(row => row.id === button.dataset.sigRemove);
      if (!signature) return;
      const revision = revisionOf(signature);
      if (!Number.isSafeInteger(revision) || revision < 0) { status.textContent = 'could not confirm this signature version; reload signatures.'; retry.style.display = ''; return; }
      signatureBusy = true; renderSignatures();
      const confirmed = await dlgConfirm(`remove “${signature.name || 'signature'}” from saved signatures? text already inserted in messages stays unchanged.`);
      signatureBusy = false;
      if (!current()) return;
      if (confirmed) { pendingRemoval = { id: signature.id, revision }; await removeSignature(); }
      else renderSignatures();
    }));
    if (pendingRemoval) {
      const action = document.createElement('button'); action.className = 'btn'; action.type = 'button'; action.dataset.sigRetry = pendingRemoval.id;
      action.textContent = 'retry signature removal'; action.setAttribute('aria-disabled', String(signatureBusy));
      action.addEventListener('click', removeSignature); panel.appendChild(action);
    }
    if (focused && document.activeElement === document.body) {
      const match = [...list.querySelectorAll('button'), ...panel.querySelectorAll('button')].find(button => Object.keys(focused).some(key => key.startsWith('sig') && button.dataset[key] === focused[key]));
      (match || manage).focus();
    }
  };
  const loadSignatures = async () => {
    const generation = ++readGeneration;
    const restoreFocus = document.activeElement === retry;
    retry.disabled = true; status.textContent = 'loading signatures…';
    try {
      const rows = await readSignatures();
      if (!current() || generation !== readGeneration) return;
      sigs = rows;
      if (pendingRemoval) {
        const row = rows.find(item => item.id === pendingRemoval.id);
        if (!row || revisionOf(row) > pendingRemoval.revision) pendingRemoval = null;
      }
      renderSignatures(); status.textContent = pendingRemoval ? 'signature removal is still unconfirmed. retry removal or review the saved signature.' : '';
      retry.style.display = pendingRemoval ? '' : 'none';
    } catch (error) {
      if (!current() || generation !== readGeneration) return;
      status.textContent = `could not load signatures. ${error.message || 'check your connection.'}`; retry.style.display = '';
    } finally {
      if (generation === readGeneration) {
        retry.disabled = false;
        if (current() && restoreFocus && document.activeElement === document.body) {
          (retry.style.display === 'none' ? manage : retry).focus();
        }
      }
    }
  };
  async function removeSignature() {
    if (!current() || signatureBusy || !pendingRemoval) return;
    const attempt = pendingRemoval; signatureBusy = true; ++readGeneration;
    status.textContent = 'removing signature…'; renderSignatures();
    let confirmed = false, error;
    try {
      const result = await mailJson(`/api/mail/signatures/${encodeURIComponent(attempt.id)}?expected_revision=${attempt.revision}`, { method: 'DELETE', signal: AbortSignal.timeout(15000) });
      if (result?.ok !== true) throw new Error('could not confirm signature removal');
      confirmed = true;
    } catch (failure) {
      error = failure;
      try { confirmed = !(await readSignatures()).some(row => row.id === attempt.id); } catch { /* Keep the captured removal available for retry. */ }
    } finally { signatureBusy = false; }
    if (!current()) return;
    ++readGeneration;
    const retryFocused = document.activeElement === retry || document.activeElement === document.body;
    retry.disabled = false;
    if (confirmed) {
      sigs = sigs.filter(row => row.id !== attempt.id); pendingRemoval = null; renderSignatures();
      status.textContent = 'signature removed'; retry.style.display = 'none';
      if (retryFocused) manage.focus();
    } else {
      status.textContent = `signature removal unconfirmed. ${error?.message || 'check your connection and retry.'}`;
      retry.style.display = ''; renderSignatures();
    }
  }
  async function editSignature(original = null) {
    if (!current() || signatureBusy) return;
    const baseline = original ? revisionOf(original) : 0;
    if (!Number.isSafeInteger(baseline) || baseline < 0) { status.textContent = 'could not confirm this signature version; reload signatures.'; retry.style.display = ''; return; }
    signatureBusy = true; ++readGeneration; renderSignatures();
    const id = original?.id || savedRequestId();
    let confirmed, attempt = null;
    try {
      const values = await dlgFields(original ? 'edit signature' : 'signature', [
        { id: 'name', label: 'name', value: original?.name || '' },
        { id: 'body', label: 'signature text', multiline: true, value: original?.body || '' },
      ], { submit: async fields => {
        if (!current()) throw new Error('the original message is no longer open; your signature text is still here');
        const desired = { id, name: fields.name.trim(), body: fields.body };
        if (!desired.name) throw new Error('enter a signature name');
        const unchanged = attempt && ['name', 'body'].every(key => attempt[key] === desired[key]);
        let latestRevision = baseline;
        if (original) {
          let rows;
          try { rows = await readSignatures(); }
          catch { throw new Error('could not check the saved signature. check your connection and retry.'); }
          const latest = rows.find(row => row.id === id);
          if (!current()) throw new Error('the original message is no longer open; your signature text is still here');
          if (!latest) throw new Error('this signature was removed. copy this text, cancel, then add a new signature.');
          latestRevision = revisionOf(latest);
          const same = row => row && ['id', 'name', 'body'].every(key => row[key] === latest[key]);
          if (!Number.isSafeInteger(latestRevision) || latestRevision < 0 ||
              !(same(original) && latestRevision === baseline) && !(same(attempt) && latestRevision >= attempt.revision)) {
            throw new Error('this signature changed. copy your edits, cancel, then reload signatures to review the current version.');
          }
          desired.expected_revision = latestRevision;
        }
        desired.revision = unchanged ? attempt.revision : Math.max(attempt?.revision ?? baseline, latestRevision) + 1;
        attempt = desired;
        const matches = row => validSignature(row) && Number.isInteger(row.revision) && row.revision >= desired.revision && ['id', 'name', 'body'].every(key => row[key] === desired[key]);
        try {
          const row = await mailJson('/api/mail/signatures', {
            method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(desired), signal: AbortSignal.timeout(15000),
          });
          if (!matches(row)) throw new Error('could not confirm the saved signature');
          confirmed = row;
        } catch (error) {
          try { confirmed = (await readSignatures()).find(matches); } catch { /* Keep the original save error and form for retry. */ }
          if (!confirmed) throw new Error(error.status === 410 ? 'this signature was removed. copy this text, cancel, then add a new signature.' : `save unconfirmed. ${error.message || 'check your connection and retry.'}`);
        }
      } });
      if (!values || !confirmed || !current()) return;
      if (pendingRemoval?.id === confirmed.id && confirmed.revision > pendingRemoval.revision) pendingRemoval = null;
      sigs = [...sigs.filter(row => row.id !== confirmed.id), confirmed]; renderSignatures(); toast('signature saved', 'success');
    } finally {
      signatureBusy = false;
      if (current()) { renderSignatures(); await loadSignatures(); }
    }
  }
  retry.addEventListener('click', loadSignatures);
  manage.addEventListener('click', () => { managerOpen = !managerOpen; renderSignatures(); });
  $('mc-sig-add').addEventListener('click', () => editSignature());
  await loadSignatures();
}

const OUTGOING_PREFIX = 'alles-mail-outbox:';
const OUTGOING_FIELDS = ['to', 'cc', 'bcc', 'subject', 'body', 'html', 'in_reply_to', 'references'];
const OUTGOING_STATES = ['scheduled', 'sending', 'sent', 'uncertain', 'canceled'];
let _outboxScopes = [], _outboxRows = [], _outboxPending = null, _outboxKnown = null;
let _outboxRead = 0, _outboxReady = false, _outboxOperation = null;
let _outboxAnnounced = '';
let _outboxReadError = '', _outboxStorageError = '', _outboxNotice = '', _outboxConflict = false;
const outgoingKey = scope => OUTGOING_PREFIX + scope;
const outgoingHtml = message => message.html || esc(message.body).replace(/\r\n?|\n/g, '<br>');
const sameOutgoing = (a, b) => Boolean(a && b && JSON.stringify(a) === JSON.stringify(b));
const outgoingInstant = value => new Date(value + (/(Z|[+-]\d\d:\d\d)$/.test(value) ? '' : 'Z')).getTime();
const validOutgoingRow = row => row && typeof row.id === 'string' && row.id && typeof row.account_id === 'string' && OUTGOING_FIELDS.every(key => typeof row[key] === 'string') && OUTGOING_STATES.includes(row.status) && typeof row.send_at === 'string';
function outgoingMatches(row, pending) {
  if (row.id !== pending.request_id) return false;
  if (pending.action === 'cancel' || row.request_kind === 'canceled-before-queue') return true;
  return row.account_id === pending.account_id && row.request_kind === pending.action && OUTGOING_FIELDS.every(key => row[key] === pending.message[key]) && (pending.action === 'send' ? row.request_delay === pending.message.delay : outgoingInstant(row.send_at) === outgoingInstant(pending.message.send_at));
}
function readPendingOutgoing() {
  _outboxStorageError = '';
  try {
    let pending = null;
    for (const scope of _outboxScopes) {
      const raw = sessionStorage.getItem(outgoingKey(scope));
      if (!raw) continue;
      const value = JSON.parse(raw), queue = value?.action !== 'cancel';
      if (value?.version !== 1 || value.recovery_scope !== scope || typeof value.request_id !== 'string' || !value.request_id || !['send', 'schedule', 'cancel'].includes(value.action) || typeof value.subject !== 'string' || (queue && (!/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.request_id) || typeof value.account_id !== 'string' || !OUTGOING_FIELDS.every(key => typeof value.message?.[key] === 'string') || (value.action === 'send' ? !Number.isSafeInteger(value.message.delay) || value.message.delay < 1 : !Number.isFinite(outgoingInstant(value.message.send_at || '')))))) throw new Error('invalid recovery record');
      if (pending && !sameOutgoing(pending, value)) throw new Error('more than one recovery record');
      pending = value;
    }
    if (!sameOutgoing(pending, _outboxPending)) _outboxKnown = null;
    _outboxPending = pending;
  } catch { _outboxStorageError = 'could not read delivery recovery data. retry loading, or review Sent and the outbox before clearing it.'; }
}
function storePendingOutgoing(pending, editor, snapshot) {
  ++_outboxRead;
  const raw = JSON.stringify(pending), key = outgoingKey(pending.recovery_scope);
  sessionStorage.setItem(key, raw);
  _outboxPending = pending; _outboxKnown = null; _outboxConflict = false; _outboxNotice = '';
  if (editor) { editor.outgoing = pending; editor.outgoingSnapshot = snapshot; }
  if (sessionStorage.getItem(key) !== raw) throw new Error('could not retain delivery recovery data');
}
function retireOutgoing() {
  if (_outboxOperation) _outboxOperation.retired = true;
  _outboxOperation = null;
}
function clearPendingOutgoing(pending) {
  for (const scope of _outboxScopes) {
    const key = outgoingKey(scope), raw = sessionStorage.getItem(key);
    if (raw && sameOutgoing(JSON.parse(raw), pending)) {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error('could not clear delivery recovery data');
    }
  }
  if (sameOutgoing(pending, _outboxPending)) { _outboxPending = null; _outboxKnown = null; }
}
function outgoingStatus(row) {
  if (row.status === 'sending') return 'delivery has started; cancellation is no longer available';
  if (row.status === 'uncertain') return 'delivery is uncertain. check Sent before sending again';
  if (row.status === 'sent') return 'sent';
  if (row.status === 'canceled') return 'delivery canceled';
  const instant = new Date(outgoingInstant(row.send_at));
  return Number.isFinite(instant.getTime()) ? `scheduled for ${formatDate(instant)} ${formatTime(instant, { hour: '2-digit', minute: '2-digit' })}` : 'scheduled time unavailable';
}
function paintOutbox() {
  const bar = $('mail-outbox-recovery'), strip = $('mail-scheduled');
  if (!bar || !strip) return;
  const focused = bar.contains(document.activeElement) || strip.contains(document.activeElement) ? document.activeElement.id : '';
  const pending = _outboxPending, busy = Boolean(_outboxOperation);
  let message = _outboxReadError || _outboxStorageError || _outboxNotice;
  if (!message && pending) message = pending.cancel_requested || pending.action === 'cancel' ? 'cancellation is unconfirmed. check the current outcome or retry cancellation.' : `delivery of “${pending.subject.trim() || 'untitled message'}” is unconfirmed. retry uses the same request.`;
  if (busy) message = _outboxOperation.action === 'cancel' ? 'canceling delivery…' : (_outboxOperation.action === 'cleanup' ? 'removing the saved draft…' : 'queueing message…');
  const button = (id, label, blocked = busy) => `<button type="button" class="btn" id="${id}" aria-disabled="${blocked}">${label}</button>`;
  let actions = '';
  if (pending || _outboxReadError || _outboxStorageError) actions += button('mail-outbox-check', 'check delivery status', false);
  if (_outboxStorageError) actions += button('mail-outbox-clear', 'clear recovery data');
  else if (pending) {
    if (_outboxKnown && (_outboxKnown.status !== 'scheduled' || !(pending.cancel_requested || pending.action === 'cancel'))) {
      actions += button('mail-outbox-finish', _outboxKnown.status === 'canceled' ? 'dismiss canceled message' : (pending.draft ? 'retry draft cleanup' : 'retry cleanup'));
      if (pending.draft && _outboxKnown.status !== 'canceled') actions += button('mail-outbox-keep-draft', 'keep saved draft');
    } else if (!_outboxConflict && !pending.cancel_requested && pending.action !== 'cancel') actions += button('mail-outbox-retry', 'retry delivery request', busy || Boolean(_outboxReadError));
    if (!_outboxConflict && (!_outboxKnown || _outboxKnown.status === 'scheduled')) actions += button('mail-outbox-cancel', pending.cancel_requested || pending.action === 'cancel' ? 'retry cancellation' : 'cancel delivery', Boolean(busy && _outboxOperation.action === 'cancel'));
    if (pending.action !== 'cancel' || _outboxKnown?.status === 'canceled') actions += button('mail-outbox-open', _outboxKnown?.status === 'canceled' ? 'open canceled message' : 'open pending message', busy && _outboxOperation.action === 'cleanup');
    if (_outboxConflict) actions += button('mail-outbox-forget', 'dismiss recovery');
  }
  bar.hidden = !message && !actions;
  bar.innerHTML = message || actions ? `<div class="mail-saved-status"><p id="mail-outbox-status" role="status" tabindex="-1">${esc(message)}</p>${actions}</div>` : '';
  $('mail-outbox-check')?.addEventListener('click', () => _renderScheduled());
  $('mail-outbox-retry')?.addEventListener('click', () => submitOutgoing());
  $('mail-outbox-cancel')?.addEventListener('click', () => cancelOutgoing());
  $('mail-outbox-finish')?.addEventListener('click', () => finishOutgoing(_outboxPending, _outboxKnown, _outboxKnown?.status === 'canceled'));
  $('mail-outbox-keep-draft')?.addEventListener('click', () => finishOutgoing(_outboxPending, _outboxKnown, true));
  $('mail-outbox-clear')?.addEventListener('click', () => forgetOutgoing(true));
  $('mail-outbox-forget')?.addEventListener('click', () => forgetOutgoing(false));
  $('mail-outbox-open')?.addEventListener('click', async () => {
    const p = _outboxPending, row = _outboxKnown;
    if (!p || _outboxOperation?.action === 'cleanup' || (p.action === 'cancel' && row?.status !== 'canceled')) return;
    const message = p.action === 'cancel' ? row : p.message;
    const recovered = await compose({ ...message, id: '', body: outgoingHtml(message), account_id: p.account_id || row.account_id, _outgoing: p });
    if (row?.status === 'canceled' && recovered && mailEditor() === recovered && recovered.snapshot() === recovered.outgoingSnapshot && sameOutgoing(recovered.outgoing, p)) await finishOutgoing(p, row, true);
  });
  strip.innerHTML = _outboxRows.length ? '<span class="mail-sched-lbl">outbox</span>' + _outboxRows.map(row => `<span class="mail-sched-chip"><span>${esc(row.subject || '(no subject)')} · ${esc(outgoingStatus(row))}</span>${row.status === 'scheduled' ? `<button type="button" class="mail-sched-cancel" id="mail-outbox-cancel-${esc(row.id)}" data-cancel="${esc(row.id)}" aria-label="cancel ${esc(row.subject || 'untitled message')}" aria-disabled="${Boolean(pending || busy || _outboxReadError || _outboxStorageError)}">cancel</button>` : ''}</span>`).join('') : '';
  strip.querySelectorAll('[data-cancel]').forEach(button => button.addEventListener('click', () => {
    if (button.getAttribute('aria-disabled') !== 'true') cancelOutgoing(_outboxRows.find(row => row.id === button.dataset.cancel));
  }));
  const editor = mailEditor();
  if (editor) for (const id of ['mc-send', 'mc-schedule']) editor.root.querySelector('#' + id)?.setAttribute('aria-disabled', String(!_outboxReady || busy || Boolean(pending || _outboxReadError || _outboxStorageError || (editor.outboxScope && !_outboxScopes.includes(editor.outboxScope)))));
  if (focused && document.activeElement === document.body) {
    const target = document.getElementById(focused) || (!bar.hidden ? $('mail-outbox-status') : editor?.root.querySelector('#mc-send') || $('mail-compose-btn'));
    if (target?.getClientRects().length) target.focus();
  }
}
async function _renderScheduled() {
  const generation = ++_outboxRead;
  try {
    const data = await mailJson('/api/mail/scheduled?context=true', { cache: 'no-store' });
    if (!Array.isArray(data?.scheduled) || data.scheduled.some(row => !validOutgoingRow(row)) || !Array.isArray(data.recovery_scopes) || !data.recovery_scopes.length || data.recovery_scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error('could not read outbox');
    if (generation !== _outboxRead) return;
    if (!_outboxScopes.some(scope => data.recovery_scopes.includes(scope))) {
      retireOutgoing(); _outboxPending = null; _outboxKnown = null; _outboxNotice = ''; _outboxConflict = false;
      $('mail-undo-bar')?.remove();
    }
    _outboxScopes = data.recovery_scopes; _outboxRows = data.scheduled; _outboxReady = true; _outboxReadError = '';
    readPendingOutgoing();
    const pending = _outboxPending;
    if (pending && !_outboxStorageError) {
      const result = await mailJson(`/api/mail/scheduled?request_id=${encodeURIComponent(pending.request_id)}&recovery_scope=${encodeURIComponent(pending.recovery_scope)}`, { cache: 'no-store' });
      if (generation !== _outboxRead || !sameOutgoing(pending, _outboxPending)) return;
      if (!Array.isArray(result?.scheduled) || result.scheduled.length > 1 || result.scheduled.some(row => !validOutgoingRow(row) || row.id !== pending.request_id)) throw new Error('could not confirm delivery status');
      const row = result.scheduled[0];
      _outboxKnown = null; _outboxConflict = false;
      if (row) {
        if (!outgoingMatches(row, pending)) { _outboxConflict = true; _outboxNotice = 'this request belongs to a different message. review the outbox and Sent before dismissing recovery.'; retireOutgoing(); }
        else {
          _outboxKnown = row;
          _outboxRows = _outboxRows.filter(value => value.id !== row.id);
          if (['scheduled', 'sending', 'uncertain'].includes(row.status)) _outboxRows.push(row);
          if (!(pending.cancel_requested || pending.action === 'cancel') || row.status !== 'scheduled') {
            retireOutgoing();
            await finishOutgoing(pending, row);
          }
        }
      }
    }
  } catch (error) { if (generation === _outboxRead) _outboxReadError = `could not check the outbox. ${error.message || 'retry loading.'}`; }
  if (generation === _outboxRead || !_outboxOperation) paintOutbox();
}
async function finishOutgoing(pending, row, keepDraft = false) {
  if (!pending || !row || !sameOutgoing(pending, _outboxPending) || !_outboxScopes.includes(pending.recovery_scope) || _outboxOperation) return;
  const canceled = row.status === 'canceled', cancel = pending.cancel_requested || pending.action === 'cancel';
  const editor = mailEditor();
  const owns = editor?.outgoing?.request_id === pending.request_id && editor.outgoing.recovery_scope === pending.recovery_scope;
  _outboxNotice = cancel && !canceled ? `could not cancel: ${outgoingStatus(row)}` : outgoingStatus(row);
  if (canceled) {
    const undo = $('mail-undo-bar'); if (undo?.dataset.id === row.id) undo.remove();
    if (!keepDraft && !(owns && editor.snapshot() === editor.outgoingSnapshot)) {
      if (editor) { paintOutbox(); return; }
      const message = pending.action === 'cancel' ? row : pending.message;
      await compose({ ...message, id: '', body: outgoingHtml(message), account_id: pending.account_id || row.account_id, _outgoing: pending });
      if (!sameOutgoing(pending, _outboxPending) || !sameOutgoing(mailEditor()?.outgoing, pending)) return;
    }
    if (owns) editor.outgoing = null;
  } else {
    if (owns) {
      editor.outgoing = null;
      if (editor.snapshot() === editor.outgoingSnapshot) clearMailEditor(editor);
    }
    if (_outboxAnnounced !== pending.request_id) {
      _outboxAnnounced = pending.request_id;
      toast(row.status === 'scheduled' ? 'scheduled' : outgoingStatus(row), row.status === 'uncertain' ? 'error' : 'success');
    }
    if (row.request_kind === 'send' && row.status === 'scheduled') _showUndoBar(row, pending.recovery_scope);
  }
  // Once accepted, newer text is a separate draft even if cleanup's reply is lost.
  if (!canceled && pending.draft) {
    const live = mailEditor(), draft = pending.draft;
    if (live?.draftId === draft.id && live.revision === draft.revision && _draftScopes.includes(live.scope) && _draftScopes.includes(draft.scope)) { live.detach(); paintDraftRecovery(); }
  }
  if (!canceled && pending.draft && !keepDraft) {
    const operation = { pending, action: 'cleanup', retired: false };
    _outboxOperation = operation; ++_outboxRead; paintOutbox();
    try {
      const draft = pending.draft;
      if (!draft.id || !/^[a-f0-9]{64}$/.test(draft.revision) || !_draftScopes.includes(draft.scope)) throw new Error('reopen the saved draft to remove it');
      await mailJson(`/api/mail/drafts/${encodeURIComponent(draft.id)}?expected_revision=${encodeURIComponent(draft.revision)}&recovery_scope=${encodeURIComponent(draft.scope)}`, { method: 'DELETE' });
      const live = mailEditor();
      if (live?.draftId === draft.id && live.revision === draft.revision && _draftScopes.includes(live.scope) && _draftScopes.includes(draft.scope)) { live.detach(); paintDraftRecovery(); }
      if (operation.retired || !sameOutgoing(pending, _outboxPending)) return;
    } catch (error) {
      if (operation.retired) return;
      if (![404, 409].includes(error.status)) { _outboxNotice = `${outgoingStatus(row)}. could not remove the saved draft; retry cleanup or keep it.`; return; }
      _outboxNotice += error.status === 409 ? '. the saved draft changed and was kept.' : '. the saved draft is already absent.';
    } finally { if (_outboxOperation === operation) _outboxOperation = null; paintOutbox(); }
  }
  try { clearPendingOutgoing(pending); readPendingOutgoing(); }
  catch { _outboxNotice += '. recovery data could not be cleared; retry cleanup.'; }
  if (canceled) { const undo = $('mail-undo-bar'); if (undo?.dataset.id === row.id) undo.remove(); }
  paintOutbox();
}
async function submitOutgoing() {
  const pending = _outboxPending;
  if (!pending || pending.action === 'cancel' || pending.cancel_requested || _outboxOperation || _outboxKnown || _outboxConflict || _outboxReadError || _outboxStorageError) return;
  if (pending.action === 'schedule' && outgoingInstant(pending.message.send_at) <= Date.now()) {
    if (!await dlgConfirm('this scheduled time has passed. retrying the same request may send it now. retry?')) return;
    if (!sameOutgoing(pending, _outboxPending) || _outboxOperation || _outboxKnown) return;
  }
  const operation = { pending, action: 'queue', retired: false };
  _outboxOperation = operation; ++_outboxRead; _outboxNotice = ''; paintOutbox();
  try {
    await mailJson(`/api/mail/${pending.action === 'send' ? 'send-undoable' : 'schedule'}/${encodeURIComponent(pending.account_id)}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...pending.message, request_id: pending.request_id, recovery_scope: pending.recovery_scope }) });
  } catch (error) { if (!operation.retired && sameOutgoing(pending, _outboxPending)) _outboxNotice = `delivery request unconfirmed. ${error.message || 'check its status or retry.'}`; }
  finally { if (_outboxOperation === operation) _outboxOperation = null; paintOutbox(); }
  if (!operation.retired && sameOutgoing(pending, _outboxPending)) await _renderScheduled();
}
async function cancelOutgoing(row = null, scope = _outboxScopes[0]) {
  if (_outboxStorageError || !_outboxReady || (_outboxOperation && _outboxOperation.action === 'cancel') || _outboxConflict) return;
  let pending = _outboxPending;
  if (row) {
    if (pending || row.status !== 'scheduled' || !_outboxScopes.includes(scope)) return;
    pending = { version: 1, action: 'cancel', request_id: row.id, recovery_scope: scope, subject: row.subject };
  } else if (!pending || (_outboxKnown && _outboxKnown.status !== 'scheduled')) return;
  else pending = { ...pending, cancel_requested: true };
  try { storePendingOutgoing(pending); }
  catch { _outboxStorageError = 'could not retain cancellation for recovery. no cancellation was sent.'; paintOutbox(); return; }
  retireOutgoing();
  const operation = { pending, action: 'cancel', retired: false };
  _outboxOperation = operation; paintOutbox();
  try {
    const reserve = /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(pending.request_id);
    await mailJson(`/api/mail/scheduled/${encodeURIComponent(pending.request_id)}/cancel?recovery_scope=${encodeURIComponent(pending.recovery_scope)}&reserve_if_missing=${reserve}`, { method: 'POST' });
  } catch (error) { if (!operation.retired && sameOutgoing(pending, _outboxPending)) _outboxNotice = `cancellation unconfirmed. ${error.message || 'check its status or retry.'}`; }
  finally { if (_outboxOperation === operation) _outboxOperation = null; paintOutbox(); }
  if (!operation.retired && sameOutgoing(pending, _outboxPending)) await _renderScheduled();
}
async function forgetOutgoing(unreadable) {
  if (_outboxOperation) return;
  const pending = _outboxPending, scopes = [..._outboxScopes];
  if (!await dlgConfirm('clear this recovery record? this does not cancel delivery. check Sent and the outbox before sending the message again.')) return;
  if (_outboxOperation || scopes.join() !== _outboxScopes.join() || (!unreadable && !sameOutgoing(pending, _outboxPending))) return;
  try {
    if (unreadable) for (const scope of scopes) { sessionStorage.removeItem(outgoingKey(scope)); if (sessionStorage.getItem(outgoingKey(scope)) !== null) throw new Error('cleanup failed'); }
    else clearPendingOutgoing(pending);
    _outboxNotice = ''; _outboxConflict = false; readPendingOutgoing();
  } catch { _outboxStorageError = 'could not clear delivery recovery data; it was kept.'; }
  paintOutbox();
}
function _showUndoBar(row, scope) {
  let bar = $('mail-undo-bar');
  if (!bar) { bar = document.createElement('div'); bar.id = 'mail-undo-bar'; bar.className = 'mail-undo-bar'; $('mail-view')?.appendChild(bar); }
  bar.dataset.id = row.id; bar.dataset.scope = scope;
  bar.innerHTML = '<span>queued to send</span><button type="button" class="btn" id="mail-undo-btn">undo</button>';
  bar.style.display = 'flex';
  $('mail-undo-btn').addEventListener('click', () => { if (!_outboxScopes.includes(scope)) { bar.remove(); return; } if (!_outboxPending) cancelOutgoing(row, scope); else if (_outboxPending.request_id === row.id && _outboxPending.recovery_scope === scope) cancelOutgoing(); else $('mail-outbox-status')?.focus(); });
  const remaining = Math.max(0, outgoingInstant(row.send_at) - Date.now());
  setTimeout(() => { if (bar.dataset.id === row.id && bar.dataset.scope === scope) bar.remove(); }, Math.min(remaining, 2147483647));
}

let _ruleWrite = null;
const ruleFields = ['match_field', 'match_value', 'action', 'action_arg', 'enabled'];
const ruleMatches = (row, pending) => row?.id === pending.request_id && ruleFields.every(key => row[key] === pending[key]);
const validRule = row => row && typeof row.id === 'string' && ['from', 'subject'].includes(row.match_field) &&
  typeof row.match_value === 'string' && ['markread', 'mute', 'label', 'autoreply'].includes(row.action) &&
  typeof row.action_arg === 'string' && typeof row.enabled === 'boolean';
const ruleKey = scope => 'alles-mail-rule:' + scope;
const ruleRequest = (url, options = {}) => mailJson(url, { ...options, signal: AbortSignal.timeout(15000) });

function mountRuleEditor(root, generation, initialRows, scopes) {
  const current = () => root.isConnected && generation === _messageGeneration;
  const el = id => root.querySelector('#' + id);
  let rows = initialRows, pending = null, busy = false, confirmed = false, storageError = '', notice = '';
  const fields = () => ({ match_field: getDropdownValue(el('mr-field')), match_value: savedText(el('mr-value').value),
    action: getDropdownValue(el('mr-action')), action_arg: savedText(el('mr-arg').value), enabled: true });
  const sameFields = value => ruleFields.every(key => fields()[key] === value[key]);
  const initialFields = fields();
  function keep(value) {
    const raw = JSON.stringify(value), key = ruleKey(value.recovery_scope);
    sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(key) !== raw) throw new Error('could not retain the pending rule');
    pending = value; confirmed = false;
  }
  function clear() {
    const key = ruleKey(pending.recovery_scope), raw = sessionStorage.getItem(key);
    if (raw && JSON.parse(raw).request_id !== pending.request_id) throw new Error('recovery data changed');
    sessionStorage.removeItem(key);
    if (sessionStorage.getItem(key) !== null) throw new Error('could not clear recovery data');
    pending = null; confirmed = false;
  }
  function finish(deleted = false) {
    confirmed = true;
    notice = deleted ? 'rule removed' : 'rule saved';
    if (!deleted && current() && sameFields(pending)) { el('mr-value').value = ''; el('mr-arg').value = ''; }
    else if (!deleted && current()) notice += '; newer changes are unsaved';
    try { clear(); }
    catch { notice += '. recovery data could not be cleared; retry cleanup.'; }
  }
  function readPending() {
    storageError = '';
    try {
      pending = null; confirmed = false;
      for (const scope of scopes) {
        const raw = sessionStorage.getItem(ruleKey(scope));
        if (!raw) continue;
        const value = JSON.parse(raw);
        if (!['create', 'delete'].includes(value?.kind) || value.recovery_scope !== scope ||
            !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value.request_id || '') ||
            !validRule({ ...value, id: value.request_id })) throw new Error('invalid recovery data');
        if (pending) throw new Error('multiple pending rules');
        pending = value;
      }
    } catch { storageError = 'could not read rule recovery data. retry reading it before making changes.'; }
  }
  function paint() {
    if (!current()) return;
    const focus = root.contains(document.activeElement) ? document.activeElement.id : '';
    const blocked = busy || Boolean(pending || storageError);
    el('mail-rules-list').innerHTML = rows.map(row => `<div class="mail-rule-row" data-id="${esc(row.id)}">
      <span>if <b>${esc(row.match_field)}</b> contains “${esc(row.match_value)}” → <b>${esc(({ markread: 'mark read', autoreply: 'auto-reply' })[row.action] || row.action)}</b>${row.action_arg ? ` (${esc(row.action_arg)})` : ''}${row.enabled ? '' : ' · paused'}</span>
      <button type="button" class="btn danger mail-rule-del" id="mr-delete-${esc(row.id)}" data-id="${esc(row.id)}" aria-label="remove rule for ${esc(row.match_value)}" aria-disabled="${blocked}">remove</button>
    </div>`).join('') || '<div class="mail-empty-sm">no rules yet</div>';
    el('mr-add').setAttribute('aria-disabled', String(blocked));
    el('mr-run').setAttribute('aria-disabled', String(blocked || !_accounts.length));
    const message = busy ? 'saving rule changes…' : storageError || notice || (pending ? `saving the rule for “${pending.match_value}” is unconfirmed. retry uses the same rule.` : '');
    let actions = '';
    if (storageError) actions = '<button type="button" class="btn" id="mr-read-retry">retry reading recovery data</button><button type="button" class="btn" id="mr-clear">clear recovery data</button>';
    else if (pending) actions = confirmed ? '<button type="button" class="btn" id="mr-cleanup">retry cleanup</button>' :
      `<button type="button" class="btn" id="mr-retry">${pending.kind === 'delete' ? 'retry removing rule' : 'retry saving rule'}</button>${pending.kind === 'create' ? '<button type="button" class="btn" id="mr-cancel">cancel pending rule</button>' : ''}`;
    el('mr-status').textContent = message;
    el('mr-recovery-actions').innerHTML = actions;
    el('mr-recovery').querySelectorAll('button').forEach(button => button.setAttribute('aria-disabled', String(busy)));
    root.querySelectorAll('.mail-rule-del').forEach(button => button.onclick = () => {
      if (blocked) return;
      const row = rows.find(value => value.id === button.dataset.id);
      start({ ...row, kind: 'delete', request_id: row.id, recovery_scope: scopes[0] });
    });
    el('mr-retry')?.addEventListener('click', save);
    el('mr-cancel')?.addEventListener('click', () => {
      if (busy || !pending) return;
      start({ ...pending, kind: 'delete' });
    });
    el('mr-cleanup')?.addEventListener('click', () => {
      if (busy || !pending) return;
      try { clear(); notice = 'rule recovery data cleared'; } catch { notice = 'could not clear rule recovery data; retry cleanup.'; }
      paint();
    });
    el('mr-read-retry')?.addEventListener('click', () => { if (!busy) { readPending(); reconcilePending(); paint(); } });
    el('mr-clear')?.addEventListener('click', async () => {
      if (busy || !await dlgConfirm('clear unreadable rule recovery data? an earlier change may already be saved. check the rule list before adding it again.') || !current()) return;
      try {
        for (const scope of scopes) { sessionStorage.removeItem(ruleKey(scope)); if (sessionStorage.getItem(ruleKey(scope)) !== null) throw new Error('cleanup failed'); }
        pending = null; storageError = ''; notice = 'recovery data cleared. check saved rules before adding another.';
      } catch { storageError = 'could not clear rule recovery data. retry reading it.'; }
      paint();
    });
    if (focus && document.activeElement === document.body) {
      const target = el(focus) || el('mr-status');
      (target?.getClientRects().length ? target : el('mr-add')).focus();
    }
  }
  function start(value) {
    if (busy || storageError) return;
    notice = '';
    try { keep(value); save(); }
    catch { storageError = 'could not retain this change for recovery. no request was sent. retry reading recovery data.'; paint(); }
  }
  async function save() {
    if (busy || !pending || confirmed || storageError) return;
    const desired = pending;
    busy = true; notice = ''; paint();
    const writing = (async () => {
      try {
        if (desired.kind === 'delete') {
          const data = await ruleRequest(`/api/mail/rules/${encodeURIComponent(desired.request_id)}?recovery_scope=${encodeURIComponent(desired.recovery_scope)}`, { method: 'DELETE' });
          if (data?.ok !== true) throw new Error('could not confirm removal');
          rows = rows.filter(row => row.id !== desired.request_id); finish(true);
        } else {
          const row = await ruleRequest('/api/mail/rules', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(desired) });
          if (!validRule(row) || !ruleMatches(row, desired)) throw new Error('could not confirm the saved rule');
          rows = [...rows.filter(value => value.id !== row.id), row]; finish();
        }
      } catch (error) {
        if (error.status === 410 && desired.kind === 'create') { rows = rows.filter(row => row.id !== desired.request_id); finish(true); }
        else notice = `${desired.kind === 'delete' ? 'removal' : 'save'} unconfirmed. ${error.message || 'check your connection and retry.'} your rule is kept for retry.`;
      } finally { busy = false; paint(); }
    })();
    _ruleWrite = writing;
    try { await writing; } finally { if (_ruleWrite === writing) _ruleWrite = null; }
  }
  function reconcilePending() {
    if (!pending || storageError) return;
    if (pending.kind === 'create') {
      if (sameFields(initialFields)) {
        el('mr-field').value = pending.match_field; el('mr-value').value = pending.match_value;
        el('mr-action').value = pending.action; el('mr-arg').value = pending.action_arg;
      }
      if (rows.some(row => ruleMatches(row, pending))) finish();
    } else notice = `removal of the rule for “${pending.match_value}” is unconfirmed. retry removing it.`;
  }
  readPending(); reconcilePending();
  el('mr-add').addEventListener('click', () => {
    if (busy || pending || storageError) return;
    const value = fields();
    if (!value.match_value) { notice = 'enter text to match'; paint(); el('mr-value').focus(); return; }
    if (['label', 'autoreply'].includes(value.action) && !value.action_arg) { notice = value.action === 'label' ? 'enter a label' : 'enter a reply message'; paint(); el('mr-arg').focus(); return; }
    start({ ...value, kind: 'create', request_id: savedRequestId(), recovery_scope: scopes[0] });
  });
  el('mr-run').addEventListener('click', async () => {
    if (busy || pending || storageError || !_accounts.length) return;
    busy = true; paint(); el('mr-status').textContent = '';
    el('mr-run-status').textContent = 'running rules…';
    const accounts = [..._accounts];
    const running = (async () => {
      let total = 0, completed = 0; const failed = [];
      for (const account of accounts) {
        try {
          const result = await ruleRequest(`/api/mail/rules/run/${encodeURIComponent(account.id)}`, { method: 'POST' });
          if (!Number.isSafeInteger(result?.applied) || result.applied < 0) throw new Error('could not confirm result');
          total += result.applied; completed++;
        } catch { failed.push(account.name || account.email || 'account'); }
      }
      if (current()) {
        el('mr-run-status').textContent = `${total} rule action(s) confirmed across ${completed} account(s).${failed.length ? ` could not confirm: ${failed.join(', ')}. check inbox before running again.` : ''}`;
        loadInbox();
      }
    })();
    _ruleWrite = running;
    try { await running; } finally { if (_ruleWrite === running) _ruleWrite = null; busy = false; paint(); }
  });
  paint();
}

let _vacationWrite = null;
async function rulesPanel() {
  if (!await prepareMailNavigation()) return;
  const generation = _messageGeneration;
  const main = $('mail-main');
  main.innerHTML = '<div class="mail-empty" role="status">loading rules…</div>';
  // A reopened form must read after its earlier save, not race a newer save against it.
  if (_vacationWrite) await _vacationWrite.catch(() => {});
  if (_ruleWrite) await _ruleWrite.catch(() => {});
  if (generation !== _messageGeneration) return;
  let rules, vac, scopes;
  try {
    const [data, vacation] = await Promise.all([mailJson('/api/mail/rules'), mailJson('/api/mail/vacation')]);
    if (!Array.isArray(data?.rules) || !data.rules.every(validRule) ||
        !Array.isArray(data.recovery_scopes) || !data.recovery_scopes.length || !data.recovery_scopes.every(scope => /^[a-f0-9]{64}$/.test(scope)) ||
        typeof vacation?.enabled !== 'boolean' || typeof vacation.subject !== 'string' || typeof vacation.body !== 'string') {
      throw new Error('could not confirm rules and vacation settings');
    }
    rules = data.rules; vac = vacation; scopes = data.recovery_scopes;
  } catch (error) {
    if (generation !== _messageGeneration) return;
    main.innerHTML = `<div class="mail-empty" role="alert">${esc(error.message || 'could not load rules and vacation settings')} <button type="button" class="btn">retry</button></div>`;
    main.querySelector('button').addEventListener('click', () => rulesPanel());
    return;
  }
  if (generation !== _messageGeneration) return;
  main.innerHTML = `<div class="mail-rules-panel">
    <div class="mail-compose-head">rules</div>
    <div id="mail-rules-list"></div>
    <div class="mail-rule-form">
      <label><span>match field</span><div class="settings-input custom-select" id="mr-field" aria-label="match field"></div></label>
      <label><span>contains</span><input class="settings-input" id="mr-value"></label>
      <label><span>action</span><div class="settings-input custom-select" id="mr-action" aria-label="rule action"></div></label>
      <label><span>label or reply message</span><textarea class="settings-input" id="mr-arg" rows="2" placeholder="for label or auto-reply rules"></textarea></label>
    </div>
    <button type="button" class="btn primary" id="mr-add">add rule</button>
    <div class="mail-saved-status" id="mr-recovery"><p id="mr-status" role="status" aria-live="polite" tabindex="-1"></p><div class="mail-rule-actions" id="mr-recovery-actions"></div></div>
    <div class="mail-rule-actions"><button type="button" class="btn" id="mr-run">run rules now</button><span id="mr-run-status" class="mail-status" role="status" aria-live="polite"></span></div>
    <div class="mail-compose-head" style="margin-top:1rem">vacation responder</div>
    <button class="btn mail-vac-toggle${vac.enabled ? ' active' : ''}" id="mv-enabled" aria-pressed="${vac.enabled ? 'true' : 'false'}">${vac.enabled ? '✓ ' : ''}auto-reply when I'm away</button>
    <input class="settings-input" id="mv-subject" aria-label="vacation subject" placeholder="subject" value="${esc(vac.subject || '')}">
    <textarea class="settings-input mail-compose-body" id="mv-body" aria-label="vacation message" placeholder="out-of-office message…">${esc(vac.body || '')}</textarea>
    <button class="btn primary" id="mv-save">save vacation reply</button>
    <div id="mv-status" class="mail-status" role="status" aria-live="polite"></div>
  </div>`;
  populateDropdown($('mr-field'), [{ value: 'from', label: 'from' }, { value: 'subject', label: 'subject' }], 'from');
  populateDropdown($('mr-action'), [
    { value: 'markread', label: 'mark read' }, { value: 'mute', label: 'mute' },
    { value: 'label', label: 'label' }, { value: 'autoreply', label: 'auto-reply' },
  ], 'markread');
  $('mv-enabled').addEventListener('click', () => {
    const on = $('mv-enabled').getAttribute('aria-pressed') !== 'true';
    $('mv-enabled').setAttribute('aria-pressed', on ? 'true' : 'false');
    $('mv-enabled').classList.toggle('active', on);
    $('mv-enabled').textContent = (on ? '✓ ' : '') + "auto-reply when I'm away";
  });
  mountRuleEditor(main.querySelector('.mail-rules-panel'), generation, rules, scopes);
  const vacationRoot = main.querySelector('.mail-rules-panel');
  const vacationSave = vacationRoot.querySelector('#mv-save');
  const vacationStatus = vacationRoot.querySelector('#mv-status');
  const vacationValue = () => ({
    enabled: vacationRoot.querySelector('#mv-enabled').getAttribute('aria-pressed') === 'true',
    subject: vacationRoot.querySelector('#mv-subject').value,
    body: vacationRoot.querySelector('#mv-body').value,
  });
  const sameVacation = (a, b) => ['enabled', 'subject', 'body'].every(key => a?.[key] === b?.[key]);
  let vacationSaved = null;
  const updateVacationStatus = () => {
    if (!vacationSaved || vacationSave.disabled) return;
    vacationStatus.textContent = sameVacation(vacationValue(), vacationSaved)
      ? 'vacation reply saved' : 'vacation changes are unsaved';
  };
  for (const id of ['mv-subject', 'mv-body']) vacationRoot.querySelector(`#${id}`).addEventListener('input', updateVacationStatus);
  vacationRoot.querySelector('#mv-enabled').addEventListener('click', updateVacationStatus);
  vacationSave.addEventListener('click', async () => {
    if (vacationSave.disabled) return;
    const body = vacationValue();
    vacationSaved = null;
    vacationSave.disabled = true;
    vacationStatus.textContent = 'saving vacation reply…';
    const writing = mailPost('/api/mail/vacation', body);
    _vacationWrite = writing;
    try {
      const saved = await writing;
      if (!sameVacation(saved, body)) throw new Error('could not confirm the saved vacation reply');
      if (!vacationRoot.isConnected || generation !== _messageGeneration) return;
      vacationSaved = body;
      vacationStatus.textContent = sameVacation(vacationValue(), body)
        ? 'vacation reply saved' : 'earlier vacation reply saved; newer changes are unsaved';
    } catch (error) {
      if (vacationRoot.isConnected && generation === _messageGeneration) {
        vacationStatus.textContent = `save unconfirmed. ${error.message || 'check your connection and retry.'} your changes are still here.`;
      }
    } finally {
      if (_vacationWrite === writing) _vacationWrite = null;
      vacationSave.disabled = false;
    }
  });
}

const accountFields = ['email', 'name', 'imap_host', 'imap_port', 'smtp_host', 'smtp_port', 'username', 'use_ssl'];
const validAccount = row => row && typeof row.id === 'string' && row.id &&
  ['email', 'name', 'imap_host', 'smtp_host', 'username'].every(key => typeof row[key] === 'string') &&
  ['imap_port', 'smtp_port'].every(key => Number.isSafeInteger(row[key])) &&
  Number.isSafeInteger(row.revision) && row.revision > 0 && typeof row.use_ssl === 'boolean';
const accountMatches = (row, fields) => accountFields.every(key => row?.[key] === fields[key]);
const accountSnapshot = fields => JSON.stringify([...accountFields.map(key => fields[key]), fields.password]);
const accountKey = scope => 'alles-mail-account-pending:' + scope;
const accountRequest = (url, options = {}) => mailJson(url, { ...options, signal: AbortSignal.timeout(15000) });
const _accountRecovery = { scopes: [], pending: null, attempt: null, confirmed: false, error: '', notice: '', write: null };
let _accountEditor = null;

async function readAccountContext() {
  const data = await accountRequest('/api/mail/accounts?context=true');
  if (!Array.isArray(data?.accounts) || !data.accounts.every(validAccount) ||
      !Array.isArray(data.recovery_scopes) || !data.recovery_scopes.length || !data.recovery_scopes.every(scope => /^[a-f0-9]{64}$/.test(scope))) {
    throw new Error('could not confirm mail accounts');
  }
  return data;
}
function readAccountRecovery(scopes) {
  const state = _accountRecovery;
  state.scopes = scopes; state.error = '';
  try {
    let pending = null;
    for (const scope of scopes) {
      const raw = sessionStorage.getItem(accountKey(scope));
      if (!raw) continue;
      const value = JSON.parse(raw);
      if (!['create', 'edit', 'delete'].includes(value?.kind) || value.recovery_scope !== scope ||
          !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value.id || '') || typeof value.label !== 'string' ||
          (value.kind === 'edit' && (!Number.isSafeInteger(value.expected_revision) || value.expected_revision < 1)) ||
          (value.expected_revision !== undefined && (!Number.isSafeInteger(value.expected_revision) || value.expected_revision < 1)) || pending) {
        throw new Error('invalid account recovery data');
      }
      pending = value;
    }
    if (JSON.stringify(pending) !== JSON.stringify(state.pending)) {
      state.attempt = null; state.confirmed = false; state.notice = '';
    }
    state.pending = pending;
    if (!pending && _accountEditor) _accountEditor.pendingSnapshot = null;
  } catch { state.error = 'could not read account recovery data. retry reading it before making changes.'; }
}
function keepAccountAttempt(pending, body = null) {
  const state = _accountRecovery;
  state.notice = ''; state.confirmed = false;
  // Only identifiers and revision metadata survive reload. Credentials remain in memory.
  state.pending = pending; state.attempt = body;
  const raw = JSON.stringify(pending), key = accountKey(pending.recovery_scope);
  try {
    sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(key) !== raw) throw new Error('could not retain account recovery');
  } catch {
    if (_accountEditor) _accountEditor.pendingSnapshot = null;
    state.error = 'could not retain account recovery. no request was sent; retry reading recovery data.';
    return false;
  }
  return true;
}
function clearAccountAttempt() {
  const state = _accountRecovery, pending = state.pending;
  if (!pending) return;
  const key = accountKey(pending.recovery_scope), raw = sessionStorage.getItem(key);
  if (raw && JSON.stringify(JSON.parse(raw)) !== JSON.stringify(pending)) throw new Error('account recovery changed');
  sessionStorage.removeItem(key);
  if (sessionStorage.getItem(key) !== null) throw new Error('could not clear account recovery');
  state.pending = null; state.attempt = null; state.confirmed = false;
  if (_accountEditor) _accountEditor.pendingSnapshot = null;
}
function confirmAccountAttempt(result) {
  const state = _accountRecovery;
  state.confirmed = true; state.attempt = null;
  if (result.removed) {
    _accounts = _accounts.filter(row => row.id !== result.id);
    if (_active === result.id) _active = 'all';
    state.notice = 'account removed';
  } else {
    _accounts = [..._accounts.filter(row => row.id !== result.row.id), result.row];
    state.notice = 'account saved';
  }
  syncAccountSelect();
  try { clearAccountAttempt(); }
  catch { state.notice += '. recovery data could not be cleared; retry cleanup.'; }
}
async function writeAccountAttempt() {
  const state = _accountRecovery;
  if (state.write || state.error || !state.pending || state.confirmed) return null;
  const pending = state.pending, body = state.attempt;
  if (pending.kind !== 'delete' && !body) return null;
  if (body && _accountEditor?.root.isConnected) _accountEditor.pendingSnapshot = accountSnapshot(body);
  state.notice = pending.kind === 'delete' ? 'removing account…' : 'saving account…';
  const writing = (async () => {
    try {
      let result;
      if (pending.kind === 'delete') {
        const query = new URLSearchParams({ recovery_scope: pending.recovery_scope });
        if (pending.expected_revision !== undefined) query.set('expected_revision', pending.expected_revision);
        const value = await accountRequest(`/api/mail/accounts/${encodeURIComponent(pending.id)}?${query}`, { method: 'DELETE' });
        if (value?.ok !== true) throw new Error('could not confirm account removal');
        result = { removed: true, id: pending.id };
      } else {
        const creating = pending.kind === 'create';
        const row = await accountRequest(creating ? '/api/mail/accounts' : `/api/mail/accounts/${encodeURIComponent(pending.id)}`, {
          method: creating ? 'POST' : 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ ...body, recovery_scope: pending.recovery_scope,
            ...(creating ? { request_id: pending.id } : { expected_revision: pending.expected_revision }) }),
        });
        if (!validAccount(row) || row.id !== pending.id || !accountMatches(row, body)) throw new Error('could not confirm the saved account');
        result = { row, fields: body };
      }
      confirmAccountAttempt(result);
      return result;
    } catch (error) {
      state.notice = `${pending.kind === 'delete' ? 'removal' : 'save'} unconfirmed. ${error.message || 'check your connection and retry.'}`;
      return null;
    }
  })();
  state.write = writing;
  try { return await writing; } finally { if (state.write === writing) state.write = null; }
}
function mountAccountRecovery(root, current, changed) {
  const state = _accountRecovery;
  const status = root.querySelector('#ma-recovery-status'), actions = root.querySelector('#ma-recovery-actions');
  function paint() {
    if (!current()) return;
    const focus = actions.contains(document.activeElement);
    const pending = state.pending, row = pending && _accounts.find(value => value.id === pending.id);
    status.textContent = state.error || state.notice || (pending ? `the last ${pending.kind === 'delete' ? 'removal' : 'save'} for “${pending.label}” is unconfirmed.` : '');
    actions.replaceChildren();
    const button = (label, fn) => {
      const node = document.createElement('button'); node.type = 'button'; node.className = 'btn'; node.textContent = label;
      node.setAttribute('aria-disabled', String(Boolean(state.write)));
      node.addEventListener('click', async () => { if (!state.write) await fn(); }); actions.appendChild(node);
    };
    const update = result => { if (current()) { changed(result); paint(); } };
    if (state.error) button('retry reading account recovery', async () => { readAccountRecovery(state.scopes); update(); });
    else if (pending && state.confirmed) button('retry account recovery cleanup', () => {
      try { clearAccountAttempt(); state.notice = 'account recovery cleared'; } catch { state.notice = 'recovery data could not be cleared; retry cleanup.'; }
      update();
    });
    else if (pending) {
      if (state.attempt || pending.kind === 'delete') button(pending.kind === 'delete' ? 'retry removal' : 'retry saved changes', async () => {
        const writing = writeAccountAttempt(); paint(); update(await writing);
      });
      if (pending.kind === 'create' && row) button('review saved account', () => {
        try { clearAccountAttempt(); acctForm(row); } catch { state.notice = 'recovery data could not be cleared; retry.'; update(); }
      });
      if (pending.kind === 'create' || (pending.kind === 'edit' && !row)) button('remove pending account', async () => {
        if (!await dlgConfirm('remove this pending account? any delayed save will also be cancelled.')) return;
        if (!current() || state.write || state.pending !== pending) return;
        if (!keepAccountAttempt({ kind: 'delete', id: pending.id, label: pending.label, recovery_scope: pending.recovery_scope })) { update(); return; }
        const writing = writeAccountAttempt(); paint(); update(await writing);
      });
      if (pending.kind === 'edit' || (pending.kind === 'delete' && row && Number.isSafeInteger(pending.expected_revision))) button('review current settings', async () => {
        if (!await dlgConfirm('keep the currently saved settings? the unconfirmed account change will be cancelled.')) return;
        if (!current() || state.write || state.pending !== pending) return;
        const draftSnapshot = () => JSON.stringify([serializeForm(root), root.querySelector('#ma-tls')?.getAttribute('aria-pressed')]);
        const initialDraft = draftSnapshot();
        // Claim the current revision so an older in-flight edit/removal cannot replace it.
        const operation = (async () => {
          const data = await readAccountContext();
          if (!data.recovery_scopes.includes(pending.recovery_scope)) throw new Error('account storage has changed; reopen accounts');
          _accounts = data.accounts; syncAccountSelect();
          const saved = data.accounts.find(value => value.id === pending.id);
          if (!saved) throw new Error('this account was removed elsewhere. remove the pending account to finish recovery.');
          return { saved, data };
        })();
        state.write = operation; paint();
        let data;
        try { data = await operation; }
        catch (error) { state.notice = error.message || 'could not read current settings'; }
        finally { if (state.write === operation) state.write = null; }
        if (!data || !current()) { update(); return; }
        const body = Object.fromEntries(accountFields.map(key => [key, data.saved[key]])); body.password = '';
        if (!keepAccountAttempt({ kind: 'edit', id: pending.id, label: pending.label, recovery_scope: pending.recovery_scope, expected_revision: data.saved.revision }, body)) { update(); return; }
        const writing = writeAccountAttempt(); paint();
        const result = await writing;
        if (current() && result?.row && !state.pending && draftSnapshot() === initialDraft) acctForm(result.row);
        else update(result);
      });
      if (!state.attempt && pending.kind === 'create' && !row) status.textContent += ' the password was not stored in this browser. remove the pending account before starting again.';
    }
    if (focus && document.activeElement === document.body) {
      const target = actions.querySelector('button') || (status.textContent ? status : root.querySelector('#ma-save, #mail-add-acct'));
      target?.focus();
    }
  }
  return paint;
}
const accountRecoveryHtml = '<div class="mail-saved-status"><p id="ma-recovery-status" role="status" aria-live="polite" tabindex="-1"></p><div class="mail-rule-actions" id="ma-recovery-actions"></div></div>';

async function accountsPanel(firstRun = false) {
  if (!await prepareMailNavigation()) return;
  const main = $('mail-main'), generation = _messageGeneration;
  const current = () => main.isConnected && generation === _messageGeneration;
  main.innerHTML = '<div class="mail-empty" role="status">loading accounts…</div>';
  if (_accountRecovery.write) await _accountRecovery.write.catch(() => {});
  if (!current()) return;
  try {
    const data = await readAccountContext();
    if (!current()) return;
    _accounts = data.accounts; syncAccountSelect(); readAccountRecovery(data.recovery_scopes);
  } catch (error) {
    if (!current()) return;
    main.innerHTML = `<div class="mail-empty" role="alert">${esc(error.message || 'could not load accounts')} <button type="button" class="btn">retry</button></div>`;
    main.querySelector('button').addEventListener('click', () => accountsPanel(firstRun)); return;
  }
  main.innerHTML = `<div class="mail-accounts">
    <div class="mail-form-head"><div><div class="mail-compose-head">accounts</div><div class="mail-form-sub">${firstRun ? 'connect a mailbox to get started' : 'manage saved mailboxes'}</div></div>
      <div class="mail-form-actions"><button type="button" class="btn" id="mail-accounts-close">close</button><button type="button" class="btn primary" id="mail-add-acct">add</button></div></div>
    <div class="mail-service-links">${providerHelpHtml()}</div>${accountRecoveryHtml}<div id="mail-account-rows"></div></div>`;
  const root = main.querySelector('.mail-accounts');
  const live = () => current() && root.isConnected;
  const paintRecovery = mountAccountRecovery(root, live, paintRows);
  function paintRows() {
    if (!live()) return;
    const state = _accountRecovery, blocked = Boolean(state.write || state.pending || state.error);
    root.querySelector('#mail-add-acct').setAttribute('aria-disabled', String(blocked));
    const list = root.querySelector('#mail-account-rows'), focused = list.contains(document.activeElement);
    list.innerHTML = _accounts.map(a => `<div class="mail-acct-row"><span><b>${esc(a.name || a.email)}</b><em>${esc(a.email)}</em></span><span class="mail-acct-actions">
      <button type="button" class="btn mail-acct-edit" data-id="${esc(a.id)}" aria-disabled="${blocked}">edit</button><button type="button" class="btn mail-acct-del" data-id="${esc(a.id)}" aria-disabled="${blocked}">remove</button></span></div>`).join('') || '<div class="mail-empty">no saved accounts</div>';
    list.querySelectorAll('.mail-acct-edit').forEach(button => button.addEventListener('click', () => { if (!blocked) acctForm(_accounts.find(a => a.id === button.dataset.id)); }));
    list.querySelectorAll('.mail-acct-del').forEach(button => button.addEventListener('click', async () => {
      if (blocked) return;
      const row = _accounts.find(a => a.id === button.dataset.id);
      if (!row || !await dlgConfirm(`remove ${row.name || row.email}?`)) return;
      if (!live() || state.pending || state.write || state.error) return;
      if (!keepAccountAttempt({ kind: 'delete', id: row.id, label: row.name || row.email, recovery_scope: state.scopes[0], expected_revision: row.revision })) { paintRows(); paintRecovery(); return; }
      const writing = writeAccountAttempt(); paintRows(); paintRecovery(); await writing; paintRows(); paintRecovery();
    }));
    if (focused && document.activeElement === document.body) root.querySelector('#mail-add-acct').focus();
  }
  root.querySelector('#mail-add-acct').addEventListener('click', () => { if (!_accountRecovery.pending && !_accountRecovery.error && !_accountRecovery.write) acctForm(null); });
  root.querySelector('#mail-accounts-close').addEventListener('click', () => { if (live()) { ++_messageGeneration; root.remove(); _reloadCurrent(); } });
  paintRows(); paintRecovery();
}

function acctForm(acct) {
  const main = $('mail-main');
  const a = acct || {};
  ++_messageGeneration;
  let existing = acct, testing = false;
  const state = _accountRecovery;
  main.innerHTML = `<div class="mail-accounts">
    <div class="mail-form-head">
      <div>
        <div class="mail-compose-head">${acct ? 'edit account' : 'add account'}</div>
        <div class="mail-form-sub">IMAP receives, SMTP sends</div>
      </div>
      <div class="mail-form-actions">
        <button class="btn" id="ma-close">close</button>
        <button type="button" class="btn primary" id="ma-save">save</button>
      </div>
    </div>
    <div class="mail-oauth" id="ma-oauth"></div>
    <label class="mail-account-field"><span>email address</span><input class="settings-input" id="ma-email" placeholder="email address" value="${esc(a.email || '')}"></label>
    <label class="mail-account-field"><span>label (optional)</span><input class="settings-input" id="ma-name" placeholder="label (optional)" value="${esc(a.name || '')}"></label>
    <div class="mail-provider-row">
      ${PRESETS.map(p => `<button class="mail-provider-btn" type="button" data-provider="${esc(p.key)}">${esc(p.label)}</button>`).join('')}
    </div>
    <div class="mail-provider-note" id="ma-provider-note">pick a provider, or paste your own IMAP/SMTP hosts.</div>
    <div class="mail-guide" id="ma-guide"></div>
    <div class="mail-form-grid">
      <label class="mail-account-field"><span>IMAP host</span><input class="settings-input" id="ma-imaph" placeholder="imap host" value="${esc(a.imap_host || '')}"></label>
      <label class="mail-account-field"><span>IMAP port</span><input class="settings-input" id="ma-imapp" placeholder="imap port" value="${esc(a.imap_port || (a.use_ssl === false ? 143 : 993))}"></label>
      <label class="mail-account-field"><span>SMTP host</span><input class="settings-input" id="ma-smtph" placeholder="smtp host" value="${esc(a.smtp_host || '')}"></label>
      <label class="mail-account-field"><span>SMTP port</span><input class="settings-input" id="ma-smtpp" placeholder="smtp port" value="${esc(a.smtp_port || 587)}"></label>
    </div>
    <label class="mail-account-field"><span>username</span><input class="settings-input" id="ma-user" placeholder="username (usually your email)" value="${esc(a.username || a.email || '')}"></label>
    <label class="mail-account-field"><span>password</span><input class="settings-input" type="password" id="ma-pass" placeholder="${acct ? 'password (leave blank to keep)' : 'app-specific password'}"></label>
    <button type="button" class="btn" id="ma-tls" aria-pressed="${a.use_ssl !== false}">IMAP over TLS: ${a.use_ssl !== false ? 'on' : 'off'}</button>
    <div class="mail-form-sub">this switch and the connection test apply to incoming mail.</div>
    <button type="button" class="btn" id="ma-test">test saved IMAP connection</button>
    <div id="ma-status" class="mail-status" role="status" aria-live="polite" tabindex="-1"></div>
    ${accountRecoveryHtml}
  </div>`;

  const root = main.querySelector('.mail-accounts');
  const el = id => root.querySelector('#' + id);
  const current = () => root.isConnected;
  const applyProvider = (p) => {
    const em = el('ma-email').value.trim();
    if (!p) return;
    if (p.key === 'domain') {
      const domain = domainFromEmail(em);
      if (domain) {
        el('ma-imaph').value = `imap.${domain}`;
        el('ma-smtph').value = `smtp.${domain}`;
        if (!el('ma-name').value) el('ma-name').value = domain;
      }
      el('ma-provider-note').innerHTML = 'Own domain: point MX to your mail server/provider, then use its IMAP/SMTP host here. Add SPF, DKIM, and DMARC for deliverability.';
    } else {
      el('ma-imaph').value = p.imap;
      el('ma-smtph').value = p.smtp;
      el('ma-provider-note').innerHTML = `${esc(p.note)} ${p.help ? `<a href="${esc(p.help)}" target="_blank" rel="noreferrer">setup help</a>` : ''}`;
    }
    el('ma-tls').setAttribute('aria-pressed', 'true');
    el('ma-tls').textContent = 'IMAP over TLS: on';
    el('ma-imapp').value = 993;
    el('ma-smtpp').value = 587;
    if (!el('ma-user').value) el('ma-user').value = em;
    // the quick-login guide: one tap to the exact app-password page + steps
    const guide = el('ma-guide');
    if (guide) {
      if (p && p.apppw) {
        guide.innerHTML = `
          <a class="btn primary mail-getpw" href="${esc(p.apppw)}" target="_blank" rel="noreferrer">get app password →</a>
          <ol class="mail-steps">
            <li>opens ${esc(p.label)}'s app-password page - sign in if it asks</li>
            <li>create one (name it "alles") and copy the code</li>
            <li>paste it in the password box below, then hit save</li>
          </ol>`;
      } else {
        guide.innerHTML = '';
      }
    }
    noteAccountChanges();
  };
  root.querySelectorAll('.mail-provider-btn').forEach(btn => {
    btn.addEventListener('click', () => applyProvider(PRESETS.find(p => p.key === btn.dataset.provider)));
  });
  el('ma-email').addEventListener('blur', () => {
    const p = providerForEmail(el('ma-email').value.trim());
    if (p && !el('ma-imaph').value && !el('ma-smtph').value) applyProvider(p);
  });

  const collect = () => ({
    email: el('ma-email').value.trim(),
    name: el('ma-name').value.trim(),
    imap_host: el('ma-imaph').value.trim(),
    imap_port: Number(el('ma-imapp').value),
    smtp_host: el('ma-smtph').value.trim(),
    smtp_port: Number(el('ma-smtpp').value),
    username: el('ma-user').value.trim() || el('ma-email').value.trim(),
    password: el('ma-pass').value,
    use_ssl: el('ma-tls').getAttribute('aria-pressed') === 'true',
  });
  const extraSnapshot = () => JSON.stringify(['ma-cid', 'ma-csec', 'ma-rbase'].map(id => el(id)?.value || ''));
  const editor = { root, snapshot: () => accountSnapshot(collect()), initial: accountSnapshot(collect()), pendingSnapshot: null, extraSnapshot, extraInitial: extraSnapshot() };
  _accountEditor = editor;
  const dirty = () => editor.snapshot() !== editor.initial;
  function paintForm() {
    if (!current()) return;
    const blocked = Boolean(state.write || state.pending || state.error || testing);
    el('ma-save').setAttribute('aria-disabled', String(blocked));
    el('ma-test').setAttribute('aria-disabled', String(blocked || !existing));
  }
  function acceptResult(result) {
    if (result?.row) {
      const saved = result.row;
      existing = saved;
      // Clear only the acknowledged password, keeping input typed during the save.
      const captured = result.fields;
      if (captured) {
        if (el('ma-pass').value === captured.password) el('ma-pass').value = '';
        editor.initial = accountSnapshot({ ...captured, password: '' });
      }
      editor.pendingSnapshot = null;
      if (!state.pending) state.notice = '';
      el('ma-status').textContent = dirty() ? 'earlier account settings saved; newer changes are unsaved' : 'account saved';
    } else if (result?.removed && existing?.id === result.id) {
      existing = null; editor.pendingSnapshot = null;
      el('ma-status').textContent = 'account removed; entered settings are unsaved';
    }
    paintForm();
  }
  const paintRecovery = mountAccountRecovery(root, current, acceptResult);
  async function testConnection() {
    if (!current() || testing || state.pending || state.error || state.write || !existing) return;
    const savedId = existing.id;
    testing = true; paintForm(); el('ma-status').textContent = 'account saved; testing the saved connection…';
    try {
      const result = await accountRequest(`/api/mail/test/${encodeURIComponent(savedId)}`);
      if (typeof result?.ok !== 'boolean') throw new Error('could not confirm the connection test');
      if (!result.ok) throw new Error(friendlyMailError(result.error));
      if (current()) el('ma-status').textContent = 'account saved; incoming mail connected' + (dirty() ? '; newer changes are unsaved' : '');
    } catch (error) {
      if (current()) el('ma-status').textContent = `account saved, but connection unconfirmed: ${error.message || 'check your connection and retry.'}` + (dirty() ? ' newer changes are unsaved.' : '');
    } finally { testing = false; paintForm(); }
  }
  function noteAccountChanges() {
    if (!state.pending) { state.notice = ''; paintRecovery(); }
    if (!testing) el('ma-status').textContent = dirty() ? 'account changes are unsaved' : '';
  }
  el('ma-close').addEventListener('click', () => accountsPanel());
  el('ma-test').addEventListener('click', testConnection);
  el('ma-tls').addEventListener('click', () => {
    const on = el('ma-tls').getAttribute('aria-pressed') !== 'true';
    el('ma-tls').setAttribute('aria-pressed', String(on)); el('ma-tls').textContent = `IMAP over TLS: ${on ? 'on' : 'off'}`;
    noteAccountChanges();
  });
  root.querySelectorAll('input').forEach(input => input.addEventListener('input', noteAccountChanges));
  el('ma-save').addEventListener('click', async () => {
    if (state.write || state.pending || state.error || testing || !current()) return;
    const body = collect();
    let issue;
    if (!body.email) issue = ['ma-email', 'enter an email address'];
    else if (!body.imap_host) issue = ['ma-imaph', 'enter the IMAP host'];
    else if (!Number.isInteger(body.imap_port) || body.imap_port < 1 || body.imap_port > 65535) issue = ['ma-imapp', 'enter an IMAP port from 1 to 65535'];
    else if (!body.smtp_host) issue = ['ma-smtph', 'enter the SMTP host'];
    else if (!Number.isInteger(body.smtp_port) || body.smtp_port < 1 || body.smtp_port > 65535) issue = ['ma-smtpp', 'enter an SMTP port from 1 to 65535'];
    else if (!existing && !body.password) issue = ['ma-pass', 'paste your app password'];
    if (issue) { el('ma-status').textContent = issue[1]; el(issue[0]).focus(); return; }
    const pending = { kind: existing ? 'edit' : 'create', id: existing?.id || savedRequestId(), label: body.name || body.email, recovery_scope: state.scopes[0], ...(existing ? { expected_revision: existing.revision } : {}) };
    if (!keepAccountAttempt(pending, body)) { paintForm(); paintRecovery(); return; }
    el('ma-status').textContent = '';
    const writing = writeAccountAttempt(); paintForm(); paintRecovery();
    const result = await writing;
    if (!current()) return;
    acceptResult(result); paintRecovery();
    if (result?.row && !dirty()) await testConnection();
  });
  paintForm(); paintRecovery();

  renderOauthBox(acct, editor);
}

const oauthKey = scope => 'alles-mail-oauth-pending:' + scope;
const _oauthRecovery = { scopes: [], pending: null, attempt: null, confirmed: false, error: '', notice: '', write: null };
function validOauthStatus(value) {
  return value && typeof value.configured === 'boolean' && typeof value.client_secret_configured === 'boolean' &&
    ['client_id', 'redirect_base', 'redirect_uri'].every(key => typeof value[key] === 'string') &&
    Number.isSafeInteger(value.revision) && value.revision >= 0 &&
    value.configured === Boolean(value.client_id && value.client_secret_configured) &&
    Array.isArray(value.recovery_scopes) && value.recovery_scopes.length > 0 &&
    value.recovery_scopes.every(scope => /^[a-f0-9]{64}$/.test(scope));
}
async function readOauthStatus() {
  const value = await accountRequest('/api/mail/oauth/status');
  if (!validOauthStatus(value)) throw new Error('could not confirm Google setup');
  return value;
}
function readOauthRecovery(scopes) {
  const state = _oauthRecovery;
  state.scopes = scopes; state.error = '';
  try {
    let pending = null;
    for (const scope of scopes) {
      const raw = sessionStorage.getItem(oauthKey(scope));
      if (!raw) continue;
      const value = JSON.parse(raw);
      if (value?.recovery_scope !== scope || !Number.isSafeInteger(value.expected_revision) || value.expected_revision < 0 || pending) throw new Error('invalid Google setup recovery');
      pending = value;
    }
    if (JSON.stringify(pending) !== JSON.stringify(state.pending)) {
      state.attempt = null; state.confirmed = false; state.notice = '';
    }
    state.pending = pending;
  } catch { state.error = 'could not read Google setup recovery. retry reading it before saving.'; }
}
function keepOauthAttempt(pending, body, inputs = null) {
  const state = _oauthRecovery;
  state.pending = pending; state.attempt = { body, inputs, editor: _accountEditor }; state.confirmed = false; state.error = ''; state.notice = '';
  const raw = JSON.stringify(pending), key = oauthKey(pending.recovery_scope);
  try {
    sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(key) !== raw) throw new Error('could not retain Google setup recovery');
    return true;
  } catch { state.error = 'could not retain Google setup recovery. no request was sent; retry reading recovery data.'; return false; }
}
function clearOauthAttempt() {
  const state = _oauthRecovery, pending = state.pending;
  if (!pending) return;
  const key = oauthKey(pending.recovery_scope), raw = sessionStorage.getItem(key);
  if (raw && JSON.stringify(JSON.parse(raw)) !== JSON.stringify(pending)) throw new Error('Google setup recovery changed');
  sessionStorage.removeItem(key);
  if (sessionStorage.getItem(key) !== null) throw new Error('could not clear Google setup recovery');
  state.pending = null; state.attempt = null; state.confirmed = false;
}
async function writeOauthAttempt() {
  const state = _oauthRecovery;
  if (state.write || state.error || !state.pending || !state.attempt || state.confirmed) return null;
  const pending = state.pending, { body, inputs } = state.attempt;
  state.notice = 'saving Google setup…';
  const writing = (async () => {
    try {
      const saved = await accountRequest('/api/mail/oauth/config', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...body, ...pending }),
      });
      if (!validOauthStatus(saved) || !saved.recovery_scopes.includes(pending.recovery_scope) ||
          saved.revision <= pending.expected_revision || saved.client_id !== body.client_id ||
          (saved.redirect_base !== body.redirect_base && saved.redirect_base !== body.redirect_base.replace(/\/+$/, ''))) throw new Error('could not confirm the saved Google setup');
      state.confirmed = true; state.attempt = null; state.notice = 'Google setup saved';
      try { clearOauthAttempt(); } catch { state.notice += '. recovery data could not be cleared; retry cleanup.'; }
      return { saved, fields: body, inputs };
    } catch (error) { state.notice = `Google save unconfirmed. ${error.message || 'check your connection and retry.'}`; return null; }
  })();
  state.write = writing;
  try { return await writing; } finally { if (state.write === writing) state.write = null; }
}

// Saving client keys and authorizing a mailbox are separate actions.
async function renderOauthBox(acct, editor) {
  const box = editor.root.querySelector('#ma-oauth'), state = _oauthRecovery;
  const current = () => box.isConnected && _accountEditor === editor;
  const el = id => box.querySelector('#' + id);
  box.innerHTML = '<p role="status">loading Google setup…</p>';
  if (state.write) await state.write.catch(() => {});
  if (!current()) return;
  let saved;
  try {
    saved = await readOauthStatus();
    if (!current()) return;
    readOauthRecovery(saved.recovery_scopes);
  } catch (error) {
    if (!current()) return;
    box.innerHTML = `<p role="alert">could not load Google setup. ${esc(error.message || 'check your connection.')}</p><button type="button" class="btn">retry Google setup</button>`;
    box.querySelector('button').addEventListener('click', () => renderOauthBox(acct, editor));
    return;
  }
  box.innerHTML = `
    <p id="ma-oauth-saved"></p>
    <a class="btn primary mail-google-btn" id="ma-google-start" href="/api/mail/oauth/google/start">${acct?.auth_type === 'oauth' ? 'reconnect with google' : 'sign in with google'}</a>
    <details class="mail-oauth-setup"${saved.configured ? '' : ' open'}>
      <summary>${saved.configured ? 'edit Google setup' : 'set up sign in with Google'}</summary>
      <div class="mail-oauth-steps">
        <p>create an OAuth client in <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">google cloud console</a> (type: web application), then paste the keys here.</p>
        <p>register this exact redirect url on that client:</p>
        <code class="mail-redirect" id="ma-oauth-redirect">${esc(saved.redirect_uri)}</code>
        <label class="mail-account-field"><span>Google client id</span><input class="settings-input" id="ma-cid" value="${esc(saved.client_id)}" autocomplete="off"></label>
        <label class="mail-account-field"><span>Google client secret</span><input class="settings-input" type="password" id="ma-csec" autocomplete="new-password" placeholder="${saved.client_secret_configured ? 'leave blank to keep the saved secret' : 'paste the client secret'}"></label>
        <label class="mail-account-field"><span>redirect base (optional)</span><input class="settings-input" id="ma-rbase" value="${esc(saved.redirect_base)}" placeholder="blank uses this server’s localhost address"></label>
        <button type="button" class="btn primary" id="ma-oauth-save">save google keys</button>
      </div>
    </details>
    <div class="mail-saved-status"><p id="ma-oauth-status" role="status" aria-live="polite" tabindex="-1"></p><div class="mail-rule-actions" id="ma-oauth-actions"></div></div>
    <div class="mail-or">or set it up by hand</div>`;
  const collect = () => ({ client_id: el('ma-cid').value, client_secret: el('ma-csec').value, redirect_base: el('ma-rbase').value });
  editor.extraInitial = editor.extraSnapshot();
  if (state.attempt && state.attempt.editor !== editor) {
    state.attempt.inputs = collect(); state.attempt.editor = editor;
  }
  const dirty = () => editor.extraSnapshot() !== editor.extraInitial;
  function accept(result) {
    if (!current() || !result) return;
    saved = result.saved;
    if (result.inputs) {
      for (const [key, id] of [['client_id', 'ma-cid'], ['client_secret', 'ma-csec'], ['redirect_base', 'ma-rbase']]) {
        if (el(id).value === result.inputs[key]) el(id).value = key === 'client_secret' ? '' : saved[key];
      }
    }
    editor.extraInitial = JSON.stringify([saved.client_id, '', saved.redirect_base]);
    el('ma-csec').placeholder = saved.client_secret_configured ? 'leave blank to keep the saved secret' : 'paste the client secret';
    el('ma-oauth-redirect').textContent = saved.redirect_uri;
  }
  function paint() {
    if (!current()) return;
    const blocked = Boolean(state.write || state.pending || state.error);
    el('ma-oauth-save').setAttribute('aria-disabled', String(blocked));
    el('ma-google-start').hidden = !saved.configured;
    el('ma-google-start').setAttribute('aria-disabled', String(blocked));
    el('ma-oauth-saved').textContent = saved.configured ? 'Google client keys are saved. sign in to authorize a mailbox.' : 'Google sign-in is not configured.';
    const status = el('ma-oauth-status'), actions = el('ma-oauth-actions'), focused = actions.contains(document.activeElement);
    status.textContent = state.error || state.notice || (state.pending ? 'the last Google save is unconfirmed. review the currently saved setup before continuing.' : dirty() ? 'Google setup changes are unsaved' : '');
    if (dirty() && state.notice) status.textContent += ' newer changes are unsaved.';
    actions.replaceChildren();
    const button = (label, fn) => {
      const node = document.createElement('button'); node.type = 'button'; node.className = 'btn'; node.textContent = label;
      node.setAttribute('aria-disabled', String(Boolean(state.write)));
      node.addEventListener('click', async () => { if (!state.write && current()) await fn(); }); actions.appendChild(node);
    };
    if (state.error) button('retry reading Google recovery', () => { readOauthRecovery(state.scopes); paint(); });
    else if (state.pending && state.confirmed) button('retry Google recovery cleanup', () => {
      try { clearOauthAttempt(); state.notice = 'Google setup recovery cleared'; } catch { state.notice = 'recovery data could not be cleared; retry cleanup.'; }
      paint();
    });
    else if (state.pending) {
      if (state.attempt) button('retry Google save', async () => { const writing = writeOauthAttempt(); paint(); accept(await writing); paint(); });
      button('review saved Google setup', async () => {
        const pending = state.pending, inputs = collect();
        const reading = readOauthStatus(); state.write = reading; state.notice = 'loading saved Google setup…'; paint();
        let value;
        try {
          value = await reading;
          if (!value.recovery_scopes.includes(pending.recovery_scope)) throw new Error('mail storage changed; reopen accounts');
        } catch (error) { value = null; state.notice = error.message || 'could not load saved Google setup'; }
        finally { if (state.write === reading) state.write = null; }
        if (!value || !current()) { paint(); return; }
        paint();
        const description = value.client_id || value.client_secret_configured
          ? `keep the saved Google setup: client id “${value.client_id || 'not set'}”, secret ${value.client_secret_configured ? 'saved' : 'not set'}, redirect “${value.redirect_uri}”?`
          : 'keep Google sign-in unconfigured?';
        if (!await dlgConfirm(description + ' this cancels the unconfirmed change.')) return;
        if (!current() || state.write || state.pending !== pending) return;
        const body = { client_id: value.client_id, client_secret: null, redirect_base: value.redirect_base };
        if (!keepOauthAttempt({ expected_revision: value.revision, recovery_scope: pending.recovery_scope }, body, inputs)) { paint(); return; }
        const writing = writeOauthAttempt(); paint();
        accept(await writing); paint();
      });
    }
    if (focused && document.activeElement === document.body) (actions.querySelector('button') || status).focus();
  }
  el('ma-google-start').addEventListener('click', async event => {
    event.preventDefault();
    if (state.write || state.pending || state.error || !saved.configured) return;
    if (await prepareMailNavigation()) window.location.assign('/api/mail/oauth/google/start');
  });
  for (const id of ['ma-cid', 'ma-csec', 'ma-rbase']) el(id).addEventListener('input', () => { if (!state.pending) state.notice = ''; paint(); });
  el('ma-oauth-save').addEventListener('click', async () => {
    if (state.write || state.pending || state.error || !current()) return;
    const inputs = collect(), fields = { ...inputs, client_id: inputs.client_id.trim(), redirect_base: inputs.redirect_base.trim() };
    if (!fields.client_id || (!fields.client_secret && !saved.client_secret_configured)) {
      state.notice = !fields.client_id ? 'enter a Google client id' : 'enter a Google client secret'; paint();
      el(!fields.client_id ? 'ma-cid' : 'ma-csec').focus(); return;
    }
    const body = { ...fields, client_secret: fields.client_secret || null };
    if (!keepOauthAttempt({ expected_revision: saved.revision, recovery_scope: saved.recovery_scopes[0] }, body, inputs)) { paint(); return; }
    const writing = writeOauthAttempt(); paint(); accept(await writing); paint();
  });
  paint();
}

// turn a raw IMAP/SMTP error into something a human can act on
function friendlyMailError(err) {
  const e = (err || '').toLowerCase();
  if (e.includes('application-specific password') || e.includes('badcredentials') || e.includes('support.google'))
    return 'this provider wants an app password, not your normal password - tap "get app password" above.';
  if (e.includes('authenticationfailed') || e.includes('invalid credentials') || e.includes('authentication failed') || e.includes('not accepted') || e.includes('login failed'))
    return 'login rejected - paste the app password with no spaces, and make sure 2-step verification is on.';
  if (e.includes('getaddrinfo') || e.includes('name or service') || e.includes('nodename') || e.includes('temporary failure in name'))
    return "couldn't reach the server - double-check the imap host.";
  if (e.includes('timed out') || e.includes('timeout'))
    return 'connection timed out - check the host/port or your network.';
  if (e.includes('certificate') || e.includes(' ssl') || e.includes('tls'))
    return 'tls problem - check the ports (993 imap, 587 smtp).';
  return err || 'unknown error';
}

function serializeForm(root) {
  return [...root.querySelectorAll('input,textarea,select,[contenteditable="true"]')]
    .map(el => `${el.id || el.name || el.placeholder}:${el.isContentEditable ? draftHtml(el) : el.value}`)
    .join('\n');
}
