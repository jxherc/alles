import { toast } from './util.js';
import { isIncognitoMode } from './modes.js?v=256';

let _attachments = [];   // [{id, name, type, size, status?, progress?, previewUrl?, file?}]
const _requests = new Map();
const _discardedUploads = new Set();
const CANCELLATION_KEY = 'alles_pending_upload_cancellations';

function _storedCancellations() {
  try {
    const value = JSON.parse(localStorage.getItem(CANCELLATION_KEY) || '[]');
    return Array.isArray(value) ? value.filter(id => typeof id === 'string') : [];
  } catch { return []; }
}

function _rememberCancellation(id) {
  try {
    localStorage.setItem(CANCELLATION_KEY, JSON.stringify([...new Set([..._storedCancellations(), id])]));
  } catch {}
}

function _forgetCancellation(id) {
  try {
    const remaining = _storedCancellations().filter(value => value !== id);
    if (remaining.length) localStorage.setItem(CANCELLATION_KEY, JSON.stringify(remaining));
    else localStorage.removeItem(CANCELLATION_KEY);
  } catch {}
}

const _pause = delay => new Promise(resolve => setTimeout(resolve, delay));

async function _cancelUpload(item) {
  const id = item?.serverId || item?.id;
  if (!id || String(id).startsWith('pending-')) return true;
  // The random upload id contains no attachment content. Keep it until the
  // server confirms deletion, including for incognito uploads.
  _rememberCancellation(id);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(`/api/uploads/${encodeURIComponent(id)}?pending=true`, {
        method: 'DELETE',
        keepalive: true,
      });
      // A pending cancellation creates its tombstone even when the upload POST
      // has not arrived yet, so a 404 is transient or an incompatible server.
      if (response.ok) {
        _forgetCancellation(id);
        return true;
      }
    } catch {}
    await _pause(150 * (attempt + 1));
  }
  return false;
}

async function _resumeUploadCancellations() {
  await Promise.all(_storedCancellations().map(serverId => _cancelUpload({ serverId })));
}

function _newUploadId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function getAttachments() { return _attachments.filter(a => !a.status).map(a => a.id); }
// A failed upload remains visible with a retry/remove action. It must block Send
// just like an in-flight upload so the message cannot silently omit the file.
export function hasPendingAttachments() { return _attachments.some(a => Boolean(a.status)); }

function _release(item) {
  if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl);
  _requests.get(item?.id)?.abort();
  _requests.delete(item?.id);
}

export function clearAttachments() {
  _attachments.forEach(item => {
    if (item.status === 'uploading') {
      _discardedUploads.add(item.id);
      _requests.get(item.id)?.abort();
      _requests.delete(item.id);
      void _cancelUpload(item);
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      return;
    }
    _release(item);
  });
  _attachments = [];
  _render();
}

export async function discardAttachments() {
  const snapshot = [..._attachments];
  const cancellations = [];
  snapshot.forEach(item => {
    if (item.status === 'uploading') {
      _discardedUploads.add(item.id);
      _requests.get(item.id)?.abort();
      _requests.delete(item.id);
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      cancellations.push(_cancelUpload(item));
      return;
    }
    _release(item);
    if (item.serverId || !item.status) cancellations.push(_cancelUpload(item));
  });
  _attachments = [];
  _render();
  await Promise.all(cancellations);
}

export async function attachFile(file) {
  const uploadId = _newUploadId();
  const localId = `pending-${uploadId}`;
  const incognito = isIncognitoMode();
  const pending = {
    id: localId,
    serverId: uploadId,
    incognito,
    name: file.name || 'clipboard image',
    type: file.type || '',
    size: file.size || 0,
    status: 'uploading',
    progress: 0,
    previewUrl: (file.type || '').startsWith('image/') ? URL.createObjectURL(file) : '',
    file,
  };
  _attachments.push(pending);
  _render();
  const fd = new FormData();
  fd.append('file', file);
  fd.append('upload_id', uploadId);
  try {
    const url = `/api/uploads${incognito ? '?incognito=true' : ''}`;
    const data = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      _requests.set(localId, xhr);
      xhr.open('POST', url);
      xhr.responseType = 'json';
      xhr.upload.addEventListener('progress', event => {
        if (!event.lengthComputable) return;
        const progress = Math.min(99, Math.round(event.loaded / event.total * 100));
        _attachments = _attachments.map(item => item.id === localId
          ? { ...item, progress }
          : item);
        _render();
      });
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response || {});
        else reject(new Error('upload failed'));
      });
      xhr.addEventListener('error', () => reject(new Error('upload failed')));
      xhr.addEventListener('abort', () => reject(new DOMException('upload cancelled', 'AbortError')));
      xhr.send(fd);
    });
    _requests.delete(localId);
    if (_discardedUploads.delete(localId)) {
      await _cancelUpload({ serverId: data?.id || uploadId, incognito });
      return null;
    }
    if (!data?.id) {
      _markFailed(localId);
      toast('upload failed', 'error');
      return null;
    }
    _attachments = _attachments.map(item => item.id === localId
      ? { ...data, incognito, previewUrl: item.previewUrl }
      : item);
    _render();
    return data;
  } catch (e) {
    _requests.delete(localId);
    const discarded = _discardedUploads.delete(localId);
    if (discarded) return null;
    _markFailed(localId);
    toast('upload failed', 'error');
    return null;
  }
}

