import { toast } from './util.js';
import { confirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _unlocked = false;
let _token = null;     // the unlock token; sent back on every vault request
let _entries = [];     // last loaded list, so a row click can open the editor
let _modalEl = null;   // the open add/edit overlay, if any

const $ = id => document.getElementById(id);

// each field's label + how it renders. kinds:
//   text     plain input
//   textarea multi-line
//   password masked + generate + strength + show/copy   (only the login password)
//   secret   masked + show/copy (no generator)          (tokens, card #, cvv-ish secrets)
const FIELD_DEFS = {
  username:       { label: 'username',          kind: 'text' },
  password:       { label: 'password',          kind: 'password' },
  url:            { label: 'website',           kind: 'text', placeholder: 'https://…' },
  notes:          { label: 'notes',             kind: 'textarea' },
  cardholder:     { label: 'cardholder name',   kind: 'text' },
  number:         { label: 'card number',       kind: 'secret', placeholder: '4242 4242 4242 4242' },
  expiry:         { label: 'expiry',            kind: 'text', placeholder: 'MM/YY', half: true },
  cvv:            { label: 'cvv',               kind: 'text', placeholder: '123', half: true },
  address:        { label: 'billing address',   kind: 'textarea' },
  apikey:         { label: 'API key / token',   kind: 'secret', placeholder: 'sk-…' },
  endpoint:       { label: 'endpoint',          kind: 'text', placeholder: 'https://api.…' },
  fullname:       { label: 'full name',         kind: 'text' },
  email:          { label: 'email',             kind: 'text' },
  phone:          { label: 'phone',             kind: 'text' },
  home_address:   { label: 'address',           kind: 'textarea' },
  account_holder: { label: 'account holder',    kind: 'text' },
  bank_name:      { label: 'bank',              kind: 'text' },
  account_number: { label: 'account number',    kind: 'secret' },
  routing:        { label: 'routing / sort code', kind: 'text' },
  private_key:    { label: 'private key',       kind: 'textarea' },
  public_key:     { label: 'public key',        kind: 'textarea' },
  passphrase:     { label: 'passphrase',        kind: 'secret' },
  license_key:    { label: 'license key',       kind: 'text' },
  registered_to:  { label: 'registered to',     kind: 'text' },
};

// the item types. selecting one decides which fields the form shows.
const TYPES = [
  { key: 'login',    label: 'Login',            fields: ['username', 'password', 'url', 'notes'] },
  { key: 'apikey',   label: 'API key',          fields: ['apikey', 'endpoint', 'notes'] },
  { key: 'card',     label: 'Credit card',      fields: ['cardholder', 'number', 'expiry', 'cvv', 'address', 'notes'] },
  { key: 'note',     label: 'Secure note',      fields: ['notes'] },
  { key: 'identity', label: 'Identity',         fields: ['fullname', 'email', 'phone', 'home_address', 'notes'] },
  { key: 'bank',     label: 'Bank account',     fields: ['account_holder', 'bank_name', 'account_number', 'routing', 'notes'] },
  { key: 'ssh',      label: 'SSH key',          fields: ['private_key', 'public_key', 'passphrase', 'notes'] },
  { key: 'license',  label: 'Software license', fields: ['license_key', 'registered_to', 'notes'] },
];
const TYPE_BY_KEY = Object.fromEntries(TYPES.map(t => [t.key, t]));
const PRIMARY = {
  login: 'password', apikey: 'apikey', card: 'number', note: 'notes',
  identity: 'email', bank: 'account_number', ssh: 'private_key', license: 'license_key',
};

// map a stored entry's type → one of our form types. handles legacy values
// (password/card/note from before typed items) and falls back to a field guess.
function _typeForEntry(entry) {
  const t = entry.type;
  if (TYPE_BY_KEY[t]) return t;
  if (t === 'password') return 'login';
  if (t === 'card') return 'card';
  if (t === 'note') return 'note';
  const f = Object.keys(entry.fields || {});
  if (f.includes('number') || f.includes('cardholder')) return 'card';
  if (f.includes('apikey')) return 'apikey';
  if (f.includes('private_key')) return 'ssh';
  if (f.length === 1 && f[0] === 'notes') return 'note';
  return 'login';
}
function _typeLabel(entry) { return TYPE_BY_KEY[_typeForEntry(entry)]?.label || 'item'; }

// fetch wrapper that attaches this session's unlock token so the server can
// bind the request to our unlock (not just "someone unlocked recently")
function _vfetch(url, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (_token) headers['X-Vault-Token'] = _token;
  return fetch(url, { ...opts, headers });
}

export async function loadVaultView() {
  const locked   = $('vault-locked');
  const unlocked = $('vault-unlocked');
  const newBtn   = $('vault-new-btn');
  const lockBtn  = $('vault-lock-btn');
  if (!locked || !unlocked) return;
  locked.style.display   = _unlocked ? 'none' : 'flex';
  unlocked.style.display = _unlocked ? 'flex' : 'none';
  if (newBtn)  newBtn.style.display  = _unlocked ? '' : 'none';
  if (lockBtn) lockBtn.style.display = _unlocked ? '' : 'none';
  if (_unlocked) await _loadEntries();
}

export function initVault() {
  $('vault-unlock-btn')?.addEventListener('click', _doUnlock);
  $('vault-lock-btn')?.addEventListener('click', _doLock);
  $('vault-new-btn')?.addEventListener('click', () => openVaultForm());
  $('vault-pw-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') _doUnlock(); });
}

