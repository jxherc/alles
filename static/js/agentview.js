// re-render a finished agent run (message meta.tool_steps) back into the conversation
// on reload, matching the live streaming markup so it reuses the same CSS. Claude-Code
// flavored: a collapsible step list, each tool call showing its diff (green/red +/-)
// with a +N −N count badge.

const DESTRUCTIVE = new Set(['shell', 'bash', 'write_file', 'edit_file', 'apply_patch',
  'git_commit', 'git_push', 'revert_file', 'delete_file', 'mail_send',
  'computer_click', 'computer_type', 'computer_key', 'computer_scroll']);

// one mark per kind of step, the same set the code view uses
const MARKS = {
  file: '<path d="M6 3.5h8l4 4v13H6Z"/><path d="M14 3.5v4h4"/>',
  newfile: '<path d="M6 3.5h8l4 4v13H6Z"/><path d="M12 11v6m-3-3h6"/>',
  pencil: '<path d="m4 20 1-4L16 5l3 3L8 19Z"/><path d="m14 7 3 3"/>',
  terminal: '<path d="M3.5 5.5h17v13h-17Z"/><path d="m7 10 2.5 2L7 14m4.5 0H15"/>',
  search: '<path d="M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Zm4.5-1.5 5 5"/>',
  globe: '<path d="M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z"/><path d="M3.5 12h17M12 3.5c2.5 2.5 2.5 14.5 0 17M12 3.5c-2.5 2.5-2.5 14.5 0 17"/>',
  list: '<path d="M8 7h12M8 12h12M8 17h12M4 7h.01M4 12h.01M4 17h.01"/>',
  memory: '<path d="M12 4.5a4 4 0 0 0-4 4v1a3 3 0 0 0 0 6 4 4 0 0 0 8 0 3 3 0 0 0 0-6v-1a4 4 0 0 0-4-4Z"/>',
  tool: '<path d="M14.5 6.5a4 4 0 0 0-5.4 5.1L4 16.7 7.3 20l5.1-5.1a4 4 0 0 0 5.1-5.4l-2.4 2.4-2.6-.6-.6-2.6Z"/>',
};
const KIND = {
  read_file: 'file', docs_read: 'file', note_read: 'file',
  write_file: 'newfile', docs_write: 'newfile', note_write: 'newfile', note_append: 'newfile',
  edit_file: 'pencil', apply_patch: 'pencil', revert_file: 'pencil',
  shell: 'terminal', bash: 'terminal', pi_run: 'terminal',
  web_search: 'search', grep_files: 'search', glob_files: 'search', docs_search: 'search',
  web_fetch: 'globe', list_files: 'list', memory_search: 'memory', memory_add: 'memory',
};
export function stepMark(name) {
  return `<span class="agent-step-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${MARKS[KIND[name] || 'tool']}</svg></span>`;
}
export function stepKind(name) { return KIND[name] || 'tool'; }

// a saved doc gets a card that opens it, so the answer is one click from the file
const DOC_WRITERS = new Set(['docs_write', 'note_write', 'note_append']);
// pi's saved docs, from the "saved doc:" lines of a handed-over run
export function piDocReceipts(output = '', error = false) {
  if (error) return '';
  return [...String(output).matchAll(/^\s*saved doc: (.+)$/gm)].map(m => docReceipt('docs_write', { path: m[1].trim() })).join('');
}
export function docReceipt(name, args = {}, error = false) {
  const path = String(args?.path || '').trim();
  if (!DOC_WRITERS.has(name) || error || !path) return '';
  const title = path.split('/').pop().replace(/\.md$/i, '');
  return `<button type="button" class="doc-receipt" data-open-doc="${esc(path)}">
    <span class="doc-receipt-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${MARKS.file}</svg></span>
    <span class="doc-receipt-text"><span class="doc-receipt-title">${esc(title)}</span><span class="doc-receipt-where">saved in docs · open</span></span>
  </button>`;
}
// one listener for every receipt, live or reloaded
if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-open-doc]');
    if (!button) return;
    event.preventDefault();
    window._openSearchResult?.('note', button.dataset.openDoc);
  });
}

