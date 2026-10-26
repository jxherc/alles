// read — a read-later archive. paste a URL, alles fetches + stores the readable text
// (reusing the research extractor) so it's searchable offline and the link can't rot.
// list + reader views; mirrors the watch/habits panel conventions.
import { toast, _safeUrl } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';
import { wireChoiceGroup } from './kokuen.js?v=4';
import { readingPlace } from './reading_place.js';
import { loadReadingNoteRecovery, takeReadingNote } from './reading_note.js';
import { clearLinkedRecord } from './recordlinks.js';
import { formatList, t, tp } from './i18n.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _items = [];
let _stats = null;
let _filter = 'all';
let _q = '';
let _tag = '';
let _urlDraft = '';
let _saveError = '';
let _saving = false;
let _saveScopes = [];
let _saveReady = false;
let _saveRecoveryError = '';
let _pendingSave = null;
let _unreadableSave = '';
let _savedURL = null;
const SAVE_PREFIX = 'alles.read.pending.v1:';
const requestPattern = /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
let _returnItem = null;
let _open = null;   // full item being read
let _feeds = [];
let _showFeeds = false;
let _feedDraft = '';
let _feedBusy = false;
let _feedListLoading = false;
let _feedListError = '';
let _feedLoadGeneration = 0;
let _feedMessage = '';
let _feedFailed = false;
const _feedErrors = new Map();
let _fetcher = fetch;
let _hasItems = false;
let _hasStats = false;
let _itemsCurrent = false;
let _loadState = { state: 'resting', message: '' };
let _detachPlace = () => {};
const _places = new Map();
const _textFetches = new Map();

export function initRead(fetcher = fetch) {
  ++_openGeneration;
  _fetcher = fetcher;
  void loadReadingNoteRecovery();
  return loadRead(fetcher);
}

async function loadFeeds() {
  const generation = ++_feedLoadGeneration;
  _feedListLoading = true;
  try {
    const result = await _json(_fetcher, '/api/read/feeds');
    if (!Array.isArray(result?.feeds) || result.feeds.some(feed => typeof feed.id !== 'string' || typeof feed.url !== 'string')) throw new Error('invalid feed list');
    if (generation === _feedLoadGeneration) { _feeds = result.feeds; _feedListError = ''; }
  } catch {
    if (generation === _feedLoadGeneration) _feedListError = t('read.feeds_load_failed');
  } finally {
    if (generation === _feedLoadGeneration) _feedListLoading = false;
  }
}

async function _feedRequest(url, options, valid) {
  const response = await _fetcher(url, options);
  const result = await response.json().catch(() => null);
  if (options.method === 'DELETE' && response.status === 404) return { ok: true };
  if (!response.ok) throw Object.assign(new Error(typeof result?.detail === 'string' ? result.detail : t('read.feed_change_unconfirmed')), { status: response.status });
  if (!valid(result)) throw new Error(t('read.feed_result_unconfirmed'));
  return result;
}

async function _changeFeeds(work, focusId) {
  if (_feedBusy || _feedListLoading) return;
  const navigation = _openGeneration;
  _feedBusy = true; _feedMessage = ''; _feedFailed = false;
  _render();
  try { await work(); }
  catch (error) {
    _feedFailed = true;
    _feedMessage = error instanceof TypeError ? t('read.connect_failed') : error.message;
  } finally {
    _feedBusy = false;
    _render();
    if (navigation === _openGeneration && $('read-body')?.getClientRects().length && document.activeElement === document.body) $(focusId)?.focus();
  }
}

async function _json(fetcher, url) {
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`request failed (${response.status || 'unknown'})`);
  return response.json();
}

function _readSaveRecovery(scopes) {
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) {
    _saveReady = false;
    throw new Error(t('read.save_recovery_failed'));
  }
  if (_saveScopes.length && !scopes.some(scope => _saveScopes.includes(scope))) {
    _pendingSave = null; _savedURL = null; _urlDraft = '';
  }
  if (_pendingSave && !scopes.includes(_pendingSave.recovery_scope)) {
    _pendingSave = null; _savedURL = null;
  }
  const preferred = _pendingSave?.recovery_scope;
  _saveScopes = scopes;
  _saveReady = false;
  _pendingSave = null;
  for (const scope of preferred ? [preferred, ...scopes.filter(scope => scope !== preferred)] : scopes) {
    try {
      const raw = sessionStorage.getItem(SAVE_PREFIX + scope);
      if (!raw) continue;
      const value = JSON.parse(raw);
      if (!requestPattern.test(value?.request_id || '') || typeof value.url !== 'string' || !value.url.trim() || value.recovery_scope !== scope) throw new Error('invalid pending URL');
      _pendingSave = value;
      break;
    } catch {
      _unreadableSave = scope;
      throw new Error(t('read.save_recovery_unreadable'));
    }
  }
  _saveReady = true; _unreadableSave = ''; _saveRecoveryError = '';
}

