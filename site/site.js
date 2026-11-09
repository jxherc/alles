// the app list comes from the readme's "what you can do" table.
// r is the hero crop in screenshot pixels: left, top and width of one whole part of the app
const apps = [
  { id: 'home', word: 'day', r: [-40, 590, 1000] },
  { id: 'aide', word: 'assistant', r: [400, 70, 1110] },
  { id: 'andromeda', word: 'search', r: [460, 150, 1000] },
  { id: 'plan', word: 'calendar', r: [585, 560, 1000] },
  { id: 'inbox', word: 'mail', r: [820, 165, 1080] },
  { id: 'docs', word: 'notes', r: [470, 280, 1040] },
  { id: 'files', word: 'files', r: [300, 215, 1040] },
  { id: 'library', word: 'reading list', r: [10, 470, 1150] },
  { id: 'health', slot: 'health-habits', word: 'habits', r: [480, 170, 1040] },
  { id: 'finance', word: 'money', r: [-30, 280, 1000] },
  { id: 'vault', word: 'passwords', r: [-20, 170, 1000] },
  { id: 'server', word: 'server', r: [-20, 140, 960] },
];
const byId = Object.fromEntries(apps.map((a) => [a.id, a]));
const shot = (id) => `shots/${id}.webp`;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const phone = matchMedia('(max-width: 767px)');
// a landscape phone has no height for a held stage
const short = matchMedia('(max-height: 560px)');

let current = 'plan';
let layer = 'a';

function paintSlot(app, el) {
  const [x, y, w] = app.r;
  el.src = shot(app.slot || app.id);
  el.style.setProperty('--w', (1920 / w) * 100);
  el.style.setProperty('--l', (-x / w) * 100);
  el.style.setProperty('--t', (-y / w) * 100);
}

function select(id) {
  const app = byId[id];
  if (!app || id === current) return;
  current = id;
  const text = $('.word-text');
  text.textContent = app.word;
  text.classList.remove('swap');
  void text.offsetWidth;
  text.classList.add('swap');

  // crossfade the two slot layers so the picture never blanks
  const next = layer === 'a' ? 'b' : 'a';
  const nextEl = $(`[data-slot="${next}"]`);
  const prevEl = $(`[data-slot="${layer}"]`);
  paintSlot(app, nextEl);
  nextEl.style.opacity = '1';
  prevEl.style.opacity = '0';
  layer = next;
  $$('#word-list li').forEach((li) => li.setAttribute('aria-selected', String(li.dataset.app === id)));
}

// hero word: a listbox like the app's own dropdown
const word = $('#word');
const list = $('#word-list');
let active = 0;
let lastPoint = { x: -1, y: -1 };
document.addEventListener('pointermove', (e) => { if (!list.contains(e.target)) lastPoint = { x: e.clientX, y: e.clientY }; }, { passive: true });

apps.forEach((app, i) => {
  const li = document.createElement('li');
  li.id = 'opt-' + app.id;
  li.setAttribute('role', 'option');
  li.dataset.app = app.id;
  li.setAttribute('aria-selected', String(app.id === current));
  li.append(app.word);
  const tag = document.createElement('span');
  tag.textContent = app.id;
  li.append(tag);
  li.addEventListener('click', () => { pick(app.id); close(true); });
  li.addEventListener('pointermove', (e) => {
    // webkit fires pointermove when the list opens under a resting mouse; only real movement counts
    if (e.pointerType !== 'mouse' || (e.clientX === lastPoint.x && e.clientY === lastPoint.y)) return;
    lastPoint = { x: e.clientX, y: e.clientY };
    setActive(i);
  });
  list.append(li);
});

function setActive(i) {
  active = (i + apps.length) % apps.length;
  $$('#word-list li').forEach((li, n) => li.classList.toggle('active', n === active));
  const li = list.children[active];
  list.setAttribute('aria-activedescendant', li.id);
  li.scrollIntoView({ block: 'nearest' });
}

function place() {
  const r = word.getBoundingClientRect();
  const host = $('.hero').getBoundingClientRect();
  const w = list.offsetWidth;
  let left = r.left - host.left;
  left = Math.min(left, host.width - w - 16);
  list.style.left = Math.max(16, left) + 'px';
  // keep the whole list on screen: below the word when it fits, otherwise above it
  list.style.maxHeight = '';
  const h = list.offsetHeight;
  const below = innerHeight - r.bottom - 22;
  const above = r.top - 22;
  if (h > below && above > below) {
    list.style.maxHeight = Math.max(200, Math.min(h, above)) + 'px';
    list.style.top = r.top - host.top - 6 - list.offsetHeight + 'px';
  } else {
    list.style.maxHeight = Math.max(200, Math.min(h, below)) + 'px';
    list.style.top = r.bottom - host.top + 6 + 'px';
  }
}

function open() {
  list.hidden = false;
  word.setAttribute('aria-expanded', 'true');
  place();
  setActive(apps.findIndex((a) => a.id === current));
  list.focus({ preventScroll: true });
}