// ── add / edit modal ───────────────────────────────────────────────────────

function openVaultForm(entry = null) {
  _closeModal();
  const editing = !!entry;
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <span class="modal-title">${editing ? 'edit secret' : 'new secret'}</span>
        <button class="modal-close" id="vf-x" aria-label="close">✕</button>
      </div>
      <div class="vault-form">
        <div class="vform-field"><label>name</label>
          <input id="vf-name" class="settings-input vform-input" placeholder="e.g. Chase Visa"></div>
        <div class="vform-field"><label>type</label>
          <div class="custom-select" id="vf-type" style="width:100%"></div></div>
        <div class="vform-divider"></div>
        <div id="vf-fields"></div>
      </div>
      <div class="vault-form-actions">
        ${editing ? '<button class="btn danger" id="vf-del" style="margin-right:auto">delete</button>' : ''}
        <button class="btn" id="vf-cancel">cancel</button>
        <button class="btn primary" id="vf-save">${editing ? 'save' : 'add'}</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  _modalEl = ov;
  ov._entry = entry;

  const typeSel = ov.querySelector('#vf-type');
  const initial = editing ? _typeForEntry(entry) : 'login';
  populateDropdown(typeSel, TYPES.map(t => ({ value: t.key, label: t.label })), initial);
  typeSel.addEventListener('change', () => _renderFields(_currentFields(), _editVals()));

  ov.querySelector('#vf-name').value = editing ? (entry.name || '') : '';
  _renderFields(_currentFields(), _editVals());

  ov.querySelector('#vf-x').onclick = _closeModal;
  ov.querySelector('#vf-cancel').onclick = _closeModal;
  ov.querySelector('#vf-save').onclick = () => _saveForm(editing);
  ov.querySelector('#vf-del')?.addEventListener('click', () => _delFromForm(entry.id));
  ov.addEventListener('mousedown', e => { if (e.target === ov) _closeModal(); });
  document.addEventListener('keydown', _escClose);
  ov.querySelector('#vf-name').focus();
}

function _escClose(e) { if (e.key === 'Escape') _closeModal(); }

function _closeModal() {
  if (_modalEl) { _modalEl.remove(); _modalEl = null; }
  document.removeEventListener('keydown', _escClose);
}

function _editVals() {
  const e = _modalEl?._entry;
  if (!e) return {};
  return { ...(e.fields || {}), username: e.username || '' };
}

// fields for the currently-selected type, plus any extra keys an edited entry
// already carries (so nothing it stored gets hidden)
function _currentFields() {
  const tk = _modalEl.querySelector('#vf-type').value;
  const schema = (TYPE_BY_KEY[tk]?.fields || ['notes']).slice();
  const e = _modalEl._entry;
  if (e?.fields) for (const k of Object.keys(e.fields)) if (FIELD_DEFS[k] && !schema.includes(k)) schema.push(k);
  return schema;
}

