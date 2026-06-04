import { loadSessions, showWelcome, createSession, renderSidebar } from './sessions.js';
import { loadModels, renderModelList, addEndpoint, getSelected, getCurrentEndpoint } from './models.js';
import { sendMessage, stopStream } from './chat.js';
import { toast, closeAllModals, mdToHtml } from './util.js';
import { initMemoryPanel } from './memory.js';
import { runResearch, setResearchMode, isResearchMode } from './research.js';
import { loadNotes, newNote } from './notes.js';
import { loadTasks, addTask } from './tasks.js';
import { loadCalendar, newEvent } from './calendar.js';
import { loadGallery, initGalleryUpload } from './gallery.js';
import { initSlash, tryExecuteSlashCommand } from './slash.js';
import { attachFile, initDropZone } from './uploads.js';
import { loadProjects } from './projects.js';
import { openSearch, closeSearch, initSearch } from './search.js';
import { loadDocuments, newDocument, initDocEditor, closeDocEditor, aiEditDoc } from './documents.js';
import { initCompareView, loadCompareModels } from './compare.js';
import { loadVaultView, initVault } from './vault.js';
import { loadContacts, addContact } from './contacts.js';

window._mdToHtml = mdToHtml;

// ── init ─────────────────────────────────────────────────────────────────────
async function init() {
  // check auth first
  try {
    const me = await fetch('/api/auth/me').then(r => r.json());
    if (!me.authenticated) {
      _showLoginScreen();
      return;
    }
  } catch (e) {
    // auth not enabled — proceed normally
  }
  await _boot();
}

async function _boot() {
  await loadModels();
  await loadSessions();
  await loadProjects();
  const ta = document.getElementById('composer-ta');
  initSlash(ta);
  initSearch();
  initDropZone();
  initVault();
  bindEvents();
}

function _showLoginScreen() {
  const screen = document.getElementById('login-screen');
  if (screen) screen.style.display = 'flex';
  document.getElementById('login-submit')?.addEventListener('click', async () => {
    const pw = document.getElementById('login-pw')?.value;
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (r.ok) {
      if (screen) screen.style.display = 'none';
      _boot();
    } else {
      toast('wrong password', 'error');
    }
  });
  document.getElementById('login-pw')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('login-submit')?.click();
  });
}

init();

// ── views ─────────────────────────────────────────────────────────────────────
const _VIEW_IDS = [
  'chat', 'notes-view', 'tasks-view', 'calendar-view', 'gallery-view',
  'mem-view', 'docs-view', 'compare-view', 'vault-view', 'contacts-view',
];

function hideAllViews() {
  _VIEW_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  document.getElementById('composer-outer').style.display = 'none';
}

function showView(viewId, navKey, onShow) {
  hideAllViews();
  document.getElementById(viewId).style.display = 'flex';
  setNav(navKey);
  onShow?.();
}

