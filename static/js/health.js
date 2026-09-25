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
let _draft = null;
let _saving = false;
let _formError = '';
let _returnFocus = '#health-add-toggle';
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
    ${_draft ? _addForm() : ''}
    ${_data.kinds.length ? `<div class="health-grid">${_data.kinds.map(_kindCard).join('')}</div>`
      : (_draft || !_hasOverview || _loadState.state !== 'resting' ? '' : `
        <div class="empty-state">
          <div class="empty-state-icon">${_si('heart')}</div>
          <div class="empty-state-title">no entries yet</div>
          <div class="empty-state-desc">log your weight, sleep, a workout. or any number you want to watch trend over time. each metric gets its own card and sparkline.</div>
          <button class="btn primary" id="health-empty-add">${_si('plus')} log your first entry</button>
        </div>`)}
    ${_entries.length ? `<div class="health-recent"><div class="health-recent-h">recent</div>${_entries.slice(0, 30).map(_row).join('')}</div>` : ''}`;
  _wire(body);
}

function _row(e) {
  const label = e.label || KIND_LABEL[e.kind] || e.kind;
  return `<div class="health-row" data-id="${e.id}"><span class="health-row-date">${esc(e.date)}</span><span class="health-row-kind">${esc(label)}</span><span class="health-row-val">${esc(e.value)} ${esc(e.unit)}</span><span class="health-row-note">${esc(e.note)}</span><div class="health-row-actions"><button class="btn" data-act="edit" aria-label="edit ${esc(label)} entry from ${esc(e.date)}">edit</button><button class="icon-btn danger" data-act="del" title="delete" aria-label="delete ${esc(label)} entry from ${esc(e.date)}">${_si('trash')}</button></div></div>`;
}

function _addForm() {
  const editing = _draft.id != null;
  return `
    <form class="health-add" id="health-entry-form" aria-label="${editing ? 'edit' : 'new'} health entry" aria-busy="${_saving}">
      <div class="health-form-title">${editing ? `edit ${esc(_draft.label || KIND_LABEL[_draft.kind] || _draft.kind)} entry` : 'new entry'}</div>
      <fieldset ${_saving ? 'disabled' : ''}>
        ${editing ? '' : `<div class="health-field"><span id="health-kind-label">metric</span><div class="settings-input custom-select" id="health-kind" aria-labelledby="health-kind-label" aria-disabled="${_saving}" data-value="${esc(_draft.kind)}" data-options="weight|weight;sleep|sleep;workout|workout;med|meds;custom|custom"></div></div>`}
        <div class="health-add-row">
          <label class="health-field" for="health-value">value<input type="text" class="settings-input" id="health-value" value="${esc(_draft.value)}" inputmode="decimal" aria-describedby="health-entry-error"></label>
          <label class="health-field" for="health-unit">unit<input type="text" class="settings-input" id="health-unit" value="${esc(_draft.unit)}"></label>
        </div>
        <label class="health-field" for="health-date">date<input type="text" class="settings-input" id="health-date" value="${esc(_draft.date)}" placeholder="${editing ? 'YYYY-MM-DD' : 'YYYY-MM-DD (today if empty)'}"></label>
        ${!editing && _draft.kind === 'custom' ? `<label class="health-field" for="health-label">metric name<input type="text" class="settings-input" id="health-label" value="${esc(_draft.label)}"></label>` : ''}
        <label class="health-field" for="health-note">note (optional)<input type="text" class="settings-input" id="health-note" value="${esc(_draft.note)}"></label>
        <div class="health-form-actions">
          <button type="submit" class="btn primary" id="health-create">${_saving ? 'saving…' : editing ? 'save' : 'add'}</button>
          <button type="button" class="btn" id="health-cancel">cancel</button>
        </div>
      </fieldset>
      <p id="health-entry-error" role="alert" ${_formError ? '' : 'hidden'}>${esc(_formError)}</p>
    </form>`;
}

async function _openEntry(entry = null) {
  if (_saving) return;
  if (_draft && !await dlgConfirm('discard this unsaved entry?')) return;
  _returnFocus = entry ? `.health-row[data-id="${entry.id}"] [data-act="edit"]` : '#health-add-toggle';
  _draft = entry ? { ...entry, value: String(entry.value) } : { kind: 'weight', value: '', unit: 'kg', date: '', label: '', note: '' };
  _formError = '';
  _render();
  $('health-value')?.focus();
}

function _closeEntry() {
  _draft = null;
  _formError = '';
  _render();
  document.querySelector(_returnFocus)?.focus();
}

function _wire(body) {
  wireChoiceGroup(body.querySelector('.health-ranges'));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => loadHealth());
  body.querySelectorAll('.health-chip').forEach(c => c.addEventListener('click', () => { _days = +c.dataset.days; loadHealth(); }));
  $('health-add-toggle')?.addEventListener('click', () => _openEntry());
  $('health-empty-add')?.addEventListener('click', () => _openEntry());
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

  if (_draft) {
    const kindEl = $('health-kind');
    initCustomDropdown(kindEl);
    kindEl?.addEventListener('change', () => {
      _draft.kind = kindEl.dataset.value;
      _draft.unit = KIND_UNIT[_draft.kind] ?? '';
      _render();
      $('health-kind')?.focus();
    });
    for (const key of ['value', 'unit', 'date', 'label', 'note']) {
      $(`health-${key}`)?.addEventListener('input', event => { _draft[key] = event.target.value; });
    }
    $('health-entry-form')?.addEventListener('submit', event => { event.preventDefault(); _create(); });
    $('health-cancel')?.addEventListener('click', _closeEntry);
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
    row.querySelector('[data-act="edit"]')?.addEventListener('click', () => {
      const entry = _entries.find(item => String(item.id) === row.dataset.id);
      if (entry) _openEntry(entry);
    });
    row.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
      if (!await dlgConfirm('delete this entry?')) return;
      await fetch(`/api/health/${row.dataset.id}`, { method: 'DELETE' }); loadHealth();
    });
  });
}

async function _create() {
  if (!_draft || _saving) return;
  const raw = _draft.value.trim();
  const value = Number(raw);
  const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
  const date = _draft.date.trim();
  const validDate = (!date && _draft.id == null) || (/^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(date)) && new Date(date).toISOString().slice(0, 10) === date);
  _formError = !decimal.test(raw) || !Number.isFinite(value) ? 'enter a complete, finite number.' : !validDate ? 'enter a valid date as YYYY-MM-DD.' : '';
  if (_formError) {
    _render();
    $(validDate ? 'health-value' : 'health-date')?.focus();
    return;
  }
  const editing = _draft.id != null;
  const payload = { value, unit: _draft.unit.trim(), note: _draft.note.trim() };
  if (date) payload.date = date;
  if (!editing) Object.assign(payload, { kind: _draft.kind, label: _draft.kind === 'custom' ? _draft.label.trim() : '' });
  _saving = true;
  _render();
  try {
    const r = await fetch(editing ? `/api/health/${_draft.id}` : '/api/health', {
      method: editing ? 'PATCH' : 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(`save failed (${r.status}). your input is kept; try again.`);
    _draft = null;
    toast(editing ? 'entry updated' : 'logged', 'success');
    await loadHealth();
    document.querySelector(_returnFocus)?.focus();
  } catch (error) {
    _formError = error.message || 'could not save. your input is kept; try again.';
  } finally {
    _saving = false;
    if (_draft) {
      _render();
      $('health-create')?.focus();
    }
  }
}
