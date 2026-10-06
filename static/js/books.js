// books — a reading list with shelves (want / reading / done), covers, star ratings,
// notes, and a keyless OpenLibrary lookup to autofill. mirrors the panel conventions.
import { toast } from './util.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { wireChoiceGroup } from './kokuen.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _data = { shelves: { want: [], reading: [], done: [] }, this_year: 0, total: 0 };
let _adding = false;
let _editingNotes = null;
const _noteDrafts = new Map();
const _noteErrors = new Map();
const _savingNotes = new Set();
const _writingBooks = new Set();
const _bookErrors = new Map();
const _bookUndo = new Map();
let _goalDraft = null;
let _lookup = [];
let _lookupBusy = false;
let _lookupMessage = '';
let _lookupFailed = false;
let _lookupGeneration = 0;
let _createBusy = false;
let _createError = '';
let _recoveryError = '';
let _createReady = false;
let _createScopes = [];
let _pendingCreate = null;
let _unreadableCreate = '';
let _savedBook = null;
let _viewGeneration = 0;
const CREATE_PREFIX = 'alles.books.pending.v1:';
const requestPattern = /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const emptyDraft = () => ({ query: '', title: '', author: '', status: 'reading', cover: '', isbn: '', year: 0 });
let _draft = emptyDraft();
let _fetcher = fetch;
let _hasOverview = false;
let _loadGeneration = 0;
let _loadState = { state: 'resting', message: '' };

const SHELVES = [['reading', 'reading'], ['want', 'want to read'], ['done', 'read']];

export function initBooks(fetcher = fetch) {
  ++_viewGeneration;
  _fetcher = fetcher;
  return loadBooks(fetcher);
}

function _loadFailure(error) {
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
  const retained = _hasOverview ? ' Showing the last loaded books.' : '';
  return {
    state: offline ? 'offline' : 'error',
    message: `${offline ? 'You appear to be offline.' : 'Books could not be loaded.'}${retained}`,
  };
}

function _loadNotice() {
  if (_loadState.state === 'resting') return '';
  const loading = _loadState.state === 'loading';
  return `<div class="specialist-group-note legacy-load-note" role="${loading ? 'status' : 'alert'}" aria-live="${loading ? 'polite' : 'assertive'}" data-kokuen-state="${_loadState.state}">
    <span>${esc(_loadState.message)}</span>${loading ? '' : '<button type="button" class="btn" data-act="retry-load">retry</button>'}
  </div>`;
}

