import { toast } from './util.js';

let _attachments = [];   // [{id, name, type, size}]

export function getAttachments() { return _attachments.map(a => a.id); }

export function clearAttachments() {
  _attachments = [];
  _render();
}

export async function attachFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/api/uploads', { method: 'POST', body: fd });
    if (!r.ok) { toast('upload failed', 'error'); return null; }
    const data = await r.json();
    _attachments.push(data);
    _render();
    return data;
  } catch (e) {
    toast('upload failed', 'error');
    return null;
  }
}

async function removeAttachment(id) {
  await fetch(`/api/uploads/${id}`, { method: 'DELETE' }).catch(() => {});
  _attachments = _attachments.filter(a => a.id !== id);
  _render();
}

function _render() {
  const container = document.getElementById('attachment-chips');
  if (!container) return;
  if (!_attachments.length) { container.style.display = 'none'; return; }
  container.style.display = 'flex';
  container.innerHTML = _attachments.map(a => `
    <div class="attach-chip" data-id="${a.id}">
      <span class="attach-name">${_escHtml(a.name)}</span>
      <button class="attach-remove" onclick="window._removeAttachment('${a.id}')">×</button>
    </div>`).join('');
}

window._removeAttachment = removeAttachment;

function _escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// drag-and-drop
export function initDropZone() {
  const main = document.querySelector('.main');
  const overlay = document.getElementById('drop-overlay');
  if (!main || !overlay) return;

  let dragCount = 0;
  main.addEventListener('dragenter', e => {
    e.preventDefault();
    dragCount++;
    overlay.style.display = 'flex';
  });
  main.addEventListener('dragleave', () => {
    dragCount--;
    if (dragCount <= 0) { dragCount = 0; overlay.style.display = 'none'; }
  });
  main.addEventListener('dragover', e => e.preventDefault());
  main.addEventListener('drop', async e => {
    e.preventDefault();
    dragCount = 0;
    overlay.style.display = 'none';
    const files = [...(e.dataTransfer?.files || [])];
    for (const f of files) await attachFile(f);
  });
}
