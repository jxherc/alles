import { toast } from './util.js';
import { confirm as confirmDialog, prompt as promptDialog } from './dialog.js';

let _memories = [];
let _searchTimeout = null;
let _activeCategory = 'all';
let _memoryPolicy = 'ask';
let _memoryLastActivePolicy = 'ask';
let _memoryAutoInject = true;

const CATEGORIES = ['all', 'identity', 'preference', 'fact', 'task', 'general'];

export function filterMemoriesByCategory(mems, cat = _activeCategory) {
  return cat === 'all' ? mems : mems.filter(m => m.category === cat);
}

export async function loadMemories() {
  const [memories, settings] = await Promise.all([
    _requestJson('/api/memories'),
    _requestJson('/api/settings'),
  ]);
  _memories = memories;
  _memoryPolicy = settings.memory_policy || 'ask';
  if (_memoryPolicy !== 'off') _memoryLastActivePolicy = _memoryPolicy;
  _memoryAutoInject = settings.memory_auto_inject !== false;
  _renderPolicy();
  _renderCategoryFilter();
  renderMemories(filterMemoriesByCategory(_memories));
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
      renderMemories(filterMemoriesByCategory(_memories));
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
    <div class="mem-item${m.pinned ? ' pinned' : ''}${m.status === 'suggested' ? ' suggested' : ''}" data-id="${m.id}">
      <div class="mem-text">${escHtml(m.text)}</div>
      <div class="mem-meta">
        <span class="mem-cat">${m.category}</span>
        ${m.pinned ? '<span class="mem-pin">pinned</span>' : ''}
        ${m.status === 'suggested' ? '<span class="mem-review">review</span>' : ''}
        <span class="mem-source">${escHtml(_provenanceLabel(m))} · ${escHtml(m.trust || 'owner')}</span>
        <span class="mem-source">${m.scope === 'project' ? 'project' : 'global'}</span>
        ${m.used_in_runs?.length ? `<span class="mem-source">used in ${m.used_in_runs.length} chat${m.used_in_runs.length === 1 ? '' : 's'}</span>` : ''}
      </div>
      <div class="mem-actions">
        ${m.status === 'suggested' ? `<button class="act-btn mem-accept-btn" data-id="${m.id}">accept</button>` : ''}
        <button class="act-btn mem-edit-btn" data-id="${m.id}">edit</button>
        ${window._currentSession?.project_id || m.scope === 'project' ? `<button class="act-btn mem-scope-btn" data-id="${m.id}" data-scope="${m.scope || 'global'}">${m.scope === 'project' ? 'make global' : 'use project'}</button>` : ''}
        <button class="act-btn mem-pin-btn" data-id="${m.id}" data-pinned="${m.pinned}">${m.pinned ? 'unpin' : 'pin'}</button>
        <button class="act-btn mem-del-btn" data-id="${m.id}">forget</button>
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
  list.querySelectorAll('.mem-edit-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const memory = _memories.find(item => item.id === btn.dataset.id);
      if (!memory) return;
      const text = await promptDialog('edit memory', memory.text);
      if (text === null || !text.trim() || text.trim() === memory.text) return;
      try {
        await _requestJson(`/api/memories/${memory.id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ text: text.trim() }),
        });
        toast('memory updated', 'success');
        await loadMemories();
      } catch (error) { toast(error.message, 'error'); }
    });
  });
  list.querySelectorAll('.mem-scope-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const useProject = btn.dataset.scope !== 'project';
      const projectId = window._currentSession?.project_id || '';
      if (useProject && !projectId) { toast('open a project chat first', 'error'); return; }
      try {
        await _requestJson(`/api/memories/${btn.dataset.id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            scope: useProject ? 'project' : 'global',
            project_id: useProject ? projectId : null,
          }),
        });
        await loadMemories();
      } catch (error) { toast(error.message, 'error'); }
    });
  });
  list.querySelectorAll('.mem-accept-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await _requestJson(`/api/memories/${btn.dataset.id}/accept`, { method: 'POST' });
        toast('memory accepted', 'success');
        await loadMemories();
      } catch (error) { toast(error.message, 'error'); }
    });
  });
}

function _provenanceLabel(memory) {
  let kind = '';
  try { kind = JSON.parse(memory.provenance || '{}').kind || ''; } catch {}
  return {
    owner_request: 'you asked aide to remember',
    direct_owner_statement: 'your direct preference',
    model_suggestion: 'suggested from your chat',
  }[kind] || memory.source || 'manual';
}

