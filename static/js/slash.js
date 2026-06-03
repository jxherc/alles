/**
 * Slash command autocomplete for the composer.
 * Type "/" at the start of a line to trigger.
 * Pulls entries from /api/cookbook.
 */

let _entries = [];
let _popup = null;
let _selectedIdx = 0;

async function fetchEntries() {
  try {
    const r = await fetch('/api/cookbook');
    _entries = await r.json();
  } catch (e) {}
}

export function initSlash(ta) {
  fetchEntries();

  ta.addEventListener('input', () => handleInput(ta));
  ta.addEventListener('keydown', e => handleKey(e, ta));
  ta.addEventListener('blur', () => setTimeout(hide, 150));

  // refresh on focus so new entries show up
  ta.addEventListener('focus', fetchEntries);
}

function handleInput(ta) {
  const val = ta.value;
  const cursor = ta.selectionStart;
  const lineStart = val.lastIndexOf('\n', cursor - 1) + 1;
  const line = val.slice(lineStart, cursor);

  if (!line.startsWith('/') || line.includes(' ')) {
    hide(); return;
  }

  const query = line.slice(1).toLowerCase();
  const matches = _entries.filter(e =>
    e.name.includes(query) || e.description.toLowerCase().includes(query)
  );

  if (!matches.length) { hide(); return; }
  show(matches, ta, lineStart, cursor);
}

function show(matches, ta, lineStart, cursor) {
  hide();
  _selectedIdx = 0;

  _popup = document.createElement('div');
  _popup.className = 'slash-popup';
  _popup.innerHTML = matches.map((e, i) => `
    <div class="slash-item${i === 0 ? ' selected' : ''}" data-idx="${i}">
      <span class="slash-name">/${e.name}</span>
      ${e.description ? `<span class="slash-desc">${e.description}</span>` : ''}
    </div>`).join('');

  // position above textarea
  const rect = ta.getBoundingClientRect();
  _popup.style.cssText = `bottom:${window.innerHeight - rect.top + 6}px;left:${rect.left}px;width:${rect.width}px`;
  document.body.appendChild(_popup);

  _popup.querySelectorAll('.slash-item').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault();
      apply(matches[+el.dataset.idx], ta, lineStart, cursor);
    });
  });

  // store matches ref for keyboard nav
  _popup._matches = matches;
  _popup._ta = ta;
  _popup._lineStart = lineStart;
  _popup._cursor = cursor;
}

function hide() {
  _popup?.remove();
  _popup = null;
}

function handleKey(e, ta) {
  if (!_popup) return;
  const matches = _popup._matches;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _selectedIdx = Math.min(_selectedIdx + 1, matches.length - 1);
    updateSelected();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _selectedIdx = Math.max(_selectedIdx - 1, 0);
    updateSelected();
  } else if (e.key === 'Tab' || e.key === 'Enter') {
    if (_popup) {
      e.preventDefault();
      apply(matches[_selectedIdx], ta, _popup._lineStart, _popup._cursor);
    }
  } else if (e.key === 'Escape') {
    hide();
  }
}

function updateSelected() {
  _popup?.querySelectorAll('.slash-item').forEach((el, i) => {
    el.classList.toggle('selected', i === _selectedIdx);
  });
}

function apply(entry, ta, lineStart, cursor) {
  const before = ta.value.slice(0, lineStart);
  const after  = ta.value.slice(cursor);
  ta.value = before + entry.prompt + after;
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
  ta.focus();
  const pos = lineStart + entry.prompt.length;
  ta.setSelectionRange(pos, pos);
  hide();
}
