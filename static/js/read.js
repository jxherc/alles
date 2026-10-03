// read — a read-later archive. paste a URL, alles fetches + stores the readable text
// (reusing the research extractor) so it's searchable offline and the link can't rot.
// list + reader views; mirrors the watch/habits panel conventions.
import { toast, _safeUrl } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';
import { wireChoiceGroup } from './kokuen.js';
import { readingPlace } from './reading_place.js';
import { loadReadingNoteRecovery, takeReadingNote } from './reading_note.js';
import { clearLinkedRecord } from './recordlinks.js';
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
let _returnItem = null;
let _open = null;   // full item being read
let _feeds = [];
let _showFeeds = false;
let _fetcher = fetch;
let _hasItems = false;
let _hasStats = false;
let _itemsCurrent = false;
let _loadState = { state: 'resting', message: '' };
let _detachPlace = () => {};
const _places = new Map();

export function initRead(fetcher = fetch) {
  ++_openGeneration;
  _fetcher = fetcher;
  void loadReadingNoteRecovery();
  return loadRead(fetcher);
}

async function loadFeeds() {
  try { _feeds = (await _fetcher('/api/read/feeds').then(r => r.json())).feeds || []; }
  catch { _feeds = []; }
}

async function _json(fetcher, url) {
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`request failed (${response.status || 'unknown'})`);
  return response.json();
}

function _loadFailure(failures, successes) {
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
  if (successes.length) {
    const unavailable = failures.map(([name]) => name).join(' and ');
    return {
      state: 'partial',
      message: `partial reading data: ${unavailable} unavailable.`,
    };
  }
  const retained = _hasItems || _hasStats ? ' Showing the last loaded reading data.' : '';
  return {
    state: offline ? 'offline' : 'error',
    message: `${offline ? 'You appear to be offline.' : 'Reading data could not be loaded.'}${retained}`,
  };
}

function _loadNotice() {
  if (_loadState.state === 'resting') return '';
  const loading = _loadState.state === 'loading';
  return `<div class="specialist-group-note legacy-load-note" role="${loading ? 'status' : 'alert'}" aria-live="${loading ? 'polite' : 'assertive'}" data-kokuen-state="${_loadState.state}">
    <span>${esc(_loadState.message)}</span>${loading ? '' : '<button type="button" class="btn" data-act="retry-load">retry</button>'}
  </div>`;
}

function _feedsPanel() {
  return `<div class="read-feeds">
    <div class="read-feeds-add">
      <input type="text" id="feed-url" class="settings-input" placeholder="rss / atom feed url…" spellcheck="false">
      <button class="btn" id="feed-add">add feed</button>
      <button class="btn" id="feed-refresh" title="poll all feeds now">refresh</button>
    </div>
    ${_feeds.length ? `<div class="read-feeds-list">${_feeds.map(f => `
      <div class="read-feed-row"><span class="read-feed-title">${esc(f.title || f.url)}</span><span class="read-feed-url">${esc(f.url)}</span><button class="icon-btn danger" data-feed-del="${f.id}" title="remove feed">${_si('trash')}</button></div>`).join('')}</div>`
      : '<div class="read-feeds-empty">no feeds yet: add an rss/atom url and new posts auto-save into your list.</div>'}
  </div>`;
}

