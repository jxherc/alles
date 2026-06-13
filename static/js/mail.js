import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _accounts = [];
let _active = localStorage.getItem('alles-mail-account-mode') || 'all';
let _filter = 'inbox';        // inbox | unread | sent
const _sentFolders = {};      // account_id -> detected sent folder name

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
  $('mail-compose-btn')?.addEventListener('click', () => compose());
  $('mail-accounts-btn')?.addEventListener('click', () => accountsPanel());
  document.querySelectorAll('.mail-tab').forEach(t =>
    t.addEventListener('click', () => setFilter(t.dataset.filter)));
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
  if (d.error) throw new Error(d.error);
  return (d.messages || []).map(m => ({ ...m, account_id: account.id, account_name: account.name || account.email, folder }));
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

function setFilter(f) {
  if (_filter === f) return;
  _filter = f;
  document.querySelectorAll('.mail-tab').forEach(t => t.classList.toggle('active', t.dataset.filter === f));
  loadInbox();
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

export function startMailPoll(intervalMs = 30000) {
  if (_pollTimer) return;
  _pollTimer = setInterval(() => {
    const view = $('mail-view');
    if (!view || view.style.display === 'none' || document.hidden) return;
    if (_filter === 'sent' || !_accounts.length) return;
    loadInbox(false, true).catch(() => {});
  }, intervalMs);
  document.addEventListener('visibilitychange', () => {
    // catch up immediately when the tab comes back
    if (!document.hidden && $('mail-view')?.style.display !== 'none' && _accounts.length) {
      loadInbox(false, true).catch(() => {});
    }
  });
}

function renderInbox(messages, errors = []) {
  const list = $('mail-list');
  const msgTime = m => Number(m.date_ts || 0) || Math.floor((Date.parse(m.date || '') || 0) / 1000);
  messages.sort((a, b) => msgTime(b) - msgTime(a));
  if (!messages.length && !errors.length) {
    list.innerHTML = `<div class="mail-empty">nothing in ${esc(_filter)}</div>`;
    return;
  }
  const errHtml = errors.length
    ? `<div class="mail-error-strip">${errors.map(esc).join('<br>')}</div>`
    : '';
  const rowHtml = messages.map(m => `
    <div class="mail-row${m.seen ? '' : ' unread'}" data-aid="${esc(m.account_id)}" data-uid="${esc(m.uid)}" data-folder="${esc(m.folder || 'INBOX')}">
      <div class="mail-row-top">
        <span class="mail-from">${esc(fromName(m.from))}</span>
        <span class="mail-date">${esc(shortDate(m.date))}</span>
      </div>
      <div class="mail-subject">${esc(m.subject)}</div>
      ${_active === 'all' ? `<div class="mail-account-badge">${esc(m.account_name || acctName(m.account_id))}</div>` : ''}
    </div>`).join('');
  list.innerHTML = errHtml + rowHtml;
  list.querySelectorAll('.mail-row').forEach(r => r.addEventListener('click', () => {
    list.querySelectorAll('.mail-row').forEach(x => x.classList.remove('sel'));
    r.classList.add('sel'); r.classList.remove('unread');
    openMessage(r.dataset.aid, r.dataset.uid, r.dataset.folder);
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
  $('mail-reply')?.addEventListener('click', () => {
    const addr = (/<([^>]+)>/.exec(m.from) || [, m.from])[1];
    compose({ account_id: aid, to: addr, subject: /^re:/i.test(m.subject) ? m.subject : 'Re: ' + m.subject, body: `\n\n-- on ${m.date}, ${fromName(m.from)} wrote --\n${(m.text || '').split('\n').map(l => '> ' + l).join('\n')}` });
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

function compose(pre = {}) {
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
        <button class="btn primary" id="mc-send">send</button>
      </div>
    </div>
    ${_accounts.length > 1 ? `<div class="settings-input custom-select" id="mc-account"></div>` : ''}
    <input class="settings-input" id="mc-to" placeholder="to" value="${esc(pre.to || '')}">
    <input class="settings-input" id="mc-cc" placeholder="cc (optional)">
    <input class="settings-input" id="mc-subj" placeholder="subject" value="${esc(pre.subject || '')}">
    <textarea class="settings-input mail-compose-body" id="mc-body" placeholder="write your message...">${esc(pre.body || '')}</textarea>
    <div id="mc-status" class="mail-status"></div>
  </div>`;
  if ($('mc-account')) populateDropdown($('mc-account'), _accounts.map(a => ({ value: a.id, label: a.name || a.email })), defaultAid);
  const initial = serializeForm(main);
  $('mc-close').addEventListener('click', async () => {
    if (serializeForm(main) !== initial && !await dlgConfirm('discard this draft?')) return;
    main.innerHTML = '';
  });
  $('mc-send').addEventListener('click', async () => {
    const aid = $('mc-account')?.value || defaultAid;
    const to = $('mc-to').value.trim();
    if (!to) { toast('recipient required', 'error'); return; }
    $('mc-status').textContent = 'sending...';
    const body = { to, cc: $('mc-cc').value.trim(), subject: $('mc-subj').value, body: $('mc-body').value };
    const r = await fetch(`/api/mail/send/${aid}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json()).catch(() => ({ error: 'network' }));
    if (r.ok) { toast('sent', 'success'); main.innerHTML = ''; loadInbox(); }
    else { $('mc-status').textContent = 'failed: ' + (r.error || 'unknown'); }
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
