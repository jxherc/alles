// read — a read-later archive. paste a URL, alles fetches + stores the readable text
// (reusing the research extractor) so it's searchable offline and the link can't rot.
// list + reader views; mirrors the watch/habits panel conventions.
import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _items = [];
let _filter = 'all';
let _q = '';
let _open = null;   // full item being read
let _feeds = [];
let _showFeeds = false;

export function initRead() { loadRead(); }

async function loadFeeds() {
  try { _feeds = (await fetch('/api/read/feeds').then(r => r.json())).feeds || []; }
  catch { _feeds = []; }
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
      : '<div class="read-feeds-empty">no feeds yet — add an rss/atom url and new posts auto-save into your list.</div>'}
  </div>`;
}

export async function loadRead() {
  const params = new URLSearchParams();
  if (_filter && _filter !== 'all') params.set('filter', _filter);
  if (_q) params.set('q', _q);
  // the search box triggers loadRead on a debounce; _render rebuilds the whole body
  // so remember if we were typing in it + the caret, and put focus back after.
  const wasSearching = document.activeElement?.id === 'read-q';
  const caret = wasSearching ? document.activeElement.selectionStart : null;
  try { _items = (await fetch('/api/read?' + params).then(r => r.json())).items || []; }
  catch { _items = []; }
  _render();
  if (wasSearching) {
    const q = $('read-q');
    if (q) { q.focus(); if (caret != null) try { q.setSelectionRange(caret, caret); } catch {} }
  }
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

const FILTERS = [['all', 'all'], ['unread', 'unread'], ['fav', 'starred'], ['archived', 'archive']];

function _render() {
  const body = $('read-body');
  if (!body) return;
  if (_open) { _renderReader(body); return; }
  body.innerHTML = `
    <div class="read-add">
      <input type="text" id="read-url" class="settings-input" placeholder="paste a URL to save for later…" spellcheck="false">
      <button class="btn primary" id="read-save">${_si('plus')} save</button>
    </div>
    <div class="read-toolbar">
      <div class="read-filters">${FILTERS.map(([k, l]) => `<button class="read-chip${_filter === k ? ' active' : ''}" data-filter="${k}">${l}</button>`).join('')}<button class="read-chip${_showFeeds ? ' active' : ''}" id="read-feeds-btn" title="rss feeds">feeds</button></div>
      <div class="read-search"><input type="text" id="read-q" class="settings-input" placeholder="search saved…" value="${esc(_q)}" spellcheck="false"></div>
    </div>
    ${_showFeeds ? _feedsPanel() : ''}
    ${_items.length ? `<div class="read-list">${_items.map(_card).join('')}</div>`
      : `<div class="read-empty">${_q ? 'nothing matches that search.' : 'nothing saved yet — paste a link above and alles will keep the article text here, searchable, forever.'}</div>`}`;
  _wire(body);
}

function _card(it) {
  const tags = (it.tags || '').split(',').map(t => t.trim()).filter(Boolean);
  return `
    <div class="read-card${it.read ? ' is-read' : ''}" data-id="${it.id}">
      <div class="read-card-main" data-open="${it.id}">
        <div class="read-card-title">${it.fav ? `<span class="read-fav-dot">${_si('star')}</span>` : ''}${esc(it.title)}</div>
        <div class="read-card-excerpt">${esc(it.excerpt)}</div>
        <div class="read-card-meta">${esc(it.site)} · ${it.read_minutes} min${it.read ? ' · read' : ''}${tags.length ? ' · ' + tags.map(t => `#${esc(t)}`).join(' ') : ''}</div>
      </div>
      <div class="read-card-actions">
        <button class="icon-btn${it.fav ? ' on' : ''}" data-act="fav" title="${it.fav ? 'unstar' : 'star'}">${_si(it.fav ? 'star-fill' : 'star')}</button>
        <button class="icon-btn" data-act="read" title="${it.read ? 'mark unread' : 'mark read'}">${_si('check')}</button>
        <button class="icon-btn" data-act="archive" title="${it.archived ? 'unarchive' : 'archive'}">${_si('archive')}</button>
        <button class="icon-btn danger" data-act="del" title="delete">${_si('trash')}</button>
      </div>
    </div>`;
}

function _renderReader(body) {
  const it = _open;
  const paras = (it.text || '').split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
  body.innerHTML = `
    <div class="read-reader">
      <div class="read-reader-bar">
        <button class="btn" id="read-back">${_si('chevron-left') || '←'} back</button>
        <a class="btn" href="${esc(it.url)}" target="_blank" rel="noopener">open original ${_si('link')}</a>
      </div>
      <article class="read-article">
        <h1>${esc(it.title)}</h1>
        <div class="read-article-meta">${esc(it.site)} · ${it.read_minutes} min read</div>
        ${paras.length ? paras.map(p => `<p>${esc(p)}</p>`).join('') : `<p class="read-empty">no readable text was extracted for this page — <a href="${esc(it.url)}" target="_blank" rel="noopener">open the original</a>.</p>`}
      </article>
    </div>`;
  $('read-back').addEventListener('click', () => { _open = null; loadRead(); });
}

function _wire(body) {
  const save = () => _save();
  $('read-save')?.addEventListener('click', save);
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
      const r = await fetch('/api/read/feeds', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) });
      if (!r.ok) { toast((await r.json()).detail || 'failed', 'error'); return; }
      await loadFeeds(); _render();
    };
    $('feed-add')?.addEventListener('click', addFeed);
    $('feed-url')?.addEventListener('keydown', e => { if (e.key === 'Enter') addFeed(); });
    $('feed-refresh')?.addEventListener('click', async () => {
      const btn = $('feed-refresh'); if (btn) btn.textContent = '…';
      await fetch('/api/read/feeds/refresh', { method: 'POST' });
      toast('feeds refreshed', 'success');
      await loadFeeds(); await loadRead();   // loadRead re-renders with any new items
    });
    body.querySelectorAll('[data-feed-del]').forEach(b => b.addEventListener('click', async () => {
      await fetch(`/api/read/feeds/${b.dataset.feedDel}`, { method: 'DELETE' });
      await loadFeeds(); _render();
    }));
  }

  const qEl = $('read-q');
  if (qEl) {
    let t = null;
    qEl.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { _q = qEl.value.trim(); loadRead(); }, 300); });
  }
  body.querySelectorAll('.read-chip').forEach(c => c.addEventListener('click', () => { _filter = c.dataset.filter; loadRead(); }));

  body.querySelectorAll('[data-open]').forEach(el => el.addEventListener('click', async () => {
    try { _open = await fetch(`/api/read/${el.dataset.open}`).then(r => r.json()); _render(); }
    catch { toast('could not open', 'error'); }
    // mark read on open if it wasn't
    const it = _items.find(x => x.id === el.dataset.open);
    if (it && !it.read) fetch(`/api/read/${el.dataset.open}/read`, { method: 'POST' });
  }));

  body.querySelectorAll('.read-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async e => {
      e.stopPropagation();
      const act = btn.dataset.act;
      const it = _items.find(x => x.id === id);
      if (act === 'del') {
        if (!await dlgConfirm('delete this saved item?')) return;
        await fetch(`/api/read/${id}`, { method: 'DELETE' }); toast('deleted', 'success'); loadRead(); return;
      }
      if (act === 'fav') { await fetch(`/api/read/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ fav: !it.fav }) }); loadRead(); return; }
      if (act === 'archive') { await fetch(`/api/read/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ archived: !it.archived }) }); toast(it.archived ? 'unarchived' : 'archived', 'success'); loadRead(); return; }
      if (act === 'read') { await fetch(`/api/read/${id}/read`, { method: 'POST' }); loadRead(); return; }
    }));
  });
}

async function _save() {
  const inp = $('read-url');
  const url = inp?.value.trim();
  if (!url) { toast('paste a url first', 'error'); return; }
  const btn = $('read-save');
  if (btn) { btn.disabled = true; btn.textContent = 'saving…'; }
  const r = await fetch('/api/read', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url }) });
  if (!r.ok) { toast((await r.json()).detail || 'failed to save', 'error'); if (btn) { btn.disabled = false; } loadRead(); return; }
  const it = await r.json();
  toast(`saved · ${it.read_minutes} min read`, 'success');
  if (inp) inp.value = '';
  loadRead();
}
