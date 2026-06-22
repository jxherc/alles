import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';

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

// render project folders above the session list
export function renderProjectFolders(sessions, onSelect, onChange) {
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
    <button class="project-del" data-id="${p.id}" title="delete project (chats are kept)">×</button>
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

  // clicking a project opens its workspace page (not just a toggle)
  list.querySelectorAll('.project-folder-head').forEach(head => {
    head.addEventListener('click', () => window._openProject?.(head.closest('.project-folder').dataset.id));
  });

  // drag a chat onto a project to file it there
  list.querySelectorAll('.project-folder').forEach(folder => {
    folder.addEventListener('dragover', e => { e.preventDefault(); folder.classList.add('drag-over'); });
    folder.addEventListener('dragleave', () => folder.classList.remove('drag-over'));
    folder.addEventListener('drop', async e => {
      e.preventDefault(); folder.classList.remove('drag-over');
      const sid = e.dataTransfer.getData('text/session');
      if (!sid) return;
      await assignSession(folder.dataset.id, sid);
      toast('moved to project', 'success');
      onChange?.();
    });
  });

  if (onSelect) {
    list.querySelectorAll('.session-item[data-project]').forEach(el => {
      el.addEventListener('click', () => onSelect(el.dataset.id));
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
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
