// health — a simple health/fitness log. log weight/sleep/workout/meds/custom, see the
// latest reading + a hand-drawn trend line per metric over a range. mirrors panel conventions.
import { api, toast } from './util.js';
import { initCustomDropdown } from './dropdown.js?v=215';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { wireChoiceGroup } from './kokuen.js?v=4';
import { calendarDateKey, formatList, t, tp } from './i18n.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _data = { kinds: [], days: 30 };
let _entries = [];
let _days = 30;
let _draft = null;
let _saving = false;
let _formError = '';
let _createUncertain = false;
let _conflictId = null;
let _returnFocus = '#health-add-toggle';
let _fetcher = fetch;
let _hasOverview = false;
let _hasEntries = false;
let _loadState = { state: 'resting', message: '' };
let _loadGeneration = 0;
let _navigation = 0;
let _importDraft = null;
const _deleteErrors = new Map();
const _deleting = new Set();

const KIND_UNIT = { weight: 'kg', sleep: 'h', workout: 'min', med: '', custom: '' };
const KIND_LABEL = { weight: 'health.kind_weight', sleep: 'health.kind_sleep', workout: 'health.kind_workout', med: 'health.kind_med', custom: 'health.kind_custom' };
const kindLabel = kind => (KIND_LABEL[kind] ? t(KIND_LABEL[kind]) : kind);
const RANGES = [[7, 'health.range_7d'], [30, 'health.range_30d'], [90, 'health.range_90d'], [365, 'health.range_1y']];
const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;

function _newCreateRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function initHealth(fetcher = fetch) {
  ++_navigation;
  _fetcher = fetcher;
  return loadHealth(fetcher);
}

async function _json(fetcher, url) {
  const response = await fetcher(url);
  if (!response.ok) throw new Error(t('health.request_failed', { status: response.status || t('common.unknown') }));
  return response.json();
}

function _loadFailure(failures, successes) {
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
  if (successes.length) {
    const unavailable = formatList(failures.map(([name]) => name));
    return {
      state: 'partial',
      message: t('health.partial', { unavailable }),
    };
  }
  const retained = _hasOverview || _hasEntries ? t('health.showing_last') : '';
  return {
    state: offline ? 'offline' : 'error',
    message: `${offline ? t('health.offline') : t('health.load_failed')}${retained}`,
  };
}

function _loadNotice() {
  if (_loadState.state === 'resting') return '';
  const loading = _loadState.state === 'loading';
  return `<div class="specialist-group-note legacy-load-note" role="${loading ? 'status' : 'alert'}" aria-live="${loading ? 'polite' : 'assertive'}" data-kokuen-state="${_loadState.state}">
    <span>${esc(_loadState.message)}</span>${loading ? '' : '<button type="button" class="btn" data-act="retry-load">' + esc(t('common.retry')) + '</button>'}
  </div>`;
}