function _urlRequestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function _keepUrlSave(pending) {
  const key = SAVE_PREFIX + pending.recovery_scope, raw = JSON.stringify(pending);
  sessionStorage.setItem(key, raw);
  if (sessionStorage.getItem(key) !== raw) throw new Error(t('read.save_keep_failed'));
  if (!_pendingSave && _urlDraft.trim() === pending.url) _urlDraft = '';
  _pendingSave = pending;
}

function _confirmUrlSave(result, pending) {
  if (!result || result.request_id !== pending.request_id || typeof result.id !== 'string' || !result.id.trim()
    || typeof result.url !== 'string' || !result.url.trim() || !Number.isInteger(result.read_minutes) || result.read_minutes < 1) {
    throw new Error(t('read.save_unconfirmed'));
  }
  if (!_saveScopes.includes(pending.recovery_scope)) throw new Error(t('read.storage_changed'));
  _savedURL = result;
  const key = SAVE_PREFIX + pending.recovery_scope;
  try {
    if (sessionStorage.getItem(key) === JSON.stringify(pending)) {
      sessionStorage.removeItem(key);
      if (sessionStorage.getItem(key) !== null) throw new Error('cleanup failed');
    }
  } catch {
    _saveError = t('read.save_cleanup_failed');
    return;
  }
  if (_pendingSave?.request_id === pending.request_id) _pendingSave = null;
  try { _readSaveRecovery(_saveScopes); }
  catch (error) { _saveRecoveryError = error.message; }
}

async function _discardUrlSave() {
  const pending = _pendingSave, scope = pending?.recovery_scope || _unreadableSave;
  const navigation = _openGeneration;
  if (_saving || !scope || !await dlgConfirm(t('read.discard_pending_confirm'))) return;
  try {
    const key = SAVE_PREFIX + scope;
    if (pending && sessionStorage.getItem(key) !== JSON.stringify(pending)) throw new Error('recovery changed');
    sessionStorage.removeItem(key);
    if (sessionStorage.getItem(key) !== null) throw new Error('cleanup failed');
    _pendingSave = null; _unreadableSave = ''; _saveError = ''; _saveRecoveryError = '';
    _readSaveRecovery(_saveScopes);
  } catch { _saveRecoveryError = t('read.discard_recovery_failed'); }
  _render();
  if (navigation === _openGeneration && $('read-body')?.getClientRects().length) {
    (_pendingSave ? $('read-save-check') : $('read-url'))?.focus();
  }
}

function _loadFailure(failures, successes) {
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
  if (successes.length) {
    const unavailable = formatList(failures.map(([name]) => name));
    return {
      state: 'partial',
      message: t('read.load_partial', { parts: unavailable }),
    };
  }
  const retained = _hasItems || _hasStats;
  return {
    state: offline ? 'offline' : 'error',
    message: t(offline ? (retained ? 'read.load_offline_kept' : 'read.load_offline') : (retained ? 'read.load_failed_kept' : 'read.load_failed')),
  };
}

function _loadNotice() {
  if (_loadState.state === 'resting') return '';
  const loading = _loadState.state === 'loading';
  return `<div class="specialist-group-note legacy-load-note" role="${loading ? 'status' : 'alert'}" aria-live="${loading ? 'polite' : 'assertive'}" data-kokuen-state="${_loadState.state}">
    <span>${esc(_loadState.message)}</span>${loading ? '' : `<button type="button" class="btn" data-act="retry-load">${t('common.retry')}</button>`}
  </div>`;
}

function _feedsPanel() {
  const disabled = _feedBusy || _feedListLoading ? 'disabled' : '';
  return `<div class="read-feeds" aria-busy="${_feedBusy || _feedListLoading}">
    <div class="read-feeds-add">
      <input type="text" id="feed-url" class="settings-input" aria-label="${esc(t('read.feed_url_label'))}" placeholder="${esc(t('read.feed_url_placeholder'))}" spellcheck="false" value="${esc(_feedDraft)}" ${disabled}>
      <button class="btn" id="feed-add" ${disabled}>${t('read.add_feed')}</button>
      <button class="btn" id="feed-refresh" title="${esc(t('read.refresh_feeds_title'))}" ${disabled}>${_feedBusy ? t('read.working') : t('read.refresh')}</button>
    </div>
    ${_feedListLoading ? `<p class="read-feed-notice" role="status">${t('read.feeds_loading')}</p>` : ''}
    ${_feedListError ? `<div class="read-feed-notice" role="alert"><span>${esc(_feedListError)}</span><button class="btn" id="feed-retry" ${disabled}>${t('read.retry_feed_list')}</button></div>` : ''}
    ${_feedMessage ? `<p class="read-feed-notice" role="${_feedFailed ? 'alert' : 'status'}">${esc(_feedMessage)}</p>` : ''}
    ${_feeds.length ? `<div class="read-feeds-list">${_feeds.map(f => `
      <div class="read-feed-row"><div class="read-feed-info"><span class="read-feed-title">${esc(f.title || f.url)}</span>${f.title ? `<span class="read-feed-url">${esc(f.url)}</span>` : ''}${_feedErrors.has(f.id) ? `<span class="read-feed-error">${esc(_feedErrors.get(f.id))}</span>` : ''}</div><button class="icon-btn danger" data-feed-del="${f.id}" title="${esc(t('read.remove_feed'))}" aria-label="${esc(t('read.remove_feed_named', { name: f.title || f.url }))}" ${disabled}>${_si('trash')}</button></div>`).join('')}</div>`
      : (!_feedListError && !_feedListLoading ? `<div class="read-feeds-empty">${t('read.feeds_empty')}</div>` : '')}
  </div>`;
}

