// habits — a dedicated habit grid (journal has streaks, but no habit tracker). tap a
// day to mark it done; each habit shows its streak, this-week progress, and a
// GitHub-style contribution heatmap. mirrors the days/watch panel conventions.
import { api, toast } from './util.js';
import { initCustomDropdown } from './dropdown.js?v=215';
import { confirm as dlgConfirm, pick } from './dialog.js';
import { calendarDateKey, formatCalendarDate, t, tp } from './i18n.js';
import { categoryHue } from './color.js';
import { closeEmojiPicker, emojiFieldHtml, wireEmojiPicker } from './emoji_picker.js';
import { catalogEntry, catalogName, catalogOptions } from './habit_catalog.js';
import { hasLogger, logSummary, openLogger } from './habit_loggers.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _habits = [];
let _editing = null;
let _adding = false;

let _inited = false;
let _hasLoaded = false;
let _loading = false;
let _loadError = '';
let _generation = 0;
let _saving = false;
let _draft = null;
let _creation = null;
let _showArchived = false;
let _navigation = 0;
let _day = calendarDateKey();

function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function initHabits(fetcher = fetch) {
  ++_navigation;
  // A fresh navigation (including a Home record link) opens active habits.
  if (_showArchived) { _showArchived = false; _habits = []; _hasLoaded = false; }
  if (!_inited) {
    _inited = true;
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && !_saving && $('habits-body')?.offsetParent) loadHabits();
    });
  }
  return loadHabits(fetcher);
}

export async function loadHabits(fetcher = fetch) {
  const generation = ++_generation;
  const day = calendarDateKey();
  _loading = true; _loadError = ''; _render();
  try {
    const data = await api('/api/habits/overview?date_q=' + day + (_showArchived ? '&archived=true' : ''), {}, fetcher);
    if (!Array.isArray(data.habits)) throw new Error('invalid habit response');
    if (generation !== _generation) return false;
    _habits = data.habits; _hasLoaded = true; _day = day;
  } catch {
    if (generation !== _generation) return false;
    _loadError = t(_hasLoaded ? 'habits.load_failed_shown' : 'habits.load_failed_retry');
  } finally {
    if (generation === _generation) { _loading = false; _render(); }
  }
  return !_loadError;
}

function setBusy() {
  const body = $('habits-body');
  body?.setAttribute('aria-busy', String(_saving || _loading));
  body?.querySelectorAll('button, input, .custom-select').forEach(el => {
    el.disabled = _saving || (el.dataset.act === 'create' && !!_creation?.deleted);
  });
}

async function writeHabit(change) {
  if (_saving) return;
  const navigation = _navigation;
  const focus = document.activeElement;
  const cardId = focus?.closest('.habit-card')?.dataset.id;
  const day = focus?.dataset.toggle;
  const action = focus?.dataset.act;
  const interruptedLoad = _loading;
  const generation = ++_generation;
  _saving = true; _loading = false; setBusy();
  let resultFocus;
  try { resultFocus = await change(); }
  catch (error) {
    toast(error.message === 'Failed to fetch' ? t('habits.save_offline') : (error.message || t('habits.save_failed')), 'error');
    if (interruptedLoad && generation === _generation) {
      _loadError = t('habits.not_refreshed');
      _render();
    }
  }
  finally {
    _saving = false; setBusy();
    if (navigation === _navigation && $('habits-body')?.offsetParent
      && (document.activeElement === focus || document.activeElement === document.body)) {
      const card = cardId ? $('habits-body').querySelector(`[data-id="${CSS.escape(cardId)}"]`) : null;
      const target = focus?.isConnected && !focus.disabled ? focus : (day ? card?.querySelector(`[data-toggle="${CSS.escape(day)}"]`) : card?.querySelector('[data-act="edit"], [data-act="restore"]'));
      const draftAction = action && _adding ? $('habits-body').querySelector(`.habit-add [data-act="${CSS.escape(action)}"]:not(:disabled)`) : null;
      ((resultFocus?.isConnected ? resultFocus : null) || target || draftAction || $('habits-body').querySelector('.habit-card.editing [data-f="name"]') || $('habits-add-toggle') || $('habits-body').querySelector('[data-act="archive-view"]'))?.focus();
    }
  }
}

