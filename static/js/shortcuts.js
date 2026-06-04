const KEY = 'aide-shortcuts';

export const DEFAULT_SHORTCUTS = {
  search: 'Ctrl+K',
  sidebar: 'Ctrl+B',
  settings: 'Ctrl+,',
  new_chat: 'Ctrl+N',
  send: 'Ctrl+Enter',
};

export function loadShortcuts() {
  try {
    return { ...DEFAULT_SHORTCUTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
  } catch {
    return { ...DEFAULT_SHORTCUTS };
  }
}

export function saveShortcuts(next) {
  localStorage.setItem(KEY, JSON.stringify({ ...loadShortcuts(), ...next }));
}

export function formatShortcut(parts) {
  return [
    parts.ctrl ? 'Ctrl' : '',
    parts.alt ? 'Alt' : '',
    parts.shift ? 'Shift' : '',
    parts.meta ? 'Meta' : '',
    parts.key || '',
  ].filter(Boolean).join('+');
}

export function eventToShortcut(e) {
  const key = _keyName(e.key);
  if (!key) return '';
  return formatShortcut({
    ctrl: e.ctrlKey,
    alt: e.altKey,
    shift: e.shiftKey,
    meta: e.metaKey,
    key,
  });
}

export function matchesShortcut(e, shortcut) {
  if (!shortcut) return false;
  return eventToShortcut(e).toLowerCase() === shortcut.toLowerCase();
}

function _keyName(key) {
  if (!key || ['Control', 'Alt', 'Shift', 'Meta'].includes(key)) return '';
  if (key === ' ') return 'Space';
  if (key.length === 1) return key.toUpperCase();
  return key;
}
