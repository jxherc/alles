import { toast } from './util.js';

let _notes = [];
let _editing = null;
let _q = '';
let _tag = '';      // active tag filter, '' = all
let _searchWired = false;

export async function loadNotes() {
  _wireSearch();
  const qs = new URLSearchParams();
  if (_q) qs.set('q', _q);
  if (_tag) qs.set('tag', _tag);
  const r = await fetch('/api/notes' + (qs.toString() ? `?${qs}` : ''));
  _notes = await r.json();
  renderNotes();
  _renderTagbar();
}

function _wireSearch() {
  if (_searchWired) return;
  const inp = document.getElementById('note-search');
  if (!inp) return;
  let t;
  inp.addEventListener('input', e => {
    clearTimeout(t);
    t = setTimeout(() => { _q = e.target.value.trim(); loadNotes(); }, 200);
  });
  _searchWired = true;
}

async function _renderTagbar() {
  const bar = document.getElementById('note-tagbar');
  if (!bar) return;
  let tags = [];
  try { tags = await fetch('/api/notes/tags').then(r => r.json()); } catch {}
  if (!tags.length) { bar.innerHTML = ''; return; }
  bar.innerHTML =
    `<button class="note-tag-chip${_tag ? '' : ' on'}" data-tag="">all</button>` +
    tags.map(t => `<button class="note-tag-chip${_tag === t.tag ? ' on' : ''}" data-tag="${esc(t.tag)}">${esc(t.tag)} ${t.count}</button>`).join('');
  bar.querySelectorAll('.note-tag-chip').forEach(b => b.addEventListener('click', () => {
    _tag = b.dataset.tag; loadNotes();
  }));
}

function renderNotes() {
  const list = document.getElementById('notes-list');
  if (!list) return;

  if (!_notes.length) {
    const msg = _q || _tag ? 'no matches' : 'no docs yet';
    list.innerHTML = `<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">${msg}</div>`;
    return;
  }

  list.innerHTML = _notes.map(n => `
    <div class="note-card${n.pinned ? ' pinned' : ''}" data-id="${n.id}">
      <div class="note-title">${esc(n.title || 'untitled')}</div>
      <div class="note-preview">${esc(n.content.slice(0, 80)) || '—'}</div>
      ${n.tags?.length ? `<div class="note-tags">${n.tags.map(t => `<span class="note-tag">${esc(t)}</span>`).join('')}</div>` : ''}
      <div class="note-actions">
        <button class="act-btn note-pin-btn" data-id="${n.id}" data-pinned="${n.pinned}">${n.pinned ? 'unpin' : 'pin'}</button>
        <button class="act-btn note-archive-btn" data-id="${n.id}">archive</button>
        <button class="act-btn note-del-btn" data-id="${n.id}">delete</button>
      </div>
    </div>`).join('');

  list.querySelectorAll('.note-card').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.closest('.note-actions')) return;
      openEditor(_notes.find(n => n.id === el.dataset.id));
    });
  });

  list.querySelectorAll('.note-del-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/notes/${btn.dataset.id}`, { method: 'DELETE' });
      await loadNotes();
    });
  });

  list.querySelectorAll('.note-archive-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/notes/${btn.dataset.id}/archive`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ archived: true }),
      });
      toast('archived', 'success');
      await loadNotes();
    });
  });

  list.querySelectorAll('.note-pin-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/notes/${btn.dataset.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pinned: btn.dataset.pinned === 'false' }),
      });
      await loadNotes();
    });
  });
}


function openEditor(note) {
  const list = document.getElementById('notes-list');
  _editing = note;

  list.innerHTML = `
    <div class="note-editor">
      <input class="note-editor-title" id="note-edit-title" value="${esc(note.title)}" placeholder="title...">
      <textarea class="note-editor-body" id="note-edit-body" rows="8">${esc(note.content)}</textarea>
      <input class="note-editor-title" id="note-edit-tags" value="${esc((note.tags || []).join(', '))}" placeholder="tags, comma separated…" style="font-size:0.78rem">
      <div style="display:flex;gap:0.4rem;justify-content:flex-end">
        <button class="btn" id="note-back-btn">← back</button>
        <button class="btn primary" id="note-save-btn">save</button>
      </div>
    </div>`;

  document.getElementById('note-back-btn').addEventListener('click', async () => {
    await saveCurrentNote();
    await loadNotes();
  });

  document.getElementById('note-save-btn').addEventListener('click', async () => {
    await saveCurrentNote();
    toast('saved', 'success');
  });
}


async function saveCurrentNote() {
  if (!_editing) return;
  const title = document.getElementById('note-edit-title')?.value || '';
  const content = document.getElementById('note-edit-body')?.value || '';
  const tags = (document.getElementById('note-edit-tags')?.value || '').split(',').map(t => t.trim()).filter(Boolean);
  await fetch(`/api/notes/${_editing.id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title, content, tags }),
  });
  _editing = null;
}


export async function newNote() {
  const r = await fetch('/api/notes', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title: '', content: '' }),
  });
  const note = await r.json();
  _notes.unshift(note);
  openEditor(note);
}


function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
