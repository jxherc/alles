// activity timeline — one reverse-chron feed of everything that happened across
// alles, grouped by day. reads /api/timeline (a read-time aggregator over the
// apps' own tables), filterable by source. clicking a row jumps to its app.
import { calendarDateKey, formatCalendarDate, formatTime, t, tp } from './i18n.js';
import { replaceRouteUrl } from './route_history.js';
import { toast } from './util.js';
import { icon } from './icons.js';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const TYPES = [
  { key: 'journal', label: 'server.activity_journal' }, { key: 'task', label: 'server.activity_task' },
  { key: 'calendar', label: 'server.activity_calendar' }, { key: 'money', label: 'server.activity_money' },
  { key: 'mail', label: 'server.activity_mail' }, { key: 'photo', label: 'server.activity_photo' },
  { key: 'doc', label: 'server.activity_doc' }, { key: 'agent', label: 'server.activity_agent' },
  { key: 'sub', label: 'server.activity_sub' },
];
// each kind's svg icon from the shared set (these were text glyphs: ✎ ✓ ◷ $ ✉ ▣ ❏ ⟳ ↻)
const ICON = { journal: 'edit', task: 'check-circle', calendar: 'calendar', money: 'dollar', mail: 'mail', photo: 'image', doc: 'file', agent: 'sparkles', sub: 'refresh' };
const glyph = kind => icon(ICON[kind] || 'clock');
const LABEL = Object.fromEntries(TYPES.map(item => [item.key, item.label]));
const typeLabel = key => (LABEL[key] ? t(LABEL[key]) : key);

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

const RANGES = [[7, 'health.range_7d'], [30, 'health.range_30d'], [90, 'health.range_90d'], [365, 'health.range_1y']];

