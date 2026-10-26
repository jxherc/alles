import { toast } from './util.js';
import { confirm } from './dialog.js';
import { getDropdownValue, populateDropdown } from './dropdown.js?v=213';
import { formatDateTime, formatNumber, t, tp } from './i18n.js';
import { createFocusBoundary } from './kokuen.js?v=4';

const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

let _unlocked = false;
let _token = null;     // the unlock token; sent back on every vault request
let _entries = [];     // last loaded list, so a row click can open the editor
let _entriesGeneration = 0;
let _revealGeneration = 0;
let _setupState = null;
let _setupGeneration = 0;
let _unlocking = false;
let _unlockGeneration = 0;
let _modalEl = null;   // the open add/edit overlay, if any
let _modalFocusBoundary = null;
let _totpTimer = null;  // live TOTP countdown interval
let _vaultId = 'default';  // 9c — which vault is currently unlocked
let _vaults = [];          // 9c — known vaults for the switcher
let _travel = false;       // 9c — travel mode on?
let _wtOpen = false;       // 8d — is the watchtower panel showing? (the button is a real toggle)
let _wtGeneration = 0;
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
const _fieldDefs = () => ({
  username:       { label: t('common.username'),          kind: 'text' },
  password:       { label: t('common.password'),          kind: 'password' },
  totp:           { label: t('vault.totp_secret_2fa'), kind: 'secret', placeholder: t('vault.base32_secret') },
  url:            { label: t('vault.website'),           kind: 'text', placeholder: 'https://…' },
  notes:          { label: t('common.notes'),             kind: 'textarea' },
  cardholder:     { label: t('vault.cardholder_name'),   kind: 'text' },
  number:         { label: t('vault.card_number'),       kind: 'secret', placeholder: '4242 4242 4242 4242' },
  expiry:         { label: t('vault.expiry'),            kind: 'text', placeholder: 'MM/YY', half: true },
  cvv:            { label: t('vault.cvv'),               kind: 'secret', placeholder: '123', half: true },
  address:        { label: t('vault.billing_address'),   kind: 'textarea' },
  apikey:         { label: t('vault.api_key_token'),   kind: 'secret', placeholder: 'sk-…' },
  endpoint:       { label: t('vault.endpoint'),          kind: 'text', placeholder: 'https://api.…' },
  fullname:       { label: t('vault.full_name'),         kind: 'text' },
  email:          { label: t('vault.email'),             kind: 'text' },
  phone:          { label: t('vault.phone'),             kind: 'text' },
  home_address:   { label: t('vault.address'),           kind: 'textarea' },
  account_holder: { label: t('vault.account_holder'),    kind: 'text' },
  bank_name:      { label: t('vault.bank'),              kind: 'text' },
  account_number: { label: t('vault.account_number'),    kind: 'secret' },
  routing:        { label: t('vault.routing_sort_code'), kind: 'text' },
  private_key:    { label: t('vault.private_key'),       kind: 'secretarea' },
  public_key:     { label: t('vault.public_key'),        kind: 'textarea' },
  passphrase:     { label: t('vault.passphrase'),        kind: 'secret' },
  license_key:    { label: t('vault.license_key'),       kind: 'text' },
  registered_to:  { label: t('vault.registered_to'),     kind: 'text' },
  rp_id:          { label: t('vault.site_rp_id'),       kind: 'text', placeholder: 'github.com' },
});

// the item types. selecting one decides which fields the form shows.
const _builtinTypes = () => [
  { key: 'login',    label: t('vault.login'),            fields: ['username', 'password', 'totp', 'url', 'notes'] },
  { key: 'apikey',   label: t('vault.api_key'),          fields: ['apikey', 'endpoint', 'totp', 'notes'] },
  { key: 'card',     label: t('vault.credit_card'),      fields: ['cardholder', 'number', 'expiry', 'cvv', 'address', 'notes'] },
  { key: 'note',     label: t('vault.secure_note'),      fields: ['notes'] },
  { key: 'identity', label: t('vault.identity'),         fields: ['fullname', 'email', 'phone', 'home_address', 'notes'] },
  { key: 'bank',     label: t('vault.bank_account'),     fields: ['account_holder', 'bank_name', 'account_number', 'routing', 'notes'] },
  { key: 'ssh',      label: t('vault.ssh_key'),          fields: ['private_key', 'public_key', 'passphrase', 'notes'] },
  { key: 'license',  label: t('vault.software_license'), fields: ['license_key', 'registered_to', 'notes'] },
  { key: 'passkey',  label: t('vault.passkey'),          fields: ['rp_id', 'username', 'notes'] },
];
const _builtinType = key => _builtinTypes().find(item => item.key === key);
// what gets stored with an entry stays plain english, whatever language the labels show in
const _TYPE_CATEGORY = { login: 'login', apikey: 'API key', card: 'credit card', note: 'secure note', identity: 'identity', bank: 'bank account', ssh: 'SSH key', license: 'software license', passkey: 'passkey' };
const PRIMARY = {
  login: 'password', apikey: 'apikey', card: 'number', note: 'notes',
  identity: 'email', bank: 'account_number', ssh: 'private_key', license: 'license_key',
  passkey: 'username',
};

// map a stored entry's type → one of our form types. handles legacy values
// (password/card/note from before typed items) and falls back to a field guess.
function _typeForEntry(entry) {
  const t = entry.type;
  if (_builtinType(t)) return t;
  if (_customTypes[t]) return t;   // 8e — a user-defined type
  if (t === 'api_key') return 'apikey';
  if (t === 'password') return 'login';
  if (t === 'card') return 'card';
  if (t === 'note') return 'note';
  const f = Object.keys(_entryFields(entry));
  if (f.includes('number') || f.includes('cardholder')) return 'card';
  if (f.includes('apikey')) return 'apikey';
  if (f.includes('private_key')) return 'ssh';
  if (f.length === 1 && f[0] === 'notes') return 'note';
  return 'login';
}
function _typeLabel(entry) { return _typeDef(_typeForEntry(entry))?.label || t('vault.item'); }

function _entryFields(entry) {
  const fields = { ...(entry?.fields || {}) };
  if (fields.apikey == null && fields.api_key != null) fields.apikey = fields.api_key;
  delete fields.api_key;
  return fields;
}

// fetch wrapper that attaches this session's unlock token so the server can
// bind the request to our unlock (not just "someone unlocked recently")
function _vfetch(url, opts = {}, fetcher = fetch) {
  const headers = { ...(opts.headers || {}) };
  if (_token) headers['X-Vault-Token'] = _token;
  return fetcher(url, { ...opts, headers });
}

async function _checkedVault(url, opts = {}) {
  const response = await _vfetch(url, opts);
  if (!response.ok) throw Object.assign(new Error('vault request failed'), { status: response.status });
  return response;
}

function _sameVault(token, vaultId) {
  return _unlocked && _token === token && _vaultId === vaultId;
}

async function _formAction(ov, work, failure) {
  const token = _token;
  if (!ov || ov._acting || ov._saving || ov._openingSaved || !_sameForm(ov, token)) return;
  ov._acting = true; _formError(ov, ''); _formBusy(ov, true);
  const current = () => _sameForm(ov, token);
  try { await work(current); }
  catch (error) {
    if (!current()) return;
    if (error.status === 403) {
      await _doLock(); toast(t('vault.vault_access_expired_unlock_and'), 'error');
    } else _formError(ov, failure);
  } finally {
    ov._acting = false;
    if (current()) _formBusy(ov, false);
  }
}

function _activateManagedModal(overlay, source, initialFocus) {
  const dialog = overlay.querySelector('[role="dialog"], [role="alertdialog"]');
  if (!dialog) return;
  _modalFocusBoundary = createFocusBoundary(dialog, {
    trigger: source,
    onEscape: _requestCloseModal,
  });
  _modalFocusBoundary.activate({ source, focus: initialFocus });
}

function _activateTemporaryModal(overlay, source, initialFocus, close) {
  const dialog = overlay.querySelector('[role="dialog"], [role="alertdialog"]');
  const boundary = createFocusBoundary(dialog, { trigger: source, onEscape: () => close(null) });
  boundary.activate({ source, focus: initialFocus });
  return boundary;
}

async function _confirmRecentOwner() {
  const me = await fetch('/api/auth/me').then(r => r.json()).catch(() => null);
  if (me?.enabled === false) return true;
  const password = await _promptPw(t('vault.confirm_alles_password'), {
    placeholder: t('vault.alles_password'),
    action: 'confirm',
  });
  if (password == null) return false;
  const response = await fetch('/api/auth/reauth', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) toast(t('vault.password_confirmation_failed'), 'error');
  return response.ok;
}

async function _vfetchRecentOwner(url, opts = {}) {
  if (Object.prototype.hasOwnProperty.call(opts, 'body')) {
    throw new TypeError('recent-owner retry only supports bodyless requests');
  }
  let response = await _vfetch(url, opts);
  if (response.status !== 403) return response;
  const payload = await response.clone().json().catch(() => ({}));
  if (payload.code !== 'recent_auth_required' || !await _confirmRecentOwner()) return response;
  return _vfetch(url, opts);
}

export async function loadVaultView(fetcher = fetch) {
  const locked   = $('vault-locked');
  const unlocked = $('vault-unlocked');
  if (!locked || !unlocked) return;
  _decorateToolbar();
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
  if (_unlocked) { await _loadCustomTypes(fetcher); await _loadEntries(fetcher); await _loadVaults(fetcher); }
  else {
    _unlockError('');
    const [, biometricReady] = await Promise.all([_refreshVaultSetup(fetcher), _refreshBioUnlock(fetcher)]);
    if (biometricReady === false && _setupState) {
      return { partialMessage: t('vault.biometric_check_failed'), retryLabel: t('vault.retry_checks') };
    }
  }
}

async function _refreshVaultSetup(fetcher = fetch) {
  const generation = ++_setupGeneration;
  const button = $('vault-unlock-btn');
  const retry = $('vault-setup-retry');
  if (!button) return;
  _setupState = null;
  button.textContent = t('vault.checking');
  button.disabled = true;
  if (retry) retry.hidden = true;
  try {
    const response = await fetcher('/api/vault/setup');
    if (!response.ok) throw new Error('setup status unavailable');
    const status = await response.json();
    if (_unlocked || generation !== _setupGeneration) return;
    if (!['setup', 'locked', 'recovery'].includes(status.state)) throw new Error('invalid setup status');
    _setupState = status.state;
    const creating = _setupState === 'setup';
    $('vault-password-label').textContent = creating ? t('vault.create_a_master_password') : t('vault.master_password');
    $('vault-pw-input').autocomplete = 'current-password';
    if (creating) $('vault-pw-input').autocomplete = 'new-password';
    $('vault-confirm-field').hidden = !creating;
    if (!creating) $('vault-pw-confirm').value = '';
    button.textContent = creating ? t('vault.create_vault') : t('vault.unlock');
    button.disabled = _unlocking || _setupState === 'recovery';
    $('vault-lock-help').textContent = _setupState === 'recovery'
      ? t('vault.recovery_help')
      : t('vault.lock_help');
  } catch {
    if (_unlocked || generation !== _setupGeneration) return;
    _unlockError(t('vault.could_not_check_vault_setup_retry'));
    if (retry) retry.hidden = false;
  }
}

