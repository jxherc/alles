import { toast } from './util.js';
import { confirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _unlocked = false;
let _token = null;     // the unlock token; sent back on every vault request
let _schemas = {};     // category -> {fields:[...]}; drives which inputs show
let _cats = ['password', 'api key', 'card', 'note', 'general'];
let _entries = [];     // last loaded list, so a row click can open the editor
let _modalEl = null;   // the open add/edit overlay, if any

const NEW_CAT = '__new__';
const $ = id => document.getElementById(id);

// what each field looks like in the form. order here = order in the chip picker.
const FIELD_DEFS = {
  username:   { label: 'username',        kind: 'text' },
  password:   { label: 'password',        kind: 'password' },
  url:        { label: 'website',         kind: 'text', placeholder: 'https://…' },
  notes:      { label: 'notes',           kind: 'textarea' },
  cardholder: { label: 'cardholder name', kind: 'text' },
  number:     { label: 'card number',     kind: 'text', placeholder: '4242 4242 4242 4242' },
  expiry:     { label: 'expiry',          kind: 'text', placeholder: 'MM/YY', half: true },
  cvv:        { label: 'cvv',             kind: 'text', placeholder: '•••', half: true },
  address:    { label: 'billing address', kind: 'textarea' },
};
const ALL_FIELDS = Object.keys(FIELD_DEFS);
const CARD_FIELDS = ['cardholder', 'number', 'expiry', 'cvv', 'address', 'notes'];

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
  if (_unlocked) { await _populateCats(); await _loadEntries(); }
}

export function initVault() {
  $('vault-unlock-btn')?.addEventListener('click', _doUnlock);
  $('vault-lock-btn')?.addEventListener('click', _doLock);
  $('vault-new-btn')?.addEventListener('click', () => openVaultForm());
  $('vault-pw-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') _doUnlock(); });
}

// legacy schemas used a single "card" marker — expand it into the real fields,
// drop anything we don't know how to render, and never come back empty
function _normSchema(fields) {
  const out = [];
  for (const f of fields || []) {
    if (f === 'card') { for (const k of CARD_FIELDS) if (!out.includes(k)) out.push(k); }
    else if (FIELD_DEFS[f] && !out.includes(f)) out.push(f);
  }
  return out.length ? out : ['password', 'notes'];
}

function _typeOf(fields) {
  if (fields.includes('number') || fields.includes('cardholder')) return 'card';
  if (fields.length && fields.every(f => f === 'notes')) return 'note';
  return 'password';
}