function _fieldHtml(key) {
  const def = FIELD_DEFS[key];
  const id = 'vf-f-' + key;
  const ph = def.placeholder || '';
  if (def.kind === 'textarea')
    return `<div class="vform-field"><label>${def.label}</label>
      <textarea id="${id}" class="settings-input vform-input" rows="2" placeholder="${ph}"></textarea></div>`;
  if (def.kind === 'password' || def.kind === 'secret') {
    const gen = def.kind === 'password' ? '<button type="button" class="btn" id="vf-gen">⚙ gen</button>' : '';
    const strength = def.kind === 'password'
      ? `<div class="vault-strength" id="vf-strength" style="display:none">
          <span class="vault-strength-bar"><span class="vault-strength-fill"></span></span>
          <span class="vault-strength-label"></span></div>` : '';
    return `<div class="vform-field"><label>${def.label}</label>
      <div class="vform-pw">
        <input id="${id}" type="password" class="settings-input vform-input" placeholder="${ph}">
        <button type="button" class="act-btn" data-reveal="${id}">show</button>
        <button type="button" class="act-btn" data-copy="${id}">copy</button>
        ${gen}
      </div>${strength}</div>`;
  }
  return `<div class="vform-field${def.half ? ' half' : ''}"><label>${def.label}</label>
    <input id="${id}" type="text" class="settings-input vform-input" placeholder="${ph}"></div>`;
}

function _renderFields(schema, values = {}) {
  const box = _modalEl.querySelector('#vf-fields');
  let html = '', i = 0;
  while (i < schema.length) {
    const k = schema[i], def = FIELD_DEFS[k];
    if (!def) { i++; continue; }
    const k2 = schema[i + 1];
    if (def.half && k2 && FIELD_DEFS[k2]?.half) {   // expiry + cvv share a row
      html += `<div class="vform-row">${_fieldHtml(k)}${_fieldHtml(k2)}</div>`;
      i += 2;
    } else { html += _fieldHtml(k); i++; }
  }
  box.innerHTML = html || '<div class="vform-empty">nothing to fill in</div>';

  for (const k of schema) {
    const el = box.querySelector('#vf-f-' + k);
    if (el && values[k] != null) el.value = values[k];
  }
  box.querySelector('#vf-gen')?.addEventListener('click', _genFormPw);
  box.querySelectorAll('[data-reveal]').forEach(b => b.onclick = () => {
    const inp = box.querySelector('#' + b.dataset.reveal);
    const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    b.textContent = show ? 'hide' : 'show';
  });
  box.querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => {
    await navigator.clipboard.writeText(box.querySelector('#' + b.dataset.copy).value);
    toast('copied', 'success');
  });
  box.querySelector('#vf-f-password')?.addEventListener('input', _checkStrength);
}

async function _genFormPw() {
  try {
    const d = await fetch('/api/vault/generate?length=20').then(r => r.json());
    const inp = _modalEl.querySelector('#vf-f-password');
    if (inp) { inp.value = d.password; inp.type = 'text'; }
    const showBtn = _modalEl.querySelector('[data-reveal="vf-f-password"]');
    if (showBtn) showBtn.textContent = 'hide';
    _showStrength(d.strength);
  } catch { toast("couldn't generate a password — try again", 'error'); }
}

let _stTimer;
function _checkStrength() {
  clearTimeout(_stTimer);
  const inp = _modalEl?.querySelector('#vf-f-password');
  const box = _modalEl?.querySelector('#vf-strength');
  if (!inp || !box) return;
  if (!inp.value) { box.style.display = 'none'; return; }
  _stTimer = setTimeout(async () => {
    try {
      const s = await fetch('/api/vault/strength', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ password: inp.value }),
      }).then(r => r.json());
      _showStrength(s);
    } catch {}
  }, 200);
}

function _showStrength(s) {
  const box = _modalEl?.querySelector('#vf-strength');
  if (!box) return;
  box.style.display = 'flex';
  const colors = ['var(--error)', 'var(--error)', '#d8a24a', 'var(--green)', 'var(--green)'];
  box.querySelector('.vault-strength-fill').style.width = ((s.score + 1) * 20) + '%';
  box.querySelector('.vault-strength-fill').style.background = colors[s.score] || 'var(--muted)';
  box.querySelector('.vault-strength-label').textContent = s.label + (s.warning ? ' — ' + s.warning : '');
}

