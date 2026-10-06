import { toast, escapeHtml } from './util.js';
import { exportActiveSessionMarkdown, getActiveId } from './sessions.js';
import { formatTime, t } from './i18n.js';
import { confirm } from './dialog.js';
import { loadShortcuts } from './shortcuts.js';
import { createFocusBoundary } from './kokuen.js';

let _reminderPending = null;
let _reminderBusy = false;

// ── built-in command registry ────────────────────────────────────────
const BUILTINS = [
  // Aide tasks
  { name: 'new',       cat: 'aide',     help: 'start a new aide task' },
  { name: 'clear',     cat: 'aide',     help: 'clear this aide task’s message display' },
  { name: 'rename',    cat: 'aide',     help: 'rename this aide task: or auto-name if blank', args: '[name]' },
  { name: 'archive',   cat: 'aide',     help: 'archive this aide task' },
  { name: 'export',    cat: 'aide',     help: 'export this aide task as markdown' },
  { name: 'incognito', cat: 'aide',     help: 'start a new private aide task' },
  // model & persona
  { name: 'model',     cat: 'model',    help: 'open model picker' },
  { name: 'persona',   cat: 'model',    help: 'switch persona',          args: '[name]' },
  { name: 'andromeda', cat: 'search',   help: 'search the web', args: '[query]' },
  // memory
  { name: 'remember',  cat: 'memory',   help: 'save a memory',           args: '<text>' },
  { name: 'memories',  cat: 'memory',   help: 'open memory panel' },
  { name: 'forget',    cat: 'memory',   help: 'delete memory by id',     args: '<id>' },
  // productivity
  { name: 'todo',      cat: 'plan',     help: 'add a task to Plan',       args: '<task>' },
  { name: 'doc',       cat: 'docs',     help: 'create a doc',            args: '<text>' },
  // navigate (aide-only)
  { name: 'secrets',   cat: 'navigate', help: 'open secrets' },
  { name: 'compare',   cat: 'navigate', help: 'open model compare' },
  { name: 'docs',      cat: 'navigate', help: 'open docs' },
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
  document.getElementById('aide-help')?.addEventListener('click', _showHelp);
}

function _showHelp() {
  if (document.getElementById('aide-help-dialog')) return;
  _hide();
  const source = document.activeElement;
  const trigger = document.getElementById('aide-help');
  const shortcuts = loadShortcuts();
  const rows = [
    ['new_chat', 'aide.new_task'], ['search', 'common.search'],
    ['focus_input', 'aide.message_label'], ['send', 'common.send'], ['settings', 'common.settings'],
  ].filter(([key]) => shortcuts[key]);
  const guides = ['model', 'notes', 'task', 'save', 'recovery'];
  const overlay = document.createElement('div');
  overlay.className = 'dialog-overlay aide-help-overlay';
  overlay.innerHTML = `<section class="dialog-card aide-help-card" id="aide-help-dialog" role="dialog" aria-labelledby="aide-help-title">
    <header><h2 id="aide-help-title">${escapeHtml(t('aide.help_title'))}</h2><button type="button" class="icon-btn" data-help-close aria-label="${escapeHtml(t('common.close'))}">×</button></header>
    <label class="sr-only" for="aide-help-search">${escapeHtml(t('aide.help_search'))}</label>
    <input type="search" class="settings-input" id="aide-help-search" placeholder="${escapeHtml(t('aide.help_search'))}">
    <p class="aide-help-status" role="status" aria-live="polite"></p>
    <div class="aide-help-body" tabindex="0">
      <section data-help-group>
        <h3>${escapeHtml(t('aide.help_guides'))}</h3>
        <dl class="aide-help-guides">${guides.map(key => `<div data-help-entry data-help-guide="${key}"><dt>${escapeHtml(t(`aide.help_${key}_title`))}</dt><dd>${escapeHtml(t(`aide.help_${key}_body`))}</dd></div>`).join('')}</dl>
      </section>
      <section data-help-group>
        <h3>${escapeHtml(t('aide.help_shortcuts'))}</h3>
        <dl class="aide-help-shortcuts">${rows.map(([key, label]) => `<div data-help-entry><dt>${escapeHtml(t(label))}</dt><dd><kbd>${escapeHtml(shortcuts[key])}</kbd></dd></div>`).join('')}</dl>
        <p data-help-entry>${escapeHtml(t('aide.shortcut_send_tip'))}</p>
        <p data-help-entry>${escapeHtml(t('aide.shortcut_escape_tip'))}</p>
      </section>
      <section data-help-group>
        <h3>${escapeHtml(t('aide.help_commands'))}</h3>
        <p data-help-entry>${escapeHtml(t('aide.command_tip'))}</p>
        <dl class="aide-help-commands">${_allEntries().map(entry => `<div data-help-entry><dt><code>/${escapeHtml(entry.name)}${entry.args ? ' ' + escapeHtml(entry.args) : ''}</code></dt><dd>${escapeHtml(entry.description || '')}</dd></div>`).join('')}</dl>
      </section>
    </div>
    <footer><button type="button" class="btn" data-help-settings="models">${escapeHtml(t('aide.help_models'))}</button><button type="button" class="btn" data-help-settings="developer">${escapeHtml(t('aide.customize_shortcuts'))}</button></footer>
  </section>`;
  document.body.appendChild(overlay);
  const dialog = overlay.querySelector('[role="dialog"]');
  const close = () => {
    boundary.deactivate();
    boundary.destroy();
    overlay.remove();
    trigger?.setAttribute('aria-expanded', 'false');
  };
  const boundary = createFocusBoundary(dialog, { onEscape: close });
  overlay.addEventListener('keydown', event => event.stopPropagation());
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  overlay.querySelector('[data-help-close]').onclick = close;
  overlay.querySelector('#aide-help-search').addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    const entries = [...overlay.querySelectorAll('[data-help-entry]')];
    for (const entry of entries) entry.hidden = !entry.textContent.toLocaleLowerCase().includes(query);
    for (const group of overlay.querySelectorAll('[data-help-group]')) {
      group.hidden = [...group.querySelectorAll('[data-help-entry]')].every(entry => entry.hidden);
    }
    overlay.querySelector('.aide-help-status').textContent = entries.every(entry => entry.hidden) ? t('aide.help_no_matches') : '';
    overlay.querySelector('.aide-help-body').scrollTop = 0;
  });
  overlay.querySelectorAll('[data-help-settings]').forEach(button => { button.onclick = async () => {
    const pane = button.dataset.helpSettings;
    close();
    const { openSettings } = await import('./settings.js?v=289');
    if (source?.isConnected && document.activeElement === source) {
      openSettings(pane);
      if (pane === 'developer') requestAnimationFrame(() => {
        const input = document.querySelector('.shortcut-input[data-shortcut="new_chat"]');
        if (input?.offsetParent !== null) { input?.focus(); input?.scrollIntoView({ block: 'center' }); }
      });
    }
  }; });
  trigger?.setAttribute('aria-expanded', 'true');
  boundary.activate({ source, focus: overlay.querySelector('[data-help-close]') });
}

