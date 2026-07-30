// project workspace page — open a project to see its chats, its files (working dir),
// standing instructions, and notes. notebook-lm-ish: a home base per project.
import { toast } from './util.js';
import { prompt as dlgPrompt } from './dialog.js';
import { getProjects, loadProjects } from './projects.js';
import { projectFolderMessage } from './projectenv.js';
import { selectSession, loadSessions } from './sessions.js';

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function _patch(pid, body) {
  return fetch(`/api/projects/${pid}`, {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  }).catch(() => {});
}

async function _fetchWithRecentOwner(input, init) {
  let response = await fetch(input, init);
  if (response.status !== 403) return response;
  const me = await fetch('/api/auth/me').then(r => r.json()).catch(() => null);
  if (me?.enabled === false) return response;
  const password = await dlgPrompt('enter your Alles password to change the Project folder', '', { secret: true });
  if (password == null) return response;
  const confirmed = await fetch('/api/auth/reauth', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password }),
  });
  if (!confirmed.ok) { toast('password confirmation failed', 'error'); return response; }
  return fetch(input, init);
}

export async function renderProject(pid) {
  const view = document.getElementById('project-view');
  if (!view) return;
  view.innerHTML = '<div class="page-view-body"><div class="settings-row-empty">loading…</div></div>';

  let proj = await fetch(`/api/projects/${pid}/open`, { method: 'POST' }).then(r => r.ok ? r.json() : null).catch(() => null);
  if (!proj) { await loadProjects(); proj = getProjects().find(p => p.id === pid); }
  if (!proj) { view.innerHTML = '<div class="page-view-body"><div class="settings-row-empty">project not found</div></div>'; return; }

  // /api/sessions is grouped {today, yesterday, earlier} — flatten then filter
  const g = await fetch('/api/sessions').then(r => r.json()).catch(() => ({}));
  const all = [...(g.today || []), ...(g.yesterday || []), ...(g.earlier || [])];
  const mine = all.filter(s => s.project_id === pid);
  const dot = proj.color ? ` style="background:${esc(proj.color)}"` : '';

  view.innerHTML = `
    <div class="page-view-head">
      <span class="project-dot"${dot}></span>
      <span class="page-view-title">${esc(proj.name)}</span>
      <button class="btn primary" id="pj-newchat" style="margin-left:auto;font-size:0.75rem">+ new chat</button>
    </div>
    <div class="page-view-body project-workspace">
      <div class="pj-col">
        <div class="s-card">
          <div class="s-card-head">chats · ${mine.length}</div>
          <div class="s-card-body" id="pj-chats">${mine.length
            ? mine.map(s => `<div class="pj-chat" data-id="${s.id}"><span class="session-dot"></span>${esc(s.name || 'untitled')}</div>`).join('')
            : '<div class="settings-row-empty">no chats yet — start one, or drag a chat onto this project</div>'}</div>
        </div>
        <div class="s-card">
          <div class="s-card-head">files <span class="pj-hint">— the Project's server folder</span></div>
          <div class="s-card-body">
            <div class="settings-row-empty" id="pj-folder-state">${esc(projectFolderMessage(proj.folder_state))}</div>
            <div style="display:flex;gap:0.45rem;margin-bottom:0.55rem">
              <input class="settings-input" id="pj-wd" aria-label="Project server folder" placeholder="absolute folder path on this server" value="${esc(proj.working_dir || '')}" style="min-width:0;flex:1">
              <button class="btn" id="pj-relink">${proj.folder_state === 'available' ? 'change folder' : 'relink folder'}</button>
            </div>
            <div id="pj-files" class="pj-files"></div>
          </div>
        </div>
      </div>
      <div class="pj-col">
        <div class="s-card">
          <div class="s-card-head">instructions <span class="pj-hint">— context for this project's chats</span></div>
          <div class="s-card-body"><textarea class="settings-textarea" id="pj-sys" rows="7" placeholder="e.g. You're helping me build X. Prefer Y. Always…">${esc(proj.system_prompt || '')}</textarea></div>
        </div>
        <div class="s-card">
          <div class="s-card-head">scratchpad <span class="pj-hint">— links, commands, and working notes</span></div>
          <div class="s-card-body"><textarea class="settings-textarea" id="pj-scratch" rows="6" placeholder="anything you want to keep with this Project…">${esc(proj.scratchpad || '')}</textarea></div>
        </div>
      </div>
    </div>`;

  view.querySelectorAll('.pj-chat').forEach(el =>
    el.addEventListener('click', () => selectSession(el.dataset.id)));

  view.querySelector('#pj-newchat')?.addEventListener('click', async () => {
    const r = await fetch('/api/sessions', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'new chat', project_id: pid }) });
    if (!r.ok) { toast('failed to start chat', 'error'); return; }
    const s = await r.json();
    await loadSessions();
    selectSession(s.id);
  });

  const debounceSave = (el, field, after) => {
    if (!el) return;
    let t; el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(async () => { await _patch(pid, { [field]: el.value }); after?.(); }, 500); });
  };
  debounceSave(view.querySelector('#pj-sys'), 'system_prompt');
  debounceSave(view.querySelector('#pj-scratch'), 'scratchpad');
  const relink = async () => {
    const input = view.querySelector('#pj-wd');
    const value = input?.value.trim() || '';
    if (!value) { toast('enter an absolute folder path on the server', 'error'); input?.focus(); return; }
    const response = await _fetchWithRecentOwner(`/api/projects/${pid}/relink`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ working_dir: value }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { toast(data.detail || 'Project folder could not be changed', 'error'); input?.focus(); return; }
    proj = data;
    input.value = data.working_dir;
    view.querySelector('#pj-folder-state').textContent = projectFolderMessage(data.folder_state);
    view.querySelector('#pj-relink').textContent = 'change folder';
    toast('Project folder linked', 'success');
    _loadFiles(pid);
  };
  view.querySelector('#pj-relink')?.addEventListener('click', relink);
  view.querySelector('#pj-wd')?.addEventListener('keydown', e => { if (e.key === 'Enter') relink(); });

  _loadFiles(pid);
}

async function _loadFiles(pid) {
  const box = document.getElementById('pj-files');
  if (!box) return;
  const d = await fetch(`/api/projects/${pid}/files`).then(r => r.json()).catch(() => ({ files: [] }));
  if (d.folder_state === 'missing') { box.innerHTML = '<div class="settings-row-empty">folder missing — relink it above</div>'; return; }
  if (!d.working_dir) { box.innerHTML = '<div class="settings-row-empty">choose a server folder to list its files</div>'; return; }
  const files = d.files || [];
  if (!files.length) { box.innerHTML = '<div class="settings-row-empty">no files found in that directory</div>'; return; }
  box.innerHTML = files.map(f => `<div class="pj-file" title="${esc(f)}">${esc(f)}</div>`).join('');
}
