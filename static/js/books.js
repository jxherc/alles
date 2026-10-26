// books — a reading list with shelves (want / reading / done), covers, star ratings,
// notes, and a keyless OpenLibrary lookup to autofill. mirrors the panel conventions.
import { toast } from './util.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { wireChoiceGroup } from './kokuen.js?v=4';
import { t, tp } from './i18n.js';
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

// labels are catalog keys, translated at render
const SHELVES = [['reading', 'books.shelf_reading'], ['want', 'books.shelf_want'], ['done', 'books.shelf_done']];
const _moveLabel = k => t(k === 'done' ? 'books.move_done' : k === 'reading' ? 'books.move_reading' : 'books.move_want');

export function initBooks(fetcher = fetch) {
  ++_viewGeneration;
  _fetcher = fetcher;
  return loadBooks(fetcher);
}

function _loadFailure(error) {
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
  const retained = _hasOverview;
  return {
    state: offline ? 'offline' : 'error',
    message: t(offline ? (retained ? 'books.load_offline_kept' : 'books.load_offline') : (retained ? 'books.load_failed_kept' : 'books.load_failed')),
  };
}

function _loadNotice() {
  if (_loadState.state === 'resting') return '';
  const loading = _loadState.state === 'loading';
  return `<div class="specialist-group-note legacy-load-note" role="${loading ? 'status' : 'alert'}" aria-live="${loading ? 'polite' : 'assertive'}" data-kokuen-state="${_loadState.state}">
    <span>${esc(_loadState.message)}</span>${loading ? '' : `<button type="button" class="btn" data-act="retry-load">${t('common.retry')}</button>`}
  </div>`;
}

export async function loadBooks(fetcher = _fetcher) {
  const generation = ++_loadGeneration;
  _fetcher = fetcher;
  _loadState = { state: 'loading', message: t('books.loading') };
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
  let out = `<span class="book-stars" data-id="${b.id}" role="radiogroup" aria-label="${esc(t('books.rating_for', { title: b.title }))}">`;
  for (let i = 1; i <= 5; i++) out += `<button type="button" role="radio" aria-checked="${i === b.rating}" aria-label="${esc(tp('books.stars', i))}" class="book-star${i <= b.rating ? ' on' : ''}" data-rate="${i}" title="${esc(tp('books.stars', i))}">${_si(i <= b.rating ? 'star-fill' : 'star')}</button>`;
  return out + '</span>';
}

// a cover that won't load becomes the letter placeholder. error doesn't bubble, so it's caught
// on the way down (the csp blocks the inline onerror this used to be)
if (typeof document !== 'undefined') document.addEventListener?.('error', e => {
  const img = e.target;
  if (!img?.matches?.('img.book-cover')) return;
  img.replaceWith(Object.assign(document.createElement('div'), { className: 'book-cover book-cover-ph', textContent: img.dataset.ph }));
}, true);

