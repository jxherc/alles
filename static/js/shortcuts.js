const KEY = 'aide-shortcuts';

export const DEFAULT_SHORTCUTS = {
  search: 'Ctrl+K',
  sidebar: 'Ctrl+B',
  settings: 'Ctrl+,',
  new_chat: 'Alt+N',        // Ctrl+N is the browser's new-window — don't fight it
  send: 'Ctrl+Enter',
  focus_input: 'Ctrl+/',    // jump to the composer from anywhere
  stop: 'Escape',           // stop an in-flight generation (also closes overlays)
};

// combos the OS/browser already own — binding these would either never fire or
// fight the browser, so we refuse them when rebinding. lowercased for compare.
const RESERVED = new Set([
  'ctrl+t','ctrl+n','ctrl+w','ctrl+q','ctrl+s','ctrl+p','ctrl+r','ctrl+l','ctrl+d',
  'ctrl+j','ctrl+h','ctrl+o','ctrl+u','ctrl+f','ctrl+g','ctrl+e','ctrl+a','ctrl+tab',
  'ctrl+shift+t','ctrl+shift+n','ctrl+shift+w','ctrl+shift+q','ctrl+shift+delete',
  'ctrl+shift+j','ctrl+shift+i','ctrl+shift+c','ctrl+shift+r','ctrl+shift+b',
  'f5','f11','f12','alt+f4','alt+tab','ctrl+escape',
]);
export function isReservedShortcut(combo) {
  const c = (combo || '').toLowerCase();
  if (!c) return false;
  if (c === 'meta' || c.startsWith('meta+')) return true;   // Win / Cmd are OS-level
  return RESERVED.has(c);
}

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
