import { toast } from './util.js';
import { exportActiveSessionMarkdown } from './sessions.js';

// ── built-in command registry ────────────────────────────────────────
const BUILTINS = [
  // chats
  { name: 'new',       cat: 'chats',    help: 'start a new chat' },
  { name: 'clear',     cat: 'chats',    help: 'clear chat display' },
  { name: 'rename',    cat: 'chats',    help: 'rename — or auto-name if blank', args: '[name]' },
  { name: 'archive',   cat: 'chats',    help: 'archive this chat' },
  { name: 'export',    cat: 'chats',    help: 'export chat as markdown' },
  { name: 'incognito', cat: 'chats',    help: 'start a new incognito chat' },
  // model & persona
  { name: 'model',     cat: 'model',    help: 'open model picker' },
  { name: 'persona',   cat: 'model',    help: 'switch persona',          args: '[name]' },
  // mode
  { name: 'research',  cat: 'mode',     help: 'toggle research mode' },
  { name: 'agent',     cat: 'mode',     help: 'toggle agent mode' },
  { name: 'bg',        cat: 'mode',     help: 'run an agent task in the background', args: '<task>' },
  // memory
  { name: 'remember',  cat: 'memory',   help: 'save a memory',           args: '<text>' },
  { name: 'memories',  cat: 'memory',   help: 'open memory panel' },
  { name: 'forget',    cat: 'memory',   help: 'delete memory by id',     args: '<id>' },
  // productivity
  { name: 'todo',      cat: 'tasks',    help: 'add a task',              args: '<task>' },
  { name: 'note',      cat: 'notes',    help: 'create a note',           args: '<text>' },
  // navigate (aide-only)
  { name: 'vault',     cat: 'navigate', help: 'open vault' },
  { name: 'compare',   cat: 'navigate', help: 'open model compare' },
  { name: 'docs',      cat: 'navigate', help: 'open document editor' },
  { name: 'contacts',  cat: 'navigate', help: 'open contacts' },
  { name: 'search',    cat: 'navigate', help: 'open search',             args: '[query]' },
  // system
  { name: 'system',    cat: 'system',   help: 'set session system prompt', args: '<prompt>' },
  { name: 'backup',    cat: 'system',   help: 'download backup zip' },
  { name: 'compact',   cat: 'system',   help: 'compact context now' },
  { name: 'help',      cat: 'system',   help: 'list all slash commands' },
  // scheduling
  { name: 'remind',    cat: 'schedule', help: 'set a reminder', args: '<in 2h|at 3pm> <text>' },
  { name: 'send',      cat: 'schedule', help: 'schedule a message to AI', args: '<in 2h|at 3pm> <text>' },
  { name: 'reminders', cat: 'schedule', help: 'view scheduled reminders & messages' },
];

// cookbook entries from API
let _cookbook = [];

async function _fetchCookbook() {
  try {
    const r = await fetch('/api/cookbook');
    _cookbook = await r.json();
  } catch (e) { _cookbook = []; }
}

function _allEntries() {
  const builtins = BUILTINS.map(b => ({
    name: b.name, description: b.help,
    prompt: null,   // null = action command
    cat: b.cat, args: b.args || '',
  }));
  const cookbook = _cookbook.map(c => ({
    name: c.name, description: c.description,
    prompt: c.prompt,
    cat: 'cookbook', args: '',
  }));
  return [...builtins, ...cookbook];
}


// ── autocomplete UI ──────────────────────────────────────────────────

let _popup = null;
let _selectedIdx = 0;
let _currentMatches = [];

export function initSlash(ta) {
  _fetchCookbook();
  ta.addEventListener('input', () => _handleInput(ta));
  ta.addEventListener('keydown', e => _handleKey(e, ta));
  ta.addEventListener('blur', () => setTimeout(_hide, 150));
  ta.addEventListener('focus', _fetchCookbook);
}

function _handleInput(ta) {
  const val = ta.value;
  const cursor = ta.selectionStart;
  const lineStart = val.lastIndexOf('\n', cursor - 1) + 1;
  const line = val.slice(lineStart, cursor);

  if (!line.startsWith('/') || line.includes(' ')) { _hide(); return; }
  const query = line.slice(1).toLowerCase();
  // show ALL when just "/" — filter when query has chars
  const all = _allEntries();
  const matches = query
    ? all.filter(e => e.name.startsWith(query) || e.name.includes(query) || e.description.includes(query))
    : all;
  if (!matches.length) { _hide(); return; }
  _show(matches, ta, lineStart, cursor, !query);
}

