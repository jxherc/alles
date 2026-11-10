// the docs app's documents and journal, as in shots/docs.webp. every document is made up.
// markdown is rendered into nodes (never as html), so nothing typed can inject markup
import { h, ic, css, topbar, toast } from './kit.js';

const DOCS = [
  { id: 'q4', title: 'Q4 roadmap', note: false, tags: ['roadmap'], src: `# Q4 roadmap

Goal: ship Fieldnote 2.0 on **Nov 20** and make onboarding the focus of the quarter.

## Themes

1. **Onboarding.** Cut time to first note from 6 minutes to under 2. Owners: Maya, Marcus. Ships Nov 20.
2. **Shared notebooks.** Invites and comments. Owner: Marcus. Dec 4.
3. **Search.** Typo tolerance and filters. Owner: Marcus's team. Dec 11.
4. **Mobile offline mode.** Moved to Q1, not enough capacity this quarter.

## Targets

| Metric | Now | End of Q4 |
| --- | --- | --- |
| Activation rate | 38% | 55% |
| Week-4 retention | 31% | 38% |
| Time to first note | 6 min | under 2 min |

## Risks

- Only 5 of the 8 planned user interviews are booked. See [Onboarding research notes](doc:onboarding).
- Search needs a spike before Dec 11 or the date moves.
- Shared notebooks depend on the permissions screen, which Marcus has not scoped yet.

## Next steps

- Jordan reviews the draft this week.
- Priya books the three missing interviews.
- Maya sends a rough onboarding prototype to Marcus by Tuesday.
- Revisit mobile offline mode in the Q1 planning session.

## Notes

The permissions screen blocks shared notebooks, so Marcus scopes it first. Jordan wants to review the targets table before it goes to the wider team. Revisit the search date once the spike is done. Send any questions to Maya before Friday.` },
  { id: 'reading', title: 'Reading list', note: true, tags: [], src: `# Reading list

## This month

- **Keeping notes small.** Short essay on why one idea per note holds up.
- **The weekly review, revisited.** From the Margin Notes newsletter.
- **How onboarding gets measured.** Useful when setting the Q4 targets.

## Later

- A book on pottery glazes, lent by the studio.
- Two travel guides for the Lisbon trip.` },
  { id: 'dal', title: 'Weeknight dal', note: true, tags: [], src: `# Weeknight dal

Serves 3. About 30 minutes.

## Ingredients

- 1 cup red lentils, rinsed
- 1 onion, diced
- 3 cloves garlic
- 1 tsp **cumin seeds**
- 1 tsp turmeric
- Lemon and cilantro to finish

## Steps

1. Toast the cumin in oil, then add the onion and garlic.
2. Stir in the turmeric and lentils with 3 cups of water.
3. Simmer for 20 minutes until soft.
4. Finish with lemon and cilantro.` },
  { id: 'crit', title: 'Design crit notes', note: true, tags: ['design', 'principles'], src: `# Design crit notes

Review of the new onboarding flow with Priya and Jordan.

## What worked

- The first screen asks for one thing only.
- **Empty states** teach by showing a real example note.

## Fix next

- The skip link is too quiet.
- Progress dots look like buttons.

## Principles

| Rule | Why |
| --- | --- |
| One action per screen | Keeps first-run under 2 minutes |
| Show, don't explain | Fewer words to read |` },
  { id: 'lisbon', title: 'Lisbon trip', note: false, tags: ['travel'], src: `# Lisbon trip

Dec 11 to Dec 20. Flight booked with Air Portugal, ref **KX4P2R**.

## Plan

| Day | Idea |
| --- | --- |
| Sat Dec 12 | Arrive, walk Alfama |
| Mon Dec 14 | Ceramics workshop |
| Wed Dec 16 | Day trip to Sintra |

## Pack

- Warm jacket
- Sketchbook
- Adapter` },
  { id: 'onboarding', title: 'Onboarding research notes', note: true, tags: [], src: `# Onboarding research notes

Five interviews so far, three more to book.

## What people said

- Most users want to type a first note within a minute.
- Folders feel like homework on day one.
- Nobody found the import button.

These feed the targets in the [Q4 roadmap](doc:q4).` },
  { id: 'weekly', title: 'Weekly review', note: true, tags: [], src: `# Weekly review

## Done

- Q4 roadmap draft sent to Jordan
- Glaze order placed

## Next week

- Prototype for Marcus
- Dentist on Tuesday at 4:30 pm` },
];
const RECENT = ['reading', 'dal', 'crit', 'weekly'];
const JOURNAL = { id: 'journal', title: 'Sunday, Nov 8', file: 'journal/2026-11-08.md', src: `# Sunday, Nov 8

Slept in. Brunch with Priya at 11:30, then the pottery studio to look at glazes.

## Today

- Reply to Jordan about the prototype
- Pack list for Lisbon is in [Lisbon trip](doc:lisbon)
- Weeknight dal for dinner

## Notes

Marcus's questions on the permissions screen are fair. Answer them before Tuesday.` };