async function _saveForm(editing) {
  const ov = _modalEl;
  const name = ov.querySelector('#vf-name').value.trim();
  const typeKey = ov.querySelector('#vf-type').value;
  const schema = _currentFields();
  const fields = {};
  let username = '';
  for (const key of schema) {
    const el = ov.querySelector('#vf-f-' + key);
    const val = el ? el.value.trim() : '';
    if (key === 'username') { username = val; continue; }
    if (val) fields[key] = val;
  }
  if (!name) { toast('name required', 'error'); return; }
  if (!username && !Object.keys(fields).length) { toast('fill in at least one field', 'error'); return; }
  const body = JSON.stringify({
    name, type: typeKey, fields, username,
    category: TYPE_BY_KEY[typeKey]?.label || typeKey,
  });
  const id = editing ? ov._entry.id : null;
  const r = await _vfetch(editing ? `/api/vault/${id}` : '/api/vault', {
    method: editing ? 'PATCH' : 'POST',
    headers: { 'content-type': 'application/json' }, body,
  });
  if (!r.ok) { toast('save failed — is the vault still unlocked?', 'error'); return; }
  toast(editing ? 'saved' : 'entry added', 'success');
  _closeModal();
  await _loadEntries();
}

async function _delFromForm(id) {
  if (!await confirm('delete this entry?')) return;
  await _vfetch(`/api/vault/${id}`, { method: 'DELETE' });
  _closeModal();
  await _loadEntries();
}

// ── unlock / lock ────────────────────────────────────────────────────────────

async function _doUnlock() {
  const pw = $('vault-pw-input')?.value;
  if (!pw) { toast('enter master password', 'error'); return; }
  try {
    const r = await fetch('/api/vault/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (!r.ok) { toast('wrong password', 'error'); return; }
    _token = (await r.json()).token;
    _unlocked = true;
    $('vault-pw-input').value = '';
    await loadVaultView();
  } catch {
    toast('unlock failed', 'error');
  }
}

async function _doLock() {
  await fetch('/api/vault/lock', { method: 'POST' }).catch(() => {});
  _token = null;
  _unlocked = false;
  _closeModal();
  loadVaultView();
}

// ── list ──────────────────────────────────────────────────────────────────────

async function _loadEntries() {
  const list = $('vault-entry-list');
  if (!list) return;
  try {
    _entries = await _vfetch('/api/vault').then(r => r.json());
    if (!_entries.length) { list.innerHTML = '<div class="page-empty">no entries — hit “+ new”</div>'; return; }
    list.innerHTML = _entries.map(e => `
      <div class="vault-entry" data-id="${e.id}" onclick="window._vaultOpen('${e.id}')" title="open">
        <span class="vault-entry-name">${_esc(e.name)}${e.username ? ` <span class="vault-entry-user">${_esc(e.username)}</span>` : ''}</span>
        <span class="vault-entry-cat">${_esc(_typeLabel(e))}</span>
        <span class="vault-entry-grow"></span>
        <button class="act-btn" onclick="event.stopPropagation();window._vaultCopy('${e.id}')">copy</button>
        <button class="act-btn danger" onclick="event.stopPropagation();window._vaultDel('${e.id}')">del</button>
      </div>`).join('');
  } catch {
    toast('load failed — vault may be locked', 'error');
    _unlocked = false;
    loadVaultView();
  }
}

// which field to copy when you hit "copy" on a row
function _primarySecret(d) {
  const f = d.fields || {};
  let tk = TYPE_BY_KEY[d.type] ? d.type
    : d.type === 'password' ? 'login'
    : d.type === 'card' ? 'card'
    : d.type === 'note' ? 'note'
    : f.number ? 'card' : f.apikey ? 'apikey' : 'login';
  const k = PRIMARY[tk];
  return (k && f[k]) || f.password || d.value || Object.values(f).find(Boolean) || '';
}

window._vaultOpen = async id => {
  const row = _entries.find(e => e.id === id);
  if (!row) return;
  try {
    const d = await _vfetch(`/api/vault/${id}/reveal`).then(r => r.json());
    openVaultForm({ id, name: row.name, category: row.category, username: row.username, type: row.type, fields: d.fields || {} });
  } catch { toast('reveal failed — vault may be locked', 'error'); }
};

window._vaultCopy = async id => {
  try {
    const d = await _vfetch(`/api/vault/${id}/reveal`).then(r => r.json());
    await navigator.clipboard.writeText(_primarySecret(d));
    toast('copied', 'success');
  } catch { toast('copy failed', 'error'); }
};

window._vaultDel = async id => {
  if (!await confirm('delete this entry?')) return;
  await _vfetch(`/api/vault/${id}`, { method: 'DELETE' });
  await _loadEntries();
};

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