export async function loadBooks(fetcher = _fetcher) {
  const generation = ++_loadGeneration;
  _fetcher = fetcher;
  _loadState = { state: 'loading', message: 'loading books…' };
  _render();
  try {
    const r = await fetcher('/api/books/overview');
    if (!r.ok) throw new Error(`request failed (${r.status || 'unknown'})`);
    const data = await r.json();
    if (generation !== _loadGeneration) return;
    if (!data || !data.shelves) throw new Error('invalid response');
    _data = data;
    try { _readCreateRecovery(data.recovery_scopes); }
    catch (error) { _recoveryError = error.message; }
    _hasOverview = true;
    _loadState = { state: 'resting', message: '' };
  } catch (error) {
    if (generation !== _loadGeneration) return;
    _loadState = _loadFailure(error);
  }
  _render();
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function _stars(b) {
  let out = `<span class="book-stars" data-id="${b.id}" role="radiogroup" aria-label="rating for ${esc(b.title)}">`;
  for (let i = 1; i <= 5; i++) out += `<button type="button" role="radio" aria-checked="${i === b.rating}" aria-label="${i} star${i > 1 ? 's' : ''}" class="book-star${i <= b.rating ? ' on' : ''}" data-rate="${i}" title="${i} star${i > 1 ? 's' : ''}">${_si(i <= b.rating ? 'star-fill' : 'star')}</button>`;
  return out + '</span>';
}

function _cover(b) {
  if (b.cover) {
    const ph = (b.title || '?')[0].toUpperCase();
    return `<img class="book-cover" src="${esc(b.cover)}" alt="" loading="lazy" data-ph="${esc(ph)}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'book-cover book-cover-ph',textContent:this.dataset.ph}))">`;
  }
  return `<div class="book-cover book-cover-ph">${esc((b.title || '?')[0].toUpperCase())}</div>`;
}

function _applyBookValue(id, field, value, scope) {
  if (!_createScopes.includes(scope)) return;
  const book = Object.values(_data.shelves).flat().find(book => book.id === id);
  if (book) book[field] = value;
}

function _rememberBookEdit(id, field, before, after, scope) {
  _applyBookValue(id, field, after, scope);
  if (before === after || typeof before !== typeof after || !_createScopes.includes(scope)) return;
  const edits = _bookUndo.get(id) || {};
  edits[field] = { before, after, scope };
  _bookUndo.set(id, edits);
}

function _undoControls(book) {
  const edits = _bookUndo.get(book.id);
  const buttons = ['rating', 'notes'].filter(field => edits?.[field] && edits[field].after === book[field]
    && !(field === 'notes' && _noteDrafts.has(book.id)))
    .map(field => `<button type="button" class="btn" data-undo="${field}">undo ${field === 'notes' ? 'note edit' : 'rating'}</button>`);
  return buttons.length ? `<div class="book-notes-actions book-undo-actions">${buttons.join('')}</div>` : '';
}

function _card(b) {
  const others = SHELVES.map(([k]) => k).filter(k => k !== b.status);
  return `
    <div class="book-card" data-id="${b.id}" role="group" aria-label="book: ${esc(b.title)}" tabindex="-1">
      ${_cover(b)}
      <div class="book-info">
        <div class="book-title">${esc(b.title)}</div>
        <div class="book-author">${esc(b.author || '')}${b.year ? ` · ${b.year}` : ''}</div>
        ${_stars(b)}
        ${_bookErrors.has(b.id) ? `<p class="book-notes-error book-write-error" role="alert">${esc(_bookErrors.get(b.id))}</p>` : ''}
        <div class="book-move">${others.map(k => `<button class="book-move-btn" data-move="${k}">${k === 'done' ? 'read' : k === 'reading' ? 'reading' : 'want'}</button>`).join('')}</div>
        ${b.id === _editingNotes
          ? `<div class="book-notes-edit"><textarea class="settings-input" data-f="notes" rows="3" placeholder="your notes…">${esc(_noteDrafts.get(b.id) ?? b.notes)}</textarea>${_noteErrors.has(b.id) ? `<p class="book-notes-error" role="alert">${esc(_noteErrors.get(b.id))}</p>` : ''}<div class="book-notes-actions"><button class="btn primary" data-act="save-notes">save</button><button class="btn" data-act="cancel-notes">cancel</button></div></div>`
          : (b.notes ? `<button type="button" class="book-notes" data-act="notes" aria-label="edit notes for ${esc(b.title)}">${esc(b.notes)}</button>` : `<button class="book-add-note" data-act="notes">+ note</button>`)}
        ${_undoControls(b)}
      </div>
      <button class="icon-btn danger book-del" data-act="del" title="remove">${_si('trash')}</button>
    </div>`;
}

function _render() {
  const body = $('books-body');
  if (!body) return;
  const active = document.activeElement;
  const editing = body.contains(active) && ['book-q', 'book-title', 'book-author'].includes(active.id)
    ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null;
  const editingNote = body.contains(active) && active.matches('[data-f="notes"]')
    ? { id: active.closest('.book-card').dataset.id, start: active.selectionStart, end: active.selectionEnd } : null;
  const buttonKey = body.contains(active) && active.matches('button')
    ? ['data-act', 'data-rate', 'data-move', 'data-undo', 'data-pick', 'data-val'].find(key => active.hasAttribute(key)) : null;
  const focusedButton = body.contains(active) && active.matches('button') && (active.id || buttonKey)
    ? { id: active.id, book: active.closest('.book-card')?.dataset.id, key: buttonKey, value: active.getAttribute(buttonKey) } : null;
  const shelves = _data.shelves || {};
  const shelfHtml = SHELVES.map(([k, label]) => {
    const list = shelves[k] || [];
    if (!list.length && !_adding) return '';
    return `<div class="book-shelf"><div class="book-shelf-h">${label} <span>${list.length}</span></div><div class="book-grid">${list.map(_card).join('')}</div></div>`;
  }).join('');
  const goal = _data.goal || 0, yr = _data.this_year || 0;
  const goalHtml = goal > 0
    ? `<button type="button" class="books-goal" data-act="set-goal" title="reading goal: click to change">
         <span>${yr} / ${goal} this year${yr >= goal ? ' ✓' : ''}</span>
         <div class="books-goal-bar"><i style="width:${Math.min(100, Math.round(yr / goal * 100))}%"></i></div>
       </button>`
    : `<button class="books-goal-set" data-act="set-goal">+ reading goal</button>`;
  body.innerHTML = `
    <div class="books-bar">
      <div class="books-summary">${_data.total ? `${_data.total} book${_data.total !== 1 ? 's' : ''}${goal ? '' : ` · ${yr} read this year`}` : ''}</div>
      ${goalHtml}
      <button class="btn" id="books-import" title="import a Goodreads export (.csv)">import</button>
      <button class="btn primary" id="books-add-toggle">${_si('plus')} book</button>
    </div>
    ${_loadNotice()}
    <p class="book-notes-error" id="book-create-error" role="alert" ${_createError || _recoveryError ? '' : 'hidden'}>${esc(_recoveryError || _createError)}</p>
    ${_recoveryError ? '<button class="btn" id="book-recovery-retry">retry save recovery</button>' : ''}
    ${_pendingCreate || _unreadableCreate ? `<div class="book-create-recovery"><p role="status">a book save still needs confirmation</p><div class="book-notes-actions">${_pendingCreate ? `<button class="btn" id="book-create-check" ${_createBusy ? 'disabled' : ''}>check saved book</button>` : ''}<button class="btn" id="book-create-discard" ${_createBusy ? 'disabled' : ''}>discard pending save</button></div></div>` : ''}
    ${_savedBook ? `<div class="book-create-result"><p role="status">saved ${esc(_savedBook.title)}</p><button class="btn" id="book-create-open">open saved book</button></div>` : ''}
    ${_adding ? _addForm() : ''}
    ${_data.total ? shelfHtml : (_adding || !_hasOverview || _loadState.state !== 'resting' ? '' : `
      <div class="empty-state">
        <div class="empty-state-icon">${_si('bookmark')}</div>
        <div class="empty-state-title">no books yet</div>
        <div class="empty-state-desc">track what you're reading, want to read, or have finished. search a title and alles autofills the cover, author and year.</div>
        <button class="btn primary" id="books-empty-add">${_si('plus')} add your first book</button>
      </div>`)}`;
  _wire(body);
  if (editing && body.getClientRects().length) {
    const field = $(editing.id);
    field?.focus();
    if (editing.start != null) field?.setSelectionRange(editing.start, editing.end);
  }
  if (editingNote && body.getClientRects().length) {
    const field = body.querySelector(`.book-card[data-id="${editingNote.id}"] [data-f="notes"]`);
    field?.focus();
    if (editingNote.start != null) field?.setSelectionRange(editingNote.start, editingNote.end);
  }
  if (focusedButton && body.getClientRects().length) {
    const button = [...body.querySelectorAll('button')].find(button => button.id === focusedButton.id
      && button.closest('.book-card')?.dataset.id === focusedButton.book
      && (!focusedButton.key || button.getAttribute(focusedButton.key) === focusedButton.value));
    if (button && !button.disabled) button.focus();
  }
}

function _addForm() {
  const draft = _pendingCreate ? { ..._pendingCreate.payload, query: '' } : _draft;
  const locked = _createBusy || _pendingCreate ? 'disabled' : '';
  return `
    <div class="book-add" aria-busy="${_createBusy}">
      <div class="book-add-row">
        <input type="text" id="book-q" class="settings-input" aria-label="search books to autofill" placeholder="search a title to autofill (or type one)…" spellcheck="false" value="${esc(draft.query)}" ${locked}>
        <button class="btn" id="book-search" ${locked || (_lookupBusy ? 'disabled' : '')}>${_lookupBusy ? 'searching…' : 'search'}</button>
      </div>
      ${_lookupMessage ? `<p class="book-lookup-notice ${_lookupFailed ? 'book-notes-error' : 'specialist-group-note'}" role="${_lookupFailed ? 'alert' : 'status'}">${esc(_lookupMessage)}</p>` : ''}
      ${_lookup.length ? `<div class="book-lookup">${_lookup.map((r, i) => `<button class="book-lookup-item" data-pick="${i}" ${locked}>${r.cover ? `<img src="${esc(r.cover)}" alt="" loading="lazy">` : '<span class="book-lk-ph"></span>'}<span><b>${esc(r.title)}</b><i>${esc(r.author)}${r.year ? ` · ${r.year}` : ''}</i></span></button>`).join('')}</div>` : ''}
      <div class="book-add-row">
        <label class="book-field" for="book-title">book title
          <input type="text" id="book-title" class="settings-input" aria-label="book title" placeholder="title" value="${esc(draft.title)}" ${locked}>
        </label>
        <label class="book-field" for="book-author">book author
          <input type="text" id="book-author" class="settings-input" aria-label="book author" placeholder="author" value="${esc(draft.author)}" ${locked}>
        </label>
      </div>
      <div class="book-add-row">
        <div class="te-seg" id="book-status" role="radiogroup" aria-label="book shelf">${SHELVES.map(([k]) => `<button type="button" role="radio" aria-checked="${draft.status === k}" class="te-seg-opt${draft.status === k ? ' active' : ''}" data-val="${k}" ${locked}>${k === 'done' ? 'read' : k === 'reading' ? 'reading' : 'want'}</button>`).join('')}</div>
        <button class="btn primary" id="book-create" ${_createBusy || !_createReady ? 'disabled' : ''}>${_createBusy ? 'saving…' : _pendingCreate ? 'retry save' : 'add'}</button>
        <button class="btn" id="book-cancel">close</button>
      </div>
    </div>`;
}

function _readCreateRecovery(scopes) {
  const previous = _pendingCreate;
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) {
    _createReady = false;
    throw new Error('book save recovery could not load; retry recovery before saving');
  }
  if (_createScopes.length && !scopes.some(scope => _createScopes.includes(scope))) {
    _bookUndo.clear();
    _pendingCreate = null; _savedBook = null; _draft = emptyDraft(); _lookup = [];
  }
  if (_pendingCreate && !scopes.includes(_pendingCreate.recovery_scope)) _pendingCreate = null;
  const preferred = _pendingCreate?.recovery_scope;
  _createScopes = scopes; _createReady = false; _pendingCreate = null;
  for (const scope of preferred ? [preferred, ...scopes.filter(scope => scope !== preferred)] : scopes) {
    try {
      const raw = sessionStorage.getItem(CREATE_PREFIX + scope);
      if (!raw) continue;
      const value = JSON.parse(raw), payload = value?.payload;
      if (!requestPattern.test(value?.request_id || '') || value.recovery_scope !== scope || !payload
        || ['title', 'author', 'cover', 'isbn'].some(key => typeof payload[key] !== 'string') || !payload.title.trim()
        || !SHELVES.some(([key]) => key === payload.status) || !Number.isSafeInteger(payload.year)) throw new Error('invalid pending book');
      _pendingCreate = value;
      if (value.request_id !== previous?.request_id || scope !== previous?.recovery_scope) _adding = true;
      break;
    } catch {
      _unreadableCreate = scope;
      throw new Error('could not read book save recovery; retry recovery or discard the pending save');
    }
  }
  _createReady = true; _unreadableCreate = ''; _recoveryError = '';
}

