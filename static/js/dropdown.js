// custom select — replaces native <select> everywhere so the UI stays ours.
// options live in el.dataset.options ("val|label;val|label"), so they can be
// swapped at runtime (mail accounts, photo albums, etc.) without re-wiring.
let _open = null;

export function initCustomDropdowns(root = document) {
  root.querySelectorAll('.custom-select').forEach(initCustomDropdown);
}

export function initCustomDropdown(el) {
  if (!el || el.dataset.dropdownReady === '1') return;
  el.dataset.dropdownReady = '1';
  el.setAttribute('role', 'combobox');
  el.setAttribute('aria-haspopup', 'listbox');
  el.setAttribute('aria-expanded', 'false');
  if (!el.hasAttribute('tabindex')) el.tabIndex = 0;

  if (!el.dataset.value) el.dataset.value = _readOptions(el)[0]?.value || '';

  Object.defineProperty(el, 'value', {
    configurable: true,
    get() { return el.dataset.value || ''; },
    set(next) {
      const opts = _readOptions(el);
      const idx = opts.findIndex(o => o.value === String(next));
      el.dataset.value = idx >= 0 ? opts[idx].value : String(next ?? '');
      _renderTrigger(el);
      if (_open?.el === el) _renderPanel(el);
    },
  });

  _renderTrigger(el);

  el.addEventListener('click', e => { e.stopPropagation(); _toggle(el); });
  el.addEventListener('keydown', e => {
    const opts = _readOptions(el);
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (_open?.el === el) _choose(el, _open.activeIndex);
      else _openDropdown(el);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (_open?.el !== el) _openDropdown(el);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      _open.activeIndex = Math.max(0, Math.min(opts.length - 1, _open.activeIndex + step));
      _renderPanel(el);
    } else if (e.key === 'Escape') {
      _close();
    }
  });
}

export function getDropdownValue(el) { return el?.dataset?.value || ''; }

export function setDropdownValue(el, value) {
  if (!el) return;
  if (el.dataset.dropdownReady !== '1') initCustomDropdown(el);
  el.value = String(value ?? '');
}

// swap the option set at runtime (and optionally the selected value)
export function populateDropdown(el, options, value) {
  if (!el) return;
  el.dataset.options = options.map(o => `${o.value}|${o.label ?? o.value}`).join(';');
  if (el.dataset.dropdownReady !== '1') initCustomDropdown(el);
  el.value = value != null ? String(value) : (options[0]?.value || '');
}

function _readOptions(el) {
  return (el.dataset.options || '')
    .split(';')
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => {
      const [value, ...labelParts] = part.split('|');
      const label = labelParts.join('|') || value;
      return { value, label };
    });
}

function _activeIndex(el) {
  const opts = _readOptions(el);
  return Math.max(0, opts.findIndex(o => o.value === el.dataset.value));
}

function _renderTrigger(el) {
  const opts = _readOptions(el);
  const label = opts.find(o => o.value === el.dataset.value)?.label || el.dataset.placeholder || 'select';
  el.innerHTML = `
    <span class="custom-select-label">${_esc(label)}</span>
    <svg class="custom-select-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  `;
}

function _toggle(el) {
  if (_open?.el === el) _close();
  else _openDropdown(el);
}

function _openDropdown(el) {
  _close();
  const panel = document.createElement('div');
  panel.className = 'custom-dropdown-panel';
  panel.setAttribute('role', 'listbox');
  document.body.appendChild(panel);
  _open = { el, panel, activeIndex: _activeIndex(el) };
  el.classList.add('open');
  el.setAttribute('aria-expanded', 'true');
  _positionPanel(el, panel);
  _renderPanel(el);
  setTimeout(() => document.addEventListener('click', _outsideClick), 0);
  window.addEventListener('resize', _repositionOpen);
  window.addEventListener('scroll', _repositionOpen, true);
}

function _renderPanel(el) {
  const panel = _open?.panel;
  if (!panel) return;
  const opts = _readOptions(el);
  panel.innerHTML = opts.map((opt, idx) => `
    <button type="button" class="custom-dropdown-option${opt.value === el.dataset.value ? ' selected' : ''}${idx === _open.activeIndex ? ' active' : ''}" data-index="${idx}" role="option" aria-selected="${opt.value === el.dataset.value}">
      ${_esc(opt.label)}
    </button>
  `).join('');
  panel.querySelectorAll('.custom-dropdown-option').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      _choose(el, Number(btn.dataset.index));
    });
  });
  panel.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
}

function _choose(el, index) {
  const opts = _readOptions(el);
  const opt = opts[index];
  if (!opt) return;
  el.dataset.value = opt.value;
  _renderTrigger(el);
  el.dispatchEvent(new Event('change', { bubbles: true }));
  _close();
  el.focus();
}

function _positionPanel(el, panel) {
  const rect = el.getBoundingClientRect();
  panel.style.left = `${rect.left}px`;
  panel.style.top = `${rect.bottom + 4}px`;
  panel.style.minWidth = `${rect.width}px`;
}

function _repositionOpen() {
  if (_open) _positionPanel(_open.el, _open.panel);
}

function _outsideClick(e) {
  if (!_open) return;
  if (_open.el.contains(e.target) || _open.panel.contains(e.target)) return;
  _close();
}

function _close() {
  if (!_open) return;
  _open.el.classList.remove('open');
  _open.el.setAttribute('aria-expanded', 'false');
  _open.panel.remove();
  _open = null;
  document.removeEventListener('click', _outsideClick);
  window.removeEventListener('resize', _repositionOpen);
  window.removeEventListener('scroll', _repositionOpen, true);
}

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