export async function loadRead(fetcher = _fetcher) {
  _fetcher = fetcher;
  const params = new URLSearchParams();
  if (_filter && _filter !== 'all') params.set('filter', _filter);
  if (_q) params.set('q', _q);
  if (_tag) params.set('tag', _tag);
  _loadState = { state: 'loading', message: 'loading saved reading…' };
  _itemsCurrent = false;
  _render();
  const [itemsResult, statsResult] = await Promise.allSettled([
    _json(fetcher, '/api/read?' + params),
    _json(fetcher, '/api/read/stats'),
  ]);
  const failures = [];
  const successes = [];
  if (itemsResult.status === 'fulfilled') {
    _items = itemsResult.value.items || [];
    _hasItems = true;
    _itemsCurrent = true;
    successes.push('saved items');
  } else failures.push(['saved items', itemsResult.reason]);
  if (statsResult.status === 'fulfilled') {
    _stats = statsResult.value;
    _hasStats = true;
    successes.push('reading statistics');
  } else failures.push(['reading statistics', statsResult.reason]);
  _loadState = failures.length ? _loadFailure(failures, successes) : { state: 'resting', message: '' };
  _render();
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

const FILTERS = [['all', 'all'], ['unread', 'unread'], ['fav', 'starred'], ['archived', 'archive']];

function _render() {
  const body = $('read-body');
  if (!body) return;
  _detachPlace();
  $('read-position-bar')?.remove();
  body.removeAttribute('tabindex');
  body.removeAttribute('aria-label');
  if (_open) { _renderReader(body); return; }
  const active = document.activeElement;
  const editing = !_saving && body.contains(active) && ['read-url', 'read-q'].includes(active.id)
    ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null;
  if (editing?.id === 'read-url') _urlDraft = active.value;
  body.innerHTML = `
    <div class="read-add">
      <input type="text" id="read-url" class="settings-input" aria-label="URL to save for later" aria-describedby="read-save-error" placeholder="paste a URL to save for later…" spellcheck="false" value="${esc(_urlDraft)}" ${_saving ? 'disabled' : ''}>
      <button class="btn primary" id="read-save" ${_saving ? 'disabled aria-busy="true"' : ''}>${_saving ? 'saving…' : `${_si('plus')} save`}</button>
    </div>
    <p id="read-save-error" class="read-save-error" role="alert" ${_saveError ? '' : 'hidden'}>${esc(_saveError)}</p>
    <div class="read-toolbar">
      <div class="read-filters"><span class="read-filter-choices" role="radiogroup" aria-label="saved reading filter">${FILTERS.map(([k, l]) => `<button type="button" role="radio" aria-checked="${_filter === k}" class="read-chip${_filter === k ? ' active' : ''}" data-filter="${k}">${l}</button>`).join('')}</span><button type="button" class="read-chip${_showFeeds ? ' active' : ''}" id="read-feeds-btn" aria-pressed="${_showFeeds}" title="rss feeds">feeds</button></div>
      <div class="read-search"><input type="text" id="read-q" class="settings-input" placeholder="search saved…" value="${esc(_q)}" spellcheck="false"></div>
    </div>
    ${_loadNotice()}
    ${_showFeeds ? _feedsPanel() : ''}
    ${_tag ? `<div class="read-tagfilter">showing <span class="read-tag active">#${esc(_tag)}</span><button class="btn" id="read-tag-clear">clear</button></div>` : ''}
    ${_statsBar()}
    ${_items.length ? `<div class="read-list">${_items.map(_card).join('')}</div>`
      : (_itemsCurrent ? `<div class="read-empty">${_q ? 'nothing matches that search.' : 'nothing saved yet: paste a link above and alles will keep the article text here, searchable, forever.'}</div>` : '')}`;
  _wire(body);
  if (editing) {
    const field = $(editing.id);
    field?.focus();
    if (editing.start != null) field?.setSelectionRange(editing.start, editing.end);
  }
}

function _fmtMin(m) {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), mm = m % 60;
  return mm ? `${h}h ${mm}m` : `${h}h`;
}

// 4b - reading-queue capacity: how much is stacked up + roughly how long to clear it
function _statsBar() {
  const s = _stats;
  if (!s || !s.unread) return '';
  const days = s.days_to_clear
    ? ` · about ${s.days_to_clear} day${s.days_to_clear === 1 ? '' : 's'} at ${s.pace_per_day} min/day` : '';
  return `<div class="read-stats">${s.unread} unread · ${_fmtMin(s.minutes)} to read${days}</div>`;
}

function _card(it) {
  const tags = (it.tags || '').split(',').map(t => t.trim()).filter(Boolean);
  return `
    <div class="read-card${it.read ? ' is-read' : ''}" data-id="${it.id}">
      <div class="read-card-main">
        <button type="button" class="read-card-open" data-open="${it.id}" aria-label="open ${esc(it.title)}">
        <span class="read-card-title">${it.fav ? `<span class="read-fav-dot">${_si('star')}</span>` : ''}${esc(it.title)}</span>
        <span class="read-card-excerpt">${esc(it.excerpt)}</span>
        </button>
        <div class="read-card-meta">${esc(it.site)} · ${it.read_minutes} min${it.read ? ' · read' : ''}${tags.length ? ' · ' + tags.map(t => `<button class="read-tag" data-tag="${esc(t)}">#${esc(t)}</button>`).join(' ') : ''}</div>
      </div>
      <div class="read-card-actions">
        <button class="icon-btn${it.fav ? ' on' : ''}" data-act="fav" title="${it.fav ? 'unstar' : 'star'}">${_si(it.fav ? 'star-fill' : 'star')}</button>
        <button class="icon-btn" data-act="read" title="${it.read ? 'mark unread' : 'mark read'}">${_si('check')}</button>
        <button class="icon-btn" data-act="archive" title="${it.archived ? 'unarchive' : 'archive'}">${_si('archive')}</button>
        <button class="icon-btn danger" data-act="del" title="delete">${_si('trash')}</button>
      </div>
    </div>`;
}

async function _writeReadItem(id, patch, keepalive = false) {
  const response = await _fetcher(`/api/read/${encodeURIComponent(id)}`, patch ? {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch), keepalive,
  } : { method: 'DELETE' });
  if (!patch && response.status === 404) return null;
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(typeof result.detail === 'string' ? result.detail : 'could not confirm the change; try again'), { status: response.status });
  if (patch ? result.id !== id || Object.entries(patch).some(([key, value]) => result[key] !== value) : result.ok !== true) throw new Error('could not confirm the change; try again');
  return result;
}

function _renderReader(body) {
  const it = _open;
  const paras = (it.text || '').split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
  body.innerHTML = `
    <div class="read-reader">
      <div class="read-reader-bar">
        <button class="btn" id="read-back">${_si('chevron-left') || '←'} back</button>
        <button class="btn" type="button" id="read-note">take note</button>
        <a class="btn" href="${_safeUrl(it.url)}" target="_blank" rel="noopener">open original ${_si('link')}</a>
      </div>
      <article class="read-article">
        ${it.sourceChanged ? '<p class="read-source-notice" role="status">this article changed since the note was saved. the current text is shown below.</p>' : ''}
        <div class="read-toolbar">
          <button type="button" class="btn" id="read-complete" aria-pressed="${!!it.read}">${it.read ? 'mark unread' : 'mark read'}</button>
          <p id="read-completion-status" role="status"></p>
        </div>
        <h1>${esc(it.title)}</h1>
        <div class="read-article-meta">${esc(it.site)} · ${it.read_minutes} min read</div>
        ${paras.length ? paras.map(p => `<p>${esc(p)}</p>`).join('') : `<p class="read-empty">no readable text was extracted for this page. <a href="${_safeUrl(it.url)}" target="_blank" rel="noopener">open the original</a>.</p>`}
      </article>
    </div>`;
  const place = _attachReadingPlace(body, it);
  $('read-note').addEventListener('click', () => takeReadingNote(it));
  const complete = $('read-complete');
  const back = $('read-back');
  back.addEventListener('click', async () => {
    if (back.disabled) return;
    back.disabled = complete.disabled = true;
    try {
      if ((!(await place.drain()) && !place.blocked) || _open !== it) return;
      clearLinkedRecord('read');
      _open = null;
      await loadRead();
      (body.querySelector(`[data-open="${_returnItem}"]`) || $('read-q'))?.focus();
    } finally { back.disabled = complete.disabled = false; }
  });
  const notice = $('read-completion-status');
  complete.addEventListener('click', async () => {
    const desired = !it.read;
    back.disabled = complete.disabled = true;
    notice.classList.remove('read-save-error');
    notice.textContent = 'saving reading status…';
    try {
      const result = await _writeReadItem(it.id, { read: desired });
      it.read = result.read; it.read_at = result.read_at;
      complete.textContent = it.read ? 'mark unread' : 'mark read';
      complete.setAttribute('aria-pressed', String(it.read));
      notice.textContent = it.read ? 'marked read' : 'marked unread';
    } catch { notice.classList.add('read-save-error'); notice.textContent = 'could not confirm reading status; try again'; }
    finally { back.disabled = complete.disabled = false; }
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
  bar.innerHTML = '<div class="read-toolbar"><p id="read-position-status" role="status" tabindex="-1"></p><button type="button" class="btn" id="read-position-retry" hidden>retry</button></div>';
  bar.prepend(body.querySelector('.read-reader-bar'));
  const sourceNotice = body.querySelector('.read-source-notice');
  if (sourceNotice) bar.append(sourceNotice);
  body.before(bar);
  const notice = bar.querySelector('#read-position-status');
  const retry = bar.querySelector('#read-position-retry');
  body.tabIndex = 0; body.setAttribute('aria-label', 'saved article');
  place.listen(({ pending, error, blocked, unsaved }) => {
    notice.textContent = error || (pending ? 'saving reading place…' : unsaved ? 'reading place not saved yet' : 'reading place saved');
    notice.classList.toggle('read-save-error', !!error);
    const hadFocus = document.activeElement === retry;
    retry.hidden = !error;
    retry.disabled = pending;
    retry.textContent = blocked ? 'reopen article' : 'retry';
    retry.onclick = () => blocked ? openReadItem(item.id) : place.flush();
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
  const leaving = () => { if (document.visibilityState === 'hidden') void place.flush(); };
  document.addEventListener('visibilitychange', leaving);
  const unload = () => void place.flush();
  window.addEventListener('pagehide', unload);
  restore();
  _detachPlace = () => {
    attached = false;
    cancelAnimationFrame(frame);
    observer.disconnect();
    body.removeEventListener('scroll', scroll);
    document.removeEventListener('visibilitychange', leaving);
    window.removeEventListener('pagehide', unload);
    place.listen(() => {});
    void place.flush();
    _detachPlace = () => {};
  };
  return place;
}

function _wire(body) {
  wireChoiceGroup(body.querySelector('.read-filter-choices'));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => loadRead());
  const save = () => _save();
  $('read-save')?.addEventListener('click', save);
  $('read-url')?.addEventListener('input', e => { _urlDraft = e.target.value; });
  $('read-url')?.addEventListener('keydown', e => { if (e.key === 'Enter') save(); });

  $('read-feeds-btn')?.addEventListener('click', async () => {
    _showFeeds = !_showFeeds;
    if (_showFeeds) await loadFeeds();
    _render();
  });
  if (_showFeeds) {
    const addFeed = async () => {
      const url = $('feed-url')?.value.trim();
      if (!url) return;
      const r = await _fetcher('/api/read/feeds', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) });
      if (!r.ok) { toast((await r.json()).detail || 'failed', 'error'); return; }
      await loadFeeds(); _render();
    };
    $('feed-add')?.addEventListener('click', addFeed);
    $('feed-url')?.addEventListener('keydown', e => { if (e.key === 'Enter') addFeed(); });
    $('feed-refresh')?.addEventListener('click', async () => {
      const btn = $('feed-refresh'); if (btn) btn.textContent = '…';
      await _fetcher('/api/read/feeds/refresh', { method: 'POST' });
      toast('feeds refreshed', 'success');
      await loadFeeds(); await loadRead();   // loadRead re-renders with any new items
    });
    body.querySelectorAll('[data-feed-del]').forEach(b => b.addEventListener('click', async () => {
      await _fetcher(`/api/read/feeds/${b.dataset.feedDel}`, { method: 'DELETE' });
      await loadFeeds(); _render();
    }));
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
      if (act === 'del' && !await dlgConfirm('delete this saved item?')) return;
      if (!card.isConnected || card.dataset.saving === 'true') return;
      const patch = act === 'fav' ? { fav: !it.fav } : act === 'archive' ? { archived: !it.archived } : act === 'read' ? { read: !it.read } : null;
      card.dataset.saving = 'true';
      const buttons = [...card.querySelectorAll('button')];
      buttons.forEach(button => { button.disabled = true; });
      try {
        const result = await _writeReadItem(id, patch);
        if (_open?.id === id) _open = result ? { ..._open, ...result } : null;
        if (act === 'del') toast('deleted', 'success');
        if (act === 'archive') toast(it.archived ? 'unarchived' : 'archived', 'success');
        const restoreFocus = document.activeElement === btn || document.activeElement === document.body;
        await loadRead();
        if (restoreFocus && document.activeElement === document.body) {
          (body.querySelector(`.read-card[data-id="${id}"] [data-act="${act}"]`) || $('read-q'))?.focus();
        }
      } catch (error) { toast(error.message || 'could not confirm the change; try again', 'error'); }
      finally {
        delete card.dataset.saving;
        buttons.forEach(button => { button.disabled = false; });
      }
    }));
  });
}

async function _save() {
  if (_saving) return;
  _urlDraft = $('read-url')?.value || _urlDraft;
  const url = _urlDraft.trim();
  if (!url) { _saveError = 'Paste a URL first.'; _render(); $('read-url')?.focus(); return; }
  _saving = true;
  _saveError = '';
  _render();
  try {
    const response = await _fetcher('/api/read', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) });
    const result = await response.json().catch(() => { throw new Error('Could not read the save response. Check saved items before retrying.'); });
    if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : 'Could not save this URL. Try again.');
    if (!result || typeof result !== 'object' || Array.isArray(result)
      || typeof result.id !== 'string' || !result.id.trim()
      || typeof result.url !== 'string' || !result.url.trim()
      || !Number.isInteger(result.read_minutes) || result.read_minutes < 1) {
      throw new Error('Save was not confirmed. Check saved items before retrying.');
    }
    _urlDraft = '';
    toast(`saved · ${result.read_minutes} min read`, 'success');
    await loadRead();
  } catch (error) {
    _saveError = error instanceof TypeError ? 'Could not connect. Check your connection and try again.' : (error.message || 'Could not save this URL. Try again.');
  } finally {
    _saving = false;
    _render();
    $('read-url')?.focus();
  }
}

let _openGeneration = 0;
export async function openReadItem(id, isCurrent = () => Boolean($('read-body')?.getClientRects().length), expectedHash = '') {
  const run = ++_openGeneration;
  try {
    const item = await _json(_fetcher, `/api/read/${encodeURIComponent(id)}`);
    if (run !== _openGeneration || !isCurrent()) return false;
    _open = item;
    _open.sourceChanged = !!expectedHash && expectedHash !== item.content_hash;
    const previous = _places.get(id)?.place;
    if (previous && !previous.unsaved && !previous.pending) _places.delete(id);
    _returnItem = id;
    _render();
    $('read-back')?.focus();
  } catch {
    if (run !== _openGeneration || !isCurrent()) return false;
    _open = null;
    _render();
    $('read-q')?.focus();
    toast('could not open', 'error');
    return false;
  }
  return true;
}
