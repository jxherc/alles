// activity timeline — one reverse-chron feed of everything that happened across
// alles, grouped by day. reads /api/timeline (a read-time aggregator over the
// apps' own tables), filterable by source. clicking a row jumps to its app.
import { calendarDateKey, formatCalendarDate, formatTime } from './i18n.js';
import { replaceRouteUrl } from './route_history.js';
import { toast } from './util.js';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const TYPES = [
  { key: 'journal', label: 'journal' }, { key: 'task', label: 'tasks' },
  { key: 'calendar', label: 'calendar' }, { key: 'money', label: 'money' },
  { key: 'mail', label: 'mail' }, { key: 'photo', label: 'photos' },
  { key: 'doc', label: 'docs' }, { key: 'agent', label: 'agent' },
  { key: 'sub', label: 'subs' },
];
const GLYPH = { journal: '✎', task: '✓', calendar: '◷', money: '$', mail: '✉', photo: '▣', doc: '❏', agent: '⟳', sub: '↻' };
const LABEL = Object.fromEntries(TYPES.map(t => [t.key, t.label]));

let _days = 30;
let _off = new Set();   // hidden type keys
let _q = '';
let _qTimer = null;
let _loadSequence = 0;
let _openSequence = 0;
const _hk = 'alles-activity-hidden';

function _readUrl() {
  const p = new URLSearchParams(location.search);
  const d = parseInt(p.get('days'));
  if ([7, 30, 90, 365].includes(d)) _days = d;
  const hide = p.get('hide');
  if (hide !== null) _off = new Set(hide.split(',').filter(Boolean));
  if (p.get('q')) _q = p.get('q');
}
function _writeUrl() {
  try {
    const u = new URL(location.href);
    u.searchParams.set('days', _days);
    if (_off.size) u.searchParams.set('hide', [..._off].join(',')); else u.searchParams.delete('hide');
    if (_q) u.searchParams.set('q', _q); else u.searchParams.delete('q');
    replaceRouteUrl(u);
  } catch {}
}

let _inited = false;
export function initActivity(fetcher = fetch) {
  if (!_inited) {
    _inited = true;
    try { _off = new Set(JSON.parse(localStorage.getItem(_hk) || '[]')); } catch {}
    _readUrl();   // URL wins over localStorage so a shared link restores exactly
    renderFilters();
  }
  return load(fetcher);
}

const RANGES = [[7, '7d'], [30, '30d'], [90, '90d'], [365, '1y']];

function renderFilters() {
  const wrap = $('activity-filters');
  if (!wrap) return;
  const chips = TYPES.map(t =>
    `<button class="act-chip${_off.has(t.key) ? ' off' : ''}" data-k="${t.key}">${GLYPH[t.key]} ${t.label}</button>`).join('');
  const ranges = `<span class="seg seg-sm act-seg">${RANGES.map(([d, l]) =>
    `<button class="seg-opt${d === _days ? ' active' : ''}" data-d="${d}">${l}</button>`).join('')}</span>`;
  const search = `<input type="text" id="act-search" class="act-search" placeholder="search activity…" value="${esc(_q)}">`;
  wrap.innerHTML = chips + ranges + search;
  wrap.querySelectorAll('.act-chip').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.k;
    if (_off.has(k)) _off.delete(k); else _off.add(k);
    b.classList.toggle('off');
    localStorage.setItem(_hk, JSON.stringify([..._off]));
    _writeUrl();
    load();
  }));
  wrap.querySelectorAll('.act-seg .seg-opt').forEach(b => b.addEventListener('click', () => {
    _days = +b.dataset.d || 30;
    wrap.querySelectorAll('.act-seg .seg-opt').forEach(x => x.classList.toggle('active', x === b));
    _writeUrl();
    load();
  }));
  $('act-search')?.addEventListener('input', e => {
    _q = e.target.value;
    clearTimeout(_qTimer);
    _qTimer = setTimeout(() => { _writeUrl(); load(); }, 220);
  });
}

async function load(fetcher = fetch, restoreFocus = false) {
  const body = $('activity-body');
  if (!body) return;
  const sequence = ++_loadSequence;
  body.innerHTML = '<div class="activity-empty" role="status">loading…</div>';
  if (restoreFocus) { body.tabIndex = -1; body.focus({ preventScroll: true }); }
  const summary = $('activity-summary');
  if (summary) summary.innerHTML = '';
  const want = TYPES.map(t => t.key).filter(k => !_off.has(k));
  if (!want.length) { body.innerHTML = '<div class="activity-empty">all sources hidden: turn some back on above</div>'; return; }
  let d;
  try {
    const qp = _q ? `&q=${encodeURIComponent(_q)}` : '';
    const response = await fetcher(`/api/timeline?days=${_days}&limit=200&types=${want.join(',')}${qp}`);
    if (!response.ok) throw new Error('activity unavailable');
    d = await response.json();
  } catch {
    if (sequence === _loadSequence) renderProblem('couldn’t load activity.', fetcher, restoreFocus);
    return;
  }
  if (sequence !== _loadSequence) return;
  render(d.events || [], d.partial_sources || [], fetcher);
  if (restoreFocus) (body.querySelector('.activity-retry, .activity-row') || body).focus({ preventScroll: true });
  await loadSummary(want, fetcher, sequence);
}

