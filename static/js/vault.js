import { toast } from './util.js';
import { confirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

let _unlocked = false;
let _token = null;     // the unlock token; sent back on every vault request
let _entries = [];     // last loaded list, so a row click can open the editor
let _modalEl = null;   // the open add/edit overlay, if any
let _totpTimer = null;  // live TOTP countdown interval
let _vaultId = 'default';  // 9c — which vault is currently unlocked
let _vaults = [];          // 9c — known vaults for the switcher
let _travel = false;       // 9c — travel mode on?
let _wtOpen = false;       // 8d — is the watchtower panel showing? (the button is a real toggle)
let _customTypes = {};     // 8e — user-defined entry types {key: {label, fields:[{key,label,kind,width,placeholder}]}}

const $ = id => document.getElementById(id);

// 9c — ArrayBuffer <-> base64 for WebAuthn blobs
function _b64(buf) {
  const b = new Uint8Array(buf); let s = '';
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s);
}
function _b64ToBuf(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  s += '='.repeat((4 - s.length % 4) % 4);
  const bin = atob(s), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}

// each field's label + how it renders. kinds:
//   text     plain input
//   textarea multi-line
//   password masked + generate + strength + show/copy   (only the login password)
//   secret   masked + show/copy (no generator)          (tokens, card #, cvv-ish secrets)
const FIELD_DEFS = {
  username:       { label: 'username',          kind: 'text' },
  password:       { label: 'password',          kind: 'password' },
  totp:           { label: 'TOTP secret (2FA)', kind: 'secret', placeholder: 'base32 secret' },
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
  rp_id:          { label: 'site (rp id)',       kind: 'text', placeholder: 'github.com' },
};

// the item types. selecting one decides which fields the form shows.
const TYPES = [
  { key: 'login',    label: 'Login',            fields: ['username', 'password', 'totp', 'url', 'notes'] },
  { key: 'apikey',   label: 'API key',          fields: ['apikey', 'endpoint', 'totp', 'notes'] },
  { key: 'card',     label: 'Credit card',      fields: ['cardholder', 'number', 'expiry', 'cvv', 'address', 'notes'] },
  { key: 'note',     label: 'Secure note',      fields: ['notes'] },
  { key: 'identity', label: 'Identity',         fields: ['fullname', 'email', 'phone', 'home_address', 'notes'] },
  { key: 'bank',     label: 'Bank account',     fields: ['account_holder', 'bank_name', 'account_number', 'routing', 'notes'] },
  { key: 'ssh',      label: 'SSH key',          fields: ['private_key', 'public_key', 'passphrase', 'notes'] },
  { key: 'license',  label: 'Software license', fields: ['license_key', 'registered_to', 'notes'] },
  { key: 'passkey',  label: 'Passkey',          fields: ['rp_id', 'username', 'notes'] },
];
const TYPE_BY_KEY = Object.fromEntries(TYPES.map(t => [t.key, t]));
const PRIMARY = {
  login: 'password', apikey: 'apikey', card: 'number', note: 'notes',
  identity: 'email', bank: 'account_number', ssh: 'private_key', license: 'license_key',
  passkey: 'username',
};

// map a stored entry's type → one of our form types. handles legacy values
// (password/card/note from before typed items) and falls back to a field guess.
function _typeForEntry(entry) {
  const t = entry.type;
  if (TYPE_BY_KEY[t]) return t;
  if (_customTypes[t]) return t;   // 8e — a user-defined type
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
function _typeLabel(entry) { return _typeDef(_typeForEntry(entry))?.label || 'item'; }

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
  if (!locked || !unlocked) return;
  locked.style.display   = _unlocked ? 'none' : 'flex';
  unlocked.style.display = _unlocked ? 'flex' : 'none';
  // controls that only make sense once unlocked
  for (const id of ['vault-new-btn', 'vault-lock-btn', 'vault-watchtower-btn',
                    'vault-switcher', 'vault-add-btn', 'vault-travel-btn',
                    'vault-manage-btn', 'vault-bio-add-btn']) {
    const el = $(id); if (el) el.style.display = _unlocked ? '' : 'none';
  }
  if ($('vault-bio-add-btn')) $('vault-bio-add-btn').style.display =
    (_unlocked && window.PublicKeyCredential) ? '' : 'none';
  if (_unlocked) { await _loadCustomTypes(); await _loadEntries(); await _loadVaults(); }
  else _refreshBioUnlock();
}

async function _loadCustomTypes() {
  try { _customTypes = (await _vfetch('/api/vault/custom-types').then(r => r.json())).types || {}; }
  catch { _customTypes = {}; }
}

// built-in + custom types, as {key, label, fields:[defObj]}
function _allTypes() {
  const custom = Object.entries(_customTypes).map(([key, t]) => ({ key, label: t.label, custom: true, fields: t.fields || [] }));
  return [...TYPES, ...custom];
}
function _typeDef(key) {
  if (TYPE_BY_KEY[key]) return TYPE_BY_KEY[key];
  if (_customTypes[key]) return { key, label: _customTypes[key].label, custom: true, fields: _customTypes[key].fields || [] };
  return null;
}
// resolve a field key (within a type) → a render def {key,label,kind,placeholder,half}
function _defOf(key, typeKey) {
  const t = _typeDef(typeKey);
  if (t?.custom) {
    const f = (t.fields || []).find(x => x.key === key);
    if (f) return { key, label: f.label, kind: f.kind || 'text', placeholder: f.placeholder || '', half: f.width === 'half' };
  }
  const d = FIELD_DEFS[key];
  return d ? { key, ...d } : { key, label: key, kind: 'text', placeholder: '' };
}

