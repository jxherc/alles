import { toast } from './util.js';
import { confirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _unlocked = false;
let _token = null;   // the unlock token; sent back on every vault request

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

export function initVault() {
  document.getElementById('vault-unlock-btn')?.addEventListener('click', _doUnlock);
  document.getElementById('vault-lock-btn')?.addEventListener('click', _doLock);
  document.getElementById('vault-add-btn')?.addEventListener('click', _addEntry);
  document.getElementById('vault-pw-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') _doUnlock();
  });
  document.getElementById('vault-new-cat')?.addEventListener('change', _onCatChange);
  document.getElementById('vault-new-cat-custom')?.addEventListener('input', _onCatChange);
  document.getElementById('vault-gen-btn')?.addEventListener('click', _genPw);
  document.getElementById('vault-new-value')?.addEventListener('input', _checkStrength);
  document.querySelectorAll('#vault-new-type .vts-btn').forEach(b => b.addEventListener('click', () => {
    document.getElementById('vault-new-type').dataset.type = b.dataset.t;
    document.querySelectorAll('#vault-new-type .vts-btn').forEach(x => x.classList.toggle('active', x === b));
    _applyType();
  }));
  _applyType();
}

function _curType() { return document.getElementById('vault-new-type')?.dataset.type || 'password'; }

function _applyType() {
  const t = _curType();
  document.querySelectorAll('.vault-f-pw').forEach(el => el.style.display = t === 'card' ? 'none' : '');
  document.querySelectorAll('.vault-f-card').forEach(el => el.style.display = t === 'card' ? '' : 'none');
  const v = document.getElementById('vault-new-value');
  if (v) v.placeholder = t === 'note' ? 'note text' : 'value / password';
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
  const sel = document.getElementById('vault-new-cat');
  if (!sel) return;
  let cats = ['password', 'api key', 'card', 'note', 'general'];
  try {
    const d = await _vfetch('/api/vault/categories').then(r => r.json());
    if (d.categories?.length) cats = d.categories;
  } catch {}
  const cur = sel.value;
  const opts = [...cats.map(c => ({ value: c, label: c })), { value: NEW_CAT, label: '+ new category…' }];
  populateDropdown(sel, opts, (cur && cats.includes(cur)) ? cur : cats[0]);
  _onCatChange();
}

function _onCatChange() {
  const sel = document.getElementById('vault-new-cat');
  const custom = document.getElementById('vault-new-cat-custom');
  const user = document.getElementById('vault-new-username');
  if (!sel) return;
  const isNew = sel.value === NEW_CAT;
  custom.style.display = isNew ? '' : 'none';
  if (isNew) custom.focus();
  // username field for credential-style categories
  const cat = isNew ? custom.value.trim() : sel.value;
  user.style.display = /password|login|account/i.test(cat) ? '' : 'none';
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
  const name = document.getElementById('vault-new-name')?.value.trim();
  const sel  = document.getElementById('vault-new-cat');
  const cat  = (sel.value === NEW_CAT
    ? document.getElementById('vault-new-cat-custom').value.trim()
    : sel.value) || 'general';
  const type = _curType();
  const g = id => document.getElementById(id)?.value.trim() || '';
  let fields, ok;
  if (type === 'card') {
    fields = { cardholder: g('vault-new-cardholder'), number: g('vault-new-number'), expiry: g('vault-new-expiry'), cvv: g('vault-new-cvv') };
    ok = fields.number;
  } else if (type === 'note') {
    fields = { notes: g('vault-new-value') };
    ok = fields.notes;
  } else {
    const userEl = document.getElementById('vault-new-username');
    fields = { password: g('vault-new-value'), url: '', notes: '' };
    ok = fields.password;
    var username = userEl.style.display !== 'none' ? userEl.value.trim() : '';
  }
  if (!name || !ok) { toast('name and value required', 'error'); return; }
  const r = await _vfetch('/api/vault', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, type, fields, category: cat, username: username || '' }),
  });
  if (!r.ok) { toast('failed — is vault unlocked?', 'error'); return; }
  ['vault-new-name','vault-new-value','vault-new-cat-custom','vault-new-username',
   'vault-new-cardholder','vault-new-number','vault-new-expiry','vault-new-cvv'].forEach(id => {
    const el = document.getElementById(id);
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
  return [f.password || d.value, f.url && '↗ ' + f.url].filter(Boolean).join('  ');
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