async function removeAttachment(id) {
  const item = _attachments.find(a => a.id === id);
  if (item?.status === 'uploading') {
    _discardedUploads.add(item.id);
    _requests.get(item.id)?.abort();
    _requests.delete(item.id);
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    _attachments = _attachments.filter(a => a.id !== id);
    _render();
    if (!await _cancelUpload(item)) toast('upload cancellation will retry', 'error');
    return;
  }
  _release(item);
  if (item?.serverId || !String(id).startsWith('pending-')) {
    if (!await _cancelUpload(item || { id })) toast('attachment cleanup will retry', 'error');
  }
  _attachments = _attachments.filter(a => a.id !== id);
  _render();
}

async function retryAttachment(id) {
  const failed = _attachments.find(a => a.id === id && a.status === 'failed' && a.file);
  if (!failed) return;
  _release(failed);
  await _cancelUpload(failed);
  _attachments = _attachments.filter(a => a.id !== id);
  await attachFile(failed.file);
}

function _markFailed(id) {
  _attachments = _attachments.map(item => item.id === id ? { ...item, status: 'failed' } : item);
  _render();
}

function _render() {
  const container = document.getElementById('attachment-chips');
  if (!container) return;
  if (!_attachments.length) {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'flex';
  container.innerHTML = _attachments.map(a => `
    <div class="attach-chip${a.status ? ` ${_escHtml(a.status)}` : ''}" data-id="${a.id}">
      <div class="attach-card-body">
        <span class="attach-thumb">${_isImg(a)
          ? _thumbMarkup(a)
          : _escHtml(_fileMark(a.name))}</span>
        <span class="attach-copy"><span class="attach-name">${_escHtml(a.name)}</span><span class="attach-size">${_statusText(a)}</span></span>
      </div>
      ${a.status === 'failed' ? `<button class="attach-retry" type="button" aria-label="retry ${_escHtml(a.name)}">retry</button>` : ''}
      <button class="attach-remove" type="button" aria-label="remove ${_escHtml(a.name)}">×</button>
    </div>`).join('');
  container.querySelectorAll('.attach-chip').forEach(chip => {
    chip.querySelector('.attach-retry')?.addEventListener('click', event => {
      event.stopPropagation();
      retryAttachment(chip.dataset.id);
    });
    chip.querySelector('.attach-remove')?.addEventListener('click', event => {
      event.stopPropagation();
      window._removeAttachment(chip.dataset.id);
    });
  });
}

function _fileMark(name = '') {
  const match = String(name).toLowerCase().match(/\.([a-z0-9]{1,5})$/);
  return match ? match[1].slice(0, 3) : 'file';
}

function _isImg(a) {
  return (a.type || '').startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(a.name || '');
}

function _thumbMarkup(a) {
  if (a.previewUrl) return `<img class="attach-chip-thumb" src="${_escHtml(a.previewUrl)}" alt="">`;
  if (a.status) return 'img';
  return `<img class="attach-chip-thumb" src="/api/uploads/${encodeURIComponent(a.id)}" alt="">`;
}

function _statusText(a) {
  if (a.status === 'uploading') return `uploading ${a.progress || 0}%`;
  if (a.status === 'failed') return 'failed';
  return _fmtSize(a.size);
}

function _fmtSize(n = 0) {
  if (n < 1024) return `${n}b`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}kb`;
  return `${(n / 1024 / 1024).toFixed(1)}mb`;
}

window._removeAttachment = (id) => removeAttachment(id);
window._retryAttachment = (id) => retryAttachment(id);

function _escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// drag-and-drop (chat file attach). only reacts to real files dragged in from
// outside — internal element drags (the docs tree move, etc.) carry no "Files"
// type, so they never trigger the overlay. drops aimed at the docs editor / tree
// are left for those to handle.
export function initDropZone() {
  void _resumeUploadCancellations();
  const main = document.querySelector('.main');
  const overlay = document.getElementById('drop-overlay');
  if (!main || !overlay) return;

  const hasFiles = e => Array.from(e.dataTransfer?.types || []).includes('Files');
  const ownsDrop = e => !!e.target?.closest?.('#wiki-live, .cm-editor, .wiki-tree');
  let dragCount = 0;
  const hide = () => { dragCount = 0; overlay.style.display = 'none'; };

  main.addEventListener('dragenter', e => {
    if (!hasFiles(e) || ownsDrop(e)) return;
    e.preventDefault();
    dragCount++;
    overlay.style.display = 'flex';
  });
  main.addEventListener('dragleave', e => {
    if (!hasFiles(e)) return;
    if (--dragCount <= 0) hide();
  });
  main.addEventListener('dragover', e => { if (hasFiles(e) && !ownsDrop(e)) e.preventDefault(); });
  main.addEventListener('drop', async e => {
    if (!hasFiles(e) || ownsDrop(e)) { hide(); return; }   // not a chat attach — just clear the overlay
    e.preventDefault();
    hide();
    for (const f of [...(e.dataTransfer?.files || [])]) await attachFile(f);
  });
  // safety net: any drag that ends or drops anywhere clears a stuck overlay
  window.addEventListener('dragend', hide);
  window.addEventListener('drop', e => { if (!hasFiles(e)) hide(); });
}