function _unlockError(message) {
  const error = $('vault-unlock-error');
  if (error) { error.textContent = message; error.hidden = !message; }
}

async function _loadCustomTypes(fetcher = fetch) {
  try { _customTypes = (await _vfetch('/api/vault/custom-types', {}, fetcher).then(r => r.json())).types || {}; }
  catch { _customTypes = {}; }
}

// built-in + custom types, as {key, label, fields:[defObj]}
function _allTypes() {
  const custom = Object.entries(_customTypes).map(([key, t]) => ({ key, label: t.label, custom: true, fields: t.fields || [] }));
  return [..._builtinTypes(), ...custom];
}
function _typeDef(key) {
  if (_builtinType(key)) return _builtinType(key);
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
  const d = _fieldDefs()[key];
  return d ? { key, ...d } : { key, label: key, kind: 'text', placeholder: '' };
}

export function initVault() {
  $('vault-unlock-btn')?.addEventListener('click', _doUnlock);
  $('vault-setup-retry')?.addEventListener('click', () => { _unlockError(''); _refreshVaultSetup(); });
  $('vault-lock-btn')?.addEventListener('click', _doLock);
  $('vault-new-btn')?.addEventListener('click', () => openVaultForm());
  $('vault-watchtower-btn')?.addEventListener('click', showWatchtower);
  $('vault-add-btn')?.addEventListener('click', _createVaultForm);
  $('vault-travel-btn')?.addEventListener('click', _toggleTravel);
  $('vault-manage-btn')?.addEventListener('click', _manageVaults);
  $('vault-bio-add-btn')?.addEventListener('click', _enableBiometric);
  $('vault-bio-unlock-btn')?.addEventListener('click', _bioUnlock);
  $('vault-pw-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') _doUnlock(); });
  $('vault-pw-confirm')?.addEventListener('keydown', e => { if (e.key === 'Enter') _doUnlock(); });
  // a message about the last try clears once either field changes, so it never describes old input.
  // a failed setup check isn't about the input, so it stays until retry
  for (const id of ['vault-pw-input', 'vault-pw-confirm']) $(id)?.addEventListener('input', () => { if (!_unlocking && _setupState) _unlockError(''); });
  _decorateToolbar();
}

// 8a — unified icons on the toolbar (settings is now rightmost). redone on every load so a
// language switch shows up
function _decorateToolbar() {
  const dec = (id, name, label) => { const b = $(id); if (b) b.innerHTML = `${_si(name)} ${_esc(label)}`; };
  dec('vault-manage-btn', 'gear', t('common.settings'));
  dec('vault-bio-add-btn', 'fingerprint', t('vault.biometric'));
  dec('vault-watchtower-btn', 'shield', t('vault.watchtower'));
  dec('vault-bio-unlock-btn', 'fingerprint', t('vault.unlock_with_biometric'));
}

// 9c — multiple vaults, Travel Mode, biometric ──────────────────────────────
async function _loadVaults(fetcher = fetch) {
  try {
    _vaults = await _vfetch('/api/vault/vaults', {}, fetcher).then(r => r.json());
    const tm = await fetcher('/api/vault/travel-mode').then(r => r.json()).catch(() => ({}));
    _travel = !!tm.on;
  } catch { _vaults = []; }
  _renderSwitcher();
  const tb = $('vault-travel-btn');
  if (tb) { tb.classList.toggle('active', _travel); tb.innerHTML = `${_si('plane')} ${_esc(_travel ? t('vault.travel_on') : t('vault.travel'))}`; }
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
  const pw = await _promptPw(t('vault.unlock_named', { name: v?.name || t('vault.vault') }));
  if (pw == null) { _renderSwitcher(); return; }  // cancelled → restore selection
  try {
    const r = await fetch('/api/vault/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw, vault_id: id }),
    });
    if (!r.ok) { toast(t('vault.wrong_password_for_that_vault'), 'error'); _renderSwitcher(); return; }
    const j = await r.json();
    if (j.requires_2fa) { await _do2fa(pw, { ...j, vault_id: id }); return; }  // 2fa vault was unreachable via the switcher
    _token = j.token; _vaultId = j.vault_id;
    await _loadEntries(); await _loadVaults();
    toast(t('vault.switched_vault'), 'success');
  } catch { toast(t('vault.switch_failed'), 'error'); _renderSwitcher(); }
}

function _createVaultForm() {
  const returnFocus = document.activeElement;
  _closeModal();
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="nv-title">
      <div class="modal-head"><span class="modal-title" id="nv-title">${_esc(t('vault.new_vault'))}</span>
        <button type="button" class="modal-close" id="nv-x" aria-label="${_esc(t('common.close'))}">✕</button></div>
      <div class="vault-form">
        <div class="vform-field"><label for="nv-name">${_esc(t('common.name'))}</label>
          <input id="nv-name" class="settings-input vform-input" placeholder="${_esc(t('vault.e_g_work'))}"></div>
        <div class="vform-field"><label for="nv-pw">${_esc(t('vault.master_password'))}</label>
          <input id="nv-pw" type="password" autocomplete="new-password" class="settings-input vform-input" minlength="12" placeholder="${_esc(t('vault.12_or_more_characters'))}"></div>
      </div>
      <div class="vault-form-actions">
        <button type="button" class="btn" id="nv-cancel">${_esc(t('common.cancel'))}</button>
        <button type="button" class="btn primary" id="nv-create">${_esc(t('common.create'))}</button>
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
    if (!name || pw.length < 12) { toast(t('vault.name_a_12_character_password'), 'error'); return; }
    const r = await _vfetch('/api/vault/vaults', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, password: pw }),
    });
    if (!r.ok) { toast(t('vault.create_failed'), 'error'); return; }
    const j = await r.json();
    _closeModal();
    // unlock straight into the new vault
    const u = await fetch('/api/vault/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw, vault_id: j.id }),
    }).then(x => x.json());
    _token = u.token; _vaultId = u.vault_id;
    await _loadEntries(); await _loadVaults();
    toast(t('vault.vault_created'), 'success');
  };
  _activateManagedModal(ov, returnFocus, ov.querySelector('#nv-name'));
}

async function _toggleTravel() {
  try {
    const r = await _vfetch('/api/vault/travel-mode', {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ on: !_travel }),
    }).then(x => x.json());
    _travel = !!r.on;
    await _loadVaults();
    toast(_travel ? t('vault.travel_mode_on_only_travel_safe') : t('vault.travel_mode_off'), 'success');
  } catch { toast(t('vault.could_not_toggle_travel_mode'), 'error'); }
}

async function _manageVaults() {
  const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  _closeModal();
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="mv-title">
      <div class="modal-head"><span class="modal-title" id="mv-title">${_esc(t('vault.vaults'))}</span>
        <button type="button" class="modal-close" id="mv-x" aria-label="${_esc(t('common.close'))}">✕</button></div>
      <div class="mv-scroll">
        <div class="vault-form" id="mv-list"></div>
        <div class="vform-divider"></div>
        <div class="vault-form" id="mv-extra"></div>
        <div class="vform-divider"></div>
        <div class="vault-form" id="mv-types"></div>
      </div>
      <div class="vault-form-actions"><button type="button" class="btn" id="mv-close">${_esc(t('common.done'))}</button></div>
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
  _activateManagedModal(ov, returnFocus, ov.querySelector('#mv-x'));
}

// 8e — visual editor for user-defined entry types
let _vtDraft = null;   // { key, label, fields:[{key,label,width,kind,placeholder}] } while editing

function _renderTypeEditor() {
  const box = _modalEl?.querySelector('#mv-types');
  if (!box) return;
  const types = Object.entries(_customTypes);
  box.innerHTML = `
    <div class="mv-2fa-head">${_esc(t('vault.custom_entry_types'))}</div>
    <p class="mv-2fa-explain">${_esc(t('vault.define_your_own_item_types_name'))}</p>
    <div class="vt-list">
      ${types.length ? types.map(([k, type]) => `
        <div class="vt-row" data-k="${k}">
          <span class="vt-name">${_esc(type.label)}</span>
          <span class="vt-meta">${_esc(tp('vault.field_count', type.fields.length))}</span>
          <span class="vault-entry-grow"></span>
          <button class="act-btn" data-edit="${k}">${_esc(t('common.edit'))}</button>
          <button class="act-btn danger" data-del="${k}">${_esc(t('common.delete'))}</button>
        </div>`).join('') : `<div class="vform-empty">${_esc(t('vault.no_custom_types_yet'))}</div>`}
    </div>
    <button class="act-btn" id="vt-new">${_esc(t('vault.new_type'))}</button>
    <div id="vt-edit"></div>`;
  box.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => _editType(b.dataset.edit));
  box.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!await confirm(t('vault.delete_this_custom_type'))) return;
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
const _widthWord = w => ({ full: t('vault.width_full'), half: t('vault.width_half'), third: t('vault.width_third') })[w] || w;
const _kindWord = k => ({ text: t('vault.kind_text'), secret: t('vault.kind_secret'), password: t('common.password'), textarea: t('vault.kind_textarea') })[k] || k;

