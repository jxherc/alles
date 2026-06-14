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

export async function loadTasks() {
  _wireTabs();
  const r = await fetch(_tab === 'done' ? '/api/tasks/done' : '/api/tasks');
  _tasks = await r.json();
  renderTasks();
}

function renderTasks() {
  const list = document.getElementById('tasks-list');
  if (!list) return;

  if (!_tasks.length) {
    const msg = _tab === 'done' ? 'no completed tasks yet' : 'no tasks';
    list.innerHTML = `<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">${msg}</div>`;
    return;
  }

  list.innerHTML = _tasks.map(t => `
    <div class="task-item" data-id="${t.id}">
      <button class="task-check${t.done ? ' done' : ''}" data-id="${t.id}"></button>
      <span class="task-title${t.done ? ' done' : ''}">${esc(t.title)}</span>
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
  await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (_tab !== 'active') {   // jump back to active so the new task is visible
    _tab = 'active';
    document.querySelectorAll('.tasks-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === 'active'));
  }
  await loadTasks();
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