function _requestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function _discardCreate() {
  const pending = _pendingCreate, scope = pending?.recovery_scope || _unreadableCreate;
  const navigation = _viewGeneration;
  if (_createBusy || !scope || !await dlgConfirm('discard this pending book save? it may already be saved; check your books before adding it again.')) return;
  try {
    const key = CREATE_PREFIX + scope;
    if (pending && sessionStorage.getItem(key) !== JSON.stringify(pending)) throw new Error('recovery changed');
    sessionStorage.removeItem(key);
    if (sessionStorage.getItem(key) !== null) throw new Error('cleanup failed');
    _pendingCreate = null; _unreadableCreate = ''; _createError = ''; _recoveryError = '';
    _readCreateRecovery(_createScopes);
  } catch { _recoveryError = 'could not discard browser recovery; allow browser storage and retry'; }
  _render();
  if (navigation === _viewGeneration && $('books-body')?.getClientRects().length) (_pendingCreate ? $('book-create-check') : $('book-title'))?.focus();
}

async function _bookRequest(url, options, valid) {
  const response = await _fetcher(url, options);
  const result = await response.json().catch(() => null);
  if (options.method === 'DELETE' && response.status === 404) return { ok: true };
  if (!response.ok) {
    const error = new Error(typeof result?.detail === 'string' ? result.detail : 'could not confirm this change; try again');
    error.status = response.status;
    throw error;
  }
  if (!valid(result)) throw new Error('could not confirm this change; check saved books before retrying');
  return result;
}

