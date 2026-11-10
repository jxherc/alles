// the library app's saved list, as in shots/library.webp. every article is made up.
// labels from static/js/read.js (filters, stats line, card actions)
import { h, ic, css, topbar, menu, toast } from './kit.js';

let nextId = 1;
const art = (title, sum, site, tags, extra = {}) => ({ id: nextId++, title, sum, site, min: 3, tags, fav: false, read: false, archived: false, ...extra });
const ARTICLES = [
  art('Why first-run screens should ask for less', 'Most onboarding flows ask for everything up front: a name, a team size, a goal, three permissions. Each question feels small to the team that wrote it. To the person on the other side, it is a toll booth.', 'Margin Notes', ['design', 'onboarding'], { fav: true }),
  art('A field guide to quiet interfaces', 'Quiet software does not shout about itself. It leaves room for the work, keeps its controls where your hands expect them, and lets an empty screen stay empty.', 'The Long Draft', ['design'], { read: true }),
  art('How to run a five-person interview study in a week', 'You do not need forty interviews to learn something useful. Five well-chosen conversations surface most of the big problems, as long as you stop trying to prove a point and start listening.', 'Field Notes Weekly', ['research']),
  art('The case for a smaller design system', 'Design systems tend to grow until nobody knows what is in them. A smaller one, with twelve components and a short list of rules, gets used more than a catalog of two hundred.', 'Pixel & Pine', ['design', 'systems']),
  art('Eating well on a weeknight budget', "A pot of lentils costs about two dollars and feeds four. Add onions, a can of tomatoes and whatever greens are wilting in the fridge, and you have dinner and tomorrow's lunch.", 'The Weeknight Table', ['cooking']),
  art('Why we stopped writing weekly status updates', 'Status updates answer a question nobody asked. A short note when something changes beats a Friday ritual that everyone skims.', 'The Long Draft', ['work']),
  art('Notes on keeping a field notebook', 'A notebook works when it is cheap to write in and easy to find things in later. Date every page, keep one line per thought, and leave the cleverness for later.', 'Margin Notes', ['notes'], { read: true, archived: true }),
];
const FILTERS = ['all', 'unread', 'starred', 'archive'];
const PACE = 20;

// "notes.example/kiln-log" becomes the title "kiln log" from the source "notes.example"
const parse = (raw) => {
  const s = raw.trim();
  if (!s || /\s/.test(s)) return null;
  let u;
  try { u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(s) ? s : 'https://' + s); } catch { return null; }
  if (!/^https?:$/.test(u.protocol) || !u.hostname.includes('.')) return null;
  const host = u.hostname.replace(/^www\./, '');
  let last = u.pathname.split('/').filter(Boolean).pop() || '';
  try { last = decodeURIComponent(last); } catch { /* keep it raw */ }
  const title = last.replace(/\.(html?|php)$/i, '').replace(/[-_]+/g, ' ').trim() || host;
  return { host, title, where: host + (u.pathname === '/' ? '' : u.pathname) };
};

