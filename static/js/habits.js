// habits — a dedicated habit grid (journal has streaks, but no habit tracker). tap a
// day to mark it done; each habit shows its streak, this-week progress, and a
// GitHub-style contribution heatmap. mirrors the days/watch panel conventions.
import { api, toast } from './util.js';
import { initCustomDropdown } from './dropdown.js?v=212';
import { confirm as dlgConfirm } from './dialog.js';
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

export function initHabits(fetcher = fetch) {
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
  _loading = true; _loadError = ''; _render();
  try {
    const data = await api('/api/habits/overview', {}, fetcher);
    if (!Array.isArray(data.habits)) throw new Error('invalid habit response');
    if (generation !== _generation) return false;
    _habits = data.habits; _hasLoaded = true;
  } catch {
    if (generation !== _generation) return false;
    _loadError = 'could not load habits. ' + (_hasLoaded ? 'the last loaded habits are still shown.' : 'retry to see your habits.');
  } finally {
    if (generation === _generation) { _loading = false; _render(); }
  }
  return !_loadError;
}

function setBusy() {
  const body = $('habits-body');
  body?.setAttribute('aria-busy', String(_saving || _loading));
  body?.querySelectorAll('button, input, .custom-select').forEach(el => { el.disabled = _saving; });
}

async function writeHabit(change) {
  if (_saving) return;
  const focus = document.activeElement;
  const cardId = focus?.closest('.habit-card')?.dataset.id;
  const day = focus?.dataset.toggle;
  const interruptedLoad = _loading;
  const generation = ++_generation;
  _saving = true; _loading = false; setBusy();
  try { await change(); }
  catch (error) {
    toast(error.message === 'Failed to fetch' ? 'could not save. your input is kept; retry when connected.' : (error.message || 'could not save. try again.'), 'error');
    if (interruptedLoad && generation === _generation) {
      _loadError = 'habits were not refreshed. retry to load them; your input is kept.';
      _render();
    }
  }
  finally {
    _saving = false; setBusy();
    if ($('habits-body')?.offsetParent) {
      const card = cardId ? $('habits-body').querySelector(`[data-id="${CSS.escape(cardId)}"]`) : null;
      const target = focus?.isConnected ? focus : (day ? card?.querySelector(`[data-toggle="${CSS.escape(day)}"]`) : card?.querySelector('[data-act="edit"]'));
      (target || $('habits-add-toggle'))?.focus();
    }
  }
}

function readForm(card) {
  const value = field => card.querySelector(`[data-f="${field}"]`);
  return { id: card.dataset.id || null, name: value('name')?.value || '', icon: value('icon')?.value || '',
    cadence: value('cadence')?.dataset.value || 'daily', target: value('target')?.value ?? '3', color: value('color')?.dataset.value || '' };
}