function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _renderPolicy() {
  document.querySelectorAll('[data-memory-policy]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.memoryPolicy === _memoryPolicy);
    btn.setAttribute('aria-pressed', String(btn.dataset.memoryPolicy === _memoryPolicy));
  });
  const desc = document.getElementById('mem-policy-desc');
  if (desc) desc.textContent = {
    off: 'do not read or write long-term memory',
    ask: 'suggest memories for you to review',
    auto: 'save only low-risk preferences you state directly',
  }[_memoryPolicy] || '';
  const off = _memoryPolicy === 'off';
  const inject = document.getElementById('s-memory-inject-toggle');
  if (inject) {
    inject.classList.toggle('on', !off && _memoryAutoInject);
    inject.setAttribute('aria-checked', String(!off && _memoryAutoInject));
    inject.setAttribute('aria-disabled', String(off));
  }
  ['mem-extract-btn', 'mem-add-input', 'mem-cat-cycle-btn', 'mem-add-btn'].forEach(id => {
    const control = document.getElementById(id);
    if (!control) return;
    control.disabled = off;
    control.setAttribute('aria-disabled', String(off));
  });
  const pause = document.getElementById('mem-pause-btn');
  if (pause) {
    pause.textContent = off ? 'resume' : 'pause';
    pause.setAttribute('aria-pressed', String(off));
  }
}

async function _requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) throw new Error(data.detail || 'memory request failed');
  return data;
}

let _panelBound = false;

export function initMemoryPanel() {
  // only bind events once — the list re-renders on loadMemories
  if (_panelBound) { loadMemories(); return; }
  _panelBound = true;

  document.querySelectorAll('[data-memory-policy]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await _requestJson('/api/settings', {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ memory_policy: btn.dataset.memoryPolicy }),
        });
        _memoryPolicy = btn.dataset.memoryPolicy;
        _renderPolicy();
        await loadMemories();
      } catch (error) { toast(error.message, 'error'); }
    });
  });

  document.getElementById('s-memory-inject-toggle')?.addEventListener('click', async event => {
    if (_memoryPolicy === 'off') return;
    const next = !event.currentTarget.classList.contains('on');
    try {
      await _requestJson('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ memory_auto_inject: next }),
      });
      _memoryAutoInject = next;
      _renderPolicy();
    } catch (error) { toast(error.message, 'error'); }
  });

  document.getElementById('mem-pause-btn')?.addEventListener('click', async () => {
    const next = _memoryPolicy === 'off' ? _memoryLastActivePolicy : 'off';
    try {
      await _requestJson('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ memory_policy: next }),
      });
      if (_memoryPolicy !== 'off') _memoryLastActivePolicy = _memoryPolicy;
      _memoryPolicy = next;
      _renderPolicy();
      await loadMemories();
    } catch (error) { toast(error.message, 'error'); }
  });

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
    try {
      const memory = await _requestJson('/api/memories', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          text,
          category: cat,
          scope: window._currentSession?.project_id ? 'project' : 'global',
          project_id: window._currentSession?.project_id || '',
        }),
      });
      inp.value = '';
      _showUndo(memory.id);
      toast('remembered', 'success');
      await loadMemories();
    } catch (error) { toast(error.message, 'error'); }
  });

  document.getElementById('mem-add-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('mem-add-btn')?.click();
  });

  // search
  document.getElementById('mem-search')?.addEventListener('input', e => {
    clearTimeout(_searchTimeout);
    const q = e.target.value.trim();
    if (!q) { renderMemories(filterMemoriesByCategory(_memories)); return; }
    _searchTimeout = setTimeout(async () => {
      const r = await fetch('/api/memories/search', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ query: q, top_k: 20 }),
      });
      renderMemories(filterMemoriesByCategory(await r.json()));
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
      const data = await _requestJson('/api/memories/extract', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      });
      toast(`${data.extracted} memories ready to review`, 'success');
      await loadMemories();
    } catch (e) {
      toast('extraction failed', 'error');
    } finally {
      btn.textContent = 'extract from chat';
      btn.disabled = _memoryPolicy === 'off';
    }
  });

  document.getElementById('mem-clear-btn')?.addEventListener('click', async () => {
    if (!await confirmDialog('forget every saved and suggested memory?')) return;
    try {
      const result = await _requestJson('/api/memories', { method: 'DELETE' });
      toast(`${result.deleted || 0} memories cleared`, 'success');
      await loadMemories();
    } catch (error) { toast(error.message, 'error'); }
  });

  loadMemories();
}

function _showUndo(memoryId) {
  const el = document.getElementById('mem-undo');
  if (!el) return;
  el.hidden = false;
  const button = el.querySelector('button');
  button.onclick = async () => {
    await fetch(`/api/memories/${memoryId}`, { method: 'DELETE' });
    el.hidden = true;
    toast('memory removed', 'success');
    await loadMemories();
  };
  clearTimeout(_showUndo.timer);
  _showUndo.timer = setTimeout(() => { el.hidden = true; }, 10000);
}