function _show(matches, ta, lineStart, cursor, grouped = false) {
  _hide();
  _selectedIdx = 0;
  _currentMatches = matches;

  _popup = document.createElement('div');
  _popup.className = 'slash-popup slash-cheatsheet';

  if (grouped) {
    // group by category — cheatsheet mode
    const cats = {};
    for (const e of matches) (cats[e.cat] = cats[e.cat] || []).push(e);
    let flatIdx = 0;
    let html = '';
    for (const [cat, entries] of Object.entries(cats)) {
      html += `<div class="slash-cat-label">${cat}</div>`;
      for (const e of entries) {
        const argsHtml = e.args ? `<span class="slash-args">${e.args}</span>` : '';
        const tag = e.cat === 'cookbook' ? '<span class="slash-tag">saved</span>' : '';
        html += `<div class="slash-item${flatIdx === 0 ? ' selected' : ''}" data-idx="${flatIdx}">
          <span class="slash-cmd"><span class="slash-name">/${e.name}</span>${argsHtml}</span>
          <span class="slash-desc">${e.description}</span>${tag}
        </div>`;
        flatIdx++;
      }
    }
    _popup.innerHTML = html;
  } else {
    // filtered mode — flat list, prefix-sorted
    _popup.innerHTML = matches.map((e, i) => {
      const argsHtml = e.args ? `<span class="slash-args">${e.args}</span>` : '';
      const tag = e.cat === 'cookbook' ? '<span class="slash-tag">saved</span>' : '';
      return `<div class="slash-item${i === 0 ? ' selected' : ''}" data-idx="${i}">
        <span class="slash-cmd"><span class="slash-name">/${e.name}</span>${argsHtml}</span>
        <span class="slash-desc">${e.description}</span>${tag}
      </div>`;
    }).join('');
  }

  // position above textarea, wider than textarea for cheatsheet feel
  const rect = ta.getBoundingClientRect();
  const width = Math.max(480, rect.width);
  const left  = Math.min(rect.left, window.innerWidth - width - 12);
  _popup.style.cssText = `bottom:${window.innerHeight - rect.top + 8}px;left:${left}px;width:${width}px`;
  document.body.appendChild(_popup);

  _popup.querySelectorAll('.slash-item').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault();
      _apply(matches[+el.dataset.idx], ta, lineStart, cursor);
    });
  });
}

function _hide() { _popup?.remove(); _popup = null; _currentMatches = []; }

function _handleKey(e, ta) {
  if (!_popup) return;
  const m = _currentMatches;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _selectedIdx = Math.min(_selectedIdx + 1, m.length - 1);
    _updateSelected();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _selectedIdx = Math.max(_selectedIdx - 1, 0);
    _updateSelected();
  } else if (e.key === 'Tab') {
    e.preventDefault();
    const ls = ta.value.lastIndexOf('\n', ta.selectionStart - 1) + 1;
    _apply(m[_selectedIdx], ta, ls, ta.selectionStart);
  } else if (e.key === 'Escape') {
    _hide();
  }
}

function _updateSelected() {
  _popup?.querySelectorAll('.slash-item').forEach((el, i) =>
    el.classList.toggle('selected', i === _selectedIdx));
}

function _apply(entry, ta, lineStart, cursor) {
  // cookbook entry → insert prompt template
  if (entry.prompt !== null) {
    const before = ta.value.slice(0, lineStart);
    const after  = ta.value.slice(cursor);
    ta.value = before + entry.prompt + after;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
    ta.focus();
    const pos = lineStart + entry.prompt.length;
    ta.setSelectionRange(pos, pos);
  } else {
    // builtin → insert command token so user can add args
    const token = '/' + entry.name + (entry.args ? ' ' : '');
    const before = ta.value.slice(0, lineStart);
    const after  = ta.value.slice(cursor);
    ta.value = before + token + after;
    ta.style.height = 'auto';
    ta.focus();
    const pos = lineStart + token.length;
    ta.setSelectionRange(pos, pos);
  }
  _hide();
}


// ── command execution ────────────────────────────────────────────────
// Called from app.js doSend() before sending to LLM.
// Returns true if the command was handled (suppress LLM send).