async function _changeBook(card, options, valid, message, onSaved = () => {}) {
  const id = card.dataset.id;
  if (_writingBooks.has(id) || _savingNotes.has(id)) return;
  _writingBooks.add(id); _bookErrors.delete(id);
  card = [...document.querySelectorAll('#books-body .book-card')].find(item => item.dataset.id === id) || card;
  card.querySelector('.book-write-error')?.remove();
  const trigger = document.activeElement;
  const controls = [...card.querySelectorAll('button, textarea')].map(control => [control, control.disabled]);
  controls.forEach(([control]) => { control.disabled = true; });
  card.setAttribute('aria-busy', 'true');
  try {
    const saved = await _bookRequest(`/api/books/${id}`, options, valid);
    onSaved(saved);
    if (options.method === 'DELETE') _bookUndo.delete(id);
    toast(message, 'success');
    await loadBooks();
  } catch (failure) {
    const message = failure instanceof TypeError ? 'could not connect; check your connection and try again' : failure.message;
    _bookErrors.set(id, message);
    if (failure.status === 409) await loadBooks();
    const current = [...document.querySelectorAll('#books-body .book-card')].find(item => item.dataset.id === id);
    if (current) {
      let notice = current.querySelector('.book-write-error');
      if (!notice) { notice = document.createElement('p'); notice.className = 'book-notes-error book-write-error'; notice.setAttribute('role', 'alert'); current.querySelector('.book-info').append(notice); }
      notice.textContent = message;
      const book = Object.values(_data.shelves).flat().find(item => item.id === id);
      current.querySelectorAll('[data-rate]').forEach(radio => { radio.setAttribute('aria-checked', String(+radio.dataset.rate === book?.rating)); });
    }
    toast(message, 'error');
  } finally {
    _writingBooks.delete(id);
    card.removeAttribute('aria-busy');
    controls.forEach(([control, disabled]) => { control.disabled = disabled; });
    const current = [...document.querySelectorAll('#books-body .book-card')].find(item => item.dataset.id === id);
    if (current && current !== card && !_savingNotes.has(id)) {
      current.removeAttribute('aria-busy');
      current.querySelectorAll('button, textarea').forEach(control => { control.disabled = false; });
    }
    if ($('books-body')?.getClientRects().length && document.activeElement === document.body) {
      (trigger?.isConnected ? trigger : current || $('books-add-toggle'))?.focus();
    }
  }
}

