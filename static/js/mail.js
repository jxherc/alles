import { toast } from './util.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { populateDropdown, getDropdownValue } from './dropdown.js';
import { initDatePicker as _dpInit } from './datepick.js';

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
  } catch {}
  try {
    const rs = (await fetch('/api/mail/recipients?limit=300').then(r => r.json())).recipients || [];
    rs.forEach(r => book.push({ email: r.email, name: r.name || '' }));
  } catch {}
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
let _lastMsgs = [];           // last rendered message set (for re-render on toggle)
let _lastSearch = '';         // last advanced-search query (5a, for the save-search button)

// mirror services.mail.normalize_subject — strip re:/fwd:/aw:… so a conversation collapses
const _subjPrefix = /^(?:\s*(?:re|fwd|fw|aw|wg)\s*:\s*)+/i;
const threadKey = s => (String(s ?? '').replace(_subjPrefix, '').trim() || '(no subject)').toLowerCase();

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const fromName = f => {
  const m = /^(.*?)\s*<([^>]+)>/.exec(f || '');
  return (m ? (m[1].replace(/"/g, '').trim() || m[2]) : f) || '(unknown)';
};
const shortDate = d => { try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); } catch { return ''; } };
const acctName = id => {
  const a = _accounts.find(x => x.id === id);
  return a ? (a.name || a.email || 'mail') : 'mail';
};

// stale-while-revalidate: IMAP is a network round-trip to your provider, so the
// first hit is never instant. cache the last list per account+folder and show it
// immediately while the fresh fetch runs in the background.
const cacheKey = () => `mail-cache-${_active}-${_filter === 'sent' ? 'sent' : 'inbox'}`;
const readCache = () => { try { return JSON.parse(localStorage.getItem(cacheKey()) || 'null'); } catch { return null; } };
const writeCache = msgs => { try { localStorage.setItem(cacheKey(), JSON.stringify(msgs.slice(0, 40))); } catch {} };

const PRESETS = [
  { key: 'gmail', label: 'Gmail', re: /@gmail\.com$/i, imap: 'imap.gmail.com', smtp: 'smtp.gmail.com', help: 'https://support.google.com/mail/answer/7126229', note: 'Use an app password if 2FA is on.' },
  { key: 'outlook', label: 'Outlook', re: /@(outlook|hotmail|live)\.com$/i, imap: 'outlook.office365.com', smtp: 'smtp.office365.com', help: 'https://support.microsoft.com/office/pop-imap-and-smtp-settings', note: 'Works for Outlook, Hotmail, and Live accounts.' },
  { key: 'icloud', label: 'iCloud', re: /@(icloud|me|mac)\.com$/i, imap: 'imap.mail.me.com', smtp: 'smtp.mail.me.com', help: 'https://support.apple.com/102525', note: 'Use an app-specific password from Apple ID settings.' },
  { key: 'yahoo', label: 'Yahoo', re: /@yahoo\.com$/i, imap: 'imap.mail.yahoo.com', smtp: 'smtp.mail.yahoo.com', help: 'https://help.yahoo.com/kb/SLN4075.html', note: 'Use an app password when account security requires it.' },
  { key: 'fastmail', label: 'Fastmail', re: /@fastmail\.com$/i, imap: 'imap.fastmail.com', smtp: 'smtp.fastmail.com', help: 'https://www.fastmail.help/hc/en-us/articles/1500000278342', note: 'Fastmail supports custom domains too.' },
  { key: 'domain', label: 'Own domain', re: /@[^@\s]+\.[^@\s]+$/i, imap: '', smtp: '', help: '', note: 'Use your domain mailbox or self-hosted IMAP/SMTP server.' },
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

let _inited = false;
export function initMail() {
  if (_inited) return;
  _inited = true;
  $('mail-account')?.addEventListener('change', e => {
    _active = e.target.value;
    localStorage.setItem('alles-mail-account-mode', _active);
    loadInbox();
  });
  $('mail-refresh-btn')?.addEventListener('click', () => loadInbox(true));
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
  try { _threads = (await fetch('/api/settings').then(r => r.json())).mail_threads === 'group'; } catch {}
}

async function searchMail(q) {
  const list = $('mail-list');
  list.innerHTML = '<div class="mail-empty">searching…</div>';
  _lastSearch = q;
  _renderSavedBar();
  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const all = [];
  // adv-search runs over the local cache, so it's instant, offline-friendly, and
  // understands from:/subject:/before:/after: operators (5a)
  await Promise.all(accts.map(async a => {
    try {
      const d = await fetch(`/api/mail/adv-search/${a.id}?q=${encodeURIComponent(q)}&limit=40`).then(r => r.json());
      (d.messages || []).forEach(msg => { msg.account_id = a.id; msg.account_name = a.name || a.email; all.push(msg); });
    } catch {}
  }));
  if (!all.length) { list.innerHTML = `<div class="mail-empty">no mail matches “${esc(q)}”</div>`; return; }
  renderInbox(all);
}

function _reloadCurrent() {
  if (_filter === 'flagged') loadSmart('flagged');
  else if (_filter === 'vip') loadSmart('vip');
  else if (_filter === 'drafts') loadDrafts();
  else loadInbox();
}

// saved searches (5a): a chip bar above the list — save the current query, click to run, × to drop
async function _renderSavedBar() {
  const bar = $('mail-saved'); if (!bar) return;
  let saved = [];
  try { saved = (await fetch('/api/mail/saved-searches').then(r => r.json())).searches || []; } catch {}
  const chips = saved.map(s => `<span class="mail-saved-chip" data-q="${esc(s.query)}">${esc(s.name)}<button class="mail-saved-del" data-del="${esc(s.id)}" title="remove">×</button></span>`).join('');
  const saveBtn = _lastSearch ? `<button class="btn mail-saved-save" id="mail-saved-save" title="save this search">★ save “${esc(_lastSearch.slice(0, 20))}”</button>` : '';
  bar.innerHTML = chips + saveBtn;
  bar.querySelectorAll('.mail-saved-chip').forEach(c => c.addEventListener('click', e => {
    if (e.target.closest('.mail-saved-del')) return;
    const inp = $('mail-search'); if (inp) inp.value = c.dataset.q;
    searchMail(c.dataset.q);
  }));
  bar.querySelectorAll('.mail-saved-del').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    await fetch(`/api/mail/saved-searches/${b.dataset.del}`, { method: 'DELETE' }).catch(() => {});
    _renderSavedBar();
  }));
  $('mail-saved-save')?.addEventListener('click', async () => {
    const name = _lastSearch.slice(0, 40);
    await fetch('/api/mail/saved-searches', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, query: _lastSearch }),
    }).catch(() => {});
    toast('search saved', '');
    _renderSavedBar();
  });
}