// ---- markdown into nodes
function inline(text, onDoc, onExt) {
  const out = [];
  for (const part of text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/)) {
    if (!part) continue;
    let m;
    if ((m = part.match(/^\*\*([^*]+)\*\*$/))) out.push(h('strong', { text: m[1] }));
    else if ((m = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/))) {
      const url = m[2];
      out.push(h('button', { type: 'button', class: 'dc-link', text: m[1], onclick: () => (url.startsWith('doc:') ? onDoc(url.slice(4)) : onExt(url)) }));
    } else out.push(part);
  }
  return out;
}
function render(src, onDoc, onExt) {
  const lines = src.replace(/\r/g, '').split('\n');
  const nodes = [];
  let i = 0;
  const inl = (t) => inline(t, onDoc, onExt);
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (!line.trim()) { i++; continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) { nodes.push(h('h' + (m[1].length + 3), {}, inl(m[2]))); i++; continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(h('li', {}, inl(lines[i++].replace(/^\s*[-*]\s+/, ''))));
      nodes.push(h('ul', {}, items)); continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(h('li', {}, inl(lines[i++].replace(/^\s*\d+\.\s+/, ''))));
      nodes.push(h('ol', {}, items)); continue;
    }
    if (line.includes('|') && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || '')) {
      const cells = (l) => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
      nodes.push(h('table', {}, h('thead', {}, h('tr', {}, head.map((c) => h('th', {}, inl(c))))), h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, inl(c))))))));
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|\s*[-*]\s|\s*\d+\.\s)/.test(lines[i])) para.push(lines[i++]);
    nodes.push(h('p', {}, inl(para.join(' '))));
  }
  return nodes;
}
const wordCount = (src) => src.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w)).length;
const firstTitle = (src) => (src.match(/^#\s+(.+)$/m) || [])[1];

export default function build(root) {
  css('docs');
  const st = { tab: 'documents', cur: 'q4', filter: 'all', q: '', tag: null, edit: false, jedit: false };
  const docs = DOCS.map((d) => ({ ...d }));
  const journal = { ...JOURNAL };
  let recent = [...RECENT];
  let n = 0;
  const get = (id) => docs.find((d) => d.id === id);
  const path = (d) => d.file || d.title + '.md';
  const ext = (url) => toast(root, 'in alles this opens the link');

  // ---- a pane: header, rendered article or markdown source, edit toggle
  function pane({ journalMode }) {
    const title = h('h4', { class: 'dc-title' });
    const file = h('div', { class: 'dc-file' });
    const words = h('span');
    const saved = h('span', { text: 'saved' });
    const edit = h('button', { type: 'button', class: '', 'aria-pressed': 'false', text: 'edit' });
    const ask = h('button', { type: 'button', text: 'ask Aide' });
    const obs = h('button', { type: 'button', text: 'open in Obsidian' });
    const more = h('button', { type: 'button', 'aria-label': 'more', text: '···' });
    const imp = journalMode ? null : h('button', { type: 'button', class: 'dc-import', text: 'import' });
    const article = h('article', { class: 'dc-article' });
    const ta = h('textarea', { class: 'dc-edit', spellcheck: 'false', hidden: true, 'aria-label': 'markdown source' });
    const el = h('div', { class: 'dc-pane' + (journalMode ? ' dc-journal' : '') },
      h('div', { class: 'dc-head' }, title, file, imp, h('div', { class: 'dc-meta' }, words, saved), h('div', { class: 'dc-acts' }, edit, ask, obs, more)),
      h('div', { class: 'dc-body' }, article, ta));
    const api = { el, doc: null, editing: false, ta, edit };
    const meta = () => { const w = wordCount(api.doc.src); words.textContent = `${w} words · ${Math.max(1, Math.round(w / 200))} min`; };
    api.show = (doc) => {
      api.doc = doc;
      title.textContent = doc.title;
      file.textContent = path(doc);
      api.setEdit(false, true);
    };
    api.paint = () => { article.replaceChildren(...render(api.doc.src, api.onDoc, ext)); meta(); };
    api.setEdit = (on, silent) => {
      api.editing = on;
      ta.hidden = !on;
      article.hidden = on;
      edit.textContent = on ? 'done' : 'edit';
      edit.setAttribute('aria-pressed', String(on));
      if (on) {
        ta.value = api.doc.src;
        saved.textContent = 'editing';
        ta.focus({ preventScroll: true });
        ta.setSelectionRange(ta.value.length, ta.value.length);
      } else {
        saved.textContent = 'saved';
        api.paint();
        if (!silent) edit.focus({ preventScroll: true });
      }
    };
    edit.addEventListener('click', () => {
      if (!api.editing) return api.setEdit(true);
      api.doc.src = ta.value;
      const t = firstTitle(ta.value);
      if (t && !journalMode) { api.doc.title = t.trim(); title.textContent = api.doc.title; file.textContent = path(api.doc); }
      api.setEdit(false);
      api.onSaved?.();
    });
    ta.addEventListener('input', () => { words.textContent = `${wordCount(ta.value)} words · ${Math.max(1, Math.round(wordCount(ta.value) / 200))} min`; });
    ask.addEventListener('click', () => toast(root, 'in alles this opens aide with this document attached'));
    obs.addEventListener('click', () => toast(root, 'in alles this opens the file in your Obsidian vault'));
    more.addEventListener('click', () => toast(root, 'in alles this opens the document menu'));
    imp?.addEventListener('click', () => toast(root, 'in alles this imports markdown, text and pdf files'));
    return api;
  }

  // ---- left column
  const newDoc = h('button', { type: 'button', text: 'new document' });
  const newFolder = h('button', { type: 'button', text: 'new folder' });
  const search = h('input', { type: 'text', class: 'dm-input dc-search', placeholder: 'search documents...', 'aria-label': 'search documents', autocomplete: 'off' });
  const section = (label, rows) => {
    const head = h('button', { type: 'button', class: 'dc-sech', 'aria-expanded': 'true' }, label, ic('chevron-down'));
    head.addEventListener('click', () => { const on = head.getAttribute('aria-expanded') !== 'true'; head.setAttribute('aria-expanded', String(on)); rows.hidden = !on; });
    return head;
  };
  const colRows = h('div', { class: 'dc-rows' });
  const recentRows = h('div', { class: 'dc-rows' });
  const folderRows = h('div', { class: 'dc-rows' });
  const tagBtns = ['design', 'principles'].map((t) => h('button', { type: 'button', class: 'dc-tag', 'aria-pressed': 'false', text: '#' + t, onclick: () => { st.tag = st.tag === t ? null : t; tagBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === '#' + st.tag))); drawLists(); } }));
  const trash = h('button', { type: 'button', text: 'recently deleted' });
  const side = h('nav', { class: 'dc-side', 'aria-label': 'documents' },
    h('div', { class: 'dc-actions' }, newDoc, newFolder), search,
    h('div', { class: 'dc-scroll' },
      section('document collections', colRows), colRows,
      section('recent', recentRows), recentRows,
      section('document folder', folderRows), h('div', { class: 'dc-tags' }, tagBtns), folderRows),
    h('div', { class: 'dc-foot' }, trash));

  // ---- main: documents pane + right column, and the journal pane
  const main = pane({ journalMode: false });
  const jpane = pane({ journalMode: true });
  const rFacts = h('div');
  const rLinked = h('div', { class: 'dc-linked' });
  const right = h('aside', { class: 'dc-right', 'aria-label': 'file details' }, h('h4', { text: 'file' }), rFacts, rLinked);
  const docsPanel = h('div', { class: 'dc-panel', 'data-tab': 'documents' }, side, h('div', { class: 'dc-main' }, main.el, right));
  const jPanel = h('div', { class: 'dc-panel', 'data-tab': 'journal', hidden: true }, h('div', { class: 'dc-main' }, jpane.el));

  const bar = topbar({
    app: 'docs', tabs: ['documents', 'journal'], selected: 'documents',
    onTab: (name) => { st.tab = name; docsPanel.hidden = name !== 'documents'; jPanel.hidden = name !== 'journal'; },
  });
  bar.el.classList.add('dc-top');
  root.append(bar.el, docsPanel, jPanel);

  const fact = (k, v) => h('dl', { class: 'dc-fact' }, h('dt', { text: k }), h('dd', { text: v }));
  function drawRight() {
    const d = get(st.cur);
    rFacts.replaceChildren(fact('path', path(d)), fact('format', 'Markdown'), fact('encoding', 'utf-8'));
    const from = docs.filter((o) => o.id !== d.id && o.src.includes(`(doc:${d.id})`));
    rLinked.replaceChildren(h('h4', { text: 'linked from' }), ...(from.length ? from.map((o) => h('button', { type: 'button', class: 'dc-ln', onclick: () => open(o.id) }, ic('file'), o.title)) : [h('p', { class: 'dc-none', text: 'none' })]));
  }

  const inCollection = (d) => st.filter === 'all' || d.note;
  const matches = (d) => { const q = st.q.trim().toLowerCase(); return !q || d.title.toLowerCase().includes(q) || d.src.toLowerCase().includes(q); };
  function drawLists() {
    const was = root.contains(document.activeElement) && document.activeElement.dataset.k;
    const item = (d, where) => h('button', { type: 'button', class: 'dc-item', 'data-k': where + d.id, 'data-id': d.id, 'aria-current': String(st.tab === 'documents' && d.id === st.cur), onclick: () => open(d.id) }, ic('file'), h('span', { text: d.title }));
    const none = () => h('p', { class: 'dc-none', text: 'no documents' });
    const coll = [['all', 'all documents', 'copy'], ['notes', 'notes', 'file']];
    colRows.replaceChildren(...coll.map(([k, label, icon]) => h('button', { type: 'button', class: 'dc-item', 'data-k': 'col' + k, 'aria-current': String(st.filter === k), onclick: () => { st.filter = k; drawLists(); } }, ic(icon), h('span', { text: label }))));
    const rec = recent.map(get).filter((d) => matches(d) && inCollection(d));
    recentRows.replaceChildren(...(rec.length ? rec.map((d) => item(d, 'r')) : [none()]));
    const all = docs.filter((d) => matches(d) && inCollection(d) && (!st.tag || d.tags.includes(st.tag))).sort((a, b) => a.title.localeCompare(b.title));
    folderRows.replaceChildren(...(all.length ? all.map((d) => item(d, 'f')) : [none()]));
    if (was) root.querySelector(`[data-k="${was}"]`)?.focus({ preventScroll: true });
  }

  function open(id, fromJournal) {
    st.cur = id;
    if (st.tab !== 'documents') bar.select('documents');
    const d = get(id);
    main.show(d);
    drawRight();
    drawLists();
  }
  main.onDoc = (id) => open(id);
  jpane.onDoc = (id) => open(id);
  main.onSaved = () => { drawRight(); drawLists(); };

  newDoc.addEventListener('click', () => {
    const d = { id: 'new' + n++, title: 'untitled', note: false, tags: [], src: '' };
    docs.push(d);
    recent.unshift(d.id);
    st.filter = 'all'; st.q = ''; st.tag = null;
    search.value = '';
    tagBtns.forEach((b) => b.setAttribute('aria-pressed', 'false'));
    st.cur = d.id;
    main.show(d);
    drawRight();
    drawLists();
    main.setEdit(true);
  });
  newFolder.addEventListener('click', () => toast(root, 'in alles this makes a folder for your documents'));
  trash.addEventListener('click', () => toast(root, 'in alles this opens recently deleted documents'));
  search.addEventListener('input', () => { st.q = search.value; drawLists(); });
  search.addEventListener('keydown', (e) => { if (e.key === 'Escape' && search.value) { e.preventDefault(); search.value = ''; st.q = ''; drawLists(); } });
  [main, jpane].forEach((p) => p.ta.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); p.edit.click(); } }));

  main.show(get('q4'));
  jpane.show(journal);
  drawRight();
  drawLists();
}
