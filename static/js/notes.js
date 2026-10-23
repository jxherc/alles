import { toast } from './util.js';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

let _notes = [];
let _editing = null;
let _editorOwner = null;
let _creating = false;
let _q = '';
let _tag = '';      // active tag filter, '' = all
let _searchWired = false;
let _deepLinked = false;
let _fetcher = fetch;

export async function loadNotes(fetcher = _fetcher) {
  _fetcher = fetcher;
  _wireSearch();
  const qs = new URLSearchParams();
  if (_q) qs.set('q', _q);
  if (_tag) qs.set('tag', _tag);
  const r = await _fetcher('/api/notes' + (qs.toString() ? `?${qs}` : ''));
  _notes = await r.json();
  renderNotes();
  _renderTagbar();
  // recall links here as /?app=notes#<stem> — open that note once
  if (!_deepLinked && location.hash.length > 1) {
    _deepLinked = true;
    const want = decodeURIComponent(location.hash.slice(1));
    const hit = _notes.find(n => n.id === want);
    if (hit) openEditor(hit);
  }
}

function _wireSearch() {
  if (_searchWired) return;
  const inp = document.getElementById('note-search');
  const newBtn = document.getElementById('note-new-btn');
  if (!inp && !newBtn) return;
  let t;
  inp?.addEventListener('input', e => {
    clearTimeout(t);
    t = setTimeout(() => { _q = e.target.value.trim(); loadNotes(); }, 200);
  });
  newBtn?.addEventListener('click', newNote);
  _searchWired = true;
}