function readForm(card) {
  const value = field => card.querySelector(`[data-f="${field}"]`);
  return { id: card.dataset.id || null, name: value('name')?.value || '', icon: value('icon')?.dataset.value || '',
    cadence: value('cadence')?.dataset.value || 'daily', target: value('target')?.value ?? '3', color: value('color')?.dataset.value || '',
    kind: card.dataset.kind || 'check', unit: card.dataset.unit || '' };
}

function formPayload(card) {
  const values = readForm(card), target = parseInt(values.target, 10);
  if (!values.name.trim()) throw new Error(t('habits.name_it'));
  // one whole emoji: a 2-character cap cut flags and family emoji in half
  const icon = typeof Intl.Segmenter === 'function'
    ? ([...new Intl.Segmenter().segment(values.icon.trim())][0]?.segment || '') : values.icon.trim();
  const payload = { name: values.name.trim(), icon, cadence: values.cadence,
    color: values.color, target: Number.isNaN(target) ? 3 : target };
  // the type is chosen once, when the habit is made
  return card.dataset.add ? { ...payload, kind: values.kind, unit: values.unit } : payload;
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function upsertHabit(saved) {
  _habits = _habits.filter(h => h.id !== saved.id);
  if (saved.archived === _showArchived) _habits.push(saved);
}

async function closeAdd() {
  if (_saving) return false;
  const navigation = _navigation;
  if (_creation?.uncertain && !await dlgConfirm(t('habits.close_draft_confirm'))) return false;
  if (navigation !== _navigation) return false;
  const refresh = _creation?.uncertain;
  _adding = false; _creation = null; _draft = null;
  if (refresh) {
    // The caller may change views next; do not let a newer form open in between.
    _saving = true; setBusy();
    try { await loadHabits(); }
    finally { _saving = false; setBusy(); }
  }
  return navigation === _navigation;
}

function _localDays(n) {
  const out = [];
  const [year, month, day] = _day.split('-').map(Number);
  const t = new Date(year, month - 1, day);
  for (let i = n - 1; i >= 0; i--) { const d = new Date(t); d.setDate(t.getDate() - i); out.push(d); }
  return out;
}
const _iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function _render() {
  const body = $('habits-body');
  if (!body) return;
  closeEmojiPicker({ restore: false });
  const active = body.contains(document.activeElement) ? document.activeElement : null;
  const field = (active?.closest('[data-f]') ?? active)?.dataset.f;
  const toolbarFocus = active?.closest('.habits-bar') ? (active.id ? `#${CSS.escape(active.id)}` : `[data-act="${CSS.escape(active.dataset.act)}"]`) : null;
  const focusedRecord = active?.matches('.habit-card.record-target') ? active.dataset.id : null;
  const selection = typeof active?.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
  const cards = _habits.map(h => h.id === _editing ? _editCard(h) : _card(h)).join('');
  body.innerHTML = `
    <div class="habits-bar">
      <div class="habits-summary">${_habits.length ? esc(tp(_showArchived ? 'habits.archived_count' : 'habits.count', _habits.length)) : ''}</div>
      <div class="habit-actions">
        <button class="btn" data-act="archive-view" aria-pressed="${_showArchived}">${esc(_showArchived ? t('habits.active_habits') : t('habits.archived_habits'))}</button>
        ${_showArchived ? '' : `<button class="btn primary" id="habits-add-toggle">${_si('plus')} ${esc(t('habits.habit'))}</button>`}
      </div>
    </div>
    ${_loading ? `<div class="specialist-group-note" role="status">${esc(t('habits.loading'))}</div>` : ''}
    ${_loadError ? `<div class="specialist-group-note legacy-load-note habit-load-error" role="alert"><span>${esc(_loadError)}</span><button type="button" class="btn" data-act="retry-load">${esc(t('common.retry'))}</button></div>` : ''}
    ${_adding ? _addForm() : ''}
    ${_habits.length ? `<div class="habits-list">${cards}</div>` : (_adding || !_hasLoaded || _loading ? '' : `<div class="habits-empty">${esc(_showArchived ? t('habits.empty_archived') : t('habits.empty'))}</div>`)}`;
  _wire(body);
  setBusy();
  if (field) {
    const found = body.querySelector(`.habit-card.editing [data-f="${CSS.escape(field)}"]`);
    const input = found?.matches('.habit-icon-pick') ? found.querySelector('button') : found;
    input?.focus();
    if (selection && input?.setSelectionRange) input.setSelectionRange(...selection);
  } else if (focusedRecord) {
    const card = body.querySelector(`.habit-card[data-id="${CSS.escape(focusedRecord)}"]`);
    if (card) {
      card.classList.add('record-target'); card.tabIndex = -1;
      card.focus({ preventScroll: true });
    }
  } else if (toolbarFocus) {
    body.querySelector(`${toolbarFocus}:not(:disabled)`)?.focus({ preventScroll: true });
  }
}

function _heat(grid) {
  // grid is oldest→newest; render as 7-row columns (weeks)
  return `<div class="habit-heat">${grid.map(g =>
    `<i class="${g.done ? 'on' : ''}" title="${g.date}"></i>`).join('')}</div>`;
}

function _weekStrip(h) {
  const done = new Set(h.grid.filter(g => g.done).map(g => g.date));
  return `<div class="habit-week">${_localDays(7).map(d => {
    const iso = _iso(d);
    const completed = done.has(iso);
    const date = formatCalendarDate(iso, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    const letter = formatCalendarDate(iso, { weekday: 'narrow' });
    return `<button type="button" class="habit-day${completed ? ' done' : ''}" data-toggle="${iso}" title="${iso}" aria-pressed="${completed}"${hasLogger(h) ? ' aria-haspopup="dialog"' : ''} aria-label="${esc(t(completed ? 'habits.day_completed' : 'habits.day_not_completed', { name: h.name, date }))}"><span>${esc(letter)}</span><b>${d.getDate()}</b><span class="habit-day-state" aria-hidden="true">${completed ? _si('check') : ''}</span></button>`;
  }).join('')}</div>`;
}

function _card(h) {
  // a habit without a picked color still gets its own steady hue
  // only a real hex goes into style="…"; anything else falls back to the name's colour
  const accent = /^#[0-9a-f]{3,8}$/i.test(String(h.color || '')) ? h.color : `var(--cat-${categoryHue(h.name)})`;
  const slip = !h.archived && h.risk && h.risk.slipping
    ? `<span class="habit-slip" title="${esc(h.risk.reason)}">${esc(t('habits.slipping'))}</span>` : '';
  const today = h.archived ? '' : logSummary(h, h.logs?.[_day]);
  return `
    <div class="habit-card${slip ? ' at-risk' : ''}" data-id="${h.id}" style="--habit-accent:${esc(accent)}">
      <div class="habit-top">
        ${h.icon ? `<span class="habit-icon">${esc(h.icon)}</span>` : ''}
        <div class="habit-name">${esc(h.name)}</div>
        ${slip}
        <span class="habit-streak${h.streak > 0 ? ' on' : ''}" title="${esc(t('habits.current_streak'))}">${h.streak}${_si('fire')}</span>
        <div class="habit-actions">
          ${h.archived ? `<button class="btn" data-act="restore">${esc(t('habits.restore'))}</button>` : `<button class="icon-btn" data-act="edit" title="${esc(t('common.edit'))}">${_si('edit')}</button>`}
          <button class="icon-btn danger" data-act="del" title="${esc(t('common.delete'))}">${_si('trash')}</button>
        </div>
      </div>
      ${today ? `<div class="habit-log-sum">${esc(today)}</div>` : ''}
      ${h.archived ? `<div class="habit-meta">${esc(t('habits.archived_kept'))}</div>` : _weekStrip(h)}
      ${_heat(h.grid)}
      <div class="habit-meta">${esc(h.cadence === 'weekly' ? t('habits.week_progress', { done: h.week_done, target: h.target }) : t('habits.days_progress', { done: h.week_done }))} · ${h.pct}%</div>
    </div>`;
}

function _cadenceSelect(v, id) {
  return `<div class="habit-field">
    <span id="${id}-frequency-label">${esc(t('habits.frequency'))}</span>
    <div class="settings-input custom-select" data-f="cadence" data-value="${esc(v || 'daily')}" data-options="${esc(`daily|${t('habits.every_day')};weekly|${t('habits.weekly')}`)}" aria-labelledby="${id}-frequency-label" aria-describedby="${id}-frequency-help"></div>
  </div>`;
}

function _cadenceHelp(cadence) {
  return t(cadence === 'weekly' ? 'habits.help_weekly' : 'habits.help_daily');
}

function _formFields(h, scope) {
  const id = esc(scope);
  return `<label class="habit-field">${esc(t('habits.habit_name'))}
      <input type="text" class="settings-input" data-f="name" value="${esc(h.name)}" placeholder="${esc(t('habits.name_placeholder'))}">
    </label>
    <div class="habit-edit-row">
      <div class="habit-field habit-icon-field">
        <span>${esc(t('habits.icon'))}</span>
        ${emojiFieldHtml(h.icon)}
      </div>
      ${_cadenceSelect(h.cadence, id)}
      <label class="habit-field habit-target-field"${h.cadence === 'weekly' ? '' : ' hidden'}>${esc(t('habits.days_per_week'))}
        <input type="text" class="settings-input" data-f="target" value="${esc(h.target)}" inputmode="numeric" placeholder="${esc(t('habits.target_placeholder'))}" aria-describedby="${id}-frequency-help">
      </label>
    </div>
    <p class="habit-cadence-help specialist-group-note" id="${id}-frequency-help">${_cadenceHelp(h.cadence)}</p>`;
}

const HABIT_COLORS = ['', '#818cf8', '#34d399', '#f472b6', '#fbbf24', '#60a5fa', '#f87171', '#a78bfa'];
const HABIT_COLOR_NAMES = { '#818cf8': 'indigo', '#34d399': 'green', '#f472b6': 'pink', '#fbbf24': 'amber', '#60a5fa': 'blue', '#f87171': 'red', '#a78bfa': 'violet' };
const colorName = c => t(`habits.color_${HABIT_COLOR_NAMES[c]}`);

function _colorPicker(sel) {
  return `<div class="habit-colors" data-f="color" data-value="${esc(sel || '')}">
    ${HABIT_COLORS.map(c => `<button type="button" class="habit-sw${(sel || '') === c ? ' sel' : ''}" data-c="${c}" style="${c ? `--sw:${c}` : ''}" aria-pressed="${(sel || '') === c}" aria-label="${c ? t('habits.colour_named', { name: colorName(c) }) : t('habits.colour_default')}">${c ? '' : _si('none')}</button>`).join('')}
  </div>`;
}

function _editCard(h) {
  if (_draft?.id === h.id) h = { ...h, ..._draft };
  return `
    <div class="habit-card editing" data-id="${h.id}">
      ${_formFields(h, `habit-${h.id}`)}
      ${_colorPicker(h.color)}
      <div class="habit-actions">
        <button class="btn primary" data-act="save">${esc(t('common.save'))}</button>
        <button class="btn" data-act="cancel">${esc(t('common.cancel'))}</button>
        <button class="btn" data-act="archive">${esc(t('habits.archive'))}</button>
      </div>
    </div>`;
}

function _addForm() {
  const draft = _draft?.id === null ? _draft : { name: '', icon: '', cadence: 'daily', target: '3', color: '', kind: 'check', unit: '' };
  return `
    <div class="habit-card editing habit-add" data-add="1" data-kind="${esc(draft.kind || 'check')}" data-unit="${esc(draft.unit || '')}">
      ${_formFields(draft, 'habit-add')}
      ${_colorPicker(draft.color)}
      ${_creation?.error ? `<div class="habit-create-error specialist-group-note" role="alert">${esc(_creation.error)}</div>` : ''}
      <div class="habit-actions">
        <button class="btn primary" data-act="create">${esc(_creation?.uncertain ? t('habits.retry_save') : t('habits.add_habit'))}</button>
        ${_creation?.canOpen ? `<button class="btn" data-act="open-saved">${esc(t('habits.open_saved'))}</button>` : ''}
        <button class="btn" data-act="cancel-add">${esc(t('common.cancel'))}</button>
      </div>
    </div>`;
}

function _wire(body) {
  body.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  body.querySelectorAll('.habit-icon-pick').forEach(host => wireEmojiPicker(host, { disabled: () => _saving }));
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => {
    if (!_showArchived && typeof window._navigateTo === 'function') window._navigateTo('habits', { preserveRecord: true });
    else loadHabits();
  });
  body.querySelector('[data-act="archive-view"]')?.addEventListener('click', async () => {
    if (_saving || !await closeAdd()) return;
    _showArchived = !_showArchived; _editing = null; _draft = null;
    _habits = []; _hasLoaded = false; await loadHabits();
  });
  $('habits-add-toggle')?.addEventListener('click', async () => {
    if (_saving) return;
    if (_adding) { if (!await closeAdd()) return; }
    else {
      const navigation = _navigation;
      const draft = await _pickHabit();
      if (!draft || navigation !== _navigation || _saving || _adding) return;
      _adding = true; _creation = { requestId: newRequestId() }; _draft = draft;
    }
    _editing = null; _render();
    $('habits-body')?.querySelector('.habit-add [data-f="name"]')?.focus();
  });
  body.querySelectorAll('.habit-card.editing').forEach(card => {
    for (const event of ['input', 'change']) card.addEventListener(event, () => {
      _draft = readForm(card);
      card.querySelector('.habit-target-field').hidden = _draft.cadence !== 'weekly';
      card.querySelector('.habit-cadence-help').textContent = _cadenceHelp(_draft.cadence);
    });
  });
  body.querySelectorAll('.habit-colors').forEach(box => box.querySelectorAll('.habit-sw').forEach(sw =>
    sw.addEventListener('click', () => {
      if (_saving) return;
      box.dataset.value = sw.dataset.c;
      box.querySelectorAll('.habit-sw').forEach(x => { x.classList.toggle('sel', x === sw); x.setAttribute('aria-pressed', String(x === sw)); });
      _draft = readForm(box.closest('.habit-card'));
    })));

  const add = body.querySelector('.habit-add');
  if (add) {
    add.querySelector('[data-act="create"]')?.addEventListener('click', () => writeHabit(async () => {
      const payload = formPayload(add);
      _draft = readForm(add);
      let saved;
      try {
        saved = await api('/api/habits', { method: 'POST', body: { ...payload, request_id: _creation.requestId } });
      } catch (error) {
        _creation.uncertain ||= !error.status || error.status >= 500 || error.status === 409;
        _creation.canOpen = _creation.uncertain && error.status !== 410;
        _creation.deleted = error.status === 410;
        _creation.error = error.status === 409 ? t('habits.err_already_saved')
          : error.status === 410 ? t('habits.err_deleted')
          : _creation.uncertain ? t('habits.err_unconfirmed')
          : (error.message || t('habits.err_save_kept'));
        _render(); throw error;
      }
      upsertHabit(saved); _adding = false; _draft = null; _creation = null;
      toast(t('habits.tracking', { name: saved.name }), 'success'); await loadHabits();
    }));
    add.querySelector('[data-act="cancel-add"]')?.addEventListener('click', async () => { if (await closeAdd()) _render(); });
    add.querySelector('[data-act="open-saved"]')?.addEventListener('click', async () => {
      const navigation = _navigation;
      if (_saving || !await dlgConfirm(t('habits.open_saved_confirm'))) return;
      if (navigation !== _navigation) return;
      await writeHabit(async () => {
        let saved;
        try { saved = await api(`/api/habits/requests/${_creation.requestId}`); }
        catch (error) {
          if (navigation !== _navigation) return;
          _creation.error = error.status === 404 ? t('habits.err_not_found')
            : error.status === 410 ? t('habits.err_deleted')
            : t('habits.err_open_failed');
          if (error.status === 410) { _creation.deleted = true; _creation.canOpen = false; }
          _render(); throw error;
        }
        if (navigation !== _navigation) return;
        _showArchived = saved.archived; _habits = []; _hasLoaded = false; upsertHabit(saved);
        _adding = false; _creation = null; _draft = null; _editing = saved.archived ? null : saved.id;
        await loadHabits();
        if (navigation !== _navigation) return;
        toast(saved.archived ? t('habits.opened_archived') : t('habits.opened_review'), 'success');
        return $('habits-body').querySelector(`[data-id="${CSS.escape(saved.id)}"] ${saved.archived ? '[data-act="restore"]' : '[data-f="name"]'}`);
      });
    });
  }

  body.querySelectorAll('.habit-day[data-toggle]').forEach(btn => btn.addEventListener('click', () => {
    const habit = _habits.find(h => h.id === btn.closest('.habit-card').dataset.id);
    return hasLogger(habit) ? _openDayLog(habit, btn.dataset.toggle) : _toggleDay(btn);
  }));

  // escape on the edit card is cancel. an open frequency menu keeps its escape to itself
  body.querySelectorAll('.habit-card.editing[data-id]').forEach(card => card.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    event.preventDefault();
    card.querySelector('[data-act="cancel"]')?.click();
  }));

  _wireCards(body);
}

