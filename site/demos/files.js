// the files app's project folder, as in shots/files.webp: locations, views, a selectable list, a preview
// and a trash with restore. every file is made up. labels from static/js/filesphase7.js
import { h, ic, css, topbar, toast } from './kit.js';

const KINDS = { pdf: 'pdf document', png: 'png image', txt: 'text file', md: 'markdown note', csv: 'csv table', folder: 'folder' };
const file = (name, size, changed, extra = {}) => ({ name, ext: name.includes('.') ? name.split('.').pop() : 'folder', size, changed, star: false, offline: false, deleted: null, ...extra });

const SERVER = [
  file('Brand guidelines.pdf', '72.1 KB', '10/9/2026', { offline: true }),
  file('Interview notes, round one.txt', '159 B', '9d ago'),
  file('Interview script.pdf', '85.1 KB', '3d ago', { offline: true }),
  file('Onboarding flow v3.png', '34.8 KB', '1d ago'),
  file('Palette.png', '24.7 KB', '9d ago'),
  file('Q3 design review.pdf', '96.4 KB', '12d ago'),
  file('Q4 timeline.png', '32.3 KB', '2d ago'),
  file('Roadmap summary.md', '123 B', '1d ago'),
  file('Usage metrics.csv', '96 B', '5d ago'),
  file('Logo draft v1.png', '41.2 KB', '3w ago', { deleted: '3d ago' }),
];
const DOCS = [
  file('Q4 roadmap.md', '2.1 KB', '1d ago', { offline: true }),
  file('Reading list.md', '864 B', '4d ago'),
  file('Weeknight dal.md', '1.4 KB', '9d ago'),
];
const SPACES = {
  server: { name: 'on this server', items: SERVER, folder: 'Fieldnote', writable: true },
  docs: { name: 'docs', items: DOCS, folder: 'Docs', writable: false },
};
const VIEWS = { all: 'all files', starred: 'starred', offline: 'available offline', trash: 'recently deleted' };
const EMPTY = { all: 'no files', starred: 'nothing starred', offline: 'nothing offline', trash: 'nothing deleted' };

