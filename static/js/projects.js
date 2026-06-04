import { toast } from './util.js';

let _projects = [];

export async function loadProjects() {
  try {
    const r = await fetch('/api/projects');
    _projects = await r.json();
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
  await fetch(`/api/projects/${projectId}/sessions/${sessionId}`, { method: 'POST' });
}

export async function unassignSession(projectId, sessionId) {
  await fetch(`/api/projects/${projectId}/sessions/${sessionId}`, { method: 'DELETE' });
}

// render project folders above the session list
export function renderProjectFolders(sessions, onSelect) {
  const list = document.getElementById('session-list');
  if (!list) return;

  // only inject if there are projects
  const projectSessions = sessions.filter(s => s.project_id);
  if (!_projects.length) return;

  let html = '';
  for (const p of _projects) {
    const pSessions = sessions.filter(s => s.project_id === p.id);
    const dot = p.color ? `background:${p.color}` : '';
    html += `<div class="project-folder" data-id="${p.id}">
  <div class="project-folder-head">
    <span class="project-dot" style="${dot}"></span>
    <span class="project-name">${_esc(p.name)}</span>
    <span class="project-count">${pSessions.length}</span>
  </div>
  <div class="project-sessions" id="proj-sessions-${p.id}" style="display:none">
    ${pSessions.map(s => `<div class="session-item" data-id="${s.id}" data-project="${p.id}">
      <div class="session-dot"></div>
      <span class="session-name">${_esc(s.name)}</span>
    </div>`).join('')}
  </div>
</div>`;
  }

  // prepend project folders
  list.insertAdjacentHTML('afterbegin', html);

  // wire toggles + clicks
  list.querySelectorAll('.project-folder-head').forEach(head => {
    head.addEventListener('click', () => {
      const body = head.nextElementSibling;
      body.style.display = body.style.display === 'none' ? 'flex' : 'none';
      head.parentElement.classList.toggle('open');
    });
  });

  if (onSelect) {
    list.querySelectorAll('.session-item[data-project]').forEach(el => {
      el.addEventListener('click', () => onSelect(el.dataset.id));
    });
  }
}

function _esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