function _cover(b) {
  if (b.cover) {
    const ph = (b.title || '?')[0].toUpperCase();
    return `<img class="book-cover" src="${esc(b.cover)}" alt="" loading="lazy" data-ph="${esc(ph)}">`;
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
    .map(field => `<button type="button" class="btn" data-undo="${field}">${t(field === 'notes' ? 'books.undo_note' : 'books.undo_rating')}</button>`);
  return buttons.length ? `<div class="book-notes-actions book-undo-actions">${buttons.join('')}</div>` : '';
}

function _card(b) {
  const others = SHELVES.map(([k]) => k).filter(k => k !== b.status);
  return `
    <div class="book-card" data-id="${b.id}" role="group" aria-label="${esc(t('books.card_label', { title: b.title }))}" tabindex="-1">
      ${_cover(b)}
      <div class="book-info">
        <div class="book-title">${esc(b.title)}</div>
        <div class="book-author">${esc(b.author || '')}${b.year ? ` · ${b.year}` : ''}</div>
        ${_stars(b)}
        ${_bookErrors.has(b.id) ? `<p class="book-notes-error book-write-error" role="alert">${esc(_bookErrors.get(b.id))}</p>` : ''}
        <div class="book-move">${others.map(k => `<button class="book-move-btn" data-move="${k}">${_moveLabel(k)}</button>`).join('')}</div>
        ${b.id === _editingNotes
          ? `<div class="book-notes-edit"><textarea class="settings-input" data-f="notes" rows="3" placeholder="${esc(t('books.notes_placeholder'))}">${esc(_noteDrafts.get(b.id) ?? b.notes)}</textarea>${_noteErrors.has(b.id) ? `<p class="book-notes-error" role="alert">${esc(_noteErrors.get(b.id))}</p>` : ''}<div class="book-notes-actions"><button class="btn primary" data-act="save-notes">${t('common.save')}</button><button class="btn" data-act="cancel-notes">${t('common.cancel')}</button></div></div>`
          : (b.notes ? `<button type="button" class="book-notes" data-act="notes" aria-label="${esc(t('books.edit_notes_for', { title: b.title }))}">${esc(b.notes)}</button>` : `<button class="book-add-note" data-act="notes">${t('books.add_note')}</button>`)}
        ${_undoControls(b)}
      </div>
      <button class="icon-btn danger book-del" data-act="del" title="${esc(t('common.remove'))}">${_si('trash')}</button>
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
    return `<div class="book-shelf"><div class="book-shelf-h">${t(label)} <span>${list.length}</span></div><div class="book-grid">${list.map(_card).join('')}</div></div>`;
  }).join('');
  const goal = _data.goal || 0, yr = _data.this_year || 0;
  const goalHtml = goal > 0
    ? `<button type="button" class="books-goal" data-act="set-goal" title="${esc(t('books.goal_title'))}">
         <span>${t('books.goal_progress', { read: yr, goal })}${yr >= goal ? ` ${_si('check')}` : ''}</span>
         <div class="books-goal-bar"><i style="width:${Math.min(100, Math.round(yr / goal * 100))}%"></i></div>
       </button>`
    : `<button class="books-goal-set" data-act="set-goal">${t('books.set_goal')}</button>`;
  body.innerHTML = `
    <div class="books-bar">
      <div class="books-summary">${_data.total ? `${tp('books.count', _data.total)}${goal ? '' : ` · ${tp('books.read_this_year', yr)}`}` : ''}</div>
      ${goalHtml}
      <button class="btn" id="books-import" title="${esc(t('books.import_title'))}">${t('books.import')}</button>
      <button class="btn primary" id="books-add-toggle">${_si('plus')} ${t('books.add_book')}</button>
    </div>
    ${_loadNotice()}
    <p class="book-notes-error" id="book-create-error" role="alert" ${_createError || _recoveryError ? '' : 'hidden'}>${esc(_recoveryError || _createError)}</p>
    ${_recoveryError ? `<button class="btn" id="book-recovery-retry">${t('books.retry_save_recovery')}</button>` : ''}
    ${_pendingCreate || _unreadableCreate ? `<div class="book-create-recovery"><p role="status">${_createBusy ? t('books.saving_book') : t('books.create_pending')}</p><div class="book-notes-actions">${_pendingCreate ? `<button class="btn" id="book-create-check" ${_createBusy ? 'disabled' : ''}>${t('books.check_saved')}</button>` : ''}<button class="btn" id="book-create-discard" ${_createBusy ? 'disabled' : ''}>${t('books.discard_pending')}</button></div></div>` : ''}
    ${_savedBook ? `<div class="book-create-result"><p role="status">${esc(t('books.saved_named', { title: _savedBook.title }))}</p><button class="btn" id="book-create-open">${t('books.open_saved')}</button></div>` : ''}
    ${_adding ? _addForm() : ''}
    ${_data.total ? shelfHtml : (_adding || !_hasOverview || _loadState.state !== 'resting' ? '' : `
      <div class="empty-state">
        <div class="empty-state-icon">${_si('bookmark')}</div>
        <div class="empty-state-title">${t('books.empty_title')}</div>
        <div class="empty-state-desc">${t('books.empty_desc')}</div>
        <button type="button" class="btn" id="books-empty-add">${_si('plus')} ${t('books.add_first')}</button>
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
        <input type="text" id="book-q" class="settings-input" aria-label="${esc(t('books.search_label'))}" placeholder="${esc(t('books.search_placeholder'))}" spellcheck="false" value="${esc(draft.query)}" ${locked}>
        <button class="btn" id="book-search" ${locked || (_lookupBusy ? 'disabled' : '')}>${_lookupBusy ? t('books.searching') : t('common.search')}</button>
      </div>
      ${_lookupMessage ? `<p class="book-lookup-notice ${_lookupFailed ? 'book-notes-error' : 'specialist-group-note'}" role="${_lookupFailed ? 'alert' : 'status'}">${esc(_lookupMessage)}</p>` : ''}
      ${_lookup.length ? `<div class="book-lookup">${_lookup.map((r, i) => `<button class="book-lookup-item" data-pick="${i}" ${locked}>${r.cover ? `<img src="${esc(r.cover)}" alt="" loading="lazy">` : '<span class="book-lk-ph"></span>'}<span><b>${esc(r.title)}</b><i>${esc(r.author)}${r.year ? ` · ${esc(r.year)}` : ''}</i></span></button>`).join('')}</div>` : ''}
      <div class="book-add-row">
        <label class="book-field" for="book-title">${t('books.title_label')}
          <input type="text" id="book-title" class="settings-input" aria-label="${esc(t('books.title_label'))}" placeholder="${esc(t('books.title_placeholder'))}" value="${esc(draft.title)}" ${locked}>
        </label>
        <label class="book-field" for="book-author">${t('books.author_label')}
          <input type="text" id="book-author" class="settings-input" aria-label="${esc(t('books.author_label'))}" placeholder="${esc(t('books.author_placeholder'))}" value="${esc(draft.author)}" ${locked}>
        </label>
      </div>
      <div class="book-add-row">
        <div class="te-seg" id="book-status" role="radiogroup" aria-label="${esc(t('books.shelf_label'))}">${SHELVES.map(([k]) => `<button type="button" role="radio" aria-checked="${draft.status === k}" class="te-seg-opt${draft.status === k ? ' active' : ''}" data-val="${k}" ${locked}>${_moveLabel(k)}</button>`).join('')}</div>
        <button class="btn primary" id="book-create" ${_createBusy || !_createReady ? 'disabled' : ''}>${_createBusy ? t('common.saving') : _pendingCreate ? t('books.retry_save') : t('common.add')}</button>
        <button class="btn" id="book-cancel">${t('common.close')}</button>
      </div>
    </div>`;
}

function _readCreateRecovery(scopes) {
  const previous = _pendingCreate;
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) {
    _createReady = false;
    throw new Error(t('books.recovery_failed'));
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
      throw new Error(t('books.recovery_unreadable'));
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
  if (_createBusy || !scope || !await dlgConfirm(t('books.discard_confirm'))) return;
  try {
    const key = CREATE_PREFIX + scope;
    if (pending && sessionStorage.getItem(key) !== JSON.stringify(pending)) throw new Error('recovery changed');
    sessionStorage.removeItem(key);
    if (sessionStorage.getItem(key) !== null) throw new Error('cleanup failed');
    _pendingCreate = null; _unreadableCreate = ''; _createError = ''; _recoveryError = '';
    _readCreateRecovery(_createScopes);
  } catch { _recoveryError = t('books.discard_recovery_failed'); }
  _render();
  if (navigation === _viewGeneration && $('books-body')?.getClientRects().length) (_pendingCreate ? $('book-create-check') : $('book-title'))?.focus();
}

async function _bookRequest(url, options, valid) {
  const response = await _fetcher(url, options);
  const result = await response.json().catch(() => null);
  if (options.method === 'DELETE' && response.status === 404) return { ok: true };
  if (!response.ok) {
    const error = new Error(typeof result?.detail === 'string' ? result.detail : t('books.change_unconfirmed'));
    error.status = response.status;
    throw error;
  }
  if (!valid(result)) throw new Error(t('books.change_unverified'));
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
    const message = failure instanceof TypeError ? t('books.connect_failed') : failure.message;
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
        toast(tp('books.imported', d.imported), 'success'); await loadBooks();
      } catch (error) { toast(error instanceof TypeError ? t('books.import_connect_failed') : error.message, 'error'); }
    };
    inp.click();
  });
  body.querySelector('[data-act="set-goal"]')?.addEventListener('click', async () => {
    const v = await dlgPrompt('', _goalDraft?.value ?? String(_data.goal || 0), { title: t('books.goal_dialog_title'), label: t('books.goal_label'), hint: t('books.goal_hint'), confirmLabel: t('books.goal_save'), validate: value => /^\d+$/.test(value.trim()) && Number.isSafeInteger(Number(value)) ? '' : t('books.goal_invalid') });
    if (v == null) return;
    const n = Number(v), draft = { value: v }; _goalDraft = draft;
    try {
      await _bookRequest('/api/books/goal', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ goal: n }) }, result => result?.goal === n);
      if (_goalDraft === draft) _goalDraft = null;
      await loadBooks();
    } catch (error) { toast(error instanceof TypeError ? t('books.goal_connect_failed') : error.message, 'error'); }
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
        _lookupMessage = _lookup.length ? '' : t('books.lookup_empty');
      } catch (error) {
        if (generation !== _lookupGeneration || !_adding || _pendingCreate) return;
        _lookupFailed = true; _lookupMessage = t('books.lookup_failed');
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
      search.disabled = false; search.textContent = t('common.search');
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
      await _changeBook(card, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ rating: +s.dataset.rate, expected_rating: before, recovery_scope: scope }) }, result => result?.id === id && result.rating === +s.dataset.rate, t('books.rating_saved'), result => _rememberBookEdit(id, 'rating', before, result.rating, scope));
    }));
    card.querySelectorAll('[data-undo]').forEach(button => button.addEventListener('click', async () => {
      const field = button.dataset.undo;
      const edit = _bookUndo.get(id)?.[field];
      if (!edit) return;
      await _changeBook(card, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ [field]: edit.before, [`expected_${field}`]: edit.after, recovery_scope: edit.scope }) }, result => result?.id === id && result[field] === edit.before, t(field === 'notes' ? 'books.note_restored' : 'books.rating_restored'), result => {
        _applyBookValue(id, field, result[field], edit.scope);
        const edits = _bookUndo.get(id);
        if (edits) delete edits[field];
      });
    }));
    card.querySelectorAll('[data-move]').forEach(btn => btn.addEventListener('click', async () => {
      await _changeBook(card, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ status: btn.dataset.move }) }, result => result?.id === id && result.status === btn.dataset.move, t(btn.dataset.move === 'done' ? 'books.moved_done' : btn.dataset.move === 'reading' ? 'books.moved_reading' : 'books.moved_want'));
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
          await _bookRequest(`/api/books/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ notes: v, expected_notes: before, recovery_scope: scope }) }, result => result?.id === id && result.notes === v);
          _rememberBookEdit(id, 'notes', before, v, scope);
          _noteDrafts.delete(id);
          if (_editingNotes === id) _editingNotes = null;
          toast(t('common.saved'), 'success');
          await loadBooks();
        } catch (error) {
          _noteErrors.set(id, error instanceof TypeError ? t('books.notes_connect_failed') : (error.message || t('books.notes_failed')));
          if (error.status === 409) await loadBooks();
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
        const book = Object.values(_data.shelves).flat().find(book => book.id === id);
        if (!book) return;
        if (!await dlgConfirm(t('books.remove_confirm', { title: book.title }), { confirmLabel: t('books.remove_book') })) return;
        await _changeBook(card, { method: 'DELETE' }, result => result?.ok === true, t('books.removed')); return;
      }
    }));
  });
}

async function _create(checkOnly = false) {
  if (_createBusy || !_createReady) return;
  if (!_pendingCreate && !_draft.title.trim()) { _createError = t('books.title_required'); _render(); $('book-title')?.focus(); return; }
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
    if (sessionStorage.getItem(key) !== raw) throw new Error(t('books.keep_failed'));
    if (!_pendingCreate) _draft = emptyDraft();
    _pendingCreate = pending;
    _render();
    const result = await _bookRequest(checkOnly ? `/api/books/requests/${encodeURIComponent(pending.request_id)}?recovery_scope=${encodeURIComponent(pending.recovery_scope)}` : '/api/books',
      checkOnly ? { cache: 'no-store' } : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...pending.payload, request_id: pending.request_id, recovery_scope: pending.recovery_scope }) },
      value => value?.request_id === pending.request_id && typeof value.id === 'string' && !!value.id && typeof value.title === 'string');
    if (!_createScopes.includes(pending.recovery_scope)) throw new Error(t('books.storage_changed'));
    _savedBook = result;
    if (sessionStorage.getItem(key) === raw) {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error(t('books.cleanup_failed'));
    }
    if (_pendingCreate?.request_id === pending.request_id) _pendingCreate = null;
    _adding = false;
    _readCreateRecovery(_createScopes);
    toast(t('books.book_saved'), 'success');
    await loadBooks();
  } catch (error) {
    _createError = error instanceof TypeError ? t('books.create_connect_failed') : error.message || t('books.create_failed');
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
    toast(t('books.unavailable'), 'error');
    $('books-add-toggle')?.focus();
    return false;
  }
  card.focus();
  return true;
}
