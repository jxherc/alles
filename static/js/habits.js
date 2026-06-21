// habits — a dedicated habit grid (journal has streaks, but no habit tracker). tap a
// day to mark it done; each habit shows its streak, this-week progress, and a
// GitHub-style contribution heatmap. mirrors the days/watch panel conventions.
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { confirm as dlgConfirm } from './dialog.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _habits = [];
let _editing = null;
let _adding = false;

export function initHabits() {
  loadHabits();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadHabits(); });
}

export async function loadHabits() {
  try { _habits = (await fetch('/api/habits/overview').then(r => r.json())).habits || []; }
  catch { _habits = []; }
  _render();
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
  const cards = _habits.map(h => h.id === _editing ? _editCard(h) : _card(h)).join('');
  body.innerHTML = `
    <div class="habits-bar">
      <div class="habits-summary">${_habits.length ? `${_habits.length} habit${_habits.length !== 1 ? 's' : ''}` : ''}</div>
      <button class="btn primary" id="habits-add-toggle">${_si('plus')} habit</button>
    </div>
    ${_adding ? _addForm() : ''}
    ${_habits.length ? `<div class="habits-list">${cards}</div>` : (_adding ? '' : `<div class="habits-empty">no habits yet — track something daily (read, water, walk) or a few times a week. add one above.</div>`)}`;
  _wire(body);
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
  return `
    <div class="habit-card" data-id="${h.id}" style="--habit-accent:${esc(accent)}">
      <div class="habit-top">
        ${h.icon ? `<span class="habit-icon">${esc(h.icon)}</span>` : ''}
        <div class="habit-name">${esc(h.name)}</div>
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

function _editCard(h) {
  return `
    <div class="habit-card editing" data-id="${h.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(h.name)}" placeholder="habit name">
      <div class="habit-edit-row">
        <input type="text" class="settings-input habit-icon-in" data-f="icon" value="${esc(h.icon)}" placeholder="icon (emoji)" maxlength="2">
        ${_cadenceSelect(h.cadence)}
        <input type="text" class="settings-input" data-f="target" value="${h.target}" inputmode="numeric" placeholder="x / week" title="weekly target">
      </div>
      <div class="habit-actions">
        <button class="btn primary" data-act="save">save</button>
        <button class="btn" data-act="cancel">cancel</button>
        <button class="btn" data-act="archive">archive</button>
      </div>
    </div>`;
}

function _addForm() {
  return `
    <div class="habit-card editing habit-add" data-add="1">
      <input type="text" class="settings-input" data-f="name" placeholder="habit name (e.g. read, water, walk)">
      <div class="habit-edit-row">
        <input type="text" class="settings-input habit-icon-in" data-f="icon" placeholder="icon" maxlength="2">
        ${_cadenceSelect('daily')}
        <input type="text" class="settings-input" data-f="target" value="3" inputmode="numeric" placeholder="x / week">
      </div>
      <div class="habit-actions">
        <button class="btn primary" data-act="create">add habit</button>
        <button class="btn" data-act="cancel-add">cancel</button>
      </div>
    </div>`;
}

function _wire(body) {
  body.querySelectorAll('.custom-select').forEach(initCustomDropdown);
  $('habits-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _editing = null; _render(); });

  const add = body.querySelector('.habit-add');
  if (add) {
    add.querySelector('[data-act="create"]')?.addEventListener('click', () => _create(add));
    add.querySelector('[data-act="cancel-add"]')?.addEventListener('click', () => { _adding = false; _render(); });
  }

  body.querySelectorAll('.habit-day[data-toggle]').forEach(btn => btn.addEventListener('click', async () => {
    const card = btn.closest('.habit-card'); const id = card.dataset.id;
    await fetch(`/api/habits/${id}/toggle`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ date: btn.dataset.toggle }) });
    loadHabits();
  }));

  body.querySelectorAll('.habit-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'edit') { _editing = id; _adding = false; _render(); return; }
      if (act === 'cancel') { _editing = null; _render(); return; }
      if (act === 'del') {
        const h = _habits.find(x => x.id === id);
        if (!await dlgConfirm(`delete "${h?.name || 'this habit'}" and its history?`)) return;
        await fetch(`/api/habits/${id}`, { method: 'DELETE' }); toast('deleted', 'success'); _editing = null; loadHabits(); return;
      }
      if (act === 'archive') {
        await fetch(`/api/habits/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ archived: true }) });
        toast('archived', 'success'); _editing = null; loadHabits(); return;
      }
      if (act === 'save') {
        const v = f => card.querySelector(`[data-f="${f}"]`);
        const t = parseInt(v('target')?.value, 10);
        const r = await fetch(`/api/habits/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name: v('name')?.value.trim(), icon: v('icon')?.value.trim(), cadence: v('cadence')?.dataset.value, target: Number.isNaN(t) ? undefined : t }),
        });
        if (!r.ok) { toast((await r.json()).detail || 'save failed', 'error'); return; }
        _editing = null; toast('saved', 'success'); loadHabits(); return;
      }
    }));
  });
}

async function _create(card) {
  const v = f => card.querySelector(`[data-f="${f}"]`);
  const name = v('name')?.value.trim();
  if (!name) { toast('name the habit', 'error'); return; }
  const t = parseInt(v('target')?.value, 10);
  const r = await fetch('/api/habits', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, icon: v('icon')?.value.trim() || '', cadence: v('cadence')?.dataset.value || 'daily', target: Number.isNaN(t) ? 3 : t }),
  });
  if (!r.ok) { toast((await r.json()).detail || 'failed', 'error'); return; }
  _adding = false; toast(`tracking ${name}`, 'success'); loadHabits();
}
