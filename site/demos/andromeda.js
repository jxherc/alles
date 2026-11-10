// andromeda's search box and results view, as in shots/andromeda.webp and static/js/andromeda.js:
// recent searches under the box, then the query, an overview with numbered sources, and the result list.
// every site is on a reserved .example domain and every answer is made up
import { h, ic, css, topbar, toast, needsInstall } from './kit.js';

const SEARCHES = [
  {
    q: 'how long to rest bread dough',
    key: 'Let the dough rest until it has about doubled, which usually takes 1 to 2 hours at room temperature.',
    claims: [
      { text: 'Time depends on warmth. A cooler kitchen can take longer, and a warm one can take less. Judge by size, not by the clock.', cites: [1, 2] },
      { text: 'To check, press a floured finger into the dough. If the dent springs back slowly, it is ready to shape.', cites: [2, 3] },
    ],
    results: [
      { host: 'crumbschool.example', name: 'Crumb School', path: 'crumbschool.example › basics › proofing', title: 'The first rise: how long and how to tell', snippet: 'Most doughs need 1 to 2 hours to double at room temperature. Look for size and a soft, airy feel instead of watching the clock.', passage: 'Let the dough rise until it has about doubled in size. Warmer rooms are faster.' },
      { host: 'homebakers.example', name: 'Home Bakers Notes', path: 'homebakers.example › guides', title: 'Why your dough rises slowly in winter', snippet: 'A cool kitchen slows yeast down. Try the oven with only the light on, or give the dough more time.', passage: 'A cooler room means a longer rise. Go by how the dough looks, not how long it has been.' },
      { host: 'proofclub.example', name: 'Proof Club', path: 'proofclub.example › tips', title: 'The poke test, explained', snippet: 'Press a floured finger about a centimetre into the dough. A slow spring back means it is ready to shape.', passage: 'If the dent springs back slowly and only partly, the dough is ready.' },
      { host: 'flourtable.example', name: 'The Flour Table', path: 'flourtable.example › recipes', title: 'A plain loaf for beginners', snippet: 'Four ingredients, one rise in the bowl and one in the pan. Plan on about three hours from start to oven.', passage: '' },
    ],
  },
  {
    q: 'cone 6 glaze recipes',
    key: 'Most cone 6 glazes mix silica, feldspar, whiting and kaolin, then fire to a mid-range temperature.',
    claims: [
      { text: 'A clear base is the usual starting point: roughly equal parts feldspar and silica, with smaller amounts of whiting and kaolin. Test it on a tile first.', cites: [1, 2] },
      { text: 'A slow cool at the end of the firing lets the surface mature and often deepens the colour.', cites: [3] },
    ],
    results: [
      { host: 'tiletest.example', name: 'Test Tile Journal', path: 'tiletest.example › recipes › cone 6', title: 'A clear glaze base: four materials, one test tile', snippet: 'A simple clear to start from. Mix a small batch, dip a tile, and fire it with your next load.', passage: 'Feldspar and silica in roughly equal parts, with whiting and kaolin making up the rest.' },
      { host: 'mugandkiln.example', name: 'Mug and Kiln Diary', path: 'mugandkiln.example › notes', title: 'Glazes worth testing at mid-range', snippet: 'A few simple recipes from one hobby studio, with notes on how each looked over light and dark clay.', passage: 'Always test a new recipe on a tile before it goes on a pot.' },
      { host: 'slowcool.example', name: 'Slow Cool Notes', path: 'slowcool.example › firing', title: 'What a slow cool does to a glossy glaze', snippet: 'Three cooling schedules to try, with photos of the same glaze after each one.', passage: 'A slow cool lets the glaze surface mature.' },
      { host: 'materialsprimer.example', name: 'Materials Primer', path: 'materialsprimer.example › learn', title: 'What each glaze material does', snippet: 'Silica builds glass, feldspar melts it, whiting stiffens it and kaolin keeps it on the pot.', passage: '' },
    ],
  },
  {
    q: 'fieldnote competitors',
    key: 'Fieldnote’s closest competitors are Sample Notes, Sample Field and Sample Trowel. All three capture notes offline.',
    claims: [
      { text: 'Sample Notes and Sample Trowel are single-user tools. Sample Field is the only one of the three that shares notes with a team.', cites: [1, 2] },
      { text: 'All three charge between 6 and 12 dollars a month per person.', cites: [3] },
    ],
    results: [
      { host: 'samplenotes.example', name: 'Sample Notes', path: 'samplenotes.example › pricing', title: 'Sample Notes pricing: personal plans', snippet: 'Offline capture, photo notes and a map view. One plan for one person, 8 dollars a month.', passage: 'Built for one person. Team sharing is not offered.' },
      { host: 'samplefield.example', name: 'Sample Field', path: 'samplefield.example › teams', title: 'Sample Field for teams: share notes live', snippet: 'Shared notebooks, comments and an offline mode that syncs when you are back on a network. 12 dollars per person.', passage: 'Invite your team and see each other’s notes as they sync.' },
      { host: 'samplereviews.example', name: 'Sample Review Site', path: 'samplereviews.example › field apps', title: 'Offline note apps for field work, compared', snippet: 'Three apps held up without a signal, and only one let two people edit together.', passage: 'Prices for the three apps ranged from 6 to 12 dollars a month.' },
      { host: 'sampletrowel.example', name: 'Sample Trowel', path: 'sampletrowel.example › plans', title: 'Sample Trowel: notes for people who work outdoors', snippet: 'Capture by voice, photo or text with no signal. 6 dollars a month, billed yearly.', passage: '' },
    ],
  },
];