const showChatView = () => {
  hideAllViews();
  document.getElementById('chat').style.display = 'flex';
  document.getElementById('composer-outer').style.display = 'block';
  setNav('chat');
};
const showNotesView    = () => showView('notes-view',    'notes',    loadNotes);
const showTasksView    = () => showView('tasks-view',    'tasks',    loadTasks);
const showCalendarView = () => showView('calendar-view', 'calendar', loadCalendar);
const showGalleryView  = () => showView('gallery-view',  'gallery',  () => { loadGallery(); initGalleryUpload(); });
const showMemoryView   = () => showView('mem-view',      'memory',   initMemoryPanel);
const showDocsView     = () => showView('docs-view',     'docs',     () => { loadDocuments(); initDocEditor(); });
const showCompareView  = () => showView('compare-view',  'compare',  () => { initCompareView(); loadCompareModels(); });
const showVaultView    = () => showView('vault-view',    'vault',    loadVaultView);
const showContactsView = () => showView('contacts-view', 'contacts', () => loadContacts());

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

  document.getElementById('session-search').addEventListener('input', e => renderSidebar(e.target.value));

  document.getElementById('research-toggle-btn').addEventListener('click', () => {
    const on = !isResearchMode();
    setResearchMode(on);
    document.getElementById('research-toggle-btn').classList.toggle('active', on);
    ta.placeholder = on ? 'research a topic...' : 'message aide...';
  });

  document.getElementById('shell-btn-tool').addEventListener('click', openShellPrompt);

  document.getElementById('mode-agent').addEventListener('click', () => setMode('agent'));
  document.getElementById('mode-chat').addEventListener('click', () => setMode('chat'));
  document.getElementById('theme-btn').addEventListener('click', toggleTheme);

  // persona picker
  document.getElementById('persona-btn').addEventListener('click', openPersonaPicker);

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
  document.getElementById('mcp-add-btn').addEventListener('click', addMcpServer);
  document.getElementById('persona-add-btn').addEventListener('click', addPersona);
  document.getElementById('cookbook-add-btn').addEventListener('click', addCookbookEntry);
  document.getElementById('wh-add-btn').addEventListener('click', addWebhook);
  document.getElementById('token-add-btn').addEventListener('click', generateToken);

  // notes / tasks / calendar / gallery
  document.getElementById('note-new-btn').addEventListener('click', newNote);
  document.getElementById('cal-new-btn').addEventListener('click', newEvent);
  const taskInput = document.getElementById('task-add-input');
  document.getElementById('task-add-btn').addEventListener('click', async () => {
    await addTask(taskInput.value.trim()); taskInput.value = '';
  });
  taskInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('task-add-btn').click();
  });

  // attach button wires to hidden file input
  document.getElementById('attach-btn')?.addEventListener('click', () => {
    document.getElementById('file-input-hidden')?.click();
  });
  document.getElementById('file-input-hidden')?.addEventListener('change', async e => {
    for (const f of e.target.files) await attachFile(f);
    e.target.value = '';
  });

  // mic button
  document.getElementById('mic-btn')?.addEventListener('click', async () => {
    const { isRecording, startRecording, stopRecording } = await import('./voice.js');
    if (isRecording()) stopRecording();
    else startRecording();
  });

  // new incognito session button
  document.getElementById('incognito-btn')?.addEventListener('click', async () => {
    toast('incognito session — messages not saved', 'success');
    const ep = getCurrentEndpoint();
    const s = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: getSelected()?.model || '', endpoint_id: ep?.id || '', incognito: true }),
    }).then(r => r.json());
    if (s?.id) {
      showChatView();
      const { selectSession } = await import('./sessions.js');
      await loadSessions();
      await selectSession(s.id);
    }
  });

  // doc ai-edit bar
  document.getElementById('doc-ai-send')?.addEventListener('click', async () => {
    const inp = document.getElementById('doc-ai-input');
    if (!inp?.value.trim()) return;
    await aiEditDoc(inp.value.trim());
    inp.value = '';
  });
  document.getElementById('doc-back-btn')?.addEventListener('click', closeDocEditor);
  document.getElementById('doc-new-btn')?.addEventListener('click', newDocument);

  // contacts search
  document.getElementById('contacts-search')?.addEventListener('input', e => loadContacts(e.target.value));
  document.getElementById('contact-add-btn')?.addEventListener('click', addContact);

  // backup/restore in settings
  document.getElementById('backup-export-btn')?.addEventListener('click', () => {
    window.location = '/api/backup';
  });
  document.getElementById('backup-restore-input')?.addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/backup/restore', { method: 'POST', body: fd });
    if (r.ok) { toast('restore complete — reloading…', 'success'); setTimeout(() => location.reload(), 1500); }
    else toast('restore failed', 'error');
    e.target.value = '';
  });

  // sidebar nav
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      const v = el.dataset.view;
      if      (v === 'chat')     showChatView();
      else if (v === 'notes')    showNotesView();
      else if (v === 'tasks')    showTasksView();
      else if (v === 'calendar') showCalendarView();
      else if (v === 'gallery')  showGalleryView();
      else if (v === 'memory')   showMemoryView();
      else if (v === 'docs')     showDocsView();
      else if (v === 'compare')  showCompareView();
      else if (v === 'vault')    showVaultView();
      else if (v === 'contacts') showContactsView();
      else if (v === 'settings') openSettingsModal();
    });
  });

  document.querySelectorAll('.modal-overlay').forEach(o => {
    o.addEventListener('click', e => { if (e.target === o) closeAllModals(); });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeAllModals(); closeSearch(); }
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); openSearch(); }
  });
  document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
  });
  document.getElementById('share-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(location.href).then(() => toast('link copied'));
  });

  setInterval(loadModels, 30000);
}

