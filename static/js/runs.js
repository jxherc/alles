// agent runs drawer — browse past runs + see what the agent actually touched.
// the run logs already live on disk (data/agent_runs/*.json); this just surfaces
// them so an autonomous agent is inspectable instead of a black box.
import { toast } from './util.js';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const ago = iso => {
  if (!iso) return '';
  const s = (Date.now() - Date.parse(iso + (iso.endsWith('Z') ? '' : 'Z'))) / 1000;
  if (isNaN(s)) return '';
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

const STATUS = { done: '✓', running: '⟳', interrupted: '◷', turn_limit: '⊘', stopped: '■', error: '✕' };

let _wired = false;
export function initRuns() {
  if (_wired) return;
  _wired = true;
  $('runs-btn')?.addEventListener('click', openRuns);
  $('runs-close')?.addEventListener('click', closeRuns);
  $('runs-scrim')?.addEventListener('click', closeRuns);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('runs-drawer')?.hidden) closeRuns(); });
}

function closeRuns() { $('runs-drawer').hidden = true; $('runs-scrim').hidden = true; }

export async function openRuns() {
  initRuns();
  const d = $('runs-drawer'), scrim = $('runs-scrim'), body = $('runs-drawer-body');
  d.hidden = false; scrim.hidden = false;
  body.innerHTML = '<div class="runs-empty">loading…</div>';
  let runs;
  try { runs = await fetch('/api/agent/runs?summary=1&limit=40').then(r => r.json()); }
  catch { body.innerHTML = '<div class="runs-empty">couldn’t load runs</div>'; return; }
  if (!Array.isArray(runs) || !runs.length) {
    body.innerHTML = '<div class="runs-empty">no agent runs yet — they show up here once the agent does something</div>';
    return;
  }
  body.innerHTML = runs.map(rowHtml).join('');
  body.querySelectorAll('.run-row').forEach(r => r.addEventListener('click', () => toggleDetail(r, r.dataset.id)));
}

function rowHtml(r) {
  const prog = r.todos_total ? ` · ${r.todos_done}/${r.todos_total} todos` : '';
  const edits = r.edits ? ` · ${r.edits} edit${r.edits > 1 ? 's' : ''}` : '';
  return `<div class="run-row" data-id="${esc(r.id)}">
    <div class="run-row-head">
      <span class="run-status run-${esc(r.status)}" title="${esc(r.status)}">${STATUS[r.status] || '·'}</span>
      <span class="run-model">${esc(r.model || 'agent')}</span>
      <span class="run-time">${esc(ago(r.updated_at || r.started_at))}</span>
    </div>
    <div class="run-row-sub">${r.steps} step${r.steps === 1 ? '' : 's'}${prog}${edits}${r.todo ? ` — ${esc(r.todo)}` : ''}</div>
    <div class="run-detail" hidden></div>
  </div>`;
}

async function toggleDetail(row, id) {
  const box = row.querySelector('.run-detail');
  if (!box.hidden) { box.hidden = true; return; }
  // collapse siblings
  row.parentElement.querySelectorAll('.run-detail').forEach(b => { if (b !== box) b.hidden = true; });
  box.hidden = false;
  if (box.dataset.loaded) return;
  box.innerHTML = '<div class="runs-empty">loading…</div>';
  let run, src;
  try {
    [run, src] = await Promise.all([
      fetch(`/api/agent/runs/${id}`).then(r => r.json()),
      fetch(`/api/agent/runs/${id}/sources`).then(r => r.json()),
    ]);
  } catch { box.innerHTML = '<div class="runs-empty">failed to load detail</div>'; return; }
  box.dataset.loaded = '1';
  box.innerHTML = detailHtml(run, src, id);
  box.querySelector('[data-revert]')?.addEventListener('click', async e => {
    e.stopPropagation();
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = 'reverting…';
    try {
      const r = await fetch(`/api/agent/runs/${id}/revert`, { method: 'POST' }).then(x => x.json());
      btn.textContent = `reverted ${r.restored || 0}`;
      toast(`reverted ${r.restored || 0} file(s)`, 'success');
    } catch { btn.textContent = 'revert failed'; toast('revert failed', 'error'); }
  });
}

export function sourcesHtml(src) {
  if (!src) return '';
  const section = (label, items, cls = '') => items?.length
    ? `<div class="run-src-group"><span class="run-src-label">${label}</span>${items.map(x => `<span class="run-src-item ${cls}">${esc(x)}</span>`).join('')}</div>`
    : '';
  const out = section('files', src.files) + section('urls', src.urls, 'mono')
    + section('searches', src.searches) + section('commands', src.commands, 'mono');
  return out || '<div class="run-src-none">nothing external touched</div>';
}

function detailHtml(run, src, id) {
  const todos = (run.todos || []).map(t =>
    `<div class="run-todo ${t.status === 'done' ? 'done' : ''}">${t.status === 'done' ? '✓' : '○'} ${esc(t.text || t.title || '')}</div>`).join('');
  const steps = (run.tool_steps || []).slice(-12).map(s =>
    `<span class="run-step ${s.error ? 'err' : ''}" title="${esc(s.output || '')}">${esc(s.name || s.tool || 'tool')}</span>`).join('');
  const editN = (run.checkpoints || []).length;
  return `
    ${todos ? `<div class="run-d-block">${todos}</div>` : ''}
    ${steps ? `<div class="run-d-block run-steps">${steps}</div>` : ''}
    <div class="run-d-block">${sourcesHtml(src)}</div>
    ${editN ? `<button class="btn run-revert" data-revert>revert ${editN} edit${editN > 1 ? 's' : ''}</button>` : ''}`;
}