const words = (s) => s.toLowerCase().split(/\s+/).filter(Boolean);
// a typed search finds a prepared one when it is the same, or all of 2+ typed words appear in it
function find(q) {
  const w = words(q);
  if (!w.length) return null;
  return SEARCHES.find((s) => s.q === w.join(' ')) || (w.length >= 2 ? SEARCHES.find((s) => w.every((x) => s.q.includes(x))) : null) || null;
}

export default function build(root) {
  css('andromeda');
  let state = 'idle';
  let active = -1;
  let shown = [];
  let card = null; // { el, chip }

  const input = h('input', { class: 'an-input', type: 'text', placeholder: 'search the web', 'aria-label': 'search the web', role: 'combobox', 'aria-expanded': 'false', 'aria-controls': 'an-list', 'aria-autocomplete': 'list', autocomplete: 'off', spellcheck: 'false', maxlength: '200' });
  const clear = h('button', { type: 'button', class: 'an-btn an-clear', 'aria-label': 'clear search', hidden: true }, ic('close'));
  const go = h('button', { type: 'submit', class: 'an-btn an-go', 'aria-label': 'search' }, ic('arrow-right'));
  const box = h('form', { class: 'an-box', role: 'search' }, ic('search'), input, clear, go);
  const list = h('ul', { class: 'an-list', id: 'an-list', role: 'listbox', 'aria-label': 'recent searches', hidden: true });
  const col = h('div', { class: 'an-col' });
  const settings = h('button', { type: 'button', class: 'an-settings', text: 'settings' });
  settings.addEventListener('click', () => toast(root, 'in alles this opens andromeda\'s settings: search provider, result count and the overview'));
  const bar = topbar({ app: 'andromeda' });
  const wrap = h('div', { class: 'an', 'data-state': 'idle', style: 'position:absolute;inset:0' }, bar.el, col, box, list, settings);
  root.append(wrap);

  // ---- recent searches ----
  const setActive = (i) => {
    active = i;
    [...list.querySelectorAll('.an-opt')].forEach((li, n) => li.classList.toggle('active', n === i));
    if (i >= 0) input.setAttribute('aria-activedescendant', 'an-opt-' + i); else input.removeAttribute('aria-activedescendant');
  };
  const closeList = () => {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    setActive(-1);
  };
  const openList = () => {
    const typed = input.value.trim().toLowerCase();
    shown = SEARCHES.filter((s) => !typed || s.q.includes(typed));
    if (!shown.length) { closeList(); return; }
    list.replaceChildren(h('li', { class: 'an-group', role: 'presentation', text: 'recent' }), ...shown.map((s, i) => {
      const li = h('li', { class: 'an-opt', role: 'option', id: 'an-opt-' + i, 'aria-selected': 'false' }, ic('history'), h('span', { text: s.q }));
      li.addEventListener('pointermove', () => { if (active !== i) setActive(i); });
      li.addEventListener('click', () => pick(s.q));
      return li;
    }));
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    setActive(-1);
  };
  // clicks inside the list keep the keyboard in the box
  list.addEventListener('mousedown', (e) => e.preventDefault());
  const pick = (q) => { input.value = q; submit(); };

  // ---- results ----
  const closeCard = (focus) => {
    if (!card) return;
    card.el.remove();
    card.chip.setAttribute('aria-expanded', 'false');
    if (focus) card.chip.focus();
    card = null;
  };
  const openCard = (chip, anchor, r, n) => {
    if (card && card.chip === chip) { closeCard(true); return; }
    closeCard();
    const el = h('div', { class: 'an-card', role: 'group', 'aria-label': `source ${n}` },
      h('span', { class: 'an-card-site', text: `${r.name} · ${r.host}` }),
      h('strong', { text: r.title }),
      r.passage ? h('blockquote', { text: r.passage }) : null);
    el.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeCard(true); } });
    anchor.after(el);
    chip.setAttribute('aria-expanded', 'true');
    card = { el, chip };
  };
  const chipRow = (hit, cites) => {
    const row = h('div', { class: 'an-cites' });
    cites.forEach((n) => {
      const r = hit.results[n - 1];
      const chip = h('button', { type: 'button', class: 'an-cite', 'aria-expanded': 'false', 'aria-label': `source ${n}: ${r.host}` }, h('i', { text: String(n) }), r.host);
      chip.addEventListener('click', () => openCard(chip, row, r, n));
      chip.addEventListener('keydown', (e) => { if (e.key === 'Escape' && card) { e.preventDefault(); closeCard(true); } });
      row.append(chip);
    });
    return row;
  };
  const tab = (name) => {
    const b = h('button', { type: 'button', class: 'an-tab', 'aria-current': name === 'all' ? 'page' : null, text: name });
    if (name !== 'all') b.addEventListener('click', () => toast(root, `in alles this shows ${name} results from your search provider`));
    return b;
  };
  const resultNode = (r) => {
    const title = h('button', { type: 'button', class: 'an-title', text: r.title });
    title.addEventListener('click', () => toast(root, `in alles this opens ${r.host} in a new tab`));
    return h('article', { class: 'an-result' },
      h('div', { class: 'an-src' }, h('span', { class: 'an-fav', 'aria-hidden': 'true', text: r.name[0] }), h('span', { class: 'an-src-copy' }, h('span', { class: 'an-src-name', text: r.name }), h('span', { class: 'an-src-path', text: r.path }))),
      title, h('p', { class: 'an-snip', text: r.snippet }));
  };
  const showResults = (q) => {
    closeCard();
    const hit = find(q);
    // only the three recent searches are in this copy; anything else needs the real andromeda
    if (!hit) {
      needsInstall(root, `in alles, andromeda searches the web for “${q}” through your search provider, with a cited overview when you want one.`);
      return;
    }
    const claims = hit.claims.flatMap((c) => [h('p', { class: 'an-claim', text: c.text }), chipRow(hit, c.cites)]);
    col.replaceChildren(
      h('div', { class: 'an-tools' }, h('nav', { class: 'an-tabs', 'aria-label': 'search types' }, ['all', 'images', 'news', 'videos'].map(tab)), h('span', { class: 'an-meta', text: `${hit.results.length} results` })),
      h('section', { class: 'an-overview', 'aria-label': 'ai overview' },
        h('div', { class: 'an-head' }, ic('sparkles'), 'ai overview', h('span', { class: 'an-state', text: 'checked against exact source passages' })),
        h('strong', { class: 'an-key', text: hit.key }), claims),
      h('div', { class: 'an-list-results' }, hit.results.map(resultNode)));
  };

  function submit() {
    const q = input.value.replace(/\s+/g, ' ').trim();
    if (!q) return;
    input.value = q;
    state = 'results';
    wrap.dataset.state = 'results';
    clear.hidden = false;
    closeList();
    showResults(q);
  }
  const backToSearch = () => {
    state = 'idle';
    wrap.dataset.state = 'idle';
    input.value = '';
    clear.hidden = true;
    closeCard();
    col.replaceChildren();
    input.focus();
  };

  box.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  clear.addEventListener('click', () => {
    if (state === 'results') backToSearch();
    else { input.value = ''; clear.hidden = true; input.focus(); }
  });
  input.addEventListener('focus', openList);
  input.addEventListener('blur', closeList);
  input.addEventListener('input', () => { clear.hidden = !input.value && state === 'idle'; openList(); });
  input.addEventListener('keydown', (e) => {
    const open = !list.hidden;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { openList(); if (list.hidden) return; }
      const n = shown.length;
      setActive(e.key === 'ArrowDown' ? (active + 1) % n : (active - 1 + n) % n);
    } else if (e.key === 'Enter' && open && active >= 0) {
      e.preventDefault();
      pick(shown[active].q);
    } else if (e.key === 'Escape') {
      if (open) { e.preventDefault(); closeList(); }
    }
  });
}