export async function loadMail() {
  initMail();
  startMailPoll();
  _accounts = await fetch('/api/mail/accounts').then(r => r.json()).catch(() => []);
  if (_accounts.length > 1 && !localStorage.getItem('alles-mail-account-mode')) _active = 'all';
  syncAccountSelect();
  if (!_accounts.length) {
    $('mail-list').innerHTML = '';
    accountsPanel(true);
    return;
  }
  _renderSavedBar();
  _renderScheduled();
  loadInbox();
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

async function fetchInboxFor(account, limit = 35, folder = 'INBOX', quick = false) {
  // quick=1 lets the server skip the full header re-fetch when the mailbox tip
  // hasn't moved — keeps the 30s background poll cheap on slow connections
  const url = `/api/mail/inbox/${account.id}?folder=${encodeURIComponent(folder)}&limit=${limit}${quick ? '&quick=1' : ''}`;
  const d = await fetch(url).then(r => r.json());
  const map = ms => ms.map(m => ({ ...m, account_id: account.id, account_name: account.name || account.email, folder }));
  // IMAP failed but the server handed back the cached copy → show it (offline-friendly) instead of erroring
  if (d.error) { if ((d.messages || []).length) return map(d.messages); throw new Error(d.error); }
  return map(d.messages || []);
}

// providers don't agree on a sent-folder name; sniff it once per account
async function sentFolderFor(account) {
  if (_sentFolders[account.id]) return _sentFolders[account.id];
  const d = await fetch(`/api/mail/folders/${account.id}`).then(r => r.json()).catch(() => ({ folders: [] }));
  const f = (d.folders || []).find(x => /sent/i.test(x)) || 'Sent';
  _sentFolders[account.id] = f;
  return f;
}

const applyFilter = msgs => _filter === 'unread' ? msgs.filter(m => !m.seen) : msgs;

// remember the read state locally so a refresh (from cache) doesn't re-bold it
function markSeenLocal(aid, uid) {
  const c = readCache();
  if (!c) return;
  const m = c.find(x => String(x.uid) === String(uid) && x.account_id === aid);
  if (m && !m.seen) { m.seen = true; writeCache(c); }
}

// Gmail-style left sidebar (4b): folders/categories as icon+label rows
const _MAIL_NAV = [
  { f: 'inbox', label: 'inbox', icon: 'mail' },
  { f: 'cat:primary', label: 'primary', icon: 'user' },
  { f: 'cat:social', label: 'social', icon: 'comment' },
  { f: 'cat:promotions', label: 'promotions', icon: 'tag' },
  { f: 'unread', label: 'unread', icon: 'bell' },
  { f: 'flagged', label: 'flagged', icon: 'bookmark' },
  { f: 'vip', label: 'vip', icon: 'star' },
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
  if (_filter === f) return;
  _filter = f;
  document.querySelectorAll('.mail-nav-item').forEach(t => t.classList.toggle('active', t.dataset.filter === f));
  if (f === 'drafts') loadDrafts();
  else if (f === 'flagged') loadSmart('flagged');
  else if (f === 'vip') loadSmart('vip');
  else if (f.startsWith('cat:')) loadCategory(f.slice(4));
  else loadInbox();
}

async function loadCategory(cat) {
  const list = $('mail-list'); const main = $('mail-main'); main.innerHTML = '';
  list.innerHTML = `<div class="mail-empty">loading ${esc(cat)}…</div>`;
  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const results = await Promise.allSettled(accts.map(a =>
    fetch(`/api/mail/category/${a.id}?cat=${encodeURIComponent(cat)}`).then(r => r.json())));
  let msgs = [];
  for (const r of results) if (r.status === 'fulfilled') msgs = msgs.concat(r.value.messages || []);
  renderInbox(msgs);
}

async function loadByLabel(label) {
  const list = $('mail-list'); const main = $('mail-main'); main.innerHTML = '';
  list.innerHTML = `<div class="mail-empty">label “${esc(label)}”…</div>`;
  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const results = await Promise.allSettled(accts.map(a =>
    fetch(`/api/mail/by-label/${a.id}?label=${encodeURIComponent(label)}`).then(r => r.json())));
  let msgs = [];
  for (const r of results) if (r.status === 'fulfilled') msgs = msgs.concat(r.value.messages || []);
  renderInbox(msgs);
}

async function loadSmart(filter) {
  const list = $('mail-list'); const main = $('mail-main');
  main.innerHTML = '';
  list.innerHTML = `<div class="mail-empty">loading ${esc(filter)}…</div>`;
  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const results = await Promise.allSettled(accts.map(a =>
    fetch(`/api/mail/smart/${a.id}?filter=${encodeURIComponent(filter)}`).then(r => r.json())));
  let msgs = [];
  for (const r of results) if (r.status === 'fulfilled') msgs = msgs.concat(r.value.messages || []);
  renderInbox(msgs);
}

async function loadDrafts() {
  const list = $('mail-list'); const main = $('mail-main');
  main.innerHTML = '';
  list.innerHTML = '<div class="mail-empty">loading drafts…</div>';
  let drafts = [];
  try {
    const url = _active && _active !== 'all' ? `/api/mail/drafts?account_id=${encodeURIComponent(_active)}` : '/api/mail/drafts';
    drafts = await fetch(url).then(r => r.json());
  } catch { list.innerHTML = '<div class="mail-empty">failed to load drafts</div>'; return; }
  if (!drafts.length) { list.innerHTML = '<div class="mail-empty">no drafts</div>'; return; }
  list.innerHTML = drafts.map(d => `
    <div class="mail-row mail-draft-row" data-id="${esc(d.id)}">
      <div class="mail-row-top"><span class="mail-from">${esc(d.to || '(no recipient)')}</span>
        <button class="mail-draft-del" data-id="${esc(d.id)}" title="delete draft">×</button></div>
      <div class="mail-subj">${esc(d.subject || '(no subject)')}</div>
      <div class="mail-snippet">${esc((d.body || '').slice(0, 80))}</div>
    </div>`).join('');
  list.querySelectorAll('.mail-draft-row').forEach(row => {
    row.addEventListener('click', async e => {
      if (e.target.closest('.mail-draft-del')) return;
      const d = await fetch(`/api/mail/drafts/${row.dataset.id}`).then(r => r.json());
      compose(d);
    });
  });
  list.querySelectorAll('.mail-draft-del').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    await fetch(`/api/mail/drafts/${b.dataset.id}`, { method: 'DELETE' });
    loadDrafts();
  }));
}