function formPayload(card) {
  const values = readForm(card), target = parseInt(values.target, 10);
  if (!values.name.trim()) throw new Error('name the habit');
  return { name: values.name.trim(), icon: values.icon.trim(), cadence: values.cadence,
    color: values.color, target: Number.isNaN(target) ? 3 : target };
}

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function _localDays(n) {
  const out = [];
  const t = new Date(); t.setHours(0, 0, 0, 0);
  for (let i = n - 1; i >= 0; i--) { const d = new Date(t); d.setDate(t.getDate() - i); out.push(d); }
  return out;
}
const _iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const _DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function _render() {
  const body = $('habits-body');
  if (!body) return;
  const active = body.contains(document.activeElement) ? document.activeElement : null;
  const field = active?.dataset.f;
  const selection = typeof active?.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
  const cards = _habits.map(h => h.id === _editing ? _editCard(h) : _card(h)).join('');
  body.innerHTML = `
    <div class="habits-bar">
      <div class="habits-summary">${_habits.length ? `${_habits.length} habit${_habits.length !== 1 ? 's' : ''}` : ''}</div>
      <button class="btn primary" id="habits-add-toggle">${_si('plus')} habit</button>
    </div>
    ${_loading ? '<div class="specialist-group-note" role="status">loading habits…</div>' : ''}
    ${_loadError ? `<div class="specialist-group-note legacy-load-note habit-load-error" role="alert"><span>${esc(_loadError)}</span><button type="button" class="btn" data-act="retry-load">retry</button></div>` : ''}
    ${_adding ? _addForm() : ''}
    ${_habits.length ? `<div class="habits-list">${cards}</div>` : (_adding || !_hasLoaded || _loading ? '' : `<div class="habits-empty">no habits yet: track something daily (read, water, walk) or a few times a week. add one above.</div>`)}`;
  _wire(body);
  setBusy();
  if (field) {
    const input = body.querySelector(`.habit-card.editing [data-f="${CSS.escape(field)}"]`);
    input?.focus();
    if (selection && input?.setSelectionRange) input.setSelectionRange(...selection);
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
    return `<button class="habit-day${done.has(iso) ? ' done' : ''}" data-toggle="${iso}" title="${iso}"><span>${_DOW[d.getDay()]}</span><b>${d.getDate()}</b></button>`;
  }).join('')}</div>`;
}

function _card(h) {
  const accent = h.color || 'var(--accent)';
  const slip = h.risk && h.risk.slipping
    ? `<span class="habit-slip" title="${esc(h.risk.reason)}">slipping</span>` : '';
  return `
    <div class="habit-card${slip ? ' at-risk' : ''}" data-id="${h.id}" style="--habit-accent:${esc(accent)}">
      <div class="habit-top">
        ${h.icon ? `<span class="habit-icon">${esc(h.icon)}</span>` : ''}
        <div class="habit-name">${esc(h.name)}</div>
        ${slip}
        <span class="habit-streak${h.streak > 0 ? ' on' : ''}" title="current streak">${h.streak}${_si('fire')}</span>
        <div class="habit-actions">
          <button class="icon-btn" data-act="edit" title="edit">${_si('edit')}</button>
          <button class="icon-btn danger" data-act="del" title="delete">${_si('trash')}</button>
        </div>
      </div>
      ${_weekStrip(h)}
      ${_heat(h.grid)}
      <div class="habit-meta">${h.cadence === 'weekly' ? `${h.week_done}/${h.target} this week` : `${h.week_done}/7 days`} · ${h.pct}%</div>
    </div>`;
}

function _cadenceSelect(v) {
  return `<div class="settings-input custom-select" data-f="cadence" data-value="${esc(v || 'daily')}" data-options="daily|every day;weekly|a few times a week"></div>`;
}

const HABIT_COLORS = ['', '#818cf8', '#34d399', '#f472b6', '#fbbf24', '#60a5fa', '#f87171', '#a78bfa'];

function _colorPicker(sel) {
  return `<div class="habit-colors" data-f="color" data-value="${esc(sel || '')}">
    ${HABIT_COLORS.map(c => `<span class="habit-sw${(sel || '') === c ? ' sel' : ''}" data-c="${c}" style="${c ? `background:${c}` : ''}" title="${c || 'default'}">${c ? '' : '○'}</span>`).join('')}
  </div>`;
}

function _editCard(h) {
  if (_draft?.id === h.id) h = { ...h, ..._draft };
  return `
    <div class="habit-card editing" data-id="${h.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(h.name)}" placeholder="habit name">
      <div class="habit-edit-row">
        <input type="text" class="settings-input habit-icon-in" data-f="icon" value="${esc(h.icon)}" placeholder="icon (emoji)" maxlength="2">
        ${_cadenceSelect(h.cadence)}
        <input type="text" class="settings-input" data-f="target" value="${esc(h.target)}" inputmode="numeric" placeholder="x / week" title="weekly target">
      </div>
      ${_colorPicker(h.color)}
      <div class="habit-actions">
        <button class="btn primary" data-act="save">save</button>
        <button class="btn" data-act="cancel">cancel</button>
        <button class="btn" data-act="archive">archive</button>
      </div>
    </div>`;
}

function _addForm() {
  const draft = _draft?.id === null ? _draft : { name: '', icon: '', cadence: 'daily', target: '3', color: '' };
  return `
    <div class="habit-card editing habit-add" data-add="1">
      <input type="text" class="settings-input" data-f="name" value="${esc(draft.name)}" placeholder="habit name (e.g. read, water, walk)">
      <div class="habit-edit-row">
        <input type="text" class="settings-input habit-icon-in" data-f="icon" value="${esc(draft.icon)}" placeholder="icon" maxlength="2">
        ${_cadenceSelect(draft.cadence)}
        <input type="text" class="settings-input" data-f="target" value="${esc(draft.target)}" inputmode="numeric" placeholder="x / week">
      </div>
      ${_colorPicker(draft.color)}
      <div class="habit-actions">
        <button class="btn primary" data-act="create">add habit</button>
        <button class="btn" data-act="cancel-add">cancel</button>
      </div>
    </div>`;
}

function _wire(body) {
  body.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  body.querySelector('[data-act="retry-load"]')?.addEventListener('click', () => {
    if (typeof window._navigateTo === 'function') window._navigateTo('habits', { preserveRecord: true });
    else loadHabits();
  });
  $('habits-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _editing = null; _draft = null; _render(); });
  body.querySelectorAll('.habit-card.editing').forEach(card => {
    for (const event of ['input', 'change']) card.addEventListener(event, () => { _draft = readForm(card); });
  });
  body.querySelectorAll('.habit-colors').forEach(box => box.querySelectorAll('.habit-sw').forEach(sw =>
    sw.addEventListener('click', () => {
      if (_saving) return;
      box.dataset.value = sw.dataset.c;
      box.querySelectorAll('.habit-sw').forEach(x => x.classList.toggle('sel', x === sw));
      _draft = readForm(box.closest('.habit-card'));
    })));

  const add = body.querySelector('.habit-add');
  if (add) {
    add.querySelector('[data-act="create"]')?.addEventListener('click', () => writeHabit(async () => {
      const saved = await api('/api/habits', { method: 'POST', body: formPayload(add) });
      _habits.push(saved); _adding = false; _draft = null;
      toast(`tracking ${saved.name}`, 'success'); await loadHabits();
    }));
    add.querySelector('[data-act="cancel-add"]')?.addEventListener('click', () => { _adding = false; _draft = null; _render(); });
  }

  body.querySelectorAll('.habit-day[data-toggle]').forEach(btn => btn.addEventListener('click', () => writeHabit(async () => {
    const id = btn.closest('.habit-card').dataset.id;
    const saved = await api(`/api/habits/${id}/toggle`, { method: 'POST', body: { date: btn.dataset.toggle, done: !btn.classList.contains('done') } });
    const habit = _habits.find(h => h.id === id);
    if (habit) habit.grid = habit.grid.map(day => day.date === saved.date ? { ...day, done: saved.done } : day);
    await loadHabits();
  })));

  body.querySelectorAll('.habit-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (_saving) return;
      if (act === 'edit') { _editing = id; _adding = false; _draft = null; _render(); return; }
      if (act === 'cancel') { _editing = null; _draft = null; _render(); return; }
      if (act === 'del') {
        const h = _habits.find(x => x.id === id);
        if (!await dlgConfirm(`delete "${h?.name || 'this habit'}" and its history?`)) return;
      }
      await writeHabit(async () => {
        if (act === 'del') {
          await api(`/api/habits/${id}`, { method: 'DELETE' });
          _habits = _habits.filter(h => h.id !== id);
          toast('deleted', 'success');
        } else if (act === 'archive' || act === 'save') {
          const saved = await api(`/api/habits/${id}`, { method: 'PATCH', body: act === 'archive' ? { archived: true } : formPayload(card) });
          _habits = _habits.map(h => h.id === id ? saved : h).filter(h => !h.archived);
          toast(act === 'archive' ? 'archived' : 'saved', 'success');
        } else return;
        _editing = null; _draft = null; await loadHabits();
      });
    }));
  });
}
