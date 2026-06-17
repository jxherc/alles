// re-render a finished agent run (message meta.tool_steps) back into the conversation
// on reload, matching the live streaming markup so it reuses the same CSS. Claude-Code
// flavored: a collapsible step list, each tool call showing its diff (green/red +/-)
// with a +N −N count badge.

const DESTRUCTIVE = new Set(['shell', 'bash', 'write_file', 'edit_file', 'apply_patch',
  'git_commit', 'git_push', 'revert_file', 'delete_file', 'mail_send',
  'computer_click', 'computer_type', 'computer_key', 'computer_scroll']);

function esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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

export function renderAgentSteps(steps, open = false) {
  if (!Array.isArray(steps) || !steps.length) return '';
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
    return `<div class="agent-step${destructive}${errCls}">
      <div class="agent-step-head">
        <span class="agent-step-dot"></span>
        <span class="agent-step-name">${esc(name)}</span>
        <span class="agent-step-summary">${esc(summary(name, s.args))}</span>
        ${badge}
      </div>${argsBlock}${out}${diff}
    </div>`;
  }).join('');
  const label = `agent steps · ${steps.length}${edits ? ` · ${edits} edit${edits > 1 ? 's' : ''}` : ''}`;
  return `<details class="agent-steps"${open ? ' open' : ''}><summary>${label}</summary><div class="agent-step-list">${rows}</div></details>`;
}
