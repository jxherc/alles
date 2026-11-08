// the app list comes from the readme's "what you can do" table.
// x, y and z pick the crop the hero shows inside the sentence (background position and zoom)
const apps = [
  { id: 'home', word: 'day', text: 'see your day, open your apps, and capture a task', alt: 'the home app: today\'s schedule, open tasks and a capture box', x: 0, y: 75, z: 240 },
  { id: 'aide', word: 'assistant', text: 'chat with a configured model and approve actions in your workspace', alt: 'aide moving a meeting to tuesday, then summarizing a roadmap doc', x: 48, y: 13, z: 200 },
  { id: 'andromeda', word: 'search', text: 'search the web and optionally get a cited overview; it can be your browser\'s search too', alt: 'andromeda\'s search box', x: 50, y: 26, z: 200 },
  { id: 'plan', word: 'calendar', text: 'keep a calendar, tasks, reminders, and countdowns', alt: 'the plan app: a week calendar full of events across four calendars', x: 69, y: 62, z: 240 },
  { id: 'inbox', word: 'mail', text: 'read mail and manage contacts after connecting your account', alt: 'the inbox app: a message list with one email open', x: 31, y: 17, z: 220 },
  { id: 'docs', word: 'notes', text: 'write markdown notes and journal entries', alt: 'the docs app: a roadmap note with a table of targets', x: 49, y: 34, z: 220 },
  { id: 'files', word: 'files', text: 'browse local or connected storage, offline copies, and photos', alt: 'the files app: a project folder of pdfs, images and notes', x: 29, y: 31, z: 240 },
  { id: 'library', word: 'reading list', text: 'save articles and reading lists', alt: 'the library app: saved articles with their reading times', x: 0, y: 30, z: 260 },
  { id: 'health', slot: 'health-habits', word: 'habits', text: 'track habits and health records', alt: 'the health app: weight, sleep, workout and heart rate over 30 days', x: 50, y: 17, z: 220 },
  { id: 'finance', word: 'money', text: 'track accounts, transactions, budgets, and subscriptions', alt: 'the finance app: spending this month, accounts, categories and renewals', x: 0, y: 11, z: 240 },
  { id: 'vault', word: 'passwords', text: 'store encrypted secrets, passwords, and passkeys, and fill logins, cards and addresses in chrome with the alles extension', alt: 'the vault app: saved logins, a card and a secure note', x: 0, y: 20, z: 240 },
  { id: 'server', word: 'server', text: 'check health, access settings, backups, and updates', alt: 'the server app: cpu, memory, storage and network', x: 0, y: 20, z: 220 },
];
const byId = Object.fromEntries(apps.map((a) => [a.id, a]));
const shot = (id) => `shots/${id}.webp`;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let current = 'plan';
let layer = 'a';

function paintSlot(app, el) {
  el.src = shot(app.slot || app.id);
  el.style.setProperty('--x', app.x);
  el.style.setProperty('--y', app.y);
  el.style.setProperty('--z', app.z);
}

function select(id) {
  const app = byId[id];
  if (!app || id === current) return;
  current = id;
  $('.word-text').textContent = app.word;

  // crossfade the two slot layers so the picture never blanks
  const next = layer === 'a' ? 'b' : 'a';
  const nextEl = $(`[data-slot="${next}"]`);
  const prevEl = $(`[data-slot="${layer}"]`);
  paintSlot(app, nextEl);
  nextEl.style.opacity = '1';
  prevEl.style.opacity = '0';
  layer = next;

  $$('.apps-index button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.app === id)));
  const img = $('#sheet-img');
  img.classList.add('swap');
  const done = () => img.classList.remove('swap');
  img.onload = done;
  img.onerror = done;
  img.src = shot(id);
  img.alt = app.alt;
  $('#sheet-link').href = shot(id);
  const cap = $('#sheet-cap');
  cap.replaceChildren();
  const name = document.createElement('strong');
  name.textContent = app.id;
  cap.append(name, ' ' + app.text);
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
  li.addEventListener('click', () => { select(app.id); close(true); });
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
  else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(apps[active].id); close(true); }
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

$$('.apps-index button').forEach((b) => b.addEventListener('click', () => select(b.dataset.app)));

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

// install steps: one range and four names drive the same state
const titles = ['first, paste one line', 'then open it in your browser', 'let your phone in, if you want', 'update, or go back'];
const names = ['install', 'open', 'share', 'update'];
const range = $('#step-range');
function step(n) {
  n = Number(n);
  range.value = n;
  range.parentElement.style.setProperty('--fill', (n / 3) * 100 + '%');
  range.setAttribute('aria-valuetext', names[n]);
  $('#step-title').textContent = titles[n];
  $$('.step-names button').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.step) === n)));
  $$('.step').forEach((s) => { s.hidden = Number(s.dataset.step) !== n; });
}
range.addEventListener('input', () => step(range.value));
$$('.step-names button').forEach((b) => b.addEventListener('click', () => step(b.dataset.step)));

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

// warm the other screenshots once the page is idle, so switching apps doesn't wait
const warm = () => apps.forEach((a) => {
  if (a.id !== current) new Image().src = shot(a.id);
  if (a.slot) new Image().src = shot(a.slot);
});
if ('requestIdleCallback' in window) requestIdleCallback(warm, { timeout: 3000 });
else setTimeout(warm, 2000);