export async function loadRead(fetcher = _fetcher) {
  _fetcher = fetcher;
  const params = new URLSearchParams();
  if (_filter && _filter !== 'all') params.set('filter', _filter);
  if (_q) params.set('q', _q);
  if (_tag) params.set('tag', _tag);
  _loadState = { state: 'loading', message: t('read.loading') };
  _itemsCurrent = false;
  _render();
  const [itemsResult, statsResult] = await Promise.allSettled([
    _json(fetcher, '/api/read?' + params),
    _json(fetcher, '/api/read/stats'),
  ]);
  const failures = [];
  const successes = [];
  if (itemsResult.status === 'fulfilled') {
    try { _readSaveRecovery(itemsResult.value.recovery_scopes); }
    catch (error) { _saveRecoveryError = error.message; }
    _items = itemsResult.value.items || [];
    _hasItems = true;
    _itemsCurrent = true;
    successes.push(t('read.part_items'));
  } else failures.push([t('read.part_items'), itemsResult.reason]);
  if (statsResult.status === 'fulfilled') {
    _stats = statsResult.value;
    _hasStats = true;
    successes.push(t('read.part_stats'));
  } else failures.push([t('read.part_stats'), statsResult.reason]);
  _loadState = failures.length ? _loadFailure(failures, successes) : { state: 'resting', message: '' };
  _render();
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

// labels are catalog keys, translated at render
const FILTERS = [['all', 'common.all'], ['unread', 'read.filter_unread'], ['fav', 'read.filter_starred'], ['archived', 'read.filter_archive']];

function _render() {
  const body = $('read-body');
  if (!body) return;
  _detachPlace();
  $('read-position-bar')?.remove();
  body.removeAttribute('tabindex');
  body.removeAttribute('aria-label');
  if (_open) { _renderReader(body); return; }
  const active = document.activeElement;
  const editing = !_saving && body.contains(active) && ['read-url', 'read-q', 'feed-url'].includes(active.id)
    ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null;
  if (editing?.id === 'read-url' && !active.disabled) _urlDraft = active.value;
  // a filter or feeds pick re-renders the toolbar; keep the keyboard on the chip that was pressed
  const chip = body.contains(active) && active.classList.contains('read-chip')
    ? (active.id ? `#${active.id}` : `.read-chip[data-filter="${active.dataset.filter}"]`) : null;
  body.innerHTML = `
    <div class="read-add">
      <input type="text" id="read-url" class="settings-input" aria-label="${esc(t('read.url_label'))}" aria-describedby="read-save-error" placeholder="${esc(t('read.url_placeholder'))}" spellcheck="false" value="${esc(_pendingSave?.url ?? _urlDraft)}" ${_saving || _pendingSave ? 'disabled' : ''}>
      <button class="btn primary" id="read-save" ${_saving || !_saveReady ? 'disabled' : ''} ${_saving ? 'aria-busy="true"' : ''}>${_saving ? t('common.saving') : _pendingSave ? t('read.retry_save') : `${_si('plus')} ${t('common.save')}`}</button>
    </div>
    <p id="read-save-error" class="read-save-error" role="alert" ${_saveError || _saveRecoveryError ? '' : 'hidden'}>${esc(_saveRecoveryError || _saveError)}</p>
    ${_saveRecoveryError ? `<button type="button" class="btn" id="read-save-recovery">${t('read.retry_save_recovery')}</button>` : ''}
    ${_pendingSave || _unreadableSave ? `<div class="read-save-recovery"><p role="status">${t('read.save_pending')}</p><div class="capture-actions">${_pendingSave ? `<button type="button" class="btn" id="read-save-check" ${_saving ? 'disabled' : ''}>${t('read.check_saved_item')}</button>` : ''}<button type="button" class="btn" id="read-save-discard" ${_saving ? 'disabled' : ''}>${t('read.discard_pending')}</button></div></div>` : ''}
    ${_savedURL ? `<div class="read-save-result"><p role="status">${esc(t('read.saved_named', { name: _savedURL.title || _savedURL.url }))}</p><button type="button" class="btn" id="read-save-open">${t('read.open_saved_item')}</button></div>` : ''}
    <div class="read-toolbar">
      <div class="read-filters"><span class="read-filter-choices" role="radiogroup" aria-label="${esc(t('read.filter_label'))}">${FILTERS.map(([k, l]) => `<button type="button" role="radio" aria-checked="${_filter === k}" class="read-chip${_filter === k ? ' active' : ''}" data-filter="${k}">${t(l)}</button>`).join('')}</span><button type="button" class="read-chip${_showFeeds ? ' active' : ''}" id="read-feeds-btn" aria-pressed="${_showFeeds}" title="${esc(t('read.feeds_title'))}">${t('read.feeds')}</button></div>
      <div class="read-search"><input type="text" id="read-q" aria-label="${esc(t('read.search_label'))}" class="settings-input" placeholder="${esc(t('read.search_placeholder'))}" value="${esc(_q)}" spellcheck="false"></div>
    </div>
    ${_loadNotice()}
    ${_showFeeds ? _feedsPanel() : ''}
    ${_tag ? `<div class="read-tagfilter">${t('read.tag_showing', { tag: `<span class="read-tag active">#${esc(_tag)}</span>` })}<button class="btn" id="read-tag-clear">${t('read.clear')}</button></div>` : ''}
    ${_statsBar()}
    ${_items.length ? `<div class="read-list">${_items.map(_card).join('')}</div>`
      : (_itemsCurrent ? `<div class="read-empty">${_q ? t('read.no_matches') : t('read.empty')}</div>` : '')}`;
  _wire(body);
  if (chip) body.querySelector(chip)?.focus();
  if (editing) {
    if (editing.id === 'read-url' && _pendingSave) { $('read-save-check')?.focus(); return; }
    const field = $(editing.id);
    field?.focus();
    if (editing.start != null) field?.setSelectionRange(editing.start, editing.end);
  }
}

function _fmtMin(m) {
  if (m < 60) return tp('read.minutes', m);
  const h = Math.floor(m / 60), mm = m % 60;
  return mm ? t('read.duration_hm', { hours: h, minutes: mm }) : t('read.duration_h', { hours: h });
}

// 4b - reading-queue capacity: how much is stacked up + roughly how long to clear it
function _statsBar() {
  const s = _stats;
  if (!s || !s.unread) return '';
  const parts = [tp('read.stats_unread', s.unread), t('read.stats_to_read', { time: _fmtMin(s.minutes) })];
  if (s.days_to_clear) parts.push(tp('read.stats_pace', s.days_to_clear, { pace: s.pace_per_day }));
  return `<div class="read-stats">${parts.join(' · ')}</div>`;
}

function _card(it) {
  const tags = (it.tags || '').split(',').map(t => t.trim()).filter(Boolean);
  return `
    <div class="read-card${it.read ? ' is-read' : ''}" data-id="${it.id}">
      <div class="read-card-main">
        <button type="button" class="read-card-open" data-open="${it.id}" aria-label="${esc(t('read.open_named', { title: it.title }))}">
        <span class="read-card-title">${it.fav ? `<span class="read-fav-dot">${_si('star')}</span>` : ''}${esc(it.title)}</span>
        <span class="read-card-excerpt">${esc(_plainExcerpt(it.excerpt))}</span>
        </button>
        <div class="read-card-meta">${esc(it.site)} · ${tp('read.minutes', it.read_minutes)}${it.read ? ` · ${t('read.state_read')}` : ''}${tags.length ? ' · ' + tags.map(t => `<button class="read-tag" data-tag="${esc(t)}">#${esc(t)}</button>`).join(' ') : ''}</div>
      </div>
      <div class="read-card-actions">
        <button class="icon-btn${it.fav ? ' on' : ''}" data-act="fav" title="${esc(t(it.fav ? 'read.unstar' : 'read.star'))}">${_si(it.fav ? 'star-fill' : 'star')}</button>
        <button class="icon-btn" data-act="read" title="${esc(t(it.read ? 'read.mark_unread' : 'read.mark_read'))}">${_si('check')}</button>
        <button class="icon-btn" data-act="archive" title="${esc(t(it.archived ? 'read.unarchive' : 'read.archive'))}">${_si('archive')}</button>
        <button class="icon-btn danger" data-act="del" title="${esc(t('common.delete'))}">${_si('trash')}</button>
      </div>
    </div>`;
}

async function _writeReadItem(id, patch, keepalive = false) {
  const response = await _fetcher(`/api/read/${encodeURIComponent(id)}`, patch ? {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch), keepalive,
  } : { method: 'DELETE' });
  if (!patch && response.status === 404) return null;
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(typeof result.detail === 'string' ? result.detail : t('read.change_unconfirmed')), { status: response.status });
  if (patch ? result.id !== id || Object.entries(patch).some(([key, value]) => key !== 'position_base' && result[key] !== value) : result.ok !== true) throw new Error(t('read.change_unconfirmed'));
  return result;
}

function _textState(item) {
  let state = _textFetches.get(item.id);
  if (!state) { state = { busy: false, error: '', message: '' }; _textFetches.set(item.id, state); }
  return state;
}

function _updateTextControls(item) {
  if (_open !== item) return;
  const state = _textState(item);
  const label = item.text_state === 'extracted' ? t('read.text_saved')
    : item.text_state === 'excerpt' ? t('read.text_excerpt')
    : !(item.text || '').trim() ? t('read.text_none')
    : t('read.text_unknown');
  const panel = $('read-text-tools');
  if (!panel) return;
  panel.setAttribute('aria-busy', String(state.busy));
  $('read-text-status').textContent = state.busy ? t('read.text_busy') : state.message || label;
  $('read-text-error').textContent = state.error;
  $('read-text-error').hidden = !state.error;
  const button = $('read-fetch-text');
  button.hidden = item.text_state === 'extracted';
  button.disabled = state.busy || !!state.savingRead;
  button.textContent = state.error ? t('read.retry_fetch') : t('read.fetch_text');
  $('read-check-text').hidden = !state.error;
  $('read-check-text').disabled = state.busy || !!state.savingRead;
  $('read-note').disabled = state.busy;
  $('read-complete').disabled = state.busy || !!state.savingRead;
  if (state.savingRead) $('read-completion-status').textContent = t('read.status_saving');
}

async function _fetchArticleText(item, place, checkOnly = false) {
  const state = _textState(item);
  if (state.busy || _open !== item) return;
  const generation = _openGeneration;
  const current = () => generation === _openGeneration && _open === item && $('read-body')?.getClientRects().length;
  const focusOwned = () => current() && (document.activeElement === document.body
    || ['read-fetch-text', 'read-check-text'].includes(document.activeElement?.id));
  state.busy = true; state.error = ''; state.message = '';
  // Keep the initiating button enabled until the custom dialog restores its focus.
  try {
    const replace = item.text_state === 'unknown' && !!(item.text || '').trim();
    if (!checkOnly && replace && !await dlgConfirm(t('read.replace_text_confirm'))) return;
    if (!current()) return;
    _updateTextControls(item);
    if (!(await place.drain()) && !checkOnly) throw new Error(t('read.place_save_first'));
    if (!current()) return;
    const response = await _fetcher(`/api/read/${encodeURIComponent(item.id)}${checkOnly ? '' : '/fetch-text'}`, checkOnly
      ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ content_hash: item.content_hash, replace_saved_text: replace }) });
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : t('read.text_unconfirmed'));
    if (result?.id !== item.id || typeof result.text !== 'string' || !/^[a-f0-9]{64}$/.test(result.content_hash || '') || (!checkOnly && result.text_state !== 'extracted')) throw new Error(t('read.text_unconfirmed'));
    state.message = result.text_state === 'extracted'
      ? t(result.content_hash !== item.content_hash ? 'read.text_saved_restarted' : 'read.text_saved')
      : t('read.text_checked');
    if (_open?.id !== item.id || _open.content_hash !== item.content_hash || !$('read-body')?.getClientRects().length) return;
    const focus = focusOwned();
    const active = document.activeElement;
    const hadReaderFocus = $('read-body').contains(active) || $('read-position-bar')?.contains(active);
    const focusId = hadReaderFocus ? active.id : '';
    const sourceHash = _open.sourceHash;
    // A pending old-version position write cannot update the new text version.
    _detachPlace(false);
    if (result.content_hash !== item.content_hash) _places.delete(item.id);
    _open = { ...result, sourceHash, sourceChanged: !!sourceHash && sourceHash !== result.content_hash };
    state.busy = false;
    _render();
    if (focus) $('read-text-status')?.focus({ preventScroll: true });
    else if (hadReaderFocus) ($(focusId) || $('read-text-status'))?.focus({ preventScroll: true });
  } catch (error) {
    state.error = error instanceof TypeError ? t('read.text_connect_failed') : error.message;
  } finally {
    state.busy = false;
    if (_open?.id === item.id) _updateTextControls(_open);
  }
}

// a card excerpt is a sentence to read, not table cells: "| Type | Dumpling | |||||" loses its pipes
function _plainExcerpt(value) {
  return String(value || '').replace(/\|/g, ' ').replace(/\s{2,}/g, ' ').trim();
}

function _renderReader(body) {
  const it = _open;
  // most saved text marks paragraphs with blank lines; some (wikipedia) uses single line breaks
  // only, which made one wall of text
  const text = it.text || '';
  const paras = text.split(/\n{2,}/.test(text) ? /\n{2,}/ : /\n/).map(p => p.trim()).filter(Boolean);
  body.innerHTML = `
    <div class="read-reader">
      <div class="read-reader-bar">
        <button class="btn" id="read-back">${_si('chevron-left')} ${t('common.back')}</button>
        <button class="btn" type="button" id="read-note">${t('read.take_note')}</button>
        <a class="btn" href="${esc(_safeUrl(it.url))}" target="_blank" rel="noopener">${t('read.open_original')} ${_si('link')}</a>
      </div>
      <article class="read-article">
        ${it.sourceChanged ? `<p class="read-source-notice" role="status">${t('read.source_changed')}</p>` : ''}
        <div class="read-toolbar">
          <button type="button" class="btn" id="read-complete" aria-pressed="${!!it.read}">${it.read ? t('read.mark_unread') : t('read.mark_read')}</button>
          <p id="read-completion-status" role="status"></p>
        </div>
        <h1>${esc(it.title)}</h1>
        <div class="read-article-meta">${esc(it.site)} · ${tp('read.minutes_read', it.read_minutes)}</div>
        <section class="read-text-tools" id="read-text-tools" aria-label="${esc(t('read.text_tools_label'))}">
          <p id="read-text-status" role="status" tabindex="-1"></p>
          <p id="read-text-error" class="read-save-error" role="alert" hidden></p>
          <div class="capture-actions">
            <button type="button" class="btn" id="read-fetch-text">${t('read.fetch_text')}</button>
            <button type="button" class="btn" id="read-check-text" hidden>${t('read.check_text')}</button>
          </div>
        </section>
        ${paras.length ? paras.map(p => `<p>${esc(p)}</p>`).join('') : `<p class="read-empty">${t('read.no_text', { link: `<a href="${esc(_safeUrl(it.url))}" target="_blank" rel="noopener">${t('read.open_the_original')}</a>` })}</p>`}
      </article>
    </div>`;
  const place = _attachReadingPlace(body, it);
  _updateTextControls(it);
  $('read-fetch-text').addEventListener('click', () => _fetchArticleText(it, place));
  $('read-check-text').addEventListener('click', () => _fetchArticleText(it, place, true));
  $('read-note').addEventListener('click', () => takeReadingNote(it));
  const complete = $('read-complete');
  const back = $('read-back');
  back.addEventListener('click', async () => {
    if (back.disabled) return;
    ++_openGeneration;
    back.disabled = complete.disabled = true;
    try {
      if ((!(await place.drain()) && !place.blocked) || _open !== it) return;
      clearLinkedRecord('read');
      _open = null;
      await loadRead();
      (body.querySelector(`[data-open="${_returnItem}"]`) || $('read-q'))?.focus();
    } finally { back.disabled = complete.disabled = false; _updateTextControls(it); }
  });
  const notice = $('read-completion-status');
  complete.addEventListener('click', async () => {
    const desired = !it.read;
    _textState(it).savingRead = true;
    _updateTextControls(it);
    back.disabled = complete.disabled = true;
    notice.classList.remove('read-save-error');
    notice.textContent = t('read.status_saving');
    try {
      const result = await _writeReadItem(it.id, { read: desired });
      it.read = result.read; it.read_at = result.read_at;
      if (_open?.id === it.id) {
        _open.read = result.read; _open.read_at = result.read_at;
        $('read-complete').textContent = result.read ? t('read.mark_unread') : t('read.mark_read');
        $('read-complete').setAttribute('aria-pressed', String(result.read));
        $('read-completion-status').textContent = result.read ? t('read.marked_read') : t('read.marked_unread');
      }
    } catch {
      if (_open?.id === it.id) {
        $('read-completion-status').classList.add('read-save-error');
        $('read-completion-status').textContent = t('read.status_unconfirmed');
      }
    } finally {
      _textState(it).savingRead = false;
      back.disabled = complete.disabled = false;
      if (_open?.id === it.id) _updateTextControls(_open);
    }
  });
}

function _attachReadingPlace(body, item) {
  let state = _places.get(item.id);
  if (!state || state.hash !== item.content_hash) {
    state = { hash: item.content_hash, place: readingPlace(item, patch => _writeReadItem(item.id, patch, true)) };
    _places.set(item.id, state);
  }
  const place = state.place;
  const bar = document.createElement('div');
  bar.id = 'read-position-bar';
  bar.innerHTML = `<div class="read-toolbar"><p id="read-position-status" role="status" tabindex="-1"></p><button type="button" class="btn" id="read-position-retry" hidden>${t('common.retry')}</button></div>`;
  bar.prepend(body.querySelector('.read-reader-bar'));
  const sourceNotice = body.querySelector('.read-source-notice');
  if (sourceNotice) bar.append(sourceNotice);
  body.before(bar);
  const notice = bar.querySelector('#read-position-status');
  const retry = bar.querySelector('#read-position-retry');
  body.tabIndex = 0; body.setAttribute('aria-label', t('read.article_label'));
  place.listen(({ pending, error, blocked, unsaved }) => {
    notice.textContent = error || (pending ? t('read.place_saving') : unsaved ? t('read.place_unsaved') : t('read.place_saved'));
    notice.classList.toggle('read-save-error', !!error);
    const hadFocus = document.activeElement === retry;
    retry.hidden = !error;
    retry.disabled = pending;
    retry.textContent = blocked ? t('read.reopen_article') : t('common.retry');
    retry.onclick = () => blocked ? openReadItem(item.id, undefined, item.sourceHash || '') : place.flush();
    if (hadFocus && retry.hidden) notice.focus({ preventScroll: true });
  });
  let attached = true;
  let mounting = true;
  let restoredTop = -1;
  let restoredRange = -1;
  let frame = 0;
  const restore = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!attached || !body.getClientRects().length) return;
      restoredRange = Math.max(0, body.scrollHeight - body.clientHeight);
      body.scrollTop = place.value * restoredRange;
      restoredTop = body.scrollTop;
      mounting = false;
    });
  };
  const scroll = () => {
    const range = body.scrollHeight - body.clientHeight;
    if (!mounting && range !== restoredRange) { restore(); return; }
    if (!mounting && body.getClientRects().length && range > 0 && (restoredTop < 0 || Math.abs(body.scrollTop - restoredTop) > 1)) {
      restoredTop = -1;
      place.set(body.scrollTop / range);
    }
  };
  const observer = new ResizeObserver(restore);
  observer.observe(body); observer.observe(body.querySelector('.read-article'));
  body.addEventListener('scroll', scroll, { passive: true });
  const leaving = () => { if (document.visibilityState === 'hidden') void place.flush(true); };
  document.addEventListener('visibilitychange', leaving);
  const unload = () => { scroll(); void place.flush(true); };
  window.addEventListener('pagehide', unload);
  restore();
  _detachPlace = (flush = true) => {
    attached = false;
    cancelAnimationFrame(frame);
    observer.disconnect();
    body.removeEventListener('scroll', scroll);
    document.removeEventListener('visibilitychange', leaving);
    window.removeEventListener('pagehide', unload);
    place.listen(() => {});
    if (flush) void place.flush();
    _detachPlace = () => {};
  };
  return place;
}

function _wire(body) {
  $('read-save-recovery')?.addEventListener('click', () => loadRead());
  $('read-save-discard')?.addEventListener('click', _discardUrlSave);
  $('read-save-check')?.addEventListener('click', () => _save(true));
  $('read-save-open')?.addEventListener('click', () => openReadItem(_savedURL.id));
  wireChoiceGroup(body.querySelector('.read-filter-choices'));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => loadRead());
  const save = () => _save();
  $('read-save')?.addEventListener('click', save);
  $('read-url')?.addEventListener('input', e => { _urlDraft = e.target.value; });
  $('read-url')?.addEventListener('keydown', e => { if (e.key === 'Enter') save(); });

  $('read-feeds-btn')?.addEventListener('click', async () => {
    _showFeeds = !_showFeeds;
    if (_showFeeds) { const loading = loadFeeds(); _render(); await loading; }
    _render();
  });
  if (_showFeeds) {
    $('feed-url')?.addEventListener('input', event => { _feedDraft = event.target.value; });
    $('feed-retry')?.addEventListener('click', async () => {
      const loading = loadFeeds(); _render(); await loading; _render();
      if ($('feed-url')?.getClientRects().length && document.activeElement === document.body) $('feed-url').focus();
    });
    const addFeed = () => {
      const url = _feedDraft.trim();
      if (!url) return;
      return _changeFeeds(async () => {
        try {
          await _feedRequest('/api/read/feeds', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) }, result => typeof result?.id === 'string' && typeof result.url === 'string');
        } catch (error) {
          if (error.status !== 400 || error.message !== 'feed already added') throw error;
          await loadFeeds();
          const normalized = url.startsWith('http') ? url : 'https://' + url;
          if (_feedListError || _feedListLoading || !_feeds.some(feed => feed.url === normalized)) throw new Error(t('read.feed_maybe_added'));
        }
        if (_feedDraft.trim() === url) _feedDraft = '';
        _feedMessage = t('read.feed_added');
        await loadFeeds();
      }, 'feed-url');
    };
    $('feed-add')?.addEventListener('click', addFeed);
    $('feed-url')?.addEventListener('keydown', e => { if (e.key === 'Enter') void addFeed(); });
    $('feed-refresh')?.addEventListener('click', () => _changeFeeds(async () => {
      const result = await _feedRequest('/api/read/feeds/refresh', { method: 'POST' }, value =>
        typeof value?.ok === 'boolean' && ['checked', 'failed', 'added', 'skipped'].every(key => Number.isInteger(value[key]) && value[key] >= 0) && Array.isArray(value.feeds));
      _feedErrors.clear();
      result.feeds.forEach(feed => { if (!feed.ok) _feedErrors.set(feed.id, feed.error || t('read.feed_refresh_failed')); });
      _feedFailed = !result.ok;
      const summary = [tp('read.feeds_checked', result.checked), tp('read.items_saved', result.added)];
      if (result.failed) summary.push(tp('read.feeds_failed', result.failed));
      if (result.skipped) summary.push(tp('read.feeds_skipped', result.skipped));
      _feedMessage = summary.join('; ');
      if (!result.checked && !result.failed && !result.skipped) _feedMessage = t('read.no_feeds_to_refresh');
      await loadFeeds(); await loadRead();
    }, 'feed-refresh'));
    body.querySelectorAll('[data-feed-del]').forEach(button => button.addEventListener('click', () => _changeFeeds(async () => {
      await _feedRequest(`/api/read/feeds/${encodeURIComponent(button.dataset.feedDel)}`, { method: 'DELETE' }, result => result?.ok === true);
      _feeds = _feeds.filter(feed => feed.id !== button.dataset.feedDel);
      _feedErrors.delete(button.dataset.feedDel);
      _feedMessage = t('read.feed_removed');
      await loadFeeds();
    }, 'feed-refresh')));
  }

  const qEl = $('read-q');
  if (qEl) {
    let t = null;
    qEl.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { _q = qEl.value.trim(); loadRead(); }, 300); });
  }
  body.querySelectorAll('.read-filter-choices .read-chip').forEach(c => c.addEventListener('click', () => { _filter = c.dataset.filter; loadRead(); }));

  // click a tag to filter by it; stop the click bubbling up to the card-open handler
  body.querySelectorAll('.read-card .read-tag').forEach(t => t.addEventListener('click', e => {
    e.stopPropagation();
    _tag = t.dataset.tag; loadRead();
  }));
  $('read-tag-clear')?.addEventListener('click', () => { _tag = ''; loadRead(); });

  body.querySelectorAll('[data-open]').forEach(el => el.addEventListener('click', async () => {
    await openReadItem(el.dataset.open);
  }));

  body.querySelectorAll('.read-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async e => {
      e.stopPropagation();
      const act = btn.dataset.act;
      const it = _items.find(x => x.id === id);
      if (!it || card.dataset.saving === 'true') return;
      if (act === 'del' && !await dlgConfirm(t('read.delete_confirm'))) return;
      if (!card.isConnected || card.dataset.saving === 'true') return;
      const patch = act === 'fav' ? { fav: !it.fav } : act === 'archive' ? { archived: !it.archived } : act === 'read' ? { read: !it.read } : null;
      card.dataset.saving = 'true';
      const buttons = [...card.querySelectorAll('button')];
      buttons.forEach(button => { button.disabled = true; });
      try {
        const result = await _writeReadItem(id, patch);
        if (_open?.id === id) _open = result ? { ..._open, ...result } : null;
        if (act === 'del') toast(t('read.deleted'), 'success');
        if (act === 'archive') toast(it.archived ? t('read.unarchived') : t('read.archived'), 'success');
        const restoreFocus = document.activeElement === btn || document.activeElement === document.body;
        await loadRead();
        if (restoreFocus && document.activeElement === document.body) {
          (body.querySelector(`.read-card[data-id="${id}"] [data-act="${act}"]`) || $('read-q'))?.focus();
        }
      } catch (error) { toast(error.message || t('read.change_unconfirmed'), 'error'); }
      finally {
        delete card.dataset.saving;
        buttons.forEach(button => { button.disabled = false; });
      }
    }));
  });
}

async function _save(checkOnly = false) {
  if (_saving || !_saveReady) return;
  if (!_pendingSave) _urlDraft = $('read-url')?.value ?? _urlDraft;
  const url = (_pendingSave?.url ?? _urlDraft).trim();
  if (!url) { _saveError = t('read.url_required'); _render(); $('read-url')?.focus(); return; }
  const navigation = _openGeneration;
  const mayFocus = () => navigation === _openGeneration && $('read-body')?.getClientRects().length
    && (document.activeElement === document.body || ['read-save', 'read-save-check'].includes(document.activeElement?.id));
  _saving = true; _saveError = ''; _savedURL = null;
  _render();
  let restoreFocus = false;
  try {
    const pending = _pendingSave || { url, request_id: _urlRequestId(), recovery_scope: _saveScopes[0] };
    _keepUrlSave(pending);
    const response = checkOnly
      ? await _fetcher(`/api/read/requests/${encodeURIComponent(pending.request_id)}?recovery_scope=${encodeURIComponent(pending.recovery_scope)}`, { cache: 'no-store' })
      : await _fetcher('/api/read', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pending) });
    const result = await response.json().catch(() => { throw new Error(t('read.save_response_unreadable')); });
    if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : t('read.save_not_confirmed'));
    _confirmUrlSave(result, pending);
    toast(t('read.url_saved'), 'success');
    restoreFocus = mayFocus();
    await loadRead();
  } catch (error) {
    _saveError = error instanceof TypeError ? t('read.save_connect_failed') : (error.message || t('read.save_failed'));
    restoreFocus = mayFocus();
  } finally {
    _saving = false;
    const focus = restoreFocus && mayFocus();
    _render();
    if (focus) (_savedURL ? $('read-save-open') : _pendingSave ? $('read-save') : $('read-url'))?.focus();
  }
}

let _openGeneration = 0;
export async function openReadItem(id, isCurrent = () => Boolean($('read-body')?.getClientRects().length), expectedHash = '') {
  const previous = _places.get(id)?.place;
  const previousValue = previous?.value;
  const wasBlocked = previous?.blocked;
  const run = ++_openGeneration;
  try {
    const item = await _json(_fetcher, `/api/read/${encodeURIComponent(id)}`);
    if (run !== _openGeneration || !isCurrent()) return false;
    if (item?.id !== id) throw new Error('could not confirm the article');
    _open = item;
    if (!_textState(item).busy) { _textState(item).error = ''; _textState(item).message = ''; }
    _open.sourceHash = expectedHash;
    _open.sourceChanged = !!expectedHash && expectedHash !== item.content_hash;
    // Reopen accepts fresh state only for the unchanged draft that requested it.
    if (previous && _places.get(id)?.place === previous && previous.value === previousValue && !previous.pending
      && (!previous.unsaved || (wasBlocked && previous.blocked))) _places.delete(id);
    _returnItem = id;
    _render();
    $('read-back')?.focus();
  } catch {
    if (run !== _openGeneration || !isCurrent()) return false;
    _open = null;
    _render();
    $('read-q')?.focus();
    toast(t('read.open_failed'), 'error');
    return false;
  }
  return true;
}
