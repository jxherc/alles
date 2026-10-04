import { confirm } from './dialog.js';
import { t } from './i18n.js';

const PREFIX = 'alles.note.pending.v1:';
let busy = false;
let generation = 0;

async function pendingStore() {
  const response = await fetch('/api/vault-md/create-scope', { cache: 'no-store' });
  if (!response.ok) throw new Error('note recovery could not load; try again');
  const { scopes, vault_scopes: vaultScopes } = await response.json();
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error('note recovery could not load; try again');
  if (!Array.isArray(vaultScopes) || !vaultScopes.length || vaultScopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error('note destination could not load; try again');
  const keys = scopes.map(scope => PREFIX + scope);
  let pending = null;
  for (const key of keys) {
    const raw = sessionStorage.getItem(key);
    if (!raw) continue;
    const value = JSON.parse(raw);
    if (typeof value?.text !== 'string' || typeof value.body?.path !== 'string' || typeof value.body?.content !== 'string' || typeof value.body?.request_id !== 'string' || value.body?.unique !== true) throw new Error('could not read the pending note');
    pending ||= value;
  }
  return {
    pending,
    vault: vaultScopes[0],
    put(value) {
      const raw = JSON.stringify(value);
      sessionStorage.setItem(keys[0], raw);
      if (sessionStorage.getItem(keys[0]) !== raw) throw new Error('could not keep this note for retry');
    },
    clear() { for (const key of keys) sessionStorage.removeItem(key); },
  };
}

function requestId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function submit(store, pending) {
  if (!/^[a-f0-9]{64}$/.test(pending.body.expected_vault || '')) throw new Error('this older pending note has no verified vault; check the original note before discarding this retry');
  const response = await fetch('/api/vault-md/file', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pending.body),
  });
  let data;
  try { data = await response.json(); }
  catch { throw new Error('could not confirm note'); }
  if (!response.ok) {
    const error = new Error(data.detail?.message || (typeof data.detail === 'string' ? data.detail : 'could not confirm note'));
    error.path = data.detail?.path || '';
    error.status = response.status;
    throw error;
  }
  if (data.created !== true || data.request_id !== pending.body.request_id || typeof data.path !== 'string' || !data.path) throw new Error('could not confirm note');
  // A confirmed server save remains successful if browser cleanup fails. Any
  // retained receipt can only reconfirm that same note on the next recovery.
  try { store.clear(); } catch { /* Keep the verified result and clear matching input. */ }
  return data;
}

export async function saveNote(text, path, { preserveContent = false } = {}) {
  if (preserveContent && !text.trim()) throw new Error('cannot import empty text');
  const content = preserveContent ? text : `${text.trim()}\n`;
  if (busy) throw new Error('a note is already being saved');
  busy = true; ++generation;
  try {
    const store = await pendingStore();
    const pending = store.pending || { text, body: { path, content, unique: true, request_id: requestId(), expected_vault: store.vault } };
    if (pending.text !== text || pending.body.content !== content || pending.body.path !== path) throw new Error('finish the pending note below before saving another');
    store.put(pending);
    return await submit(store, pending);
  } finally { busy = false; }
}

