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
  } catch (e) {}
}

function _renderResults({ chats = [], notes = [], memories = [] }) {
  const container = document.getElementById('search-results');
  if (!container) return;

  let html = '';

  if (chats.length) {
    html += '<div class="search-group-label">chats</div>';
    html += chats.map(c => `
      <div class="search-result" data-type="chat" data-id="${c.session_id}">
        <span class="search-result-name">${_esc(c.session_name)}</span>
        <span class="search-result-snippet">${_esc(c.snippet)}</span>
      </div>`).join('');
  }
  if (notes.length) {
    html += '<div class="search-group-label">notes</div>';
    html += notes.map(n => `
      <div class="search-result" data-type="note" data-id="${n.id}">
        <span class="search-result-name">${_esc(n.title)}</span>
        <span class="search-result-snippet">${_esc(n.snippet)}</span>
      </div>`).join('');
  }
  if (memories.length) {
    html += '<div class="search-group-label">memories</div>';
    html += memories.map(m => `
      <div class="search-result" data-type="memory">
        <span class="search-result-snippet">${_esc(m.text)}</span>
      </div>`).join('');
  }

  if (!html) html = '<div class="search-empty">no results</div>';
  container.innerHTML = html;

  container.querySelectorAll('.search-result[data-type="chat"]').forEach(el => {
    el.addEventListener('click', async () => {
      closeSearch();
      const { selectSession } = await import('./sessions.js');
      selectSession(el.dataset.id);
      // switch to chat view
      document.querySelector('.nav-item[data-view="chat"]')?.click();
    });
  });

  container.querySelectorAll('.search-result[data-type="note"]').forEach(el => {
    el.addEventListener('click', () => {
      closeSearch();
      document.querySelector('.nav-item[data-view="notes"]')?.click();
    });
  });

  container.querySelectorAll('.search-result[data-type="memory"]').forEach(el => {
    el.addEventListener('click', () => {
      closeSearch();
      document.querySelector('.nav-item[data-view="memory"]')?.click();
    });
  });
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