function renderFilters() {
  const wrap = $('activity-filters');
  if (!wrap) return;
  const chips = TYPES.map(item =>
    `<button type="button" class="act-chip${_off.has(item.key) ? ' off' : ''}" data-k="${item.key}" aria-pressed="${!_off.has(item.key)}">${glyph(item.key)} ${esc(t(item.label))}</button>`).join('');
  const ranges = `<span class="seg seg-sm act-seg" role="group" aria-label="${esc(t('server.activity_time_range'))}">${RANGES.map(([d, l]) =>
    `<button type="button" class="seg-opt${d === _days ? ' active' : ''}" data-d="${d}" aria-pressed="${d === _days}">${esc(t(l))}</button>`).join('')}</span>`;
  const search = `<input type="text" id="act-search" class="act-search" placeholder="${esc(t('server.activity_search'))}" aria-label="${esc(t('server.activity_search_label'))}" value="${esc(_q)}">`;
  wrap.innerHTML = chips + ranges + search;
  wrap.querySelectorAll('.act-chip').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.k;
    if (_off.has(k)) _off.delete(k); else _off.add(k);
    b.classList.toggle('off');
    b.setAttribute('aria-pressed', String(!_off.has(k)));
    localStorage.setItem(_hk, JSON.stringify([..._off]));
    _writeUrl();
    load();
  }));
  wrap.querySelectorAll('.act-seg .seg-opt').forEach(b => b.addEventListener('click', () => {
    _days = +b.dataset.d || 30;
    wrap.querySelectorAll('.act-seg .seg-opt').forEach(x => { x.classList.toggle('active', x === b); x.setAttribute('aria-pressed', String(x === b)); });
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
  body.innerHTML = `<div class="activity-empty" role="status">${esc(t('server.activity_loading'))}</div>`;
  if (restoreFocus) { body.tabIndex = -1; body.focus({ preventScroll: true }); }
  const summary = $('activity-summary');
  if (summary) summary.innerHTML = '';
  const want = TYPES.map(item => item.key).filter(k => !_off.has(k));
  if (!want.length) { body.innerHTML = `<div class="activity-empty">${esc(t('server.activity_all_hidden'))}</div>`; return; }
  let d;
  try {
    const qp = _q ? `&q=${encodeURIComponent(_q)}` : '';
    const response = await fetcher(`/api/timeline?days=${_days}&limit=200&types=${want.join(',')}${qp}`);
    if (!response.ok) throw new Error('activity unavailable');
    d = await response.json();
  } catch {
    if (sequence === _loadSequence) renderProblem(t('server.activity_load_failed'), fetcher, restoreFocus);
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
      `<span class="act-sum-chip"><span class="act-sum-glyph act-${x.type}">${glyph(x.type)}</span>${x.count} ${esc(typeLabel(x.type))}</span>`).join('');
    const busy = s.busiest ? `<span class="act-sum-busy">${esc(t('server.activity_busiest', { day: dayLabel(s.busiest.date), count: s.busiest.count }))}</span>` : '';
    const total = s.partial_sources?.length ? tp('server.activity_available_events', s.total) : tp('server.activity_events', s.total);
    strip.innerHTML = `<span class="act-sum-total">${total}</span>${chips}${busy}`;
  } catch {}
}

function problem(message) {
  return `<div class="activity-status" role="status"><span>${esc(message)}</span><button type="button" class="btn activity-retry">${esc(t('common.retry'))}</button></div>`;
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
  if (diff === 0) return t('common.today');
  if (diff === 1) return t('server.activity_yesterday');
  if (diff < 7) return formatCalendarDate(day, { weekday: 'long' });
  return formatCalendarDate(day, { month: 'short', day: 'numeric', year: day.slice(0, 4) === today.slice(0, 4) ? undefined : 'numeric' });
}
const timeOf = iso => { const d = new Date(iso); return iso.includes('T') && !iso.endsWith('T00:00:00') ? formatTime(d, { hour: 'numeric', minute: '2-digit' }) : ''; };

// the server words these lines in english; the catalog has them by pattern
const SUBTITLES = { edited: 'server.activity_ev_edited', added: 'server.activity_ev_added', completed: 'server.activity_ev_completed', 'all-day': 'calendar.all_day_row' };
const TITLES = { transaction: 'money.kind_transaction', photo: 'photos.photo', '(no subject)': 'mail.no_subject' };
function eventTitle(title = '') {
  if (TITLES[title]) return t(TITLES[title]);
  let m = /^(.+) renewed$/.exec(title);
  if (m) return t('server.activity_ev_renewed', { name: m[1] });
  m = /^journaled · (.+)$/.exec(title);
  if (m) return t('server.activity_ev_journaled', { date: m[1] });
  m = /^agent run · (.*)$/.exec(title);
  if (m) return t('server.activity_ev_agent_run', { status: m[1] });
  return title;
}
function eventSubtitle(subtitle = '') {
  if (SUBTITLES[subtitle]) return t(SUBTITLES[subtitle]);
  let m = /^from (.+)$/.exec(subtitle);
  if (m) return t('server.activity_ev_from', { name: m[1] });
  m = /^(\d+) steps?$/.exec(subtitle);
  if (m) return Number(m[1]) === 1 ? t('server.activity_ev_step') : t('server.activity_ev_steps', { count: m[1] });
  return subtitle;
}

function render(events, partialSources = [], fetcher = fetch) {
  const body = $('activity-body');
  const partial = partialSources.length
    ? problem(t('server.activity_finance_unavailable'))
    : '';
  if (!events.length) {
    body.innerHTML = partial || `<div class="activity-empty">${esc(t('server.activity_nothing'))}</div>`;
    bindRetry(fetcher);
    return;
  }
  let html = '', curDay = '';
  for (const e of events) {
    const dl = dayLabel(e.ts);
    if (dl !== curDay) { curDay = dl; html += `<div class="activity-day">${esc(dl)}</div>`; }
    const title = eventTitle(e.title);
    const subtitle = eventSubtitle(e.subtitle);
    const label = [typeLabel(e.type), title, subtitle].filter(Boolean).join(', ');
    html += `<button type="button" class="activity-row" aria-label="${esc(label)}" data-type="${esc(e.type)}" data-view="${esc(e.view)}" data-id="${esc(e.id)}">
      <span class="activity-glyph act-${esc(e.type)}" aria-hidden="true">${glyph(e.type)}</span>
      <span class="activity-main">
        <span class="activity-title">${esc(title)}</span>
        ${subtitle ? `<span class="activity-sub">${esc(subtitle)}</span>` : ''}
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
        // a doc that's gone stays here with its path named, like a run that's gone. opening the
        // link would land on docs under a generic "could not open this item"
        const response = await fetcher(`/api/vault-md/file?path=${encodeURIComponent(id)}`);
        const doc = response.ok ? await response.json().catch(() => null) : null;
        if (!current()) return;
        if (doc?.exists === false) throw new Error(t('server.activity_doc_gone', { id }));
        await window._openRecord?.('wiki', id);
      } else if (type === 'agent') {
        // These are conversation runs, distinct from the scheduled jobs in Home.
        const response = await fetcher(`/api/agent/runs/${encodeURIComponent(id)}`);
        if (!response.ok) throw new Error(t('server.activity_run_gone'));
        const run = await response.json();
        if (!current()) return;
        if (run.id !== id || !/^[a-zA-Z0-9_-]{1,160}$/.test(run.session_id || '')) throw new Error(t('server.activity_run_no_chat'));
        const historyResponse = await fetcher(`/api/sessions/${encodeURIComponent(run.session_id)}/history`);
        if (!historyResponse.ok) throw new Error(t('server.activity_chat_gone'));
        const history = await historyResponse.json();
        if (!current()) return;
        if (history.session?.id !== run.session_id || !Array.isArray(history.messages)) throw new Error(t('server.activity_chat_unconfirmed'));
        const message = history.messages.find(item => item.role === 'assistant' && item.meta?.agent_run_id === id);
        if (!await window._openSearchResult?.('chat', run.session_id, message?.id || '')) throw new Error(t('server.activity_chat_open_failed'));
      } else if (view) await window._navigateTo?.(view);
    } catch (error) {
      if (sequence === _openSequence) toast(error.message || t('server.activity_open_failed'), 'error');
    }
  }));
}
