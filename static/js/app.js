import { loadSessions, showWelcome, createSession, renderSidebar } from './sessions.js';
import { loadModels, renderModelList, addEndpoint, getSelected, getCurrentEndpoint } from './models.js';
import { sendMessage, stopStream } from './chat.js';
import { toast, closeAllModals } from './util.js';
import { initMemoryPanel } from './memory.js';
import { runResearch, setResearchMode, isResearchMode } from './research.js';

// expose mdToHtml for sessions.js
import { mdToHtml } from './util.js';
window._mdToHtml = mdToHtml;

// ── init ─────────────────────────────────────────────────────────────────────

async function init() {
  await loadModels();
  await loadSessions();
  bindEvents();
}

init();


// ── views ─────────────────────────────────────────────────────────────────────

function showChatView() {
  document.getElementById('chat').style.display = 'flex';
  document.getElementById('mem-view').style.display = 'none';
  document.getElementById('composer-outer').style.display = 'block';
  setNav('chat');
}

function showMemoryView() {
  document.getElementById('chat').style.display = 'none';
  document.getElementById('mem-view').style.display = 'flex';
  document.getElementById('composer-outer').style.display = 'none';
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
  // send
  const ta = document.getElementById('composer-ta');
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  document.getElementById('send-btn').addEventListener('click', doSend);
  document.getElementById('stop-btn').addEventListener('click', stopStream);

  // new chat
  document.getElementById('new-chat-btn').addEventListener('click', async () => {
    const ep = getCurrentEndpoint();
    const model = getSelected()?.model || '';
    const s = await createSession(model, ep?.id || '');
    if (s) {
      showChatView();
      const { selectSession } = await import('./sessions.js');
      await selectSession(s.id);
    }
  });

  // session search
  document.getElementById('session-search').addEventListener('input', e => {
    renderSidebar(e.target.value);
  });

  // research toggle button in composer
  document.getElementById('research-toggle-btn').addEventListener('click', () => {
    const on = !isResearchMode();
    setResearchMode(on);
    document.getElementById('research-toggle-btn').classList.toggle('active', on);
    ta.placeholder = on ? 'research a topic...' : 'message aide...';
  });

  // mode toggle (agent/chat)
  document.getElementById('mode-agent').addEventListener('click', () => setMode('agent'));
  document.getElementById('mode-chat').addEventListener('click', () => setMode('chat'));

  // theme
  document.getElementById('theme-btn').addEventListener('click', toggleTheme);

  // model picker
  document.getElementById('model-btn').addEventListener('click', openModelModal);
  document.getElementById('model-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('model-search-input').addEventListener('input', e => {
    renderModelList(e.target.value);
  });

  // add endpoint
  document.getElementById('ep-add-btn').addEventListener('click', async () => {
    const name = document.getElementById('ep-name').value.trim();
    const url  = document.getElementById('ep-url').value.trim();
    const key  = document.getElementById('ep-key').value.trim();
    if (!name || !url) { toast('name and url required', 'error'); return; }
    try {
      await addEndpoint(name, url, key);
      document.getElementById('ep-name').value = '';
      document.getElementById('ep-url').value  = '';
      document.getElementById('ep-key').value  = '';
      toast('endpoint added', 'success');
      renderModelList();
    } catch (e) {
      toast(`failed: ${e.message}`, 'error');
    }
  });

  // settings
  document.getElementById('settings-btn').addEventListener('click', openSettingsModal);
  document.getElementById('settings-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('settings-save-btn').addEventListener('click', saveSettings);

  // sidebar nav
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      if (el.dataset.view === 'chat')     showChatView();
      else if (el.dataset.view === 'memory') showMemoryView();
      else if (el.dataset.view === 'settings') openSettingsModal();
    });
  });

  // close modals on overlay click + escape
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) closeAllModals();
    });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeAllModals();
  });

  // close ctx menu
  document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
  });

  // share
  document.getElementById('share-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(location.href).then(() => toast('link copied'));
  });

  // poll models
  setInterval(loadModels, 30000);
}


// ── helpers ───────────────────────────────────────────────────────────────────

function doSend() {
  const ta = document.getElementById('composer-ta');
  const text = ta.value.trim();
  if (!text) return;
  ta.value = '';
  ta.style.height = 'auto';
  if (isResearchMode()) {
    runResearch(text);
  } else {
    sendMessage(text);
  }
}

function setMode(m) {
  document.getElementById('mode-agent').classList.toggle('active', m === 'agent');
  document.getElementById('mode-chat').classList.toggle('active', m === 'chat');
}

function toggleTheme() {
  const root = document.documentElement;
  const isLight = root.dataset.theme === 'light';
  if (isLight) {
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
  document.getElementById('model-search-input').value = '';
  document.getElementById('model-search-input').focus();
}

async function openSettingsModal() {
  document.getElementById('settings-modal').style.display = 'flex';
  try {
    const r = await fetch('/api/settings');
    const s = await r.json();
    document.getElementById('settings-system-prompt').value = s.system_prompt || '';
    document.getElementById('settings-context-limit').value = s.context_limit || 40;
  } catch (e) {}
}

async function saveSettings() {
  const body = {
    system_prompt: document.getElementById('settings-system-prompt').value,
    context_limit: parseInt(document.getElementById('settings-context-limit').value) || 40,
  };
  await fetch('/api/settings', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  toast('saved', 'success');
  closeAllModals();
}