export async function loadHealth(fetcher = _fetcher, { clearWriteError = false } = {}) {
  _fetcher = fetcher;
  const generation = ++_loadGeneration;
  _loadState = { state: 'loading', message: t('health.loading') };
  _render();
  const [overviewResult, entriesResult] = await Promise.allSettled([
    _json(fetcher, '/api/health/overview?days=' + _days + '&date_q=' + calendarDateKey()),
    _json(fetcher, '/api/health'),
  ]);
  if (generation !== _loadGeneration) return;
  const failures = [];
  const successes = [];
  if (overviewResult.status === 'fulfilled' && Array.isArray(overviewResult.value.kinds)) {
    _data = overviewResult.value;
    _hasOverview = true;
    successes.push(t('health.part_overview'));
  } else failures.push([t('health.part_overview'), overviewResult.reason]);
  if (entriesResult.status === 'fulfilled' && Array.isArray(entriesResult.value.entries)) {
    _entries = entriesResult.value.entries;
    _hasEntries = true;
    if (clearWriteError) _deleteErrors.clear();
    successes.push(t('health.part_recent'));
  } else failures.push([t('health.part_recent'), entriesResult.reason]);
  _loadState = failures.length ? _loadFailure(failures, successes) : { state: 'resting', message: '' };
  _render();
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function _line(series, target) {
  if (!series || series.length < 2) return `<div class="health-spark-empty">${esc(t('health.need_two'))}</div>`;
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
  const label = k.label || kindLabel(k.kind);
  const tgt = (typeof k.target === 'number') ? k.target : null;
  const anom = k.anomaly
    ? `<span class="health-anom ${k.anomaly.dir}" title="${esc(t('health.outside_range'))}">${k.anomaly.dir === 'high' ? `${_si('trend-up')} ${esc(t('health.above_usual'))}` : `${_si('trend-down')} ${esc(t('health.below_usual'))}`}</span>` : '';
  const base = (k.baseline && k.baseline.n >= 5)
    ? `<div class="health-baseline">${esc(t('health.usual'))} ${_fmtNum(k.baseline.mean)}<span>${esc(unit)}</span> <span class="health-pm">± ${_fmtNum(k.baseline.std)}</span></div>` : '';
  return `
    <div class="health-card" data-kind="${esc(k.kind)}">
      <div class="health-card-h">${esc(label)}
        <button class="health-target-btn${tgt != null ? ' on' : ''}" data-act="set-target" title="${esc(t('health.set_a_target'))}">${tgt != null ? `${_si('target')} ${_fmtNum(tgt)}` : esc(t('health.set_target'))}</button>
      </div>
      <div class="health-latest">${k.latest ? `${_fmtNum(k.latest.value)}<span>${esc(unit)}</span>` : '—'}${anom}</div>
      ${base}
      ${_line(k.series, tgt)}
      <div class="health-card-meta">${k.latest ? esc(k.latest.date) : esc(t('health.no_entries'))} · ${esc(t('health.in_range', { count: k.series.length }))}</div>
    </div>`;
}

function _fmtNum(v) { return (Math.round(v * 10) / 10).toString(); }

function _render() {
  const body = $('health-body');
  if (!body) return;
  const active = document.activeElement;
  const row = active?.closest('.health-row');
  const focus = body.contains(active) ? (active.id ? `#${CSS.escape(active.id)}`
    : row && active.dataset.act ? `.health-row[data-record-id="${CSS.escape(row.dataset.recordId)}"] [data-act="${CSS.escape(active.dataset.act)}"]`
      : active.dataset.days ? `[data-days="${CSS.escape(active.dataset.days)}"]` : null) : null;
  const selection = typeof active?.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
  body.innerHTML = `
    <div class="health-bar">
      <div class="health-ranges" role="radiogroup" aria-label="${esc(t('health.history_range'))}">${RANGES.map(([d, l]) => `<button type="button" role="radio" aria-checked="${_days === d}" class="health-chip${_days === d ? ' active' : ''}" data-days="${d}">${esc(t(l))}</button>`).join('')}</div>
      <div class="health-bar-actions">
        <button class="btn" id="health-import" title="${esc(t('health.import_title'))}" ${_importDraft ? 'disabled' : ''}>${esc(t('health.import'))}</button>
        <button class="btn primary" id="health-add-toggle">${_si('plus')} ${esc(t('health.entry'))}</button>
      </div>
    </div>
    ${_loadNotice()}
    ${_deleteErrors.size ? `<div class="specialist-group-note legacy-load-note" role="alert" id="health-write-error"><div>${[..._deleteErrors.values()].map(message => `<p>${esc(message)}</p>`).join('')}</div><button type="button" class="btn" id="health-refresh">${esc(t('health.refresh'))}</button></div>` : ''}
    ${_importDraft ? _importForm() : ''}
    ${_draft ? _addForm() : ''}
    ${_data.kinds.length ? `<div class="health-grid">${_data.kinds.map(_kindCard).join('')}</div>`
      : (_draft || _importDraft || !_hasOverview || _loadState.state !== 'resting' ? '' : `
        <div class="empty-state">
          <div class="empty-state-icon">${_si('heart')}</div>
          <div class="empty-state-title">${esc(t('health.empty_title'))}</div>
          <div class="empty-state-desc">${esc(t('health.empty_desc'))}</div>
          <button type="button" class="btn" id="health-empty-add">${_si('plus')} ${esc(t('health.log_first'))}</button>
        </div>`)}
    ${_entries.length ? `<div class="health-recent"><div class="health-recent-h">${esc(t('health.recent'))}</div>${_entries.slice(0, 30).map(_row).join('')}</div>` : ''}`;
  _wire(body);
  const restored = focus && body.querySelector(focus);
  if (restored && !restored.disabled && body.getClientRects().length) {
    restored.focus({ preventScroll: true });
    if (selection && restored.setSelectionRange) restored.setSelectionRange(...selection);
  }
}

function _focusIfUnclaimed(selector, navigation) {
  if (navigation === _navigation && document.activeElement === document.body && $('health-body')?.getClientRects().length) {
    document.querySelector(selector)?.focus({ preventScroll: true });
  }
}

function _row(e) {
  const label = e.label || kindLabel(e.kind);
  const busy = _deleting.has(e.record_id) || _saving;
  return `<div class="health-row" data-id="${e.id}" data-record-id="${esc(e.record_id)}" aria-busy="${busy}"><span class="health-row-date">${esc(e.date)}</span><span class="health-row-kind">${esc(label)}</span><span class="health-row-val">${esc(e.value)} ${esc(e.unit)}</span><span class="health-row-note">${esc(e.note)}</span><div class="health-row-actions"><button class="btn" data-act="edit" ${busy ? 'disabled' : ''} aria-label="${esc(t('health.edit_entry_from', { label, date: e.date }))}">${esc(t('common.edit'))}</button><button class="icon-btn danger" data-act="del" ${busy ? 'disabled' : ''} title="${esc(t('common.delete'))}" aria-label="${esc(t('health.delete_entry_from', { label, date: e.date }))}">${_si('trash')}</button></div></div>`;
}

function _importForm() {
  const draft = _importDraft;
  const pending = ['reading', 'saving'].includes(draft.phase);
  const status = draft.phase === 'reading' ? t('health.reading_file') : draft.phase === 'saving' ? t('health.importing')
    : draft.phase === 'done' ? (draft.result.replayed ? tp('health.already_imported', draft.result.imported)
      : tp('health.imported', draft.result.imported)) : '';
  return `<section class="health-add" id="health-import-form" aria-label="${esc(t('health.import_entries'))}" aria-busy="${pending}">
    <div class="health-form-title">${esc(draft.name)}</div>
    ${status ? `<p role="status">${esc(status)}</p>` : ''}
    ${draft.error ? `<p id="health-import-error" role="alert">${esc(draft.error)}</p>` : ''}
    <div class="health-form-actions">
      ${draft.phase === 'error' ? `<button type="button" class="btn primary" id="health-import-retry">${esc(t('health.retry_import'))}</button>` : ''}
      <button type="button" class="btn" id="health-import-close" ${draft.phase === 'saving' ? 'disabled' : ''}>${esc(draft.phase === 'done' ? t('common.done') : t('common.close'))}</button>
    </div>
  </section>`;
}

async function _runImport(draft) {
  if (_importDraft !== draft || draft.phase === 'saving') return;
  const navigation = _navigation;
  draft.error = '';
  try {
    if (draft.text == null) {
      draft.phase = 'reading'; _render();
      draft.text = await draft.file.text();
      if (_importDraft !== draft) return;
      draft.file = null;
    }
    draft.requestId ||= _newCreateRequestId();
    draft.defaultDate ||= calendarDateKey();
    draft.phase = 'saving'; _render();
    const previousUncertainty = draft.uncertain;
    draft.uncertain = true;
    let result;
    try {
      result = await api('/api/health/import', { method: 'POST', body: { text: draft.text, request_id: draft.requestId, strict: true, default_date: draft.defaultDate } });
    } catch (error) {
      if ([400, 422].includes(error.status)) draft.uncertain = previousUncertainty;
      throw error;
    }
    if (!Number.isInteger(result?.imported) || result.imported < 0 || result.skipped !== 0 || typeof result.replayed !== 'boolean') throw new Error(t('health.import_unconfirmed'));
    draft.result = result; draft.phase = 'done'; draft.uncertain = false; draft.text = null;
    await loadHealth();
  } catch (error) {
    if (_importDraft !== draft) return;
    draft.phase = 'error';
    const reason = error.status && error.status < 500 && typeof error.data?.detail === 'string' ? error.data.detail : t('health.import_unconfirmed_short');
    draft.error = t(draft.uncertain ? 'health.import_error_uncertain' : 'health.import_error_kept', { reason });
  } finally {
    if (_importDraft === draft) {
      _render();
      _focusIfUnclaimed(draft.phase === 'error' ? '#health-import-retry' : '#health-import-close', navigation);
    }
  }
}

function _chooseImport() {
  if (_importDraft) return;
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.csv,text/csv';
  inp.onchange = () => {
    const file = inp.files[0];
    if (!file || _importDraft) return;
    _importDraft = { file, name: file.name, text: null, phase: 'reading', error: '', uncertain: false };
    _runImport(_importDraft);
  };
  inp.click();
}

async function _closeImport() {
  const draft = _importDraft, navigation = _navigation;
  if (!draft || draft.phase === 'saving') return;
  if (draft.uncertain && !await dlgConfirm(t('health.close_import_confirm'))) return;
  if (_importDraft !== draft || draft.phase === 'saving' || navigation !== _navigation) return;
  _importDraft = null; _render();
  if (draft.uncertain) await loadHealth();
  _focusIfUnclaimed('#health-import', navigation);
}

async function _deleteEntry(entry) {
  if (!entry || _deleting.has(entry.record_id) || _saving) return;
  if (!entry.record_id) { _deleteErrors.set(`missing:${entry.id}`, t('health.refresh_before_delete')); _render(); return; }
  const navigation = _navigation;
  if (!await dlgConfirm(t('health.delete_confirm')) || navigation !== _navigation || _deleting.has(entry.record_id) || _saving) return;
  ++_loadGeneration;
  _deleting.add(entry.record_id); _render();
  let removed = false;
  try {
    await api(`/api/health/${entry.id}?record_id=${encodeURIComponent(entry.record_id)}`, { method: 'DELETE' });
    removed = true;
  } catch (error) {
    if ([404, 410].includes(error.status)) removed = true;
    else {
      const reading = `${entry.label || kindLabel(entry.kind)}, ${entry.date}`;
      const message = error.status === 409 ? t('health.delete_changed') : t('health.delete_unconfirmed');
      _deleteErrors.set(entry.record_id, t('health.delete_error', { reading, message }));
    }
  } finally {
    if (removed) {
      _deleteErrors.delete(entry.record_id);
      _entries = _entries.filter(item => item.record_id !== entry.record_id);
      if (_draft?.record_id === entry.record_id) { _draft = null; _formError = ''; }
    }
    _deleting.delete(entry.record_id);
    await loadHealth();
    _focusIfUnclaimed(_deleteErrors.size ? '#health-refresh' : '#health-add-toggle', navigation);
  }
}

function _addForm() {
  const editing = _draft.id != null;
  return `
    <form class="health-add" id="health-entry-form" aria-label="${esc(editing ? t('health.edit_health_entry') : t('health.new_health_entry'))}" aria-busy="${_saving}">
      <div class="health-form-title">${editing ? esc(t('health.edit_kind_entry', { label: _draft.label || kindLabel(_draft.kind) })) : esc(t('health.new_entry'))}</div>
      <fieldset ${_saving ? 'disabled' : ''}>
        ${editing ? '' : `<div class="health-field"><span id="health-kind-label">${esc(t('health.metric'))}</span><div class="settings-input custom-select" id="health-kind" aria-labelledby="health-kind-label" aria-disabled="${_saving}" data-value="${esc(_draft.kind)}" data-options="${esc(['weight', 'sleep', 'workout', 'med', 'custom'].map(kind => `${kind}|${kindLabel(kind)}`).join(';'))}"></div></div>`}
        <div class="health-add-row">
          <label class="health-field" for="health-value">${esc(t('health.value'))}<input type="text" class="settings-input" id="health-value" value="${esc(_draft.value)}" inputmode="decimal" aria-describedby="health-entry-error"></label>
          <label class="health-field" for="health-unit">${esc(t('health.unit'))}<input type="text" class="settings-input" id="health-unit" value="${esc(_draft.unit)}"></label>
        </div>
        <label class="health-field" for="health-date">${esc(t('health.date'))}<input type="text" class="settings-input" id="health-date" value="${esc(_draft.date)}" placeholder="${esc(editing ? t('tasks.date_placeholder') : t('health.date_placeholder_today'))}" aria-describedby="health-date-help health-entry-error"></label>
        <p id="health-date-help" class="muted" role="status"></p>
        ${!editing && _draft.kind === 'custom' ? `<label class="health-field" for="health-label">${esc(t('health.metric_name'))}<input type="text" class="settings-input" id="health-label" value="${esc(_draft.label)}"></label>` : ''}
        <label class="health-field" for="health-note">${esc(t('health.note_optional'))}<input type="text" class="settings-input" id="health-note" value="${esc(_draft.note)}"></label>
        <div class="health-form-actions">
          <button type="submit" class="btn primary" id="health-create" ${_draft.openingSaved ? 'disabled' : ''}>${esc(_saving ? t('common.saving') : editing ? t('common.save') : t('common.add'))}</button>
          <button type="button" class="btn" id="health-cancel">${esc(t('common.cancel'))}</button>
        </div>
      </fieldset>
      <p id="health-entry-error" role="alert" ${_formError ? '' : 'hidden'}>${esc(_formError)}</p>
      ${_conflictId != null ? `<button type="button" class="btn" id="health-open-saved" ${_saving || _draft.openingSaved ? 'disabled' : ''}>${esc(_draft.openingSaved ? t('health.opening_saved') : t('health.open_saved'))}</button>` : ''}
    </form>`;
}

function _validDate(date, editing) {
  return (!date && !editing) || (/^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(date)) && new Date(date).toISOString().slice(0, 10) === date);
}

