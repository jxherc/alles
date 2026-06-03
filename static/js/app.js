import { loadSessions, showWelcome, createSession, renderSidebar } from './sessions.js';
import { loadModels, renderModelList, addEndpoint, getSelected, getCurrentEndpoint } from './models.js';
import { sendMessage, stopStream } from './chat.js';
import { toast, closeAllModals, mdToHtml } from './util.js';
import { initMemoryPanel } from './memory.js';
import { runResearch, setResearchMode, isResearchMode } from './research.js';
import { loadNotes, newNote } from './notes.js';
import { loadTasks, addTask } from './tasks.js';

window._mdToHtml = mdToHtml;

// ── init ─────────────────────────────────────────────────────────────────────

async function init() {
  await loadModels();
  await loadSessions();
  bindEvents();
}
init();


// ── views ─────────────────────────────────────────────────────────────────────

const _allViews = ['chat', 'notes', 'tasks', 'memory'];

function hideAllViews() {
  document.getElementById('chat').style.display = 'none';
  document.getElementById('notes-view').style.display = 'none';
  document.getElementById('tasks-view').style.display = 'none';
  document.getElementById('mem-view').style.display = 'none';
  document.getElementById('composer-outer').style.display = 'none';
}

function showChatView() {
  hideAllViews();
  document.getElementById('chat').style.display = 'flex';
  document.getElementById('composer-outer').style.display = 'block';
  setNav('chat');
}

function showNotesView() {
  hideAllViews();
  document.getElementById('notes-view').style.display = 'flex';
  setNav('notes');
  loadNotes();
}

function showTasksView() {
  hideAllViews();
  document.getElementById('tasks-view').style.display = 'flex';
  setNav('tasks');
  loadTasks();
}

function showMemoryView() {
  hideAllViews();
  document.getElementById('mem-view').style.display = 'flex';
  setNav('memory');
  initMemoryPanel();
}

function setNav(view) {
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.view === view);
  });
}


// ── events ────────────────────────────────────────────────────────────────────

function bindEvents() {
  const ta = document.getElementById('composer-ta');
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  document.getElementById('send-btn').addEventListener('click', doSend);
  document.getElementById('stop-btn').addEventListener('click', stopStream);

  document.getElementById('new-chat-btn').addEventListener('click', async () => {
    const ep = getCurrentEndpoint();
    const s = await createSession(getSelected()?.model || '', ep?.id || '');
    if (s) {
      showChatView();
      const { selectSession } = await import('./sessions.js');
      await selectSession(s.id);
    }
  });

  document.getElementById('session-search').addEventListener('input', e => {
    renderSidebar(e.target.value);
  });

  // research toggle
  document.getElementById('research-toggle-btn').addEventListener('click', () => {
    const on = !isResearchMode();
    setResearchMode(on);
    document.getElementById('research-toggle-btn').classList.toggle('active', on);
    ta.placeholder = on ? 'research a topic...' : 'message aide...';
  });

  // shell button — opens a quick shell prompt
  document.getElementById('shell-btn-tool').addEventListener('click', openShellPrompt);

  // mode toggle
  document.getElementById('mode-agent').addEventListener('click', () => setMode('agent'));
  document.getElementById('mode-chat').addEventListener('click', () => setMode('chat'));

  document.getElementById('theme-btn').addEventListener('click', toggleTheme);

  // model picker
  document.getElementById('model-btn').addEventListener('click', openModelModal);
  document.getElementById('model-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('model-search-input').addEventListener('input', e => renderModelList(e.target.value));

  document.getElementById('ep-add-btn').addEventListener('click', async () => {
    const name = document.getElementById('ep-name').value.trim();
    const url  = document.getElementById('ep-url').value.trim();
    const key  = document.getElementById('ep-key').value.trim();
    if (!name || !url) { toast('name and url required', 'error'); return; }
    try {
      await addEndpoint(name, url, key);
      ['ep-name','ep-url','ep-key'].forEach(id => document.getElementById(id).value = '');
      toast('endpoint added', 'success');
      renderModelList();
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
  });

  // settings
  document.getElementById('settings-btn').addEventListener('click', openSettingsModal);
  document.getElementById('settings-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('settings-save-btn').addEventListener('click', saveSettings);

  // mcp add
  document.getElementById('mcp-add-btn').addEventListener('click', addMcpServer);

  // notes
  document.getElementById('note-new-btn').addEventListener('click', newNote);

  // tasks
  const taskInput = document.getElementById('task-add-input');
  document.getElementById('task-add-btn').addEventListener('click', async () => {
    await addTask(taskInput.value.trim());
    taskInput.value = '';
  });
  taskInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('task-add-btn').click();
  });

  // sidebar nav
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      const v = el.dataset.view;
      if (v === 'chat')     showChatView();
      else if (v === 'notes')    showNotesView();
      else if (v === 'tasks')    showTasksView();
      else if (v === 'memory')   showMemoryView();
      else if (v === 'settings') openSettingsModal();
    });
  });

  // close modals
  document.querySelectorAll('.modal-overlay').forEach(o => {
    o.addEventListener('click', e => { if (e.target === o) closeAllModals(); });
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAllModals(); });
  document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
  });

  document.getElementById('share-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(location.href).then(() => toast('link copied'));
  });

  setInterval(loadModels, 30000);
}