export function canRevertTool(name) {
  return ['write_file', 'edit_file', 'apply_patch'].includes(name);
}

function esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function summary(name, a = {}) {
  const cut = (s, n = 70) => String(s || '').replace(/\s+/g, ' ').slice(0, n);
  switch (name) {
    case 'read_file': return `read ${a.path || ''}`;
    case 'write_file': return `write ${a.path || ''}`;
    case 'edit_file': return `edit ${a.path || ''}`;
    case 'apply_patch': return 'apply a patch';
    case 'shell': case 'bash': return `run: ${cut(a.command, 90)}`;
    case 'grep_files': return `grep "${cut(a.pattern, 40)}"`;
    case 'glob_files': return `glob ${a.pattern || ''}`;
    case 'list_files': return `list ${a.path || '.'}`;
    case 'web_search': return `search: ${cut(a.query, 50)}`;
    case 'web_fetch': return `fetch ${cut(a.url, 60)}`;
    case 'pi_run': return `hand to pi: ${cut(a.task, 110)}`;
    default: { const v = Object.values(a).find(x => typeof x === 'string' && x.length < 80); return v ? `${name}: ${cut(v)}` : name; }
  }
}

function counts(diff) {
  let add = 0, del = 0;
  for (const ln of String(diff).split('\n')) {
    if (ln.startsWith('+') && !ln.startsWith('+++')) add++;
    else if (ln.startsWith('-') && !ln.startsWith('---')) del++;
  }
  return { add, del };
}

export function renderDiff(diff = '') {
  return String(diff).split('\n').map(line => {
    let cls = '';
    if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add';
    else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-del';
    else if (line.startsWith('@@')) cls = 'diff-hunk';
    else if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ')) cls = 'diff-meta';
    return `<span class="${cls}">${esc(line)}</span>`;
  }).join('\n');
}

// a question aide asked you is a step for people, not a tool dump: no args or json, and skipping
// it is your answer, not a failure
function asQuestion(step) {
  if ((step?.name || step?.tool) !== 'ask_user') return step;
  let cancelled = false;
  try { cancelled = JSON.parse(String(step.output || '{}'))?.cancelled === true; } catch {}
  return { ...step, error: cancelled ? false : step.error, args: {}, output: '', _question: cancelled ? 'you skipped this question' : (step.args?.title || 'asked you a question') };
}