function _dateGuidance(force = false) {
  const input = $('health-date');
  const help = $('health-date-help');
  if (!input || !help || !_draft) return;
  const date = input.value.trim();
  const editing = _draft.id != null;
  const invalid = (force || date.length >= 10) && !_validDate(date, editing);
  input.setAttribute('aria-invalid', String(invalid));
  help.textContent = invalid ? t('health.date_invalid')
    : editing ? t('health.date_help_edit') : t('health.date_help_new');
}

async function _openEntry(entry = null) {
  if (_saving) return;
  const previousDraft = _draft;
  if (_draft && !await dlgConfirm(_createUncertain ? t('health.discard_uncertain') : t('health.discard_unsaved'))) return;
  if (_draft !== previousDraft || _saving) return;
  _returnFocus = entry ? `.health-row[data-record-id="${CSS.escape(entry.record_id || '')}"] [data-act="edit"]` : '#health-add-toggle';
  _draft = entry ? { ...entry, value: String(entry.value) } : { kind: 'weight', value: '', unit: 'kg', date: '', label: '', note: '' };
  _formError = '';
  _createUncertain = false; _conflictId = null;
  _render();
  $('health-value')?.focus();
}

async function _closeEntry() {
  if (_saving) return;
  if (_createUncertain && !await dlgConfirm(t('health.close_uncertain'))) return;
  const refresh = _createUncertain;
  _draft = null;
  _formError = ''; _createUncertain = false; _conflictId = null;
  _render();
  if (refresh) await loadHealth();
  document.querySelector(_returnFocus)?.focus();
}