// "new habit": pick one from the catalog, or start a custom one (a plain check) with what was typed
async function _pickHabit() {
  const choice = await pick(t('habits.new_habit'), catalogOptions(), {
    placeholder: t('habits.search_habits'), action: { label: t('habits.custom_habit') } });
  if (!choice) return null;
  const blank = { id: null, name: '', icon: '', cadence: 'daily', target: '3', color: '', kind: 'check', unit: '' };
  if (choice.action) return { ...blank, name: choice.query };
  const entry = catalogEntry(choice);
  return entry ? { ...blank, name: catalogName(entry), icon: entry.icon, kind: entry.kind, unit: entry.unit } : null;
}

// a habit with a logger opens that day's log; saving marks the day done with its details
async function _openDayLog(habit, day) {
  if (_saving) return;
  const navigation = _navigation;
  const done = habit.grid.some(g => g.date === day && g.done);
  const result = await openLogger(habit, day, { done,
    save: data => api(`/api/habits/${habit.id}/toggle`, { method: 'POST', body: { date: day, data } }) });
  if (!result || navigation !== _navigation) return;
  await writeHabit(async () => {
    if (result.remove) await api(`/api/habits/${habit.id}/toggle`, { method: 'POST', body: { date: day, done: false } });
    await loadHabits();
  });
}