function _renderTypeForm() {
  const box = _modalEl?.querySelector('#vt-edit');
  if (!box || !_vtDraft) return;
  box.innerHTML = `
    <div class="vt-form">
      <div class="vform-field"><label>${_esc(t('vault.type_name'))}</label>
        <input id="vt-label" class="settings-input vform-input" placeholder="${_esc(t('vault.e_g_wi_fi'))}" value="${_esc(_vtDraft.label)}"></div>
      <div class="vt-fields">
        ${_vtDraft.fields.map((f, i) => `
          <div class="vt-field" data-i="${i}">
            <input class="settings-input vt-flabel" data-i="${i}" placeholder="${_esc(t('vault.field_name'))}" value="${_esc(f.label)}">
            <div class="seg seg-sm vt-width" data-i="${i}">${_WIDTHS.map(w => `<button type="button" class="seg-opt${f.width === w ? ' active' : ''}" data-w="${w}">${_esc(_widthWord(w))}</button>`).join('')}</div>
            <div class="seg seg-sm vt-kind" data-i="${i}">${_KINDS.map(k => `<button type="button" class="seg-opt${(f.kind || 'text') === k ? ' active' : ''}" data-kd="${k}">${_esc(_kindWord(k))}</button>`).join('')}</div>
            <button type="button" class="act-btn danger vt-rmf" data-i="${i}" title="${_esc(t('vault.remove_field'))}">${_si('close')}</button>
          </div>`).join('')}
      </div>
      <div class="vt-form-actions">
        <button type="button" class="act-btn" id="vt-addf">${_esc(t('vault.field'))}</button>
        <span class="vault-entry-grow"></span>
        <button type="button" class="btn" id="vt-cancel">${_esc(t('common.cancel'))}</button>
        <button type="button" class="btn primary" id="vt-save">${_esc(t('vault.save_type'))}</button>
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
  if (!label) return err(t('vault.give_the_type_a_name'));
  const fields = _vtDraft.fields
    .filter(f => f.label.trim())
    .map(f => ({ key: f.key || _slug(f.label), label: f.label.trim(), width: f.width, kind: f.kind }));
  if (!fields.length) return err(t('vault.add_at_least_one_field'));
  const key = _vtDraft.key || _slug(label);
  const r = await _vfetch(`/api/vault/custom-types/${key}`, {
    method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ label, fields }),
  });
  if (!r.ok) return err(t('vault.could_not_save'));
  _vtDraft = null;
  await _loadCustomTypes();
  _renderTypeEditor();
  toast(t('vault.type_saved'), 'success');
}

function _browserSeen(value) {
  if (!value) return t('vault.not_used_yet');
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? t('vault.used_before') : t('vault.last_used', { date: formatDateTime(date) });
}

function _browserCreated(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? t('vault.paired_before') : t('vault.paired_on', { date: formatDateTime(date) });
}

function _browserExpiry(seconds) {
  const minutes = Math.max(1, Math.ceil(Number(seconds || 0) / 60));
  return t('vault.expires_in', { minutes });
}

function _browserAccessMarkup(state, failed) {
  if (failed) return `<p class="mv-browser-empty" role="alert">${_esc(t('vault.browser_load_failed'))}</p>`;
  const pairings = state.pairings || [];
  const unlocks = state.unlock_requests || [];
  const connections = state.connections || [];
  const requests = [
    ...pairings.map(item => `
      <div class="mv-browser-row request" role="listitem">
        <div class="mv-browser-copy"><strong>${_esc(item.name)}</strong><small>${t('vault.pairing_code_line', { code: `<span class="mv-browser-code">${_esc(item.code)}</span>`, expiry: _esc(_browserExpiry(item.expires_in)) })}</small></div>
        <button class="act-btn" type="button" data-browser-pair="${_esc(item.id)}" aria-label="${_esc(t('vault.approve_pairing_for', { name: item.name }))}">${_esc(t('vault.approve'))}</button>
        <button class="act-btn danger" type="button" data-browser-pair-deny="${_esc(item.id)}" aria-label="${_esc(t('vault.deny_pairing_for', { name: item.name }))}">${_esc(t('vault.deny'))}</button>
      </div>`),
    ...unlocks.map(item => `
      <div class="mv-browser-row request" role="listitem">
        <div class="mv-browser-copy"><strong>${_esc(item.name)}</strong><small>${t('vault.access_code_line', { code: `<span class="mv-browser-code">${_esc(item.code)}</span>`, expiry: _esc(_browserExpiry(item.expires_in)) })}</small></div>
        <button class="act-btn" type="button" data-browser-unlock="${_esc(item.id)}" aria-label="${_esc(t('vault.approve_access_for', { name: item.name }))}">${_esc(t('vault.approve'))}</button>
        <button class="act-btn danger" type="button" data-browser-unlock-deny="${_esc(item.id)}" aria-label="${_esc(t('vault.deny_access_for', { name: item.name }))}">${_esc(t('vault.deny'))}</button>
      </div>`),
  ];
  return `
    ${requests.length ? `<div class="mv-browser-group"><div class="mv-browser-label">${_esc(t('vault.waiting_for_you'))}</div><div role="list">${requests.join('')}</div></div>` : ''}
    <div class="mv-browser-group">
      <div class="mv-browser-label">${_esc(t('vault.connected_to_this_vault'))}</div>
      <div role="list">
        ${connections.length ? connections.map(item => `
          <div class="mv-browser-row" role="listitem">
            <div class="mv-browser-copy"><strong>${_esc(item.name)}</strong><small>${_esc(_browserCreated(item.created_at))} · ${_esc(_browserSeen(item.last_seen_at))}</small></div>
            <span class="mv-browser-state${item.locked ? '' : ' active'}">${_esc(item.locked ? t('vault.locked') : t('vault.access_active'))}</span>
            <button class="act-btn" type="button" data-browser-lock="${_esc(item.id)}" ${item.locked ? 'disabled' : ''}>${_esc(t('vault.lock'))}</button>
            <button class="act-btn danger" type="button" data-browser-revoke="${_esc(item.id)}" data-browser-name="${_esc(item.name)}">${_esc(t('vault.revoke'))}</button>
          </div>`).join('') : `<p class="mv-browser-empty">${_esc(t('vault.no_browsers_connected_to_this'))}</p>`}
      </div>
    </div>`;
}

async function _browserOwnerMutation(url, opts, success) {
  try {
    const response = await _vfetchRecentOwner(url, opts);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      toast(payload.message || payload.detail || t('vault.browser_access_could_not_be'), 'error');
      return false;
    }
    toast(success, 'success');
    await _renderManageExtra();
    return true;
  } catch {
    toast(t('vault.browser_access_could_not_be'), 'error');
    return false;
  }
}

async function _downloadBrowserExtension(button) {
  button.disabled = true;
  try {
    const response = await _vfetchRecentOwner('/api/vault/browsers/extension');
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.message || payload.detail || t('vault.extension_download_failed'));
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = 'alles-passwords-extension.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast(t('vault.extension_downloaded'), 'success');
  } catch (error) {
    toast(error.message || t('vault.extension_download_failed'), 'error');
  } finally {
    button.disabled = false;
  }
}

// the "this vault" extras: hardware-key 2FA + exact-site browser access
async function _renderManageExtra() {
  const box = _modalEl?.querySelector('#mv-extra');
  if (!box) return;
  let st = { on: false, totp: false, credentials: [] };
  let browsers = { connections: [], pairings: [], unlock_requests: [] };
  let browserLoadFailed = false;
  const [factorResult, browserResult] = await Promise.allSettled([
    _vfetch('/api/vault/2fa').then(response => response.ok ? response.json() : Promise.reject()),
    _vfetch('/api/vault/browsers').then(response => response.ok ? response.json() : Promise.reject()),
  ]);
  if (factorResult.status === 'fulfilled') st = factorResult.value;
  if (browserResult.status === 'fulfilled') browsers = browserResult.value;
  else browserLoadFailed = true;
  if (!box.isConnected) return;
  const cur = _vaults.find(v => v.id === _vaultId);
  const keyCount = (st.credentials || []).length;
  box.innerHTML = `
    <div class="mv-2fa-head">${t('vault.two_factor_head', { name: `<span class="mv-cur">${_esc(cur?.name || t('vault.this_vault'))}</span>` })}</div>
    <p class="mv-2fa-explain">${t('vault.two_factor_explain', { after: `<b>${_esc(t('vault.explain_after'))}</b>` })}</p>
    <div class="mv-row">
      <span class="mv-name">${_esc(t('vault.passkey_security_key'))}${keyCount ? ` <span class="mv-badge">${_esc(t('vault.enrolled_count', { count: keyCount }))}</span>` : ''}</span>
      <span class="vault-entry-grow"></span>
      <button class="act-btn" id="mv-2fa-add" title="${_esc(t('vault.register_a_fido2_yubikey_or'))}">${_esc(t('vault.key'))}</button>
    </div>
    <div class="mv-row">
      <span class="mv-name">${_esc(t('vault.authenticator_app_totp'))}${st.totp ? ` <span class="mv-badge mv-main">${_esc(t('vault.enrolled'))}</span>` : ''}</span>
      <span class="vault-entry-grow"></span>
      ${st.totp
        ? `<button class="act-btn danger" id="mv-totp-del">${_esc(t('common.remove'))}</button>`
        : `<button class="act-btn" id="mv-totp-add" title="${_esc(t('vault.enrol_title'))}">${_esc(t('vault.set_up'))}</button>`}
    </div>
    <div class="mv-row">
      <span class="mv-name">${_esc(t('vault.require_a_second_factor_to_unlock'))}</span>
      <span class="vault-entry-grow"></span>
      <button class="home-settings-switch" type="button" id="mv-2fa" role="switch" aria-label="${_esc(t('vault.require_a_second_factor_to_unlock'))}" aria-checked="${st.on}"></button>
    </div>
    <p class="mv-2fa-note">${t('vault.biometric_note', { bio: `<b>${_esc(t('vault.note_biometric'))}</b>`, typing: `<i>${_esc(t('vault.note_without_typing'))}</i>`, passkey: `<b>${_esc(t('vault.note_passkey_2fa'))}</b>` })}</p>
    <section class="mv-browser" id="vault-browser-access" aria-labelledby="mv-browser-title">
      <div class="mv-browser-head">
        <div><h3 id="mv-browser-title">${_esc(t('vault.connected_browsers'))}</h3><p>${_esc(t('vault.approve_each_browser_here_access'))}</p></div>
        <button class="act-btn" type="button" id="mv-browser-refresh">${_esc(t('common.refresh'))}</button>
      </div>
      <div id="mv-browser-content" aria-live="polite">${_browserAccessMarkup(browsers, browserLoadFailed)}</div>
      <div class="mv-browser-install">
        <p>${t('vault.extension_steps', { url: '<code>chrome://extensions</code>', action: `<b>${_esc(t('vault.load_unpacked'))}</b>` })}</p>
        <button class="act-btn" type="button" id="mv-browser-download">${_esc(t('vault.download_extension'))}</button>
      </div>
    </section>`;
  box.querySelector('#mv-2fa').onclick = async () => {
    try {
      const r = await _vfetch('/api/vault/2fa', {
        method: 'PUT', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ on: !st.on }),
      }).then(x => x.json());
      await _renderManageExtra();
      toast(r.on ? t('vault.second_factor_required_to_unlock') : t('vault.2fa_off'), 'success');
    } catch { toast(t('vault.could_not_change_2fa'), 'error'); }
  };
  box.querySelector('#mv-2fa-add').onclick = _registerSecurityKey;
  box.querySelector('#mv-totp-add')?.addEventListener('click', _setupTotp);
  box.querySelector('#mv-totp-del')?.addEventListener('click', async () => {
    if (!await confirm(t('vault.remove_the_authenticator_app'))) return;
    await _vfetch('/api/vault/2fa/totp', { method: 'DELETE' });
    await _renderManageExtra();
    toast(t('vault.authenticator_app_removed'), 'success');
  });
  box.querySelector('#mv-browser-refresh').onclick = async event => {
    event.currentTarget.disabled = true;
    await _renderManageExtra();
  };
  box.querySelector('#mv-browser-download').onclick = event => _downloadBrowserExtension(event.currentTarget);
  box.querySelectorAll('[data-browser-pair]').forEach(button => button.onclick = () =>
    _browserOwnerMutation(`/api/vault/browsers/pairings/${button.dataset.browserPair}/approve`, { method: 'POST' }, t('vault.browser_paired')));
  box.querySelectorAll('[data-browser-pair-deny]').forEach(button => button.onclick = () =>
    _browserOwnerMutation(`/api/vault/browsers/pairings/${button.dataset.browserPairDeny}`, { method: 'DELETE' }, t('vault.pairing_denied')));
  box.querySelectorAll('[data-browser-unlock]').forEach(button => button.onclick = () =>
    _browserOwnerMutation(`/api/vault/browsers/unlock-requests/${button.dataset.browserUnlock}/approve`, { method: 'POST' }, t('vault.browser_access_approved')));
  box.querySelectorAll('[data-browser-unlock-deny]').forEach(button => button.onclick = () =>
    _browserOwnerMutation(`/api/vault/browsers/unlock-requests/${button.dataset.browserUnlockDeny}`, { method: 'DELETE' }, t('vault.browser_access_denied')));
  box.querySelectorAll('[data-browser-lock]').forEach(button => button.onclick = () =>
    _browserOwnerMutation(`/api/vault/browsers/${button.dataset.browserLock}/lock`, { method: 'POST' }, t('vault.browser_locked')));
  box.querySelectorAll('[data-browser-revoke]').forEach(button => button.onclick = async () => {
    if (!await confirm(t('vault.revoke_confirm', { name: button.dataset.browserName || t('vault.this_browser') }))) return;
    await _browserOwnerMutation(`/api/vault/browsers/${button.dataset.browserRevoke}`, { method: 'DELETE' }, t('vault.browser_revoked'));
  });
}

// 8c — enrol an authenticator app: fetch a secret, show it + a confirm-code box
async function _setupTotp() {
  let d;
  try { d = await _vfetch('/api/vault/2fa/totp/setup', { method: 'POST' }).then(r => r.json()); }
  catch { toast(t('vault.could_not_start_setup'), 'error'); return; }
  const ov = document.createElement('div');
  const returnFocus = document.activeElement;
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="totp-title" style="max-width:380px">
      <div class="modal-head"><span class="modal-title" id="totp-title">${_esc(t('vault.add_authenticator_app'))}</span></div>
      <div class="vault-form">
        <p class="mv-2fa-explain">${_esc(t('vault.scan_this_in_google_authenticator'))}</p>
        <div class="totp-secret" id="totp-secret">${_esc(d.secret)}</div>
        <div class="vform-field"><input id="totp-code" class="settings-input vform-input" inputmode="numeric" maxlength="6" placeholder="${_esc(t('vault.6_digit_code'))}"></div>
        <div class="np-err" id="totp-err"></div>
      </div>
      <div class="vault-form-actions">
        <button class="btn" id="totp-cancel">${_esc(t('common.cancel'))}</button>
        <button class="btn primary" id="totp-ok">${_esc(t('common.confirm'))}</button></div>
    </div>`;
  document.body.appendChild(ov);
  let focusBoundary = null;
  const close = () => {
    focusBoundary?.deactivate();
    focusBoundary?.destroy();
    ov.remove();
  };
  ov.querySelector('#totp-cancel').onclick = close;
  ov.addEventListener('mousedown', e => { if (e.target === ov) close(); });
  const go = async () => {
    const code = ov.querySelector('#totp-code').value.trim();
    const r = await _vfetch('/api/vault/2fa/totp', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ secret: d.secret, code }),
    });
    if (!r.ok) { ov.querySelector('#totp-err').textContent = t('vault.code_didn_t_match_try_the_current'); return; }
    close();
    await _renderManageExtra();
    toast(t('vault.authenticator_app_enrolled'), 'success');
  };
  ov.querySelector('#totp-ok').onclick = go;
  ov.querySelector('#totp-code').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  focusBoundary = _activateTemporaryModal(ov, returnFocus, ov.querySelector('#totp-code'), close);
}

