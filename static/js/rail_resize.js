// a sidebar you can drag wider or narrower (decision 0054, from aide code's projects rail).
// the handle is a role=separator strip on the rail's trailing edge: drag it with a mouse, pen or
// finger, arrow keys step 1rem (shift 3), home and end go to the ends, double click goes back to the
// app's own width. the width is in rem, so it grows with the type, and is saved per browser.
// below `media` (phones, and tablets where apps stack the rail) there's no handle and the app's own layout wins.
import { t } from './i18n.js';

const remPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
const read = key => { try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch { return {}; } };
const write = (key, patch) => {
  try { localStorage.setItem(key, JSON.stringify({ ...read(key), ...patch })); } catch { /* private mode */ }
};

// host: where the width variable goes (the rail's grid or flex parent, or the rail itself).
// handle: an existing separator (aide code); otherwise one is made. inside: the handle lives in the
// rail (rails that are positioned and never rebuild their content); otherwise it sits over the rail's
// edge from the rail's positioned ancestor, so rails a module fills with innerHTML keep it.
// prop + sizeRail: the css variable to set, and whether the shared rule sizes the rail itself.
export function makeResizableRail({
  rail, host = rail, handle = null, key, min = 11, max = 28, def = null, label = '', labelKey = '',
  inside = false, prop = '--k-rail-w', sizeRail = true, media = '(min-width: 761px)', onChange = null,
}) {
  if (!rail || rail._kRail) return rail?._kRail || null;
  const wide = typeof matchMedia === 'function' ? matchMedia(media) : { matches: true, addEventListener() {} };
  let width = Number(read(key).width) || null;
  if (!handle) {
    handle = document.createElement('div');
    handle.className = 'k-rail-resize';
    if (inside) handle.dataset.inside = '';
    (inside ? rail : document.body).append(handle);
  }
  if (inside) rail.dataset.kRailInside = '';
  if (!rail.id) rail.id = `k-rail-${key.replace(/[^\w-]/g, '-')}`;
  handle.setAttribute('role', 'separator');
  handle.setAttribute('aria-orientation', 'vertical');
  handle.setAttribute('aria-controls', rail.id);
  handle.setAttribute('aria-valuemin', String(min));
  handle.setAttribute('aria-valuemax', String(max));
  handle.tabIndex = 0;
  if (label || labelKey) handle.setAttribute('aria-label', label || t(labelKey));
  // the catalog pass relabels it once the language loads
  if (labelKey) handle.dataset.i18nAriaLabel = labelKey;

  // a side rail is taller than wide; where an app stacks its rail over the content there's no handle
  const shown = () => {
    const r = rail.getBoundingClientRect();
    return wide.matches && r.width > 0 && r.height > r.width;
  };
  const measured = () => rail.getBoundingClientRect().width / remPx();

  // an outside handle follows the rail's edge inside the rail's positioned ancestor
  function place() {
    const on = shown();
    handle.hidden = !on;
    if (!on || inside) { if (on) syncValue(); return; }
    const parent = rail.offsetParent || document.body;
    if (handle.parentElement !== parent) parent.append(handle);
    const r = rail.getBoundingClientRect(), p = parent.getBoundingClientRect();
    handle.style.left = `${r.right - p.left - parent.clientLeft + parent.scrollLeft}px`;
    handle.style.top = `${r.top - p.top - parent.clientTop + parent.scrollTop}px`;
    handle.style.height = `${r.height}px`;
    // a grid parent can anchor an absolute child to a cell instead of its box, so measure and correct
    const at = handle.getBoundingClientRect();
    const dx = at.left + at.width / 2 - r.right, dy = at.top - r.top;
    if (Math.abs(dx) > 0.5) handle.style.left = `${parseFloat(handle.style.left) - dx}px`;
    if (Math.abs(dy) > 0.5) handle.style.top = `${parseFloat(handle.style.top) - dy}px`;
    syncValue();
  }

  // before the first drag the value is whatever width the app gave the rail
  function syncValue() {
    const now = width ?? (shown() ? Math.round(measured() * 4) / 4 : def ?? min);
    handle.setAttribute('aria-valuenow', String(now));
    handle.setAttribute('aria-valuetext', t('shell.rail_width', { n: Math.round(now * remPx()) }));
  }

  function apply(save = true) {
    if (width != null) width = Math.round(Math.min(max, Math.max(min, width)) * 4) / 4;
    const sized = width != null && wide.matches;
    if (sized) host.style.setProperty(prop, `${width}rem`);
    else host.style.removeProperty(prop);
    if (sizeRail && sized) rail.dataset.kRailSized = '';
    else delete rail.dataset.kRailSized;
    if (save) write(key, { width });
    place();
    syncValue();
    onChange?.(width);
  }

  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    try { handle.setPointerCapture(event.pointerId); } catch { /* a pointer the page didn't see go down */ }
    document.documentElement.dataset.railResizing = 'true';
    handle.dataset.active = '';
    const left = rail.getBoundingClientRect().left;
    const move = e => { width = (e.clientX - left) / remPx(); apply(false); };
    const done = () => {
      handle.removeEventListener('pointermove', move);
      delete document.documentElement.dataset.railResizing;
      delete handle.dataset.active;
      apply();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', done, { once: true });
    handle.addEventListener('pointercancel', done, { once: true });
  });
  // back to the app's own width (or the given default)
  handle.addEventListener('dblclick', () => { width = def; apply(); });
  handle.addEventListener('keydown', event => {
    const base = width ?? measured();
    const step = event.shiftKey ? 3 : 1;
    const next = { ArrowLeft: base - step, ArrowRight: base + step, Home: min, End: max }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    width = next;
    apply();
  });

  wide.addEventListener('change', () => apply(false));
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => place()).observe(rail);
  addEventListener('resize', place);
  // the rail can move without changing size (a banner above it), so look again when the pointer comes near
  rail.addEventListener('pointerenter', place);
  apply(false);
  rail._kRail = { apply, place, handle, get width() { return width; }, set width(v) { width = v; apply(); } };
  return rail._kRail;
}
