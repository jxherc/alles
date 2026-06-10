// custom date / datetime picker — replaces native <input type=datetime-local|date>.
// a .date-input div carries data-type="date|datetime" and data-value; .value
// reads/writes the same strings the backend expects (YYYY-MM-DD / YYYY-MM-DDTHH:MM).
let _open = null;

export function initDatePickers(root = document) {
  root.querySelectorAll('.date-input').forEach(initDatePicker);
}

export function initDatePicker(el) {
  if (!el || el.dataset.dpReady === '1') return;
  el.dataset.dpReady = '1';
  el.tabIndex = 0;
  Object.defineProperty(el, 'value', {
    configurable: true,
    get() { return el.dataset.value || ''; },
    set(v) { el.dataset.value = v || ''; _trigger(el); if (_open?.el === el) _render(el); },
  });
  _trigger(el);
  el.addEventListener('click', e => { e.stopPropagation(); _toggle(el); });
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _toggle(el); }
    else if (e.key === 'Escape') _close();
  });
}

export const getDateValue = el => el?.dataset?.value || '';
export function setDateValue(el, v) { if (!el) return; if (el.dataset.dpReady !== '1') initDatePicker(el); el.value = v || ''; }

const _isDate = el => el.dataset.type === 'date';
const _z = n => String(n).padStart(2, '0');

function _parse(el) {
  const v = el.dataset.value;
  let dt = v ? new Date(v.length <= 10 ? v + 'T00:00' : v) : new Date();
  if (isNaN(dt)) dt = new Date();
  return { y: dt.getFullYear(), mo: dt.getMonth(), d: dt.getDate(), h: dt.getHours(), mi: dt.getMinutes() };
}
function _fmt(p, isDate) {
  const date = `${p.y}-${_z(p.mo + 1)}-${_z(p.d)}`;
  return isDate ? date : `${date}T${_z(p.h)}:${_z(p.mi)}`;
}
function _display(v, isDate) {
  const dt = new Date(v.length <= 10 ? v + 'T00:00' : v);
  if (isNaN(dt)) return v;
  const d = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return isDate ? d : `${d}, ${dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
}
function _trigger(el) {
  const v = el.dataset.value;
  el.innerHTML = `<span class="date-input-label${v ? '' : ' ph'}">${v ? _display(v, _isDate(el)) : (el.dataset.ph || 'pick a date')}</span>` +
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`;
}

function _toggle(el) { if (_open?.el === el) _close(); else _openPanel(el); }

function _openPanel(el) {
  _close();
  const panel = document.createElement('div');
  panel.className = 'date-panel';
  document.body.appendChild(panel);
  const cur = _parse(el);
  _open = { el, panel, view: { y: cur.y, mo: cur.mo }, sel: cur };
  _render(el);   // render first so the panel has a measurable height
  setTimeout(() => document.addEventListener('click', _outside), 0);
}

function _render(el) {
  const { panel, view, sel } = _open;
  const isDate = _isDate(el);
  const monthName = new Date(view.y, view.mo, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  const first = new Date(view.y, view.mo, 1).getDay();
  const days = new Date(view.y, view.mo + 1, 0).getDate();
  let grid = ['su', 'mo', 'tu', 'we', 'th', 'fr', 'sa'].map(d => `<span class="dp-dow">${d}</span>`).join('');
  for (let i = 0; i < first; i++) grid += '<span></span>';
  for (let d = 1; d <= days; d++) {
    const on = sel.y === view.y && sel.mo === view.mo && sel.d === d;
    grid += `<button type="button" class="dp-day${on ? ' sel' : ''}" data-d="${d}">${d}</button>`;
  }
  const time = isDate ? '' : `
    <div class="dp-time">
      <button type="button" class="dp-step" data-step="h-1">‹</button><span class="dp-tv">${_z(sel.h)}</span><button type="button" class="dp-step" data-step="h1">›</button>
      <span class="dp-colon">:</span>
      <button type="button" class="dp-step" data-step="mi-1">‹</button><span class="dp-tv">${_z(sel.mi)}</span><button type="button" class="dp-step" data-step="mi1">›</button>
    </div>`;
  panel.innerHTML = `
    <div class="dp-head"><button type="button" class="dp-nav" data-nav="-1">‹</button><span>${monthName}</span><button type="button" class="dp-nav" data-nav="1">›</button></div>
    <div class="dp-grid">${grid}</div>${time}
    <div class="dp-foot"><button type="button" class="dp-clear">clear</button><button type="button" class="dp-now">now</button></div>`;

  panel.querySelectorAll('.dp-nav').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    view.mo += +b.dataset.nav;
    if (view.mo < 0) { view.mo = 11; view.y--; }
    if (view.mo > 11) { view.mo = 0; view.y++; }
    _render(el);
  }));
  panel.querySelectorAll('.dp-day').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    sel.y = view.y; sel.mo = view.mo; sel.d = +b.dataset.d;
    _commit(el);
    if (isDate) _close(); else _render(el);
  }));
  panel.querySelectorAll('.dp-step').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    const s = b.dataset.step;
    if (s.startsWith('h')) sel.h = (sel.h + (s === 'h1' ? 1 : 23)) % 24;
    else sel.mi = (sel.mi + (s === 'mi1' ? 1 : 59)) % 60;
    _commit(el); _render(el);
  }));
  panel.querySelector('.dp-clear').addEventListener('click', e => { e.stopPropagation(); el.value = ''; _close(); });
  panel.querySelector('.dp-now').addEventListener('click', e => {
    e.stopPropagation();
    const n = new Date();
    Object.assign(sel, { y: n.getFullYear(), mo: n.getMonth(), d: n.getDate(), h: n.getHours(), mi: n.getMinutes() });
    view.y = sel.y; view.mo = sel.mo;
    _commit(el);
    if (isDate) _close(); else _render(el);
  });

  _position(el, panel);   // after content exists — height changes with the month
}

function _commit(el) {
  el.dataset.value = _fmt(_open.sel, _isDate(el));
  _trigger(el);
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function _position(el, panel) {
  const r = el.getBoundingClientRect();
  const margin = 8;
  const h = panel.offsetHeight || 300;
  const w = panel.offsetWidth || 250;
  const spaceBelow = window.innerHeight - r.bottom - margin;
  // flip above the trigger when there isn't room below (footer forms etc.)
  const top = (h <= spaceBelow || spaceBelow >= r.top - margin) ? r.bottom + 4 : r.top - h - 4;
  panel.style.top = `${Math.max(margin, top)}px`;
  panel.style.left = `${Math.max(margin, Math.min(r.left, window.innerWidth - w - margin))}px`;
}
function _outside(e) {
  if (!_open) return;
  if (_open.el.contains(e.target) || _open.panel.contains(e.target)) return;
  _close();
}
function _close() {
  if (!_open) return;
  _open.panel.remove();
  _open = null;
  document.removeEventListener('click', _outside);
}