// ── send ──────────────────────────────────────────────────────────────────────
async function doSend() {
  const ta = document.getElementById('composer-ta');
  const text = ta.value.trim();
  if (!text) return;
  if (await tryExecuteSlashCommand(text)) {
    ta.value = ''; ta.style.height = 'auto';
    return;
  }
  ta.value = ''; ta.style.height = 'auto';
  if (isResearchMode()) runResearch(text);
  else sendMessage(text);
}

// ── helpers ───────────────────────────────────────────────────────────────────
function setMode(m) {
  document.getElementById('mode-agent').classList.toggle('active', m === 'agent');
  document.getElementById('mode-chat').classList.toggle('active', m === 'chat');
}

function toggleTheme() {
  const root = document.documentElement;
  if (root.dataset.theme === 'light') {
    delete root.dataset.theme; localStorage.removeItem('aide-theme');
  } else {
    root.dataset.theme = 'light'; localStorage.setItem('aide-theme', 'light');
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
    const s = await (await fetch('/api/settings')).json();
    document.getElementById('settings-system-prompt').value = s.system_prompt || '';
    document.getElementById('settings-context-limit').value = s.context_limit ?? 40;
    if (document.getElementById('settings-tts-provider'))
      document.getElementById('settings-tts-provider').value = s.tts_provider || 'browser';
    if (document.getElementById('settings-stt-provider'))
      document.getElementById('settings-stt-provider').value = s.stt_provider || 'browser';
  } catch (e) {}
  loadMcpServers();
  loadPersonas();
  loadCookbook();
  loadWebhooks();
  loadTokens();
}

async function saveSettings() {
  const patch = {
    system_prompt: document.getElementById('settings-system-prompt').value,
    context_limit: parseInt(document.getElementById('settings-context-limit').value) || 40,
  };
  const oaiKey = document.getElementById('settings-openai-key')?.value?.trim();
  if (oaiKey) patch.openai_api_key = oaiKey;
  const ttsProvider = document.getElementById('settings-tts-provider')?.value;
  if (ttsProvider) patch.tts_provider = ttsProvider;
  const sttProvider = document.getElementById('settings-stt-provider')?.value;
  if (sttProvider) patch.stt_provider = sttProvider;
  await fetch('/api/settings', {
    method: 'PATCH', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch),
  });
  toast('saved', 'success');
  closeAllModals();
}

// ── mcp ───────────────────────────────────────────────────────────────────────
async function loadMcpServers() {
  const el = document.getElementById('mcp-server-list');
  if (!el) return;
  try {
    const servers = await (await fetch('/api/mcp/servers')).json();
    if (!servers.length) { el.innerHTML = '<div class="settings-row-empty">no servers</div>'; return; }
    el.innerHTML = servers.map(s => `
      <div class="settings-list-row">
        <span class="status-dot" style="background:${s.connected ? 'var(--green)' : 'var(--faint)'}"></span>
        <span class="row-name">${s.name}</span>
        <span class="row-meta">${s.tools.length} tools</span>
        <button class="act-btn" data-id="${s.id}" onclick="rmMcp(this)">remove</button>
      </div>`).join('');
  } catch (e) {}
}

window.rmMcp = async btn => {
  await fetch(`/api/mcp/servers/${btn.dataset.id}`, { method: 'DELETE' });
  loadMcpServers();
};

async function addMcpServer() {
  const name = document.getElementById('mcp-name').value.trim();
  const command = document.getElementById('mcp-command').value.trim();
  if (!name || !command) { toast('name + command required', 'error'); return; }
  const parts = command.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
  const cmd = parts[0], args = parts.slice(1).map(a => a.replace(/^"|"$/g,''));
  try {
    await fetch('/api/mcp/servers', { method: 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify({ name, transport: 'stdio', command: cmd, args }) });
    document.getElementById('mcp-name').value = '';
    document.getElementById('mcp-command').value = '';
    toast('mcp server added', 'success');
    loadMcpServers();
  } catch (e) { toast('failed', 'error'); }
}

