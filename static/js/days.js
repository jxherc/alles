// days — countdowns to what's ahead, day counts since what's behind.
// the server resolves each event's target date (and repeat rollover); the
// count/mode are recomputed here against the *viewer's* local midnight, so the
// numbers are never off by the server's timezone.
import { plainError, toast } from './util.js';
import { initCustomDropdown } from './dropdown.js?v=213';
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
import { initDatePicker } from './datepick.js';
import { confirm as dlgConfirm } from './dialog.js';
import { formatDate, formatNumber, ordinalCategory, t, tp } from './i18n.js';

const $ = id => document.getElementById(id);
let _events = [];
let _editing = null;
let _midnightTimer = null;
let _lastRenderDay = '';
let _loadSequence = 0;
let _loadError = '';
let _adding = false;
const _pending = new Set();
const _editFields = ['name', 'date', 'repeat', 'category', 'notes', 'notify_days'];

export async function loadDays(fetcher = fetch) {
  const sequence = ++_loadSequence;
  try {
    const data = await dayJson(fetcher, '/api/days', undefined, value => Array.isArray(value?.events)
      && value.events.every(item => item && typeof item.id === 'string' && typeof item.name === 'string'
        && typeof item.date === 'string' && typeof item.target === 'string'
        && Number.isFinite(new Date(item.target + 'T00:00:00').getTime())));
    if (sequence !== _loadSequence) return;
    _events = data.events;
    _loadError = '';
  } catch (error) {
    if (sequence !== _loadSequence) return;
    _loadError = plainError(error.message || t('common.try_again'));
  }
  _render();
}

async function dayJson(request, path, options, valid) {
  const response = await request(path, options);
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof value?.detail === 'string' ? value.detail : t('common.action_failed_retry'));
  if (!valid(value)) throw new Error(t('common.response_unconfirmed'));
  return value;
}

export function initDaysPanel(fetcher = fetch) {
  const loading = loadDays(fetcher);
  initCustomDropdown($('day-repeat'));
  initDatePicker($('day-date'));
  _armMidnightRefresh();
  if (!$('day-add-btn') || $('day-add-btn').dataset.wired) return loading;
  $('day-add-btn').dataset.wired = '1';
  $('day-add-btn').addEventListener('click', _add);
  $('day-name')?.addEventListener('keydown', e => { if (e.key === 'Enter') _add(); });
  // an open tab shouldn't go stale across midnight / while backgrounded
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && _lastRenderDay !== _todayLocal().toDateString()) loadDays();
  });
  return loading;
}

async function _add() {
  if (_adding) return;
  const originalName = $('day-name')?.value;
  const originalCategory = $('day-category')?.value;
  const name = $('day-name')?.value.trim();
  const dt = $('day-date')?.value;
  if (!name) { toast(t('plan.days_what_counting'), 'error'); return; }
  if (!dt) { toast(t('plan.days_pick_date'), 'error'); return; }
  const button = $('day-add-btn');
  _adding = true; button.disabled = true; button.setAttribute('aria-busy', 'true');
  try {
    await dayJson(fetch, '/api/days', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, date: dt.slice(0, 10), repeat: $('day-repeat')?.dataset.value || 'none', category: originalCategory?.trim() || '' }),
    }, value => typeof value?.id === 'string' && value.name === name && value.date === dt.slice(0, 10));
    ++_loadSequence;
    for (const [id, original] of [['day-name', originalName], ['day-category', originalCategory]]) {
      if ($(id)?.value === original) $(id).value = '';
    }
    toast(t('plan.days_counting', { name }), 'success');
    await loadDays();
  } catch (error) { toast(error.message || t('plan.days_unconfirmed'), 'error'); }
  finally { _adding = false; button.disabled = false; button.removeAttribute('aria-busy'); }
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
  if (y) p.push(tp('plan.days_n_years', y));
  if (m) p.push(tp('plan.days_n_months', m));
  if (d || !p.length) p.push(tp('plan.days_n_days', d));
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
function _nth(n) {
  return t(`plan.days_ordinal_${ordinalCategory(n)}`, { n });
}