export function initVault() {
  $('vault-unlock-btn')?.addEventListener('click', _doUnlock);
  $('vault-lock-btn')?.addEventListener('click', _doLock);
  $('vault-new-btn')?.addEventListener('click', () => openVaultForm());
  $('vault-watchtower-btn')?.addEventListener('click', showWatchtower);
  $('vault-add-btn')?.addEventListener('click', _createVaultForm);
  $('vault-travel-btn')?.addEventListener('click', _toggleTravel);
  $('vault-manage-btn')?.addEventListener('click', _manageVaults);
  $('vault-bio-add-btn')?.addEventListener('click', _enableBiometric);
  $('vault-bio-unlock-btn')?.addEventListener('click', _bioUnlock);
  $('vault-pw-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') _doUnlock(); });
  // 8a — unified icons on the toolbar (settings is now rightmost)
  const dec = (id, name, label) => { const b = $(id); if (b) b.innerHTML = `${_si(name)} ${label}`; };
  dec('vault-manage-btn', 'gear', 'settings');
  dec('vault-bio-add-btn', 'fingerprint', 'biometric');
  dec('vault-watchtower-btn', 'shield', 'watchtower');
  dec('vault-bio-unlock-btn', 'fingerprint', 'unlock with biometric');
}

// 9c — multiple vaults, Travel Mode, biometric ──────────────────────────────
async function _loadVaults() {
  try {
    _vaults = await _vfetch('/api/vault/vaults').then(r => r.json());
    const tm = await fetch('/api/vault/travel-mode').then(r => r.json()).catch(() => ({}));
    _travel = !!tm.on;
  } catch { _vaults = []; }
  _renderSwitcher();
  const tb = $('vault-travel-btn');
  if (tb) { tb.classList.toggle('active', _travel); tb.innerHTML = _travel ? `${_si('plane')} travel on` : `${_si('plane')} travel`; }
}

function _renderSwitcher() {
  const sel = $('vault-switcher');
  if (!sel) return;
  const opts = _vaults.map(v => ({ value: v.id, label: v.name }));
  // travel-safe vaults get a plane icon via the dropdown's per-option icon map (was a plane text suffix)
  sel._iconHtml = Object.fromEntries(_vaults.filter(v => v.travel_safe).map(v => [v.id, _si('plane')]));
  populateDropdown(sel, opts, _vaultId);
  sel.onchange = () => { const id = sel.value; if (id && id !== _vaultId) _switchVault(id); };
}

async function _switchVault(id) {
  const v = _vaults.find(x => x.id === id);
  const pw = await _promptPw(`unlock “${v?.name || 'vault'}”`);
  if (pw == null) { _renderSwitcher(); return; }  // cancelled → restore selection
  try {
    const r = await fetch('/api/vault/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw, vault_id: id }),
    });
    if (!r.ok) { toast('wrong password for that vault', 'error'); _renderSwitcher(); return; }
    const j = await r.json();
    _token = j.token; _vaultId = j.vault_id;
    await _loadEntries(); await _loadVaults();
    toast('switched vault', 'success');
  } catch { toast('switch failed', 'error'); _renderSwitcher(); }
}

function _createVaultForm() {
  _closeModal();
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true">
      <div class="modal-head"><span class="modal-title">new vault</span>
        <button class="modal-close" id="nv-x" aria-label="close">✕</button></div>
      <div class="vault-form">
        <div class="vform-field"><label>name</label>
          <input id="nv-name" class="settings-input vform-input" placeholder="e.g. Work"></div>
        <div class="vform-field"><label>master password</label>
          <input id="nv-pw" type="password" class="settings-input vform-input" placeholder="a password for this vault"></div>
      </div>
      <div class="vault-form-actions">
        <button class="btn" id="nv-cancel">cancel</button>
        <button class="btn primary" id="nv-create">create</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  _modalEl = ov;
  ov.querySelector('#nv-x').onclick = _closeModal;
  ov.querySelector('#nv-cancel').onclick = _closeModal;
  ov.addEventListener('mousedown', e => { if (e.target === ov) _closeModal(); });
  ov.querySelector('#nv-create').onclick = async () => {
    const name = ov.querySelector('#nv-name').value.trim();
    const pw = ov.querySelector('#nv-pw').value;
    if (!name || !pw) { toast('name + password required', 'error'); return; }
    const r = await _vfetch('/api/vault/vaults', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, password: pw }),
    });
    if (!r.ok) { toast('create failed', 'error'); return; }
    const j = await r.json();
    _closeModal();
    // unlock straight into the new vault
    const u = await fetch('/api/vault/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw, vault_id: j.id }),
    }).then(x => x.json());
    _token = u.token; _vaultId = u.vault_id;
    await _loadEntries(); await _loadVaults();
    toast('vault created', 'success');
  };
  ov.querySelector('#nv-name').focus();
}

async function _toggleTravel() {
  try {
    const r = await _vfetch('/api/vault/travel-mode', {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ on: !_travel }),
    }).then(x => x.json());
    _travel = !!r.on;
    await _loadVaults();
    toast(_travel ? 'travel mode on — only travel-safe vaults shown' : 'travel mode off', 'success');
  } catch { toast('could not toggle travel mode', 'error'); }
}

