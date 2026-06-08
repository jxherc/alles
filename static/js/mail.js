import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';

let _accounts = [];
let _active = null;     // active account id
let _folder = 'INBOX';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const fromName = f => { const m = /^(.*?)\s*<([^>]+)>/.exec(f || ''); return (m ? (m[1].replace(/"/g, '').trim() || m[2]) : f) || '(unknown)'; };
const shortDate = d => { try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); } catch { return ''; } };

// known providers — autofill on email entry
const PRESETS = [
  { re: /@(icloud|me|mac)\.com$/i, imap: 'imap.mail.me.com', smtp: 'smtp.mail.me.com' },
  { re: /@gmail\.com$/i, imap: 'imap.gmail.com', smtp: 'smtp.gmail.com' },
  { re: /@(outlook|hotmail|live)\.com$/i, imap: 'outlook.office365.com', smtp: 'smtp.office365.com' },
  { re: /@yahoo\.com$/i, imap: 'imap.mail.yahoo.com', smtp: 'smtp.mail.yahoo.com' },
  { re: /@fastmail\.com$/i, imap: 'imap.fastmail.com', smtp: 'smtp.fastmail.com' },
];

let _inited = false;
export function initMail() {
  if (_inited) return;
  _inited = true;
  $('mail-account')?.addEventListener('change', e => { _active = e.target.value; loadInbox(); });
  $('mail-refresh-btn')?.addEventListener('click', () => loadInbox());
  $('mail-compose-btn')?.addEventListener('click', () => compose());
  $('mail-accounts-btn')?.addEventListener('click', () => accountsPanel());
}

export async function loadMail() {
  initMail();
  _accounts = await fetch('/api/mail/accounts').then(r => r.json()).catch(() => []);
  const sel = $('mail-account');
  if (!_accounts.length) {
    sel.innerHTML = '';
    $('mail-list').innerHTML = '';
    accountsPanel(true);
    return;
  }
  if (!_active || !_accounts.find(a => a.id === _active)) _active = _accounts[0].id;
  sel.innerHTML = _accounts.map(a => `<option value="${a.id}" ${a.id === _active ? 'selected' : ''}>${esc(a.name || a.email)}</option>`).join('');
  loadInbox();
}

async function loadInbox() {
  if (!_active) return;
  const list = $('mail-list');
  list.innerHTML = '<div class="mail-empty">loading inbox…</div>';
  let d;
  try { d = await fetch(`/api/mail/inbox/${_active}?folder=${encodeURIComponent(_folder)}&limit=40`).then(r => r.json()); }
  catch { list.innerHTML = '<div class="mail-empty">failed to load</div>'; return; }
  if (d.error) { list.innerHTML = `<div class="mail-empty">couldn't reach the server:<br><span style="color:var(--error)">${esc(d.error)}</span><br><br>check the account settings.</div>`; return; }
  const msgs = d.messages || [];
  if (!msgs.length) { list.innerHTML = '<div class="mail-empty">inbox empty</div>'; return; }
  list.innerHTML = msgs.map(m => `
    <div class="mail-row${m.seen ? '' : ' unread'}" data-uid="${esc(m.uid)}">
      <div class="mail-row-top"><span class="mail-from">${esc(fromName(m.from))}</span><span class="mail-date">${esc(shortDate(m.date))}</span></div>
      <div class="mail-subject">${esc(m.subject)}</div>
    </div>`).join('');
  list.querySelectorAll('.mail-row').forEach(r => r.addEventListener('click', () => {
    list.querySelectorAll('.mail-row').forEach(x => x.classList.remove('sel'));
    r.classList.add('sel'); r.classList.remove('unread');
    openMessage(r.dataset.uid);
  }));
}

async function openMessage(uid) {
  const main = $('mail-main');
  main.innerHTML = '<div class="mail-empty">loading…</div>';
  let m;
  try { m = await fetch(`/api/mail/message/${_active}?uid=${encodeURIComponent(uid)}&folder=${encodeURIComponent(_folder)}`).then(r => r.json()); }
  catch { main.innerHTML = '<div class="mail-empty">failed to load message</div>'; return; }
  if (m.error) { main.innerHTML = `<div class="mail-empty">${esc(m.error)}</div>`; return; }
  const bodyHtml = m.html
    ? `<iframe class="mail-body-frame" sandbox></iframe>`
    : `<pre class="mail-body-text">${esc(m.text || '(no content)')}</pre>`;
  main.innerHTML = `<div class="mail-reader">
    <div class="mail-reader-head">
      <div class="mail-reader-subject">${esc(m.subject)}</div>
      <div class="mail-reader-meta"><b>${esc(fromName(m.from))}</b> &lt;${esc((/<([^>]+)>/.exec(m.from) || [, m.from])[1])}&gt;</div>
      <div class="mail-reader-meta">to ${esc(m.to)} · ${esc(m.date)}</div>
      <button class="btn" id="mail-reply" style="margin-top:0.4rem;font-size:0.72rem">reply</button>
    </div>
    <div class="mail-reader-body">${bodyHtml}</div>
  </div>`;
  if (m.html) {
    const f = main.querySelector('.mail-body-frame');
    f.srcdoc = `<style>body{font-family:Inter,system-ui,sans-serif;color:#111;background:#fff;font-size:14px;padding:8px;margin:0}</style>${m.html}`;
  }
  $('mail-reply')?.addEventListener('click', () => {
    const addr = (/<([^>]+)>/.exec(m.from) || [, m.from])[1];
    compose({ to: addr, subject: /^re:/i.test(m.subject) ? m.subject : 'Re: ' + m.subject, body: `\n\n— on ${m.date}, ${fromName(m.from)} wrote —\n${(m.text || '').split('\n').map(l => '> ' + l).join('\n')}` });
  });
}

function compose(pre = {}) {
  const main = $('mail-main');
  main.innerHTML = `<div class="mail-compose">
    <div class="mail-compose-head">new message</div>
    <input class="settings-input" id="mc-to" placeholder="to" value="${esc(pre.to || '')}">
    <input class="settings-input" id="mc-cc" placeholder="cc (optional)">
    <input class="settings-input" id="mc-subj" placeholder="subject" value="${esc(pre.subject || '')}">
    <textarea class="settings-input mail-compose-body" id="mc-body" placeholder="write your message…">${esc(pre.body || '')}</textarea>
    <div style="display:flex;gap:0.4rem;justify-content:flex-end">
      <button class="btn" id="mc-cancel">cancel</button>
      <button class="btn primary" id="mc-send">send</button>
    </div>
    <div id="mc-status" style="font-size:0.72rem;color:var(--muted);text-align:right"></div>
  </div>`;
  $('mc-cancel').addEventListener('click', () => { main.innerHTML = ''; });
  $('mc-send').addEventListener('click', async () => {
    const to = $('mc-to').value.trim();
    if (!to) { toast('recipient required', 'error'); return; }
    $('mc-status').textContent = 'sending…';
    const body = { to, cc: $('mc-cc').value.trim(), subject: $('mc-subj').value, body: $('mc-body').value };
    const r = await fetch(`/api/mail/send/${_active}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json()).catch(() => ({ error: 'network' }));
    if (r.ok) { toast('sent', 'success'); main.innerHTML = ''; }
    else { $('mc-status').textContent = 'failed: ' + (r.error || 'unknown'); }
  });
}

function accountsPanel(firstRun) {
  const main = $('mail-main');
  const rows = _accounts.map(a => `
    <div class="mail-acct-row">
      <span>${esc(a.name || a.email)} <em style="color:var(--muted)">${esc(a.email)}</em></span>
      <span><button class="btn mail-acct-edit" data-id="${a.id}" style="font-size:0.68rem">edit</button>
      <button class="btn mail-acct-del" data-id="${a.id}" style="font-size:0.68rem">remove</button></span>
    </div>`).join('');
  main.innerHTML = `<div class="mail-accounts">
    <div class="mail-compose-head">mail accounts</div>
    ${firstRun ? '<div class="mail-empty" style="padding:0.3rem 0">connect a mailbox to get started. you enter your own credentials — they stay on this machine.</div>' : ''}
    ${rows}
    <button class="btn" id="mail-add-acct" style="margin-top:0.5rem">+ add account</button>
  </div>`;
  main.querySelectorAll('.mail-acct-edit').forEach(b => b.addEventListener('click', () => acctForm(_accounts.find(a => a.id === b.dataset.id))));
  main.querySelectorAll('.mail-acct-del').forEach(b => b.addEventListener('click', async () => {
    if (!await dlgConfirm('remove this account?')) return;
    await fetch(`/api/mail/accounts/${b.dataset.id}`, { method: 'DELETE' });
    if (_active === b.dataset.id) _active = null;
    await loadMail();
  }));
  $('mail-add-acct').addEventListener('click', () => acctForm(null));
}

function acctForm(acct) {
  const main = $('mail-main');
  const a = acct || {};
  main.innerHTML = `<div class="mail-accounts">
    <div class="mail-compose-head">${acct ? 'edit' : 'add'} account</div>
    <input class="settings-input" id="ma-email" placeholder="email address" value="${esc(a.email || '')}">
    <input class="settings-input" id="ma-name" placeholder="label (optional)" value="${esc(a.name || '')}">
    <div class="mail-form-grid">
      <input class="settings-input" id="ma-imaph" placeholder="imap host" value="${esc(a.imap_host || '')}">
      <input class="settings-input" id="ma-imapp" placeholder="imap port" value="${esc(a.imap_port || 993)}">
      <input class="settings-input" id="ma-smtph" placeholder="smtp host" value="${esc(a.smtp_host || '')}">
      <input class="settings-input" id="ma-smtpp" placeholder="smtp port" value="${esc(a.smtp_port || 587)}">
    </div>
    <input class="settings-input" id="ma-user" placeholder="username (usually your email)" value="${esc(a.username || a.email || '')}">
    <input class="settings-input" type="password" id="ma-pass" placeholder="${acct ? 'password (leave blank to keep)' : 'app-specific password'}">
    <div style="display:flex;gap:0.4rem;justify-content:flex-end;margin-top:0.4rem">
      <button class="btn" id="ma-cancel">cancel</button>
      <button class="btn" id="ma-test">save & test</button>
      <button class="btn primary" id="ma-save">save</button>
    </div>
    <div id="ma-status" style="font-size:0.72rem;color:var(--muted);text-align:right"></div>
  </div>`;
  // autofill hosts from the email's provider
  $('ma-email').addEventListener('blur', () => {
    const em = $('ma-email').value.trim();
    const p = PRESETS.find(x => x.re.test(em));
    if (p) {
      if (!$('ma-imaph').value) $('ma-imaph').value = p.imap;
      if (!$('ma-smtph').value) $('ma-smtph').value = p.smtp;
      if (!$('ma-user').value) $('ma-user').value = em;
    }
  });
  $('ma-cancel').addEventListener('click', () => accountsPanel());
  const collect = () => ({
    email: $('ma-email').value.trim(), name: $('ma-name').value.trim(),
    imap_host: $('ma-imaph').value.trim(), imap_port: +$('ma-imapp').value || 993,
    smtp_host: $('ma-smtph').value.trim(), smtp_port: +$('ma-smtpp').value || 587,
    username: $('ma-user').value.trim() || $('ma-email').value.trim(),
    password: $('ma-pass').value, use_ssl: true,
  });
  const save = async () => {
    const body = collect();
    let res;
    if (acct) res = await fetch(`/api/mail/accounts/${acct.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
    else res = await fetch('/api/mail/accounts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
    _accounts = await fetch('/api/mail/accounts').then(r => r.json());
    return res;
  };
  $('ma-save').addEventListener('click', async () => { await save(); toast('saved', 'success'); accountsPanel(); loadMail(); });
  $('ma-test').addEventListener('click', async () => {
    $('ma-status').textContent = 'saving + testing…';
    const res = await save();
    const id = acct ? acct.id : res.id;
    const t = await fetch(`/api/mail/test/${id}`).then(r => r.json()).catch(() => ({ ok: false, error: 'network' }));
    $('ma-status').textContent = t.ok ? '✓ connected' : '✗ ' + (t.error || 'failed');
    if (t.ok) { _active = id; }
  });
}