async function _renderTagbar() {
  const bar = document.getElementById('note-tagbar');
  if (!bar) return;
  let tags = [];
  try { tags = await _fetcher('/api/notes/tags').then(r => r.json()); } catch {}
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
  // Vault events refresh the backing list after note writes. Keep the active
  // editor and its unsaved input mounted until the owner explicitly goes back.
  if (!list || _editing) return;

  if (!_notes.length) {
    const filtered = _q || _tag;
    const title = filtered ? 'no notes match that' : 'no notes yet';
    const sub = filtered ? 'try a different search or tag.' : 'jot a thought, a list, anything. hit + new note.';
    list.innerHTML = `<div class="notes-empty"><div class="notes-empty-title">${title}</div><div class="notes-empty-sub">${sub}</div></div>`;
    return;
  }

  list.innerHTML = _notes.map(n => `
    <div class="note-card${n.pinned ? ' pinned' : ''}" data-id="${esc(n.id)}">
      <button class="note-title" type="button">${esc(n.title || 'untitled')}</button>
      <div class="note-preview">${esc(n.content.slice(0, 200)) || '—'}</div>
      ${(n.due || n.items?.length) ? `<div class="note-meta-row">
        ${n.due ? `<span class="note-due${_isOverdue(n.due) ? ' overdue' : ''}">${_isOverdue(n.due) ? 'overdue' : 'due'} ${esc(n.due)}</span>` : ''}
        ${n.items?.length ? `<span class="note-progress">${_si('check')} ${n.items.filter(i => i.done).length}/${n.items.length}</span>` : ''}
      </div>` : ''}
      ${n.tags?.length ? `<div class="note-tags">${n.tags.map(t => `<span class="note-tag">${esc(t)}</span>`).join('')}</div>` : ''}
      <div class="note-actions">
        <button class="act-btn note-pin-btn" data-id="${esc(n.id)}" data-pinned="${n.pinned}">${n.pinned ? 'unpin' : 'pin'}</button>
        <button class="act-btn note-archive-btn" data-id="${esc(n.id)}">archive</button>
        <button class="act-btn note-del-btn" data-id="${esc(n.id)}">delete</button>
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
      await _fetcher(`/api/notes/${encodeURIComponent(btn.dataset.id)}`, { method: 'DELETE' });
      await loadNotes();
    });
  });

  list.querySelectorAll('.note-archive-btn').forEach(btn => {
    let archiving = false;
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      if (archiving) return;
      archiving = true;
      btn.setAttribute('aria-disabled', 'true');
      let archived = false;
      try {
        const r = await _fetcher(`/api/notes/${encodeURIComponent(btn.dataset.id)}/archive`, {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ archived: true }),
        });
        const result = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(result.detail || 'note could not be archived');
        if (result.id !== btn.dataset.id || result.archived !== true) throw new Error('archive was not confirmed. reload notes to check');
        archived = true;
        toast('archived', 'success');
        await loadNotes();
      } catch (error) {
        toast(archived ? 'note archived, but the list could not refresh. reopen notes' : error.message || 'note could not be archived', 'error');
      } finally { archiving = false; btn.removeAttribute('aria-disabled'); }
    });
  });

  list.querySelectorAll('.note-pin-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await _fetcher(`/api/notes/${encodeURIComponent(btn.dataset.id)}`, {
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
  const owner = _editorOwner = { note, pending: null, saved: null };

  list.innerHTML = `
    <div class="note-editor">
      <input class="note-editor-title" id="note-edit-title" value="${esc(note.title)}" placeholder="title...">
      <textarea class="note-editor-body" id="note-edit-body" rows="7">${esc(note.content)}</textarea>
      <div class="note-checklist" id="note-checklist"></div>
      <button class="act-btn" id="note-add-item" style="align-self:flex-start">+ checklist item</button>
      <div class="note-editor-fields">
        <input class="note-editor-title" id="note-edit-tags" value="${esc((note.tags || []).join(', '))}" placeholder="tags, comma separated…" style="font-size:0.78rem;flex:1">
        <input type="date" class="note-editor-title" id="note-edit-due" value="${esc(note.due || '')}" style="font-size:0.78rem;width:auto" title="due date">
      </div>
      <div style="display:flex;gap:0.4rem;justify-content:flex-end">
        <button class="btn" id="note-obsidian-btn" title="open this note in Obsidian">obsidian</button>
        <button class="btn" id="note-back-btn">${_si('chevron-left')} back</button>
        <button class="btn primary" id="note-save-btn">save</button>
      </div>
    </div>`;

  (note.items || []).forEach(it => _addChecklistRow(it.text, it.done));
  document.getElementById('note-add-item').addEventListener('click', () => _addChecklistRow('', false, true));

  document.getElementById('note-obsidian-btn')?.addEventListener('click', async () => {
    if (!_editing) return;
    const rel = 'Notes/' + _editing.id + '.md';
    const r = await _fetcher('/api/vault-location?path=' + encodeURIComponent(rel)).then(r => r.json()).catch(() => null);
    if (r?.obsidian) location.href = r.obsidian;
  });

  document.getElementById('note-back-btn').addEventListener('click', async () => {
    if (!await _saveBeforeLeaving(owner) || owner !== _editorOwner) return;
    _editing = null;
    _editorOwner = null;
    await loadNotes();
  });

  document.getElementById('note-save-btn').addEventListener('click', async () => {
    if (owner.pending) return;
    const updated = await saveCurrentNote();
    if (!updated) return;
    const current = owner === _editorOwner;
    const newer = current && owner.saved !== JSON.stringify(_editorFields());
    toast(newer ? 'saved; newer edits are still unsaved' : current ? 'saved' : `saved ${updated.title || 'untitled'}`, 'success');
  });
}

function _addChecklistRow(text = '', done = false, focus = false) {
  const box = document.getElementById('note-checklist');
  if (!box) return;
  const row = document.createElement('div');
  row.className = 'note-cl-row';
  row.innerHTML = `
    <button type="button" class="note-cl-done chk" role="checkbox" aria-checked="${done ? 'true' : 'false'}" aria-label="mark item done"></button>
    <input type="text" class="note-cl-text" value="${esc(text)}" placeholder="item…">
    <button class="act-btn note-cl-del" title="remove" aria-label="remove">${_si('close')}</button>`;
  row.querySelector('.note-cl-done').addEventListener('click', event => {
    const button = event.currentTarget;
    button.setAttribute('aria-checked', button.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
  });
  row.querySelector('.note-cl-del').addEventListener('click', () => row.remove());
  box.appendChild(row);
  if (focus) row.querySelector('.note-cl-text').focus();
}

function _gatherItems() {
  return [...document.querySelectorAll('#note-checklist .note-cl-row')]
    .map(r => ({
      text: r.querySelector('.note-cl-text').value.trim(),
      done: r.querySelector('.note-cl-done').getAttribute('aria-checked') === 'true',
    }))
    .filter(i => i.text);
}

function _isOverdue(due) {
  if (!due) return false;
  const today = new Date().toISOString().slice(0, 10);
  return due < today;
}


function _editorFields() {
  const title = document.getElementById('note-edit-title')?.value || '';
  const content = document.getElementById('note-edit-body')?.value || '';
  const tags = (document.getElementById('note-edit-tags')?.value || '').split(',').map(t => t.trim()).filter(Boolean);
  const due = document.getElementById('note-edit-due')?.value || '';
  const items = _gatherItems();
  return { title, content, tags, items, due };
}

// Navigation may begin during a Save, and typing may continue while it waits.
// Finish each submitted snapshot before saving newer input with its fresh hash.
async function _saveBeforeLeaving(owner) {
  while (owner === _editorOwner) {
    if (!owner.pending && owner.saved === JSON.stringify(_editorFields())) return true;
    if (!await saveCurrentNote()) return false;
  }
  return false;
}

export async function saveCurrentNote() {
  const owner = _editorOwner;
  if (!owner) return null;
  if (owner.pending) return owner.pending;
  const fields = _editorFields();
  const button = document.getElementById('note-save-btn');
  button?.setAttribute('aria-disabled', 'true');
  button?.setAttribute('aria-busy', 'true');
  owner.pending = _saveNote(owner, fields);
  try { return await owner.pending; }
  finally {
    owner.pending = null;
    button?.removeAttribute('aria-disabled');
    button?.removeAttribute('aria-busy');
  }
}

async function _saveNote(owner, fields) {
  // the id is the filename stem — retitling renames the file, so the response can carry a NEW id
  let updated = null;
  try {
    const r = await _fetcher(`/api/notes/${encodeURIComponent(owner.note.id)}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ...fields, expected_hash: owner.note.hash || '' }),
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      if (data.code === 'document_conflict') {
        toast('this note changed outside Alles. reload it before saving', 'error');
        return null;
      }
      throw new Error(data.detail || 'note could not be saved');
    }
    updated = await r.json();
    if (!updated?.id || !updated.hash) throw new Error('save was not confirmed. reload notes to check');
    owner.note = updated;
    owner.saved = JSON.stringify(fields);
    // Keep the live fields mounted: the receipt may rename the file, but it
    // must neither replace newer typing nor bind a different editor to this id.
    if (owner === _editorOwner) _editing = updated;
    return updated;
  } catch (error) { toast(error.message || 'note could not be saved', 'error'); }
  return null;
}


export async function newNote() {
  if (_creating) return;
  _creating = true;
  const owner = _editorOwner;
  const button = document.getElementById('note-new-btn');
  button?.setAttribute('aria-disabled', 'true');
  button?.setAttribute('aria-busy', 'true');
  try {
    if (owner && !await _saveBeforeLeaving(owner)) return;
    if (owner !== _editorOwner) return;
    const r = await _fetcher('/api/notes', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title: '', content: '' }),
    });
    const note = await r.json();
    if (!r.ok) throw new Error(note.detail || 'note could not be created');
    if (!note?.id || !note.hash) throw new Error('new note was not confirmed. reload notes to check');
    _notes.unshift(note);
    if (owner !== _editorOwner) return;
    if (owner && !await _saveBeforeLeaving(owner)) return;
    if (owner !== _editorOwner) return;
    openEditor(note);
  } catch (error) { toast(error.message || 'note could not be created', 'error'); }
  finally {
    _creating = false;
    button?.removeAttribute('aria-disabled');
    button?.removeAttribute('aria-busy');
  }
}


function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// let settings "apply" + the vault file-watcher refresh the list
if (typeof window !== 'undefined') window._reloadNotes = loadNotes;
