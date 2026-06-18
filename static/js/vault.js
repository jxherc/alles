import { toast } from './util.js';
import { confirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _unlocked = false;
let _token = null;   // the unlock token; sent back on every vault request
let _schemas = {};   // category -> {fields:[...]}; drives which inputs show

// fetch wrapper that attaches this session's unlock token so the server can
// bind the request to our unlock (not just "someone unlocked recently")
function _vfetch(url, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (_token) headers['X-Vault-Token'] = _token;
  return fetch(url, { ...opts, headers });
}

export async function loadVaultView() {
  const locked   = document.getElementById('vault-locked');
  const unlocked = document.getElementById('vault-unlocked');
  const addBar   = document.getElementById('vault-add-bar');
  const lockBtn  = document.getElementById('vault-lock-btn');
  if (!locked || !unlocked) return;
  locked.style.display   = _unlocked ? 'none' : 'flex';
  unlocked.style.display = _unlocked ? 'flex' : 'none';
  if (addBar)  addBar.style.display  = _unlocked ? 'flex' : 'none';
  if (lockBtn) lockBtn.style.display = _unlocked ? ''     : 'none';
  if (_unlocked) { await _populateCats(); await _loadEntries(); }
}

const NEW_CAT = '__new__';

const $ = id => document.getElementById(id);

export function initVault() {
  $('vault-unlock-btn')?.addEventListener('click', _doUnlock);
  $('vault-lock-btn')?.addEventListener('click', _doLock);
  $('vault-add-btn')?.addEventListener('click', _addEntry);
  $('vault-pw-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') _doUnlock();
  });
  $('vault-new-cat')?.addEventListener('change', _onCatChange);
  $('vault-new-cat-custom')?.addEventListener('input', _onCatChange);
  $('vault-gen-btn')?.addEventListener('click', _genPw);
  $('vault-new-value')?.addEventListener('input', _checkStrength);
  // field-picker chips for a brand-new category
  document.querySelectorAll('#vault-new-schema .vsp-chip').forEach(c => c.addEventListener('click', () => {
    c.classList.toggle('active');
    _applySchema(_currentSchema());
  }));
}

// fields the form is currently set to collect
function _currentSchema() {
  const sel = $('vault-new-cat');
  if (sel && sel.value === NEW_CAT) {
    return [...document.querySelectorAll('#vault-new-schema .vsp-chip.active')].map(c => c.dataset.f);
  }
  return (_schemas[sel?.value]?.fields) || ['password', 'notes'];
}

function _typeFromFields(f) {
  if (f.includes('card')) return 'card';
  if (f.includes('notes') && !f.includes('password')) return 'note';
  return 'password';
}

function _show(id, on) { const el = $(id); if (el) el.style.display = on ? '' : 'none'; }

// show exactly the inputs the selected category's schema declares
function _applySchema(fields) {
  const card = fields.includes('card');
  _show('vault-new-username', fields.includes('username') && !card);
  document.querySelectorAll('.vault-f-pw').forEach(el => el.style.display = (fields.includes('password') && !card) ? '' : 'none');
  _show('vault-new-url', fields.includes('url') && !card);
  _show('vault-new-notes', fields.includes('notes') && !card);
  document.querySelectorAll('.vault-f-card').forEach(el => el.style.display = card ? '' : 'none');
}

async function _genPw() {
  try {
    const d = await fetch('/api/vault/generate?length=20').then(r => r.json());
    const inp = document.getElementById('vault-new-value');
    inp.value = d.password;
    inp.type = 'text';              // reveal the generated one so it can be reviewed
    _showStrength(d.strength);
  } catch { toast("couldn't generate a password — try again", 'error'); }
}

let _stTimer;
function _checkStrength() {
  clearTimeout(_stTimer);
  const pw = document.getElementById('vault-new-value').value;
  const box = document.getElementById('vault-strength');
  if (!pw) { if (box) box.style.display = 'none'; return; }
  _stTimer = setTimeout(async () => {
    try {
      const s = await fetch('/api/vault/strength', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      }).then(r => r.json());
      _showStrength(s);
    } catch {}
  }, 200);
}

function _showStrength(s) {
  const box = document.getElementById('vault-strength');
  if (!box) return;
  box.style.display = 'flex';
  const colors = ['var(--error)', 'var(--error)', '#d8a24a', 'var(--green)', 'var(--green)'];
  box.querySelector('.vault-strength-fill').style.width = ((s.score + 1) * 20) + '%';
  box.querySelector('.vault-strength-fill').style.background = colors[s.score] || 'var(--muted)';
  box.querySelector('.vault-strength-label').textContent = s.label + (s.warning ? ' — ' + s.warning : '');
}

async function _populateCats() {
  const sel = $('vault-new-cat');
  if (!sel) return;
  let cats = ['password', 'api key', 'card', 'note', 'general'];
  try {
    const d = await _vfetch('/api/vault/categories').then(r => r.json());
    if (d.categories?.length) cats = d.categories;
    _schemas = d.schemas || {};
  } catch {}
  const cur = sel.value;
  const opts = [...cats.map(c => ({ value: c, label: c })), { value: NEW_CAT, label: '+ new category…' }];
  populateDropdown(sel, opts, (cur && cats.includes(cur)) ? cur : cats[0]);
  _onCatChange();
}

function _onCatChange() {
  const sel = $('vault-new-cat');
  if (!sel) return;
  const isNew = sel.value === NEW_CAT;
  _show('vault-new-cat-custom', isNew);
  _show('vault-new-schema', isNew);
  if (isNew) $('vault-new-cat-custom').focus();
  _applySchema(_currentSchema());   // category drives which fields show
}