async function _manageVaults() {
  _closeModal();
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true">
      <div class="modal-head"><span class="modal-title">vaults</span>
        <button class="modal-close" id="mv-x" aria-label="close">✕</button></div>
      <div class="mv-scroll">
        <div class="vault-form" id="mv-list"></div>
        <div class="vform-divider"></div>
        <div class="vault-form" id="mv-extra"></div>
        <div class="vform-divider"></div>
        <div class="vault-form" id="mv-types"></div>
      </div>
      <div class="vault-form-actions"><button class="btn" id="mv-close">done</button></div>
    </div>`;
  document.body.appendChild(ov);
  _modalEl = ov;
  ov.querySelector('#mv-x').onclick = _closeModal;
  ov.querySelector('#mv-close').onclick = _closeModal;
  ov.addEventListener('mousedown', e => { if (e.target === ov) _closeModal(); });
  _renderManage();
  await _renderManageExtra();
  await _loadCustomTypes();
  _renderTypeEditor();
}

// 8e — visual editor for user-defined entry types
let _vtDraft = null;   // { key, label, fields:[{key,label,width,kind,placeholder}] } while editing

function _renderTypeEditor() {
  const box = _modalEl?.querySelector('#mv-types');
  if (!box) return;
  const types = Object.entries(_customTypes);
  box.innerHTML = `
    <div class="mv-2fa-head">custom entry types</div>
    <p class="mv-2fa-explain">define your own item types — name them, add fields, and set each field's width. they appear in the type picker when you add a secret.</p>
    <div class="vt-list">
      ${types.length ? types.map(([k, t]) => `
        <div class="vt-row" data-k="${k}">
          <span class="vt-name">${_esc(t.label)}</span>
          <span class="vt-meta">${t.fields.length} field${t.fields.length === 1 ? '' : 's'}</span>
          <span class="vault-entry-grow"></span>
          <button class="act-btn" data-edit="${k}">edit</button>
          <button class="act-btn danger" data-del="${k}">delete</button>
        </div>`).join('') : '<div class="vform-empty">no custom types yet</div>'}
    </div>
    <button class="act-btn" id="vt-new">+ new type</button>
    <div id="vt-edit"></div>`;
  box.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => _editType(b.dataset.edit));
  box.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!await confirm('delete this custom type?')) return;
    await _vfetch(`/api/vault/custom-types/${b.dataset.del}`, { method: 'DELETE' });
    await _loadCustomTypes(); _renderTypeEditor();
  });
  box.querySelector('#vt-new').onclick = () => _editType(null);
}

function _editType(key) {
  const t = key ? _customTypes[key] : { label: '', fields: [{ key: '', label: '', width: 'full', kind: 'text' }] };
  _vtDraft = { key, label: t.label, fields: (t.fields || []).map(f => ({ ...f })) };
  _renderTypeForm();
}

const _WIDTHS = ['full', 'half', 'third'];
const _KINDS = ['text', 'secret', 'password', 'textarea'];

function _renderTypeForm() {
  const box = _modalEl?.querySelector('#vt-edit');
  if (!box || !_vtDraft) return;
  box.innerHTML = `
    <div class="vt-form">
      <div class="vform-field"><label>type name</label>
        <input id="vt-label" class="settings-input vform-input" placeholder="e.g. Wi-Fi" value="${_esc(_vtDraft.label)}"></div>
      <div class="vt-fields">
        ${_vtDraft.fields.map((f, i) => `
          <div class="vt-field" data-i="${i}">
            <input class="settings-input vt-flabel" data-i="${i}" placeholder="field name" value="${_esc(f.label)}">
            <div class="seg seg-sm vt-width" data-i="${i}">${_WIDTHS.map(w => `<button type="button" class="seg-opt${f.width === w ? ' active' : ''}" data-w="${w}">${w}</button>`).join('')}</div>
            <div class="seg seg-sm vt-kind" data-i="${i}">${_KINDS.map(k => `<button type="button" class="seg-opt${(f.kind || 'text') === k ? ' active' : ''}" data-kd="${k}">${k}</button>`).join('')}</div>
            <button type="button" class="act-btn danger vt-rmf" data-i="${i}" title="remove field">${_si('close')}</button>
          </div>`).join('')}
      </div>
      <div class="vt-form-actions">
        <button type="button" class="act-btn" id="vt-addf">+ field</button>
        <span class="vault-entry-grow"></span>
        <button type="button" class="btn" id="vt-cancel">cancel</button>
        <button type="button" class="btn primary" id="vt-save">save type</button>
      </div>
      <div class="np-err" id="vt-err"></div>
    </div>`;
  box.querySelector('#vt-addf').onclick = () => { _vtSync(); _vtDraft.fields.push({ key: '', label: '', width: 'full', kind: 'text' }); _renderTypeForm(); };
  box.querySelector('#vt-cancel').onclick = () => { _vtDraft = null; box.innerHTML = ''; };
  box.querySelectorAll('.vt-rmf').forEach(b => b.onclick = () => { _vtSync(); _vtDraft.fields.splice(+b.dataset.i, 1); _renderTypeForm(); });
  box.querySelectorAll('.vt-width .seg-opt').forEach(o => o.onclick = () => {
    o.closest('.vt-width').querySelectorAll('.seg-opt').forEach(x => x.classList.toggle('active', x === o));
  });
  box.querySelectorAll('.vt-kind .seg-opt').forEach(o => o.onclick = () => {
    o.closest('.vt-kind').querySelectorAll('.seg-opt').forEach(x => x.classList.toggle('active', x === o));
  });
  box.querySelector('#vt-save').onclick = _saveType;
}

// read the current DOM state back into the draft (so add/remove keeps typed values)
function _vtSync() {
  const box = _modalEl?.querySelector('#vt-edit');
  if (!box || !_vtDraft) return;
  _vtDraft.label = box.querySelector('#vt-label')?.value || '';
  box.querySelectorAll('.vt-field').forEach(row => {
    const i = +row.dataset.i;
    if (!_vtDraft.fields[i]) return;
    _vtDraft.fields[i].label = row.querySelector('.vt-flabel')?.value || '';
    _vtDraft.fields[i].width = row.querySelector('.vt-width .seg-opt.active')?.dataset.w || 'full';
    _vtDraft.fields[i].kind = row.querySelector('.vt-kind .seg-opt.active')?.dataset.kd || 'text';
  });
}

function _slug(s) { return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''); }

async function _saveType() {
  _vtSync();
  const label = _vtDraft.label.trim();
  const err = m => { const e = _modalEl?.querySelector('#vt-err'); if (e) e.textContent = m; };
  if (!label) return err('give the type a name');
  const fields = _vtDraft.fields
    .filter(f => f.label.trim())
    .map(f => ({ key: f.key || _slug(f.label), label: f.label.trim(), width: f.width, kind: f.kind }));
  if (!fields.length) return err('add at least one field');
  const key = _vtDraft.key || _slug(label);
  const r = await _vfetch(`/api/vault/custom-types/${key}`, {
    method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ label, fields }),
  });
  if (!r.ok) return err('could not save');
  _vtDraft = null;
  await _loadCustomTypes();
  _renderTypeEditor();
  toast('type saved', 'success');
}

// the "this vault" extras: hardware-key 2FA + the autofill extension pointer
async function _renderManageExtra() {
  const box = _modalEl?.querySelector('#mv-extra');
  if (!box) return;
  let st = { on: false, totp: false, credentials: [] };
  try { st = await _vfetch('/api/vault/2fa').then(r => r.json()); } catch {}
  const cur = _vaults.find(v => v.id === _vaultId);
  const keyCount = (st.credentials || []).length;
  box.innerHTML = `
    <div class="mv-2fa-head">two-factor unlock <span class="mv-cur">${_esc(cur?.name || 'this vault')}</span></div>
    <p class="mv-2fa-explain">a second factor is asked for <b>after</b> your password when unlocking. two kinds:</p>
    <div class="mv-row">
      <span class="mv-name">passkey / security key${keyCount ? ` <span class="mv-badge">${keyCount} enrolled</span>` : ''}</span>
      <span class="vault-entry-grow"></span>
      <button class="act-btn" id="mv-2fa-add" title="register a FIDO2 / YubiKey or platform passkey">+ key</button>
    </div>
    <div class="mv-row">
      <span class="mv-name">authenticator app (TOTP)${st.totp ? ' <span class="mv-badge mv-main">enrolled</span>' : ''}</span>
      <span class="vault-entry-grow"></span>
      ${st.totp
        ? '<button class="act-btn danger" id="mv-totp-del">remove</button>'
        : '<button class="act-btn" id="mv-totp-add" title="enrol Google Authenticator, Authy, 1Password, …">set up</button>'}
    </div>
    <div class="mv-row">
      <span class="mv-name">require a second factor to unlock</span>
      <span class="vault-entry-grow"></span>
      <button class="chip-toggle ${st.on ? 'on' : ''}" id="mv-2fa" role="switch" aria-checked="${st.on}">${st.on ? 'on' : 'off'}</button>
    </div>
    <p class="mv-2fa-note"><b>biometric unlock</b> (Touch ID / Windows Hello) is different: it stores your
    master password on this device so you can unlock <i>without typing it</i> — it replaces the password,
    it isn't a second factor. A <b>passkey 2FA</b> is an extra check on top of the password and may ask
    for the same device's biometrics to release the key.</p>
    <div class="mv-autofill" id="vault-autofill-info">
      <span class="mv-autofill-text">Browser autofill: load the <code>extension/</code> folder as an unpacked extension, paste an unlock token, and it fills logins from this vault on matching sites.</span>
      <a class="mv-autofill-link ic-btn-lbl" href="https://developer.chrome.com/docs/extensions/get-started" id="vault-ext-link" target="_blank" rel="noopener">how to load it ${_si('external')}</a>
    </div>`;
  box.querySelector('#mv-2fa').onclick = async () => {
    try {
      const r = await _vfetch('/api/vault/2fa', {
        method: 'PUT', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ on: !st.on }),
      }).then(x => x.json());
      await _renderManageExtra();
      toast(r.on ? 'second factor required to unlock this vault' : '2FA off', 'success');
    } catch { toast('could not change 2FA', 'error'); }
  };
  box.querySelector('#mv-2fa-add').onclick = _registerSecurityKey;
  box.querySelector('#mv-totp-add')?.addEventListener('click', _setupTotp);
  box.querySelector('#mv-totp-del')?.addEventListener('click', async () => {
    if (!await confirm('remove the authenticator-app factor for this vault?')) return;
    await _vfetch('/api/vault/2fa/totp', { method: 'DELETE' });
    await _renderManageExtra();
    toast('authenticator app removed', 'success');
  });
}

// 8c — enrol an authenticator app: fetch a secret, show it + a confirm-code box
async function _setupTotp() {
  let d;
  try { d = await _vfetch('/api/vault/2fa/totp/setup', { method: 'POST' }).then(r => r.json()); }
  catch { toast('could not start setup', 'error'); return; }
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" style="max-width:380px">
      <div class="modal-head"><span class="modal-title">add authenticator app</span></div>
      <div class="vault-form">
        <p class="mv-2fa-explain">scan this in Google Authenticator / Authy / 1Password, or type the secret manually, then enter the 6-digit code to confirm.</p>
        <div class="totp-secret" id="totp-secret">${_esc(d.secret)}</div>
        <div class="vform-field"><input id="totp-code" class="settings-input vform-input" inputmode="numeric" maxlength="6" placeholder="6-digit code"></div>
        <div class="np-err" id="totp-err"></div>
      </div>
      <div class="vault-form-actions">
        <button class="btn" id="totp-cancel">cancel</button>
        <button class="btn primary" id="totp-ok">confirm</button></div>
    </div>`;
  document.body.appendChild(ov);
  const close = () => ov.remove();
  ov.querySelector('#totp-cancel').onclick = close;
  ov.addEventListener('mousedown', e => { if (e.target === ov) close(); });
  const go = async () => {
    const code = ov.querySelector('#totp-code').value.trim();
    const r = await _vfetch('/api/vault/2fa/totp', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ secret: d.secret, code }),
    });
    if (!r.ok) { ov.querySelector('#totp-err').textContent = "code didn't match — try the current one"; return; }
    close();
    await _renderManageExtra();
    toast('authenticator app enrolled', 'success');
  };
  ov.querySelector('#totp-ok').onclick = go;
  ov.querySelector('#totp-code').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  ov.querySelector('#totp-code').focus();
}

