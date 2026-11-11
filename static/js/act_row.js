// act where you are (u.01): what a task or habit row on home and plan's agenda can do without
// leaving the page. check it off, move it to tomorrow, swipe on touch (right done, left
// tomorrow), and open its details in a side panel over the page (a bottom sheet on a phone).
import { t } from './i18n.js';
import { icon } from './icons.js';
import { addDays, localDay, whenDay, whenTime } from './when.js';
import { esc } from './escape.js';

const SWIPE = 72;   // px a finger has to travel before a swipe counts

export async function patchTask(id, body) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(t('common.request_failed'));
  return response.json();
}

export const completeTask = (id, done = true) => patchTask(id, { done, stage: done ? 'done' : 'backlog' });
export const tomorrowKey = () => addDays(localDay(), 1);
export const moveToTomorrow = id => patchTask(id, { due_date: tomorrowKey() });

export async function checkHabit(id, done = true) {
  const response = await fetch(`/api/habits/${encodeURIComponent(id)}/toggle`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ date: localDay(), done }),
  });
  if (!response.ok) throw new Error(t('common.request_failed'));
  return response.json();
}

// a horizontal finger drag on the row: past SWIPE to the right is done, to the left is
// tomorrow. a mostly vertical drag is left to the page so lists still scroll. mouse and pen
// use the row's buttons instead, which do the same two things
export function wireSwipe(row, { right, left }) {
  let start = null;
  let swipedAt = 0;
  // the click a finger sends after a swipe must not also open the row
  row.addEventListener('click', event => {
    if (Date.now() - swipedAt < 400) { event.preventDefault(); event.stopPropagation(); }
  }, { capture: true });
  const reset = () => {
    row.classList.remove('is-swiping', 'swipe-right', 'swipe-left');
    row.style.removeProperty('--swipe-x');
    start = null;
  };
  row.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch' || !event.isPrimary) return;
    start = { x: event.clientX, y: event.clientY, id: event.pointerId, dx: 0, locked: false };
  });
  row.addEventListener('pointermove', event => {
    if (!start || event.pointerId !== start.id) return;
    const dx = event.clientX - start.x, dy = event.clientY - start.y;
    if (!start.locked) {
      if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { reset(); return; }
      if (Math.abs(dx) < 10) return;
      start.locked = true;
      try { row.setPointerCapture?.(event.pointerId); } catch { /* a pointer the browser no longer tracks */ }
      row.classList.add('is-swiping');
    }
    start.dx = dx;
    row.style.setProperty('--swipe-x', `${dx}px`);
    row.classList.toggle('swipe-right', dx > SWIPE);
    row.classList.toggle('swipe-left', dx < -SWIPE);
  });
  const end = event => {
    if (!start || event.pointerId !== start.id) return;
    const { dx, locked } = start;
    reset();
    if (!locked) return;
    if (dx > SWIPE) right?.();
    else if (dx < -SWIPE) left?.();
    // after the action's own click, so only the finger's trailing click is dropped
    swipedAt = Date.now();
  };
  row.addEventListener('pointerup', end);
  row.addEventListener('pointercancel', reset);
}

let panel = null;
let opener = null;

function build() {
  panel = document.createElement('aside');
  panel.id = 'details-panel';
  panel.className = 'details-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'false');
  panel.setAttribute('aria-labelledby', 'details-panel-title');
  panel.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    closeDetails();
  });
  document.body.append(panel);
  // the panel belongs to the page it opened over: going to another app or back closes it
  new MutationObserver(() => closeDetails({ restoreFocus: false }))
    .observe(document.body, { attributes: true, attributeFilter: ['data-app'] });
  window.addEventListener('popstate', () => closeDetails({ restoreFocus: false }));
}

export function isDetailsOpen() { return !!panel && !panel.hidden; }

export function closeDetails({ restoreFocus = true } = {}) {
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  panel.replaceChildren();
  document.body.classList.remove('details-panel-open');
  if (restoreFocus && opener?.isConnected) opener.focus();
  opener = null;
}

// a task's details over the current page. done and tomorrow act here; edit opens the full
// editor where the task lives (openFull). onChange runs after a change so the list redraws
export async function openTaskDetails(id, { from = document.activeElement, onChange = () => {}, openFull = null } = {}) {
  if (!panel) build();
  // finished tasks live in their own list (the task list's done view opens them here too)
  let task = null;
  for (const path of ['/api/tasks', '/api/tasks/done']) {
    const response = await fetch(path);
    task = response.ok ? (await response.json()).find(item => item.id === id) : null;
    if (task) break;
  }
  if (!task) { if (openFull) await openFull(); return; }
  opener = from;
  const due = task.due_date ? `${whenDay(task.due_date)}${task.due_time ? ` ${whenTime(task.due_time)}` : ''}` : '';
  const late = task.due_date && task.due_date < localDay();
  const meta = [late ? `${t('home.overdue')} · ${due}` : due, task.project_name, (task.tags || []).map(tag => `#${tag}`).join(' ')].filter(Boolean);
  panel.innerHTML = `
    <header class="details-panel-head">
      <h2 id="details-panel-title">${esc(task.title)}</h2>
      <button type="button" class="details-panel-close" aria-label="${esc(t('common.close'))}">${icon('close')}</button>
    </header>
    ${meta.length ? `<p class="details-panel-meta${late ? ' late' : ''}">${meta.map(esc).join(' · ')}</p>` : ''}
    ${task.notes ? `<p class="details-panel-notes">${esc(task.notes)}</p>` : ''}
    <div class="details-panel-actions">
      ${task.done ? '' : `<button type="button" class="btn primary" data-details="done">${esc(t('common.done'))}</button>`}
      ${task.done || task.due_date === tomorrowKey() ? '' : `<button type="button" class="btn" data-details="tomorrow">${esc(t('tasks.reschedule.tomorrow'))}</button>`}
      ${openFull ? `<button type="button" class="btn" data-details="edit">${esc(t('common.edit'))}</button>` : ''}
    </div>`;
  panel.querySelector('.details-panel-close').addEventListener('click', () => closeDetails());
  const act = async (button, change) => {
    button.disabled = true;
    try { await change(); } catch { button.disabled = false; return; }
    closeDetails();
    await onChange();
  };
  panel.querySelector('[data-details="done"]')?.addEventListener('click', event => act(event.currentTarget, () => completeTask(id)));
  panel.querySelector('[data-details="tomorrow"]')?.addEventListener('click', event => act(event.currentTarget, () => moveToTomorrow(id)));
  panel.querySelector('[data-details="edit"]')?.addEventListener('click', async () => { closeDetails({ restoreFocus: false }); await openFull(); });
  panel.hidden = false;
  document.body.classList.add('details-panel-open');
  requestAnimationFrame(() => panel.querySelector('[data-details="done"], [data-details="edit"]')?.focus());
}
