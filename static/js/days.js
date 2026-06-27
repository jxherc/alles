// days — countdowns to what's ahead, day counts since what's behind.
// the server resolves each event's target date (and repeat rollover); the
// count/mode are recomputed here against the *viewer's* local midnight, so the
// numbers are never off by the server's timezone.
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
import { initDatePicker } from './datepick.js';
import { confirm as dlgConfirm } from './dialog.js';

const $ = id => document.getElementById(id);
let _events = [];
let _editing = null;
let _midnightTimer = null;
let _lastRenderDay = '';

export async function loadDays() {
  try {
    _events = (await fetch('/api/days').then(r => r.json())).events || [];
  } catch { _events = []; }
  _render();
}

export function initDaysPanel() {
  loadDays();
  initCustomDropdown($('day-repeat'));
  initDatePicker($('day-date'));
  _armMidnightRefresh();
  if (!$('day-add-btn') || $('day-add-btn').dataset.wired) return;
  $('day-add-btn').dataset.wired = '1';
  $('day-add-btn').addEventListener('click', _add);
  $('day-name')?.addEventListener('keydown', e => { if (e.key === 'Enter') _add(); });
  // an open tab shouldn't go stale across midnight / while backgrounded
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && _lastRenderDay !== _todayLocal().toDateString()) loadDays();
  });
}

async function _add() {
  const name = $('day-name')?.value.trim();
  const dt = $('day-date')?.value;
  if (!name) { toast('what are we counting?', 'error'); return; }
  if (!dt) { toast('pick a date', 'error'); return; }
  const r = await fetch('/api/days', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      name, date: dt.slice(0, 10),
      repeat: $('day-repeat')?.dataset.value || 'none',
      category: $('day-category')?.value.trim() || '',
    }),
  });
  if (!r.ok) { toast((await r.json()).detail || 'failed to add', 'error'); return; }
  ['day-name', 'day-category'].forEach(id => { if ($(id)) $(id).value = ''; });
  toast(`counting ${name}`, 'success');
  loadDays();
}

// ── local-time derivation ───────────────────────────────────────────────────
function _todayLocal() {
  const n = new Date();
  return new Date(n.getFullYear(), n.getMonth(), n.getDate());
}

function _breakdown(a, b) {
  if (a > b) [a, b] = [b, a];
  let y = b.getFullYear() - a.getFullYear();
  let m = b.getMonth() - a.getMonth();
  let d = b.getDate() - a.getDate();
  if (d < 0) { m--; d += new Date(b.getFullYear(), b.getMonth(), 0).getDate(); }
  if (m < 0) { y--; m += 12; }
  const p = [];
  if (y) p.push(`${y} year${y !== 1 ? 's' : ''}`);
  if (m) p.push(`${m} month${m !== 1 ? 's' : ''}`);
  if (d || !p.length) p.push(`${d} day${d !== 1 ? 's' : ''}`);
  return p.join(' ');
}

// recompute count/mode/breakdown against the viewer's local today
// (today is injectable for tests; defaults to the real local midnight)
export function _derive(e, today = _todayLocal()) {
  if (!(today instanceof Date)) today = _todayLocal();  // guard: Array.map passes the index as arg 2
  const target = new Date(e.target + 'T00:00:00');
  let days = Math.round((target - today) / 86400000);
  // the server resolves a recurring event to its next occurrence, never the past — so if a
  // viewer east of the server computes a small negative on the event day, that's a timezone
  // artifact, not "since". clamp it to today instead of flipping to "N days since".
  if (e.repeat && e.repeat !== 'none' && days < 0) days = 0;
  const mode = days === 0 ? 'today' : (days > 0 ? 'countdown' : 'since');
  return { ...e, days, count: Math.abs(days), mode, breakdown: days ? _breakdown(today, target) : '' };
}

function _armMidnightRefresh() {
  clearTimeout(_midnightTimer);
  const n = new Date();
  const next = new Date(n.getFullYear(), n.getMonth(), n.getDate() + 1, 0, 0, 30);
  _midnightTimer = setTimeout(() => { loadDays(); _armMidnightRefresh(); }, next - n);
}

