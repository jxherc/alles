import { prompt as dlgPrompt } from './dialog.js';
import { getDropdownValue, populateDropdown } from './dropdown.js?v=212';
import { t as tr } from './i18n.js';
import { createFocusBoundary, setControlState } from './kokuen.js?v=1';
import { toast } from './util.js';
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

let _tasks = [];
let _tree = [];
let _tab = 'active';   // 'active' | 'done' (history)
let _search = '';
let _tabsWired = false;

function _wireTabs() {
  if (_tabsWired) return; _tabsWired = true;
  document.querySelectorAll('.tasks-tab').forEach(b => b.addEventListener('click', () => {
    _tab = b.dataset.tab;
    document.querySelectorAll('.tasks-tab').forEach(x => {
      const selected = x === b;
      x.classList.toggle('active', selected);
      x.setAttribute('aria-pressed', String(selected));
    });
    loadTasks();
  }));
  const si = document.getElementById('tasks-search');
  let _t = 0;
  si?.addEventListener('input', () => {
    clearTimeout(_t);
    _t = setTimeout(() => { _search = si.value.trim(); loadTasks(); }, 180);
  });
  window.addEventListener('alles:localization-change', () => {
    if (_tab === 'active' && !_search) renderTree();
    else renderTasks();
  });
}

const _URL = { active: '/api/tasks', done: '/api/tasks/done',
               today: '/api/tasks/views/today', upcoming: '/api/tasks/views/upcoming',
               someday: '/api/tasks/views/someday' };

export async function loadTasks(fetcher = fetch) {
  _wireTabs();
  const isTree = _tab === 'active' && !_search;   // the "all" view shows the subtask tree
  const url = _search ? `/api/tasks/search?q=${encodeURIComponent(_search)}`
                      : (isTree ? '/api/tasks/tree' : (_URL[_tab] || '/api/tasks'));
  const data = await fetcher(url).then(r => r.json());
  if (isTree) { _tree = data; renderTree(); } else { _tasks = data; renderTasks(); }
}

function _todayISO() { return new Date().toISOString().slice(0, 10); }

