import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';

let _projects = [];

export async function loadProjects() {
  try {
    const projects = await fetch('/api/projects').then(r => r.ok ? r.json() : []);
    _projects = Array.isArray(projects) ? projects : [];
  } catch (e) { _projects = []; }
  return _projects;
}

export function getProjects() { return _projects; }

export async function createProject(name, color = '') {
  const r = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, color }),
  });
  if (!r.ok) { toast('failed to create project', 'error'); return null; }
  const p = await r.json();
  _projects.push(p);
  return p;
}

export async function deleteProject(id) {
  await fetch(`/api/projects/${id}`, { method: 'DELETE' });
  _projects = _projects.filter(p => p.id !== id);
}

export async function assignSession(projectId, sessionId) {
  const response = await fetch(`/api/projects/${projectId}/sessions/${sessionId}`, { method: 'POST' });
  if (!response.ok) throw new Error('project assignment failed');
}

export async function unassignSession(projectId, sessionId) {
  const response = await fetch(`/api/projects/${projectId}/sessions/${sessionId}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('project unassignment failed');
}

// render project folders above the session list
export function renderProjectFolders(sessions, onSelect, onChange) {
  const list = document.getElementById('session-list');
  if (!list) return;

  const afterlife = document.body.classList.contains('afterlife-aide-projects');
  if (!_projects.length && !afterlife) return;

  let html = '';
  if (afterlife) {
    const taskSessions = sessions.filter(session => !session.project_id);
    html += `<section class="aide-session-section" data-session-drop="unassigned"><span class="section-label">tasks</span>${taskSessions.map(s => `<div class="session-item" data-id="${s.id}">
      <button type="button" class="session-open" aria-haspopup="menu" aria-current="false" aria-label="open session ${_esc(s.name)}"><span class="session-name">${_esc(s.name)}</span></button>
    </div>`).join('') || '<span class="aide-session-empty">no tasks yet</span>'}</section><span class="section-label aide-projects-label">projects</span>`;
  }
  const groups = _projects;
  for (const p of groups) {
    const pSessions = sessions.filter(s => s.project_id === p.id);
    html += `<div class="project-folder${afterlife ? ' open' : ''}" data-id="${p.id}">
  <div class="project-folder-head">
    <button type="button" class="project-folder-toggle" aria-expanded="${String(afterlife)}" aria-label="toggle project ${_esc(p.name)}">
      <svg class="project-folder-icon project-folder-closed" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 6.5h6l2-2h9v14h-17z"/></svg>
      <svg class="project-folder-icon project-folder-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8V6.5h6l2-2h5l2 3H21"/><path d="M3 9h18l-2 10H5Z"/></svg>
      <span class="project-name">${_esc(p.name)}</span>
      <span class="project-count">${pSessions.length}</span>
    </button>
    <button type="button" class="project-del" data-id="${p.id}" aria-label="delete project ${_esc(p.name)}" title="delete project (chats are kept)">×</button>
  </div>
  <div class="project-sessions" id="proj-sessions-${p.id}" style="display:${afterlife ? 'flex' : 'none'}">
    ${pSessions.map(s => `<div class="session-item" data-id="${s.id}" data-project="${p.id}">
      <button type="button" class="session-open" aria-haspopup="menu" aria-current="false" aria-label="open session ${_esc(s.name)}"><span class="session-name">${_esc(s.name)}</span></button>
    </div>`).join('')}
  </div>
</div>`;
  }

  // prepend project folders
  list.insertAdjacentHTML('afterbegin', html);

  // Project rows expand and collapse in place; their conversations stay directly below.
  list.querySelectorAll('.project-folder-toggle').forEach(toggleButton => {
    const toggle = () => {
      const folder = toggleButton.closest('.project-folder');
      const open = folder.classList.toggle('open');
      toggleButton.setAttribute('aria-expanded', String(open));
      const sessions = folder.querySelector('.project-sessions');
      if (sessions) sessions.style.display = open ? 'flex' : 'none';
    };
    toggleButton.addEventListener('click', toggle);
  });

  // drag a chat onto a project to file it there
  list.querySelectorAll('.project-folder').forEach(folder => {
    folder.addEventListener('dragover', e => { e.preventDefault(); folder.classList.add('drag-over'); });
    folder.addEventListener('dragleave', () => folder.classList.remove('drag-over'));
    folder.addEventListener('drop', async e => {
      e.preventDefault(); folder.classList.remove('drag-over');
      const sid = e.dataTransfer.getData('text/session');
      if (!sid) return;
      try {
        await assignSession(folder.dataset.id, sid);
        toast('moved to project', 'success');
        onChange?.();
      } catch {
        toast('could not move to project', 'error');
      }
    });
  });

  const taskTarget = list.querySelector('[data-session-drop="unassigned"]');
  if (taskTarget) {
    taskTarget.addEventListener('dragover', event => {
      event.preventDefault();
      taskTarget.classList.add('drag-over');
    });
    taskTarget.addEventListener('dragleave', () => taskTarget.classList.remove('drag-over'));
    taskTarget.addEventListener('drop', async event => {
      event.preventDefault();
      taskTarget.classList.remove('drag-over');
      const sessionId = event.dataTransfer.getData('text/session');
      const session = sessions.find(item => String(item.id) === String(sessionId));
      if (!session?.project_id) return;
      try {
        await unassignSession(session.project_id, sessionId);
        toast('moved to tasks', 'success');
        onChange?.();
      } catch {
        toast('could not move to tasks', 'error');
      }
    });
  }

  list.querySelectorAll('.project-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const p = _projects.find(x => x.id === btn.dataset.id);
      if (!await dlgConfirm(`delete project "${p?.name || ''}"? the chats inside are kept.`)) return;
      await deleteProject(btn.dataset.id);
      toast('project deleted', 'success');
      onChange?.();
    });
  });
}

function _esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