// ── labels ──────────────────────────────────────────────────────────────────
function _ord(n) {
  const t = n % 100;
  if (t >= 11 && t <= 13) return 'th';
  return { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th';
}

function _unitLabel(e) {
  if (e.mode === 'today') return e.repeat !== 'none' && e.nth > 1 ? `${e.nth}${_ord(e.nth)} — today!` : 'today!';
  if (e.mode === 'since') return e.count === 1 ? 'day since' : 'days since';
  return e.count === 1 ? 'day left' : 'days left';
}

function _fmtDate(e) {
  const d = new Date(e.target + 'T00:00:00');
  const near = e.mode !== 'since' && e.days <= 7;   // weekday helps when it's close
  const opts = near ? { weekday: 'short', month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString('en-US', opts).toLowerCase();
}

function _metaLine(e) {
  const bits = [_fmtDate(e)];
  if (e.repeat === 'yearly') bits.push(`${_si('refresh')} yearly${e.nth > 0 ? ` · ${e.nth}${_ord(e.nth)}` : ''}`);
  if (e.repeat === 'monthly') bits.push(`${_si('refresh')} monthly${e.nth > 0 ? ` · ${e.nth}${_ord(e.nth)}` : ''}`);
  if (e.category) bits.push(esc(e.category));
  return bits.join(' · ');
}

// ── render ──────────────────────────────────────────────────────────────────
function _render() {
  _lastRenderDay = _todayLocal().toDateString();
  const grid = $('days-grid');
  if (!grid) return;

  const derived = _events.map(e => _derive(e));  // not map(_derive) — that leaks the index in as `today`
  const sum = $('days-summary');
  if (sum) {
    const c = m => derived.filter(x => x.mode === m).length;
    const bits = [];
    if (c('today')) bits.push(`${c('today')} today`);
    if (c('countdown')) bits.push(`${c('countdown')} upcoming`);
    if (c('since')) bits.push(`${c('since')} counting up`);
    sum.textContent = bits.join(' · ');
  }

  if (!derived.length) {
    grid.innerHTML = '<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">nothing counted yet — a trip, a birthday, a streak. add one below.</div>';
    return;
  }

  // editing renders the card in place (its own section), not yanked to the top
  const cardOf = e => e.id === _editing ? _editCard(e) : _card(e);
  const sections = [
    ['today',     derived.filter(x => x.mode === 'today').sort(_byPinThenName)],
    ['upcoming',  derived.filter(x => x.mode === 'countdown').sort(_byPinThenSoonest)],
    ['counting up', derived.filter(x => x.mode === 'since').sort((a, b) => a.count - b.count)],
  ];
  grid.innerHTML = sections
    .filter(([, list]) => list.length)
    .map(([label, list]) => `<div class="day-section">${label}</div>` + list.map(cardOf).join(''))
    .join('');
  _wire(grid);
}

function _byPinThenName(a, b) {
  return (b.pinned - a.pinned) || a.name.localeCompare(b.name);
}
function _byPinThenSoonest(a, b) {
  return (b.pinned - a.pinned) || (a.days - b.days);
}

function _card(e) {
  const tip = e.breakdown ? `${esc(e.breakdown)}${e.notes ? ' — ' + esc(e.notes) : ''}` : esc(e.notes || '');
  return `
    <div class="day-card${e.mode === 'today' ? ' today' : ''}${e.mode === 'since' ? ' since' : ''}${e.days >= 1 && e.days <= 3 ? ' soon' : ''}" data-id="${e.id}"${tip ? ` title="${tip}"` : ''}>
      <button class="day-pin${e.pinned ? ' on' : ''}" data-act="pin" title="${e.pinned ? 'unpin' : 'pin to top'}">${_si(e.pinned ? 'star-fill' : 'star')}</button>
      <div class="day-num">${e.mode === 'today' ? _si('party') : e.count.toLocaleString()}</div>
      <div class="day-unit">${_unitLabel(e)}</div>
      <div class="day-name">${esc(e.name)}</div>
      <div class="day-meta">${_metaLine(e)}</div>
      ${e.progress != null && e.mode !== 'today' ? `<div class="day-bar"><i style="width:${Math.round(e.progress * 100)}%"></i></div>` : ''}
      <div class="day-actions">
        <button class="btn" data-act="edit">edit</button>
        <button class="btn danger" data-act="del">×</button>
      </div>
    </div>`;
}

function _editCard(e) {
  return `
    <div class="day-card editing" data-id="${e.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(e.name)}" placeholder="name">
      <div class="date-input" data-f="date" data-type="date" data-value="${esc(e.date)}" data-ph="date"></div>
      <div class="settings-input custom-select" data-f="repeat" data-value="${esc(e.repeat || 'none')}" data-options="none|one-time;yearly|every year;monthly|every month"></div>
      <input type="text" class="settings-input" data-f="category" value="${esc(e.category)}" placeholder="category">
      <input type="text" class="settings-input" data-f="notify_days" value="${e.notify_days}" title="push reminder N days before (-1 = off, 0 = day of)" inputmode="numeric" placeholder="remind">
      <input type="text" class="settings-input" data-f="notes" value="${esc(e.notes)}" placeholder="notes">
      <div class="day-actions">
        <button class="btn primary" data-act="save">save</button>
        <button class="btn" data-act="cancel">cancel</button>
      </div>
    </div>`;
}

function _wire(grid) {
  grid.querySelectorAll('.day-card.editing .custom-select').forEach(initCustomDropdown);
  grid.querySelectorAll('.day-card.editing .date-input').forEach(initDatePicker);
  grid.querySelectorAll('.day-card').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'edit') { _editing = id; _render(); return; }
      if (act === 'cancel') { _editing = null; _render(); return; }
      if (act === 'pin') {
        const e = _events.find(x => x.id === id);
        await fetch(`/api/days/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ pinned: !e.pinned }),
        });
        loadDays(); return;
      }
      if (act === 'del') {
        const e = _events.find(x => x.id === id);
        if (!await dlgConfirm(`stop counting ${e?.name || 'this'}?`)) return;
        await fetch(`/api/days/${id}`, { method: 'DELETE' });
        loadDays(); return;
      }
      if (act === 'save') {
        const v = f => card.querySelector(`[data-f="${f}"]`)?.value;
        const r = await fetch(`/api/days/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            name: v('name')?.trim(), date: v('date'), repeat: v('repeat'),
            category: v('category')?.trim() || '', notes: v('notes') || '',
            notify_days: Number.isNaN(parseInt(v('notify_days'), 10)) ? undefined : parseInt(v('notify_days'), 10),
          }),
        });
        if (!r.ok) { toast((await r.json()).detail || 'save failed', 'error'); return; }
        _editing = null;
        toast('saved', 'success');
        loadDays(); return;
      }
    }));
  });
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
