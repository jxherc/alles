// agent runs drawer — browse past runs + see what the agent actually touched.
// the run logs already live on disk (data/agent_runs/*.json); this just surfaces
// them so an autonomous agent is inspectable instead of a black box.
import { toast } from './util.js';
import { t as tr, tp as trp } from './i18n.js';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const ago = iso => {
  if (!iso) return '';
  const s = (Date.now() - Date.parse(iso + (iso.endsWith('Z') ? '' : 'Z'))) / 1000;
  if (isNaN(s)) return '';
  if (s < 60) return tr('aide.run_just_now');
  if (s < 3600) return trp('aide.run_minutes_ago', Math.floor(s / 60));
  if (s < 86400) return trp('aide.run_hours_ago', Math.floor(s / 3600));
  return trp('aide.run_days_ago', Math.floor(s / 86400));
};

const STATUS_ICON = { done: 'check', running: 'refresh', interrupted: 'pause', turn_limit: 'none', stopped: 'stop', error: 'x-circle' };
// read out for the status icon; an unknown status falls back to its own words
const STATUS_LABEL = {
  done: () => tr('aide.run_status_done'),
  running: () => tr('aide.run_status_running'),
  interrupted: () => tr('aide.run_status_interrupted'),
  turn_limit: () => tr('aide.run_status_turn_limit'),
  stopped: () => tr('aide.run_status_stopped'),
  error: () => tr('aide.run_status_error'),
};
const statusLabel = status => status ? (STATUS_LABEL[status]?.() ?? String(status).replace(/_/g, ' ')) : tr('common.unknown');

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
  body.innerHTML = `<div class="runs-empty">${esc(tr('aide.loading'))}</div>`;
  let runs;
  try { runs = await fetch('/api/agent/runs?summary=1&limit=40').then(r => r.json()); }
  catch { body.innerHTML = `<div class="runs-empty">${esc(tr('aide.run_load_failed'))}</div>`; return; }
  if (!Array.isArray(runs) || !runs.length) {
    body.innerHTML = `<div class="runs-empty">${esc(tr('aide.run_empty'))}</div>`;
    return;
  }
  body.innerHTML = runs.map(rowHtml).join('');
  body.querySelectorAll('.run-row').forEach(r => r.addEventListener('click', () => toggleDetail(r, r.dataset.id)));
}