async function loadInbox(force = false, silent = false) {
  const list = $('mail-list');
  const main = $('mail-main');
  if (!_accounts.length) return;
  const cached = readCache();
  if (!silent) {
    if (cached?.length) renderInbox(applyFilter(cached), []);   // instant, stale
    else list.innerHTML = `<div class="mail-empty">loading ${_filter}...</div>`;
    if (force) main.innerHTML = '';
  }

  const accts = _active === 'all' ? _accounts : _accounts.filter(a => a.id === _active);
  const results = await Promise.allSettled(accts.map(async a => {
    const folder = _filter === 'sent' ? await sentFolderFor(a) : 'INBOX';
    return fetchInboxFor(a, _active === 'all' ? 30 : 45, folder, silent);   // silent poll → cheap quick fetch
  }));
  const messages = results.flatMap(r => r.status === 'fulfilled' ? r.value : []);
  const errors = results
    .map((r, i) => r.status === 'rejected' ? `${acctName(accts[i].id)}: ${r.reason?.message || 'failed'}` : '')
    .filter(Boolean);
  if (messages.length || !cached?.length) {
    const newest = _newestKey(messages);
    if (silent && _lastNewest && newest === _lastNewest) return;   // nothing new — leave the UI alone
    if (silent && _lastNewest && newest !== _lastNewest) {
      const top = [...messages].sort((a, b) => _msgTime(b) - _msgTime(a))[0];
      if (top && !top.seen) toast(`new mail: ${fromName(top.from)} — ${(top.subject || '').slice(0, 60)}`, 'success');
    }
    _lastNewest = newest;
    renderInbox(applyFilter(messages), errors);
    if (messages.length) writeCache(messages);
  }
}

// ── live inbox: poll while the mail view is visible ─────────────────────────
let _pollTimer = null;
let _lastNewest = '';
const _msgTime = m => Number(m.date_ts || 0) || Math.floor((Date.parse(m.date || '') || 0) / 1000);
const _newestKey = msgs => [...msgs].sort((a, b) => _msgTime(b) - _msgTime(a))
  .slice(0, 5).map(m => `${m.account_id || ''}:${m.uid}`).join('|');