async function _registerSecurityKey() {
  if (!window.PublicKeyCredential) { toast(t('vault.security_keys_not_supported_here'), 'error'); return; }
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
    if (!pub) { toast(t('vault.unsupported_security_key'), 'error'); return; }
    await _vfetch('/api/vault/2fa/register', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ label: 'security key', credential_id: _b64(cred.rawId), public_key: _b64(pub) }),
    });
    toast(t('vault.security_key_registered'), 'success');
    await _renderManageExtra();
  } catch { toast(t('vault.security_key_registration'), ''); }
}

function _renderManage() {
  const box = _modalEl?.querySelector('#mv-list');
  if (!box) return;
  box.innerHTML = _vaults.map(v => `
    <div class="mv-row" data-id="${v.id}">
      <span class="mv-name" data-rename="${v.id}" title="${_esc(t('vault.click_to_rename'))}">${_esc(v.name)}</span>
      <span class="mv-badge${v.main ? ' mv-main' : ''}" title="${_esc(v.main ? t('vault.opens_with_master') : t('vault.has_own_password'))}">${_esc(v.main ? t('vault.main') : t('vault.own_password'))}</span>
      ${v.id === _vaultId ? `<span class="mv-cur">${_esc(t('vault.current'))}</span>` : ''}
      <span class="vault-entry-grow"></span>
      <span class="mv-entries">${_esc(tp('vault.item_count', v.entries))}</span>
      ${v.id === _vaultId ? `<button class="act-btn" data-chpw="${v.id}">${_esc(v.main ? t('vault.change_master_password') : t('vault.change_password'))}</button>` : ''}
      <button class="chip ic-btn-lbl ${v.travel_safe ? 'on' : ''}" data-travel="${v.id}" title="${_esc(t('vault.reachable_while_travelling'))}">${_si('plane')} ${_esc(t('vault.travel_safe'))}</button>
      ${v.id === 'default' ? '' : `<button class="act-btn danger" data-del="${v.id}">${_esc(t('common.delete'))}</button>`}
    </div>`).join('')
    + `<div class="mv-help">${t('vault.manage_help', { main: `<b>${_esc(t('vault.main'))}</b>` })}</div>`;
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
    if (!await confirm(t('vault.delete_this_vault_and_all_its'))) return;
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
    if (!r.ok) { toast(t('vault.change_failed'), 'error'); return; }
    _token = (await r.json()).token;   // re-bind to the new password
    toast(t('vault.password_changed'), 'success');
  } catch { toast(t('vault.change_failed'), 'error'); }
}

// a tiny password prompt that resolves to the entered string (or null on cancel)
function _promptPw(title, { placeholder = t('vault.master_password'), action = t('vault.unlock') } = {}) {
  return new Promise(resolve => {
    const returnFocus = document.activeElement;
    const ov = document.createElement('div');
    ov.className = 'modal-overlay vault-modal';
    ov.innerHTML = `
      <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="pp-title" style="max-width:340px">
        <div class="modal-head"><span class="modal-title" id="pp-title">${_esc(title)}</span></div>
        <div class="vault-form"><div class="vform-field">
          <label for="pp-pw">${_esc(t('common.password'))}</label>
          <input id="pp-pw" type="password" autocomplete="current-password" class="settings-input vform-input" placeholder="${_esc(placeholder)}"></div></div>
        <div class="vault-form-actions">
          <button type="button" class="btn" id="pp-cancel">${_esc(t('common.cancel'))}</button>
          <button type="button" class="btn primary" id="pp-ok">${_esc(action)}</button></div>
      </div>`;
    document.body.appendChild(ov);
    let focusBoundary = null;
    const done = val => {
      focusBoundary?.deactivate();
      focusBoundary?.destroy();
      ov.remove();
      resolve(val);
    };
    ov.querySelector('#pp-cancel').onclick = () => done(null);
    ov.querySelector('#pp-ok').onclick = () => done(ov.querySelector('#pp-pw').value);
    ov.querySelector('#pp-pw').addEventListener('keydown', e => { if (e.key === 'Enter') done(ov.querySelector('#pp-pw').value); });
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(null); });
    focusBoundary = _activateTemporaryModal(ov, returnFocus, ov.querySelector('#pp-pw'), done);
  });
}

// new-password prompt with confirm (8b change-password); resolves to the password or null
function _promptNewPw() {
  return new Promise(resolve => {
    const returnFocus = document.activeElement;
    const ov = document.createElement('div');
    ov.className = 'modal-overlay vault-modal';
    ov.innerHTML = `
      <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="np-title" style="max-width:340px">
        <div class="modal-head"><span class="modal-title" id="np-title">${_esc(t('vault.change_password'))}</span></div>
        <div class="vault-form">
          <div class="vform-field"><label for="np-1">${_esc(t('vault.new_password'))}</label><input id="np-1" type="password" autocomplete="new-password" class="settings-input vform-input" minlength="12" placeholder="${_esc(t('vault.12_or_more_characters'))}"></div>
          <div class="vform-field"><label for="np-2">${_esc(t('vault.confirm_new_password'))}</label><input id="np-2" type="password" autocomplete="new-password" class="settings-input vform-input" minlength="12" placeholder="${_esc(t('vault.repeat_new_password'))}"></div>
          <div class="np-err" id="np-err"></div>
        </div>
        <div class="vault-form-actions">
          <button type="button" class="btn" id="np-cancel">${_esc(t('common.cancel'))}</button>
          <button type="button" class="btn primary" id="np-ok">${_esc(t('vault.change'))}</button></div>
      </div>`;
    document.body.appendChild(ov);
    let focusBoundary = null;
    const done = val => {
      focusBoundary?.deactivate();
      focusBoundary?.destroy();
      ov.remove();
      resolve(val);
    };
    const go = () => {
      const a = ov.querySelector('#np-1').value, b = ov.querySelector('#np-2').value;
      if (a.length < 12) { ov.querySelector('#np-err').textContent = t('vault.use_at_least_12_characters'); return; }
      if (a !== b) { ov.querySelector('#np-err').textContent = t('vault.passwords_don_t_match'); return; }
      done(a);
    };
    ov.querySelector('#np-cancel').onclick = () => done(null);
    ov.querySelector('#np-ok').onclick = go;
    ov.querySelectorAll('input').forEach(i => i.addEventListener('keydown', e => { if (e.key === 'Enter') go(); }));
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(null); });
    focusBoundary = _activateTemporaryModal(ov, returnFocus, ov.querySelector('#np-1'), done);
  });
}

async function _enableBiometric() {
  if (!window.PublicKeyCredential) { toast(t('vault.biometric_not_supported_in_this'), 'error'); return; }
  try {
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const cred = await navigator.credentials.create({ publicKey: {
      challenge,
      rp: { name: 'alles vault' },
      user: { id: new TextEncoder().encode('vault:' + _vaultId), name: 'vault:' + _vaultId, displayName: 'vault' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],  // ES256
      authenticatorSelection: { userVerification: 'required' },
      timeout: 60000,
    }});
    const pub = cred.response.getPublicKey();  // SPKI DER
    if (!pub) { toast(t('vault.this_authenticator_is_unsupported'), 'error'); return; }
    const r = await _vfetch('/api/vault/webauthn/register', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ label: navigator.platform || 'device',
        credential_id: _b64(cred.rawId), public_key: _b64(pub) }),
    });
    if (!r.ok) { toast(t('vault.could_not_enable_biometric'), 'error'); return; }
    toast(t('vault.biometric_unlock_enabled_for_this'), 'success');
  } catch (e) { toast(t('vault.biometric_setup_cancelled'), ''); }
}

// show the lock-screen biometric button only if the default vault has a credential
async function _refreshBioUnlock(fetcher = fetch) {
  const btn = $('vault-bio-unlock-btn');
  if (!btn) return;
  if (!window.PublicKeyCredential) { btn.style.display = 'none'; return; }
  try {
    const response = await fetcher('/api/vault/webauthn/challenge?vault_id=default');
    if (!response.ok) throw new Error('biometric availability check failed');
    const d = await response.json();
    btn.style.display = (d.credentials && d.credentials.length) ? '' : 'none';
    return true;
  } catch { btn.style.display = 'none'; return false; }
}

