import { toast } from './util.js';
import { prompt as dlgPrompt } from './dialog.js';

let _tasks = [];
let _tree = [];
let _tab = 'active';   // 'active' | 'done' (history)
let _search = '';
let _tabsWired = false;

function _wireTabs() {
  if (_tabsWired) return; _tabsWired = true;
  document.querySelectorAll('.tasks-tab').forEach(b => b.addEventListener('click', () => {
    _tab = b.dataset.tab;
    document.querySelectorAll('.tasks-tab').forEach(x => x.classList.toggle('active', x === b));
    loadTasks();
  }));
  const si = document.getElementById('tasks-search');
  let _t = 0;
  si?.addEventListener('input', () => {
    clearTimeout(_t);
    _t = setTimeout(() => { _search = si.value.trim(); loadTasks(); }, 180);
  });
}

const _URL = { active: '/api/tasks', done: '/api/tasks/done',
               today: '/api/tasks/views/today', upcoming: '/api/tasks/views/upcoming',
               someday: '/api/tasks/views/someday' };

export async function loadTasks() {
  _wireTabs();
  const isTree = _tab === 'active' && !_search;   // the "all" view shows the subtask tree
  const url = _search ? `/api/tasks/search?q=${encodeURIComponent(_search)}`
                      : (isTree ? '/api/tasks/tree' : (_URL[_tab] || '/api/tasks'));
  const data = await fetch(url).then(r => r.json());
  if (isTree) { _tree = data; renderTree(); } else { _tasks = data; renderTasks(); }
}

function _todayISO() { return new Date().toISOString().slice(0, 10); }

function _dueBadge(d) {
  if (!d) return '';
  const iso = d.slice(0, 10), today = _todayISO();
  const cls = iso < today ? 'task-due overdue' : (iso === today ? 'task-due today' : 'task-due');
  const label = iso === today ? 'today' : (iso === _shift(today, 1) ? 'tomorrow' : iso);
  return `<span class="${cls}">${label}</span>`;
}
function _shift(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

function _rowHtml(t, child, progress) {
  return `
    <div class="task-item${child ? ' task-child' : ''}" data-id="${t.id}">
      <button class="task-check${t.done ? ' done' : ''}" data-id="${t.id}"></button>
      <span class="task-title${t.done ? ' done' : ''}">${esc(t.title)}</span>
      ${t.repeat ? `<span class="task-repeat" title="repeats ${t.repeat}">🔁</span>` : ''}
      ${_dueBadge(t.due_date)}
      ${(t.tags || []).map(g => `<span class="task-tag">#${esc(g)}</span>`).join('')}
      ${t.priority ? `<span class="task-high task-p${t.priority}">${['', 'low', 'med', 'high'][t.priority] || 'high'}</span>` : ''}
      ${progress && progress.total ? `<span class="task-progress">${progress.done}/${progress.total}</span>` : ''}
      ${!child ? `<button class="task-addsub" data-id="${t.id}" title="add subtask">+ sub</button>` : ''}
      <button class="task-del" data-id="${t.id}">×</button>
    </div>`;
}

function _emptyMsg() {
  const msg = _tab === 'done' ? 'no completed tasks yet' : 'nothing here';
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
    const t = _findTask(btn.dataset.id);
    await fetch(`/api/tasks/${btn.dataset.id}`, {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ done: !(t && t.done) }),
    });
    await loadTasks();
  }));
  list.querySelectorAll('.task-del').forEach(btn => btn.addEventListener('click', async () => {
    await fetch(`/api/tasks/${btn.dataset.id}`, { method: 'DELETE' });
    await loadTasks();
  }));
  list.querySelectorAll('.task-addsub').forEach(btn => btn.addEventListener('click', async () => {
    const title = await dlgPrompt('subtask:');
    if (!title?.trim()) return;
    await fetch('/api/tasks', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title: title.trim(), parent_id: btn.dataset.id }),
    });
    await loadTasks();
  }));
  list.querySelectorAll('.task-title').forEach(el => el.addEventListener('click', () => {
    openTaskEditor(el.closest('.task-item').dataset.id);
  }));
}

function openTaskEditor(id) {
  const t = _findTask(id);
  if (!t) return;
  const prio = [[0, 'none'], [1, 'low'], [2, 'med'], [3, 'high']]
    .map(([v, l]) => `<option value="${v}"${(t.priority || 0) === v ? ' selected' : ''}>${l}</option>`).join('');
  const rep = [['', 'no repeat'], ['daily', 'daily'], ['weekly', 'weekly'], ['monthly', 'monthly'], ['yearly', 'yearly']]
    .map(([v, l]) => `<option value="${v}"${(t.repeat || '') === v ? ' selected' : ''}>${l}</option>`).join('');
  const ov = document.createElement('div');
  ov.className = 'task-editor-ov';
  ov.innerHTML = `<div class="task-editor">
    <input class="settings-input" id="te-title" value="${esc(t.title)}">
    <textarea class="settings-input te-notes" id="te-notes" placeholder="notes…">${esc(t.notes || '')}</textarea>
    <div class="te-row"><label>priority</label><select class="settings-input" id="te-prio">${prio}</select></div>
    <div class="te-row"><label>repeat</label><select class="settings-input" id="te-rep">${rep}</select></div>
    <div class="te-row"><label>due</label><input class="settings-input" id="te-due" value="${esc((t.due_date || '').slice(0, 10))}" placeholder="YYYY-MM-DD"></div>
    <div class="te-resched">${['today', 'tomorrow', 'next_week', 'weekend'].map(w => `<button class="btn te-rs" data-w="${w}">${w.replace('_', ' ')}</button>`).join('')}</div>
    <div class="te-row"><label>tags</label><input class="settings-input" id="te-tags" value="${esc((t.tags || []).join(', '))}" placeholder="comma, separated"></div>
    <div class="te-row"><label>project</label><input class="settings-input" id="te-proj" value="${esc(t.project || '')}"></div>
    <div class="te-actions"><button class="btn" id="te-cancel">cancel</button><button class="btn primary" id="te-save">save</button></div>
  </div>`;
  document.body.appendChild(ov);
  const close = () => ov.remove();
  ov.addEventListener('click', e => { if (e.target === ov) close(); });
  ov.querySelector('#te-cancel').onclick = close;
  ov.querySelectorAll('.te-rs').forEach(b => b.addEventListener('click', async () => {
    const r = await fetch(`/api/tasks/${id}/reschedule`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ when: b.dataset.w }) }).then(r => r.json());
    if (r.due_date) ov.querySelector('#te-due').value = r.due_date.slice(0, 10);
  }));
  ov.querySelector('#te-save').onclick = async () => {
    const body = {
      title: ov.querySelector('#te-title').value.trim() || t.title,
      notes: ov.querySelector('#te-notes').value,
      priority: parseInt(ov.querySelector('#te-prio').value) || 0,
      repeat: ov.querySelector('#te-rep').value,
      due_date: ov.querySelector('#te-due').value.trim() || null,
      tags: ov.querySelector('#te-tags').value.split(',').map(s => s.trim()).filter(Boolean).join(','),
      project: ov.querySelector('#te-proj').value.trim(),
    };
    await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    close();
    loadTasks();
  };
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
    document.querySelectorAll('.tasks-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === 'active'));
  }
  await loadTasks();
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