let _pollWired = false;
let _pollGen = 0;
export async function startMailPoll() {
  const gen = ++_pollGen;   // newer call wins the await race so a stale one can't leak a 2nd interval
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  let ms = 30000;
  try { ms = Math.max(10, Number((await fetch('/api/settings').then(r => r.json())).mail_poll_seconds) || 30) * 1000; } catch {}
  if (gen !== _pollGen) return;   // superseded while awaiting
  _pollTimer = setInterval(() => {
    const view = $('mail-view');
    if (!view || view.style.display === 'none' || document.hidden) return;
    if (_filter === 'sent' || !_accounts.length) return;
    loadInbox(false, true).catch(() => {});
  }, ms);
  if (_pollWired) return;
  _pollWired = true;
  document.addEventListener('visibilitychange', () => {
    // catch up immediately when the tab comes back
    if (!document.hidden && $('mail-view')?.style.display !== 'none' && _accounts.length) {
      loadInbox(false, true).catch(() => {});
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
  const unsub = _unsubLink(m.list_unsubscribe);
  return `
    <div class="mail-row${m.seen ? '' : ' unread'}${indent ? ' mail-row-child' : ''}" data-aid="${esc(m.account_id)}" data-uid="${esc(m.uid)}" data-folder="${esc(m.folder || 'INBOX')}" data-subject="${esc(m.subject)}">
      <div class="mail-row-top">
        <span class="mail-from">${esc(fromName(m.from))}</span>
        <span class="mail-date">${esc(shortDate(m.date))}</span>
        <span class="mail-row-acts">
          ${unsub ? `<button class="mail-act" data-unsub="${esc(unsub)}" title="unsubscribe">${_si('x-circle')}</button>` : ''}
          <button class="mail-act" data-label title="add a label">${_si('tag')}</button>
          <button class="mail-act" data-snooze title="snooze until tomorrow">${_si('snooze')}</button>
          <button class="mail-act" data-mute title="mute thread">${_si('mute')}</button>
          <button class="mail-act" data-archive title="archive">${_si('archive')}</button>
          <button class="mail-flag${m.flagged ? ' on' : ''}" data-flag title="flag">${_si(m.flagged ? 'star-fill' : 'star')}</button>
        </span>
      </div>
      <div class="mail-subject">${esc(m.subject)}${(m.labels || []).map(l => `<span class="mail-label-chip" data-labelfilter="${esc(l)}">${esc(l)}</span>`).join('')}</div>
      ${_active === 'all' ? `<div class="mail-account-badge">${esc(m.account_name || acctName(m.account_id))}</div>` : ''}
    </div>`;
};

function renderInbox(messages, errors = []) {
  const list = $('mail-list');
  const msgTime = m => Number(m.date_ts || 0) || Math.floor((Date.parse(m.date || '') || 0) / 1000);
  messages = [...messages].sort((a, b) => msgTime(b) - msgTime(a));
  _lastMsgs = messages;
  if (!messages.length && !errors.length) {
    list.innerHTML = `<div class="mail-empty">nothing in ${esc(_filter)}</div>`;
    return;
  }
  const errHtml = errors.length
    ? `<div class="mail-error-strip">${errors.map(esc).join('<br>')}</div>`
    : '';
  list.innerHTML = errHtml + (_threads ? _renderThreads(messages, msgTime) : messages.map(m => _msgRow(m)).join(''));
  _wireRows(list);
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
        <div class="mail-subject"><span class="mail-thread-caret">${open ? '▾' : '▸'}</span> ${esc(t.top.subject)} <span class="mail-thread-count">${t.msgs.length}</span></div>
        ${_active === 'all' ? `<div class="mail-account-badge">${esc(t.top.account_name || acctName(t.top.account_id))}</div>` : ''}
      </div>`;
    const kids = open ? t.msgs.map(m => _msgRow(m, true)).join('') : '';
    return head + kids;
  }).join('');
}

function _wireRows(list) {
  list.querySelectorAll('.mail-thread-head').forEach(h => h.addEventListener('click', () => {
    const k = h.dataset.thread;
    if (_expanded.has(k)) _expanded.delete(k); else _expanded.add(k);
    renderInbox(_lastMsgs);
  }));
  list.querySelectorAll('.mail-row:not(.mail-thread-head)').forEach(r => r.addEventListener('click', () => {
    list.querySelectorAll('.mail-row').forEach(x => x.classList.remove('sel'));
    r.classList.add('sel'); r.classList.remove('unread');
    openMessage(r.dataset.aid, r.dataset.uid, r.dataset.folder);
  }));
  list.querySelectorAll('.mail-flag').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const row = btn.closest('.mail-row');
    const on = !btn.classList.contains('on');
    btn.classList.toggle('on', on); btn.innerHTML = _si(on ? 'star-fill' : 'star');
    const m = _lastMsgs.find(x => String(x.uid) === row.dataset.uid && (x.account_id || '') === row.dataset.aid);
    if (m) m.flagged = on;
    await fetch(`/api/mail/flag/${row.dataset.aid}?uid=${encodeURIComponent(row.dataset.uid)}&folder=${encodeURIComponent(row.dataset.folder)}&flagged=${on}`, { method: 'POST' }).catch(() => {});
    if (_filter === 'flagged' && !on) row.remove();   // unflagged in the flagged view → drop it
  }));
  // 5a triage row actions
  list.querySelectorAll('[data-unsub]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const link = btn.dataset.unsub;
    if (link.startsWith('mailto:')) location.href = link;
    else window.open(link, '_blank', 'noopener');
    toast('opened unsubscribe', '');
  }));
  list.querySelectorAll('[data-mute]').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const row = btn.closest('.mail-row');
    await fetch(`/api/mail/mute/${row.dataset.aid}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ subject: row.dataset.subject }),
    }).catch(() => {});
    toast('thread muted', '');
    _reloadCurrent();
  }));
  list.querySelectorAll('[data-archive]').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const row = btn.closest('.mail-row');
    await fetch(`/api/mail/archive/${row.dataset.aid}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ uid: row.dataset.uid, folder: row.dataset.folder }),
    }).catch(() => {});
    row.remove();
    toast('archived', '');
  }));
  list.querySelectorAll('[data-label]').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const row = btn.closest('.mail-row');
    const label = await dlgPrompt('label this message:'); if (!label || !label.trim()) return;
    const m = _lastMsgs.find(x => String(x.uid) === row.dataset.uid && (x.account_id || '') === row.dataset.aid);
    const labels = [...new Set([...((m && m.labels) || []), label.trim().toLowerCase()])];
    await fetch(`/api/mail/labels/${row.dataset.aid}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ uid: row.dataset.uid, folder: row.dataset.folder, labels }),
    }).catch(() => {});
    if (m) m.labels = labels;
    renderInbox(_lastMsgs);
    toast('labeled', '');
  }));
  list.querySelectorAll('[data-labelfilter]').forEach(c => c.addEventListener('click', e => {
    e.stopPropagation();
    loadByLabel(c.dataset.labelfilter);
  }));
  list.querySelectorAll('[data-snooze]').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const row = btn.closest('.mail-row');
    const until = new Date(Date.now() + 864e5).toISOString();  // +1 day
    await fetch(`/api/mail/snooze/${row.dataset.aid}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ uid: row.dataset.uid, folder: row.dataset.folder, until }),
    }).catch(() => {});
    row.remove();
    toast('snoozed until tomorrow', '');
  }));
}

async function openMessage(aid, uid, folder = 'INBOX') {
  const main = $('mail-main');
  main.innerHTML = '<div class="mail-empty">loading message...</div>';
  let m;
  try {
    m = await fetch(`/api/mail/message/${aid}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(folder)}`).then(r => r.json());
  } catch {
    main.innerHTML = '<div class="mail-empty">failed to load message</div>';
    return;
  }
  if (m.error) { main.innerHTML = `<div class="mail-empty">${esc(m.error)}</div>`; return; }
  // actually mark it read on the server (+ locally so a refresh stays read)
  fetch(`/api/mail/seen/${aid}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(folder)}`, { method: 'POST' }).catch(() => {});
  markSeenLocal(aid, uid);
  const bodyHtml = m.html
    ? `<iframe class="mail-body-frame" sandbox></iframe>`
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
        <button class="btn" id="mail-to-task" title="create a task from this mail">→ task</button>
        <button class="btn" id="mail-to-cal" title="AI-extract the event and add it to your calendar">→ calendar</button>
        <button class="btn" id="mail-summarize" title="AI summary + action items">summarize</button>
      </div>
    </div>
    <div class="mail-summary" id="mail-summary" style="display:none"></div>
    <div class="mail-reader-body">${bodyHtml}</div>
  </div>`;
  if (m.html) {
    const f = main.querySelector('.mail-body-frame');
    f.srcdoc = `<style>body{font-family:Inter,system-ui,sans-serif;color:#111;background:#fff;font-size:14px;padding:8px;margin:0}</style>${m.html}`;
  }
  // attachment chips — backend lists/serves them, the reader just never showed them
  loadAttachments(aid, uid, folder);
  const senderAddr = ((/<([^>]+)>/.exec(m.from) || [, m.from])[1] || '').trim().toLowerCase();
  $('mail-unread')?.addEventListener('click', async () => {
    await fetch(`/api/mail/read/${aid}?uid=${encodeURIComponent(uid)}&seen=false&folder=${encodeURIComponent(folder)}`, { method: 'POST' }).catch(() => {});
    const row = [...document.querySelectorAll('.mail-row')].find(r => r.dataset.uid === String(uid) && r.dataset.aid === aid);
    if (row) row.classList.add('unread');
    const lm = _lastMsgs.find(x => String(x.uid) === String(uid) && (x.account_id || '') === aid); if (lm) lm.seen = false;
    toast('marked unread', 'success');
  });
  (async () => {
    const vips = ((await fetch('/api/mail/vips').then(r => r.json()).catch(() => ({ vips: [] }))).vips || []).map(v => v.toLowerCase());
    const btn = $('mail-vip'); if (btn) { const on = vips.includes(senderAddr); btn.classList.toggle('on', on); btn.textContent = on ? 'VIP ★' : '+ VIP'; }
  })();
  $('mail-vip')?.addEventListener('click', async () => {
    const btn = $('mail-vip'); const adding = !btn.classList.contains('on');
    await fetch('/api/mail/vips', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: senderAddr, add: adding }) }).catch(() => {});
    btn.classList.toggle('on', adding); btn.textContent = adding ? 'VIP ★' : '+ VIP';
    toast(adding ? 'added to VIP' : 'removed from VIP', 'success');
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
  $('mail-to-task')?.addEventListener('click', async () => {
    const r = await fetch('/api/mail/make-task', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title: m.subject || `mail from ${fromName(m.from)}` }),
    });
    toast(r.ok ? 'task created' : 'failed to create task', r.ok ? 'success' : 'error');
  });
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
    } catch { toast('summarize failed', 'error'); }
    btn.disabled = false; btn.textContent = 'summarize';
  });
  $('mail-to-cal')?.addEventListener('click', async () => {
    const btn = $('mail-to-cal');
    btn.disabled = true; btn.textContent = 'extracting...';
    try {
      const r = await fetch('/api/mail/extract-event', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ subject: m.subject || '', body: m.text || '', date: m.date || '' }),
      });
      const d = await r.json();
      if (!r.ok) { toast(d.detail || 'extraction failed', 'error'); }
      else if (!d.found) { toast('no event found in this mail', ''); }
      else {
        const when = d.all_day ? d.start.slice(0, 10) : d.start.replace('T', ' ');
        toast(`added to calendar: ${d.title} — ${when}`, 'success');
      }
    } catch { toast('extraction failed', 'error'); }
    btn.disabled = false; btn.textContent = '→ calendar';
  });
}

const fmtBytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;

async function loadAttachments(aid, uid, folder) {
  let d;
  try {
    d = await fetch(`/api/mail/attachments/${aid}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(folder)}`).then(r => r.json());
  } catch { return; }
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

async function compose(pre = {}) {
  // blank new message picks up the saved signature; replies keep their quote untouched
  if (!pre.body) {
    try {
      const sig = (await fetch('/api/settings').then(r => r.json())).mail_signature;
      if (sig) pre = { ...pre, body: '\n\n' + sig };
    } catch {}
  }
  const main = $('mail-main');
  const defaultAid = pre.account_id || (_active !== 'all' ? _active : _accounts[0]?.id);
  main.innerHTML = `<div class="mail-compose">
    <div class="mail-form-head">
      <div>
        <div class="mail-compose-head">new message</div>
        <div class="mail-form-sub">from ${esc(acctName(defaultAid))}</div>
      </div>
      <div class="mail-form-actions">
        <button class="btn" id="mc-close">close</button>
        <button class="btn" id="mc-save">save draft</button>
        <span class="mc-sched-wrap" id="mc-sched-wrap" style="display:none">
          <input class="settings-input date-input mc-sched-date" id="mc-sched-date" placeholder="date">
          <input class="settings-input mc-sched-time" id="mc-sched-time" placeholder="HH:MM" value="09:00" maxlength="5">
        </span>
        <button class="btn" id="mc-schedule" title="schedule for later">schedule</button>
        <button class="btn primary" id="mc-send">send</button>
      </div>
    </div>
    ${_accounts.length > 1 ? `<div class="settings-input custom-select" id="mc-account"></div>` : ''}
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
    </div>
    <div class="settings-input mail-compose-body mail-rich-body" id="mc-html" contenteditable="true" data-ph="write your message…">${pre.body || ''}</div>
    <div id="mc-suggest-box" class="mail-suggest-box"></div>
    <input type="file" id="mc-image-input" accept="image/*" style="display:none">
    <div id="mc-status" class="mail-status"></div>
  </div>`;
  if ($('mc-account')) populateDropdown($('mc-account'), _accounts.map(a => ({ value: a.id, label: a.name || a.email })), defaultAid);
  // recipient chip fields + address autocomplete (4d)
  main.querySelectorAll('.mc-chipfield').forEach(f => _initChipField(f));
  if (pre.to) main.querySelector('.mc-chipfield[data-role="to"]')._add(pre.to);
  if (pre.cc) { $('mc-cc-row').style.display = ''; main.querySelector('.mc-chipfield[data-role="cc"]')._add(pre.cc); }
  if (pre.bcc) { $('mc-bcc-row').style.display = ''; main.querySelector('.mc-chipfield[data-role="bcc"]')._add(pre.bcc); }
  $('mc-add-cc')?.addEventListener('click', () => { $('mc-cc-row').style.display = ''; $('mc-cc-row').querySelector('.mc-chip-input').focus(); });
  $('mc-add-bcc')?.addEventListener('click', () => { $('mc-bcc-row').style.display = ''; $('mc-bcc-row').querySelector('.mc-chip-input').focus(); });
  _loadAddrBook();   // warm the autocomplete cache
  let _draftId = pre.id || '';
  const initial = serializeForm(main);
  const _draftBody = () => ({
    id: _draftId, account_id: $('mc-account')?.value || defaultAid,
    to: $('mc-to').value.trim(), cc: $('mc-cc').value.trim(), bcc: $('mc-bcc').value.trim(),
    subject: $('mc-subj').value, body: $('mc-html')?.innerHTML || '',
    in_reply_to: pre.in_reply_to || '', references: pre.references || '',
  });
  // rich-compose toolbar + signatures (5c)
  _wireRichCompose(defaultAid);
  $('mc-save').addEventListener('click', async () => {
    const d = await fetch('/api/mail/drafts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(_draftBody()) }).then(r => r.json()).catch(() => null);
    if (d?.id) { _draftId = d.id; toast('draft saved', 'success'); } else toast('save failed', 'error');
  });
  $('mc-close').addEventListener('click', async () => {
    if (serializeForm(main) !== initial && !await dlgConfirm('discard this draft?')) return;
    main.innerHTML = '';
  });
  const _composeBody = () => {
    const el = $('mc-html');
    return {
      to: $('mc-to').value.trim(), cc: $('mc-cc').value.trim(), bcc: $('mc-bcc').value.trim(),
      subject: $('mc-subj').value, body: el?.innerText || '', html: el?.innerHTML || '',
      in_reply_to: pre.in_reply_to || '', references: pre.references || '',
    };
  };
  // schedule send (5b) — first click reveals a date picker + time, second click schedules (4d)
  $('mc-schedule').addEventListener('click', async () => {
    const wrap = $('mc-sched-wrap');
    if (wrap.style.display === 'none') {
      wrap.style.display = '';
      _dpInit($('mc-sched-date'));
      $('mc-schedule').textContent = 'schedule send';
      $('mc-sched-date').focus();
      return;
    }
    const aid = $('mc-account')?.value || defaultAid;
    const to = $('mc-to').value.trim();
    const date = $('mc-sched-date').value.trim();
    const time = ($('mc-sched-time').value.trim() || '09:00');
    if (!to) { toast('recipient required', 'error'); return; }
    if (!date) { toast('pick a date', 'error'); return; }
    if (!/^\d{1,2}:\d{2}$/.test(time)) { toast('time must be HH:MM', 'error'); return; }
    const send_at = `${date}T${time.padStart(5, '0')}`;
    const r = await fetch(`/api/mail/schedule/${aid}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ..._composeBody(), send_at }),
    }).then(x => x.json()).catch(() => null);
    if (r?.id) {
      if (_draftId) fetch(`/api/mail/drafts/${_draftId}`, { method: 'DELETE' }).catch(() => {});
      toast('scheduled', 'success'); main.innerHTML = ''; _renderScheduled(); loadInbox();
    } else toast('schedule failed', 'error');
  });
  // send with an undo window (5b): queue a few seconds out, offer undo
  $('mc-send').addEventListener('click', async () => {
    const aid = $('mc-account')?.value || defaultAid;
    const to = $('mc-to').value.trim();
    if (!to) { toast('recipient required', 'error'); return; }
    const r = await fetch(`/api/mail/send-undoable/${aid}`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ..._composeBody(), delay: 8 }),
    }).then(x => x.json()).catch(() => null);
    if (r?.id) {
      if (_draftId) fetch(`/api/mail/drafts/${_draftId}`, { method: 'DELETE' }).catch(() => {});
      main.innerHTML = '';
      _showUndoBar(r.id);
      loadInbox();
    } else { $('mc-status').textContent = 'send failed'; }
  });
}

async function _wireRichCompose(defaultAid) {
  document.querySelectorAll('#mc-richbar .mc-rt').forEach(b => b.addEventListener('mousedown', e => {
    e.preventDefault();  // keep the editor selection
    const cmd = b.dataset.cmd;
    if (cmd === 'createLink') {
      const url = window.prompt('link URL:');
      if (url) document.execCommand('createLink', false, url);
    } else document.execCommand(cmd, false, null);
  }));
  $('mc-suggest')?.addEventListener('click', async () => {
    const box = $('mc-suggest-box'); if (!box) return;
    box.innerHTML = '<span class="mail-suggest-off">thinking…</span>';
    const ctx = $('mc-html')?.innerText || $('mc-subj')?.value || '';
    let d;
    try { d = await fetch('/api/mail/smart-reply', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: ctx }) }).then(r => r.json()); }
    catch { d = { enabled: false, suggestions: [] }; }
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
      const ed = $('mc-html'); ed?.focus();
      document.execCommand('insertHTML', false, `<img src="/api/uploads/${up.id}" alt="${esc(up.name || '')}" style="max-width:100%">`);
    } catch { toast('image upload failed', 'error'); }
  });
  // signature chips — click to append (5c)
  let sigs = [];
  try { sigs = (await fetch('/api/mail/signatures').then(r => r.json())).signatures || []; } catch {}
  const list = $('mc-sig-list');
  if (list) {
    list.innerHTML = sigs.map(s => `<button class="btn mc-sig-chip" data-sig="${esc(s.id)}" title="insert signature">✎ ${esc(s.name)}</button>`).join('');
    list.querySelectorAll('.mc-sig-chip').forEach(b => b.addEventListener('click', () => {
      const s = sigs.find(x => x.id === b.dataset.sig); if (!s) return;
      const ed = $('mc-html'); if (!ed) return;
      ed.innerHTML += `<div class="mail-sig" data-sig>--<br>${esc(s.body).replace(/\n/g, '<br>')}</div>`;
    }));
  }
  $('mc-sig-add')?.addEventListener('click', async () => {
    const name = await dlgPrompt('signature name:'); if (!name) return;
    const bodyTxt = await dlgPrompt('signature text:'); if (bodyTxt == null) return;
    await fetch('/api/mail/signatures', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, body: bodyTxt }),
    }).catch(() => {});
    toast('signature saved', 'success');
    _wireRichCompose(defaultAid);  // refresh the picker
  });
}

function _showUndoBar(scheduledId) {
  let bar = $('mail-undo-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'mail-undo-bar'; bar.className = 'mail-undo-bar';
    document.getElementById('mail-view')?.appendChild(bar);
  }
  bar.innerHTML = `<span>message sending…</span><button class="btn" id="mail-undo-btn">undo</button>`;
  bar.style.display = 'flex';
  const hide = () => { bar.style.display = 'none'; };
  const t = setTimeout(hide, 8000);
  $('mail-undo-btn').addEventListener('click', async () => {
    clearTimeout(t);
    await fetch(`/api/mail/scheduled/${scheduledId}/cancel`, { method: 'POST' }).catch(() => {});
    toast('send canceled', '');
    hide();
    _renderScheduled();
  });
}

// scheduled-send strip (5b): pending scheduled messages with a cancel
async function _renderScheduled() {
  const bar = $('mail-scheduled'); if (!bar) return;
  let items = [];
  try { items = (await fetch('/api/mail/scheduled').then(r => r.json())).scheduled || []; } catch {}
  if (!items.length) { bar.innerHTML = ''; return; }
  bar.innerHTML = `<span class="mail-sched-lbl">scheduled</span>` + items.map(s =>
    `<span class="mail-sched-chip" title="to ${esc(s.to)}">🕒 ${esc(s.subject || '(no subject)')} · ${esc((s.send_at || '').slice(0, 16))}<button class="mail-sched-cancel" data-cancel="${esc(s.id)}" title="cancel">×</button></span>`).join('');
  bar.querySelectorAll('.mail-sched-cancel').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/mail/scheduled/${b.dataset.cancel}/cancel`, { method: 'POST' }).catch(() => {});
    _renderScheduled();
  }));
}

async function rulesPanel() {
  const main = $('mail-main');
  main.innerHTML = '<div class="mail-empty">loading rules…</div>';
  let rules = [], vac = { enabled: false, subject: 'Out of office', body: '' };
  try { rules = (await fetch('/api/mail/rules').then(r => r.json())).rules || []; } catch {}
  try { vac = await fetch('/api/mail/vacation').then(r => r.json()); } catch {}
  const ruleRows = rules.map(r => `
    <div class="mail-rule-row" data-id="${esc(r.id)}">
      <span>if <b>${esc(r.match_field)}</b> contains “${esc(r.match_value)}” → <b>${esc(r.action)}</b>${r.action_arg ? ` (${esc(r.action_arg)})` : ''}</span>
      <button class="btn danger mail-rule-del" data-id="${esc(r.id)}">×</button>
    </div>`).join('') || '<div class="mail-empty-sm">no rules yet</div>';
  main.innerHTML = `<div class="mail-rules-panel">
    <div class="mail-compose-head">rules</div>
    <div id="mail-rules-list">${ruleRows}</div>
    <div class="mail-rule-form">
      <div class="settings-input custom-select" id="mr-field" style="width:100px"></div>
      <input class="settings-input" id="mr-value" placeholder="contains…" style="flex:1;min-width:120px">
      <div class="settings-input custom-select" id="mr-action" style="width:120px"></div>
      <input class="settings-input" id="mr-arg" placeholder="label / reply (optional)" style="width:150px">
      <button class="btn primary" id="mr-add">add rule</button>
    </div>
    <div class="mail-rule-actions"><button class="btn" id="mr-run">run rules now</button><span id="mr-run-status" class="mail-status"></span></div>
    <div class="mail-compose-head" style="margin-top:1rem">vacation responder</div>
    <button class="btn mail-vac-toggle${vac.enabled ? ' active' : ''}" id="mv-enabled" aria-pressed="${vac.enabled ? 'true' : 'false'}">${vac.enabled ? '✓ ' : ''}auto-reply when I'm away</button>
    <input class="settings-input" id="mv-subject" placeholder="subject" value="${esc(vac.subject || '')}">
    <textarea class="settings-input mail-compose-body" id="mv-body" placeholder="out-of-office message…">${esc(vac.body || '')}</textarea>
    <button class="btn primary" id="mv-save">save vacation reply</button>
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
  main.querySelectorAll('.mail-rule-del').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/mail/rules/${b.dataset.id}`, { method: 'DELETE' }).catch(() => {});
    rulesPanel();
  }));
  $('mr-add').addEventListener('click', async () => {
    const val = $('mr-value').value.trim();
    if (!val) { toast('enter a match value', 'error'); return; }
    await fetch('/api/mail/rules', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ match_field: getDropdownValue($('mr-field')) || 'from', match_value: val, action: getDropdownValue($('mr-action')) || 'markread', action_arg: $('mr-arg').value.trim() }),
    }).catch(() => {});
    rulesPanel();
  });
  $('mr-run').addEventListener('click', async () => {
    let total = 0;
    for (const a of _accounts) {
      const d = await fetch(`/api/mail/rules/run/${a.id}`, { method: 'POST' }).then(r => r.json()).catch(() => ({ applied: 0 }));
      total += d.applied || 0;
    }
    $('mr-run-status').textContent = `applied to ${total} message(s)`;
    loadInbox();
  });
  $('mv-save').addEventListener('click', async () => {
    await fetch('/api/mail/vacation', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled: $('mv-enabled').getAttribute('aria-pressed') === 'true', subject: $('mv-subject').value, body: $('mv-body').value }),
    }).catch(() => {});
    toast('vacation reply saved', 'success');
  });
}

