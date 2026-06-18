// activity timeline — one reverse-chron feed of everything that happened across
// alles, grouped by day. reads /api/timeline (a read-time aggregator over the
// apps' own tables), filterable by source. clicking a row jumps to its app.
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

let _days = 30;
let _off = new Set();   // hidden type keys
let _q = '';
let _qTimer = null;
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
    history.replaceState(null, '', u);
  } catch {}
}

let _inited = false;
export function initActivity() {
  if (!_inited) {
    _inited = true;
    try { _off = new Set(JSON.parse(localStorage.getItem(_hk) || '[]')); } catch {}
    _readUrl();   // URL wins over localStorage so a shared link restores exactly
    renderFilters();
  }
  load();
}

const RANGES = [[7, '7d'], [30, '30d'], [90, '90d'], [365, '1y']];

function renderFilters() {
  const wrap = $('activity-filters');
  if (!wrap) return;
  const chips = TYPES.map(t =>
    `<button class="act-chip${_off.has(t.key) ? ' off' : ''}" data-k="${t.key}">${GLYPH[t.key]} ${t.label}</button>`).join('');
  const ranges = `<span class="act-range">${RANGES.map(([d, l]) =>
    `<button class="act-range-opt${d === _days ? ' on' : ''}" data-d="${d}">${l}</button>`).join('')}</span>`;
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
  wrap.querySelectorAll('.act-range-opt').forEach(b => b.addEventListener('click', () => {
    _days = +b.dataset.d || 30;
    wrap.querySelectorAll('.act-range-opt').forEach(x => x.classList.toggle('on', x === b));
    _writeUrl();
    load();
  }));
  $('act-search')?.addEventListener('input', e => {
    _q = e.target.value;
    clearTimeout(_qTimer);
    _qTimer = setTimeout(() => { _writeUrl(); load(); }, 220);
  });
}

async function load() {
  const body = $('activity-body');
  if (!body) return;
  body.innerHTML = '<div class="activity-empty">loading…</div>';
  const want = TYPES.map(t => t.key).filter(k => !_off.has(k));
  if (!want.length) { body.innerHTML = '<div class="activity-empty">all sources hidden — turn some back on above</div>'; return; }
  let d;
  try {
    const qp = _q ? `&q=${encodeURIComponent(_q)}` : '';
    d = await fetch(`/api/timeline?days=${_days}&limit=200&types=${want.join(',')}${qp}`).then(r => r.json());
  } catch { body.innerHTML = '<div class="activity-empty">couldn’t load activity</div>'; return; }
  render(d.events || []);
}

function dayLabel(iso) {
  const d = new Date(iso);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const that = new Date(d); that.setHours(0, 0, 0, 0);
  const diff = Math.round((today - that) / 86400000);
  if (diff === 0) return 'today';
  if (diff === 1) return 'yesterday';
  if (diff < 7) return d.toLocaleDateString('en-US', { weekday: 'long' });
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
}
const timeOf = iso => { const d = new Date(iso); return iso.includes('T') && !iso.endsWith('T00:00:00') ? d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : ''; };

function render(events) {
  const body = $('activity-body');
  if (!events.length) { body.innerHTML = '<div class="activity-empty">nothing in this window</div>'; return; }
  let html = '', curDay = '';
  for (const e of events) {
    const dl = dayLabel(e.ts);
    if (dl !== curDay) { curDay = dl; html += `<div class="activity-day">${esc(dl)}</div>`; }
    html += `<div class="activity-row" data-view="${esc(e.view)}" data-id="${esc(e.id)}">
      <span class="activity-glyph act-${esc(e.type)}" title="${esc(e.type)}">${GLYPH[e.type] || '·'}</span>
      <span class="activity-main">
        <span class="activity-title">${esc(e.title)}</span>
        ${e.subtitle ? `<span class="activity-sub">${esc(e.subtitle)}</span>` : ''}
      </span>
      <span class="activity-time">${esc(timeOf(e.ts))}</span>
    </div>`;
  }
  body.innerHTML = html;
  body.querySelectorAll('.activity-row').forEach(r => r.addEventListener('click', () => {
    const v = r.dataset.view;
    if (v) window._navigateTo?.(v);
  }));
}
