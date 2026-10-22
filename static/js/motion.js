// motion for the revamp (decision 0040): controls give under the pointer, one pill slides to
// whatever is picked, a view settles in when it opens, numbers count up. reduced motion
// turns every one of these off; the pill still sits behind the picked item, it just jumps.

// util.js imports this under node for tests, so nothing here may assume a page
const page = typeof document !== 'undefined' && typeof MutationObserver !== 'undefined';
const reduce = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : { matches: true };
// automated browsers (the gates) read text mid-count, so they get the final numbers at once
const still = () => reduce.matches || (typeof navigator !== 'undefined' && navigator.webdriver === true);
const EASE = 'cubic-bezier(.23, 1, .32, 1)';
const SPRING = 'linear(0, .009, .035 2.1%, .141 4.4%, .723 12.9%, .938 16.7%, 1.017 20.5%, 1.043 24.5%, 1.035 28.4%, 1.007 36%, .998 41.2%, .996 46.9%, 1)';

// ── press ──────────────────────────────────────────────────────────────────────
const PRESSABLE = 'button, [role="button"], [role="tab"], [role="menuitem"], [role="menuitemradio"], [role="option"], [role="switch"], [role="checkbox"], a.btn, summary';
let pressed = null;

function pressDown(el) {
  if (!el || still() || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
  if (el.closest('[contenteditable="true"], .xterm')) return;
  const w = el.getBoundingClientRect().width || 1;
  // small things give more: 0.965 at 100px, about 0.994 for a full-width row
  const to = 1 - Math.min(0.035, 5 / w);
  release();
  el._press?.cancel();
  el._press = el.animate([{ scale: 1 }, { scale: to }], { duration: 120, easing: EASE, fill: 'forwards' });
  pressed = el;
}

function release() {
  const el = pressed;
  pressed = null;
  if (!el || !el._press) return;
  const from = getComputedStyle(el).scale;
  el._press.cancel();
  el._press = null;
  if (!el.isConnected || from === 'none' || from === '1') return;
  el.animate([{ scale: from }, { scale: 1 }], { duration: 380, easing: SPRING });
}

// ── the sliding pill ─────────────────────────────────────────────────────────
// a group is the parent of two or more of these items with exactly one picked. the pill is the
// group's ::before (revamp.css), moved through --pill-* so no element or class is added to items
const ITEM = '[role="tab"], .aide-mode-nav > button, .seg-opt, .tasks-tab, .te-seg > button, .theme-mode-btn, .s-nav-item, .health-chip, .read-chip, .mem-policy-btn, .andromeda-tab';
const PICKED = '[aria-selected="true"], [aria-pressed="true"], [aria-checked="true"], [aria-current="page"], [aria-current="true"], .active';
const TINT = /chip|policy/;
const skipped = new WeakSet();

function pillFor(group) {
  const items = [...group.children].filter(c => c.matches(ITEM));
  if (items.length < 2) return;
  const picked = items.filter(c => c.matches(PICKED));
  if (!group.classList.contains('has-pill')) {
    if (skipped.has(group)) return;
    // a group that already draws its own ::before keeps it
    if (getComputedStyle(group, '::before').content !== 'none' || group.closest('[data-no-pill]')) { skipped.add(group); return; }
    group.classList.add('has-pill');
    if (getComputedStyle(group).position === 'static') group.classList.add('pill-pos');
    if (TINT.test(items[0].className)) group.dataset.pill = 'tint';
  }
  const on = picked.length === 1 ? picked[0] : null;
  if (!on || !on.offsetWidth) { group.style.setProperty('--pill-o', '0'); return; }
  const s = group.style;
  // a row of tall tabs gets a pill 4px inside the 44px target, so it reads as a tab, not a block
  const row = items[0].offsetTop === items[1].offsetTop;
  const inset = row && on.offsetHeight >= 40 ? 4 : 0;
  s.setProperty('--pill-x', `${on.offsetLeft}px`);
  s.setProperty('--pill-y', `${on.offsetTop + inset}px`);
  s.setProperty('--pill-w', `${on.offsetWidth}px`);
  s.setProperty('--pill-h', `${on.offsetHeight - inset * 2}px`);
  s.setProperty('--pill-r', getComputedStyle(on).borderRadius);
  s.setProperty('--pill-o', '1');
  // the first placement jumps; after that it slides
  if (!group.dataset.pillReady) requestAnimationFrame(() => { group.dataset.pillReady = '1'; });
}

let queued = false;
let lastRun = 0;
function placePills() {
  if (queued) return;
  queued = true;
  const wait = Math.max(0, 80 - (performance.now() - lastRun));
  setTimeout(() => requestAnimationFrame(() => {
    queued = false;
    lastRun = performance.now();
    const groups = new Set();
    for (const item of document.querySelectorAll(ITEM)) if (item.parentElement) groups.add(item.parentElement);
    groups.forEach(pillFor);
    watcher?.takeRecords();   // our own --pill-* and class writes are not news
  }), wait);
}

// ── views settle in ──────────────────────────────────────────────────────────
export function enterView(root) {
  if (!root || still()) return;
  // opacity only: a translate here would carry the view's fixed children with it
  root.animate([{ opacity: 0.55 }, { opacity: 1 }], { duration: 260, easing: EASE });
}

// ── numbers count up ─────────────────────────────────────────────────────────
// countTo(el, 4078.44, n => fmt(n)): the final text is set at once for readers and copy;
// only what's painted moves
export function countTo(el, to, format = n => String(Math.round(n))) {
  if (!el) return;
  const done = format(to);
  if (still() || !Number.isFinite(to)) { el.textContent = done; return; }
  el.setAttribute('aria-label', done);
  const t0 = performance.now();
  const step = t => {
    const k = Math.min(1, (t - t0) / 800);
    el.textContent = k < 1 ? format(to * (1 - Math.pow(1 - k, 3))) : done;
    if (k < 1) requestAnimationFrame(step);
    else el.removeAttribute('aria-label');
  };
  requestAnimationFrame(step);
}

// tickNumbers(root, '.ms-val'): each match whose text is one number counts up to it once. the
// number was already formatted by the shared i18n helpers, so the count reuses its separators
// and decimals instead of formatting it again. a re-render with the same text stays still
export function tickNumbers(root, selector) {
  if (!root) return;
  for (const el of root.querySelectorAll(selector)) {
    if (el.children.length) continue;
    const text = el.textContent;
    const m = text.match(/^(\D*?)(\d(?:[\d.,  ' ]*\d)?)(\D*)$/);
    if (!m || el.dataset.counted === text) { el.dataset.counted = text; continue; }
    const [, pre, num, post] = m;
    // the last separator is the decimal one when it isn't followed by exactly three digits
    // or when the number uses two kinds of separator
    const seps = num.match(/[^\d]/g) || [];
    const last = seps.at(-1);
    const tail = last ? num.slice(num.lastIndexOf(last) + 1) : '';
    const decSep = last && (new Set(seps).size > 1 || tail.length !== 3) ? last : '';
    const groupSep = seps.find(c => c !== decSep) || '';
    const dec = decSep ? tail.length : 0;
    const digits = decSep ? num.slice(0, num.lastIndexOf(decSep)) : num;
    const to = Number(digits.replace(/\D/g, '') + (dec ? '.' + tail : ''));
    const shape = n => {
      const [int, frac] = n.toFixed(dec).split('.');
      const grouped = groupSep ? int.replace(/\B(?=(\d{3})+(?!\d))/g, groupSep) : int;
      return pre + grouped + (frac ? decSep + frac : '') + post;
    };
    countTo(el, to, shape);
    el.dataset.counted = text;
  }
}

// ── leaving ──────────────────────────────────────────────────────────────────
// leave(el): fade a toast or row out, then remove it
export function leave(el, ms = 180) {
  if (!el) return;
  if (still()) { el.remove(); return; }
  el.classList.add('leaving');
  setTimeout(() => el.remove(), ms);
}

let watcher = null;
if (page) {
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    pressDown(e.target.closest?.(PRESSABLE));
  }, { passive: true, capture: true });
  for (const type of ['pointerup', 'pointercancel', 'dragstart']) document.addEventListener(type, release, { passive: true, capture: true });
  document.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && !e.repeat && document.activeElement?.matches?.(PRESSABLE)) pressDown(document.activeElement);
  }, true);
  document.addEventListener('keyup', e => { if (e.key === 'Enter' || e.key === ' ') release(); }, true);
  addEventListener('blur', release);

  watcher = new MutationObserver(placePills);
  watcher.observe(document.documentElement, {
    subtree: true, childList: true, attributes: true,
    attributeFilter: ['class', 'aria-selected', 'aria-pressed', 'aria-checked', 'aria-current', 'hidden', 'style'],
  });
  addEventListener('resize', placePills, { passive: true });
  document.fonts?.ready.then(placePills);
  placePills();
}