export default function build(root) {
  css('library');
  root.classList.add('lb-app');
  let filter = 'all';
  let query = '';
  const items = ARTICLES.map((a) => ({ ...a, tags: [...a.tags] }));

  const bar = topbar({
    app: 'library',
    tabs: ['overview', 'books', 'saved'],
    selected: 'saved',
    onTab: (name) => {
      if (name === 'saved') return;
      toast(root, name === 'overview' ? 'in alles overview shows what you are reading and your pace' : 'in alles books holds your shelves and ratings');
      bar.select('saved');
    },
  });

  const url = h('input', { class: 'dm-input lb-url', type: 'text', placeholder: 'paste a URL to save for later…', 'aria-label': 'URL to save for later', autocomplete: 'off', spellcheck: 'false' });
  const save = h('button', { type: 'button', class: 'dm-btn primary' }, ic('plus'), 'save');
  const add = () => {
    const p = parse(url.value);
    if (!p) { toast(root, 'paste a web address first'); url.focus(); return; }
    items.unshift(art(p.title, p.where, p.host, [], {}));
    url.value = '';
    filter = 'all';
    query = '';
    filterBtn.dataset.value = 'all';
    filterLabel.textContent = 'all';
    search.value = '';
    toast(root, 'saved ' + p.title);
    paint();
  };
  save.addEventListener('click', add);
  url.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });

  const filterLabel = h('span', { text: 'all' });
  const filterBtn = h('button', { type: 'button', class: 'lb-filter', 'aria-label': 'saved reading filter', 'data-value': 'all' }, filterLabel, ic('chevron-down'));
  const feeds = h('button', { type: 'button', class: 'lb-feeds', text: 'feeds' });
  feeds.addEventListener('click', () => toast(root, 'in alles feeds saves new posts from rss and atom urls for you'));
  const search = h('input', { class: 'dm-input lb-search', type: 'text', placeholder: 'search saved…', 'aria-label': 'search saved', autocomplete: 'off' });
  search.addEventListener('input', () => { query = search.value.trim().toLowerCase().replace(/^#/, ''); paint(); });

  const stats = h('div', { class: 'lb-stats', 'aria-live': 'polite' });
  const list = h('div', { class: 'lb-list' });
  root.append(bar.el, h('div', { class: 'lb' }, h('div', { class: 'lb-add' }, url, save), h('div', { class: 'lb-filters' }, filterBtn, feeds, h('span', { class: 'dm-spacer' }), search), stats, list));

  // menu() looks up the canvas from the button, so it runs once the button is inside it
  menu(filterBtn, FILTERS, (v) => { filter = v; filterBtn.dataset.value = v; filterLabel.textContent = v; paint(); });

  const shown = () => items.filter((a) => {
    if (filter === 'archive' ? !a.archived : a.archived) return false;
    if (filter === 'unread' && a.read) return false;
    if (filter === 'starred' && !a.fav) return false;
    return !query || a.title.toLowerCase().includes(query) || a.tags.some((t) => t.includes(query));
  });

  const card = (a) => {
    const act = (key, on, label, icon, pressed) => {
      const b = h('button', { type: 'button', class: 'dm-btn', 'aria-label': label, title: label, 'data-k': `${a.id}:${key}`, 'aria-pressed': pressed == null ? null : String(pressed) }, ic(icon));
      b.addEventListener('click', on);
      return b;
    };
    const open = h('button', { type: 'button', class: 'lb-open', 'aria-label': 'open ' + a.title, 'data-k': `${a.id}:open` },
      h('span', { class: 'lb-title' }, a.fav ? ic('star') : null, h('span', { text: a.title })), h('span', { class: 'lb-sum', text: a.sum }));
    open.addEventListener('click', () => toast(root, 'in alles this opens the article in the reader'));
    const meta = h('div', { class: 'lb-meta' }, `${a.site} · ${a.min} min${a.read ? ' · read' : ''}${a.tags.length ? ' · ' : ''}`);
    a.tags.forEach((t, i) => {
      const tag = h('button', { type: 'button', class: 'lb-tag', text: '#' + t, 'data-k': `${a.id}:tag:${t}` });
      tag.addEventListener('click', () => { search.value = t; query = t; paint(); });
      meta.append(i ? ' ' : '', tag);
    });
    const keep = (fn, key) => () => { fn(); paint(key); };
    return h('div', { class: 'lb-card' + (a.read ? ' read' : ''), 'data-id': String(a.id) }, open, meta,
      h('div', { class: 'lb-acts' },
        act('fav', keep(() => { a.fav = !a.fav; }, `${a.id}:fav`), a.fav ? 'unstar' : 'star', a.fav ? 'star-fill' : 'star', a.fav),
        act('read', keep(() => { a.read = !a.read; }, `${a.id}:read`), a.read ? 'mark unread' : 'mark read', 'check', a.read),
        act('archive', () => { a.archived = !a.archived; toast(root, a.archived ? 'archived' : 'unarchived'); paint(); }, a.archived ? 'unarchive' : 'archive', 'archive'),
        act('del', () => { items.splice(items.indexOf(a), 1); toast(root, 'deleted'); paint(); }, 'delete', 'trash')));
  };

  function paint(focusKey) {
    const rows = shown();
    list.replaceChildren(...rows.map(card));
    if (!rows.length) list.append(h('p', { class: 'lb-empty', text: query ? 'no matches' : filter === 'archive' ? 'nothing archived' : 'nothing here' }));
    const unread = items.filter((a) => !a.archived && !a.read);
    const mins = unread.reduce((n, a) => n + a.min, 0);
    const days = Math.ceil(mins / PACE);
    stats.textContent = unread.length ? `${unread.length} unread · ${mins} min to read · about ${days} ${days === 1 ? 'day' : 'days'} at ${PACE} min/day` : '';
    if (focusKey) list.querySelector(`[data-k="${focusKey}"]`)?.focus();
  }
  paint();
}
