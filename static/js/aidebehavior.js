const BEHAVIORS = new Set(['', 'automatic_tools', 'answer_only']);

let _defaultBehavior = 'automatic_tools';
let _wired = false;

function normalize(value) {
  return BEHAVIORS.has(value) ? value : '';
}

function effective(value) {
  return normalize(value) || _defaultBehavior;
}

export function refreshAideBehavior(session = window._currentSession) {
  const select = document.getElementById('chat-behavior-select');
  if (!select) return;
  const value = session ? normalize(session.chat_behavior) : normalize(window._pendingChatBehavior);
  select.value = value;
  const current = effective(value) === 'answer_only' ? 'answer only' : 'automatic tools';
  select.title = value ? `this conversation uses ${current}` : `follows settings: ${current}`;
  select.setAttribute('aria-description', select.title);
}

export function setDefaultAideBehavior(value) {
  _defaultBehavior = value === 'answer_only' ? 'answer_only' : 'automatic_tools';
  refreshAideBehavior();
}

async function save(value) {
  value = normalize(value);
  const select = document.getElementById('chat-behavior-select');
  const session = window._currentSession;
  const previous = session ? normalize(session.chat_behavior) : normalize(window._pendingChatBehavior);
  if (session) {
    try {
      const response = await fetch(`/api/sessions/${session.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ chat_behavior: value }),
      });
      if (!response.ok) throw new Error('behavior could not be saved');
      const updated = await response.json();
      session.chat_behavior = normalize(updated.chat_behavior);
    } catch {
      if (select) select.value = previous;
      return;
    }
  } else {
    window._pendingChatBehavior = value;
  }
  refreshAideBehavior();
}

export async function initAideBehavior(settings = null) {
  if (!settings) {
    try { settings = await fetch('/api/settings').then(response => response.json()); }
    catch { settings = {}; }
  }
  setDefaultAideBehavior(settings?.default_chat_behavior);
  if (!_wired) {
    _wired = true;
    document.getElementById('chat-behavior-select')?.addEventListener('change', event => {
      save(event.currentTarget.value);
    });
  }
  window._refreshChatBehaviorBtn = refreshAideBehavior;
  window._setDefaultChatBehavior = setDefaultAideBehavior;
  refreshAideBehavior();
}