async function _doUnlock() {
  const pw = document.getElementById('vault-pw-input')?.value;
  if (!pw) { toast('enter master password', 'error'); return; }
  try {
    const r = await fetch('/api/vault/unlock', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (!r.ok) { toast('wrong password', 'error'); return; }
    _token = (await r.json()).token;
    _unlocked = true;
    document.getElementById('vault-pw-input').value = '';
    await loadVaultView();
  } catch (e) {
    toast('unlock failed', 'error');
  }
}

async function _doLock() {
  await fetch('/api/vault/lock', { method: 'POST' }).catch(() => {});
  _token = null;
  _unlocked = false;
  loadVaultView();
}

async function _loadEntries() {
  const list = document.getElementById('vault-entry-list');
  if (!list) return;
  try {
    const entries = await _vfetch('/api/vault').then(r => r.json());
    if (!entries.length) { list.innerHTML = '<div class="page-empty">no entries</div>'; return; }
    list.innerHTML = entries.map(e => `
      <div class="vault-entry" data-id="${e.id}">
        <span class="vault-entry-name">${_esc(e.name)}${e.username ? ` <span class="vault-entry-user">${_esc(e.username)}</span>` : ''}</span>
        <span class="vault-entry-cat">${_esc(e.category)}</span>
        <span class="vault-entry-value" id="vault-val-${e.id}">••••••••</span>
        ${e.username ? `<button class="act-btn" onclick="window._vaultCopyUser('${e.id}','${_esc(e.username).replace(/'/g, "\\'")}')">user</button>` : ''}
        <button class="act-btn" onclick="window._vaultReveal('${e.id}')">reveal</button>
        <button class="act-btn" onclick="window._vaultCopy('${e.id}')">copy</button>
        <button class="act-btn danger" onclick="window._vaultDel('${e.id}')">del</button>
      </div>`).join('');
  } catch (e) {
    toast('load failed — vault may be locked', 'error');
    _unlocked = false;
    loadVaultView();
  }
}

async function _addEntry() {
  const name = $('vault-new-name')?.value.trim();
  const sel  = $('vault-new-cat');
  const isNew = sel.value === NEW_CAT;
  const cat  = (isNew ? $('vault-new-cat-custom').value.trim() : sel.value) || 'general';
  const schema = _currentSchema();
  const type = _typeFromFields(schema);
  const g = id => $(id)?.value.trim() || '';
  let fields = {}, ok = false, username = '';
  if (type === 'card') {
    fields = { cardholder: g('vault-new-cardholder'), number: g('vault-new-number'), expiry: g('vault-new-expiry'), cvv: g('vault-new-cvv') };
    ok = !!fields.number;
  } else {
    if (schema.includes('password')) fields.password = g('vault-new-value');
    if (schema.includes('url')) fields.url = g('vault-new-url');
    if (schema.includes('notes')) fields.notes = g('vault-new-notes');
    ok = !!(fields.password || fields.notes);
    username = schema.includes('username') ? g('vault-new-username') : '';
  }
  if (!name || !ok) { toast('name and value required', 'error'); return; }
  if (isNew && cat) {   // remember the new category's field schema
    await _vfetch('/api/vault/category-schema', {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: cat, fields: schema }),
    }).catch(() => {});
  }
  const r = await _vfetch('/api/vault', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, type, fields, category: cat, username }),
  });
  if (!r.ok) { toast('failed — is vault unlocked?', 'error'); return; }
  ['vault-new-name','vault-new-value','vault-new-cat-custom','vault-new-username','vault-new-url','vault-new-notes',
   'vault-new-cardholder','vault-new-number','vault-new-expiry','vault-new-cvv'].forEach(id => {
    const el = $(id);
    if (el) el.value = '';
  });
  toast('entry added', 'success');
  await _populateCats();   // a new category becomes selectable
  await _loadEntries();
}

function _revealText(d) {
  const f = d.fields || {};
  if (d.type === 'card') {
    return [f.number, f.expiry && 'exp ' + f.expiry, f.cvv && 'cvv ' + f.cvv, f.cardholder].filter(Boolean).join('  ');
  }
  if (d.type === 'note') return f.notes || '';
  return [f.password || d.value, f.url && '↗ ' + f.url, f.notes && '— ' + f.notes].filter(Boolean).join('  ');
}
function _primarySecret(d) {
  const f = d.fields || {};
  if (d.type === 'card') return f.number || '';
  if (d.type === 'note') return f.notes || '';
  return f.password || d.value || '';
}

window._vaultReveal = async id => {
  const el = document.getElementById(`vault-val-${id}`);
  if (!el) return;
  if (el.dataset.revealed) { el.textContent = '••••••••'; delete el.dataset.revealed; return; }
  try {
    const d = await _vfetch(`/api/vault/${id}/reveal`).then(r => r.json());
    el.textContent = _revealText(d) || '(empty)';
    el.dataset.revealed = '1';
  } catch (e) { toast('reveal failed', 'error'); }
};

window._vaultCopy = async id => {
  try {
    const d = await _vfetch(`/api/vault/${id}/reveal`).then(r => r.json());
    await navigator.clipboard.writeText(_primarySecret(d));
    toast('copied', 'success');
  } catch { toast('copy failed', 'error'); }
};

window._vaultCopyUser = async (id, username) => {
  await navigator.clipboard.writeText(username);
  toast('username copied', 'success');
};

window._vaultDel = async id => {
  if (!await confirm('delete this entry?')) return;
  await _vfetch(`/api/vault/${id}`, { method: 'DELETE' });
  await _loadEntries();
};

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