async function _bioUnlock() {
  try {
    const d = await fetch('/api/vault/webauthn/challenge?vault_id=default').then(r => r.json());
    if (!d.credentials || !d.credentials.length) { toast(t('vault.no_biometric_set_up'), 'error'); return; }
    const assertion = await navigator.credentials.get({ publicKey: {
      challenge: _b64ToBuf(d.challenge),
      timeout: 60000,
      userVerification: 'required',
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
    if (!r.ok) { toast(t('vault.biometric_unlock_failed'), 'error'); return; }
    const j = await r.json();
    _token = j.token; _vaultId = j.vault_id; _unlocked = true;
    await loadVaultView();
    _settleFocus(_entryButton());
  } catch (e) { toast(t('vault.biometric_unlock_cancelled'), ''); }
}

// 9a — Watchtower security panel (weak / reused / breached)
function _closeWatchtower() {
  _wtOpen = false;
  _wtGeneration++;
  $('vault-watchtower-btn')?.classList.remove('active');
  _loadEntries();
}

async function showWatchtower() {
  if (_wtOpen) { _closeWatchtower(); return; }   // 8d — real toggle: re-click hides it
  const list = $('vault-entry-list');
  if (!list) return;
  _wtOpen = true;
  const generation = ++_wtGeneration;
  const token = _token, vaultId = _vaultId;
  const current = () => _wtOpen && generation === _wtGeneration && _sameVault(token, vaultId);
  _entriesGeneration++;
  $('vault-watchtower-btn')?.classList.add('active');
  list.innerHTML = `<div class="page-empty" role="status">${_esc(t('vault.scanning'))}</div>`;
  let d;
  try {
    const response = await _vfetch('/api/vault/watchtower');
    if (!response.ok) throw new Error('scan failed');
    d = await response.json();
    if (!d || !['breached', 'reused', 'weak'].every(key => Array.isArray(d[key]))) throw new Error('invalid scan response');
    if (!d.weak.every(row => row && typeof row.name === 'string')
      || !d.breached.every(row => row && typeof row.name === 'string' && Number.isSafeInteger(row.count) && row.count > 0)
      || !d.reused.every(row => row && Array.isArray(row.names) && row.names.every(name => typeof name === 'string'))) throw new Error('invalid scan response');
  } catch {
    if (current()) { toast(t('vault.scan_failed_try_watchtower_again'), 'error'); _closeWatchtower(); }
    return;
  }
  if (!current()) return;
  const check = d.breach_check;
  const complete = check?.status === 'complete' && Number.isSafeInteger(check.total)
    && check.total >= 0 && check.checked === check.total;
  const sec = (title, desc, rows, cls, known = true) => `
    <div class="wt-section">
      <div class="wt-head ${cls}">${title} <span class="wt-n">${rows.length}</span></div>
      <div class="wt-desc">${desc}</div>
      ${rows.length ? rows.map(x => `<div class="wt-row">${x}</div>`).join('')
        : known ? `<div class="wt-clean">${_si('check')} ${_esc(t('vault.all_clear'))}</div>` : `<div class="wt-desc" role="status">${_esc(t('vault.breach_check_incomplete_try'))}</div>`}
    </div>`;
  list.innerHTML = `
    <div class="vault-wt" id="vault-wt">
      <div class="wt-bar">
        <button class="btn ic-btn-lbl" id="wt-back">${_si('chevron-left')} ${_esc(t('vault.back_to_vault'))}</button>
        <span class="wt-intro">${_esc(t('vault.watchtower_scans_your_saved'))}</span>
      </div>
      ${!complete && d.breached.length ? `<p class="wt-desc" role="status">${_esc(t('vault.breach_check_incomplete_these'))}</p>` : ''}
      ${sec(t('vault.wt_breached'), t('vault.wt_breached_desc'), d.breached.map(x => `${_esc(x.name)} <span class="wt-meta">${_esc(t('vault.seen_times', { count: formatNumber(x.count) }))}</span>`), 'bad', complete)}
      ${sec(t('vault.wt_reused'), t('vault.wt_reused_desc'), (d.reused || []).map(g => _esc(g.names.join(', '))), 'warn')}
      ${sec(t('vault.wt_weak'), t('vault.wt_weak_desc'), (d.weak || []).map(x => _esc(x.name)), 'warn')}
    </div>`;
  $('wt-back').addEventListener('click', _closeWatchtower);
}

// ── add / edit modal ───────────────────────────────────────────────────────

function openVaultForm(entry = null, returnFocus = document.activeElement) {
  _closeModal();
  const editing = !!entry;
  const ov = document.createElement('div');
  ov.className = 'modal-overlay vault-modal';
  ov.innerHTML = `
    <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="vf-title">
      <div class="modal-head">
        <span class="modal-title" id="vf-title">${_esc(editing ? t('vault.edit_secret') : t('vault.new_secret'))}</span>
        <button type="button" class="modal-close" id="vf-x" aria-label="${_esc(t('common.close'))}">✕</button>
      </div>
      <div class="vault-form">
        <div class="vform-field"><label for="vf-name">${_esc(t('common.name'))}</label>
          <input id="vf-name" class="settings-input vform-input" placeholder="${_esc(t('vault.e_g_chase_visa'))}"></div>
        <div class="vform-field"><label id="vf-type-label">${_esc(t('vault.type'))}</label>
          <div class="settings-input custom-select vform-input" id="vf-type" style="width:100%"></div></div>
        <div class="vform-divider"></div>
        <div id="vf-fields"></div>
        ${editing ? `<div class="vform-divider"></div>
        <div class="vform-field"><label>${_esc(t('vault.attachments'))}</label><div id="vf-attach"></div>
          <input type="file" id="vf-attach-input" hidden>
          <button type="button" class="btn" id="vf-attach-btn">${_esc(t('vault.attach_file'))}</button>
          <button type="button" class="btn" id="vf-attach-clear" hidden>${_esc(t('vault.discard_upload_retry'))}</button>
          <div id="vf-upload-status" role="status" hidden></div></div>
        <div class="vform-field" id="vf-share-result" hidden>
          <label for="vf-share-url">${_esc(t('vault.share_link'))}</label>
          <input id="vf-share-url" class="settings-input vform-input" readonly>
          <small>${_esc(t('vault.anyone_with_this_link_can_read_the'))}</small>
          <button type="button" class="btn" id="vf-share-copy">${_esc(t('vault.copy_link'))}</button>
        </div>` : ''}
      </div>
      <p id="vf-error" class="vault-form-error" role="alert" hidden></p>
      <button type="button" class="btn" id="vf-open-saved" hidden>${_esc(t('vault.open_saved_entry'))}</button>
      <div class="vault-form-actions">
        ${editing ? `<button type="button" class="btn danger" id="vf-del" style="margin-right:auto">${_esc(t('common.delete'))}</button>` : ''}
        ${editing ? `<button type="button" class="btn" id="vf-share" title="${_esc(t('vault.share_title'))}">${_esc(t('vault.share'))}</button><button type="button" class="btn" id="vf-share-revoke" title="${_esc(t('vault.revoke_link_title'))}">${_esc(t('vault.revoke_link'))}</button>` : ''}
        <button type="button" class="btn" id="vf-cancel">${_esc(t('common.cancel'))}</button>
        <button type="button" class="btn primary" id="vf-save">${_esc(editing ? t('common.save') : t('common.add'))}</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  _modalEl = ov;
  ov._entry = entry;
  ov._vaultId = _vaultId;

  const typeSel = ov.querySelector('#vf-type');
  typeSel.setAttribute('aria-labelledby', 'vf-type-label');
  const initial = editing ? _typeForEntry(entry) : 'login';
  populateDropdown(typeSel, _allTypes().map(t => ({ value: t.key, label: t.label })), initial);
  typeSel.addEventListener('change', () => {
    if (ov._saving || ov._acting || ov._openingSaved) return;
    _renderFields(_currentFields(), _editVals());
  });

  ov.querySelector('#vf-name').value = editing ? (entry.name || '') : '';
  _renderFields(_currentFields(), _editVals());

  ov.querySelector('#vf-x').onclick = _requestCloseModal;
  ov.querySelector('#vf-cancel').onclick = _requestCloseModal;
  ov.querySelector('#vf-save').onclick = () => _saveForm(editing);
  ov.querySelector('#vf-open-saved').onclick = () => _openSavedEntry(ov);
  ov.querySelector('#vf-del')?.addEventListener('click', () => _delFromForm(entry.id));
  if (editing) {
    _renderAttachments(entry.id, ov);
    ov.querySelector('#vf-attach-btn').onclick = () => ov._upload ? _uploadAttachment(ov) : ov.querySelector('#vf-attach-input').click();
    ov.querySelector('#vf-attach-input').onchange = e => {
      const file = e.target.files[0]; if (!file || ov._upload) return;
      ov._upload = { file, id: _createRequestId(), uncertain: false };
      _uploadAttachment(ov);
    };
    ov.querySelector('#vf-attach-clear').onclick = async () => {
      const token = _token;
      if (ov._acting || !await confirm(t('vault.this_file_may_already_be_attached')) || !_sameForm(ov, token)) return;
      ov._upload = null; ov.querySelector('#vf-attach-input').value = ''; _uploadStatus(ov);
      await _renderAttachments(entry.id, ov);
    };
    ov.querySelector('#vf-share').onclick = () => _shareItem(entry.id, ov);
    ov.querySelector('#vf-share-copy').onclick = () => _copyShare(ov);
    ov.querySelector('#vf-share-revoke').onclick = () => _formAction(ov, async current => {
      await _checkedVault(`/api/vault/${entry.id}/share`, { method: 'DELETE' });
      if (!current()) return;
      ov.querySelector('#vf-share-url').value = ''; ov.querySelector('#vf-share-result').hidden = true;
      toast(t('vault.share_link_revoked'), 'success');
    }, t('vault.revoke_unconfirmed'));
  }
  ov.addEventListener('mousedown', e => { if (e.target === ov) _requestCloseModal(); });
  _activateManagedModal(ov, returnFocus, ov.querySelector('#vf-name'));
}

function _uploadStatus(ov) {
  const pending = ov._upload;
  ov.querySelector('#vf-attach-btn').textContent = pending ? t('vault.retry_upload') : t('vault.attach_file');
  ov.querySelector('#vf-attach-clear').hidden = !pending;
  const status = ov.querySelector('#vf-upload-status');
  status.hidden = !pending;
  status.textContent = pending ? `${pending.file.name}: ${ov._acting ? t('vault.uploading') : t('vault.the_file_is_kept_here_retry_this')}` : '';
}

async function _uploadAttachment(ov) {
  if (!ov._upload) return;
  await _formAction(ov, async current => {
    const pending = ov._upload;
    pending.uncertain = true; _uploadStatus(ov);
    const body = new FormData(); body.append('file', pending.file); body.append('request_id', pending.id);
    const response = await _checkedVault(`/api/vault/${ov._entry.id}/attachments`, { method: 'POST', body });
    const saved = await response.json();
    if (!current()) return;
    if (!saved.id || typeof saved.filename !== 'string' || saved.size !== pending.file.size) throw new Error('invalid upload acknowledgment');
    ov._upload = null; ov.querySelector('#vf-attach-input').value = ''; _uploadStatus(ov);
    await _renderAttachments(ov._entry.id, ov);
  }, t('vault.upload_unconfirmed'));
  if (_modalEl === ov && ov._upload) _uploadStatus(ov);
}

async function _renderAttachments(eid, ov = _modalEl) {
  const box = ov?.querySelector('#vf-attach'), token = _token;
  if (!box || !_sameForm(ov, token)) return;
  const generation = ov._attachmentGeneration = (ov._attachmentGeneration || 0) + 1;
  const current = () => _sameForm(ov, token) && ov._attachmentGeneration === generation;
  box.innerHTML = `<div role="status">${_esc(t('vault.loading_attachments'))}</div>`;
  try {
    const response = await _checkedVault(`/api/vault/${eid}/attachments`);
    const list = await response.json();
    if (!current()) return;
    if (!Array.isArray(list)) throw new Error('invalid attachment list');
    box.innerHTML = list.length ? list.map(a => `
      <div class="vf-attach-row" data-id="${_esc(a.id)}">
        <span class="vf-attach-name">${_esc(a.filename)}</span>
        <span class="vf-attach-size">${_esc(t('vault.size_kb', { size: Math.max(1, Math.round(a.size / 1024)) }))}</span>
        <button type="button" class="act-btn" data-dl="${_esc(a.id)}" data-name="${_esc(a.filename)}">${_esc(t('vault.download'))}</button>
        <button type="button" class="act-btn danger" data-rm="${_esc(a.id)}">${_esc(t('common.remove'))}</button>
      </div>`).join('') : `<div class="vf-attach-empty">${_esc(t('common.none'))}</div>`;
    box.querySelectorAll('[data-dl]').forEach(button => button.onclick = () => _formAction(ov, async active => {
      const response = await _checkedVault(`/api/vault/attachments/${button.dataset.dl}`);
      const blob = await response.blob();
      if (!active()) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = button.dataset.name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, t('vault.download_failed')));
    box.querySelectorAll('[data-rm]').forEach(button => button.onclick = async () => {
      if (ov._acting || !await confirm(t('vault.remove_named', { name: button.closest('.vf-attach-row').querySelector('.vf-attach-name').textContent })) || !current()) return;
      await _formAction(ov, async active => {
        const response = await _vfetch(`/api/vault/attachments/${button.dataset.rm}`, { method: 'DELETE' });
        if (!response.ok && response.status !== 404) throw Object.assign(new Error('delete failed'), { status: response.status });
        if (active()) await _renderAttachments(eid, ov);
      }, t('vault.remove_unconfirmed'));
    });
    if (ov._acting || ov._saving) _formBusy(ov, true);
  } catch (error) {
    if (!current()) return;
    if (error.status === 403) { await _doLock(); toast(t('vault.vault_access_expired_unlock_and_2'), 'error'); return; }
    box.innerHTML = `<div role="alert">${_esc(t('vault.attachments_load_failed'))}</div><button type="button" class="btn" data-attach-retry>${_esc(t('vault.retry_attachments'))}</button>`;
    box.querySelector('[data-attach-retry]').onclick = () => _renderAttachments(eid, ov);
    if (ov._acting || ov._saving) _formBusy(ov, true);
  }
}

async function _copyShare(ov) {
  const token = _token, value = ov.querySelector('#vf-share-url').value;
  if (!_sameForm(ov, token) || !value) return;
  try {
    await navigator.clipboard.writeText(value);
    if (_sameForm(ov, token)) toast(t('vault.share_link_copied'), 'success');
  } catch {
    if (_sameForm(ov, token)) _formError(ov, t('vault.clipboard_share'));
  }
}

async function _shareItem(eid, ov = _modalEl) {
  await _formAction(ov, async current => {
    ov.querySelector('#vf-share-url').value = ''; ov.querySelector('#vf-share-result').hidden = true;
    const response = await _checkedVault(`/api/vault/${eid}/share`, { method: 'POST' });
    const result = await response.json();
    if (!current()) return;
    if (typeof result.url !== 'string' || !/^\/sv\/[^/#?]+#[^#]+$/.test(result.url)) throw new Error('invalid share acknowledgment');
    ov.querySelector('#vf-share-url').value = location.origin + result.url;
    ov.querySelector('#vf-share-result').hidden = false;
    await _copyShare(ov);
  }, t('vault.share_failed'));
}

function _sameForm(ov, token) {
  return _modalEl === ov && _unlocked && _token === token && ov._vaultId === _vaultId;
}

function _formError(ov, message) {
  const error = ov.querySelector('#vf-error');
  if (error) { error.textContent = message; error.hidden = !message; }
  const open = ov.querySelector('#vf-open-saved');
  if (open) open.hidden = !ov._conflict;
}

function _formBusy(ov, busy) {
  const controls = ov.querySelectorAll('.vault-form input, .vault-form textarea, .vault-form button, #vf-type, #vf-save, #vf-open-saved, #vf-del, #vf-share, #vf-share-revoke');
  if (busy) {
    ov._disabledBefore ||= new Map();
    controls.forEach(control => {
      if (!ov._disabledBefore.has(control)) ov._disabledBefore.set(control, control.disabled);
      control.disabled = true;
    });
  } else if (!busy && ov._disabledBefore) {
    ov._disabledBefore.forEach((disabled, control) => { control.disabled = disabled; });
    ov._disabledBefore = null;
  }
  const save = ov.querySelector('#vf-save');
  if (save) save.textContent = ov._saving ? t('common.saving') : ov._entry ? t('common.save') : t('common.add');
  const open = ov.querySelector('#vf-open-saved');
  if (open) open.textContent = ov._openingSaved ? t('vault.opening_saved_entry') : t('vault.open_saved_entry');
}

async function _requestCloseModal() {
  const ov = _modalEl;
  if (!ov) return;
  if (ov._createUncertain && !await confirm(t('vault.this_entry_may_already_be_saved'))) return;
  if (ov._upload?.uncertain && !await confirm(t('vault.this_file_may_already_be_attached_2'))) return;
  if (_modalEl !== ov) return;
  _closeModal();
  if (ov._createUncertain && _unlocked && ov._vaultId === _vaultId) await _loadEntries();
}

function _createRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function _openSavedEntry(ov) {
  if (ov._saving || ov._openingSaved || !ov._requestId) return;
  const token = _token;
  if (!_sameForm(ov, token)) return;
  const focusSource = ov.querySelector('#vf-open-saved');
  let ownsFocus = document.activeElement === focusSource;
  let focusDialog = null;
  const trackFocus = event => {
    if (event.target !== focusSource && event.target !== document.body && !focusDialog?.contains(event.target)) ownsFocus = false;
  };
  document.addEventListener('focusin', trackFocus, true);
  ov._openingSaved = true;
  _formBusy(ov, true);
  try {
    const response = await _vfetch(`/api/vault/requests/${encodeURIComponent(ov._requestId)}`);
    const entry = await response.json().catch(() => ({}));
    if (!_sameForm(ov, token)) return;
    if (!response.ok) {
      if (response.status === 403) {
        await _doLock();
        toast(t('vault.vault_access_expired_unlock_and_3'), 'error');
        return;
      }
      if ([404, 410].includes(response.status)) ov._conflict = false;
      throw new Error(typeof entry.detail === 'string' ? entry.detail : t('vault.could_not_open_the_saved_entry'));
    }
    document.removeEventListener('focusin', trackFocus, true);
    const decision = confirm(t('vault.discard_this_draft_and_open_the'));
    focusDialog = document.activeElement?.closest('.dialog-overlay');
    document.addEventListener('focusin', trackFocus, true);
    if (!await decision || !_sameForm(ov, token)) return;
    openVaultForm(entry);
  } catch (error) {
    if (_sameForm(ov, token)) _formError(ov, `${error.message || t('vault.could_not_open_the_saved_entry')}. your input is kept.`);
  } finally {
    document.removeEventListener('focusin', trackFocus, true);
    ov._openingSaved = false;
    if (_sameForm(ov, token)) {
      const restoreFocus = ownsFocus && [focusSource, document.body].includes(document.activeElement);
      _formBusy(ov, false);
      if (restoreFocus) (ov.querySelector('#vf-open-saved:not([hidden])') || ov.querySelector('#vf-save'))?.focus();
    }
  }
}

// the list or the lock screen was rebuilt under the focused control. step in only when focus fell
// to <body> or onto something now hidden, so focus a closed form gave back to its opener (or a click
// elsewhere in the meantime) stays put
function _settleFocus(target) {
  const active = document.activeElement;
  if (active && active !== document.body && active.isConnected && active.getClientRects().length) return;
  if (target?.getClientRects().length) target.focus();
}
const _entryButton = id => (id && $('vault-entry-list')?.querySelector(`[data-vault-open="${CSS.escape(id)}"]`))
  || $('vault-entry-list')?.querySelector('[data-vault-open]') || $('vault-new-btn');
// the entry below the deleted one, else the one above
function _entryAfter(id) {
  const at = _entries.findIndex(entry => entry.id === id);
  return at < 0 ? '' : (_entries[at + 1] || _entries[at - 1])?.id || '';
}

function _closeModal() {
  _revealGeneration++;
  if (_totpTimer) { clearInterval(_totpTimer); _totpTimer = null; }
  _modalFocusBoundary?.deactivate();
  _modalFocusBoundary?.destroy();
  _modalFocusBoundary = null;
  if (_modalEl) {
    _modalEl.querySelectorAll('input, textarea').forEach(input => { input.value = ''; });
    _modalEl._entry = null;
    _modalEl._upload = null;
    _modalEl.remove();
    _modalEl = null;
  }
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
    if (secs > 0) { secs -= 1; const s = document.getElementById('vtotp-secs'); if (s) s.textContent = t('vault.seconds_short', { count: secs }); return; }
    try {
      const d = await _vfetch(`/api/vault/${e.id}/totp`).then(r => r.json());
      if (d.code && code()) {
        code().textContent = d.code.slice(0, 3) + ' ' + d.code.slice(3);
        secs = d.seconds || 30;
        const s = document.getElementById('vtotp-secs'); if (s) s.textContent = t('vault.seconds_short', { count: secs });
      }
    } catch { /* locked/expired — leave dots */ }
  };
  tick();
  _totpTimer = setInterval(tick, 1000);
}

function _editVals() {
  const e = _modalEl?._entry;
  if (!e) return {};
  return { ..._entryFields(e), username: e.username || '' };
}

// fields for the currently-selected type, plus any extra keys an edited entry
// already carries (so nothing it stored gets hidden)
function _currentFields() {
  const tk = getDropdownValue(_modalEl.querySelector('#vf-type'));
  const t = _typeDef(tk);
  let keys = t?.custom ? (t.fields || []).map(f => f.key) : (t?.fields || ['notes']).slice();
  const e = _modalEl._entry;
  // keep any extra fields already stored on the entry (built-in or custom)
  if (e?.fields) for (const k of Object.keys(_entryFields(e))) if (!keys.includes(k)) keys.push(k);
  return keys.map(k => _defOf(k, tk));
}

function _fieldHtml(def) {
  const id = 'vf-f-' + def.key;
  const ph = def.placeholder || '';
  if (def.kind === 'textarea')
    return `<div class="vform-field"><label for="${id}">${_esc(def.label)}</label>
      <textarea id="${id}" class="settings-input vform-input" rows="2" placeholder="${_esc(ph)}"></textarea></div>`;
  if (def.kind === 'secretarea')
    return `<div class="vform-field"><label for="${id}">${_esc(def.label)}</label>
      <div class="vform-secretarea">
        <textarea id="${id}" class="settings-input vform-input" rows="5" autocomplete="off" spellcheck="false" placeholder="${_esc(ph)}"></textarea>
        <div class="vform-secret-actions">
          <button type="button" class="act-btn" data-reveal="${id}">${_esc(t('vault.show'))}</button>
          <button type="button" class="act-btn" data-copy="${id}">${_esc(t('common.copy'))}</button>
        </div>
      </div></div>`;
  if (def.kind === 'password' || def.kind === 'secret') {
    const gen = def.kind === 'password' ? `<button type="button" class="btn ic-btn-lbl" id="vf-gen">${_si('refresh')} ${_esc(t('vault.gen'))}</button>` : '';
    const strength = def.kind === 'password'
      ? `<div class="vault-strength" id="vf-strength" style="display:none">
          <span class="vault-strength-bar"><span class="vault-strength-fill"></span></span>
          <span class="vault-strength-label"></span></div>` : '';
    return `<div class="vform-field${def.half ? ' half' : ''}"><label for="${id}">${_esc(def.label)}</label>
      <div class="vform-pw">
        <input id="${id}" type="password" autocomplete="off" class="settings-input vform-input" placeholder="${_esc(ph)}">
        <button type="button" class="act-btn" data-reveal="${id}">${_esc(t('vault.show'))}</button>
        <button type="button" class="act-btn" data-copy="${id}">${_esc(t('common.copy'))}</button>
        ${gen}
      </div>${strength}</div>`;
  }
  return `<div class="vform-field${def.half ? ' half' : ''}"><label for="${id}">${_esc(def.label)}</label>
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
  box.innerHTML = html || `<div class="vform-empty">${_esc(t('vault.nothing_to_fill'))}</div>`;

  for (const def of defs) {
    const el = box.querySelector('#vf-f-' + def.key);
    if (el && values[def.key] != null) {
      el.value = values[def.key];
      // Text controls normalize line endings; retain unchanged stored bytes on edit.
      el._vaultOriginal = { value: String(values[def.key]), rendered: el.value };
    }
  }
  box.querySelector('#vf-gen')?.addEventListener('click', _genFormPw);
  box.querySelectorAll('[data-reveal]').forEach(b => b.onclick = () => {
    const inp = box.querySelector('#' + b.dataset.reveal);
    const secretArea = inp.tagName === 'TEXTAREA';
    const show = secretArea ? !inp.classList.contains('is-revealed') : inp.type === 'password';
    if (secretArea) inp.classList.toggle('is-revealed', show);
    else inp.type = show ? 'text' : 'password';
    b.textContent = show ? t('vault.hide') : t('vault.show');
  });
  box.querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => {
    const ov = _modalEl, token = _token;
    if (!ov || !_sameForm(ov, token)) return;
    const input = box.querySelector('#' + b.dataset.copy);
    const value = input.value === input._vaultOriginal?.rendered ? input._vaultOriginal.value : input.value;
    try {
      await navigator.clipboard.writeText(value);
      if (_sameForm(ov, token)) toast(t('common.copied'), 'success');
    } catch {
      if (_sameForm(ov, token)) {
        _formError(ov, t('vault.clipboard_field'));
        toast(t('vault.clipboard_unavailable_copy_the'), 'error');
      }
    }
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
    if (showBtn) showBtn.textContent = t('vault.hide');
    _showStrength(d.strength);
  } catch { toast(t('vault.couldn_t_generate_a_password_try'), 'error'); }
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
  box.querySelector('.vault-strength-label').textContent = s.label + (s.warning ? ': ' + s.warning : '');
}

async function _saveForm(editing) {
  const ov = _modalEl;
  if (!ov || ov._saving || ov._openingSaved || ov._acting || !_sameForm(ov, _token)) return;
  if (ov._upload) { _formError(ov, t('vault.pending_upload')); return; }
  const name = ov.querySelector('#vf-name').value.trim();
  const typeKey = getDropdownValue(ov.querySelector('#vf-type'));

  // passkeys are minted server-side (keypair never leaves the box)
  if (typeKey === 'passkey' && !editing) {
    const rp = (ov.querySelector('#vf-f-rp_id')?.value || '').trim();
    const user = (ov.querySelector('#vf-f-username')?.value || '').trim();
    if (!rp) { toast(t('vault.site_rp_id_required'), 'error'); return; }
    const r = await _vfetch('/api/vault/passkey/new', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ rp_id: rp, username: user }),
    });
    if (!r.ok) { toast(t('vault.passkey_create_failed_is_the_vault'), 'error'); return; }
    toast(t('vault.passkey_created'), 'success');
    _closeModal();
    await _loadEntries();
    _settleFocus($('vault-new-btn'));
    return;
  }

  const schema = _currentFields();
  const fields = {};
  let username = '';
  for (const def of schema) {
    const key = def.key;
    const el = ov.querySelector('#vf-f-' + key);
    const val = el ? (el.value === el._vaultOriginal?.rendered ? el._vaultOriginal.value : el.value) : '';
    if (key === 'username') { username = val; continue; }
    if (val) fields[key] = val;
  }
  // editing a passkey: keep the credential fields the form doesn't render
  if (editing && ov._entry?.type === 'passkey') {
    for (const k of ['private_key', 'public_key', 'credential_id', 'rp_id']) {
      if (ov._entry.fields?.[k] != null && fields[k] == null) fields[k] = ov._entry.fields[k];
    }
  }
  if (!name) { toast(t('vault.name_required'), 'error'); return; }
  if (!username && !Object.keys(fields).length) { toast(t('vault.fill_in_at_least_one_field'), 'error'); return; }
  const payload = {
    name, type: typeKey, fields, username,
    category: _TYPE_CATEGORY[typeKey] || _typeDef(typeKey)?.label || typeKey,
  };
  const id = editing ? ov._entry.id : null;
  const token = _token;
  const refreshDismissedForm = async () => {
    if (_unlocked && _token === token && _vaultId === ov._vaultId) await _loadEntries();
  };
  const earlierUncertainty = ov._createUncertain;
  const focusSource = ov.querySelector('#vf-save');
  let ownsFocus = document.activeElement === focusSource;
  const trackFocus = event => {
    if (event.target !== focusSource && event.target !== document.body) ownsFocus = false;
  };
  document.addEventListener('focusin', trackFocus, true);
  ov._saving = true;
  _formBusy(ov, true);
  _formError(ov, '');
  try {
    if (!editing) {
      payload.request_id = ov._requestId ||= _createRequestId();
      ov._createUncertain = true;
    }
    const response = await _vfetch(editing ? `/api/vault/${id}` : '/api/vault', {
      method: editing ? 'PATCH' : 'POST',
      headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!_sameForm(ov, token)) { await refreshDismissedForm(); return; }
    if (!response.ok) {
      const detail = (await response.json().catch(() => ({}))).detail;
      if (!_sameForm(ov, token)) { await refreshDismissedForm(); return; }
      if (response.status === 403) {
        await _doLock();
        toast(t('vault.vault_access_expired_unlock_and_4'), 'error');
        return;
      }
      if (!editing && [400, 422].includes(response.status)) ov._createUncertain = earlierUncertainty;
      if (!editing && response.status === 409 && detail?.entry_id) ov._conflict = true;
      if (response.status === 410) ov._conflict = false;
      const reason = typeof detail === 'string' ? detail : detail?.message;
      throw new Error(response.status < 500 && reason ? reason : t('vault.save_failed_status', { status: response.status }));
    }
    ov._createUncertain = false;
    toast(editing ? t('common.saved') : t('vault.entry_added'), 'success');
    _closeModal();
    await _loadEntries();
    // focus goes back to what opened the form: + new stays put, an edited row was rebuilt
    _settleFocus(editing ? _entryButton(id) : $('vault-new-btn'));
  } catch (error) {
    if (_sameForm(ov, token)) _formError(ov, `${error.message || t('vault.could_not_save_try_again')}. your input is kept.`);
    else await refreshDismissedForm();
  } finally {
    document.removeEventListener('focusin', trackFocus, true);
    ov._saving = false;
    if (_sameForm(ov, token)) {
      const restoreFocus = ownsFocus && [focusSource, document.body].includes(document.activeElement);
      _formBusy(ov, false);
      if (restoreFocus) focusSource?.focus();
    }
  }
}

async function _delFromForm(id) {
  const ov = _modalEl, token = _token;
  if (!ov || ov._acting || !await confirm(t('vault.delete_this_entry')) || !_sameForm(ov, token)) return;
  await _formAction(ov, async current => {
    const response = await _vfetch(`/api/vault/${id}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) throw Object.assign(new Error('delete failed'), { status: response.status });
    if (!current()) return;
    const next = _entryAfter(id);
    _closeModal(); await _loadEntries();
    _settleFocus(_entryButton(next));
  }, t('vault.delete_unconfirmed'));
}

// ── unlock / lock ────────────────────────────────────────────────────────────

async function _doUnlock() {
  if (_unlocking || !['setup', 'locked'].includes(_setupState)) return;
  const pw = $('vault-pw-input')?.value;
  if (!pw) { _unlockError(t('vault.enter_master_password')); return; }
  if (_setupState === 'setup') {
    if (pw.length < 12) { _unlockError(t('vault.use_at_least_12_characters')); return; }
    if (pw !== $('vault-pw-confirm')?.value) { _unlockError(t('vault.passwords_don_t_match')); return; }
  }
  const generation = ++_unlockGeneration;
  _unlocking = true;
  $('vault-unlock-btn').disabled = true;
  _unlockError('');
  try {
    const r = await fetch('/api/vault/unlock', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (generation !== _unlockGeneration) return;
    if (!r.ok) {
      const detail = (await r.json().catch(() => ({}))).detail;
      if (generation !== _unlockGeneration) return;
      _unlockError(typeof detail === 'string' ? detail : t('vault.unlock_failed_try_again'));
      await _refreshVaultSetup();
      return;
    }
    const j = await r.json();
    if (generation !== _unlockGeneration) return;
    if (j.requires_2fa) { await _do2fa(pw, j); return; }   // 8c — second factor needed
    _token = j.token; _vaultId = j.vault_id || 'default';
    _unlocked = true;
    $('vault-pw-input').value = '';
    $('vault-pw-confirm').value = '';
    await loadVaultView();
    _settleFocus(_entryButton());
  } catch {
    if (generation !== _unlockGeneration) return;
    _unlockError(t('vault.unlock_failed_try_again'));
    await _refreshVaultSetup();
  } finally {
    if (generation === _unlockGeneration) {
      _unlocking = false;
      $('vault-unlock-btn').disabled = !['setup', 'locked'].includes(_setupState);
    }
  }
}

// 8c — second-factor step after a correct password. prefers the authenticator app (TOTP);
// falls back to the passkey/security-key challenge if that's the only method enrolled.
async function _do2fa(pw, j) {
  const methods = j.methods || [];
  const vid = j.vault_id || _vaultId;  // target the vault being unlocked, not the active one
  if (methods.includes('totp')) {
    const code = await _promptCode(t('vault.enter_authenticator_code'));
    if (code == null) return;
    const r = await fetch('/api/vault/unlock/2fa/totp', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ vault_id: vid, password: pw, code }),
    });
    if (!r.ok) { toast(t('vault.wrong_authenticator_code'), 'error'); return; }
    const d = await r.json();
    _token = d.token; _vaultId = d.vault_id || vid; _unlocked = true;
    if ($('vault-pw-input')) $('vault-pw-input').value = '';
    await loadVaultView();
    _settleFocus(_entryButton());
    return;
  }
  if (methods.includes('passkey')) { await _do2faPasskey(pw, j, vid); return; }
  toast(t('vault.this_vault_needs_a_second_factor'), 'error');
}

// security-key (FIDO2) second factor: the /unlock response already handed us the challenge +
// allowed credentials (routes/vault.py:157-166), so get an assertion for the role=2fa key and
// verify it at /unlock/2fa. mirrors _bioUnlock, which is the proven biometric path.
async function _do2faPasskey(pw, j, vid) {
  if (!window.PublicKeyCredential) { toast(t('vault.security_keys_not_supported_in'), 'error'); return; }
  if (!j.credentials?.length || !j.challenge) { toast(t('vault.no_security_key_set_up_for_this'), 'error'); return; }
  try {
    const assertion = await navigator.credentials.get({ publicKey: {
      challenge: _b64ToBuf(j.challenge),
      timeout: 60000,
      userVerification: 'preferred',
      allowCredentials: j.credentials.map(c => ({ type: 'public-key', id: _b64ToBuf(c) })),
    } });
    const resp = assertion.response;
    const r = await fetch('/api/vault/unlock/2fa', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        vault_id: vid, password: pw,
        credential_id: _b64(assertion.rawId),
        authenticator_data: _b64(resp.authenticatorData),
        client_data_json: _b64(resp.clientDataJSON),
        signature: _b64(resp.signature),
      }),
    });
    if (!r.ok) { toast(t('vault.security_key_unlock_failed'), 'error'); return; }
    const d = await r.json();
    _token = d.token; _vaultId = d.vault_id || vid; _unlocked = true;
    if ($('vault-pw-input')) $('vault-pw-input').value = '';
    await loadVaultView();
    _settleFocus(_entryButton());
  } catch (e) { toast(t('vault.security_key_unlock_cancelled'), ''); }
}

// a tiny numeric-code prompt → resolves to the string or null
function _promptCode(title) {
  return new Promise(resolve => {
    const returnFocus = document.activeElement;
    const ov = document.createElement('div');
    ov.className = 'modal-overlay vault-modal';
    ov.innerHTML = `
      <div class="modal-card vault-modal-card" role="dialog" aria-modal="true" aria-labelledby="cc-title" style="max-width:320px">
        <div class="modal-head"><span class="modal-title" id="cc-title">${_esc(title)}</span></div>
        <div class="vault-form"><div class="vform-field">
          <label for="cc-code">${_esc(t('vault.verification_code'))}</label>
          <input id="cc-code" class="settings-input vform-input" inputmode="numeric" maxlength="6" placeholder="${_esc(t('vault.6_digits'))}"></div></div>
        <div class="vault-form-actions">
          <button type="button" class="btn" id="cc-cancel">${_esc(t('common.cancel'))}</button>
          <button type="button" class="btn primary" id="cc-ok">${_esc(t('vault.unlock'))}</button></div>
      </div>`;
    document.body.appendChild(ov);
    let focusBoundary = null;
    const done = v => {
      focusBoundary?.deactivate();
      focusBoundary?.destroy();
      ov.remove();
      resolve(v);
    };
    ov.querySelector('#cc-cancel').onclick = () => done(null);
    ov.querySelector('#cc-ok').onclick = () => done(ov.querySelector('#cc-code').value.trim());
    ov.querySelector('#cc-code').addEventListener('keydown', e => { if (e.key === 'Enter') done(ov.querySelector('#cc-code').value.trim()); });
    ov.addEventListener('mousedown', e => { if (e.target === ov) done(null); });
    focusBoundary = _activateTemporaryModal(ov, returnFocus, ov.querySelector('#cc-code'), done);
  });
}

async function _doLock() {
  _unlockGeneration++;
  _unlocking = false;
  $('vault-pw-input').value = '';
  $('vault-pw-confirm').value = '';
  _unlockError('');
  const locking = fetch('/api/vault/lock', { method: 'POST', headers: _token ? { 'X-Vault-Token': _token } : {} }).catch(() => {});
  _token = null;
  _entries = [];
  $('vault-entry-list')?.replaceChildren();
  _unlocked = false;
  _vaultId = 'default';
  _wtOpen = false;
  $('vault-watchtower-btn')?.classList.remove('active');
  _closeModal();
  await loadVaultView();
  _settleFocus($('vault-pw-input'));
  await locking;
}

// ── list ──────────────────────────────────────────────────────────────────────

async function _loadEntries(fetcher = fetch) {
  const list = $('vault-entry-list');
  if (!list) return;
  _wtOpen = false;
  _wtGeneration++;
  $('vault-watchtower-btn')?.classList.remove('active');
  const token = _token, vaultId = _vaultId;
  const generation = ++_entriesGeneration;
  const current = () => generation === _entriesGeneration && _unlocked && _token === token && _vaultId === vaultId;
  try {
    const response = await _vfetch('/api/vault', {}, fetcher);
    if (!response.ok) throw new Error(response.status === 403 ? t('vault.access_expired') : t('vault.request_failed', { status: response.status }));
    const entries = await response.json();
    if (!current()) return;
    _entries = entries;
    if (!_entries.length) { list.innerHTML = `<div class="page-empty">${_esc(t('vault.no_entries_hit_new'))}</div>`; return; }
    list.innerHTML = _entries.map(e => `
      <div class="vault-entry" data-id="${e.id}">
        <button type="button" class="vault-entry-main" data-vault-open="${e.id}" aria-label="${_esc(t('vault.open_named', { name: e.name }))}">
          <span class="vault-entry-name">${_esc(e.name)}${e.username ? ` <span class="vault-entry-user">${_esc(e.username)}</span>` : ''}</span>
          <span class="vault-entry-cat">${_esc(_typeLabel(e))}</span>
          <span class="vault-entry-grow"></span>
        </button>
        <button type="button" class="act-btn" data-vault-copy="${e.id}" aria-label="${_esc(t('vault.copy_secret_named', { name: e.name }))}">${_esc(t('common.copy'))}</button>
        <button type="button" class="act-btn danger" data-vault-delete="${e.id}" aria-label="${_esc(t('vault.delete_named', { name: e.name }))}">${_esc(t('vault.del'))}</button>
      </div>`).join('');
    list.querySelectorAll('[data-vault-open]').forEach(button => {
      button.addEventListener('click', () => window._vaultOpen(button.dataset.vaultOpen));
    });
    list.querySelectorAll('[data-vault-copy]').forEach(button => {
      button.addEventListener('click', () => window._vaultCopy(button.dataset.vaultCopy));
    });
    list.querySelectorAll('[data-vault-delete]').forEach(button => {
      button.addEventListener('click', () => window._vaultDel(button.dataset.vaultDelete));
    });
  } catch (error) {
    if (!current()) return;
    const state = document.createElement('div');
    state.className = 'vault-load-error';
    state.setAttribute('role', 'alert');
    const copy = document.createElement('p');
    copy.textContent = globalThis.navigator?.onLine === false
      ? t('vault.entries_offline')
      : t('vault.entries_load_failed', { message: error?.message || t('vault.entries_unavailable') });
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'btn';
    retry.textContent = t('vault.retry_loading_entries');
    retry.addEventListener('click', async () => {
      if (retry.disabled) return;
      retry.disabled = true;
      retry.setAttribute('aria-busy', 'true');
      await _loadEntries(fetcher);
    });
    const lock = document.createElement('button');
    lock.type = 'button';
    lock.className = 'btn';
    lock.textContent = t('vault.lock_vault');
    lock.addEventListener('click', _doLock);
    state.append(copy, retry, lock);
    list.replaceChildren(state);
  }
}

// which field to copy when you hit "copy" on a row
function _primarySecret(d) {
  const f = _entryFields(d);
  let tk = _builtinType(d.type) ? d.type
    : d.type === 'password' ? 'login'
    : d.type === 'api_key' ? 'apikey'
    : d.type === 'card' ? 'card'
    : d.type === 'note' ? 'note'
    : f.number ? 'card' : f.apikey ? 'apikey' : 'login';
  const k = PRIMARY[tk];
  return (k && f[k]) || f.password || d.value || Object.values(f).find(Boolean) || '';
}

export const _vaultInternals = { _entryFields, _typeForEntry, _primarySecret };

window._vaultOpen = async id => {
  const row = _entries.find(e => e.id === id);
  if (!row) return;
  const returnFocus = document.activeElement;
  const token = _token, vaultId = _vaultId, modal = _modalEl;
  const generation = ++_revealGeneration;
  const current = () => generation === _revealGeneration && _unlocked && _token === token && _vaultId === vaultId && _modalEl === modal
    && $('vault-entry-list')?.getClientRects().length;
  try {
    const response = await _vfetch(`/api/vault/${id}/reveal`);
    if (!current()) return;
    if (!response.ok) {
      if (response.status === 403) {
        await _doLock();
        toast(t('vault.vault_access_expired_unlock_and_2'), 'error');
        return;
      }
      throw new Error('reveal failed');
    }
    const d = await response.json();
    if (!current()) return;
    if (!d.fields || typeof d.fields !== 'object' || Array.isArray(d.fields)) throw new Error('invalid entry');
    openVaultForm({ id, name: row.name, category: row.category, username: row.username, type: row.type, fields: d.fields || {} }, returnFocus);
  } catch { if (current()) toast(t('vault.could_not_open_the_entry_try_again'), 'error'); }
};

window._vaultCopy = async id => {
  const token = _token, vaultId = _vaultId, modal = _modalEl;
  const generation = ++_revealGeneration;
  const current = () => _sameVault(token, vaultId) && generation === _revealGeneration && _modalEl === modal && $('vault-view')?.offsetParent;
  try {
    const response = await _checkedVault(`/api/vault/${id}/reveal`);
    const data = await response.json();
    if (!current()) return;
    if (!data.fields || typeof data.fields !== 'object' || Array.isArray(data.fields)) throw new Error('invalid reveal');
    const value = _primarySecret(data);
    if (typeof value !== 'string') throw new Error('invalid value');
    await navigator.clipboard.writeText(value);
    if (current()) toast(t('common.copied'), 'success');
  } catch (error) {
    if (!current()) return;
    if (error.status === 403) await _doLock();
    toast(t('vault.could_not_copy_unlock_if_needed'), 'error');
  }
};

window._vaultDel = async id => {
  const token = _token, vaultId = _vaultId;
  if (!await confirm(t('vault.delete_this_entry')) || !_sameVault(token, vaultId)) return;
  try {
    const response = await _vfetch(`/api/vault/${id}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) throw Object.assign(new Error('delete failed'), { status: response.status });
    if (!_sameVault(token, vaultId)) return;
    const next = _entryAfter(id);
    await _loadEntries();
    _settleFocus(_entryButton(next));
  } catch (error) {
    if (!_sameVault(token, vaultId)) return;
    if (error.status === 403) await _doLock();
    toast(t('vault.could_not_confirm_deletion_retry'), 'error');
  }
};

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
