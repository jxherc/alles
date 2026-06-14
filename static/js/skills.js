// skills — manage reusable procedures (SKILL.md on disk) that the agent can
// discover + load. master/detail: pick from the list, edit on the right.
import { toast } from './util.js';
import { confirm as dlgConfirm } from './dialog.js';

let _built = false;
let _cur = null;            // slug being edited, or null for a new one

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const $ = id => document.getElementById(id);

async function _api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}

export function initSkills() {
  const body = $('skills-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="skills-wrap">
        <div class="skills-side">
          <input id="skl-search" class="settings-input" placeholder="search skills…">
          <button class="btn" id="skl-new" style="width:100%;margin:0.5rem 0">+ new skill</button>
          <div id="skl-list" class="skl-list"></div>
        </div>
        <div class="skills-main">
          <div class="s-field"><label>name</label><input id="skl-name" class="settings-input" placeholder="e.g. PDF form filler"></div>
          <div class="s-field"><label>description</label><input id="skl-desc" class="settings-input" placeholder="one line — what it does"></div>
          <div class="s-field"><label>when to use</label><input id="skl-when" class="settings-input" placeholder="the trigger — when the agent should reach for this"></div>
          <div class="s-field"><label>procedure (markdown)</label><textarea id="skl-bodytext" class="settings-textarea" rows="14" placeholder="the steps, in plain markdown…"></textarea></div>
          <div class="skl-actions">
            <button class="btn primary" id="skl-save">save</button>
            <button class="btn danger" id="skl-del" style="display:none">delete</button>
            <span id="skl-status" class="skl-status"></span>
          </div>
        </div>
      </div>`;
    $('skl-new').onclick = () => _editNew();
    $('skl-save').onclick = _save;
    $('skl-del').onclick = _delete;
    let t;
    $('skl-search').oninput = e => { clearTimeout(t); t = setTimeout(() => _loadList(e.target.value), 200); };
    _built = true;
  }
  _editNew();
  _loadList('');
}

async function _loadList(q) {
  const el = $('skl-list');
  if (!el) return;
  let skills;
  try { skills = await _api('/api/skills' + (q ? `?q=${encodeURIComponent(q)}` : '')); }
  catch { el.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>'; return; }
  if (!skills.length) {
    el.innerHTML = `<div class="skl-empty">${q ? 'no matches' : 'no skills yet — make one the agent can reuse'}</div>`;
    return;
  }
  el.innerHTML = skills.map(s => `
    <div class="skl-row${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
      <div class="skl-row-name">${esc(s.name)}</div>
      <div class="skl-row-desc">${esc(s.description) || '<em>no description</em>'}</div>
    </div>`).join('');
  el.querySelectorAll('.skl-row').forEach(r => r.onclick = () => _open(r.dataset.slug));
}

function _editNew() {
  _cur = null;
  $('skl-name').value = '';
  $('skl-desc').value = '';
  $('skl-when').value = '';
  $('skl-bodytext').value = '';
  $('skl-del').style.display = 'none';
  $('skl-status').textContent = '';
  document.querySelectorAll('.skl-row.active').forEach(r => r.classList.remove('active'));
}

async function _open(slug) {
  let s;
  try { s = await _api(`/api/skills/${encodeURIComponent(slug)}`); }
  catch { toast('failed to open skill', 'error'); return; }
  _cur = s.slug;
  $('skl-name').value = s.name || '';
  $('skl-desc').value = s.description || '';
  $('skl-when').value = s.when_to_use || '';
  $('skl-bodytext').value = s.body || '';
  $('skl-del').style.display = '';
  $('skl-status').textContent = '';
  document.querySelectorAll('.skl-row').forEach(r => r.classList.toggle('active', r.dataset.slug === slug));
}

async function _save() {
  const name = $('skl-name').value.trim();
  if (!name) { toast('give the skill a name', 'error'); return; }
  const payload = {
    name,
    description: $('skl-desc').value.trim(),
    when_to_use: $('skl-when').value.trim(),
    body: $('skl-bodytext').value,
  };
  try {
    const res = _cur
      ? await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })
      : await _api('/api/skills', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    _cur = res.slug;
    $('skl-del').style.display = '';
    $('skl-status').textContent = 'saved';
    setTimeout(() => { if ($('skl-status')) $('skl-status').textContent = ''; }, 1500);
    toast('skill saved', 'success');
    _loadList($('skl-search').value);
  } catch (e) { toast('save failed: ' + e.message, 'error'); }
}

async function _delete() {
  if (!_cur) return;
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    _editNew();
    _loadList($('skl-search').value);
  } catch { toast('delete failed', 'error'); }
}
