import { requestId } from './request_id.js';
import { confirm } from './dialog.js';
import { t } from './i18n.js';

const PREFIX = 'alles.note.pending.v1:';
let busy = false;
let generation = 0;

async function pendingStore() {
  const response = await fetch('/api/vault-md/create-scope', { cache: 'no-store' });
  if (!response.ok) throw new Error(t('note.recovery_load_failed'));
  const { scopes, vault_scopes: vaultScopes } = await response.json();
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error(t('note.recovery_load_failed'));
  if (!Array.isArray(vaultScopes) || !vaultScopes.length || vaultScopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error(t('note.destination_load_failed'));
  const keys = scopes.map(scope => PREFIX + scope);
  let pending = null;
  for (const key of keys) {
    const raw = sessionStorage.getItem(key);
    if (!raw) continue;
    const value = JSON.parse(raw);
    if (typeof value?.text !== 'string' || typeof value.body?.path !== 'string' || typeof value.body?.content !== 'string' || typeof value.body?.request_id !== 'string' || value.body?.unique !== true) throw new Error(t('note.pending_unreadable'));
    pending ||= value;
  }
  return {
    pending,
    vault: vaultScopes[0],
    put(value) {
      const raw = JSON.stringify(value);
      sessionStorage.setItem(keys[0], raw);
      if (sessionStorage.getItem(keys[0]) !== raw) throw new Error(t('note.keep_failed'));
    },
    clear() { for (const key of keys) sessionStorage.removeItem(key); },
  };
}


async function submit(store, pending) {
  if (!/^[a-f0-9]{64}$/.test(pending.body.expected_vault || '')) throw new Error(t('note.no_verified_vault'));
  const response = await fetch('/api/vault-md/file', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pending.body),
  });
  let data;
  try { data = await response.json(); }
  catch { throw new Error(t('note.confirm_failed')); }
  if (!response.ok) {
    const error = new Error(data.detail?.message || (typeof data.detail === 'string' ? data.detail : t('note.confirm_failed')));
    error.path = data.detail?.path || '';
    error.status = response.status;
    throw error;
  }
  if (data.created !== true || data.request_id !== pending.body.request_id || typeof data.path !== 'string' || !data.path) throw new Error(t('note.confirm_failed'));
  // A confirmed server save remains successful if browser cleanup fails. Any
  // retained receipt can only reconfirm that same note on the next recovery.
  try { store.clear(); } catch { /* Keep the verified result and clear matching input. */ }
  return data;
}

export async function saveNote(text, path, { preserveContent = false, sourceKey = '' } = {}) {
  if (preserveContent && !text.trim()) throw new Error(t('note.import_empty'));
  const content = preserveContent ? text : `${text.trim()}\n`;
  if (busy) throw new Error(t('note.already_saving'));
  busy = true; ++generation;
  try {
    const store = await pendingStore();
    const pending = store.pending || { text, ...(sourceKey ? { sourceKey } : {}), body: { path, content, unique: true, request_id: requestId(), expected_vault: store.vault } };
    if (pending.text !== text || pending.body.content !== content || pending.body.path !== path || (pending.sourceKey || '') !== sourceKey) throw new Error(t('note.finish_pending'));
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
    const retry = document.createElement('button'); retry.className = 'btn'; retry.type = 'button'; retry.textContent = t('note.retry_recovery');
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
      clear = document.createElement('button'); clear.className = 'btn note-clear-saved'; clear.type = 'button'; clear.textContent = t('note.clear_saved_retry');
      host.append(clear);
    }
    clear.onclick = () => {
      if (busy) return;
      try {
        store.clear(); clear.remove();
        host.querySelector('p').textContent = t('home.note_saved');
        if (host.getClientRects().length) host.querySelector('.note-saved-open')?.focus();
      } catch { host.querySelector('p').textContent = t('note.clear_failed'); }
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
  notice.innerHTML = '<p role="status"></p><details class="capture-source"><summary></summary><pre></pre></details><div class="capture-actions"><button class="btn note-retry" type="button"></button><button class="btn note-open" type="button" hidden></button><button class="btn note-discard" type="button"></button></div>';
  notice.querySelector('p').textContent = t('note.needs_confirmation');
  notice.querySelector('summary').textContent = t('note.original');
  notice.querySelector('.note-retry').textContent = t('note.retry_save');
  notice.querySelector('.note-open').textContent = t('note.open_existing');
  notice.querySelector('.note-discard').textContent = t('shell.andromeda.discard_pending_save');
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
    busy = true; ++generation; lock(true); status.textContent = t('note.checking');
    try {
      const saved = await submit(store, pending);
      const restore = returnFocus();
      notice.remove();
      onSaved(saved, pending.text, restore, pending.body, pending.sourceKey);
    } catch (error) {
      status.textContent = t('note.error_kept', { message: error.message });
      open.hidden = !error.path || error.status === 410;
      if (error.path) open.onclick = async () => {
        try { await onOpen(error.path); }
        catch { status.textContent = t('note.open_failed'); }
      };
    } finally {
      busy = false; lock(false);
      if (notice.isConnected && returnFocus()) retry.focus();
    }
  };
  discard.onclick = async () => {
    if (busy || !(await confirm(t('note.discard_confirm')))) return;
    if (busy || !notice.isConnected) return;
    try {
      store.clear(); ++generation; notice.remove();
      focusTarget()?.focus();
    } catch (error) { status.textContent = t('note.discard_failed', { message: error.message }); }
  };
  host.replaceChildren(notice);
  if (restoreFocus && host.getClientRects().length) retry.focus();
}
