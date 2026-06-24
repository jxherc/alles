// books — a reading list with shelves (want / reading / done), covers, star ratings,
// notes, and a keyless OpenLibrary lookup to autofill. mirrors the panel conventions.
import { toast } from './util.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _data = { shelves: { want: [], reading: [], done: [] }, this_year: 0, total: 0 };
let _adding = false;
let _editingNotes = null;
let _lookup = [];

const SHELVES = [['reading', 'reading'], ['want', 'want to read'], ['done', 'read']];

export function initBooks() { loadBooks(); }

const _EMPTY = () => ({ shelves: { want: [], reading: [], done: [] }, this_year: 0, total: 0 });

export async function loadBooks() {
  // check r.ok — a non-2xx (e.g. a 401 on a subdomain) still returns JSON, and a
  // {detail:…} body with no `shelves` would crash _render and blank the page.
  try {
    const r = await fetch('/api/books/overview');
    _data = r.ok ? await r.json() : _EMPTY();
  } catch { _data = _EMPTY(); }
  if (!_data || !_data.shelves) _data = _EMPTY();
  _render();
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function _stars(b) {
  let out = '<span class="book-stars" data-id="' + b.id + '">';
  for (let i = 1; i <= 5; i++) out += `<button class="book-star${i <= b.rating ? ' on' : ''}" data-rate="${i}" title="${i} star${i > 1 ? 's' : ''}">${_si(i <= b.rating ? 'star-fill' : 'star')}</button>`;
  return out + '</span>';
}

function _cover(b) {
  if (b.cover) return `<img class="book-cover" src="${esc(b.cover)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'book-cover book-cover-ph',textContent:${JSON.stringify((b.title || '?')[0].toUpperCase())}}))">`;
  return `<div class="book-cover book-cover-ph">${esc((b.title || '?')[0].toUpperCase())}</div>`;
}

function _card(b) {
  const others = SHELVES.map(([k]) => k).filter(k => k !== b.status);
  return `
    <div class="book-card" data-id="${b.id}">
      ${_cover(b)}
      <div class="book-info">
        <div class="book-title">${esc(b.title)}</div>
        <div class="book-author">${esc(b.author || '')}${b.year ? ` · ${b.year}` : ''}</div>
        ${_stars(b)}
        <div class="book-move">${others.map(k => `<button class="book-move-btn" data-move="${k}">${k === 'done' ? 'read' : k === 'reading' ? 'reading' : 'want'}</button>`).join('')}</div>
        ${b.id === _editingNotes
          ? `<div class="book-notes-edit"><textarea class="settings-input" data-f="notes" rows="3" placeholder="your notes…">${esc(b.notes)}</textarea><div class="book-notes-actions"><button class="btn primary" data-act="save-notes">save</button><button class="btn" data-act="cancel-notes">cancel</button></div></div>`
          : (b.notes ? `<div class="book-notes" data-act="notes">${esc(b.notes)}</div>` : `<button class="book-add-note" data-act="notes">+ note</button>`)}
      </div>
      <button class="icon-btn danger book-del" data-act="del" title="remove">${_si('trash')}</button>
    </div>`;
}

function _render() {
  const body = $('books-body');
  if (!body) return;
  const shelves = _data.shelves || {};
  const shelfHtml = SHELVES.map(([k, label]) => {
    const list = shelves[k] || [];
    if (!list.length && !_adding) return '';
    return `<div class="book-shelf"><div class="book-shelf-h">${label} <span>${list.length}</span></div><div class="book-grid">${list.map(_card).join('')}</div></div>`;
  }).join('');
  const goal = _data.goal || 0, yr = _data.this_year || 0;
  const goalHtml = goal > 0
    ? `<div class="books-goal" data-act="set-goal" title="reading goal — click to change">
         <span>${yr} / ${goal} this year${yr >= goal ? ' ✓' : ''}</span>
         <div class="books-goal-bar"><i style="width:${Math.min(100, Math.round(yr / goal * 100))}%"></i></div>
       </div>`
    : `<button class="books-goal-set" data-act="set-goal">+ reading goal</button>`;
  body.innerHTML = `
    <div class="books-bar">
      <div class="books-summary">${_data.total ? `${_data.total} book${_data.total !== 1 ? 's' : ''}${goal ? '' : ` · ${yr} read this year`}` : ''}</div>
      ${goalHtml}
      <button class="btn" id="books-import" title="import a Goodreads export (.csv)">import</button>
      <button class="btn primary" id="books-add-toggle">${_si('plus')} book</button>
    </div>
    ${_adding ? _addForm() : ''}
    ${_data.total ? shelfHtml : (_adding ? '' : `
      <div class="empty-state">
        <div class="empty-state-icon">${_si('bookmark')}</div>
        <div class="empty-state-title">no books yet</div>
        <div class="empty-state-desc">track what you're reading, want to read, or have finished. search a title and alles autofills the cover, author and year.</div>
        <button class="btn primary" id="books-empty-add">${_si('plus')} add your first book</button>
      </div>`)}`;
  _wire(body);
}

function _addForm() {
  return `
    <div class="book-add">
      <div class="book-add-row">
        <input type="text" id="book-q" class="settings-input" placeholder="search a title to autofill (or type one)…" spellcheck="false">
        <button class="btn" id="book-search">search</button>
      </div>
      ${_lookup.length ? `<div class="book-lookup">${_lookup.map((r, i) => `<button class="book-lookup-item" data-pick="${i}">${r.cover ? `<img src="${esc(r.cover)}" alt="" loading="lazy">` : '<span class="book-lk-ph"></span>'}<span><b>${esc(r.title)}</b><i>${esc(r.author)}${r.year ? ` · ${r.year}` : ''}</i></span></button>`).join('')}</div>` : ''}
      <div class="book-add-row">
        <input type="text" id="book-title" class="settings-input" placeholder="title">
        <input type="text" id="book-author" class="settings-input" placeholder="author">
      </div>
      <div class="book-add-row">
        <div class="te-seg" id="book-status">${SHELVES.map(([k], i) => `<button class="te-seg-opt${i === 0 ? ' active' : ''}" data-val="${k}">${k === 'done' ? 'read' : k === 'reading' ? 'reading' : 'want'}</button>`).join('')}</div>
        <button class="btn primary" id="book-create">add</button>
        <button class="btn" id="book-cancel">cancel</button>
      </div>
    </div>`;
}

function _wire(body) {
  $('books-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _lookup = []; _render(); });
  $('books-empty-add')?.addEventListener('click', () => { _adding = true; _lookup = []; _render(); });
  $('books-import')?.addEventListener('click', () => {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.csv,text/csv';
    inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return;
      const r = await fetch('/api/books/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: await f.text() }) });
      const d = await r.json().catch(() => ({}));
      toast(`imported ${d.imported || 0} book${d.imported === 1 ? '' : 's'}`, 'success'); loadBooks();
    };
    inp.click();
  });
  body.querySelector('[data-act="set-goal"]')?.addEventListener('click', async () => {
    const v = await dlgPrompt('books to read this year? (0 to turn off)', String(_data.goal || 0));
    if (v == null) return;
    const n = Math.max(0, parseInt(v, 10) || 0);
    await fetch('/api/books/goal', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ goal: n }) });
    loadBooks();
  });

  if (_adding) {
    const doSearch = async () => {
      const q = $('book-q')?.value.trim();
      if (!q) return;
      // grab whatever's already typed so the re-render below doesn't blow it away
      const keep = { title: $('book-title')?.value || '', author: $('book-author')?.value || '' };
      const btn = $('book-search'); if (btn) btn.textContent = '…';
      try { _lookup = (await fetch('/api/books/lookup?q=' + encodeURIComponent(q)).then(r => r.json())).results || []; }
      catch { _lookup = []; }
      _render();
      if ($('book-q')) $('book-q').value = q;
      if ($('book-title')) $('book-title').value = keep.title;
      if ($('book-author')) $('book-author').value = keep.author;
    };
    $('book-search')?.addEventListener('click', doSearch);
    $('book-q')?.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
    body.querySelectorAll('.book-lookup-item').forEach(el => el.addEventListener('click', () => {
      const r = _lookup[+el.dataset.pick];
      $('book-title').value = r.title; $('book-author').value = r.author || '';
      $('book-title').dataset.cover = r.cover || ''; $('book-title').dataset.isbn = r.isbn || ''; $('book-title').dataset.year = r.year || 0;
      _lookup = []; _renderKeepForm(r);
    }));
    body.querySelectorAll('#book-status .te-seg-opt').forEach(o => o.addEventListener('click', () => {
      body.querySelectorAll('#book-status .te-seg-opt').forEach(x => x.classList.remove('active')); o.classList.add('active');
    }));
    $('book-create')?.addEventListener('click', _create);
    $('book-cancel')?.addEventListener('click', () => { _adding = false; _lookup = []; _render(); });
  }

  body.querySelectorAll('.book-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('.book-star').forEach(s => s.addEventListener('click', async () => {
      await fetch(`/api/books/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ rating: +s.dataset.rate }) }); loadBooks();
    }));
    card.querySelectorAll('[data-move]').forEach(btn => btn.addEventListener('click', async () => {
      await fetch(`/api/books/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ status: btn.dataset.move }) }); toast(`moved to ${btn.dataset.move}`, 'success'); loadBooks();
    }));
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'notes') { _editingNotes = id; _render(); return; }
      if (act === 'cancel-notes') { _editingNotes = null; _render(); return; }
      if (act === 'save-notes') {
        const v = card.querySelector('[data-f="notes"]').value;
        await fetch(`/api/books/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ notes: v }) });
        _editingNotes = null; toast('saved', 'success'); loadBooks(); return;
      }
      if (act === 'del') {
        if (!await dlgConfirm('remove this book?')) return;
        await fetch(`/api/books/${id}`, { method: 'DELETE' }); toast('removed', 'success'); loadBooks(); return;
      }
    }));
  });
}

// re-render but keep the typed title/author after picking a lookup result
function _renderKeepForm(r) {
  _render();
  if ($('book-title')) $('book-title').value = r.title || '';
  if ($('book-author')) $('book-author').value = r.author || '';
  if ($('book-title')) { $('book-title').dataset.cover = r.cover || ''; $('book-title').dataset.isbn = r.isbn || ''; $('book-title').dataset.year = r.year || 0; }
}

async function _create() {
  const title = $('book-title')?.value.trim();
  if (!title) { toast('title needed', 'error'); return; }
  const status = document.querySelector('#book-status .te-seg-opt.active')?.dataset.val || 'want';
  const tEl = $('book-title');
  const r = await fetch('/api/books', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title, author: $('book-author')?.value.trim() || '', status, cover: tEl?.dataset.cover || '', isbn: tEl?.dataset.isbn || '', year: parseInt(tEl?.dataset.year || '0', 10) || 0 }),
  });
  if (!r.ok) { toast((await r.json()).detail || 'failed', 'error'); return; }
  _adding = false; _lookup = []; toast(`added ${title}`, 'success'); loadBooks();
}