export function renderAgentSteps(steps, open = false, agentRunId = '') {
  if (!Array.isArray(steps) || !steps.length) return '';
  steps = steps.map(asQuestion);
  open = open || steps.some(step => step?.error || step?.completed === false);
  let edits = 0;
  const rows = steps.map(s => {
    const name = s.name || s.tool || 'tool';
    const destructive = DESTRUCTIVE.has(name) ? ' destructive' : '';
    const errCls = s.error ? ' error' : '';
    let badge = '';
    if (s.diff) {
      edits++;
      const c = counts(s.diff);
      badge = `<span class="agent-step-counts"><span class="diff-add">+${c.add}</span> <span class="diff-del">−${c.del}</span></span>`;
    }
    const argsBlock = (s.args && Object.keys(s.args).length)
      ? `<details class="agent-step-args-wrap"><summary>args</summary><pre class="agent-step-args">${esc(JSON.stringify(s.args, null, 2))}</pre></details>` : '';
    const out = s.output ? `<pre class="agent-step-output">${esc(String(s.output).slice(-4000))}</pre>` : '';
    const diff = s.diff ? `<pre class="agent-step-diff">${renderDiff(s.diff)}</pre>` : '';
    return `<div class="agent-step${destructive}${errCls}" data-kind="${stepKind(name)}">
      <div class="agent-step-head">
        <span class="agent-step-dot"></span>${stepMark(name)}
        <span class="agent-step-name">${esc(s._question ? 'question' : name)}</span>
        <span class="agent-step-summary">${esc(s._question || summary(name, s.args))}</span>
        ${s.completed === false ? '<span class="agent-step-summary">no final result</span>' : ''}
        ${badge}
      </div>${argsBlock}${out}${diff}
    </div>`;
  }).join('');
  const detail = `${steps.length} step${steps.length === 1 ? '' : 's'}${edits ? ` · ${edits} edit${edits > 1 ? 's' : ''}` : ''}`;
  const runId = String(agentRunId || '').trim();
  const reversible = steps.some(step => step.diff && canRevertTool(step.name || step.tool));
  const controls = runId ? `<span class="agent-run-controls">
    <button type="button" class="agent-sources-btn" data-agent-sources="${esc(runId)}" aria-expanded="false" title="confirmed reads, search results and tool outcomes">sources</button>
    ${reversible ? `<button type="button" class="agent-revert-btn" data-agent-revert="${esc(runId)}" title="restore every file this run changed">revert edits</button>` : ''}
  </span>` : '';
  const failed = steps.filter(step => step?.error).length;
  const dots = `<span class="agent-steps-dots" aria-hidden="true">${steps.slice(-24).map(step => `<span class="${step?.error ? 'failed' : 'done'}"></span>`).join('')}</span>`;
  const receipts = steps.map(step => (step.name || step.tool) === 'pi_run'
    ? piDocReceipts(step.output, !!step.error)
    : docReceipt(step.name || step.tool, step.args, !!step.error)).join('');
  return `<details class="agent-steps"${open ? ' open' : ''}><summary>${detail}${failed ? ` · ${failed} failed` : ''}${dots}${controls}</summary><div class="agent-step-list">${rows}</div></details>${receipts}`;
}

export function wireAgentRunControls(root) {
  root?.querySelectorAll?.('[data-agent-sources]').forEach(button => {
    if (button.dataset.wired) return;
    button.dataset.wired = '1';
    let panel = null;
    button.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      if (button.getAttribute('aria-disabled') === 'true') return;
      if (panel && !panel.hidden) { panel.hidden = true; button.setAttribute('aria-expanded', 'false'); return; }
      button.setAttribute('aria-disabled', 'true');
      button.textContent = 'loading sources…';
      try {
        const response = await fetch(`/api/agent/runs/${encodeURIComponent(button.dataset.agentSources)}/sources`);
        if (!response.ok) throw new Error('sources unavailable');
        const { sourcesHtml } = await import('./runs.js');
        const sources = await response.json();
        if (!Array.isArray(sources?.sources) || !sources.outcomes) throw new Error('sources unavailable');
        if (!button.isConnected) return;
        panel ||= document.createElement('div');
        panel.className = 'agent-sources';
        panel.innerHTML = sourcesHtml(sources);
        panel.hidden = false;
        const details = button.closest('.agent-steps');
        if (details) {
          details.open = true;
          details.appendChild(panel);
        }
        button.textContent = 'sources';
        button.setAttribute('aria-expanded', 'true');
      } catch {
        button.textContent = 'retry sources';
        button.setAttribute('aria-expanded', 'false');
      } finally {
        button.removeAttribute('aria-disabled');
      }
    });
  });
  root?.querySelectorAll?.('[data-agent-revert]').forEach(button => {
    if (button.dataset.wired) return;
    button.dataset.wired = '1';
    button.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      button.textContent = 'reverting…';
      try {
        const response = await fetch(`/api/agent/runs/${encodeURIComponent(button.dataset.agentRevert)}/revert`, { method: 'POST' });
        if (!response.ok) throw new Error('revert failed');
        const result = await response.json();
        button.textContent = `reverted ${result.restored || 0}`;
      } catch {
        button.textContent = 'revert failed';
        button.disabled = false;
      }
    });
  });
}
