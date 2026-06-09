import { toast } from './util.js';
import { confirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _unlocked = false;

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
}

async function _populateCats() {
  const sel = document.getElementById('vault-new-cat');
  if (!sel) return;
  let cats = ['password', 'api key', 'card', 'note', 'general'];
  try {
    const d = await fetch('/api/vault/categories').then(r => r.json());
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
    _unlocked = true;
    document.getElementById('vault-pw-input').value = '';
    await loadVaultView();
  } catch (e) {
    toast('unlock failed', 'error');
  }
}

async function _doLock() {
  await fetch('/api/vault/lock', { method: 'POST' }).catch(() => {});
  _unlocked = false;
  loadVaultView();
}

async function _loadEntries() {
  const list = document.getElementById('vault-entry-list');
  if (!list) return;
  try {
    const entries = await fetch('/api/vault').then(r => r.json());
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
  const val  = document.getElementById('vault-new-value')?.value.trim();
  const sel  = document.getElementById('vault-new-cat');
  const cat  = (sel.value === NEW_CAT
    ? document.getElementById('vault-new-cat-custom').value.trim()
    : sel.value) || 'general';
  const userEl = document.getElementById('vault-new-username');
  const username = userEl.style.display !== 'none' ? userEl.value.trim() : '';
  if (!name || !val) { toast('name and value required', 'error'); return; }
  const r = await fetch('/api/vault', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, value: val, category: cat, username }),
  });
  if (!r.ok) { toast('failed — is vault unlocked?', 'error'); return; }
  ['vault-new-name','vault-new-value','vault-new-cat-custom','vault-new-username'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  toast('entry added', 'success');
  await _populateCats();   // a new category becomes selectable
  await _loadEntries();
}

window._vaultReveal = async id => {
  const el = document.getElementById(`vault-val-${id}`);
  if (!el) return;
  if (el.dataset.revealed) { el.textContent = '••••••••'; delete el.dataset.revealed; return; }
  try {
    const { value } = await fetch(`/api/vault/${id}/reveal`).then(r => r.json());
    el.textContent = value;
    el.dataset.revealed = '1';
  } catch (e) { toast('reveal failed', 'error'); }
};

window._vaultCopy = async id => {
  const el = document.getElementById(`vault-val-${id}`);
  let val = el?.dataset.revealed ? el.textContent : null;
  if (!val) {
    try { val = (await fetch(`/api/vault/${id}/reveal`).then(r => r.json())).value; } catch { return; }
  }
  await navigator.clipboard.writeText(val);
  toast('copied', 'success');
};

window._vaultCopyUser = async (id, username) => {
  await navigator.clipboard.writeText(username);
  toast('username copied', 'success');
};

window._vaultDel = async id => {
  if (!await confirm('delete this entry?')) return;
  await fetch(`/api/vault/${id}`, { method: 'DELETE' });
  await _loadEntries();
};

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
