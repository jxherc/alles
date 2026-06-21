import { filterCommands } from './palette.js';

let _debounce = null;

export function openSearch() {
  const modal = document.getElementById('search-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  const inp = document.getElementById('search-input');
  if (inp) { inp.value = ''; inp.focus(); }
  document.getElementById('search-results').innerHTML = '';
}

export function closeSearch() {
  const modal = document.getElementById('search-modal');
  if (modal) modal.style.display = 'none';
}

export function initSearch() {
  const inp = document.getElementById('search-input');
  if (!inp) return;

  inp.addEventListener('input', () => {
    clearTimeout(_debounce);
    _debounce = setTimeout(() => _runSearch(inp.value.trim()), 150);
  });

  inp.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSearch();
  });

  document.getElementById('search-modal')?.addEventListener('click', e => {
    if (e.target === document.getElementById('search-modal')) closeSearch();
  });
}

let _lastQ = '';

async function _runSearch(q) {
  _lastQ = q;
  if (!q) { document.getElementById('search-results').innerHTML = ''; return; }
  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await r.json();
    _renderResults(data, q);
  } catch (e) {
    const el = document.getElementById('search-results');
    if (el) el.innerHTML = '<div style="padding:1rem;color:var(--muted);font-size:0.8rem">search failed — check your connection and try again</div>';
  }
}

function _money(amt) {
  const n = Number(amt) || 0;
  return (n >= 0 ? '+' : '−') + Math.abs(n).toFixed(2);
}

function _group(label, items, render) {
  if (!items.length) return '';
  return `<div class="search-group-label">${label}</div>` + items.map(render).join('');
}

function _row(attrs, name, snip) {
  return `<div class="search-result" ${attrs}>
      ${name ? `<span class="search-result-name">${_esc(name)}</span>` : ''}
      ${snip ? `<span class="search-result-snippet">${_esc(snip)}</span>` : ''}
    </div>`;
}

function _renderResults(d, q) {
  const { chats = [], notes = [], tasks = [], calendar = [], contacts = [],
          memories = [], mail = [], money = [], subs = [], photos = [],
          books = [], read = [], habits = [], watch = [] } = d || {};
  const container = document.getElementById('search-results');
  if (!container) return;

  // "go to" — fuzzy-match the query against every app/view, so you can jump even
  // when the view has no matching data yet (a true command-palette behaviour)
  const navHits = q ? filterCommands(window._navCommands || [], q).slice(0, 6) : [];

  let html = '';
  html += _group('go to',    navHits,  c => _row(`data-type="nav" data-view="${_esc(c.view)}"`, c.label, c.hint));
  html += _group('chats',    chats,    c => _row(`data-type="chat" data-id="${_esc(c.session_id)}"`, c.session_name, c.snippet));
  html += _group('docs',     notes,    n => _row(`data-type="note" data-path="${_esc(n.path)}"`, n.name, n.snippet));
  html += _group('mail',     mail,     m => _row(`data-type="nav" data-view="mail"`, m.subject, _fromName(m.from)));
  html += _group('tasks',    tasks,    t => _row(`data-type="nav" data-view="tasks"`, t.title, t.done ? 'done' : ''));
  html += _group('calendar', calendar, e => _row(`data-type="nav" data-view="calendar"`, e.title, e.when));
  html += _group('books',    books,    b => _row(`data-type="nav" data-view="books"`, b.title, [b.author, b.status].filter(Boolean).join(' · ')));
  html += _group('read',     read,     i => _row(`data-type="nav" data-view="read"`, i.title, i.site));
  html += _group('habits',   habits,   h => _row(`data-type="nav" data-view="habits"`, h.name, ''));
  html += _group('watch',    watch,    m => _row(`data-type="nav" data-view="watch"`, m.name, m.url));
  html += _group('money',    money,    t => _row(`data-type="nav" data-view="money"`, t.payee, `${_money(t.amount)} · ${t.when}`));
  html += _group('subs',     subs,     s => _row(`data-type="nav" data-view="subs"`, s.name, s.snippet));
  html += _group('contacts', contacts, c => _row(`data-type="nav" data-view="contacts"`, c.name, c.snippet));
  html += _group('photos',   photos,   p => _row(`data-type="nav" data-view="photos"`, p.name, ''));
  html += _group('memories', memories, m => _row(`data-type="nav" data-view="memory"`, m.text, ''));

  // action rails — search is also the place you act: ask aide, or research the web
  const rail = q ? `<div class="search-actions">
      <button class="search-act" data-act="ask"><b>ask aide</b> about “${_esc(q.slice(0, 40))}”</button>
      <button class="search-act" data-act="web">research the web ↗</button>
    </div>` : '';

  container.innerHTML = rail + (html || '<div class="search-empty">no matches — ask aide or search the web above</div>');
  container.querySelector('[data-act="ask"]')?.addEventListener('click', () => { closeSearch(); window._askInChat?.(_lastQ, false); });
  container.querySelector('[data-act="web"]')?.addEventListener('click', () => { closeSearch(); window._askInChat?.(_lastQ, true); });
  container.querySelectorAll('.search-result').forEach(el => el.addEventListener('click', () => _go(el)));
}

function _fromName(f) {
  const m = /^(.*?)\s*<([^>]+)>/.exec(f || '');
  return (m ? (m[1].replace(/"/g, '').trim() || m[2]) : f) || '';
}

async function _go(el) {
  closeSearch();
  const type = el.dataset.type;
  if (type === 'chat') {
    window._navigateTo?.('chat');
    const { selectSession } = await import('./sessions.js');
    selectSession(el.dataset.id);
  } else if (type === 'note') {
    window._navigateTo?.('wiki');
    const { openNote } = await import('./vaultmd.js');
    openNote(el.dataset.path);
  } else {
    // nav — may be a different subdomain; navigateTo cross-jumps with SSO when needed
    window._navigateTo?.(el.dataset.view);
  }
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
