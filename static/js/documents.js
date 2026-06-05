import { mdToHtml, toast } from './util.js';
import { confirm as _dlgConfirm } from './dialog.js';

let _docs = [];
let _activeDoc = null;
let _saveTimer = null;
let _aiWorking = false;
let _filter = '';

export async function loadDocuments() {
  try {
    const r = await fetch('/api/documents');
    _docs = await r.json();
  } catch { _docs = []; }
  _renderList();
}

function _renderList() {
  const el = document.getElementById('doc-list');
  if (!el) return;
  const q = _filter.toLowerCase();
  const filtered = q ? _docs.filter(d => d.title.toLowerCase().includes(q)) : _docs;
  if (!filtered.length) {
    el.innerHTML = `<div class="page-empty">${q ? 'no matches' : 'no documents'}</div>`;
    return;
  }
  el.innerHTML = filtered.map(d => `
    <div class="settings-list-row doc-item" data-id="${d.id}">
      <div style="flex:1;min-width:0">
        <div class="row-name">${_esc(d.title)}</div>
        <div class="doc-item-meta">${_relTime(d.updated_at || d.created_at)}</div>
      </div>
      <span class="row-meta">${d.doc_type}</span>
      <button class="act-btn" onclick="window._delDoc('${d.id}')">del</button>
    </div>`).join('');
  el.querySelectorAll('.doc-item').forEach(row => {
    row.addEventListener('click', e => {
      if (e.target.classList.contains('act-btn')) return;
      openDoc(row.dataset.id);
    });
  });
}

function _relTime(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export async function newDocument() {
  const r = await fetch('/api/documents', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title: 'untitled', doc_type: 'md', content: '' }),
  });
  const d = await r.json();
  _docs.unshift(d);
  _renderList();
  openDoc(d.id);
}

async function openDoc(id) {
  try {
    const r = await fetch(`/api/documents/${id}`);
    _activeDoc = await r.json();
  } catch { return; }

  const editor = document.getElementById('doc-editor-area');
  const preview = document.getElementById('doc-preview-area');
  const titleInput = document.getElementById('doc-title-input');
  if (!editor || !titleInput) return;

  titleInput.value = _activeDoc.title;
  editor.value = _activeDoc.content;
  if (preview) preview.innerHTML = mdToHtml(_activeDoc.content);
  _updateWordCount();
  _setSaveStatus('');

  document.getElementById('doc-editor-panel').style.display = 'flex';
  document.getElementById('doc-list-panel').style.display = 'none';
  editor.focus();
}

export function closeDocEditor() {
  if (_saveTimer) { clearTimeout(_saveTimer); _saveTimer = null; _save(); }
  document.getElementById('doc-editor-panel').style.display = 'none';
  document.getElementById('doc-list-panel').style.display = 'flex';
  _activeDoc = null;
}

export function initDocEditor() {
  const editor = document.getElementById('doc-editor-area');
  if (!editor || editor.dataset.init) return;
  editor.dataset.init = '1';

  const preview = document.getElementById('doc-preview-area');
  const titleInput = document.getElementById('doc-title-input');
  const filterInput = document.getElementById('doc-filter-input');

  editor.addEventListener('input', () => {
    if (preview) preview.innerHTML = mdToHtml(editor.value);
    _updateWordCount();
    _scheduleSave();
  });
  titleInput?.addEventListener('input', _scheduleSave);

  editor.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      clearTimeout(_saveTimer); _saveTimer = null;
      _save();
    }
    if (e.key === 'Escape') closeDocEditor();
  });

  filterInput?.addEventListener('input', e => {
    _filter = e.target.value;
    _renderList();
  });

  // preview layout toggle
  document.getElementById('doc-preview-toggle')?.addEventListener('click', _cycleLayout);
}

function _cycleLayout() {
  const editor = document.getElementById('doc-editor-area');
  const preview = document.getElementById('doc-preview-area');
  const btn = document.getElementById('doc-preview-toggle');
  const mode = editor.dataset.layout || 'split';
  if (mode === 'split') {
    preview.style.display = 'none';
    editor.style.flex = '1';
    editor.dataset.layout = 'edit';
    btn.textContent = 'preview';
  } else if (mode === 'edit') {
    editor.style.display = 'none';
    preview.style.display = '';
    preview.style.flex = '1';
    editor.dataset.layout = 'preview';
    btn.textContent = 'edit';
  } else {
    editor.style.display = '';
    preview.style.display = '';
    editor.style.flex = '';
    preview.style.flex = '';
    editor.dataset.layout = 'split';
    btn.textContent = 'preview';
  }
}

function _updateWordCount() {
  const el = document.getElementById('doc-word-count');
  if (!el) return;
  const editor = document.getElementById('doc-editor-area');
  const text = editor?.value || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  el.textContent = `${words}w`;
}

function _setSaveStatus(status) {
  const el = document.getElementById('doc-save-status');
  if (el) el.textContent = status;
}

function _scheduleSave() {
  _setSaveStatus('saving…');
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(_save, 900);
}

async function _save() {
  if (!_activeDoc) return;
  const editor = document.getElementById('doc-editor-area');
  const titleInput = document.getElementById('doc-title-input');
  await fetch(`/api/documents/${_activeDoc.id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      content: editor?.value || '',
      title: titleInput?.value || 'untitled',
    }),
  });
  // update local cache
  const d = _docs.find(x => x.id === _activeDoc.id);
  if (d) { d.title = titleInput?.value || 'untitled'; d.updated_at = new Date().toISOString(); }
  _setSaveStatus('saved');
  setTimeout(() => _setSaveStatus(''), 1800);
}

window._delDoc = async id => {
  if (!await _dlgConfirm('delete this document?')) return;
  await fetch(`/api/documents/${id}`, { method: 'DELETE' });
  _docs = _docs.filter(d => d.id !== id);
  _renderList();
  if (_activeDoc?.id === id) closeDocEditor();
};

export async function aiEditDoc(instruction) {
  if (!_activeDoc || !instruction || _aiWorking) return;
  const editor = document.getElementById('doc-editor-area');
  const preview = document.getElementById('doc-preview-area');
  const btn = document.getElementById('doc-ai-send');
  const inp = document.getElementById('doc-ai-input');
  if (!editor) return;

  _aiWorking = true;
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  if (inp) inp.disabled = true;

  const r = await fetch(`/api/documents/${_activeDoc.id}/ai-edit`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ instruction }),
  });

  if (!r.ok) {
    toast('ai edit failed', 'error');
    _resetAiBar(btn, inp);
    return;
  }

  editor.value = '';
  let accText = '';
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      if (raw === '[DONE]') break;
      try {
        const chunk = JSON.parse(raw);
        if (chunk.delta) {
          accText += chunk.delta;
          editor.value = accText;
          if (preview) preview.innerHTML = mdToHtml(accText);
          _updateWordCount();
        }
      } catch {}
    }
  }

  await _save();
  _resetAiBar(btn, inp);
}

function _resetAiBar(btn, inp) {
  _aiWorking = false;
  if (btn) { btn.disabled = false; btn.textContent = 'ask'; }
  if (inp) { inp.disabled = false; inp.value = ''; inp.focus(); }
}

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