async function _populateCats() {
  try {
    const d = await _vfetch('/api/vault/categories').then(r => r.json());
    if (d.categories?.length) _cats = d.categories;
    _schemas = d.schemas || {};
  } catch {}
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
        <div class="vform-field"><label>category</label>
          <div class="custom-select" id="vf-cat" style="width:100%"></div></div>
        <input id="vf-cat-custom" class="settings-input vform-input" placeholder="new category name" style="display:none">
        <div class="vault-schema-pick" id="vf-schema" style="display:none">
          <span class="vsp-label">fields</span>
          ${ALL_FIELDS.map(k => `<button type="button" class="vsp-chip" data-f="${k}">${FIELD_DEFS[k].label}</button>`).join('')}
        </div>
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
  ov._entry = entry;   // stash for the helpers

  const catSel = ov.querySelector('#vf-cat');
  const opts = [..._cats.map(c => ({ value: c, label: c })), { value: NEW_CAT, label: '+ new category…' }];
  let initial = editing ? entry.category : (_cats[0] || 'password');
  if (!_cats.includes(initial)) initial = editing ? initial : _cats[0];
  // an entry can sit in a category we don't list (e.g. deleted later) — keep it selectable
  if (editing && !_cats.includes(initial)) opts.unshift({ value: initial, label: initial });
  populateDropdown(catSel, opts, initial);
  catSel.addEventListener('change', _onFormCat);
  ov.querySelector('#vf-cat-custom').addEventListener('input', _onFormCat);
  ov.querySelectorAll('#vf-schema .vsp-chip').forEach(c => c.addEventListener('click', () => {
    c.classList.toggle('active');
    _renderFields(_formSchema(), _editVals());
  }));

  ov.querySelector('#vf-name').value = editing ? (entry.name || '') : '';
  _onFormCat();

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

// the field set the form is currently collecting
function _formSchema() {
  const sel = _modalEl.querySelector('#vf-cat');
  let schema;
  if (sel.value === NEW_CAT) {
    schema = [..._modalEl.querySelectorAll('#vf-schema .vsp-chip.active')].map(c => c.dataset.f);
    schema = schema.length ? schema : [];
  } else {
    schema = _normSchema(_schemas[sel.value]?.fields);
  }
  // when editing, never hide a field the entry actually has
  const e = _modalEl._entry;
  if (e?.fields) {
    for (const k of Object.keys(e.fields)) if (FIELD_DEFS[k] && !schema.includes(k)) schema.push(k);
  }
  return schema;
}

function _onFormCat() {
  const sel = _modalEl.querySelector('#vf-cat');
  const isNew = sel.value === NEW_CAT;
  _modalEl.querySelector('#vf-cat-custom').style.display = isNew ? '' : 'none';
  _modalEl.querySelector('#vf-schema').style.display = isNew ? '' : 'none';
  _renderFields(_formSchema(), _editVals());
}

function _fieldHtml(key) {
  const def = FIELD_DEFS[key];
  const id = 'vf-f-' + key;
  const ph = def.placeholder || '';
  if (def.kind === 'textarea')
    return `<div class="vform-field"><label>${def.label}</label>
      <textarea id="${id}" class="settings-input vform-input" rows="2" placeholder="${ph}"></textarea></div>`;
  if (def.kind === 'password')
    return `<div class="vform-field"><label>${def.label}</label>
      <div class="vform-pw">
        <input id="${id}" type="password" class="settings-input vform-input" placeholder="${ph}">
        <button type="button" class="act-btn" data-reveal="${id}">show</button>
        <button type="button" class="act-btn" data-copy="${id}">copy</button>
        <button type="button" class="btn" id="vf-gen">⚙ gen</button>
      </div>
      <div class="vault-strength" id="vf-strength" style="display:none">
        <span class="vault-strength-bar"><span class="vault-strength-fill"></span></span>
        <span class="vault-strength-label"></span></div></div>`;
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
  box.innerHTML = html || '<div class="vform-empty">pick at least one field above</div>';

  for (const k of schema) {
    const el = box.querySelector('#vf-f-' + k);
    if (el && values[k] != null) el.value = values[k];
  }
  // wire the password controls if a password field is present
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
  const sel = ov.querySelector('#vf-cat');
  const isNew = sel.value === NEW_CAT;
  const cat = (isNew ? ov.querySelector('#vf-cat-custom').value.trim() : sel.value) || 'general';
  const schema = _formSchema();
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
  if (isNew && cat) {
    await _vfetch('/api/vault/category-schema', {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: cat, fields: schema }),
    }).catch(() => {});
  }
  const body = JSON.stringify({ name, type: _typeOf(schema), fields, category: cat, username });
  const id = editing ? ov._entry.id : null;
  const r = await _vfetch(editing ? `/api/vault/${id}` : '/api/vault', {
    method: editing ? 'PATCH' : 'POST',
    headers: { 'content-type': 'application/json' }, body,
  });
  if (!r.ok) { toast('save failed — is the vault still unlocked?', 'error'); return; }
  toast(editing ? 'saved' : 'entry added', 'success');
  _closeModal();
  await _populateCats();
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
        <span class="vault-entry-cat">${_esc(e.category)}</span>
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

function _primarySecret(d) {
  const f = d.fields || {};
  if (d.type === 'card') return f.number || '';
  if (d.type === 'note') return f.notes || '';
  return f.password || d.value || '';
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
