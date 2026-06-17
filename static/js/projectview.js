// project workspace page — open a project to see its chats, its files (working dir),
// standing instructions, and notes. notebook-lm-ish: a home base per project.
import { toast } from './util.js';
import { getProjects, loadProjects } from './projects.js';
import { selectSession, loadSessions } from './sessions.js';

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function _patch(pid, body) {
  return fetch(`/api/projects/${pid}`, {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  }).catch(() => {});
}

export async function renderProject(pid) {
  const view = document.getElementById('project-view');
  if (!view) return;
  view.innerHTML = '<div class="page-view-body"><div class="settings-row-empty">loading…</div></div>';

  let proj = getProjects().find(p => p.id === pid);
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
      <button class="btn primary" id="pj-newchat" style="margin-left:auto;font-size:0.72rem">+ new chat</button>
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
          <div class="s-card-head">files <span class="pj-hint">— the project's working directory</span></div>
          <div class="s-card-body">
            <input class="settings-input" id="pj-wd" placeholder="working directory path (e.g. C:/Users/jxh/myproj)" value="${esc(proj.working_dir || '')}" style="width:100%;margin-bottom:0.55rem">
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
          <div class="s-card-head">notes <span class="pj-hint">— scratchpad, links, commands</span></div>
          <div class="s-card-body"><textarea class="settings-textarea" id="pj-desc" rows="6" placeholder="anything you want to keep with this project…">${esc(proj.description || '')}</textarea></div>
        </div>
      </div>
    </div>`;

  view.querySelectorAll('.pj-chat').forEach(el =>
    el.addEventListener('click', () => selectSession(el.dataset.id)));

  view.querySelector('#pj-newchat')?.addEventListener('click', async () => {
    const r = await fetch('/api/sessions', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'new chat' }) });
    if (!r.ok) { toast('failed to start chat', 'error'); return; }
    const s = await r.json();
    await fetch(`/api/projects/${pid}/sessions/${s.id}`, { method: 'POST' });
    await loadSessions();
    selectSession(s.id);
  });

  const debounceSave = (el, field, after) => {
    if (!el) return;
    let t; el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(async () => { await _patch(pid, { [field]: el.value }); after?.(); }, 500); });
  };
  debounceSave(view.querySelector('#pj-sys'), 'system_prompt');
  debounceSave(view.querySelector('#pj-desc'), 'description');
  debounceSave(view.querySelector('#pj-wd'), 'working_dir', () => _loadFiles(pid));

  _loadFiles(pid);
}

async function _loadFiles(pid) {
  const box = document.getElementById('pj-files');
  if (!box) return;
  const d = await fetch(`/api/projects/${pid}/files`).then(r => r.json()).catch(() => ({ files: [] }));
  if (!d.working_dir) { box.innerHTML = '<div class="settings-row-empty">set a working directory to list its files</div>'; return; }
  const files = d.files || [];
  if (!files.length) { box.innerHTML = '<div class="settings-row-empty">no files found in that directory</div>'; return; }
  box.innerHTML = files.map(f => `<div class="pj-file" title="${esc(f)}">${esc(f)}</div>`).join('');
}