async function _registerSecurityKey() {
  if (!window.PublicKeyCredential) { toast('security keys not supported here', 'error'); return; }
  try {
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const cred = await navigator.credentials.create({ publicKey: {
      challenge,
      rp: { name: 'alles vault' },
      user: { id: new TextEncoder().encode('2fa:' + _vaultId), name: '2fa:' + _vaultId, displayName: 'vault 2FA' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
      authenticatorSelection: { authenticatorAttachment: 'cross-platform', userVerification: 'discouraged' },
      timeout: 60000,
    }});
    const pub = cred.response.getPublicKey();
    if (!pub) { toast('unsupported security key', 'error'); return; }
    await _vfetch('/api/vault/2fa/register', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ label: 'security key', credential_id: _b64(cred.rawId), public_key: _b64(pub) }),
    });
    toast('security key registered', 'success');
    await _renderManageExtra();
  } catch { toast('security-key registration cancelled', ''); }
}

function _renderManage() {
  const box = _modalEl?.querySelector('#mv-list');
  if (!box) return;
  box.innerHTML = _vaults.map(v => `
    <div class="mv-row" data-id="${v.id}">
      <span class="mv-name" data-rename="${v.id}" title="click to rename">${_esc(v.name)}</span>
      <span class="mv-badge${v.main ? ' mv-main' : ''}" title="${v.main ? 'opens with your master password' : 'has its own password'}">${v.main ? 'main' : 'own password'}</span>
      ${v.id === _vaultId ? '<span class="mv-cur">current</span>' : ''}
      <span class="vault-entry-grow"></span>
      <span class="mv-entries">${v.entries} item${v.entries === 1 ? '' : 's'}</span>
      ${v.id === _vaultId ? `<button class="act-btn" data-chpw="${v.id}">${v.main ? 'change master password' : 'change password'}</button>` : ''}
      <button class="chip ic-btn-lbl ${v.travel_safe ? 'on' : ''}" data-travel="${v.id}" title="reachable while travelling">${_si('plane')} safe</button>
      ${v.id === 'default' ? '' : `<button class="act-btn danger" data-del="${v.id}">delete</button>`}
    </div>`).join('')
    + `<div class="mv-help">the <b>main</b> vault opens with your master password. other vaults each have their own password — change a vault's password from its row while it's unlocked.</div>`;
  box.querySelectorAll('[data-rename]').forEach(s => s.onclick = () => _inlineRename(s));
  box.querySelectorAll('[data-chpw]').forEach(b => b.onclick = () => _changeVaultPw());
  box.querySelectorAll('[data-travel]').forEach(b => b.onclick = async () => {
    const v = _vaults.find(x => x.id === b.dataset.travel);
    await _vfetch(`/api/vault/vaults/${b.dataset.travel}`, {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ travel_safe: !v.travel_safe }),
    });
    await _loadVaults(); _renderManage();
  });
  box.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!await confirm('delete this vault and all its entries?')) return;
    await _vfetch(`/api/vault/vaults/${b.dataset.del}`, { method: 'DELETE' });
    if (b.dataset.del === _vaultId) { _doLock(); return; }
    await _loadVaults(); _renderManage();
  });
}