function accountsPanel(firstRun = false) {
  const main = $('mail-main');
  const rows = _accounts.map(a => `
    <div class="mail-acct-row">
      <span><b>${esc(a.name || a.email)}</b><em>${esc(a.email)}</em></span>
      <span class="mail-acct-actions">
        <button class="btn mail-acct-edit" data-id="${esc(a.id)}">edit</button>
        <button class="btn mail-acct-del" data-id="${esc(a.id)}">remove</button>
      </span>
    </div>`).join('');
  main.innerHTML = `<div class="mail-accounts">
    <div class="mail-form-head">
      <div>
        <div class="mail-compose-head">accounts</div>
        <div class="mail-form-sub">${firstRun ? 'connect a mailbox to get started' : `${_accounts.length} connected`}</div>
      </div>
      <div class="mail-form-actions">
        <button class="btn" id="mail-accounts-close">close</button>
        <button class="btn primary" id="mail-add-acct">add</button>
      </div>
    </div>
    <div class="mail-service-links">${providerHelpHtml()}</div>
    ${rows || '<div class="mail-empty" style="padding:0.75rem 0">credentials stay on this machine.</div>'}
  </div>`;
  $('mail-accounts-close')?.addEventListener('click', () => { main.innerHTML = ''; });
  $('mail-add-acct')?.addEventListener('click', () => acctForm(null));
  main.querySelectorAll('.mail-acct-edit').forEach(b => b.addEventListener('click', () => acctForm(_accounts.find(a => a.id === b.dataset.id))));
  main.querySelectorAll('.mail-acct-del').forEach(b => b.addEventListener('click', async () => {
    if (!await dlgConfirm('remove this account?')) return;
    await fetch(`/api/mail/accounts/${b.dataset.id}`, { method: 'DELETE' });
    if (_active === b.dataset.id) _active = 'all';
    await loadMail();
  }));
}

