// health — a simple health/fitness log. log weight/sleep/workout/meds/custom, see the
// latest reading + a hand-drawn trend line per metric over a range. mirrors panel conventions.
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _data = { kinds: [], days: 30 };
let _entries = [];
let _days = 30;
let _adding = false;

const KIND_UNIT = { weight: 'kg', sleep: 'h', workout: 'min', med: '', custom: '' };
const KIND_LABEL = { weight: 'weight', sleep: 'sleep', workout: 'workout', med: 'meds', custom: 'custom' };
const RANGES = [[7, '7d'], [30, '30d'], [90, '90d'], [365, '1y']];

export function initHealth() { loadHealth(); }

export async function loadHealth() {
  // check r.ok — a non-2xx (e.g. a 401 on a subdomain) still returns JSON, and a
  // {detail:…} body with no `kinds` would crash _render and blank the page.
  try {
    const ro = await fetch('/api/health/overview?days=' + _days);
    _data = ro.ok ? await ro.json() : { kinds: [], days: _days };
    const re = await fetch('/api/health');
    _entries = re.ok ? ((await re.json()).entries || []) : [];
  } catch { _data = { kinds: [], days: _days }; _entries = []; }
  if (!_data || !Array.isArray(_data.kinds)) _data = { kinds: [], days: _days };
  _render();
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function _line(series, target) {
  if (!series || series.length < 2) return '<div class="health-spark-empty">need 2+ entries to chart</div>';
  const w = 260, h = 70, pad = 4;
  const vals = series.map(p => p.value);
  let min = Math.min(...vals), max = Math.max(...vals);
  const hasT = target != null && !Number.isNaN(target);
  if (hasT) { min = Math.min(min, target); max = Math.max(max, target); }   // keep the goal line in frame
  const span = (max - min) || 1;
  const n = series.length;
  const x = i => pad + (i / (n - 1)) * (w - 2 * pad);
  const y = v => pad + (1 - (v - min) / span) * (h - 2 * pad);
  const pts = series.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const dots = series.map((p, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="1.6"/>`).join('');
  const goal = hasT ? `<line class="health-goal-line" x1="0" y1="${y(target).toFixed(1)}" x2="${w}" y2="${y(target).toFixed(1)}"/>` : '';
  return `<svg class="health-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${goal}<polyline points="${pts}"/>${dots}</svg>`;
}

function _kindCard(k) {
  const unit = (k.latest && k.latest.unit) || KIND_UNIT[k.kind] || '';
  const label = k.label || KIND_LABEL[k.kind] || k.kind;
  const tgt = (typeof k.target === 'number') ? k.target : null;
  return `
    <div class="health-card" data-kind="${esc(k.kind)}">
      <div class="health-card-h">${esc(label)}
        <button class="health-target-btn${tgt != null ? ' on' : ''}" data-act="set-target" title="set a target">${tgt != null ? `◎ ${_fmtNum(tgt)}` : 'set target'}</button>
      </div>
      <div class="health-latest">${k.latest ? `${_fmtNum(k.latest.value)}<span>${esc(unit)}</span>` : '—'}</div>
      ${_line(k.series, tgt)}
      <div class="health-card-meta">${k.latest ? esc(k.latest.date) : 'no entries'} · ${k.series.length} in range</div>
    </div>`;
}

function _fmtNum(v) { return (Math.round(v * 10) / 10).toString(); }

function _render() {
  const body = $('health-body');
  if (!body) return;
  body.innerHTML = `
    <div class="health-bar">
      <div class="health-ranges">${RANGES.map(([d, l]) => `<button class="health-chip${_days === d ? ' active' : ''}" data-days="${d}">${l}</button>`).join('')}</div>
      <button class="btn primary" id="health-add-toggle">${_si('plus')} entry</button>
    </div>
    ${_adding ? _addForm() : ''}
    ${_data.kinds.length ? `<div class="health-grid">${_data.kinds.map(_kindCard).join('')}</div>`
      : (_adding ? '' : `
        <div class="empty-state">
          <div class="empty-state-icon">${_si('heart')}</div>
          <div class="empty-state-title">no entries yet</div>
          <div class="empty-state-desc">log your weight, sleep, a workout — or any number you want to watch trend over time. each metric gets its own card and sparkline.</div>
          <button class="btn primary" id="health-empty-add">${_si('plus')} log your first entry</button>
        </div>`)}
    ${_entries.length ? `<div class="health-recent"><div class="health-recent-h">recent</div>${_entries.slice(0, 30).map(_row).join('')}</div>` : ''}`;
  _wire(body);
}

function _row(e) {
  const label = e.label || KIND_LABEL[e.kind] || e.kind;
  return `<div class="health-row" data-id="${e.id}"><span class="health-row-date">${esc(e.date)}</span><span class="health-row-kind">${esc(label)}</span><span class="health-row-val">${_fmtNum(e.value)} ${esc(e.unit)}</span>${e.note ? `<span class="health-row-note">${esc(e.note)}</span>` : '<span></span>'}<button class="icon-btn danger" data-act="del" title="delete">${_si('trash')}</button></div>`;
}

function _addForm() {
  return `
    <div class="health-add">
      <div class="health-add-row">
        <div class="settings-input custom-select" id="health-kind" data-value="weight" data-options="weight|weight;sleep|sleep;workout|workout;med|meds;custom|custom"></div>
        <input type="text" class="settings-input" id="health-value" inputmode="decimal" placeholder="value">
        <input type="text" class="settings-input health-unit" id="health-unit" value="kg" placeholder="unit">
      </div>
      <div class="health-add-row">
        <input type="text" class="settings-input" id="health-note" placeholder="note (optional)">
        <button class="btn primary" id="health-create">add</button>
        <button class="btn" id="health-cancel">cancel</button>
      </div>
    </div>`;
}

function _wire(body) {
  body.querySelectorAll('.health-chip').forEach(c => c.addEventListener('click', () => { _days = +c.dataset.days; loadHealth(); }));
  $('health-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _render(); });
  $('health-empty-add')?.addEventListener('click', () => { _adding = true; _render(); });

  if (_adding) {
    const kindEl = $('health-kind');
    initCustomDropdown(kindEl);
    // keep the unit hint synced to the chosen kind
    const syncUnit = () => { const u = $('health-unit'); if (u) u.value = KIND_UNIT[kindEl.dataset.value] ?? ''; };
    kindEl.addEventListener('change', syncUnit);
    $('health-create')?.addEventListener('click', _create);
    $('health-value')?.addEventListener('keydown', e => { if (e.key === 'Enter') _create(); });
    $('health-cancel')?.addEventListener('click', () => { _adding = false; _render(); });
  }

  body.querySelectorAll('.health-card[data-kind] [data-act="set-target"]').forEach(btn => btn.addEventListener('click', async () => {
    const kind = btn.closest('.health-card').dataset.kind;
    const cur = (_data.kinds.find(k => k.kind === kind) || {}).target;
    const v = await dlgPrompt(`target for ${kind}? (0 to clear)`, String(cur || ''));
    if (v == null) return;
    await fetch('/api/health/target', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kind, value: parseFloat(v) || 0 }) });
    loadHealth();
  }));

  body.querySelectorAll('.health-row[data-id]').forEach(row => {
    row.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
      if (!await dlgConfirm('delete this entry?')) return;
      await fetch(`/api/health/${row.dataset.id}`, { method: 'DELETE' }); loadHealth();
    });
  });
}

async function _create() {
  const kind = $('health-kind')?.dataset.value || 'weight';
  const raw = $('health-value')?.value.trim();
  const value = parseFloat(raw);
  if (raw === '' || Number.isNaN(value)) { toast('enter a number', 'error'); return; }
  const r = await fetch('/api/health', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ kind, value, unit: $('health-unit')?.value.trim() || '', note: $('health-note')?.value.trim() || '' }),
  });
  if (!r.ok) { toast('failed to add', 'error'); return; }
  _adding = false; toast('logged', 'success'); loadHealth();
}
