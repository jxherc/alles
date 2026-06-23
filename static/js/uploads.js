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
  if (!_attachments.length) {
    container.style.display = 'none';
    document.getElementById('attachment-preview')?.replaceChildren();
    return;
  }
  container.style.display = 'flex';
  container.innerHTML = _attachments.map(a => `
    <div class="attach-chip" data-id="${a.id}" title="click to preview">
      <span class="attach-icon">${_isImg(a) ? '◳' : '◫'}</span>
      <span class="attach-name">${_escHtml(a.name)}</span>
      <span class="attach-size">${_fmtSize(a.size)}</span>
      <button class="attach-remove" onclick="window._removeAttachment('${a.id}')">×</button>
    </div>`).join('');
  container.querySelectorAll('.attach-chip').forEach(chip => {
    chip.querySelector('.attach-name')?.addEventListener('click', () => {
      const a = _attachments.find(x => x.id === chip.dataset.id);
      if (a) _togglePreview(a);
    });
  });
}

function _isImg(a) {
  return (a.type || '').startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(a.name || '');
}

function _isText(a) {
  if ((a.type || '').startsWith('text/')) return true;
  return /\.(txt|md|markdown|json|ya?ml|csv|tsv|js|ts|jsx|tsx|py|rb|go|rs|java|c|cpp|h|css|html?|xml|sh|toml|ini|cfg|log|sql)$/i.test(a.name || '');
}

function _fmtSize(n = 0) {
  if (n < 1024) return `${n}b`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}kb`;
  return `${(n / 1024 / 1024).toFixed(1)}mb`;
}

let _previewing = null;
async function _togglePreview(a) {
  const box = document.getElementById('attachment-preview');
  if (!box) return;
  if (_previewing === a.id) {        // toggle off
    box.replaceChildren();
    _previewing = null;
    return;
  }
  _previewing = a.id;
  box.innerHTML = `<div class="attach-preview-head">${_escHtml(a.name)} <button class="attach-preview-close" onclick="window._closeAttachPreview()">×</button></div><div class="attach-preview-body">loading…</div>`;
  const body = box.querySelector('.attach-preview-body');
  try {
    if (_isImg(a)) {
      body.innerHTML = `<img class="attach-preview-img" src="/api/uploads/${a.id}" alt="${_escHtml(a.name)}">`;
    } else if (_isText(a)) {
      const txt = await fetch(`/api/uploads/${a.id}`).then(r => r.text());
      const clipped = txt.length > 4000 ? txt.slice(0, 4000) + '\n\n… (truncated)' : txt;
      body.innerHTML = `<pre class="attach-preview-text"></pre>`;
      body.querySelector('pre').textContent = clipped;
    } else {
      body.textContent = 'no preview for this file type';
    }
  } catch {
    body.textContent = 'preview failed';
  }
}

window._removeAttachment = (id) => {
  if (_previewing === id) { document.getElementById('attachment-preview')?.replaceChildren(); _previewing = null; }
  removeAttachment(id);
};
window._closeAttachPreview = () => {
  document.getElementById('attachment-preview')?.replaceChildren();
  _previewing = null;
};

function _escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// drag-and-drop (chat file attach). only reacts to real files dragged in from
// outside — internal element drags (the docs tree move, etc.) carry no "Files"
// type, so they never trigger the overlay. drops aimed at the docs editor / tree
// are left for those to handle.
export function initDropZone() {
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