export async function tryExecuteSlashCommand(text) {
  if (!text.startsWith('/')) return false;
  const parts = text.trim().split(/\s+/);
  const cmd  = parts[0].slice(1).toLowerCase();
  const args = parts.slice(1).join(' ').trim();

  // cookbook entries take priority over same-named builtins
  const cbEntry = _cookbook.find(e => e.name === cmd);
  if (cbEntry) {
    // substitute args placeholder if present, else just use the prompt
    const ta = document.getElementById('composer-ta');
    if (ta) {
      ta.value = cbEntry.prompt.replace(/\{args\}|\$1/g, args);
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
    }
    return false;  // let normal send handle it with substituted text
  }

  switch (cmd) {
    case 'new': {
      const { newChat } = await import('./sessions.js');
      newChat();   // fresh chat, created on first send
      return true;
    }

    case 'clear': {
      const container = document.getElementById('messages');
      if (container) container.innerHTML = '';
      return true;
    }

    case 'rename': {
      const { getActiveId, updateSessionName } = await import('./sessions.js');
      const sid = getActiveId();
      if (!sid) return true;
      if (args) {
        await fetch(`/api/sessions/${sid}`, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name: args }),
        });
        updateSessionName(sid, args);
        toast(`renamed to "${args}"`, 'success');
      } else {
        // no args — let the LLM auto-name from history
        toast('auto-naming…');
        const r = await fetch(`/api/sessions/${sid}/auto-name`, { method: 'POST' });
        if (r.ok) {
          const { name } = await r.json();
          updateSessionName(sid, name);
          toast(`renamed to "${name}"`, 'success');
        } else {
          toast('auto-name failed — add some messages first', 'error');
        }
      }
      return true;
    }

    case 'archive': {
      const { getActiveId, loadSessions } = await import('./sessions.js');
      const sid = getActiveId();
      if (!sid) return true;
      await fetch(`/api/sessions/${sid}/archive`, { method: 'POST' });
      await loadSessions();
      toast('archived', 'success');
      return true;
    }

    case 'export': {
      await exportActiveSessionMarkdown();
      return true;
    }

    case 'model': {
      document.getElementById('model-btn')?.click();
      return true;
    }

    case 'research': {
      document.getElementById('research-toggle-btn')?.click();
      return true;
    }

    case 'agent': {
      // always agent — open the agent panel in settings
      document.querySelector('.nav-item[data-view="brain"]')?.click();
      return true;
    }

    case 'bg':
    case 'background': {
      if (!args) { toast('usage: /bg <task>', 'error'); return true; }
      const { getActiveId, createSession, markActive, appendUserMsg, showMessages } = await import('./sessions.js');
      const { getCurrentEndpoint, getSelected } = await import('./models.js');
      let sid = getActiveId();
      if (!sid) {
        const ep = getCurrentEndpoint();
        if (!ep) { toast('no endpoint configured', 'error'); return true; }
        const sm = getSelected()?.model || ep.models?.[0] || '';
        const s = await createSession(sm, ep.id);
        if (!s) { toast('failed to create session', 'error'); return true; }
        sid = s.id; markActive(sid);
      }
      showMessages();
      appendUserMsg(args + '  ·(background)');
      const r = await fetch('/api/agent/background', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ session_id: sid, message: args, mode: 'agent' }),
      });
      if (r.ok) { toast('running in background — keep working'); _pollBackground(sid); }
      else toast('background start failed', 'error');
      return true;
    }

    case 'remember': {
      if (!args) { toast('/remember requires text', 'error'); return true; }
      const r = await fetch('/api/memories', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: args }),
      });
      if (r.ok) toast('memory saved', 'success');
      return true;
    }

    case 'memories': {
      document.querySelector('.nav-item[data-view="memory"]')?.click();
      return true;
    }

    case 'forget': {
      if (!args) { toast('/forget requires a memory id', 'error'); return true; }
      const r = await fetch(`/api/memories/${args}`, { method: 'DELETE' });
      if (r.ok) toast('memory deleted', 'success');
      else toast('memory not found', 'error');
      return true;
    }

    case 'todo': {
      if (!args) { toast('/todo requires a task', 'error'); return true; }
      const r = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: args }),
      });
      if (r.ok) toast('task added', 'success');
      return true;
    }

    case 'note': {
      if (!args) { toast('/note requires text', 'error'); return true; }
      const r = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: args.slice(0, 60), content: args }),
      });
      if (r.ok) toast('note created', 'success');
      return true;
    }

    case 'incognito': {
      const { createSession } = await import('./sessions.js');
      const { getCurrentEndpoint, getSelected } = await import('./models.js');
      const ep = getCurrentEndpoint();
      if (!ep) { toast('no endpoint configured', 'error'); return true; }
      const model = getSelected()?.model || ep.models?.[0] || '';
      const r = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model, endpoint_id: ep.id, incognito: true, name: 'incognito' }),
      });
      if (r.ok) {
        const s = await r.json();
        const { loadSessions, selectSession } = await import('./sessions.js');
        await loadSessions();
        await selectSession(s.id);
        toast('incognito session — nothing will be saved');
      }
      return true;
    }

    case 'persona': {
      if (args) {
        // try to match by name
        const r = await fetch('/api/personas');
        if (r.ok) {
          const personas = await r.json();
          const match = personas.find(p => p.name.toLowerCase().includes(args.toLowerCase()));
          if (match) {
            const { getActiveId } = await import('./sessions.js');
            const sid = getActiveId();
            if (sid) {
              await fetch(`/api/sessions/${sid}`, {
                method: 'PATCH',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ persona_id: match.id }),
              });
              toast(`persona: ${match.name}`, 'success');
            }
          } else {
            toast(`no persona matching "${args}"`, 'error');
          }
        }
      } else {
        document.getElementById('persona-btn')?.click();
      }
      return true;
    }

    case 'vault':
      document.querySelector('.nav-item[data-view="vault"]')?.click();
      return true;

    case 'compare':
      document.querySelector('.nav-item[data-view="compare"]')?.click();
      return true;

    case 'docs':
      document.querySelector('.nav-item[data-view="docs"]')?.click();
      return true;

    case 'contacts':
      document.querySelector('.nav-item[data-view="contacts"]')?.click();
      return true;

    case 'search': {
      const { openSearch } = await import('./search.js');
      openSearch();
      if (args) {
        setTimeout(() => {
          const inp = document.getElementById('search-input');
          if (inp) { inp.value = args; inp.dispatchEvent(new Event('input')); }
        }, 50);
      }
      return true;
    }

    case 'system': {
      if (!args) { toast('/system requires a prompt', 'error'); return true; }
      const { getActiveId } = await import('./sessions.js');
      const sid = getActiveId();
      // store as session-level override in a meta patch
      // for now just save as global setting with toast hint
      const r = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ system_prompt: args }),
      });
      if (r.ok) toast('system prompt updated', 'success');
      return true;
    }

    case 'backup':
      window.location = '/api/backup';
      return true;

    case 'compact':
      toast('context compaction is automatic — happens when context exceeds threshold');
      return true;

    case 'remind':
    case 'send': {
      // usage: /remind in 2h <text>  OR  /remind at 3pm <text>
      const { parseReminderTime, createReminder } = await import('./reminders.js');
      const timePatterns = [
        /^(in\s+\d+\s*(?:m(?:in)?|h(?:r|our)?|d(?:ay)?))\s+(.+)$/i,
        /^((?:today\s+)?at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.+)$/i,
        /^(tomorrow\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.+)$/i,
      ];
      let timePart = null, textPart = null;
      for (const pat of timePatterns) {
        const m = args.match(pat);
        if (m) { timePart = m[1]; textPart = m[2]; break; }
      }
      if (!timePart || !textPart) {
        toast(`usage: /${cmd} in 2h <text> OR /${cmd} at 3pm <text>`, 'error');
        return true;
      }
      const triggerAt = parseReminderTime(timePart);
      if (!triggerAt) { toast('could not parse time', 'error'); return true; }
      const type = cmd === 'send' ? 'message' : 'reminder';
      const sessionId = type === 'message' ? (window._currentSession?.id || null) : null;
      await createReminder(textPart, triggerAt, type, sessionId);
      const when = triggerAt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
      toast(type === 'message' ? `scheduled for ${when}` : `reminder set for ${when}`, 'success');
      return true;
    }

    case 'reminders':
      document.querySelector('.nav-item[data-view="reminders"]')?.click();
      return true;

    case 'help': {
      const { showMessages, createStreamingAiRow } = await import('./sessions.js');
      const { mdToHtml } = await import('./util.js');
      showMessages();
      const { body } = createStreamingAiRow();
      const cats = {};
      for (const e of _allEntries()) {
        (cats[e.cat] = cats[e.cat] || []).push(e);
      }
      let md = '**slash commands**\n\n';
      for (const [cat, entries] of Object.entries(cats)) {
        md += `*${cat}*\n`;
        md += entries.map(e => `- \`/${e.name}${e.args ? ' ' + e.args : ''}\` — ${e.description}`).join('\n');
        md += '\n\n';
      }
      const content = document.createElement('div');
      content.className = 'ai-content';
      content.innerHTML = mdToHtml(md);
      body.appendChild(content);
      body.classList.add('done');
      return true;
    }

    default:
      return false;
  }
}

// poll a background run; when it finishes, refresh the session if it's open
function _pollBackground(sid) {
  let tries = 0;
  const iv = setInterval(async () => {
    if (++tries > 200) { clearInterval(iv); return; }   // ~10 min cap
    let runs = [];
    try { runs = await fetch('/api/agent/runs?limit=12').then(r => r.json()); } catch { return; }
    const run = (runs || [])
      .filter(r => r.session_id === sid)
      .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))[0];
    if (run && run.status !== 'running') {
      clearInterval(iv);
      const { getActiveId, selectSession } = await import('./sessions.js');
      if (getActiveId() === sid) await selectSession(sid);
      toast(`background run ${run.status}`, run.status === 'error' ? 'error' : 'success');
    }
  }, 3000);
}