// ── helpers ───────────────────────────────────────────────────────────────────

function doSend() {
  const ta = document.getElementById('composer-ta');
  const text = ta.value.trim();
  if (!text) return;
  ta.value = ''; ta.style.height = 'auto';
  if (isResearchMode()) runResearch(text);
  else sendMessage(text);
}

function setMode(m) {
  document.getElementById('mode-agent').classList.toggle('active', m === 'agent');
  document.getElementById('mode-chat').classList.toggle('active', m === 'chat');
}

function toggleTheme() {
  const root = document.documentElement;
  if (root.dataset.theme === 'light') {
    delete root.dataset.theme;
    localStorage.removeItem('aide-theme');
  } else {
    root.dataset.theme = 'light';
    localStorage.setItem('aide-theme', 'light');
  }
}

function openModelModal() {
  document.getElementById('model-modal').style.display = 'flex';
  renderModelList();
  const inp = document.getElementById('model-search-input');
  inp.value = ''; inp.focus();
}

async function openSettingsModal() {
  document.getElementById('settings-modal').style.display = 'flex';
  try {
    const r = await fetch('/api/settings');
    const s = await r.json();
    document.getElementById('settings-system-prompt').value = s.system_prompt || '';
    document.getElementById('settings-context-limit').value = s.context_limit ?? 40;
  } catch (e) {}
  loadMcpServers();
}

async function saveSettings() {
  await fetch('/api/settings', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      system_prompt: document.getElementById('settings-system-prompt').value,
      context_limit: parseInt(document.getElementById('settings-context-limit').value) || 40,
    }),
  });
  toast('saved', 'success');
  closeAllModals();
}

async function loadMcpServers() {
  const listEl = document.getElementById('mcp-server-list');
  if (!listEl) return;
  try {
    const r = await fetch('/api/mcp/servers');
    const servers = await r.json();
    if (!servers.length) { listEl.innerHTML = '<div style="font-size:0.72rem;color:var(--faint);padding:0.25rem 0">no servers</div>'; return; }
    listEl.innerHTML = servers.map(s => `
      <div style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0;font-size:0.78rem">
        <span style="width:6px;height:6px;border-radius:50%;background:${s.connected ? 'var(--green)' : 'var(--faint)'}"></span>
        <span style="flex:1;color:var(--text)">${s.name}</span>
        <span style="color:var(--muted);font-size:0.68rem">${s.tools.length} tools</span>
        <button class="act-btn mcp-del" data-id="${s.id}">remove</button>
      </div>`).join('');
    listEl.querySelectorAll('.mcp-del').forEach(btn => {
      btn.addEventListener('click', async () => {
        await fetch(`/api/mcp/servers/${btn.dataset.id}`, { method: 'DELETE' });
        loadMcpServers();
      });
    });
  } catch (e) {}
}

async function addMcpServer() {
  const name    = document.getElementById('mcp-name').value.trim();
  const command = document.getElementById('mcp-command').value.trim();
  if (!name || !command) { toast('name + command required', 'error'); return; }
  // split command into binary + args
  const parts = command.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
  const cmd = parts[0]; const args = parts.slice(1).map(a => a.replace(/^"|"$/g, ''));
  try {
    await fetch('/api/mcp/servers', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name, transport: 'stdio', command: cmd, args }),
    });
    document.getElementById('mcp-name').value = '';
    document.getElementById('mcp-command').value = '';
    toast('mcp server added', 'success');
    loadMcpServers();
  } catch (e) { toast('failed', 'error'); }
}

// shell quick-prompt — injects a shell block into the composer
function openShellPrompt() {
  const ta = document.getElementById('composer-ta');
  const current = ta.value;
  if (!current.includes('```sh')) {
    ta.value = current ? current + '\n```sh\n\n```' : '```sh\n\n```';
  }
  ta.focus();
  // put cursor inside the block
  const pos = ta.value.lastIndexOf('```sh\n') + 6;
  ta.setSelectionRange(pos, pos);
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
}