// ── personas ──────────────────────────────────────────────────────────────────
async function loadPersonas() {
  const el = document.getElementById('persona-list');
  if (!el) return;
  const personas = await (await fetch('/api/personas')).json();
  if (!personas.length) { el.innerHTML = '<div class="settings-row-empty">no personas</div>'; return; }
  el.innerHTML = personas.map(p => `
    <div class="settings-list-row">
      <span>${p.emoji}</span>
      <span class="row-name">${p.name}</span>
      <span class="row-meta">${p.system_prompt.slice(0,40)}${p.system_prompt.length>40?'…':''}</span>
      <button class="act-btn" data-id="${p.id}" onclick="rmPersona(this)">remove</button>
    </div>`).join('');
}

window.rmPersona = async btn => {
  await fetch(`/api/personas/${btn.dataset.id}`, { method: 'DELETE' });
  loadPersonas();
};

async function addPersona() {
  const name   = document.getElementById('persona-name').value.trim();
  const emoji  = document.getElementById('persona-emoji').value.trim() || '🤖';
  const prompt = document.getElementById('persona-prompt').value.trim();
  if (!name) { toast('name required', 'error'); return; }
  await fetch('/api/personas', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, emoji, system_prompt: prompt }) });
  ['persona-name','persona-emoji','persona-prompt'].forEach(id => document.getElementById(id).value = '');
  toast('persona added', 'success');
  loadPersonas();
}

// ── cookbook ──────────────────────────────────────────────────────────────────
async function loadCookbook() {
  const el = document.getElementById('cookbook-list');
  if (!el) return;
  const entries = await (await fetch('/api/cookbook')).json();
  if (!entries.length) { el.innerHTML = '<div class="settings-row-empty">no entries — type / in chat to use</div>'; return; }
  el.innerHTML = entries.map(e => `
    <div class="settings-list-row">
      <span class="row-name" style="color:var(--accent)">/${e.name}</span>
      <span class="row-meta">${e.description || e.prompt.slice(0,50)}</span>
      <button class="act-btn" data-id="${e.id}" onclick="rmCookbook(this)">remove</button>
    </div>`).join('');
}

window.rmCookbook = async btn => {
  await fetch(`/api/cookbook/${btn.dataset.id}`, { method: 'DELETE' });
  loadCookbook();
};

async function addCookbookEntry() {
  const name   = document.getElementById('cookbook-name').value.trim();
  const desc   = document.getElementById('cookbook-desc').value.trim();
  const prompt = document.getElementById('cookbook-prompt').value.trim();
  if (!name || !prompt) { toast('name + prompt required', 'error'); return; }
  await fetch('/api/cookbook', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, description: desc, prompt }) });
  ['cookbook-name','cookbook-desc','cookbook-prompt'].forEach(id => document.getElementById(id).value = '');
  toast('added', 'success');
  loadCookbook();
}

// ── webhooks ──────────────────────────────────────────────────────────────────
async function loadWebhooks() {
  const el = document.getElementById('webhook-list');
  if (!el) return;
  const hooks = await (await fetch('/api/webhooks')).json();
  if (!hooks.length) { el.innerHTML = '<div class="settings-row-empty">no webhooks</div>'; return; }
  el.innerHTML = hooks.map(h => `
    <div class="settings-list-row">
      <span class="status-dot" style="background:${h.enabled ? 'var(--green)' : 'var(--faint)'}"></span>
      <span class="row-name">${h.name}</span>
      <span class="row-meta">${h.events.join(', ')}</span>
      <button class="act-btn" data-id="${h.id}" onclick="rmWebhook(this)">remove</button>
    </div>`).join('');
}

window.rmWebhook = async btn => {
  await fetch(`/api/webhooks/${btn.dataset.id}`, { method: 'DELETE' });
  loadWebhooks();
};

async function addWebhook() {
  const name = document.getElementById('wh-name').value.trim();
  const url  = document.getElementById('wh-url').value.trim();
  if (!name || !url) { toast('name + url required', 'error'); return; }
  await fetch('/api/webhooks', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, url, events: ['message'] }) });
  ['wh-name','wh-url'].forEach(id => document.getElementById(id).value = '');
  toast('webhook added', 'success');
  loadWebhooks();
}