function _toggleDay(btn) {
  return writeHabit(async () => {
    const id = btn.closest('.habit-card').dataset.id;
    const saved = await api(`/api/habits/${id}/toggle`, { method: 'POST', body: { date: btn.dataset.toggle, done: !btn.classList.contains('done') } });
    const habit = _habits.find(h => h.id === id);
    if (habit) habit.grid = habit.grid.map(day => day.date === saved.date ? { ...day, done: saved.done } : day);
    await loadHabits();
  });
}

function _wireCards(body) {
  body.querySelectorAll('.habit-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (_saving) return;
      // the card is rebuilt under the button: put focus where the next step is
      const inCard = selector => $('habits-body')?.querySelector(`.habit-card[data-id="${CSS.escape(id)}"] ${selector}`);
      if (act === 'edit') { if (!await closeAdd()) return; _editing = id; _draft = null; _render(); inCard('[data-f="name"]')?.focus(); return; }
      if (act === 'cancel') { _editing = null; _draft = null; _render(); inCard('[data-act="edit"]')?.focus(); return; }
      if (act === 'del') {
        const h = _habits.find(x => x.id === id);
        if (!await dlgConfirm(h?.name ? t('habits.delete_confirm', { name: h.name }) : t('habits.delete_confirm_this'))) return;
      }
      await writeHabit(async () => {
        if (act === 'del') {
          await api(`/api/habits/${id}`, { method: 'DELETE' });
          _habits = _habits.filter(h => h.id !== id);
          toast(t('habits.deleted'), 'success');
        } else if (act === 'archive' || act === 'restore' || act === 'save') {
          const saved = await api(`/api/habits/${id}`, { method: 'PATCH', body: act === 'save' ? formPayload(card) : { archived: act === 'archive' } });
          upsertHabit(saved);
          toast(act === 'archive' ? t('habits.archived') : act === 'restore' ? t('habits.restored') : t('common.saved'), 'success');
        } else return;
        if (_editing === id) { _editing = null; _draft = null; }
        await loadHabits();
      });
    }));
  });
}
