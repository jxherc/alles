import { toast } from './util.js';

let _memories = [];
let _searchTimeout = null;
let _activeCategory = 'all';

const CATEGORIES = ['all', 'identity', 'preference', 'fact', 'task', 'general'];

export async function loadMemories() {
  const r = await fetch('/api/memories');
  _memories = await r.json();
  _renderCategoryFilter();
  const filtered = _activeCategory === 'all' ? _memories : _memories.filter(m => m.category === _activeCategory);
  renderMemories(filtered);
}

function _renderCategoryFilter() {
  const el = document.getElementById('mem-category-filter');
  if (!el) return;
  el.innerHTML = CATEGORIES.map(c =>
    `<button class="mem-cat-btn${c === _activeCategory ? ' active' : ''}" data-cat="${c}">${c}</button>`
  ).join('');
  el.querySelectorAll('.mem-cat-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _activeCategory = btn.dataset.cat;
      _renderCategoryFilter();
      const filtered = _activeCategory === 'all' ? _memories : _memories.filter(m => m.category === _activeCategory);
      renderMemories(filtered);
    });
  });
}

function renderMemories(mems) {
  const list = document.getElementById('memory-list');
  if (!list) return;

  if (!mems.length) {
    list.innerHTML = `<div class="mem-empty">no ${_activeCategory === 'all' ? '' : _activeCategory + ' '}memories</div>`;
    return;
  }

  list.innerHTML = mems.map(m => `
    <div class="mem-item${m.pinned ? ' pinned' : ''}" data-id="${m.id}">
      <div class="mem-text">${escHtml(m.text)}</div>
      <div class="mem-meta">
        <span class="mem-cat">${m.category}</span>
        ${m.pinned ? '<span class="mem-pin">pinned</span>' : ''}
        <span class="mem-source">${m.source}</span>
      </div>
      <div class="mem-actions">
        <button class="act-btn mem-pin-btn" data-id="${m.id}" data-pinned="${m.pinned}">${m.pinned ? 'unpin' : 'pin'}</button>
        <button class="act-btn mem-del-btn" data-id="${m.id}">delete</button>
      </div>
    </div>
  `).join('');

  list.querySelectorAll('.mem-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      await fetch(`/api/memories/${btn.dataset.id}`, { method: 'DELETE' });
      await loadMemories();
    });
  });

  list.querySelectorAll('.mem-pin-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const pinned = btn.dataset.pinned === 'true';
      await fetch(`/api/memories/${btn.dataset.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pinned: !pinned }),
      });
      await loadMemories();
    });
  });
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

let _panelBound = false;

export function initMemoryPanel() {
  // only bind events once — the list re-renders on loadMemories
  if (_panelBound) { loadMemories(); return; }
  _panelBound = true;

  // add memory form
  // category cycle button
  const cycleBtn = document.getElementById('mem-cat-cycle-btn');
  const CATS = ['general','identity','preference','fact','task'];
  cycleBtn?.addEventListener('click', () => {
    const cur = cycleBtn.dataset.val || 'general';
    const next = CATS[(CATS.indexOf(cur) + 1) % CATS.length];
    cycleBtn.dataset.val = next;
    cycleBtn.textContent = next;
  });

  document.getElementById('mem-add-btn')?.addEventListener('click', async () => {
    const inp = document.getElementById('mem-add-input');
    const cat = document.getElementById('mem-cat-cycle-btn')?.dataset.val || 'general';
    const text = inp?.value.trim();
    if (!text) return;
    await fetch('/api/memories', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, category: cat }),
    });
    inp.value = '';
    toast('memory saved', 'success');
    await loadMemories();
  });

  document.getElementById('mem-add-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('mem-add-btn')?.click();
  });

  // search
  document.getElementById('mem-search')?.addEventListener('input', e => {
    clearTimeout(_searchTimeout);
    const q = e.target.value.trim();
    if (!q) { renderMemories(_memories); return; }
    _searchTimeout = setTimeout(async () => {
      const r = await fetch('/api/memories/search', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ query: q, top_k: 20 }),
      });
      renderMemories(await r.json());
    }, 300);
  });

  // extract from current session
  document.getElementById('mem-extract-btn')?.addEventListener('click', async () => {
    const sid = window._currentSession?.id;
    if (!sid) { toast('open a chat session first', 'error'); return; }
    const btn = document.getElementById('mem-extract-btn');
    btn.textContent = 'extracting...';
    btn.disabled = true;
    try {
      const r = await fetch('/api/memories/extract', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      });
      const data = await r.json();
      toast(`extracted ${data.extracted} memories`, 'success');
      await loadMemories();
    } catch (e) {
      toast('extraction failed', 'error');
    } finally {
      btn.textContent = 'extract from chat';
      btn.disabled = false;
    }
  });

  loadMemories();
}