function close(focusWord) {
  if (list.hidden) return;
  list.hidden = true;
  word.setAttribute('aria-expanded', 'false');
  if (focusWord) word.focus({ preventScroll: true });
}

word.addEventListener('click', () => (list.hidden ? open() : close(true)));
word.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); open(); }
});
list.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
  else if (e.key === 'Home') { e.preventDefault(); setActive(0); }
  else if (e.key === 'End') { e.preventDefault(); setActive(apps.length - 1); }
  else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(apps[active].id); close(true); }
  else if (e.key === 'Escape') { e.preventDefault(); close(true); }
  else if (e.key === 'Tab') { close(false); }
});
document.addEventListener('pointerdown', (e) => {
  if (!list.hidden && !list.contains(e.target) && !word.contains(e.target)) close(false);
});
window.addEventListener('resize', () => { if (!list.hidden) place(); });
window.addEventListener('scroll', () => { if (!list.hidden) place(); }, { passive: true });

paintSlot(byId[current], $('[data-slot="a"]'));
$('[data-slot="b"]').style.opacity = '0';

// the word moves on by itself every 3 seconds. it waits while the pointer is on the word or its
// picture, focus is in the sentence, the menu is open, or the hero is off screen, and stops for
// good once someone picks. (the hero fills the first screen, so hovering all of it would mean never)
const hero = $('.hero');
const cycle = { stopped: false, hover: false, seen: true };
function pick(id) { cycle.stopped = true; select(id); }
for (const el of [word, $('.slot')]) {
  el.addEventListener('pointerenter', () => { cycle.hover = true; });
  el.addEventListener('pointerleave', () => { cycle.hover = false; });
}
new IntersectionObserver(([e]) => { cycle.seen = e.isIntersecting; }).observe(hero);
setInterval(() => {
  if (cycle.stopped || cycle.hover || !cycle.seen || reduced.matches || document.hidden) return;
  if (!list.hidden || hero.contains(document.activeElement)) return;
  const i = apps.findIndex((a) => a.id === current);
  select(apps[(i + 1) % apps.length].id);
}, 3000);

// held stages: a tall section whose stage sticks while the page scrolls past. scroll position
// picks the beat; nothing captures the wheel. reduced motion and no script show it all at rest
function scene(root, { rest, onBeat }) {
  const beats = Number(root.dataset.beats);
  let last = -1;
  let raf = 0;
  const live = () => root.classList.contains('is-live');
  const update = () => {
    raf = 0;
    if (!live()) return;
    const r = root.getBoundingClientRect();
    const span = r.height - innerHeight;
    const p = span > 0 ? Math.min(1, Math.max(0, -r.top / span)) : 0;
    root.style.setProperty('--p', p.toFixed(4));
    const b = Math.min(beats - 1, Math.floor(p * beats));
    if (b !== last) { last = b; onBeat(b); }
  };
  const mode = () => {
    const resting = reduced.matches || rest();
    root.classList.toggle('is-live', !resting);
    root.classList.toggle('is-rest', resting);
    last = -1;
    if (resting) onBeat(-1); else update();
  };
  addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(update); }, { passive: true });
  addEventListener('resize', update);
  reduced.addEventListener('change', mode);
  phone.addEventListener('change', mode);
  short.addEventListener('change', mode);
  mode();
  // a link to a beat scrolls to the middle of that beat; at rest it is a plain anchor
  root.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-beat]');
    if (!a || !live()) return;
    e.preventDefault();
    const top = root.getBoundingClientRect().top + scrollY;
    const span = root.offsetHeight - innerHeight;
    scrollTo({ top: top + (span * (Number(a.dataset.beat) + 0.5)) / beats, behavior: 'smooth' });
  });
}

const appsScene = $('.apps-scene');
scene(appsScene, {
  rest: () => short.matches,
  onBeat: (b) => {
    $$('.app', appsScene).forEach((f) => f.classList.toggle('on', Number(f.dataset.beat) === b));
    $$('.apps-index a', appsScene).forEach((a) => a.setAttribute('aria-current', String(Number(a.dataset.beat) === b)));
  },
});

const stepsScene = $('.steps-scene');
scene(stepsScene, {
  // a phone has no room for the words, the picture and the steps at once, so it lists them
  rest: () => phone.matches || short.matches,
  onBeat: (b) => {
    $$('.step', stepsScene).forEach((s) => s.classList.toggle('on', Number(s.dataset.beat) === b));
    $$('.step-names a', stepsScene).forEach((a) => a.setAttribute('aria-current', String(Number(a.dataset.beat) === b)));
  },
});

// switches
$$('.band').forEach((band) => {
  const sw = $('.switch', band);
  const note = $('.band-note', band);
  sw.addEventListener('click', () => {
    const on = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(on));
    band.dataset.on = String(on);
    note.textContent = on ? note.dataset.onText : note.dataset.offText;
  });
});

// copy buttons
$$('.copy').forEach((btn) => {
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
    } catch {
      const code = btn.previousElementSibling;
      getSelection().selectAllChildren(code);
      return;
    }
    btn.textContent = 'copied';
    btn.classList.add('done');
    clearTimeout(btn.t);
    btn.t = setTimeout(() => { btn.textContent = 'copy'; btn.classList.remove('done'); }, 1600);
  });
});