async function loadSummary(want, fetcher = fetch, sequence = _loadSequence) {
  try {
    const response = await fetcher(`/api/timeline/summary?days=${_days}&types=${want.join(',')}`);
    if (!response.ok) throw new Error('summary unavailable');
    const s = await response.json();
    if (sequence !== _loadSequence) return;
    const strip = $('activity-summary');
    if (!strip) return;
    if (!s.total && !s.partial_sources?.length) { strip.innerHTML = ''; return; }
    const chips = s.by_type.map(x =>
      `<span class="act-sum-chip"><span class="act-sum-glyph act-${x.type}">${GLYPH[x.type] || '·'}</span>${x.count} ${esc(LABEL[x.type] || x.type)}</span>`).join('');
    const busy = s.busiest ? `<span class="act-sum-busy">busiest · ${dayLabel(s.busiest.date)} (${s.busiest.count})</span>` : '';
    const total = s.partial_sources?.length ? `${s.total} available events` : `${s.total} events`;
    strip.innerHTML = `<span class="act-sum-total">${total}</span>${chips}${busy}`;
  } catch {}
}

function problem(message) {
  return `<div class="activity-status" role="status"><span>${esc(message)}</span><button type="button" class="btn activity-retry">retry</button></div>`;
}

function bindRetry(fetcher) {
  $('activity-body')?.querySelector('.activity-retry')?.addEventListener('click', () => load(fetcher, true));
}

function renderProblem(message, fetcher, restoreFocus = false) {
  const body = $('activity-body');
  if (!body) return;
  body.innerHTML = problem(message);
  bindRetry(fetcher);
  if (restoreFocus) body.querySelector('.activity-retry')?.focus({ preventScroll: true });
}

function dayLabel(iso) {
  // The API buckets both summary and rows by their stored calendar date.
  // Compare calendar days, without shifting date-only values through a timezone.
  const day = String(iso).slice(0, 10);
  const today = calendarDateKey();
  const diff = (Date.parse(today) - Date.parse(day)) / 86400000;
  if (diff === 0) return 'today';
  if (diff === 1) return 'yesterday';
  if (diff < 7) return formatCalendarDate(day, { weekday: 'long' });
  return formatCalendarDate(day, { month: 'short', day: 'numeric', year: day.slice(0, 4) === today.slice(0, 4) ? undefined : 'numeric' });
}
const timeOf = iso => { const d = new Date(iso); return iso.includes('T') && !iso.endsWith('T00:00:00') ? formatTime(d, { hour: 'numeric', minute: '2-digit' }) : ''; };

function render(events, partialSources = [], fetcher = fetch) {
  const body = $('activity-body');
  const partial = partialSources.length
    ? problem('finance activity is unavailable. results may be incomplete.')
    : '';
  if (!events.length) {
    body.innerHTML = partial || '<div class="activity-empty">nothing in this window</div>';
    bindRetry(fetcher);
    return;
  }
  let html = '', curDay = '';
  for (const e of events) {
    const dl = dayLabel(e.ts);
    if (dl !== curDay) { curDay = dl; html += `<div class="activity-day">${esc(dl)}</div>`; }
    const label = [LABEL[e.type] || e.type, e.title, e.subtitle].filter(Boolean).join(', ');
    html += `<button type="button" class="activity-row" aria-label="${esc(label)}" data-type="${esc(e.type)}" data-view="${esc(e.view)}" data-id="${esc(e.id)}">
      <span class="activity-glyph act-${esc(e.type)}" aria-hidden="true">${GLYPH[e.type] || '·'}</span>
      <span class="activity-main">
        <span class="activity-title">${esc(e.title)}</span>
        ${e.subtitle ? `<span class="activity-sub">${esc(e.subtitle)}</span>` : ''}
      </span>
      <span class="activity-time">${esc(timeOf(e.ts))}</span>
    </button>`;
  }
  body.innerHTML = partial + html;
  bindRetry(fetcher);
  body.querySelectorAll('.activity-row').forEach(r => r.addEventListener('click', async () => {
    const sequence = ++_openSequence;
    const current = () => sequence === _openSequence && r.isConnected && Boolean(r.getClientRects().length);
    const { type, view, id } = r.dataset;
    try {
      if (type === 'doc') {
        await window._openRecord?.('wiki', id);
      } else if (type === 'agent') {
        // These are conversation runs, distinct from the scheduled jobs in Home.
        const response = await fetcher(`/api/agent/runs/${encodeURIComponent(id)}`);
        if (!response.ok) throw new Error('this run is no longer available');
        const run = await response.json();
        if (!current()) return;
        if (run.id !== id || !/^[a-zA-Z0-9_-]{1,160}$/.test(run.session_id || '')) throw new Error('this run has no saved conversation');
        const historyResponse = await fetcher(`/api/sessions/${encodeURIComponent(run.session_id)}/history`);
        if (!historyResponse.ok) throw new Error('this run’s conversation is no longer available');
        const history = await historyResponse.json();
        if (!current()) return;
        if (history.session?.id !== run.session_id || !Array.isArray(history.messages)) throw new Error('could not confirm this run’s conversation');
        const message = history.messages.find(item => item.role === 'assistant' && item.meta?.agent_run_id === id);
        if (!await window._openSearchResult?.('chat', run.session_id, message?.id || '')) throw new Error('could not open this run’s conversation');
      } else if (view) await window._navigateTo?.(view);
    } catch (error) {
      if (sequence === _openSequence) toast(error.message || 'could not open this activity item', 'error');
    }
  }));
}