function acctForm(acct) {
  const main = $('mail-main');
  const a = acct || {};
  main.innerHTML = `<div class="mail-accounts">
    <div class="mail-form-head">
      <div>
        <div class="mail-compose-head">${acct ? 'edit account' : 'add account'}</div>
        <div class="mail-form-sub">IMAP receives, SMTP sends</div>
      </div>
      <div class="mail-form-actions">
        <button class="btn" id="ma-close">close</button>
        <button class="btn primary" id="ma-save">save</button>
      </div>
    </div>
    <input class="settings-input" id="ma-email" placeholder="email address" value="${esc(a.email || '')}">
    <input class="settings-input" id="ma-name" placeholder="label (optional)" value="${esc(a.name || '')}">
    <div class="mail-provider-row">
      ${PRESETS.map(p => `<button class="mail-provider-btn" type="button" data-provider="${esc(p.key)}">${esc(p.label)}</button>`).join('')}
    </div>
    <div class="mail-provider-note" id="ma-provider-note">pick a provider, or paste your own IMAP/SMTP hosts.</div>
    <div class="mail-form-grid">
      <input class="settings-input" id="ma-imaph" placeholder="imap host" value="${esc(a.imap_host || '')}">
      <input class="settings-input" id="ma-imapp" placeholder="imap port" value="${esc(a.imap_port || 993)}">
      <input class="settings-input" id="ma-smtph" placeholder="smtp host" value="${esc(a.smtp_host || '')}">
      <input class="settings-input" id="ma-smtpp" placeholder="smtp port" value="${esc(a.smtp_port || 587)}">
    </div>
    <input class="settings-input" id="ma-user" placeholder="username (usually your email)" value="${esc(a.username || a.email || '')}">
    <input class="settings-input" type="password" id="ma-pass" placeholder="${acct ? 'password (leave blank to keep)' : 'app-specific password'}">
    <div id="ma-status" class="mail-status"></div>
  </div>`;

  const applyProvider = (p) => {
    const em = $('ma-email').value.trim();
    if (!p) return;
    if (p.key === 'domain') {
      const domain = domainFromEmail(em);
      if (domain) {
        $('ma-imaph').value = `imap.${domain}`;
        $('ma-smtph').value = `smtp.${domain}`;
        if (!$('ma-name').value) $('ma-name').value = domain;
      }
      $('ma-provider-note').innerHTML = 'Own domain: point MX to your mail server/provider, then use its IMAP/SMTP host here. Add SPF, DKIM, and DMARC for deliverability.';
    } else {
      $('ma-imaph').value = p.imap;
      $('ma-smtph').value = p.smtp;
      $('ma-provider-note').innerHTML = `${esc(p.note)} ${p.help ? `<a href="${esc(p.help)}" target="_blank" rel="noreferrer">setup help</a>` : ''}`;
    }
    $('ma-imapp').value = 993;
    $('ma-smtpp').value = 587;
    if (!$('ma-user').value) $('ma-user').value = em;
  };
  document.querySelectorAll('.mail-provider-btn').forEach(btn => {
    btn.addEventListener('click', () => applyProvider(PRESETS.find(p => p.key === btn.dataset.provider)));
  });
  $('ma-email').addEventListener('blur', () => {
    const p = providerForEmail($('ma-email').value.trim());
    if (p && !$('ma-imaph').value && !$('ma-smtph').value) applyProvider(p);
  });

  const collect = () => ({
    email: $('ma-email').value.trim(),
    name: $('ma-name').value.trim(),
    imap_host: $('ma-imaph').value.trim(),
    imap_port: +$('ma-imapp').value || 993,
    smtp_host: $('ma-smtph').value.trim(),
    smtp_port: +$('ma-smtpp').value || 587,
    username: $('ma-user').value.trim() || $('ma-email').value.trim(),
    password: $('ma-pass').value,
    use_ssl: true,
  });
  const initial = serializeForm(main);
  $('ma-close').addEventListener('click', async () => {
    if (serializeForm(main) !== initial && !await dlgConfirm('discard account changes?')) return;
    accountsPanel();
  });
  $('ma-save').addEventListener('click', async () => {
    const body = collect();
    if (!body.email || !body.imap_host || !body.smtp_host) {
      toast('email, imap, and smtp are required', 'error');
      return;
    }
    $('ma-status').textContent = 'saving...';
    const url = acct ? `/api/mail/accounts/${acct.id}` : '/api/mail/accounts';
    const method = acct ? 'PATCH' : 'POST';
    const res = await fetch(url, { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json()).catch(() => ({ error: 'network' }));
    if (res.error) { $('ma-status').textContent = 'failed: ' + res.error; return; }
    _active = res.id || acct?.id || _active;
    localStorage.setItem('alles-mail-account-mode', _active);
    toast('saved', 'success');
    await loadMail();
    accountsPanel();
  });
}

function serializeForm(root) {
  return [...root.querySelectorAll('input,textarea,select')]
    .map(el => `${el.id || el.name || el.placeholder}:${el.value}`)
    .join('\n');
}