// ── api tokens ────────────────────────────────────────────────────────────────
async function loadTokens() {
  const el = document.getElementById('token-list');
  if (!el) return;
  const tokens = await (await fetch('/api/tokens')).json();
  if (!tokens.length) { el.innerHTML = '<div class="settings-row-empty">no tokens</div>'; return; }
  el.innerHTML = tokens.map(t => `
    <div class="settings-list-row">
      <span class="row-name" style="font-family:monospace;font-size:0.72rem">${t.prefix}…</span>
      <span class="row-meta">${t.name}</span>
      <span class="row-meta">${t.last_used_at ? 'used ' + new Date(t.last_used_at).toLocaleDateString() : 'never used'}</span>
      <button class="act-btn" data-id="${t.id}" onclick="rmToken(this)">revoke</button>
    </div>`).join('');
}

window.rmToken = async btn => {
  await fetch(`/api/tokens/${btn.dataset.id}`, { method: 'DELETE' });
  loadTokens();
};

async function generateToken() {
  const name = document.getElementById('token-name').value.trim();
  if (!name) { toast('name required', 'error'); return; }
  const r = await fetch('/api/tokens', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name }) });
  const data = await r.json();
  document.getElementById('token-name').value = '';
  const reveal = document.getElementById('token-reveal');
  reveal.style.display = 'block';
  reveal.textContent = data.token;
  reveal.title = 'click to copy';
  reveal.onclick = () => {
    navigator.clipboard.writeText(data.token).then(() => toast('token copied', 'success'));
  };
  toast('token generated — copy it now, shown once', 'success');
  loadTokens();
}

// ── persona picker ───────────────────────────────────────────────────────────
let _personas = [];

export async function refreshPersonaBtn() {
  try {
    _personas = await (await fetch('/api/personas')).json();
  } catch (e) { return; }

  const btn = document.getElementById('persona-btn');
  const label = document.getElementById('persona-label');
  const session = window._currentSession;
  if (!session) { btn.style.display = 'none'; return; }

  // find active persona
  const active = _personas.find(p => p.id === session.persona_id)
    || _personas.find(p => p.is_default);

  if (active) {
    btn.style.display = 'flex';
    label.textContent = active.emoji + ' ' + active.name;
  } else if (_personas.length > 0) {
    btn.style.display = 'flex';
    label.textContent = 'no persona';
  } else {
    btn.style.display = 'none';
  }
}

async function openPersonaPicker() {
  if (!_personas.length) _personas = await (await fetch('/api/personas')).json();
  const session = window._currentSession;
  if (!session) return;

  // build a tiny dropdown manually
  const existing = document.getElementById('_persona_picker');
  if (existing) { existing.remove(); return; }

  const picker = document.createElement('div');
  picker.id = '_persona_picker';
  picker.className = 'ctx-menu';
  picker.style.cssText = 'display:block;top:50px;left:260px;min-width:160px';

  const none = document.createElement('div');
  none.className = 'ctx-item';
  none.textContent = '— none';
  none.addEventListener('click', async () => {
    await fetch(`/api/sessions/${session.id}`, {
      method: 'PATCH', headers: {'content-type':'application/json'},
      body: JSON.stringify({ persona_id: '' }),
    });
    window._currentSession.persona_id = null;
    refreshPersonaBtn();
    picker.remove();
  });
  picker.appendChild(none);

  for (const p of _personas) {
    const item = document.createElement('div');
    item.className = 'ctx-item';
    item.textContent = p.emoji + ' ' + p.name;
    item.addEventListener('click', async () => {
      await fetch(`/api/sessions/${session.id}`, {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ persona_id: p.id }),
      });
      window._currentSession.persona_id = p.id;
      toast(`persona set: ${p.name}`, 'success');
      refreshPersonaBtn();
      picker.remove();
    });
    picker.appendChild(item);
  }

  document.body.appendChild(picker);
  setTimeout(() => document.addEventListener('click', () => picker.remove(), { once: true }), 0);
}

// ── shell ─────────────────────────────────────────────────────────────────────
function openShellPrompt() {
  const ta = document.getElementById('composer-ta');
  const cur = ta.value;
  ta.value = cur ? cur + '\n```sh\n\n```' : '```sh\n\n```';
  ta.focus();
  const pos = ta.value.lastIndexOf('```sh\n') + 6;
  ta.setSelectionRange(pos, pos);
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
}