function _wire(body) {
  wireChoiceGroup(body.querySelector('.health-ranges'));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => loadHealth());
  body.querySelectorAll('.health-chip').forEach(c => c.addEventListener('click', () => { _days = +c.dataset.days; loadHealth(); }));
  $('health-add-toggle')?.addEventListener('click', () => _openEntry());
  $('health-empty-add')?.addEventListener('click', () => _openEntry());
  $('health-import')?.addEventListener('click', _chooseImport);
  $('health-import-retry')?.addEventListener('click', () => _runImport(_importDraft));
  $('health-import-close')?.addEventListener('click', _closeImport);
  $('health-refresh')?.addEventListener('click', async () => {
    const navigation = _navigation;
    await loadHealth(_fetcher, { clearWriteError: true });
    _focusIfUnclaimed('#health-add-toggle', navigation);
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
    $('health-date')?.addEventListener('input', () => _dateGuidance());
    $('health-date')?.addEventListener('blur', () => _dateGuidance(true));
    _dateGuidance(Boolean(_formError));
    $('health-entry-form')?.addEventListener('submit', event => { event.preventDefault(); _create(); });
    $('health-cancel')?.addEventListener('click', _closeEntry);
    $('health-open-saved')?.addEventListener('click', async () => {
      if (_saving || !_draft?.request_id || _draft.openingSaved) return;
      const draft = _draft;
      draft.openingSaved = true;
      _render();
      try {
        const response = await fetch(`/api/health/requests/${encodeURIComponent(draft.request_id)}`);
        const entry = await response.json().catch(() => ({}));
        if (_draft !== draft) return;
        if (!response.ok) {
          if ([404, 410].includes(response.status)) _conflictId = null;
          const reason = typeof entry.detail === 'string' ? entry.detail : t('health.open_failed');
          throw new Error(t('health.reason_input_kept', { reason }));
        }
        if (!$('health-body')?.getClientRects().length) return;
        await _openEntry({ ...entry, create_request_id: draft.request_id });
      } catch (error) {
        if (_draft === draft) _formError = error.message || t('health.open_failed_retry');
      } finally {
        draft.openingSaved = false;
        if (_draft === draft) {
          _render();
          ($('health-open-saved') || $('health-create'))?.focus();
        }
      }
    });
  }

  body.querySelectorAll('.health-card[data-kind] [data-act="set-target"]').forEach(btn => btn.addEventListener('click', async () => {
    const kind = btn.closest('.health-card').dataset.kind;
    const cur = (_data.kinds.find(k => k.kind === kind) || {}).target;
    const v = await dlgPrompt('', String(cur ?? ''), {
      title: t('health.target_title', { kind: t(`health.kind_${kind}_word`) }), label: t('health.target'), hint: t('health.target_hint'), confirmLabel: t('health.save_target'),
      validate: raw => {
        const text = raw.trim();
        const value = Number(text);
        return !DECIMAL.test(text) || !Number.isFinite(value) || value < 0
          ? t('health.target_invalid')
          : '';
      },
    });
    if (v == null) return;
    try {
      const response = await fetch('/api/health/target', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kind, value: Number(v.trim()) }) });
      if (!response.ok) throw new Error(t('health.save_failed_status', { status: response.status }));
      await loadHealth();
    } catch {
      toast(t('health.target_save_failed'), 'error');
    }
  }));

  body.querySelectorAll('.health-row[data-id]').forEach(row => {
    row.querySelector('[data-act="edit"]')?.addEventListener('click', () => {
      const entry = _entries.find(item => item.record_id === row.dataset.recordId);
      if (entry) _openEntry(entry);
    });
    row.querySelector('[data-act="del"]')?.addEventListener('click', () => _deleteEntry(_entries.find(item => item.record_id === row.dataset.recordId)));
  });
}