function _handleInput(ta) {
  const val = ta.value;
  const cursor = ta.selectionStart;
  const lineStart = val.lastIndexOf('\n', cursor - 1) + 1;
  const line = val.slice(lineStart, cursor);

  if (!line.startsWith('/') || line.includes(' ')) { _hide(); return; }
  const query = line.slice(1).toLowerCase();
  // show ALL when just "/" — filter when query has chars (case-insensitive, null-safe so a
  // mixed-case cookbook name / missing description still matches without throwing)
  const all = _allEntries();
  const matches = query
    ? all.filter(e => {
        const n = (e.name || '').toLowerCase(), d = (e.description || '').toLowerCase();
        return n.startsWith(query) || n.includes(query) || d.includes(query);
      })
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
        // escape — args like <task>/<text> are otherwise parsed as html tags and vanish,
        // and cookbook name/desc are user-authored (self-xss)
        const argsHtml = e.args ? `<span class="slash-args">${escapeHtml(e.args)}</span>` : '';
        const tag = e.cat === 'cookbook' ? '<span class="slash-tag">saved</span>' : '';
        html += `<div class="slash-item${flatIdx === 0 ? ' selected' : ''}" data-idx="${flatIdx}">
          <span class="slash-cmd"><span class="slash-name">/${escapeHtml(e.name)}</span>${argsHtml}</span>
          <span class="slash-desc">${escapeHtml(e.description || '')}</span>${tag}
        </div>`;
        flatIdx++;
      }
    }
    _popup.innerHTML = html;
  } else {
    // filtered mode — flat list, prefix-sorted
    _popup.innerHTML = matches.map((e, i) => {
      const argsHtml = e.args ? `<span class="slash-args">${escapeHtml(e.args)}</span>` : '';
      const tag = e.cat === 'cookbook' ? '<span class="slash-tag">saved</span>' : '';
      return `<div class="slash-item${i === 0 ? ' selected' : ''}" data-idx="${i}">
        <span class="slash-cmd"><span class="slash-name">/${escapeHtml(e.name)}</span>${argsHtml}</span>
        <span class="slash-desc">${escapeHtml(e.description || '')}</span>${tag}
      </div>`;
    }).join('');
  }

  // position above textarea, wider than textarea for cheatsheet feel
  const rect = ta.getBoundingClientRect();
  const width = Math.min(Math.max(480, rect.width), window.innerWidth - 24);
  const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
  const height = Math.min(360, Math.max(0, rect.top - 20));
  _popup.style.cssText = `bottom:${window.innerHeight - rect.top + 8}px;left:${left}px;width:${width}px;max-height:${height}px`;
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
  _popup?.querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
}

