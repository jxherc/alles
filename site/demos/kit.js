// shared parts for the working copies. each app's module builds its screen from these, inside a
// fixed canvas (the app at 960 by 600) that the page scales to fit.
import { icon, appGlyph } from './icons.js';

export const reduced = matchMedia('(prefers-reduced-motion: reduce)');

// h('div', { class: 'x', onclick: fn, 'aria-label': 'y' }, 'text', child)
export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style') el.style.cssText = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

export function ic(name, size) {
  const wrap = document.createElement('span');
  wrap.innerHTML = icon(name, size ? { size } : {});
  return wrap.firstChild;
}

export function glyph(app) {
  const wrap = document.createElement('span');
  wrap.innerHTML = appGlyph(app);
  return wrap.firstChild;
}

const loaded = new Set();
export function css(name) {
  if (loaded.has(name)) return;
  loaded.add(name);
  document.head.append(h('link', { rel: 'stylesheet', href: new URL(`./${name}.css`, import.meta.url).href }));
}

// the app's top bar: its name with the switcher chevron, then its tabs
export function topbar({ app, tabs = [], selected, onTab, right }) {
  const buttons = tabs.map((t) => h('button', { type: 'button', class: 'dm-tab', role: 'tab', 'aria-selected': String(t === selected), tabindex: t === selected ? '0' : '-1', text: t }));
  const select = (name, focus) => {
    buttons.forEach((b) => {
      const on = b.textContent === name;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    onTab?.(name);
  };
  buttons.forEach((b, i) => {
    b.addEventListener('click', () => select(b.textContent));
    b.addEventListener('keydown', (e) => {
      const go = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: buttons.length - 1 }[e.key];
      if (go === undefined) return;
      e.preventDefault();
      select(buttons[(go + buttons.length) % buttons.length].textContent, true);
    });
  });
  const el = h('div', { class: 'dm-top' },
    h('span', { class: 'dm-app' }, app, ic('chevron-down')),
    tabs.length ? h('div', { class: 'dm-tabs', role: 'tablist', 'aria-label': app }, buttons) : null,
    h('span', { class: 'dm-spacer' }),
    right || null);
  return { el, select };
}

// a small list menu like the app's dropdown, opened from a button inside the canvas
export function menu(button, items, onPick) {
  let root = null;
  let list = null;
  let active = 0;
  const close = (focus) => {
    if (!list) return;
    list.remove();
    list = null;
    button.setAttribute('aria-expanded', 'false');
    if (focus) button.focus();
  };
  const setActive = (i) => {
    active = (i + items.length) % items.length;
    [...list.children].forEach((li, n) => li.classList.toggle('active', n === active));
  };
  const open = () => {
    // looked up when it opens, so the button may be built before it's in the canvas
    root = button.closest('.dm');
    list = h('ul', { class: 'dm-menu', role: 'listbox', tabindex: '-1' },
      items.map((it, i) => h('li', { role: 'option', onclick: () => { onPick(it); close(true); }, onpointermove: () => setActive(i) }, it)));
    const b = button.getBoundingClientRect();
    const r = root.getBoundingClientRect();
    const s = r.width / root.offsetWidth;
    list.style.left = (b.left - r.left) / s + 'px';
    list.style.top = (b.bottom - r.top) / s + 4 + 'px';
    root.append(list);
    button.setAttribute('aria-expanded', 'true');
    setActive(Math.max(0, items.indexOf(button.dataset.value)));
    list.focus({ preventScroll: true });
    list.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(items[active]); close(true); }
      else if (e.key === 'Escape') { e.preventDefault(); close(true); }
      else if (e.key === 'Tab') close(false);
    });
  };
  button.setAttribute('aria-haspopup', 'listbox');
  button.setAttribute('aria-expanded', 'false');
  button.addEventListener('click', () => (list ? close(true) : open()));
  document.addEventListener('pointerdown', (e) => { if (list && !list.contains(e.target) && !button.contains(e.target)) close(false); });
}

// a short message at the bottom of the canvas that goes away by itself
export function toast(root, text) {
  root.querySelector('.dm-toast')?.remove();
  const t = h('div', { class: 'dm-toast', role: 'status', text });
  root.append(t);
  setTimeout(() => t.remove(), 2400);
}

// made up numbers that wander inside a range
export const walk = (v, step, lo, hi) => Math.min(hi, Math.max(lo, v + (Math.random() - 0.5) * step));

// a sparkline into an svg with viewBox 0 0 100 32 holding path.area and path.line
export function spark(svg, values, max) {
  const n = values.length - 1;
  const pts = values.map((v, i) => `${((i / n) * 100).toFixed(2)},${(32 - (v / max) * 30).toFixed(2)}`);
  svg.querySelector('.line').setAttribute('d', 'M' + pts.join('L'));
  svg.querySelector('.area').setAttribute('d', 'M0,32L' + pts.join('L') + 'L100,32Z');
}
export const sparkSvg = () => {
  const wrap = document.createElement('span');
  wrap.innerHTML = '<svg class="dm-spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true"><path class="area"/><path class="line"/></svg>';
  return wrap.firstChild;
};

// run tick every ms while el is on screen, the tab is visible and motion is welcome
export function live(el, tick, ms = 1500) {
  let seen = false;
  new IntersectionObserver(([e]) => { seen = e.isIntersecting; }).observe(el);
  const state = { on: !reduced.matches };
  setInterval(() => { if (state.on && seen && !document.hidden) tick(); }, ms);
  return state;
}