async function _create() {
  if (!_draft || _saving || _draft.openingSaved) return;
  const navigation = _navigation;
  const raw = _draft.value.trim();
  const value = Number(raw);
  const date = _draft.date.trim();
  const validDate = _validDate(date, _draft.id != null);
  _formError = !DECIMAL.test(raw) || !Number.isFinite(value) ? t('health.err_number') : !validDate ? t('health.err_date') : '';
  if (_formError) {
    _render();
    $(validDate ? 'health-value' : 'health-date')?.focus();
    return;
  }
  const editing = _draft.id != null;
  if (editing && !_draft.record_id) { _formError = t('health.err_reopen'); _render(); return; }
  const payload = { value, unit: _draft.unit.trim(), note: _draft.note.trim() };
  if (editing) payload.record_id = _draft.record_id;
  if (date) payload.date = date;
  else if (!editing) payload.date = _draft.date = calendarDateKey();
  if (editing && _draft.create_request_id) payload.create_request_id = _draft.create_request_id;
  if (!editing) Object.assign(payload, { kind: _draft.kind, label: _draft.kind === 'custom' ? _draft.label.trim() : '' });
  const earlierUncertainty = _createUncertain;
  _saving = true;
  _render();
  try {
    if (!editing) {
      payload.request_id = _draft.request_id ||= _newCreateRequestId();
      _createUncertain = true;
    }
    const r = await fetch(editing ? `/api/health/${_draft.id}` : '/api/health', {
      method: editing ? 'PATCH' : 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const detail = (await r.json().catch(() => ({}))).detail;
      if (!editing && [400, 422].includes(r.status)) _createUncertain = earlierUncertainty;
      if (!editing && r.status === 409 && Number.isInteger(detail?.entry_id)) _conflictId = detail.entry_id;
      if (r.status === 410) _conflictId = null;
      const reason = typeof detail === 'string' ? detail : detail?.message;
      throw new Error(r.status < 500 && reason ? t('health.reason_input_kept', { reason }) : t('health.save_failed_retry', { status: r.status }));
    }
    _draft = null;
    _createUncertain = false; _conflictId = null;
    toast(editing ? t('health.entry_updated') : t('health.logged'), 'success');
    await loadHealth();
    _focusIfUnclaimed(_returnFocus, navigation);
  } catch (error) {
    _formError = error.message || t('health.save_failed_kept');
  } finally {
    _saving = false;
    _render();
    _focusIfUnclaimed(_draft ? '#health-create' : _returnFocus, navigation);
  }
}