export default function build(root) {
  css('files');
  root.classList.add('fl-app');
  let loc = 'server';
  let view = 'all';
  let query = '';
  let open = null; // the item in the preview
  let editing = null; // the new folder row's input
  const picked = new Set();

  const space = () => SPACES[loc];
  const visible = () => space().items.filter((f) => {
    if (view === 'trash' ? !f.deleted : f.deleted) return false;
    if (view === 'starred' && !f.star) return false;
    if (view === 'offline' && !f.offline) return false;
    return !query || f.name.toLowerCase().includes(query);
  });

  // ---- top bar ----
  const bar = topbar({
    app: 'files',
    tabs: ['files', 'gallery'],
    selected: 'files',
    onTab: (name) => {
      if (name !== 'gallery') return;
      toast(root, 'in alles gallery shows your pictures as a grid');
      bar.select('files');
    },
  });

  // ---- left column ----
  const locButton = (key, tag) => {
    const b = h('button', { type: 'button', class: 'fl-loc', 'aria-pressed': String(key === loc), 'data-k': 'loc:' + key },
      ic('folder'), h('span', { class: 'fl-loc-name' }, h('span', { text: SPACES[key].name }), h('small', { text: 'local' })), h('span', { class: 'fl-loc-tag', text: tag }));
    b.addEventListener('click', () => { loc = key; view = 'all'; query = ''; search.value = ''; closePreview(); cancelEdit(); picked.clear(); paint(); });
    return b;
  };
  const locs = [locButton('server', 'managed'), locButton('docs', 'read only')];
  const navs = Object.entries(VIEWS).map(([key, label]) => {
    const b = h('button', { type: 'button', class: 'fl-nav', 'aria-pressed': String(key === view), 'data-k': 'view:' + key, text: label });
    b.addEventListener('click', () => { view = key; closePreview(); cancelEdit(); picked.clear(); paint(); });
    return b;
  });
  const addLoc = h('button', { type: 'button', class: 'dm-btn', text: 'add location' });
  addLoc.addEventListener('click', () => toast(root, 'in alles this adds a folder, webdav or cloud location'));
  const side = h('div', { class: 'fl-side' }, h('div', { class: 'fl-side-head' }, h('span', { class: 'fl-side-title', text: 'locations' }), addLoc), ...locs, h('div', { class: 'fl-rule' }), ...navs);

  // ---- toolbar ----
  const up = h('button', { type: 'button', class: 'fl-up', 'aria-label': 'up one folder' }, ic('chevron-up'));
  up.addEventListener('click', () => toast(root, 'in alles this goes up one folder'));
  const crumb = h('button', { type: 'button', class: 'fl-crumb' });
  crumb.addEventListener('click', () => toast(root, 'in alles this opens the top of the location'));
  const slash = h('span', { class: 'fl-slash', text: '/' });
  const title = h('span', { class: 'fl-title' });
  const settingsBtn = h('button', { type: 'button', class: 'dm-btn quiet', text: 'location settings' });
  settingsBtn.addEventListener('click', () => toast(root, 'in alles this opens the location’s settings'));
  const search = h('input', { class: 'dm-input fl-search', type: 'text', placeholder: 'search files', 'aria-label': 'search files', autocomplete: 'off' });
  search.addEventListener('input', () => { query = search.value.trim().toLowerCase(); cancelEdit(); paintList(); });
  const newFolder = h('button', { type: 'button', class: 'dm-btn quiet', text: 'new folder' });
  newFolder.addEventListener('click', () => startFolder());
  const upload = h('button', { type: 'button', class: 'dm-btn primary', text: 'upload' });
  upload.addEventListener('click', () => toast(root, space().writable ? 'in alles this adds files from your device' : 'docs is read only, nothing can be added'));
  const tools = h('div', { class: 'fl-tools' }, up, crumb, slash, title, h('span', { class: 'dm-spacer' }), settingsBtn, search, newFolder, upload);

  // ---- table ----
  const allBox = h('button', { type: 'button', class: 'fl-check', role: 'checkbox', 'aria-checked': 'false', 'aria-label': 'select all', 'data-k': 'all' }, ic('check'));
  allBox.addEventListener('click', () => {
    const list = visible();
    const every = list.length && list.every((f) => picked.has(f));
    list.forEach((f) => (every ? picked.delete(f) : picked.add(f)));
    syncSelection();
  });
  const count = h('strong');
  const act = (label, icon, on) => {
    const b = h('button', { type: 'button', class: 'dm-btn quiet', 'data-k': label }, ic(icon), label);
    b.addEventListener('click', on);
    return b;
  };
  const sel = h('div', { class: 'fl-sel', hidden: true }, count,
    act('star', 'star', () => {
      const all = [...picked];
      const unstar = all.every((f) => f.star);
      all.forEach((f) => { f.star = !unstar; });
      toast(root, unstar ? `unstarred ${all.length} ${all.length === 1 ? 'file' : 'files'}` : `starred ${all.length} ${all.length === 1 ? 'file' : 'files'}`);
      paintList();
    }),
    act('download', 'download', () => toast(root, `in alles this downloads ${picked.size} ${picked.size === 1 ? 'file' : 'files'} to your device`)),
    act('delete', 'trash', () => {
      if (!space().writable) { toast(root, 'docs is read only, nothing was deleted'); return; }
      [...picked].forEach((f) => { f.deleted = 'just now'; });
      picked.clear();
      toast(root, 'moved to recently deleted');
      paintList();
    }));
  const cols = h('div', { class: 'fl-hcols' }, h('span'), h('span', { text: 'name' }), h('span', { text: 'size' }), h('span', { class: 'fl-hlast', text: 'changed' }));
  const head = h('div', { class: 'fl-head' }, allBox, cols, sel);
  const list = h('div', { class: 'fl-list' });
  const main = h('div', { class: 'fl-main' }, tools, head, list);
  const preview = h('div', { class: 'fl-prev', role: 'dialog', tabindex: '-1', hidden: true });
  const wrap = h('div', { class: 'fl' }, side, main, preview);
  root.append(bar.el, wrap);

  // ---- selection ----
  const syncSelection = () => {
    const rows = visible();
    const n = rows.filter((f) => picked.has(f)).length;
    list.querySelectorAll('.fl-row[data-i]').forEach((row) => {
      const on = picked.has(rows[+row.dataset.i]);
      row.classList.toggle('sel', on);
      row.querySelector('.fl-check').setAttribute('aria-checked', String(on));
    });
    allBox.setAttribute('aria-checked', n === 0 ? 'false' : n === rows.length ? 'true' : 'mixed');
    sel.hidden = n === 0;
    cols.hidden = n !== 0;
    count.textContent = `${n} selected`;
  };

  // ---- preview ----
  const closePreview = (focus) => {
    if (!open) return;
    const from = open;
    open = null;
    preview.hidden = true;
    if (focus) [...list.querySelectorAll('.fl-name')].find((b) => b.dataset.n === from.name)?.focus();
  };
  const openPreview = (f) => {
    open = f;
    const art = f.ext === 'png' || f.ext === 'pdf'
      ? h('div', { class: 'fl-art', 'aria-hidden': 'true' }, ic(f.ext === 'png' ? 'image' : 'file'), h('span', { text: KINDS[f.ext] }))
      : null;
    const close = h('button', { type: 'button', class: 'dm-btn icon', 'aria-label': 'close preview' }, ic('close'));
    close.addEventListener('click', () => closePreview(true));
    preview.setAttribute('aria-label', f.name);
    preview.replaceChildren(
      h('div', { class: 'fl-prev-top' }, h('span', { class: 'dm-h', text: f.name }), close), art,
      h('dl', { class: 'fl-facts' }, h('dt', { text: 'name' }), h('dd', { text: f.name }), h('dt', { text: 'kind' }), h('dd', { text: KINDS[f.ext] || f.ext + ' file' }),
        h('dt', { text: 'size' }), h('dd', { text: f.size || 'empty' }), h('dt', { text: f.deleted ? 'deleted' : 'changed' }), h('dd', { text: f.deleted || f.changed })));
    preview.hidden = false;
    preview.focus({ preventScroll: true });
  };
  root.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open && !editing) { e.preventDefault(); closePreview(true); } });

  // ---- new folder ----
  const cancelEdit = () => { if (editing) { const row = editing.closest('.fl-row'); editing = null; row?.remove(); } };
  const startFolder = () => {
    if (!space().writable) { toast(root, 'docs is read only, nothing can be added'); return; }
    if (view !== 'all') { view = 'all'; paint(); }
    query = '';
    search.value = '';
    cancelEdit();
    paintList();
    const input = h('input', { class: 'fl-folder-name', type: 'text', value: 'untitled folder', 'aria-label': 'folder name', autocomplete: 'off', spellcheck: 'false' });
    const row = h('div', { class: 'fl-row' }, h('span'), ic('folder'), input, h('span', { class: 'fl-cell' }), h('span', { class: 'fl-cell', text: 'just now' }));
    row.children[1].classList.add('fl-ico');
    list.prepend(row);
    editing = input;
    let done = false;
    const keep = () => {
      if (done) return;
      done = true;
      let name = input.value.trim() || 'untitled folder';
      const taken = (n) => space().items.some((f) => !f.deleted && f.name.toLowerCase() === n.toLowerCase());
      for (let i = 2, base = name; taken(name); i++) name = `${base} ${i}`;
      editing = null;
      space().items.unshift(file(name, '', 'just now'));
      paintList();
    };
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); keep(); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done = true; cancelEdit(); }
    });
    input.addEventListener('blur', keep);
    input.focus();
    input.select();
  };

  // ---- paint ----
  const paintList = () => {
    const rows = visible();
    [...picked].forEach((f) => { if (!rows.includes(f)) picked.delete(f); });
    if (open && !rows.includes(open)) closePreview();
    list.replaceChildren(...rows.map((f, i) => {
      const box = h('button', { type: 'button', class: 'fl-check', role: 'checkbox', 'aria-checked': 'false', 'aria-label': 'select ' + f.name, 'data-k': 'pick:' + f.name }, ic('check'));
      box.addEventListener('click', () => {
        if (picked.has(f)) picked.delete(f); else picked.add(f);
        syncSelection();
      });
      const name = h('button', { type: 'button', class: 'fl-name', 'data-n': f.name, 'data-k': 'open:' + f.name }, h('span', { text: f.name }), f.star ? ic('star-fill') : null);
      name.addEventListener('click', () => (open === f ? closePreview(true) : openPreview(f)));
      const restore = h('button', { type: 'button', class: 'dm-btn', text: 'restore', 'data-k': 'restore:' + f.name });
      restore.addEventListener('click', () => {
        f.deleted = null;
        toast(root, `restored ${f.name}`);
        paintList();
      });
      return h('div', { class: 'fl-row', 'data-i': String(i) }, box, ic(f.ext === 'png' ? 'image' : f.ext === 'folder' ? 'folder' : 'file'), name,
        h('span', { class: 'fl-cell', text: f.size }), h('span', { class: 'fl-cell', text: view === 'trash' ? f.deleted : f.changed }), view === 'trash' ? restore : null);
    }));
    list.querySelectorAll('.fl-row > .ic').forEach((i) => i.classList.add('fl-ico'));
    if (!rows.length) list.append(h('p', { class: 'fl-empty', text: query ? 'no matches' : EMPTY[view] }));
    syncSelection();
  };

  const paint = () => {
    locs.forEach((b, i) => b.setAttribute('aria-pressed', String(Object.keys(SPACES)[i] === loc)));
    navs.forEach((b, i) => b.setAttribute('aria-pressed', String(Object.keys(VIEWS)[i] === view)));
    const whole = view === 'all';
    crumb.hidden = !whole;
    slash.hidden = !whole;
    up.hidden = !whole;
    crumb.textContent = space().name;
    title.textContent = whole ? space().folder : VIEWS[view];
    wrap.classList.toggle('fl-trash', view === 'trash');
    cols.querySelector('.fl-hlast').textContent = view === 'trash' ? 'deleted' : 'changed';
    newFolder.hidden = view === 'trash';
    paintList();
  };
  paint();
}