function _dueBadge(d) {
  if (!d) return '';
  const iso = d.slice(0, 10), today = _todayISO();
  const cls = iso < today ? 'task-due overdue' : (iso === today ? 'task-due today' : 'task-due');
  const label = iso === today ? tr('common.today') : (iso === _shift(today, 1) ? tr('tasks.tomorrow') : iso);
  return `<span class="${cls}">${label}</span>`;
}
function _shift(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

function _rowHtml(t, child, progress) {
  const title = esc(t.title);
  const checkLabel = esc(tr(t.done ? 'tasks.mark_incomplete' : 'tasks.mark_complete', { task: t.title }));
  return `
    <div class="task-item${child ? ' task-child' : ''}" data-id="${t.id}">
      <button type="button" class="task-check${t.done ? ' done' : ''}" data-id="${t.id}" aria-label="${checkLabel}"></button>
      <button type="button" class="task-title${t.done ? ' done' : ''}" aria-label="${esc(tr('tasks.edit_named', { task: t.title }))}">${title}</button>
      ${t.repeat ? `<span class="task-repeat" title="${esc(tr('tasks.repeats', { repeat: tr(`tasks.repeat.${t.repeat}`) }))}">${_si('refresh')}</span>` : ''}
      ${_dueBadge(t.due_date)}
      ${(t.tags || []).map(g => `<span class="task-tag">#${esc(g)}</span>`).join('')}
      ${t.priority ? `<span class="task-high task-p${t.priority}">${esc(tr(`tasks.priority.${['', 'low', 'medium', 'high'][t.priority] || 'high'}`))}</span>` : ''}
      ${progress && progress.total ? `<span class="task-progress">${progress.done}/${progress.total}</span>` : ''}
      ${!child ? `<button type="button" class="task-addsub" data-id="${t.id}" aria-label="${esc(tr('tasks.add_subtask_named', { task: t.title }))}" title="${esc(tr('tasks.add_subtask'))}">${esc(tr('tasks.sub'))}</button>` : ''}
      <button type="button" class="task-del" data-id="${t.id}" aria-label="${esc(tr('tasks.delete_named', { task: t.title }))}">×</button>
    </div>`;
}

function _emptyMsg() {
  const msg = _tab === 'done' ? tr('tasks.no_completed') : tr('tasks.nothing_here');
  return `<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">${msg}</div>`;
}

function renderTasks() {
  const list = document.getElementById('tasks-list');
  if (!list) return;
  list.innerHTML = _tasks.length ? _tasks.map(t => _rowHtml(t, false)).join('') : _emptyMsg();
  _wireRows(list);
}

function renderTree() {
  const list = document.getElementById('tasks-list');
  if (!list) return;
  list.innerHTML = _tree.length
    ? _tree.map(t => _rowHtml(t, false, t.progress) + (t.subtasks || []).map(s => _rowHtml(s, true)).join('')).join('')
    : _emptyMsg();
  _wireRows(list);
}

function _findTask(id) {
  for (const t of _tasks) if (t.id === id) return t;
  for (const t of _tree) {
    if (t.id === id) return t;
    for (const s of (t.subtasks || [])) if (s.id === id) return s;
  }
  return null;
}

function _wireRows(list) {
  list.querySelectorAll('.task-check').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.getAttribute('aria-busy') === 'true') return;
    const t = _findTask(btn.dataset.id);
    await _mutateTask(btn, async () => {
      await _requireOk(fetch(`/api/tasks/${btn.dataset.id}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ done: !(t && t.done) }),
      }));
      await loadTasks();
    });
  }));
  list.querySelectorAll('.task-del').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.getAttribute('aria-busy') === 'true') return;
    await _mutateTask(btn, async () => {
      await _requireOk(fetch(`/api/tasks/${btn.dataset.id}`, { method: 'DELETE' }));
      await loadTasks();
    });
  }));
  list.querySelectorAll('.task-addsub').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.getAttribute('aria-busy') === 'true') return;
    setControlState(btn, 'busy', { message: tr('tasks.waiting_for_subtask') });
    const title = await dlgPrompt(tr('tasks.subtask_prompt'));
    if (!title?.trim()) {
      btn.removeAttribute('aria-busy');
      setControlState(btn, 'resting');
      return;
    }
    await _mutateTask(btn, async () => {
      await _requireOk(fetch('/api/tasks', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), parent_id: btn.dataset.id }),
      }));
      await loadTasks();
    }, { alreadyBusy: true });
  }));
  list.querySelectorAll('.task-title').forEach(el => el.addEventListener('click', () => {
    openTaskEditor(el.closest('.task-item').dataset.id, el);
  }));
}

async function _requireOk(responsePromise) {
  const response = await responsePromise;
  if (!response.ok) throw new Error(`request failed (${response.status})`);
  return response;
}

async function _mutateTask(button, action, { alreadyBusy = false } = {}) {
  if (!alreadyBusy) setControlState(button, 'busy', { message: tr('common.saving') });
  button.disabled = true;
  button.setAttribute('aria-disabled', 'true');
  try {
    await action();
    return true;
  } catch {
    button.disabled = false;
    button.removeAttribute('aria-disabled');
    button.removeAttribute('aria-busy');
    setControlState(button, 'error', { message: tr('common.request_failed') });
    toast(tr('common.request_failed'), 'error');
    return false;
  }
}

function openTaskEditor(id, source) {
  const t = _findTask(id);
  if (!t) return;
  const priorities = [[0, tr('tasks.priority.none')], [1, tr('tasks.priority.low')], [2, tr('tasks.priority.medium')], [3, tr('tasks.priority.high')]];
  const repeats = [['', tr('tasks.repeat.none')], ['daily', tr('tasks.repeat.daily')], ['weekly', tr('tasks.repeat.weekly')], ['monthly', tr('tasks.repeat.monthly')], ['yearly', tr('tasks.repeat.yearly')]];
  const ov = document.createElement('div');
  ov.className = 'task-editor-ov';
  ov.innerHTML = `<div class="task-editor" role="dialog" aria-modal="true" aria-labelledby="task-editor-title">
    <h2 class="sr-only" id="task-editor-title">${esc(tr('tasks.edit_dialog'))}</h2>
    <label class="sr-only" for="te-title">${esc(tr('tasks.title_label'))}</label><input class="settings-input" id="te-title" value="${esc(t.title)}">
    <label class="sr-only" for="te-notes">${esc(tr('tasks.notes'))}</label><textarea class="settings-input te-notes" id="te-notes" placeholder="${esc(tr('tasks.notes'))}">${esc(t.notes || '')}</textarea>
    <div class="te-row"><label id="te-prio-label">${esc(tr('tasks.priority.label'))}</label><div class="settings-input custom-select" id="te-prio" aria-labelledby="te-prio-label"></div></div>
    <div class="te-row"><label id="te-rep-label">${esc(tr('tasks.repeat.label'))}</label><div class="settings-input custom-select" id="te-rep" aria-labelledby="te-rep-label"></div></div>
    <div class="te-row"><label for="te-due">${esc(tr('tasks.due'))}</label><input class="settings-input" id="te-due" value="${esc((t.due_date || '').slice(0, 10))}" placeholder="YYYY-MM-DD"></div>
    <div class="te-resched">${['today', 'tomorrow', 'next_week', 'weekend'].map(w => `<button class="btn te-rs" data-w="${w}">${esc(tr(`tasks.reschedule.${w}`))}</button>`).join('')}</div>
    <div class="te-row"><label for="te-tags">${esc(tr('tasks.tags'))}</label><input class="settings-input" id="te-tags" value="${esc((t.tags || []).join(', '))}" placeholder="${esc(tr('tasks.tags_placeholder'))}"></div>
    <div class="te-row"><label for="te-proj">${esc(tr('tasks.project'))}</label><input class="settings-input" id="te-proj" value="${esc(t.project || '')}"></div>
    <div class="te-actions"><button type="button" class="btn" id="te-cancel">${esc(tr('common.cancel'))}</button><button type="button" class="btn primary" id="te-save">${esc(tr('common.save'))}</button></div>
  </div>`;
  document.body.appendChild(ov);
  populateDropdown(ov.querySelector('#te-prio'), priorities.map(([value, label]) => ({ value, label })), t.priority || 0);
  populateDropdown(ov.querySelector('#te-rep'), repeats.map(([value, label]) => ({ value, label })), t.repeat || '');
  const dialog = ov.querySelector('.task-editor');
  let focusBoundary = null;
  const close = ({ restoreFocus = true } = {}) => {
    focusBoundary?.deactivate({ restoreFocus });
    focusBoundary?.destroy();
    ov.remove();
  };
  focusBoundary = createFocusBoundary(dialog, { trigger: source, onEscape: close });
  ov.addEventListener('click', e => { if (e.target === ov) close(); });
  ov.querySelector('#te-cancel').onclick = close;
  // stage the date in the input only (no server write) so "save" persists it and "cancel" cancels
  ov.querySelectorAll('.te-rs').forEach(b => b.addEventListener('click', () => {
    ov.querySelector('#te-due').value = _reschedDate(b.dataset.w);
  }));
  ov.querySelector('#te-save').onclick = async event => {
    const body = {
      title: ov.querySelector('#te-title').value.trim() || t.title,
      notes: ov.querySelector('#te-notes').value,
      priority: parseInt(getDropdownValue(ov.querySelector('#te-prio'))) || 0,
      repeat: getDropdownValue(ov.querySelector('#te-rep')),
      due_date: ov.querySelector('#te-due').value.trim() || null,
      tags: ov.querySelector('#te-tags').value.split(',').map(s => s.trim()).filter(Boolean).join(','),
      project: ov.querySelector('#te-proj').value.trim(),
    };
    const saveButton = event.currentTarget;
    if (saveButton.getAttribute('aria-busy') === 'true') return;
    setControlState(saveButton, 'busy', { message: tr('common.saving') });
    saveButton.disabled = true;
    saveButton.setAttribute('aria-disabled', 'true');
    try {
      await _requireOk(fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }));
      close({ restoreFocus: false });
      await loadTasks();
      document.querySelector(`.task-item[data-id="${id}"] .task-title`)?.focus();
    } catch {
      saveButton.disabled = false;
      saveButton.removeAttribute('aria-disabled');
      saveButton.removeAttribute('aria-busy');
      setControlState(saveButton, 'error', { message: tr('common.request_failed') });
      toast(tr('common.request_failed'), 'error');
    }
  };
  focusBoundary.activate({ focus: ov.querySelector('#te-title'), source });
}

// quick-reschedule date, computed locally to mirror services/task_nl.reschedule_date
function _reschedDate(w) {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  if (w === 'tomorrow') d.setDate(d.getDate() + 1);
  else if (w === 'next_week') d.setDate(d.getDate() + 7);
  else if (w === 'weekend') d.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7));  // next Saturday (today if Sat)
  const z = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

export async function addTask(title) {
  if (!title.trim()) return;
  // natural-language quick add — parses due date / repeat / #tags / ! priority
  await fetch('/api/tasks/quick', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text: title }),
  });
  if (_tab === 'done') {   // jump back to a visible list so the new task shows
    _tab = 'active';
    document.querySelectorAll('.tasks-tab').forEach(x => {
      const selected = x.dataset.tab === 'active';
      x.classList.toggle('active', selected);
      x.setAttribute('aria-pressed', String(selected));
    });
  }
  if (_search) {   // a stale search filter would hide the new task — clear it like the done-tab case
    _search = '';
    const si = document.getElementById('tasks-search');
    if (si) si.value = '';
  }
  await loadTasks();
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
