import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';

let _projects = [];
let _jarvisRuns = [];

export async function loadProjects() {
  try {
    const [projects, runs] = await Promise.all([
      fetch('/api/projects').then(r => r.ok ? r.json() : []),
      document.body.classList.contains('afterlife-aide-projects')
        ? fetch('/api/jarvis/runs?limit=8').then(r => r.ok ? r.json() : []).catch(() => [])
        : Promise.resolve([]),
    ]);
    _projects = Array.isArray(projects) ? projects : [];
    _jarvisRuns = Array.isArray(runs) ? runs : [];
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

  const afterlife = document.body.classList.contains('afterlife-aide-projects');
  if (!_projects.length && !afterlife) return;

  let html = '';
  const groups = afterlife ? [{ id: 'general', name: 'General', color: '', folder_state: 'none' }, ..._projects] : _projects;
  for (const p of groups) {
    const general = p.id === 'general';
    const pSessions = sessions.filter(s => general ? !s.project_id : s.project_id === p.id);
    const dot = p.color ? `background:${p.color}` : '';
    const state = general ? 'no folder' : ({ available: 'available', missing: 'folder missing', relink_required: 'relink required' }[p.folder_state] || 'relink required');
    html += `<div class="project-folder" data-id="${p.id}">
  <div class="project-folder-head" role="button" tabindex="0" aria-label="open project ${_esc(p.name)}">
    <span class="project-dot" style="${dot}"></span>
    <span class="project-name">${_esc(p.name)}<small class="project-state ${_esc(p.folder_state || '')}">${state}</small></span>
    <span class="project-count">${pSessions.length}</span>
    ${general ? '' : `<button class="project-del" data-id="${p.id}" title="delete project (chats are kept)">×</button>`}
  </div>
  <div class="project-sessions" id="proj-sessions-${p.id}" style="display:${afterlife ? 'flex' : 'none'}">
    ${pSessions.map(s => `<div class="session-item" data-id="${s.id}" data-project="${p.id}">
      <div class="session-dot"></div>
      <span class="session-name">${_esc(s.name)}</span>
    </div>`).join('')}
  </div>
</div>`;
  }
  if (afterlife && _jarvisRuns.length) {
    html += `<div class="aide-runs"><span class="section-label">jarvis</span>${_jarvisRuns.map(run => `<div class="aide-run" data-state="${_esc(run.state)}"><span class="session-dot"></span><span>${_esc(run.result_summary || 'jarvis task')}</span><small>${_esc(run.state.replaceAll('_', ' '))}</small></div>`).join('')}</div>`;
  }

  // prepend project folders
  list.insertAdjacentHTML('afterbegin', html);

  // General starts a no-folder chat; folder Projects keep their existing workspace page.
  list.querySelectorAll('.project-folder-head').forEach(head => {
    const open = () => {
      const id = head.closest('.project-folder').dataset.id;
      if (id === 'general') window._newGeneralChat?.();
      else window._openProject?.(id);
    };
    head.addEventListener('click', open);
    head.addEventListener('keydown', e => {
      if (e.target !== head) return;
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      open();
    });
  });

  // drag a chat onto a project to file it there
  list.querySelectorAll('.project-folder').forEach(folder => {
    folder.addEventListener('dragover', e => { e.preventDefault(); folder.classList.add('drag-over'); });
    folder.addEventListener('dragleave', () => folder.classList.remove('drag-over'));
    folder.addEventListener('drop', async e => {
      e.preventDefault(); folder.classList.remove('drag-over');
      const sid = e.dataTransfer.getData('text/session');
      if (!sid) return;
      if (folder.dataset.id === 'general') {
        const source = sessions.find(session => session.id === sid)?.project_id;
        if (source) await fetch(`/api/projects/${source}/sessions/${sid}`, { method: 'DELETE' });
      } else {
        await assignSession(folder.dataset.id, sid);
      }
      toast('moved to project', 'success');
      onChange?.();
    });
  });

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