function _unitLabel(e) {
  if (e.mode === 'today') return e.repeat !== 'none' && e.nth > 1 ? t('plan.days_nth_today', { nth: _nth(e.nth) }) : t('plan.days_today_bang');
  if (e.mode === 'since') return tp('plan.days_since', e.count);
  return tp('plan.days_left', e.count);
}

function _fmtDate(e) {
  const d = new Date(e.target + 'T00:00:00');
  const near = e.mode !== 'since' && e.days <= 7;   // weekday helps when it's close
  const opts = near ? { weekday: 'short', month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return formatDate(d, opts).toLowerCase();
}

function _metaLine(e) {
  const bits = [_fmtDate(e)];
  if (e.repeat === 'yearly') bits.push(`${_si('refresh')} ${t('plan.days_yearly')}${e.nth > 0 ? ` · ${_nth(e.nth)}` : ''}`);
  if (e.repeat === 'monthly') bits.push(`${_si('refresh')} ${t('plan.days_monthly')}${e.nth > 0 ? ` · ${_nth(e.nth)}` : ''}`);
  if (e.category) bits.push(esc(e.category));
  return bits.join(' · ');
}

// ── render ──────────────────────────────────────────────────────────────────
function _render() {
  _lastRenderDay = _todayLocal().toDateString();
  const grid = $('days-grid');
  if (!grid) return;
  const editor = grid.querySelector('.day-card.editing');
  const draft = editor?.dataset.id === _editing
    ? Object.fromEntries(_editFields.map(field => [field, editor.querySelector(`[data-f="${field}"]`)?.value])) : null;
  const failure = _loadError ? `<div class="page-empty" role="alert">${esc(t('plan.days_load_failed', { reason: _loadError }))} <button class="btn" id="days-retry">${esc(t('common.retry'))}</button></div>` : '';

  const derived = _events.map(e => _derive(e));  // not map(_derive) — that leaks the index in as `today`
  const sum = $('days-summary');
  if (sum) {
    const c = m => derived.filter(x => x.mode === m).length;
    const bits = [];
    if (c('today')) bits.push(t('plan.days_n_today', { count: c('today') }));
    if (c('countdown')) bits.push(t('plan.days_n_upcoming', { count: c('countdown') }));
    if (c('since')) bits.push(t('plan.days_n_counting_up', { count: c('since') }));
    sum.textContent = bits.join(' · ');
  }

  if (!derived.length) {
    grid.innerHTML = failure || `<div class="days-empty" style="padding:1rem 0;font-size:0.75rem;color:var(--muted)">${esc(t('plan.days_empty'))}</div>`;
    _wire(grid);
    return;
  }

  // editing renders the card in place (its own section), not yanked to the top
  const cardOf = e => e.id === _editing ? _editCard(e) : _card(e);
  const sections = [
    ['today', t('common.today'),     derived.filter(x => x.mode === 'today').sort(_byPinThenName)],
    ['upcoming', t('plan.days_upcoming'),  derived.filter(x => x.mode === 'countdown').sort(_byPinThenSoonest)],
    ['counting up', t('plan.days_counting_up'), derived.filter(x => x.mode === 'since').sort((a, b) => a.count - b.count)],
  ];
  grid.innerHTML = failure + sections
    .filter(([,, list]) => list.length)
    .map(([, label, list]) => `<div class="day-section">${esc(label)}</div>` + list.map(cardOf).join(''))
    .join('');
  _wire(grid);
  if (draft) for (const [field, value] of Object.entries(draft)) {
    const input = grid.querySelector(`.day-card.editing[data-id="${CSS.escape(_editing)}"] [data-f="${field}"]`);
    if (input && value !== undefined) input.value = value;
  }
}

function _byPinThenName(a, b) {
  return (b.pinned - a.pinned) || a.name.localeCompare(b.name);
}
function _byPinThenSoonest(a, b) {
  return (b.pinned - a.pinned) || (a.days - b.days);
}

function _card(e) {
  const tip = e.breakdown ? `${esc(e.breakdown)}${e.notes ? ': ' + esc(e.notes) : ''}` : esc(e.notes || '');
  return `
    <div class="day-card${e.mode === 'today' ? ' today' : ''}${e.mode === 'since' ? ' since' : ''}${e.days >= 1 && e.days <= 3 ? ' soon' : ''}" data-id="${e.id}"${tip ? ` title="${tip}"` : ''}>
      <button class="day-pin${e.pinned ? ' on' : ''}" data-act="pin" title="${esc(e.pinned ? t('plan.days_unpin') : t('plan.days_pin'))}">${_si(e.pinned ? 'star-fill' : 'star')}</button>
      <div class="day-num">${e.mode === 'today' ? _si('party') : formatNumber(e.count)}</div>
      <div class="day-unit">${_unitLabel(e)}</div>
      <div class="day-name">${esc(e.name)}</div>
      <div class="day-meta">${_metaLine(e)}</div>
      ${e.progress != null && e.mode !== 'today' ? `<div class="day-bar"><i style="width:${Math.round(e.progress * 100)}%"></i></div>` : ''}
      <div class="day-actions">
        <button class="btn" data-act="edit">${esc(t('common.edit'))}</button>
        <button class="btn danger" data-act="del" aria-label="${esc(t('common.delete'))}" title="${esc(t('common.delete'))}">×</button>
      </div>
    </div>`;
}

// the reminder as words: "-1 = off" lived only in a tooltip, and typing -1 came back as 1
const _remind = () => [[-1, t('plan.days_no_reminder')], [0, t('plan.days_remind_day')], [1, tp('plan.days_remind_days', 1)], [3, tp('plan.days_remind_days', 3)],
  [7, t('plan.days_remind_week')], [14, t('plan.days_remind_2weeks')], [30, t('plan.days_remind_month')]];
function _remindOptions(current) {
  const REMIND = _remind();
  const rows = REMIND.some(([days]) => days === current) || !Number.isInteger(current) ? REMIND
    : [...REMIND, [current, tp('plan.days_remind_days', current)]].sort((a, b) => a[0] - b[0]);
  return rows.map(([days, label]) => `${days}|${label}`).join(';');
}

function _editCard(e) {
  return `
    <div class="day-card editing" data-id="${e.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(e.name)}" placeholder="${esc(t('plan.days_name'))}">
      <div class="date-input" data-f="date" data-type="date" data-value="${esc(e.date)}" data-ph="${esc(t('plan.days_date'))}"></div>
      <div class="settings-input custom-select" data-f="repeat" data-value="${esc(e.repeat || 'none')}" data-options="${esc(`none|${t('plan.days_one_time')};yearly|${t('plan.days_every_year')};monthly|${t('plan.days_every_month')}`)}"></div>
      <input type="text" class="settings-input" data-f="category" value="${esc(e.category)}" placeholder="${esc(t('plan.days_category'))}">
      <div class="settings-input custom-select" data-f="notify_days" aria-label="${esc(t('plan.days_reminder'))}" data-value="${esc(String(e.notify_days ?? -1))}" data-options="${esc(_remindOptions(e.notify_days))}"></div>
      <input type="text" class="settings-input" data-f="notes" value="${esc(e.notes)}" placeholder="${esc(t('plan.days_notes'))}">
      <div class="day-actions">
        <button class="btn primary" data-act="save">${esc(t('common.save'))}</button>
        <button class="btn" data-act="cancel">${esc(t('common.cancel'))}</button>
      </div>
    </div>`;
}

// every action redraws the grid, so focus goes back to the same control in the card; an edit
// lands on the name field, save/cancel on the card's edit, a delete on the next card's edit
function _refocus(grid, id, act, nextId = '') {
  const card = grid?.querySelector(`.day-card[data-id="${CSS.escape(id)}"]`);
  const target = act === 'name' ? card?.querySelector('[data-f="name"]')
    : act === 'del' ? grid?.querySelector(`.day-card[data-id="${CSS.escape(nextId)}"] [data-act="edit"]`)
    : card?.querySelector(`[data-act="${act}"]`) || card?.querySelector('[data-act="edit"]');
  (target || $('day-add-btn'))?.focus();
}

function _wire(grid) {
  $('days-retry')?.addEventListener('click', async () => {
    $('days-retry').disabled = true;
    await loadDays();
    if (document.activeElement === document.body) ($('days-retry') || $('day-add-btn'))?.focus();
  });
  grid.querySelectorAll('.day-card.editing .custom-select').forEach(initCustomDropdown);
  grid.querySelectorAll('.day-card.editing .date-input').forEach(initDatePicker);
  grid.querySelectorAll('.day-card').forEach(card => {
    const id = card.dataset.id;
    const busy = value => card.querySelectorAll('[data-act]').forEach(button => {
      if (!['edit', 'cancel'].includes(button.dataset.act)) button.disabled = value;
    });
    busy(_pending.has(id));
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'edit') { _editing = id; _render(); _refocus(grid, id, 'name'); return; }
      if (act === 'cancel') { _editing = null; _render(); _refocus(grid, id, 'edit'); return; }
      if (_pending.has(id)) return;
      const cards = [...grid.querySelectorAll('.day-card[data-id]')], at = cards.indexOf(card);
      const nextId = (cards[at + 1] || cards[at - 1])?.dataset.id || '';
      // ask before going busy: a disabled button can't take focus back when the dialog closes
      if (act === 'del' && !await dlgConfirm((name => name ? t('plan.days_stop_counting', { name }) : t('plan.days_stop_counting_this'))(_events.find(x => x.id === id)?.name))) {
        if (btn.isConnected) btn.focus();
        return;
      }
      if (_pending.has(id)) return;
      _pending.add(id); busy(true);
      let landed = '';
      try {
        if (act === 'pin') {
          const e = _events.find(x => x.id === id);
          await dayJson(fetch, `/api/days/${id}`, {
            method: 'PATCH', headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ pinned: !e.pinned }),
          }, value => value?.id === id && value.pinned === !e.pinned);
          ++_loadSequence;
          landed = 'pin';
          await loadDays(); return;
        }
        if (act === 'del') {
          await dayJson(fetch, `/api/days/${id}`, { method: 'DELETE' }, value => value?.ok === true);
          ++_loadSequence;
          _events = _events.filter(item => item.id !== id);
          landed = 'del';
          await loadDays(); return;
        }
        if (act === 'save') {
          const v = f => card.querySelector(`[data-f="${f}"]`)?.value;
          const submitted = Object.fromEntries(_editFields.map(field => [field, v(field)]));
          await dayJson(fetch, `/api/days/${id}`, {
            method: 'PATCH', headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              name: v('name')?.trim(), date: v('date'), repeat: v('repeat'),
              category: v('category')?.trim() || '', notes: v('notes') || '',
              notify_days: Number.isNaN(parseInt(v('notify_days'), 10)) ? undefined : parseInt(v('notify_days'), 10),
            }),
          }, value => value?.id === id && value.name === submitted.name?.trim() && value.date === submitted.date);
          ++_loadSequence;
          if (_editing === id && card.isConnected && _editFields.every(field => v(field) === submitted[field])) _editing = null;
          toast(t('common.saved'), 'success');
          landed = 'edit';
          await loadDays(); return;
        }
      } catch (error) { toast(error.message || t('plan.days_change_unconfirmed'), 'error'); }
      finally {
        _pending.delete(id); busy(false);
        const current = grid.querySelector(`.day-card[data-id="${CSS.escape(id)}"]`);
        current?.querySelectorAll('[data-act]').forEach(button => { button.disabled = false; });
        // only when focus was lost to the redraw or the disabled button, never stolen from elsewhere
        const lost = !document.activeElement || document.activeElement === document.body || !document.activeElement.isConnected;
        if (lost || btn === document.activeElement) {
          if (landed === 'del') _refocus(grid, id, 'del', nextId);
          else if (landed) _refocus(grid, id, landed === 'edit' && _editing === id ? 'save' : landed);
          // a change that failed leaves the card as it was; back to the button that was pressed
          else if (btn.isConnected) btn.focus();
          else _refocus(grid, id, act === 'del' ? 'edit' : act);
        }
      }
    }));
  });
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
