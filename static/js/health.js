// health — a simple health/fitness log. log weight/sleep/workout/meds/custom, see the
// latest reading + a hand-drawn trend line per metric over a range. mirrors panel conventions.
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js?v=212';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { wireChoiceGroup } from './kokuen.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _data = { kinds: [], days: 30 };
let _entries = [];
let _days = 30;
let _adding = false;
let _fetcher = fetch;
let _hasOverview = false;
let _hasEntries = false;
let _loadState = { state: 'resting', message: '' };

const KIND_UNIT = { weight: 'kg', sleep: 'h', workout: 'min', med: '', custom: '' };
const KIND_LABEL = { weight: 'weight', sleep: 'sleep', workout: 'workout', med: 'meds', custom: 'custom' };
const RANGES = [[7, '7d'], [30, '30d'], [90, '90d'], [365, '1y']];

export function initHealth(fetcher = fetch) {
  _fetcher = fetcher;
  return loadHealth(fetcher);
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
      message: `partial health data: ${unavailable} unavailable.`,
    };
  }
  const retained = _hasOverview || _hasEntries ? ' Showing the last loaded health data.' : '';
  return {
    state: offline ? 'offline' : 'error',
    message: `${offline ? 'You appear to be offline.' : 'Health data could not be loaded.'}${retained}`,
  };
}

function _loadNotice() {
  if (_loadState.state === 'resting') return '';
  const loading = _loadState.state === 'loading';
  return `<div class="specialist-group-note legacy-load-note" role="${loading ? 'status' : 'alert'}" aria-live="${loading ? 'polite' : 'assertive'}" data-kokuen-state="${_loadState.state}">
    <span>${esc(_loadState.message)}</span>${loading ? '' : '<button type="button" class="btn" data-act="retry-load">retry</button>'}
  </div>`;
}

export async function loadHealth(fetcher = _fetcher) {
  _fetcher = fetcher;
  _loadState = { state: 'loading', message: 'loading health data…' };
  _render();
  const [overviewResult, entriesResult] = await Promise.allSettled([
    _json(fetcher, '/api/health/overview?days=' + _days),
    _json(fetcher, '/api/health'),
  ]);
  const failures = [];
  const successes = [];
  if (overviewResult.status === 'fulfilled' && Array.isArray(overviewResult.value.kinds)) {
    _data = overviewResult.value;
    _hasOverview = true;
    successes.push('health overview');
  } else failures.push(['health overview', overviewResult.reason]);
  if (entriesResult.status === 'fulfilled' && Array.isArray(entriesResult.value.entries)) {
    _entries = entriesResult.value.entries;
    _hasEntries = true;
    successes.push('recent entries');
  } else failures.push(['recent entries', entriesResult.reason]);
  _loadState = failures.length ? _loadFailure(failures, successes) : { state: 'resting', message: '' };
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
  const anom = k.anomaly
    ? `<span class="health-anom ${k.anomaly.dir}" title="outside your usual range">${k.anomaly.dir === 'high' ? '▲ above usual' : '▼ below usual'}</span>` : '';
  const base = (k.baseline && k.baseline.n >= 5)
    ? `<div class="health-baseline">usual ${_fmtNum(k.baseline.mean)}<span>${esc(unit)}</span> <span class="health-pm">± ${_fmtNum(k.baseline.std)}</span></div>` : '';
  return `
    <div class="health-card" data-kind="${esc(k.kind)}">
      <div class="health-card-h">${esc(label)}
        <button class="health-target-btn${tgt != null ? ' on' : ''}" data-act="set-target" title="set a target">${tgt != null ? `◎ ${_fmtNum(tgt)}` : 'set target'}</button>
      </div>
      <div class="health-latest">${k.latest ? `${_fmtNum(k.latest.value)}<span>${esc(unit)}</span>` : '—'}${anom}</div>
      ${base}
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
      <div class="health-ranges" role="radiogroup" aria-label="health history range">${RANGES.map(([d, l]) => `<button type="button" role="radio" aria-checked="${_days === d}" class="health-chip${_days === d ? ' active' : ''}" data-days="${d}">${l}</button>`).join('')}</div>
      <div class="health-bar-actions">
        <button class="btn" id="health-import" title="import a date,kind,value,unit csv">import</button>
        <button class="btn primary" id="health-add-toggle">${_si('plus')} entry</button>
      </div>
    </div>
    ${_loadNotice()}
    ${_adding ? _addForm() : ''}
    ${_data.kinds.length ? `<div class="health-grid">${_data.kinds.map(_kindCard).join('')}</div>`
      : (_adding || !_hasOverview || _loadState.state !== 'resting' ? '' : `
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
        <input type="text" class="settings-input" id="health-label" placeholder="metric name (for custom)">
        <input type="text" class="settings-input" id="health-note" placeholder="note (optional)">
        <button class="btn primary" id="health-create">add</button>
        <button class="btn" id="health-cancel">cancel</button>
      </div>
    </div>`;
}

function _wire(body) {
  wireChoiceGroup(body.querySelector('.health-ranges'));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => loadHealth());
  body.querySelectorAll('.health-chip').forEach(c => c.addEventListener('click', () => { _days = +c.dataset.days; loadHealth(); }));
  $('health-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _render(); });
  $('health-empty-add')?.addEventListener('click', () => { _adding = true; _render(); });
  $('health-import')?.addEventListener('click', () => {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.csv,text/csv';
    inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return;
      const r = await fetch('/api/health/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: await f.text() }) });
      const d = await r.json().catch(() => ({}));
      toast(`imported ${d.imported || 0} entr${d.imported === 1 ? 'y' : 'ies'}`, 'success'); loadHealth();
    };
    inp.click();
  });

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
    body: JSON.stringify({ kind, value, unit: $('health-unit')?.value.trim() || '', note: $('health-note')?.value.trim() || '', label: kind === 'custom' ? ($('health-label')?.value.trim() || '') : '' }),
  });
  if (!r.ok) { toast('failed to add', 'error'); return; }
  _adding = false; toast('logged', 'success'); loadHealth();
}
