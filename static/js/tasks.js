import { toast } from './util.js';

let _tasks = [];
let _tab = 'active';   // 'active' | 'done' (history)
let _tabsWired = false;

function _wireTabs() {
  if (_tabsWired) return; _tabsWired = true;
  document.querySelectorAll('.tasks-tab').forEach(b => b.addEventListener('click', () => {
    _tab = b.dataset.tab;
    document.querySelectorAll('.tasks-tab').forEach(x => x.classList.toggle('active', x === b));
    loadTasks();
  }));
}

const _URL = { active: '/api/tasks', done: '/api/tasks/done',
               today: '/api/tasks/views/today', upcoming: '/api/tasks/views/upcoming',
               someday: '/api/tasks/views/someday' };

export async function loadTasks() {
  _wireTabs();
  const r = await fetch(_URL[_tab] || '/api/tasks');
  _tasks = await r.json();
  renderTasks();
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

function renderTasks() {
  const list = document.getElementById('tasks-list');
  if (!list) return;

  if (!_tasks.length) {
    const msg = _tab === 'done' ? 'no completed tasks yet' : 'nothing here';
    list.innerHTML = `<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">${msg}</div>`;
    return;
  }

  list.innerHTML = _tasks.map(t => `
    <div class="task-item" data-id="${t.id}">
      <button class="task-check${t.done ? ' done' : ''}" data-id="${t.id}"></button>
      <span class="task-title${t.done ? ' done' : ''}">${esc(t.title)}</span>
      ${t.repeat ? `<span class="task-repeat" title="repeats ${t.repeat}">🔁</span>` : ''}
      ${_dueBadge(t.due_date)}
      ${(t.tags || []).map(g => `<span class="task-tag">#${esc(g)}</span>`).join('')}
      ${t.priority ? '<span class="task-high">high</span>' : ''}
      <button class="task-del" data-id="${t.id}">×</button>
    </div>`).join('');

  list.querySelectorAll('.task-check').forEach(btn => {
    btn.addEventListener('click', async () => {
      const t = _tasks.find(x => x.id === btn.dataset.id);
      await fetch(`/api/tasks/${btn.dataset.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ done: !t.done }),
      });
      await loadTasks();
    });
  });

  list.querySelectorAll('.task-del').forEach(btn => {
    btn.addEventListener('click', async () => {
      await fetch(`/api/tasks/${btn.dataset.id}`, { method: 'DELETE' });
      await loadTasks();
    });
  });
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