function _wire(body) {
  body.querySelectorAll('.book-stars, #book-status').forEach(group => wireChoiceGroup(group));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => loadBooks());
  const toggleForm = () => { _adding = !_adding; ++_lookupGeneration; _lookupBusy = false; _lookup = []; _lookupMessage = ''; _render(); if (_adding) $('book-title')?.focus(); };
  $('books-add-toggle')?.addEventListener('click', toggleForm);
  $('books-empty-add')?.addEventListener('click', toggleForm);
  $('book-recovery-retry')?.addEventListener('click', () => loadBooks());
  $('book-create-check')?.addEventListener('click', () => _create(true));
  $('book-create-discard')?.addEventListener('click', _discardCreate);
  $('book-create-open')?.addEventListener('click', () => focusBook(_savedBook.id));
  $('books-import')?.addEventListener('click', () => {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.csv,text/csv';
    inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return;
      try {
        const d = await _bookRequest('/api/books/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: await f.text() }) }, result => Number.isInteger(result?.imported) && result.imported >= 0);
        toast(`imported ${d.imported} book${d.imported === 1 ? '' : 's'}`, 'success'); await loadBooks();
      } catch (error) { toast(error instanceof TypeError ? 'could not connect; select the file again to retry' : error.message, 'error'); }
    };
    inp.click();
  });
  body.querySelector('[data-act="set-goal"]')?.addEventListener('click', async () => {
    const v = await dlgPrompt('books to read this year? (0 to turn off)', _goalDraft?.value ?? String(_data.goal || 0), { validate: value => /^\d+$/.test(value.trim()) && Number.isSafeInteger(Number(value)) ? '' : 'enter a whole number, 0 or more' });
    if (v == null) return;
    const n = Number(v), draft = { value: v }; _goalDraft = draft;
    try {
      await _bookRequest('/api/books/goal', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ goal: n }) }, result => result?.goal === n);
      if (_goalDraft === draft) _goalDraft = null;
      await loadBooks();
    } catch (error) { toast(error instanceof TypeError ? 'could not connect; open the reading goal to retry' : error.message, 'error'); }
  });

  if (_adding) {
    const doSearch = async () => {
      const query = _draft.query.trim();
      if (!query || _createBusy || _pendingCreate) return;
      const generation = ++_lookupGeneration;
      _lookupBusy = true; _lookup = []; _lookupMessage = ''; _lookupFailed = false;
      _render();
      try {
        const result = await _bookRequest('/api/books/lookup?q=' + encodeURIComponent(query), {}, value => Array.isArray(value?.results) && value.results.every(row => typeof row?.title === 'string' && typeof row.author === 'string'));
        if (generation !== _lookupGeneration || !_adding || _pendingCreate) return;
        _lookup = result.results;
        _lookupMessage = _lookup.length ? '' : 'no books found; try another search or enter the details yourself';
      } catch (error) {
        if (generation !== _lookupGeneration || !_adding || _pendingCreate) return;
        _lookupFailed = true; _lookupMessage = 'could not look up books; retry or enter the details yourself';
      } finally {
        if (generation === _lookupGeneration) {
          _lookupBusy = false; _render();
          if ($('books-body')?.getClientRects().length && document.activeElement === document.body) ($('book-search') || $('book-title'))?.focus();
        }
      }
    };
    $('book-search')?.addEventListener('click', doSearch);
    $('book-q')?.addEventListener('input', event => {
      _draft.query = event.target.value; ++_lookupGeneration; _lookupBusy = false; _lookup = []; _lookupMessage = '';
      body.querySelector('.book-lookup')?.remove();
      body.querySelector('.book-lookup-notice')?.remove();
      const search = $('book-search');
      search.disabled = false; search.textContent = 'search';
    });
    $('book-q')?.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) void doSearch(); });
    for (const field of ['title', 'author']) $('book-' + field)?.addEventListener('input', event => {
      _draft[field] = event.target.value;
      if (field === 'title') Object.assign(_draft, { cover: '', isbn: '', year: 0 });
    });
    body.querySelectorAll('.book-lookup-item').forEach(button => button.addEventListener('click', () => {
      if (_createBusy || _pendingCreate) return;
      const result = _lookup[+button.dataset.pick];
      Object.assign(_draft, { title: result.title, author: result.author || '', cover: result.cover || '', isbn: result.isbn || '', year: Number.isSafeInteger(result.year) ? result.year : 0 });
      _lookup = []; ++_lookupGeneration; _lookupBusy = false; _lookupMessage = ''; _render(); $('book-title')?.focus();
    }));
    body.querySelectorAll('#book-status .te-seg-opt').forEach(option => option.addEventListener('click', () => {
      if (_createBusy || _pendingCreate) return;
      _draft.status = option.dataset.val;
      body.querySelectorAll('#book-status .te-seg-opt').forEach(other => other.classList.toggle('active', other === option));
    }));
    $('book-create')?.addEventListener('click', () => _create());
    $('book-cancel')?.addEventListener('click', () => { _adding = false; _lookup = []; ++_lookupGeneration; _lookupBusy = false; _lookupMessage = ''; _render(); $('books-add-toggle')?.focus(); });
  }

  body.querySelectorAll('.book-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelector('[data-f="notes"]')?.addEventListener('input', e => {
      _noteDrafts.set(id, e.target.value);
    });
    if (_savingNotes.has(id) || _writingBooks.has(id)) {
      card.setAttribute('aria-busy', 'true');
      card.querySelectorAll('button, textarea').forEach(control => { control.disabled = true; });
    }
    card.querySelectorAll('.book-star').forEach(s => s.addEventListener('click', async () => {
      const before = Object.values(_data.shelves).flat().find(book => book.id === id)?.rating;
      const scope = _createScopes[0];
      await _changeBook(card, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ rating: +s.dataset.rate }) }, result => result?.id === id && result.rating === +s.dataset.rate, 'rating saved', result => _rememberBookEdit(id, 'rating', before, result.rating, scope));
    }));
    card.querySelectorAll('[data-undo]').forEach(button => button.addEventListener('click', async () => {
      const field = button.dataset.undo;
      const edit = _bookUndo.get(id)?.[field];
      if (!edit) return;
      await _changeBook(card, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ [field]: edit.before, [`expected_${field}`]: edit.after, recovery_scope: edit.scope }) }, result => result?.id === id && result[field] === edit.before, `${field === 'notes' ? 'previous note' : 'previous rating'} restored`, result => {
        _applyBookValue(id, field, result[field], edit.scope);
        const edits = _bookUndo.get(id);
        if (edits) delete edits[field];
      });
    }));
    card.querySelectorAll('[data-move]').forEach(btn => btn.addEventListener('click', async () => {
      await _changeBook(card, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ status: btn.dataset.move }) }, result => result?.id === id && result.status === btn.dataset.move, `moved to ${btn.dataset.move}`);
    }));
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'notes') { _editingNotes = id; _render(); body.querySelector('.book-notes-edit textarea')?.focus(); return; }
      if (act === 'cancel-notes') { _noteDrafts.delete(id); _noteErrors.delete(id); _editingNotes = null; _render(); body.querySelector(`.book-card[data-id="${id}"] [data-act="notes"]`)?.focus(); return; }
      if (act === 'save-notes') {
        if (_savingNotes.has(id)) return;
        const v = card.querySelector('[data-f="notes"]').value;
        const before = Object.values(_data.shelves).flat().find(book => book.id === id)?.notes;
        const scope = _createScopes[0];
        _noteDrafts.set(id, v);
        _noteErrors.delete(id);
        _savingNotes.add(id);
        _render();
        try {
          await _bookRequest(`/api/books/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ notes: v }) }, result => result?.id === id && result.notes === v);
          _rememberBookEdit(id, 'notes', before, v, scope);
          _noteDrafts.delete(id);
          if (_editingNotes === id) _editingNotes = null;
          toast('saved', 'success');
          await loadBooks();
        } catch (error) {
          _noteErrors.set(id, error instanceof TypeError ? 'Could not connect. Check your connection and try again.' : (error.message || 'Notes could not be saved. Try again.'));
        } finally {
          _savingNotes.delete(id);
          _render();
          if (body.getClientRects().length && document.activeElement === document.body) {
            body.querySelector(`.book-card[data-id="${id}"] ${_editingNotes === id ? 'textarea' : '[data-act="notes"]'}`)?.focus();
          }
        }
        return;
      }
      if (act === 'del') {
        if (!await dlgConfirm('remove this book?')) return;
        await _changeBook(card, { method: 'DELETE' }, result => result?.ok === true, 'removed'); return;
      }
    }));
  });
}

async function _create(checkOnly = false) {
  if (_createBusy || !_createReady) return;
  if (!_pendingCreate && !_draft.title.trim()) { _createError = 'title needed'; _render(); $('book-title')?.focus(); return; }
  const navigation = _viewGeneration;
  const mayFocus = () => navigation === _viewGeneration && $('books-body')?.getClientRects().length && document.activeElement === document.body;
  _createBusy = true; _createError = ''; _savedBook = null;
  ++_lookupGeneration; _lookupBusy = false; _lookup = []; _lookupMessage = '';
  _render();
  try {
    const { query, ...payload } = _draft;
    const pending = _pendingCreate || { payload: { ...payload, title: payload.title.trim(), author: payload.author.trim() }, request_id: _requestId(), recovery_scope: _createScopes[0] };
    const key = CREATE_PREFIX + pending.recovery_scope, raw = JSON.stringify(pending);
    sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(key) !== raw) throw new Error('could not keep this book for retry');
    if (!_pendingCreate) _draft = emptyDraft();
    _pendingCreate = pending;
    _render();
    const result = await _bookRequest(checkOnly ? `/api/books/requests/${encodeURIComponent(pending.request_id)}?recovery_scope=${encodeURIComponent(pending.recovery_scope)}` : '/api/books',
      checkOnly ? { cache: 'no-store' } : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...pending.payload, request_id: pending.request_id, recovery_scope: pending.recovery_scope }) },
      value => value?.request_id === pending.request_id && typeof value.id === 'string' && !!value.id && typeof value.title === 'string');
    if (!_createScopes.includes(pending.recovery_scope)) throw new Error('book storage changed; reopen books');
    _savedBook = result;
    if (sessionStorage.getItem(key) === raw) {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error('book saved; browser recovery could not be cleared. check saved book again.');
    }
    if (_pendingCreate?.request_id === pending.request_id) _pendingCreate = null;
    _adding = false;
    _readCreateRecovery(_createScopes);
    toast('book saved', 'success');
    await loadBooks();
  } catch (error) {
    _createError = error instanceof TypeError ? 'could not connect; your book is kept for retry' : error.message || 'could not save this book; retry';
    toast(_createError, 'error');
  } finally {
    _createBusy = false;
    const focus = mayFocus();
    _render();
    if (focus) (_savedBook ? $('book-create-open') : _pendingCreate ? $('book-create') || $('book-create-check') : $('book-title'))?.focus();
  }
}

export function focusBook(id) {
  const card = [...document.querySelectorAll('#books-body .book-card')].find(item => item.dataset.id === id);
  if (!card) {
    toast('book is no longer available', 'error');
    $('books-add-toggle')?.focus();
    return false;
  }
  card.focus();
  return true;
}
