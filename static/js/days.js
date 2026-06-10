// days — countdowns to what's ahead, day counts since what's behind
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { initDatePicker } from './datepick.js';
import { confirm as dlgConfirm } from './dialog.js';

const $ = id => document.getElementById(id);
let _events = [];
let _summary = {};
let _editing = null;

export async function loadDays() {
  try {
    const d = await fetch('/api/days').then(r => r.json());
    _events = d.events || [];
    _summary = d.summary || {};
  } catch { _events = []; _summary = {}; }
  _render();
}

export function initDaysPanel() {
  loadDays();
  initCustomDropdown($('day-repeat'));
  initDatePicker($('day-date'));
  if (!$('day-add-btn') || $('day-add-btn').dataset.wired) return;
  $('day-add-btn').dataset.wired = '1';
  $('day-add-btn').addEventListener('click', _add);
  $('day-name')?.addEventListener('keydown', e => { if (e.key === 'Enter') _add(); });
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

function _unitLabel(e) {
  if (e.mode === 'today') return e.repeat !== 'none' && e.nth > 1 ? `${e.nth}${_ord(e.nth)} time — today!` : 'today!';
  if (e.mode === 'since') return e.count === 1 ? 'day since' : 'days since';
  return e.count === 1 ? 'day left' : 'days left';
}

function _ord(n) {
  const t = n % 100;
  if (t >= 11 && t <= 13) return 'th';
  return { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th';
}

function _metaLine(e) {
  const bits = [_fmtDate(e.target)];
  if (e.repeat === 'yearly') bits.push(`↻ yearly${e.nth > 0 ? ` · ${e.nth}${_ord(e.nth)}` : ''}`);
  if (e.repeat === 'monthly') bits.push(`↻ monthly${e.nth > 0 ? ` · ${e.nth}${_ord(e.nth)}` : ''}`);
  if (e.category) bits.push(esc(e.category));
  return bits.join(' · ');
}

function _fmtDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString('en-US', opts).toLowerCase();
}

function _render() {
  const sum = $('days-summary');
  if (sum) {
    const bits = [];
    if (_summary.today) bits.push(`${_summary.today} today`);
    if (_summary.upcoming) bits.push(`${_summary.upcoming} upcoming`);
    if (_summary.since) bits.push(`${_summary.since} counting up`);
    sum.textContent = bits.join(' · ');
  }
  const grid = $('days-grid');
  if (!grid) return;
  if (!_events.length) {
    grid.innerHTML = '<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">nothing counted yet — a trip, a birthday, a streak. add one below.</div>';
    return;
  }
  grid.innerHTML = _events.map(e => _editing === e.id ? _editCard(e) : _card(e)).join('');
  _wire(grid);
}

function _card(e) {
  const title = e.breakdown ? ` title="${esc(e.breakdown)}${e.notes ? ' — ' + esc(e.notes) : ''}"` : (e.notes ? ` title="${esc(e.notes)}"` : '');
  return `
    <div class="day-card${e.mode === 'today' ? ' today' : ''}${e.mode === 'since' ? ' since' : ''}" data-id="${e.id}"${title}>
      <button class="day-pin${e.pinned ? ' on' : ''}" data-act="pin" title="${e.pinned ? 'unpin' : 'pin to top'}">★</button>
      <div class="day-num">${e.mode === 'today' ? '🎉' : e.count.toLocaleString()}</div>
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
      <input type="date" class="settings-input" data-f="date" value="${esc(e.date)}">
      <select class="settings-input" data-f="repeat">
        ${[['none', 'one-time'], ['yearly', 'every year'], ['monthly', 'every month']].map(([v, l]) =>
          `<option value="${v}"${e.repeat === v ? ' selected' : ''}>${l}</option>`).join('')}
      </select>
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