function _apply(entry, ta, lineStart, cursor) {
  // cookbook entry → insert prompt template
  if (entry.prompt !== null) {
    const before = ta.value.slice(0, lineStart);
    const after  = ta.value.slice(cursor);
    ta.value = before + entry.prompt + after;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
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

  // cookbook entries take priority over same-named builtins (cmd is already lowercased)
  const cbEntry = _cookbook.find(e => e.name.toLowerCase() === cmd);
  if (cbEntry) {
    // substitute args placeholder if present, else just use the prompt. function replacer so
    // args containing $&, $1, $` aren't treated as replacement patterns
    const expanded = cbEntry.prompt.replace(/\{args\}|\$1/g, () => args);
    if (!expanded.trim()) {
      // an args-only template invoked with no args expands to nothing — say so instead of
      // silently swallowing the send (doSend bails on an empty composer).
      toast(`/${cmd} needs an argument`, 'error');
      return true;   // handled (suppress the empty send)
    }
    const ta = document.getElementById('composer-ta');
    if (ta) {
      ta.value = expanded;
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
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
          toast('auto-name failed: add some messages first', 'error');
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

    case 'research':
    case 'andromeda': {
      if (args) window._openAndromedaQuery?.(args);
      else window._navigateTo?.('andromeda');
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
      (await import('./settings.js?v=289')).openSettings('memory');
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

    case 'doc':
    case 'note': {
      if (!args) { toast(`/${cmd} requires text`, 'error'); return true; }
      const r = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: args.slice(0, 60), content: args }),
      });
      if (r.ok) toast('doc created', 'success');
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
        toast('incognito session: nothing will be saved');
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
              if (window._currentSession) window._currentSession.persona_id = match.id;
              window._refreshPersonaBtn?.();   // updates the label + applies the persona's accent
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

    case 'secrets':
      document.querySelector('.nav-item[data-view="vault"]')?.click();
      return true;

    case 'compare':
      window._navigateTo?.('compare');
      return true;

    case 'docs':
    case 'vault':
      document.querySelector('.nav-item[data-view="wiki"]')?.click();
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
      toast('context compaction is automatic: happens when context exceeds threshold');
      return true;

    case 'remind':
    case 'send': {
      if (_reminderBusy) return 'keep-draft';
      _reminderBusy = true;
      try {
        const { parseReminderTime, reminderRequest, createReminder, reminderMayHaveSaved } = await import('./reminders.js?v=243');
        const type = cmd === 'send' ? 'message' : 'reminder';
        const sessionId = getActiveId();
        const command = `/${cmd} ${args}`;
        if (_reminderPending && (_reminderPending.command !== command || _reminderPending.sessionId !== sessionId)) {
          if (!await confirm('the previous reminder may already be saved. discard its retry and create this one?')) return 'keep-draft';
          _reminderPending = null;
        }
        if (!_reminderPending) {
          const patterns = [
            /^(in\s+\d+\s*(?:m(?:in)?|h(?:r|our)?|d(?:ay)?))\s+(.+)$/i,
            /^((?:(?:today|tomorrow)\s+)?at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.+)$/i,
          ];
          const match = patterns.map(pattern => args.match(pattern)).find(Boolean);
          const triggerAt = match && parseReminderTime(match[1]);
          if (!triggerAt) {
            toast(`use /${cmd} in 2h <text> or /${cmd} at 3pm <text> with a valid time`, 'error');
            return 'keep-draft';
          }
          _reminderPending = { command, sessionId, request: reminderRequest(match[2], triggerAt, type, type === 'message' ? sessionId : null), uncertain: false };
        }
        try {
          const result = await createReminder(_reminderPending.request);
          const when = formatTime(new Date(_reminderPending.request.trigger_at), { hour: '2-digit', minute: '2-digit' });
          _reminderPending = null;
          toast(result.fired ? 'reminder already delivered' : type === 'message' ? `scheduled for ${when}` : `reminder set for ${when}`, 'success');
          return true;
        } catch (error) {
          _reminderPending.uncertain ||= reminderMayHaveSaved(error);
          if (!_reminderPending.uncertain) _reminderPending = null;
          toast(`${error.message || 'could not save reminder'}${_reminderPending ? '. send this command again to confirm the same reminder.' : ''}`, 'error');
          return 'keep-draft';
        }
      } finally { _reminderBusy = false; }
    }

    case 'reminders':
      document.querySelector('.nav-item[data-view="aide-reminders"]')?.click();
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
        md += entries.map(e => `- \`/${e.name}${e.args ? ' ' + e.args : ''}\`: ${e.description}`).join('\n');
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
