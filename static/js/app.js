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
import { openSettings, closeSettings, applyVis } from './settings.js';

window._mdToHtml = mdToHtml;

// ── init ──────────────────────────────────────────────────────────────────────
async function init() {
  try {
    const me = await fetch('/api/auth/me').then(r => r.json());
    if (!me.authenticated) { _showLoginScreen(); return; }
  } catch {}
  await _boot();
}

async function _boot() {
  applyVis();
  await loadModels();
  await loadProjects();
  await loadSessions();
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
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (r.ok) { if (screen) screen.style.display = 'none'; _boot(); }
    else toast('wrong password', 'error');
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
  document.getElementById('mode-chat').addEventListener('click',  () => setMode('chat'));
  document.getElementById('theme-btn').addEventListener('click', toggleTheme);

  // persona picker
  document.getElementById('persona-btn').addEventListener('click', openPersonaPicker);

  // model picker
  document.getElementById('model-btn').addEventListener('click', openModelModal);
  document.getElementById('model-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('model-search-input').addEventListener('input', e => renderModelList(e.target.value));

  // settings — delegate entirely to settings.js
  document.getElementById('settings-btn').addEventListener('click', () => openSettings());

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

  // attach button
  document.getElementById('attach-btn')?.addEventListener('click', () => {
    document.getElementById('file-input-hidden')?.click();
  });
  document.getElementById('file-input-hidden')?.addEventListener('change', async e => {
    for (const f of e.target.files) await attachFile(f);
    e.target.value = '';
  });

  // mic
  document.getElementById('mic-btn')?.addEventListener('click', async () => {
    const { isRecording, startRecording, stopRecording } = await import('./voice.js');
    if (isRecording()) stopRecording(); else startRecording();
  });

  // incognito
  document.getElementById('incognito-btn')?.addEventListener('click', async () => {
    toast('incognito session — messages not saved', 'success');
    const ep = getCurrentEndpoint();
    const s = await fetch('/api/sessions', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: getSelected()?.model || '', endpoint_id: ep?.id || '', incognito: true }),
    }).then(r => r.json());
    if (s?.id) {
      showChatView();
      const { selectSession } = await import('./sessions.js');
      await loadSessions();
      await selectSession(s.id);
    }
  });

  // docs
  document.getElementById('doc-ai-send')?.addEventListener('click', async () => {
    const inp = document.getElementById('doc-ai-input');
    if (!inp?.value.trim()) return;
    await aiEditDoc(inp.value.trim()); inp.value = '';
  });
  document.getElementById('doc-back-btn')?.addEventListener('click', closeDocEditor);
  document.getElementById('doc-new-btn')?.addEventListener('click', newDocument);

  // contacts
  document.getElementById('contacts-search')?.addEventListener('input', e => loadContacts(e.target.value));
  document.getElementById('contact-add-btn')?.addEventListener('click', addContact);

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
      else if (v === 'settings') openSettings();
    });
  });

  // modal overlays close on backdrop click (except settings which manages itself)
  document.querySelectorAll('.modal-overlay:not(#settings-modal)').forEach(o => {
    o.addEventListener('click', e => { if (e.target === o) closeAllModals(); });
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeAllModals(); closeSettings(); closeSearch(); }
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

// ── mode / theme ──────────────────────────────────────────────────────────────
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

// ── model picker ──────────────────────────────────────────────────────────────
function openModelModal() {
  document.getElementById('model-modal').style.display = 'flex';
  renderModelList();
  const inp = document.getElementById('model-search-input');
  inp.value = ''; inp.focus();
}

// ── persona picker ────────────────────────────────────────────────────────────
let _personas = [];

export async function refreshPersonaBtn() {
  try { _personas = await fetch('/api/personas').then(r => r.json()); } catch { return; }
  const btn   = document.getElementById('persona-btn');
  const label = document.getElementById('persona-label');
  const session = window._currentSession;
  if (!session) { btn.style.display = 'none'; return; }
  const active = _personas.find(p => p.id === session.persona_id) || _personas.find(p => p.is_default);
  if (active) {
    btn.style.display = 'flex'; label.textContent = active.emoji + ' ' + active.name;
  } else if (_personas.length > 0) {
    btn.style.display = 'flex'; label.textContent = 'no persona';
  } else {
    btn.style.display = 'none';
  }
}

async function openPersonaPicker() {
  if (!_personas.length) _personas = await fetch('/api/personas').then(r => r.json());
  const session = window._currentSession;
  if (!session) return;
  const existing = document.getElementById('_persona_picker');
  if (existing) { existing.remove(); return; }
  const picker = document.createElement('div');
  picker.id = '_persona_picker';
  picker.className = 'ctx-menu';
  picker.style.cssText = 'display:block;top:50px;left:260px;min-width:160px';
  const none = document.createElement('div');
  none.className = 'ctx-item'; none.textContent = '— none';
  none.addEventListener('click', async () => {
    await fetch(`/api/sessions/${session.id}`, {
      method: 'PATCH', headers: {'content-type':'application/json'},
      body: JSON.stringify({ persona_id: '' }),
    });
    window._currentSession.persona_id = null; refreshPersonaBtn(); picker.remove();
  });
  picker.appendChild(none);
  for (const p of _personas) {
    const item = document.createElement('div');
    item.className = 'ctx-item'; item.textContent = p.emoji + ' ' + p.name;
    item.addEventListener('click', async () => {
      await fetch(`/api/sessions/${session.id}`, {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ persona_id: p.id }),
      });
      window._currentSession.persona_id = p.id;
      toast(`persona set: ${p.name}`, 'success'); refreshPersonaBtn(); picker.remove();
    });
    picker.appendChild(item);
  }
  document.body.appendChild(picker);
  setTimeout(() => document.addEventListener('click', () => picker.remove(), { once: true }), 0);
}

// ── shell prompt ──────────────────────────────────────────────────────────────
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
