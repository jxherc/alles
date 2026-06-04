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

  const options = _readOptions(el);
  el._customOptions = options;
  let value = el.dataset.value || options[0]?.value || '';
  el.dataset.value = value;
  let activeIndex = Math.max(0, options.findIndex(o => o.value === value));

  Object.defineProperty(el, 'value', {
    configurable: true,
    get() {
      return value;
    },
    set(next) {
      const idx = options.findIndex(o => o.value === String(next));
      value = idx >= 0 ? options[idx].value : String(next || '');
      el.dataset.value = value;
      activeIndex = Math.max(0, options.findIndex(o => o.value === value));
      _renderTrigger(el, options, value);
      if (_open?.el === el) _renderPanel(el, options, activeIndex);
    },
  });

  _renderTrigger(el, options, value);

  el.addEventListener('click', e => {
    e.stopPropagation();
    _toggle(el, options, activeIndex);
  });

  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (_open?.el === el) _choose(el, options, activeIndex);
      else _toggle(el, options, activeIndex);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (_open?.el !== el) _openDropdown(el, options, activeIndex);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      activeIndex = Math.max(0, Math.min(options.length - 1, activeIndex + step));
      if (_open?.el === el) {
        _open.activeIndex = activeIndex;
        _renderPanel(el, options, activeIndex);
      }
    } else if (e.key === 'Escape') {
      _close();
    }
  });

  el.addEventListener('custom-dropdown-select', e => {
    activeIndex = e.detail.index;
  });
}

export function getDropdownValue(el) {
  return el?.dataset?.value || '';
}

export function setDropdownValue(el, value) {
  if (!el) return;
  if (!el.dataset.dropdownReady) initCustomDropdown(el);
  const options = el._customOptions || _readOptions(el);
  const next = String(value || '');
  const match = options.find(o => o.value === next);
  el.dataset.value = match ? match.value : next;
  try { el.value = el.dataset.value; } catch {}
  _renderTrigger(el, options, el.dataset.value);
  if (_open?.el === el) {
    const idx = Math.max(0, options.findIndex(o => o.value === el.dataset.value));
    _renderPanel(el, options, idx);
  }
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

function _renderTrigger(el, options, value) {
  const label = options.find(o => o.value === value)?.label || value || 'select';
  el.innerHTML = `
    <span class="custom-select-label">${_esc(label)}</span>
    <svg class="custom-select-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  `;
}

function _toggle(el, options, activeIndex) {
  if (_open?.el === el) _close();
  else _openDropdown(el, options, activeIndex);
}

function _openDropdown(el, options, activeIndex) {
  _close();
  const panel = document.createElement('div');
  panel.className = 'custom-dropdown-panel';
  panel.setAttribute('role', 'listbox');
  document.body.appendChild(panel);
  _open = { el, panel, activeIndex };
  el.classList.add('open');
  el.setAttribute('aria-expanded', 'true');
  _positionPanel(el, panel);
  _renderPanel(el, options, activeIndex);
  setTimeout(() => document.addEventListener('click', _outsideClick), 0);
  window.addEventListener('resize', _repositionOpen);
  window.addEventListener('scroll', _repositionOpen, true);
}

function _renderPanel(el, options, activeIndex) {
  const panel = _open?.panel;
  if (!panel) return;
  panel.innerHTML = options.map((opt, idx) => `
    <button type="button" class="custom-dropdown-option${opt.value === el.value ? ' selected' : ''}${idx === activeIndex ? ' active' : ''}" data-index="${idx}" role="option" aria-selected="${opt.value === el.value}">
      ${_esc(opt.label)}
    </button>
  `).join('');
  panel.querySelectorAll('.custom-dropdown-option').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      _choose(el, options, Number(btn.dataset.index));
    });
  });
  panel.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
}

function _choose(el, options, index) {
  const opt = options[index];
  if (!opt) return;
  el.dataset.value = opt.value;
  try { el.value = opt.value; } catch {}
  _renderTrigger(el, options, opt.value);
  el.dispatchEvent(new CustomEvent('custom-dropdown-select', { detail: { index } }));
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