function rowHtml(r) {
  const prog = r.todos_total ? ` · ${tr('aide.run_todos', { done: r.todos_done, total: r.todos_total })}` : '';
  const edits = r.edits ? ` · ${trp('aide.run_edits', r.edits)}` : '';
  return `<div class="run-row" data-id="${esc(r.id)}">
    <div class="run-row-head">
      <span class="run-status run-${esc(r.status)}" role="img" aria-label="${esc(statusLabel(r.status))}" title="${esc(r.status)}">${_si(STATUS_ICON[r.status] || 'clock')}</span>
      <span class="run-model">${esc(r.model || tr('aide.run_agent'))}</span>
      <span class="run-time">${esc(ago(r.updated_at || r.started_at))}</span>
    </div>
    <div class="run-row-sub">${trp('aide.run_steps', r.steps)}${prog}${edits}${r.todo ? `: ${esc(r.todo)}` : ''}</div>
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
  box.innerHTML = `<div class="runs-empty">${esc(tr('aide.loading'))}</div>`;
  let run, src;
  try {
    [run, src] = await Promise.all([
      fetch(`/api/agent/runs/${id}`).then(r => r.json()),
      fetch(`/api/agent/runs/${id}/sources`).then(r => r.json()),
    ]);
  } catch { box.innerHTML = `<div class="runs-empty">${esc(tr('aide.run_detail_failed'))}</div>`; return; }
  box.dataset.loaded = '1';
  box.innerHTML = detailHtml(run, src, id);
  box.querySelector('[data-revert]')?.addEventListener('click', async e => {
    e.stopPropagation();
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = tr('aide.run_reverting');
    try {
      const r = await fetch(`/api/agent/runs/${id}/revert`, { method: 'POST' }).then(x => x.json());
      btn.textContent = trp('aide.run_reverted', r.restored || 0);
      toast(trp('aide.run_reverted_files', r.restored || 0), 'success');
    } catch { btn.textContent = tr('aide.run_revert_failed'); toast(tr('aide.run_revert_failed'), 'error'); }
  });
}

export function sourcesHtml(src) {
  if (!src || !Array.isArray(src.sources) || !src.outcomes) {
    return `<p class="run-src-none">${esc(tr('aide.run_sources_unavailable'))}</p>`;
  }
  const toolName = name => String(name || tr('aide.run_tool')).replaceAll('_', ' ');
  const reference = item => {
    const path = item.path || (item.kind === 'doc' ? item.ref : '');
    const label = item.label || path || item.url || item.ref || toolName(item.tool);
    let href = '', external = false;
    if (path && ['document', 'doc'].includes(item.kind)) {
      href = `/?app=docs&doc=${encodeURIComponent(path)}`;
      if (/^[a-f0-9]{64}$/.test(item.hash || '')) href += `&doc_hash=${encodeURIComponent(item.hash)}`;
    } else if (item.kind === 'read' && /^[a-zA-Z0-9_-]{1,160}$/.test(item.ref || '')) {
      href = `/?app=read&record_view=read&record=${encodeURIComponent(item.ref)}`;
      if (/^[a-f0-9]{64}$/.test(item.hash || '')) href += `&record_hash=${encodeURIComponent(item.hash)}`;
    } else if (item.kind === 'url') {
      try {
        const url = new URL(item.url);
        if (['https:', 'http:'].includes(url.protocol)) { href = url.href; external = true; }
      } catch { /* an unavailable or invalid destination stays readable */ }
    }
    const version = /^[a-f0-9]{64}$/.test(item.hash || '') ? ` · ${esc(tr('aide.run_read_version'))}` : '';
    const text = `${esc(label)}${version}`;
    return href ? `<a class="run-src-item" href="${esc(href)}"${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${text}</a>`
      : `<span class="run-src-item">${text}</span>`;
  };
  const section = (label, items) => items.length
    ? `<div class="run-src-group"><span class="run-src-label">${esc(label)}</span>${items.join('')}</div>` : '';
  const reads = src.sources.filter(item => item.kind !== 'search');
  const searches = src.sources.filter(item => item.kind === 'search');
  let out = section(tr('aide.run_confirmed_reads'), reads.map(reference));
  for (const search of searches) {
    const results = Array.isArray(search.results) ? search.results : [];
    out += section(tr('aide.run_search_results'), [
      `<span class="run-src-item">${esc(toolName(search.tool))}: ${esc(search.query)} · ${esc(trp('aide.run_saved_references', results.length))}</span>`,
      ...results.map(reference),
    ]);
  }
  out += section(tr('aide.run_other_tools'), (src.actions || []).map(action =>
    `<span class="run-src-item">${esc(toolName(action.tool))}${action.path || action.command ? `: ${esc(action.path || action.command)}` : ''}</span>`));
  const { failed = 0, unfinished = 0, unknown = 0 } = src.outcomes;
  const pending = [failed && trp('aide.run_failed_or_denied', failed), unfinished && trp('aide.run_without_result', unfinished), unknown && trp('aide.run_unknown_outcome', unknown)].filter(Boolean);
  if (!out) out = `<p class="run-src-none">${esc(tr('aide.run_no_sources'))}</p>`;
  if (pending.length) out += `<p class="run-src-none">${esc(pending.join(' · '))}</p>`;
  if (!src.history_complete) out += `<p class="run-src-none">${esc(tr('aide.run_history_incomplete'))}</p>`;
  return out + `<p class="run-src-none">${esc(tr('aide.run_sources_note'))}</p>`;
}

function detailHtml(run, src, id) {
  const todos = (run.todos || []).map(t => {
    // producer emits {step, status: pending|in_progress|completed}; tolerate legacy text/done too
    const done = t.status === 'completed' || t.status === 'done';
    return `<div class="run-todo ${done ? 'done' : ''}">${_si(done ? 'check-circle' : 'circle')}${done ? `<span class="sr-only">${esc(tr('aide.run_todo_done'))}</span>` : ''} ${esc(t.step || t.text || t.title || '')}</div>`;
  }).join('');
  const steps = (run.tool_steps || []).slice(-12).map(s =>
    `<span class="run-step ${s.error ? 'err' : ''}" title="${esc(s.output || '')}">${esc(s.name || s.tool || tr('aide.run_tool'))}</span>`).join('');
  const editN = (run.checkpoints || []).length;
  return `
    ${todos ? `<div class="run-d-block">${todos}</div>` : ''}
    ${steps ? `<div class="run-d-block run-steps">${steps}</div>` : ''}
    <div class="run-d-block">${sourcesHtml(src)}</div>
    ${editN ? `<button class="btn run-revert" data-revert>${esc(trp('aide.run_revert_edits', editN))}</button>` : ''}`;
}