// click a vault name → edit in place → PATCH on blur/enter (8b)
function _inlineRename(span) {
  const id = span.dataset.rename;
  const cur = _vaults.find(v => v.id === id)?.name || span.textContent;
  const inp = document.createElement('input');
  inp.className = 'settings-input mv-rename-input';
  inp.value = cur;
  span.replaceWith(inp);
  inp.focus(); inp.select();
  let done = false;
  const save = async () => {
    if (done) return; done = true;
    const name = inp.value.trim();
    if (name && name !== cur) {
      await _vfetch(`/api/vault/vaults/${id}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      await _loadVaults();
    }
    _renderManage();
  };
  inp.addEventListener('blur', save);
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') inp.blur(); if (e.key === 'Escape') { done = true; _renderManage(); } });
}

// re-key the currently-unlocked vault to a new password (8b)
async function _changeVaultPw() {
  const np = await _promptNewPw();
  if (np == null) return;
  try {
    const r = await _vfetch('/api/vault/vaults/password', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ new_password: np }),
    });
    if (!r.ok) { toast('change failed', 'error'); return; }
    _token = (await r.json()).token;   // re-bind to the new password
    toast('password changed', 'success');
  } catch { toast('change failed', 'error'); }
}

// a tiny password prompt that resolves to the entered string (or null on cancel)
function _promptPw(title) {
  return new Promise(resolve => {
    const ov = document.createElement('div');
    ov.className = 'modal-overlay vault-modal';
    ov.innerHTML = `
      <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" style="max-width:340px">
        <div class="modal-head"><span class="modal-title">${_esc(title)}</span></div>
        <div class="vault-form"><div class="vform-field">
          <input id="pp-pw" type="password" class="settings-input vform-input" placeholder="master password"></div></div>
        <div class="vault-form-actions">
          <button class="btn" id="pp-cancel">cancel</button>
          <button class="btn primary" id="pp-ok">unlock</button></div>
      </div>`;
    document.body.appendChild(ov);
    const done = val => { ov.remove(); resolve(val); };
    ov.querySelector('#pp-cancel').onclick = () => done(null);
    ov.querySelector('#pp-ok').onclick = () => done(ov.querySelector('#pp-pw').value);
    ov.querySelector('#pp-pw').addEventListener('keydown', e => { if (e.key === 'Enter') done(ov.querySelector('#pp-pw').value); });
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(null); });
    ov.querySelector('#pp-pw').focus();
  });
}

// new-password prompt with confirm (8b change-password); resolves to the password or null
function _promptNewPw() {
  return new Promise(resolve => {
    const ov = document.createElement('div');
    ov.className = 'modal-overlay vault-modal';
    ov.innerHTML = `
      <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" style="max-width:340px">
        <div class="modal-head"><span class="modal-title">change password</span></div>
        <div class="vault-form">
          <div class="vform-field"><input id="np-1" type="password" class="settings-input vform-input" placeholder="new password"></div>
          <div class="vform-field"><input id="np-2" type="password" class="settings-input vform-input" placeholder="confirm new password"></div>
          <div class="np-err" id="np-err"></div>
        </div>
        <div class="vault-form-actions">
          <button class="btn" id="np-cancel">cancel</button>
          <button class="btn primary" id="np-ok">change</button></div>
      </div>`;
    document.body.appendChild(ov);
    const done = val => { ov.remove(); resolve(val); };
    const go = () => {
      const a = ov.querySelector('#np-1').value, b = ov.querySelector('#np-2').value;
      if (a.length < 4) { ov.querySelector('#np-err').textContent = 'use at least 4 characters'; return; }
      if (a !== b) { ov.querySelector('#np-err').textContent = "passwords don't match"; return; }
      done(a);
    };
    ov.querySelector('#np-cancel').onclick = () => done(null);
    ov.querySelector('#np-ok').onclick = go;
    ov.querySelectorAll('input').forEach(i => i.addEventListener('keydown', e => { if (e.key === 'Enter') go(); }));
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(null); });
    ov.querySelector('#np-1').focus();
  });
}

async function _enableBiometric() {
  if (!window.PublicKeyCredential) { toast('biometric not supported in this browser', 'error'); return; }
  try {
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const cred = await navigator.credentials.create({ publicKey: {
      challenge,
      rp: { name: 'alles vault' },
      user: { id: new TextEncoder().encode('vault:' + _vaultId), name: 'vault:' + _vaultId, displayName: 'vault' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],  // ES256
      authenticatorSelection: { userVerification: 'preferred' },
      timeout: 60000,
    }});
    const pub = cred.response.getPublicKey();  // SPKI DER
    if (!pub) { toast('this authenticator is unsupported (no public key)', 'error'); return; }
    const r = await _vfetch('/api/vault/webauthn/register', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ label: navigator.platform || 'device',
        credential_id: _b64(cred.rawId), public_key: _b64(pub) }),
    });
    if (!r.ok) { toast('could not enable biometric', 'error'); return; }
    toast('biometric unlock enabled for this vault', 'success');
  } catch (e) { toast('biometric setup cancelled', ''); }
}

// show the lock-screen biometric button only if the default vault has a credential
async function _refreshBioUnlock() {
  const btn = $('vault-bio-unlock-btn');
  if (!btn) return;
  if (!window.PublicKeyCredential) { btn.style.display = 'none'; return; }
  try {
    const d = await fetch('/api/vault/webauthn/challenge?vault_id=default').then(r => r.json());
    btn.style.display = (d.credentials && d.credentials.length) ? '' : 'none';
  } catch { btn.style.display = 'none'; }
}

async function _bioUnlock() {
  try {
    const d = await fetch('/api/vault/webauthn/challenge?vault_id=default').then(r => r.json());
    if (!d.credentials || !d.credentials.length) { toast('no biometric set up', 'error'); return; }
    const assertion = await navigator.credentials.get({ publicKey: {
      challenge: _b64ToBuf(d.challenge),
      timeout: 60000,
      userVerification: 'preferred',
      allowCredentials: d.credentials.map(c => ({ type: 'public-key', id: _b64ToBuf(c) })),
    }});
    const r = await fetch('/api/vault/webauthn/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        vault_id: 'default',
        credential_id: _b64(assertion.rawId),
        authenticator_data: _b64(assertion.response.authenticatorData),
        client_data_json: _b64(assertion.response.clientDataJSON),
        signature: _b64(assertion.response.signature),
      }),
    });
    if (!r.ok) { toast('biometric unlock failed', 'error'); return; }
    const j = await r.json();
    _token = j.token; _vaultId = j.vault_id; _unlocked = true;
    await loadVaultView();
  } catch (e) { toast('biometric unlock cancelled', ''); }
}

// 9a — Watchtower security panel (weak / reused / breached)
function _closeWatchtower() {
  _wtOpen = false;
  $('vault-watchtower-btn')?.classList.remove('active');
  _loadEntries();
}

async function showWatchtower() {
  if (_wtOpen) { _closeWatchtower(); return; }   // 8d — real toggle: re-click hides it
  const list = $('vault-entry-list');
  if (!list) return;
  _wtOpen = true;
  $('vault-watchtower-btn')?.classList.add('active');
  list.innerHTML = '<div class="page-empty">scanning…</div>';
  let d;
  try { d = await _vfetch('/api/vault/watchtower').then(r => r.json()); }
  catch { toast('scan failed', 'error'); _closeWatchtower(); return; }
  const sec = (title, desc, rows, cls) => `
    <div class="wt-section">
      <div class="wt-head ${cls}">${title} <span class="wt-n">${rows.length}</span></div>
      <div class="wt-desc">${desc}</div>
      ${rows.length ? rows.map(x => `<div class="wt-row">${x}</div>`).join('')
        : `<div class="wt-clean">${_si('check')} all clear</div>`}
    </div>`;
  list.innerHTML = `
    <div class="vault-wt" id="vault-wt">
      <div class="wt-bar">
        <button class="btn ic-btn-lbl" id="wt-back">${_si('chevron-left')} back to vault</button>
        <span class="wt-intro">Watchtower scans your saved passwords for problems — known data-breach exposure, the same password reused across logins, and weak/short passwords.</span>
      </div>
      ${sec('breached', 'passwords found in known data breaches — change these first.', (d.breached || []).map(x => `${_esc(x.name)} <span class="wt-meta">seen ${x.count.toLocaleString()}×</span>`), 'bad')}
      ${sec('reused', 'the same password used on more than one login.', (d.reused || []).map(g => _esc(g.names.join(', '))), 'warn')}
      ${sec('weak', 'short or low-entropy passwords that are easy to guess.', (d.weak || []).map(x => _esc(x.name)), 'warn')}
    </div>`;
  $('wt-back').addEventListener('click', _closeWatchtower);
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
        ${editing ? `<div class="vform-divider"></div>
        <div class="vform-field"><label>attachments</label><div id="vf-attach"></div>
          <input type="file" id="vf-attach-input" hidden>
          <button type="button" class="btn" id="vf-attach-btn" style="font-size:0.68rem">+ attach file</button></div>` : ''}
      </div>
      <div class="vault-form-actions">
        ${editing ? '<button class="btn danger" id="vf-del" style="margin-right:auto">delete</button>' : ''}
        ${editing ? '<button class="btn" id="vf-share" title="share this item via a one-off link">🔗 share</button>' : ''}
        <button class="btn" id="vf-cancel">cancel</button>
        <button class="btn primary" id="vf-save">${editing ? 'save' : 'add'}</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  _modalEl = ov;
  ov._entry = entry;

  const typeSel = ov.querySelector('#vf-type');
  const initial = editing ? _typeForEntry(entry) : 'login';
  populateDropdown(typeSel, _allTypes().map(t => ({ value: t.key, label: t.label })), initial);
  typeSel.addEventListener('change', () => _renderFields(_currentFields(), _editVals()));

  ov.querySelector('#vf-name').value = editing ? (entry.name || '') : '';
  _renderFields(_currentFields(), _editVals());

  ov.querySelector('#vf-x').onclick = _closeModal;
  ov.querySelector('#vf-cancel').onclick = _closeModal;
  ov.querySelector('#vf-save').onclick = () => _saveForm(editing);
  ov.querySelector('#vf-del')?.addEventListener('click', () => _delFromForm(entry.id));
  if (editing) {
    _renderAttachments(entry.id);
    ov.querySelector('#vf-attach-btn')?.addEventListener('click', () => ov.querySelector('#vf-attach-input').click());
    ov.querySelector('#vf-attach-input')?.addEventListener('change', async e => {
      const f = e.target.files[0]; if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      await _vfetch(`/api/vault/${entry.id}/attachments`, { method: 'POST', body: fd });
      e.target.value = ''; _renderAttachments(entry.id);
    });
    ov.querySelector('#vf-share')?.addEventListener('click', () => _shareItem(entry.id));
  }
  ov.addEventListener('mousedown', e => { if (e.target === ov) _closeModal(); });
  document.addEventListener('keydown', _escClose);
  ov.querySelector('#vf-name').focus();
}

// 9b — encrypted attachments on an entry
async function _renderAttachments(eid) {
  const box = _modalEl?.querySelector('#vf-attach');
  if (!box) return;
  const list = await _vfetch(`/api/vault/${eid}/attachments`).then(r => r.json()).catch(() => []);
  if (!list.length) { box.innerHTML = '<div class="vf-attach-empty">none</div>'; return; }
  box.innerHTML = list.map(a => `
    <div class="vf-attach-row" data-id="${a.id}">
      <span class="vf-attach-name">📎 ${_esc(a.filename)}</span>
      <span class="vf-attach-size">${Math.max(1, Math.round(a.size / 1024))} KB</span>
      <button type="button" class="act-btn" data-dl="${a.id}" data-name="${_esc(a.filename)}">download</button>
      <button type="button" class="act-btn danger" data-rm="${a.id}">remove</button>
    </div>`).join('');
  box.querySelectorAll('[data-dl]').forEach(b => b.onclick = async () => {
    const r = await _vfetch(`/api/vault/attachments/${b.dataset.dl}`);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = b.dataset.name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  box.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => {
    await _vfetch(`/api/vault/attachments/${b.dataset.rm}`, { method: 'DELETE' });
    _renderAttachments(eid);
  });
}

async function _shareItem(eid) {
  try {
    const d = await _vfetch(`/api/vault/${eid}/share`, { method: 'POST' }).then(r => r.json());
    const url = location.origin + d.url;  // includes #key in the fragment
    try { await navigator.clipboard.writeText(url); toast('share link copied (anyone with it can read this item)', 'success'); }
    catch { toast(url, ''); }
  } catch { toast('share failed', 'error'); }
}

function _escClose(e) { if (e.key === 'Escape') _closeModal(); }

function _closeModal() {
  if (_totpTimer) { clearInterval(_totpTimer); _totpTimer = null; }
  if (_modalEl) { _modalEl.remove(); _modalEl = null; }
  document.removeEventListener('keydown', _escClose);
}

// 9a — live TOTP code + countdown for an entry that stores a totp secret
function _startTotp() {
  if (_totpTimer) { clearInterval(_totpTimer); _totpTimer = null; }
  const e = _modalEl?._entry;
  const box = _modalEl?.querySelector('#vf-fields');
  if (!e?.id || !box) return;
  const field = box.querySelector('#vf-f-totp');
  if (!field || !field.value) return;  // no secret stored → nothing to show
  const wrap = field.closest('.vform-field');
  const w = document.createElement('div');
  w.className = 'vault-totp';
  w.innerHTML = '<span class="vault-totp-code" id="vtotp-code">······</span>'
    + '<span class="vault-totp-secs" id="vtotp-secs"></span>';
  wrap.appendChild(w);
  let secs = 0;
  const code = () => document.getElementById('vtotp-code');
  const tick = async () => {
    if (secs > 0) { secs -= 1; const s = document.getElementById('vtotp-secs'); if (s) s.textContent = secs + 's'; return; }
    try {
      const d = await _vfetch(`/api/vault/${e.id}/totp`).then(r => r.json());
      if (d.code && code()) {
        code().textContent = d.code.slice(0, 3) + ' ' + d.code.slice(3);
        secs = d.seconds || 30;
        const s = document.getElementById('vtotp-secs'); if (s) s.textContent = secs + 's';
      }
    } catch { /* locked/expired — leave dots */ }
  };
  tick();
  _totpTimer = setInterval(tick, 1000);
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
  const t = _typeDef(tk);
  let keys = t?.custom ? (t.fields || []).map(f => f.key) : (t?.fields || ['notes']).slice();
  const e = _modalEl._entry;
  // keep any extra fields already stored on the entry (built-in or custom)
  if (e?.fields) for (const k of Object.keys(e.fields)) if (!keys.includes(k)) keys.push(k);
  return keys.map(k => _defOf(k, tk));
}

function _fieldHtml(def) {
  const id = 'vf-f-' + def.key;
  const ph = def.placeholder || '';
  if (def.kind === 'textarea')
    return `<div class="vform-field"><label>${_esc(def.label)}</label>
      <textarea id="${id}" class="settings-input vform-input" rows="2" placeholder="${_esc(ph)}"></textarea></div>`;
  if (def.kind === 'password' || def.kind === 'secret') {
    const gen = def.kind === 'password' ? `<button type="button" class="btn ic-btn-lbl" id="vf-gen">${_si('refresh')} gen</button>` : '';
    const strength = def.kind === 'password'
      ? `<div class="vault-strength" id="vf-strength" style="display:none">
          <span class="vault-strength-bar"><span class="vault-strength-fill"></span></span>
          <span class="vault-strength-label"></span></div>` : '';
    return `<div class="vform-field"><label>${_esc(def.label)}</label>
      <div class="vform-pw">
        <input id="${id}" type="password" class="settings-input vform-input" placeholder="${_esc(ph)}">
        <button type="button" class="act-btn" data-reveal="${id}">show</button>
        <button type="button" class="act-btn" data-copy="${id}">copy</button>
        ${gen}
      </div>${strength}</div>`;
  }
  return `<div class="vform-field${def.half ? ' half' : ''}"><label>${_esc(def.label)}</label>
    <input id="${id}" type="text" class="settings-input vform-input" placeholder="${_esc(ph)}"></div>`;
}

function _renderFields(defs, values = {}) {
  const box = _modalEl.querySelector('#vf-fields');
  let html = '', i = 0;
  while (i < defs.length) {
    const def = defs[i], next = defs[i + 1];
    if (def.half && next && next.half) {   // two half-width fields share a row
      html += `<div class="vform-row">${_fieldHtml(def)}${_fieldHtml(next)}</div>`;
      i += 2;
    } else { html += _fieldHtml(def); i++; }
  }
  box.innerHTML = html || '<div class="vform-empty">nothing to fill in</div>';

  for (const def of defs) {
    const el = box.querySelector('#vf-f-' + def.key);
    if (el && values[def.key] != null) el.value = values[def.key];
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
  _startTotp();
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

  // passkeys are minted server-side (keypair never leaves the box)
  if (typeKey === 'passkey' && !editing) {
    const rp = (ov.querySelector('#vf-f-rp_id')?.value || '').trim();
    const user = (ov.querySelector('#vf-f-username')?.value || '').trim();
    if (!rp) { toast('site (rp id) required', 'error'); return; }
    const r = await _vfetch('/api/vault/passkey/new', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ rp_id: rp, username: user }),
    });
    if (!r.ok) { toast('passkey create failed — is the vault unlocked?', 'error'); return; }
    toast('passkey created', 'success');
    _closeModal();
    await _loadEntries();
    return;
  }

  const schema = _currentFields();
  const fields = {};
  let username = '';
  for (const def of schema) {
    const key = def.key;
    const el = ov.querySelector('#vf-f-' + key);
    const val = el ? el.value.trim() : '';
    if (key === 'username') { username = val; continue; }
    if (val) fields[key] = val;
  }
  // editing a passkey: keep the credential fields the form doesn't render
  if (editing && ov._entry?.type === 'passkey') {
    for (const k of ['private_key', 'public_key', 'credential_id', 'rp_id']) {
      if (ov._entry.fields?.[k] != null && fields[k] == null) fields[k] = ov._entry.fields[k];
    }
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
    const j = await r.json();
    if (j.requires_2fa) { await _do2fa(pw, j); return; }   // 8c — second factor needed
    _token = j.token; _vaultId = j.vault_id || 'default';
    _unlocked = true;
    $('vault-pw-input').value = '';
    await loadVaultView();
  } catch {
    toast('unlock failed', 'error');
  }
}

// 8c — second-factor step after a correct password. prefers the authenticator app (TOTP);
// falls back to the passkey/security-key challenge if that's the only method enrolled.
async function _do2fa(pw, j) {
  const methods = j.methods || [];
  if (methods.includes('totp')) {
    const code = await _promptCode('enter your authenticator code');
    if (code == null) return;
    const r = await fetch('/api/vault/unlock/2fa/totp', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ vault_id: _vaultId, password: pw, code }),
    });
    if (!r.ok) { toast('wrong authenticator code', 'error'); return; }
    const d = await r.json();
    _token = d.token; _unlocked = true; $('vault-pw-input').value = '';
    await loadVaultView();
    return;
  }
  toast('this vault needs its security key — use “unlock with biometric”', 'error');
}

// a tiny numeric-code prompt → resolves to the string or null
function _promptCode(title) {
  return new Promise(resolve => {
    const ov = document.createElement('div');
    ov.className = 'modal-overlay vault-modal';
    ov.innerHTML = `
      <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" style="max-width:320px">
        <div class="modal-head"><span class="modal-title">${_esc(title)}</span></div>
        <div class="vault-form"><div class="vform-field">
          <input id="cc-code" class="settings-input vform-input" inputmode="numeric" maxlength="6" placeholder="6-digit code"></div></div>
        <div class="vault-form-actions">
          <button class="btn" id="cc-cancel">cancel</button>
          <button class="btn primary" id="cc-ok">unlock</button></div>
      </div>`;
    document.body.appendChild(ov);
    const done = v => { ov.remove(); resolve(v); };
    ov.querySelector('#cc-cancel').onclick = () => done(null);
    ov.querySelector('#cc-ok').onclick = () => done(ov.querySelector('#cc-code').value.trim());
    ov.querySelector('#cc-code').addEventListener('keydown', e => { if (e.key === 'Enter') done(ov.querySelector('#cc-code').value.trim()); });
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(null); });
    ov.querySelector('#cc-code').focus();
  });
}

async function _doLock() {
  await fetch('/api/vault/lock', { method: 'POST' }).catch(() => {});
  _token = null;
  _unlocked = false;
  _vaultId = 'default';
  _wtOpen = false;
  $('vault-watchtower-btn')?.classList.remove('active');
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
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