export async function showNoteRecovery(host, onSaved, onOpen, focusTarget = () => document.getElementById('today-capture-input')) {
  if (busy) return;
  const run = ++generation;
  let store;
  try { store = await pendingStore(); }
  catch (error) {
    if (run !== generation || !host.isConnected) return;
    const restoreFocus = host.querySelector('.note-recovery-error')?.contains(document.activeElement);
    if (!host.querySelector('.note-saved-open')) host.replaceChildren();
    host.querySelector('.note-recovery-error')?.remove();
    const notice = document.createElement('div'); notice.className = 'note-recovery-error';
    const status = document.createElement('p'); status.textContent = error.message;
    status.setAttribute('role', 'status');
    const retry = document.createElement('button'); retry.className = 'btn'; retry.type = 'button'; retry.textContent = 'retry note recovery';
    retry.onclick = () => showNoteRecovery(host, onSaved, onOpen, focusTarget);
    notice.append(status, retry); host.append(notice);
    if (restoreFocus && host.getClientRects().length) retry.focus();
    return;
  }
  if (run !== generation || !host.isConnected) return;
  const errorNotice = host.querySelector('.note-recovery-error');
  const restoreFocus = errorNotice?.contains(document.activeElement);
  errorNotice?.remove();
  if (store.pending && host.dataset.savedNoteRequest === store.pending.body.request_id && host.querySelector('.note-saved-open')) {
    let clear = host.querySelector('.note-clear-saved');
    if (!clear) {
      clear = document.createElement('button'); clear.className = 'btn note-clear-saved'; clear.type = 'button'; clear.textContent = 'clear saved retry';
      host.append(clear);
    }
    clear.onclick = () => {
      if (busy) return;
      try {
        store.clear(); clear.remove();
        host.querySelector('p').textContent = t('home.note_saved');
        if (host.getClientRects().length) host.querySelector('.note-saved-open')?.focus();
      } catch { host.querySelector('p').textContent = 'note saved; its browser recovery copy could not be cleared'; }
    };
    if (restoreFocus && host.getClientRects().length) host.querySelector('.note-saved-open').focus();
    return;
  }
  host.querySelector('.note-resume')?.remove();
  if (!store.pending) {
    if (!host.querySelector('.note-saved-open')) host.replaceChildren();
    const target = host.querySelector('.note-saved-open') || focusTarget();
    if (restoreFocus && target?.getClientRects().length) target.focus();
    return;
  }
  const pending = store.pending;
  const notice = document.createElement('div'); notice.className = 'capture-resume note-resume';
  notice.innerHTML = '<p role="status">a note still needs confirmation</p><details class="capture-source"><summary>original note</summary><pre></pre></details><div class="capture-actions"><button class="btn note-retry" type="button">retry note save</button><button class="btn note-open" type="button" hidden>open existing note</button><button class="btn note-discard" type="button">discard pending save</button></div>';
  notice.querySelector('pre').textContent = pending.text;
  const status = notice.querySelector('p');
  const retry = notice.querySelector('.note-retry');
  const open = notice.querySelector('.note-open');
  const discard = notice.querySelector('.note-discard');
  const lock = value => { for (const button of notice.querySelectorAll('button')) button.disabled = value; };
  retry.onclick = async () => {
    if (busy) return;
    const focusBefore = document.activeElement;
    const hadFocus = notice.contains(focusBefore);
    const returnFocus = () => hadFocus && (document.activeElement === focusBefore || document.activeElement === document.body || notice.contains(document.activeElement));
    busy = true; ++generation; lock(true); status.textContent = 'checking note save…';
    try {
      const saved = await submit(store, pending);
      const restore = returnFocus();
      notice.remove();
      onSaved(saved, pending.text, restore, pending.body);
    } catch (error) {
      status.textContent = `${error.message}; your original text is kept here`;
      open.hidden = !error.path || error.status === 410;
      if (error.path) open.onclick = async () => {
        try { await onOpen(error.path); }
        catch { status.textContent = 'could not open the existing note; try again'; }
      };
    } finally {
      busy = false; lock(false);
      if (notice.isConnected && returnFocus()) retry.focus();
    }
  };
  discard.onclick = async () => {
    if (busy || !(await confirm('the note may already be saved. discarding stops retries and does not delete it. discard this pending save?'))) return;
    if (busy || !notice.isConnected) return;
    try {
      store.clear(); ++generation; notice.remove();
      focusTarget()?.focus();
    } catch (error) { status.textContent = `could not discard the pending save: ${error.message}`; }
  };
  host.replaceChildren(notice);
  if (restoreFocus && host.getClientRects().length) retry.focus();
}
