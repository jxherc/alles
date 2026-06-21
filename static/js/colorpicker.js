// in-house color picker — HSV square + hue bar, hex field, eyedropper, recent colors,
// and harmony suggestions. wraps <input type="color"> non-invasively: the element's
// .value stays the source of truth and we dispatch 'input' so existing listeners work.
// ported from odysseus, trimmed for alles.

const LS_RECENT = 'alles-recent-colors';
const MAX_RECENT = 12;

let _popover = null;
let _input = null;
let _h = 0, _s = 100, _v = 100;
let _drag = null;
let _onOutside = null;
let _onEsc = null;

function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

function hexToRgb(hex) {
  hex = String(hex || '').replace('#', '');
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  if (!/^[0-9a-f]{6}$/i.test(hex)) return { r: 0, g: 0, b: 0 };
  const n = parseInt(hex, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(v => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');
}
function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h; const s = max === 0 ? 0 : d / max; const v = max;
  if (d === 0) h = 0;
  else if (max === r) h = ((g - b) / d + (g < b ? 6 : 0));
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return { h: h * 60, s: s * 100, v: v * 100 };
}
function hsvToRgb(h, s, v) {
  h = ((h % 360) + 360) % 360; h /= 60; s /= 100; v /= 100;
  const i = Math.floor(h), f = h - i, p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  let r, g, b;
  switch (i % 6) {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    default: r = v; g = p; b = q;
  }
  return { r: Math.round(r * 255), g: Math.round(g * 255), b: Math.round(b * 255) };
}
function hsvToHex(h, s, v) { const { r, g, b } = hsvToRgb(h, s, v); return rgbToHex(r, g, b); }
function hexToHsv(hex) { const { r, g, b } = hexToRgb(hex); return rgbToHsv(r, g, b); }

function getRecents() { try { return JSON.parse(localStorage.getItem(LS_RECENT) || '[]'); } catch { return []; } }
function addRecent(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return;
  let recents = getRecents().filter(c => c.toLowerCase() !== hex.toLowerCase());
  recents.unshift(hex.toLowerCase());
  recents = recents.slice(0, MAX_RECENT);
  try { localStorage.setItem(LS_RECENT, JSON.stringify(recents)); } catch { /* quota */ }
}

function computeSuggestions() {
  return [
    { hex: hsvToHex(_h + 180, _s, _v), label: 'Complement' },
    { hex: hsvToHex(_h + 30, _s, _v), label: 'Analogous +30' },
    { hex: hsvToHex(_h - 30, _s, _v), label: 'Analogous -30' },
    { hex: hsvToHex(_h + 150, _s, _v), label: 'Split-complement' },
    { hex: hsvToHex(_h, _s, clamp(_v > 50 ? _v - 30 : _v + 30, 10, 95)), label: 'Tone shift' },
  ];
}

function buildPopover() {
  const p = document.createElement('div');
  p.className = 'cp-popover';
  p.innerHTML = `
    <div class="cp-sl" data-drag="sl"><div class="cp-sl-white"></div><div class="cp-sl-black"></div><div class="cp-sl-handle"></div></div>
    <div class="cp-hue" data-drag="hue"><div class="cp-hue-handle"></div></div>
    <div class="cp-row">
      <div class="cp-preview"></div>
      <input type="text" class="cp-hex" maxlength="7" spellcheck="false" autocomplete="off">
      <button class="cp-eyedropper" title="eyedropper" type="button">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 22l4-4m0 0l3-3 5 5-3 3a2 2 0 01-2.8 0l-2.2-2.2a2 2 0 010-2.8z"/><path d="M14 8l3-3a3 3 0 014.2 4.2l-3 3-4.2-4.2z"/></svg>
      </button>
    </div>
    <div class="cp-section-label">suggestions</div>
    <div class="cp-swatches cp-suggestions"></div>
    <div class="cp-section-label">recent</div>
    <div class="cp-swatches cp-recent"></div>`;
  document.body.appendChild(p);
  wireHandlers(p);
  return p;
}

function syncUI() {
  if (!_popover) return;
  const sl = _popover.querySelector('.cp-sl');
  const slH = _popover.querySelector('.cp-sl-handle');
  const hueH = _popover.querySelector('.cp-hue-handle');
  const hex = _popover.querySelector('.cp-hex');
  const preview = _popover.querySelector('.cp-preview');
  sl.style.background = hsvToHex(_h, 100, 100);
  slH.style.left = _s + '%';
  slH.style.top = (100 - _v) + '%';
  hueH.style.left = (_h / 360 * 100) + '%';
  const current = hsvToHex(_h, _s, _v);
  preview.style.background = current;
  if (document.activeElement !== hex) hex.value = current;
  _popover.querySelector('.cp-suggestions').innerHTML = computeSuggestions().map(s =>
    `<button class="cp-swatch" title="${s.label}: ${s.hex}" data-hex="${s.hex}" style="background:${s.hex}"></button>`).join('');
  const recs = getRecents();
  _popover.querySelector('.cp-recent').innerHTML = recs.length
    ? recs.map(h => `<button class="cp-swatch" title="${h}" data-hex="${h}" style="background:${h}"></button>`).join('')
    : '<div class="cp-recent-empty">(none yet)</div>';
}

function applyToInput(push) {
  if (!_input) return;
  _input.value = hsvToHex(_h, _s, _v);
  if (push) _input.dispatchEvent(new Event('input', { bubbles: true }));
  syncUI();
}
function setFromHex(hex) { const v = hexToHsv(hex); _h = v.h; _s = v.s; _v = v.v; }

let _windowPointerInstalled = false;
function _installWindowPointer() {
  if (_windowPointerInstalled) return;
  _windowPointerInstalled = true;
  window.addEventListener('pointermove', e => { if (_drag) handleDrag(e); });
  window.addEventListener('pointerup', () => { if (_drag) { _drag = null; commitCurrent(); } });
}

function wireHandlers(p) {
  const sl = p.querySelector('.cp-sl'), hue = p.querySelector('.cp-hue'), hex = p.querySelector('.cp-hex'), eye = p.querySelector('.cp-eyedropper');
  const onDown = type => e => { _drag = type; handleDrag(e); e.preventDefault(); };
  sl.addEventListener('pointerdown', onDown('sl'));
  hue.addEventListener('pointerdown', onDown('hue'));
  _installWindowPointer();
  hex.addEventListener('input', () => {
    let v = hex.value.trim(); if (!v.startsWith('#')) v = '#' + v;
    if (/^#[0-9a-f]{6}$/i.test(v)) { setFromHex(v); applyToInput(true); }
  });
  hex.addEventListener('keydown', e => { if (e.key === 'Enter') { commitCurrent(); close(); } if (e.key === 'Escape') close(); });
  p.addEventListener('click', e => {
    const sw = e.target.closest('.cp-swatch');
    if (sw && sw.dataset.hex) { setFromHex(sw.dataset.hex); applyToInput(true); commitCurrent(); }
  });
  if (window.EyeDropper) {
    eye.addEventListener('click', async ev => {
      ev.stopPropagation();
      const wasOnOutside = _onOutside; _detachOutsideHandlers();
      try { const r = await new window.EyeDropper().open(); if (r && r.sRGBHex) { setFromHex(r.sRGBHex); applyToInput(true); commitCurrent(); } } catch { /* cancelled */ }
      if (wasOnOutside && _popover) requestAnimationFrame(() => {
        if (!_popover) return;
        _onOutside = wasOnOutside;
        _onEsc = e => { if (e.key === 'Escape') { e.preventDefault(); close(); } };
        document.addEventListener('click', _onOutside, true);
        document.addEventListener('keydown', _onEsc, true);
      });
    });
  } else { eye.disabled = true; eye.style.opacity = '0.3'; eye.title = 'eyedropper not supported here'; }
}

function handleDrag(e) {
  if (_drag === 'sl') {
    const r = _popover.querySelector('.cp-sl').getBoundingClientRect();
    _s = clamp((e.clientX - r.left) / r.width, 0, 1) * 100;
    _v = (1 - clamp((e.clientY - r.top) / r.height, 0, 1)) * 100;
    applyToInput(true);
  } else if (_drag === 'hue') {
    const r = _popover.querySelector('.cp-hue').getBoundingClientRect();
    _h = clamp((e.clientX - r.left) / r.width, 0, 1) * 360;
    applyToInput(true);
  }
}
function commitCurrent() { if (!_input) return; addRecent(_input.value); syncUI(); }

function position(p, anchor) {
  const rect = anchor.getBoundingClientRect(), pRect = p.getBoundingClientRect();
  let left = rect.left, top = rect.bottom + 6;
  if (left + pRect.width > window.innerWidth - 8) left = window.innerWidth - pRect.width - 8;
  if (top + pRect.height > window.innerHeight - 8) top = rect.top - pRect.height - 6;
  if (left < 8) left = 8; if (top < 8) top = 8;
  p.style.left = left + 'px'; p.style.top = top + 'px';
}

function _detachOutsideHandlers() {
  if (_onOutside) { document.removeEventListener('click', _onOutside, true); document.removeEventListener('pointerdown', _onOutside, true); _onOutside = null; }
  if (_onEsc) { document.removeEventListener('keydown', _onEsc, true); _onEsc = null; }
}
function _destroyPopover() {
  _detachOutsideHandlers();
  if (_popover && _popover.parentNode) _popover.parentNode.removeChild(_popover);
  _popover = null; _input = null; _drag = null;
}

function open(inputEl) {
  _destroyPopover();
  _popover = buildPopover();
  _input = inputEl;
  setFromHex(inputEl.value || '#000000');
  requestAnimationFrame(() => { if (_popover && _input) position(_popover, _input); });
  syncUI();
  _onOutside = e => {
    if (_drag || !_popover) return;
    if (_popover.contains(e.target) || e.target === _input) return;
    close();
  };
  _onEsc = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } };
  requestAnimationFrame(() => {
    document.addEventListener('click', _onOutside, true);
    document.addEventListener('pointerdown', _onOutside, true);
    document.addEventListener('keydown', _onEsc, true);
  });
}
function close() { _destroyPopover(); }

const _NATIVE_VALUE_DESC = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
function _syncSwatch(el) { const v = _NATIVE_VALUE_DESC.get.call(el); if (/^#[0-9a-f]{6}$/i.test(v || '')) el.style.background = v; }

export function attachColorPicker(inputEl) {
  if (!inputEl || inputEl.dataset.cpAttached === '1') return;
  inputEl.dataset.cpAttached = '1';
  const initial = inputEl.value || inputEl.getAttribute('value') || '#000000';
  inputEl.type = 'text'; inputEl.readOnly = true; inputEl.classList.add('cp-swatch-input');
  Object.defineProperty(inputEl, 'value', {
    configurable: true,
    get() { return _NATIVE_VALUE_DESC.get.call(this); },
    set(v) { _NATIVE_VALUE_DESC.set.call(this, v); _syncSwatch(this); },
  });
  inputEl.value = initial;
  inputEl.addEventListener('mousedown', e => {
    e.preventDefault(); e.stopPropagation();
    if (_input === inputEl && _popover) close(); else open(inputEl);
  });
  inputEl.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); });
}

export function initColorPickers(root = document) { root.querySelectorAll('input[type="color"]').forEach(attachColorPicker); }
