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

async function _runSearch(q) {
  if (!q) { document.getElementById('search-results').innerHTML = ''; return; }
  try {
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await r.json();
    _renderResults(data);
  } catch (e) {
    const el = document.getElementById('search-results');
    if (el) el.innerHTML = '<div style="padding:1rem;color:var(--muted);font-size:0.8rem">search failed — check your connection and try again</div>';
  }
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

function _renderResults(d) {
  const { chats = [], notes = [], tasks = [], calendar = [], contacts = [], memories = [] } = d || {};
  const container = document.getElementById('search-results');
  if (!container) return;

  let html = '';
  html += _group('chats',    chats,    c => _row(`data-type="chat" data-id="${_esc(c.session_id)}"`, c.session_name, c.snippet));
  html += _group('docs',     notes,    n => _row(`data-type="note" data-path="${_esc(n.path)}"`, n.name, n.snippet));
  html += _group('tasks',    tasks,    t => _row(`data-type="nav" data-view="tasks"`, t.title, t.done ? 'done' : ''));
  html += _group('calendar', calendar, e => _row(`data-type="nav" data-view="calendar"`, e.title, e.when));
  html += _group('contacts', contacts, c => _row(`data-type="nav" data-view="contacts"`, c.name, c.snippet));
  html += _group('memories', memories, m => _row(`data-type="nav" data-view="memory"`, m.text, ''));

  container.innerHTML = html || '<div class="search-empty">no results</div>';
  container.querySelectorAll('.search-result').forEach(el => el.addEventListener('click', () => _go(el)));
}

async function _go(el) {
  closeSearch();
  const type = el.dataset.type;
  if (type === 'chat') {
    document.querySelector('.nav-item[data-view="chat"]')?.click();
    const { selectSession } = await import('./sessions.js');
    selectSession(el.dataset.id);
  } else if (type === 'note') {
    document.querySelector('.nav-item[data-view="wiki"]')?.click();
    const { openNote } = await import('./vaultmd.js');
    openNote(el.dataset.path);
  } else {
    document.querySelector(`.nav-item[data-view="${el.dataset.view}"]`)?.click();
  }
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