// the server demo: tabs like the app's, made up numbers that keep moving while it's live
const demo = $('.demo-win');
const tabs = $$('[role="tab"]', demo);
function showTab(tab, focus) {
  tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    $('#' + t.getAttribute('aria-controls')).classList.toggle('off', !on);
  });
  if (focus) tab.focus();
}
// without the script only the overview shows; with it, every panel takes its share of the height
$$('.demo-panel', demo).forEach((p) => { p.classList.toggle('off', p.hidden); p.hidden = false; });
tabs.forEach((t, i) => {
  t.addEventListener('click', () => showTab(t));
  t.addEventListener('keydown', (e) => {
    const go = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (go === undefined) return;
    e.preventDefault();
    showTab(tabs[(go + tabs.length) % tabs.length], true);
  });
});

const series = { cpu: [], mem: [], net: [] };
const walk = (v, step, lo, hi) => Math.min(hi, Math.max(lo, v + (Math.random() - 0.5) * step));
let cpu = 14, mem = 64, down = 16, up = 22, procs = 412;
for (let i = 0; i < 30; i++) {
  cpu = walk(cpu, 10, 4, 38); mem = walk(mem, 1.2, 58, 71); down = walk(down, 14, 2, 60);
  series.cpu.push(cpu); series.mem.push(mem); series.net.push(down);
}
function spark(svg, values, max) {
  const n = values.length - 1;
  const pts = values.map((v, i) => `${((i / n) * 100).toFixed(2)},${(32 - (v / max) * 30).toFixed(2)}`);
  $('.line', svg).setAttribute('d', 'M' + pts.join('L'));
  $('.area', svg).setAttribute('d', 'M0,32L' + pts.join('L') + 'L100,32Z');
}
function paintDemo() {
  const card = (k) => $(`.demo-card[data-k="${k}"]`, demo);
  $('.demo-val', card('cpu')).textContent = Math.round(cpu) + '%';
  $('.demo-load', demo).textContent = (cpu / 6 + 0.4).toFixed(2);
  $('.demo-val', card('mem')).textContent = Math.round(mem) + '%';
  $('.demo-used', demo).textContent = ((mem / 100) * 25.8).toFixed(1);
  $('.demo-val', card('net')).firstChild.textContent = '↓ ' + down.toFixed(1) + ' ';
  $('.demo-up', demo).textContent = up.toFixed(1);
  $('.demo-procs', demo).textContent = Math.round(procs);
  spark($('svg', card('cpu')), series.cpu, 100);
  spark($('svg', card('mem')), series.mem, 100);
  spark($('svg', card('net')), series.net, 64);
}
function tickDemo() {
  cpu = walk(cpu, 10, 4, 38); mem = walk(mem, 1.2, 58, 71); down = walk(down, 14, 2, 60); up = walk(up, 10, 2, 40); procs = walk(procs, 6, 396, 430);
  for (const [k, v] of [['cpu', cpu], ['mem', mem], ['net', down]]) { series[k].push(v); series[k].shift(); }
  paintDemo();
}
paintDemo();
const liveBtn = $('.demo-live', demo);
const demoState = { live: !reduced.matches, seen: false };
const setLive = (on) => {
  demoState.live = on;
  liveBtn.setAttribute('aria-pressed', String(on));
  $('.demo-live-word', liveBtn).textContent = on ? 'live' : 'paused';
};
setLive(demoState.live);
liveBtn.addEventListener('click', () => setLive(!demoState.live));
new IntersectionObserver(([e]) => { demoState.seen = e.isIntersecting; }).observe(demo);
setInterval(() => { if (demoState.live && demoState.seen && !document.hidden) tickDemo(); }, 1500);

// backups: the same steps the real card shows, with a made up file name
const runBtn = $('.demo-btn', demo);
const status = $('.demo-status', demo);
runBtn.addEventListener('click', () => {
  runBtn.disabled = true;
  status.textContent = 'creating encrypted backup…';
  setTimeout(() => {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const stamp = `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
    status.textContent = `backup complete · alles-backup-${stamp}-${Math.random().toString(16).slice(2, 6)}.alles-backup`;
    $('.demo-last', demo).textContent = 'just now';
    $('.demo-verified', demo).textContent = 'just now';
    runBtn.disabled = false;
  }, 1800);
});

// entrances: each section's parts arrive in order, once
const seen = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    e.target.classList.add('in');
    seen.unobserve(e.target);
  }
}, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });
$$('section, footer').forEach((sec) => {
  $$('.rv', sec).forEach((el, i) => { el.style.transitionDelay = i * 80 + 'ms'; seen.observe(el); });
});

// warm the other screenshots once the page is idle, so the hero doesn't wait
const warm = () => apps.forEach((a) => { new Image().src = shot(a.slot || a.id); });
if ('requestIdleCallback' in window) requestIdleCallback(warm, { timeout: 3000 });
else setTimeout(warm, 2000);
