import { mdToHtml, toast } from './util.js';

let _docs = [];
let _activeDoc = null;
let _aiAccText = '';

export async function loadDocuments() {
  try {
    const r = await fetch('/api/documents');
    _docs = await r.json();
  } catch (e) { _docs = []; }
  _renderList();
}

function _renderList() {
  const el = document.getElementById('doc-list');
  if (!el) return;
  if (!_docs.length) {
    el.innerHTML = '<div class="page-empty">no documents</div>';
    return;
  }
  el.innerHTML = _docs.map(d => `
    <div class="settings-list-row doc-item" data-id="${d.id}">
      <span class="row-name">${_esc(d.title)}</span>
      <span class="row-meta">${d.doc_type}</span>
      <button class="act-btn" data-id="${d.id}" onclick="window._delDoc('${d.id}')">del</button>
    </div>`).join('');
  el.querySelectorAll('.doc-item').forEach(item => {
    item.addEventListener('click', e => {
      if (e.target.classList.contains('act-btn')) return;
      openDoc(item.dataset.id);
    });
  });
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
  } catch (e) { return; }

  const editor = document.getElementById('doc-editor-area');
  const preview = document.getElementById('doc-preview-area');
  const titleInput = document.getElementById('doc-title-input');
  if (!editor || !preview || !titleInput) return;

  titleInput.value = _activeDoc.title;
  editor.value = _activeDoc.content;
  preview.innerHTML = mdToHtml(_activeDoc.content);

  document.getElementById('doc-editor-panel').style.display = 'flex';
  document.getElementById('doc-list-panel').style.display = 'none';
}

export function closeDocEditor() {
  document.getElementById('doc-editor-panel').style.display = 'none';
  document.getElementById('doc-list-panel').style.display = 'flex';
  _activeDoc = null;
}

export function initDocEditor() {
  const editor = document.getElementById('doc-editor-area');
  const preview = document.getElementById('doc-preview-area');
  const titleInput = document.getElementById('doc-title-input');
  if (!editor) return;

  let _saveTimer = null;
  const scheduleSave = () => {
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(_save, 800);
  };

  editor.addEventListener('input', () => {
    preview.innerHTML = mdToHtml(editor.value);
    scheduleSave();
  });
  titleInput?.addEventListener('input', scheduleSave);
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
}

window._delDoc = async id => {
  await fetch(`/api/documents/${id}`, { method: 'DELETE' });
  _docs = _docs.filter(d => d.id !== id);
  _renderList();
  if (_activeDoc?.id === id) closeDocEditor();
};

export async function aiEditDoc(instruction) {
  if (!_activeDoc || !instruction) return;
  const editor = document.getElementById('doc-editor-area');
  const preview = document.getElementById('doc-preview-area');
  if (!editor) return;

  const r = await fetch(`/api/documents/${_activeDoc.id}/ai-edit`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ instruction }),
  });
  if (!r.ok) { toast('ai edit failed', 'error'); return; }

  editor.value = '';
  _aiAccText = '';
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
          _aiAccText += chunk.delta;
          editor.value = _aiAccText;
          preview.innerHTML = mdToHtml(_aiAccText);
        }
      } catch {}
    }
  }
  await _save();
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
