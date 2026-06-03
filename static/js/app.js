import { loadSessions, showWelcome, createSession, renderSidebar } from './sessions.js';
import { loadModels, renderModelList, addEndpoint, getSelected, getCurrentEndpoint } from './models.js';
import { sendMessage, stopStream } from './chat.js';
import { toast, closeAllModals } from './util.js';

// ── init ────────────────────────────────────────────────────────────────────

async function init() {
  await loadModels();
  await loadSessions();
  bindEvents();
}

init();


// ── event bindings ───────────────────────────────────────────────────────────

function bindEvents() {
  // composer — send on Enter, newline on Shift+Enter
  const ta = document.getElementById('composer-ta');
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  });

  document.getElementById('send-btn').addEventListener('click', doSend);
  document.getElementById('stop-btn').addEventListener('click', stopStream);

  // new chat
  document.getElementById('new-chat-btn').addEventListener('click', async () => {
    const ep = getCurrentEndpoint();
    const model = getSelected()?.model || '';
    const s = await createSession(model, ep?.id || '');
    if (s) {
      const { selectSession } = await import('./sessions.js');
      await selectSession(s.id);
    }
  });

  // session search
  document.getElementById('session-search').addEventListener('input', e => {
    renderSidebar(e.target.value);
  });

  // chips
  document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const ta = document.getElementById('composer-ta');
      ta.value = btn.dataset.prompt;
      ta.focus();
    });
  });

  // mode toggle
  document.getElementById('mode-agent').addEventListener('click', () => setMode('agent'));
  document.getElementById('mode-chat').addEventListener('click', () => setMode('chat'));

  // theme toggle
  document.getElementById('theme-btn').addEventListener('click', toggleTheme);

  // model picker
  document.getElementById('model-btn').addEventListener('click', openModelModal);
  document.getElementById('model-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('model-search-input').addEventListener('input', e => {
    renderModelList(e.target.value);
  });

  // add endpoint form
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

  // settings modal
  document.getElementById('settings-btn').addEventListener('click', openSettingsModal);
  document.getElementById('settings-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('settings-save-btn').addEventListener('click', saveSettings);

  // sidebar nav
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
      el.classList.add('active');
      // placeholder — views not implemented in Phase 1
      if (el.dataset.view !== 'chat') {
        toast(`${el.dataset.view} — coming soon`, '');
      }
    });
  });

  // close modals on overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) closeAllModals();
    });
  });

  // close ctx menu on click anywhere
  document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
  });

  // escape closes modals
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeAllModals();
  });

  // share — copy url
  document.getElementById('share-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(location.href).then(() => toast('link copied'));
  });

  // poll models every 30s
  setInterval(loadModels, 30000);
}


function doSend() {
  const ta = document.getElementById('composer-ta');
  const text = ta.value.trim();
  if (!text) return;
  ta.value = '';
  ta.style.height = 'auto';
  sendMessage(text);
}


function setMode(m) {
  document.getElementById('mode-agent').classList.toggle('active', m === 'agent');
  document.getElementById('mode-chat').classList.toggle('active', m === 'chat');
}


function toggleTheme() {
  const root = document.documentElement;
  const current = root.dataset.theme || 'dark';
  const next = current === 'light' ? '' : 'light';
  if (next) root.dataset.theme = next;
  else delete root.dataset.theme;
  localStorage.setItem('aide-theme', next || 'dark');
  // fix: store as 'light' or '' (empty = dark)
  if (!next) localStorage.removeItem('aide-theme');
}


function openModelModal() {
  const modal = document.getElementById('model-modal');
  modal.style.display = 'flex';
  renderModelList();
  document.getElementById('model-search-input').value = '';
  document.getElementById('model-search-input').focus();
}


async function openSettingsModal() {
  const modal = document.getElementById('settings-modal');
  modal.style.display = 'flex';
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
