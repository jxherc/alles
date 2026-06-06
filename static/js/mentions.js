// @-mention file picker for the composer. type @ then a filename.
import { getActiveId } from './sessions.js';

let _menu = null, _items = [], _sel = 0, _range = null, _ta = null, _t = 0;

export function initMentions(ta) {
  if (!ta) return;
  _ta = ta;
  ta.addEventListener('input', _debouncedInput);
  ta.addEventListener('keydown', _onKey, true);   // capture — beat the send/slash handlers
  ta.addEventListener('blur', () => setTimeout(close, 150));
}

function _token() {
  const v = _ta.value, pos = _ta.selectionStart;
  let i = pos - 1;
  while (i >= 0 && /[\w./\\-]/.test(v[i])) i--;
  if (v[i] !== '@') return null;
  if (i > 0 && !/\s/.test(v[i - 1])) return null;   // @ must start a word
  return { start: i, end: pos, q: v.slice(i + 1, pos) };
}

function _debouncedInput() {
  clearTimeout(_t);
  _t = setTimeout(_onInput, 90);
}

async function _onInput() {
  const tok = _token();
  if (!tok) return close();
  const sid = getActiveId() || '';
  let files = [];
  try {
    const r = await fetch(`/api/agent/files?q=${encodeURIComponent(tok.q)}&session_id=${sid}&limit=20`);
    files = (await r.json()).files || [];
  } catch { return close(); }
  if (!files.length) return close();
  _items = files; _sel = 0; _range = tok;
  _open();
}

function _onKey(e) {
  if (!_menu) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); _sel = (_sel + 1) % _items.length; _render(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _sel = (_sel - 1 + _items.length) % _items.length; _render(); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); _choose(_items[_sel]); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
}

function _choose(path) {
  if (!_range) return;
  const v = _ta.value;
  const before = v.slice(0, _range.start);
  const ins = '@' + path + ' ';
  _ta.value = before + ins + v.slice(_range.end);
  const caret = (before + ins).length;
  _ta.setSelectionRange(caret, caret);
  _ta.dispatchEvent(new Event('input'));
  close();
  _ta.focus();
}

function _open() {
  if (!_menu) { _menu = document.createElement('div'); _menu.className = 'mention-menu'; document.body.appendChild(_menu); }
  _render();
  const r = _ta.getBoundingClientRect();
  _menu.style.left = r.left + 'px';
  _menu.style.bottom = (window.innerHeight - r.top + 6) + 'px';
  _menu.style.width = Math.min(r.width, 440) + 'px';
}

function _render() {
  _menu.innerHTML = _items.map((f, i) =>
    `<div class="mention-item${i === _sel ? ' active' : ''}" data-i="${i}">${_esc(f)}</div>`).join('');
  _menu.querySelectorAll('.mention-item').forEach(el =>
    el.addEventListener('mousedown', e => { e.preventDefault(); _choose(_items[+el.dataset.i]); }));
  _menu.querySelector('.mention-item.active')?.scrollIntoView({ block: 'nearest' });
}

function close() { _menu?.remove(); _menu = null; _items = []; _range = null; }

function _esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
