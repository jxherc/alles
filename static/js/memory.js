import { toast } from './util.js';
import { confirm as confirmDialog, fields as fieldsDialog } from './dialog.js';

let _memories = [];
let _searchTimeout = null;
let _activeCategory = 'all';
let _memoryPolicy = 'ask';
let _memoryLastActivePolicy = 'ask';
let _memoryAutoInject = true;
let _loadGeneration = 0;
let _searchGeneration = 0;
let _searchResults = null;
let _addRevision = 0;
const _pendingActions = new Set();

const CATEGORIES = ['all', 'identity', 'preference', 'fact', 'task', 'general'];

export function filterMemoriesByCategory(mems, cat = _activeCategory) {
  return cat === 'all' ? mems : mems.filter(m => m.category === cat);
}

export async function loadMemories() {
  const generation = ++_loadGeneration;
  try {
    const [memories, settings] = await Promise.all([
      _requestJson('/api/memories'),
      _requestJson('/api/settings'),
    ]);
    if (generation !== _loadGeneration) return false;
    if (!Array.isArray(memories) || !settings || typeof settings !== 'object' || Array.isArray(settings)) {
      throw new Error('invalid memory response');
    }
    _memories = memories;
    _memoryPolicy = settings.memory_policy || 'ask';
    if (_memoryPolicy !== 'off') _memoryLastActivePolicy = _memoryPolicy;
    _memoryAutoInject = settings.memory_auto_inject !== false;
    _clearReadError('load');
    _renderPolicy();
    _renderCategoryFilter();
    _renderCurrentMemories();
    const query = document.getElementById('mem-search')?.value.trim();
    if (query) await _searchMemories(query);
    return true;
  } catch (error) {
    if (generation === _loadGeneration) {
      _showReadError('load', `could not refresh memories: ${error.message}. retry to update this list.`, loadMemories);
    }
    return false;
  }
}

function _renderCurrentMemories() {
  renderMemories(filterMemoriesByCategory(_searchResults ?? _memories));
}

function _clearReadError(kind) {
  document.getElementById(`mem-${kind}-error`)?.remove();
}

function _showReadError(kind, message, retry) {
  const list = document.getElementById('memory-list');
  if (!list) return;
  let status = document.getElementById(`mem-${kind}-error`);
  if (!status) {
    status = document.createElement('div');
    status.id = `mem-${kind}-error`;
    status.className = 's-card-hint';
    status.setAttribute('role', 'alert');
    list.parentNode.insertBefore(status, list);
  }
  status.innerHTML = `${escHtml(message)} <button type="button" class="act-btn">retry</button>`;
  status.querySelector('button').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try { await retry(); } finally { button.disabled = false; }
  });
}

async function _searchMemories(query, generation = ++_searchGeneration) {
  try {
    const memories = await _requestJson('/api/memories/search', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, top_k: 20 }),
    });
    if (generation !== _searchGeneration) return;
    if (!Array.isArray(memories)) throw new Error('invalid memory search response');
    _searchResults = memories;
    _clearReadError('search');
    _renderCurrentMemories();
  } catch (error) {
    if (generation === _searchGeneration) {
      _showReadError('search', `could not search memories: ${error.message}. previous results are still shown.`, () => _searchMemories(query));
    }
  }
}

function _requireMemoryReceipt(memory, expected = {}) {
  if (!memory || Array.isArray(memory)
      || typeof memory.id !== 'string' || !memory.id.trim()
      || typeof memory.text !== 'string' || !memory.text.trim()
      || typeof memory.category !== 'string' || !memory.category.trim()
      || typeof memory.pinned !== 'boolean'
      || !['global', 'project'].includes(memory.scope)
      || !['active', 'suggested'].includes(memory.status)
      || (memory.scope === 'project' && (typeof memory.project_id !== 'string' || !memory.project_id.trim()))
      || Object.entries(expected).some(([key, value]) => memory[key] !== value)) {
    throw new Error('could not confirm memory change: invalid response');
  }
}

function _requireRemovalReceipt(receipt, clear = false) {
  if (receipt?.ok !== true || (clear && (!Number.isInteger(receipt.deleted) || receipt.deleted < 0))) {
    throw new Error('could not confirm memory removal: invalid response');
  }
}

// Apply confirmed receipts before the independent refresh, which can itself fail.
function _applyMemoryReceipt(memory, removedId = null) {
  ++_loadGeneration;
  ++_searchGeneration;
  const update = memories => removedId
    ? memories.filter(item => item.id !== removedId)
    : memories.map(item => item.id === memory.id ? memory : item);
  _memories = update(_memories);
  if (memory && !_memories.some(item => item.id === memory.id)) _memories.unshift(memory);
  if (_searchResults) _searchResults = update(_searchResults);
  _renderCurrentMemories();
}

async function _withPending(key, action) {
  if (_pendingActions.has(key)) return;
  _pendingActions.add(key);
  _renderPending();
  try { await action(); }
  catch (error) { toast(error.message || 'memory request failed', 'error'); }
  finally { _pendingActions.delete(key); _renderPending(); }
}

function _renderPending() {
  document.getElementById('memory-list')?.querySelectorAll('.act-btn').forEach(btn => {
    btn.disabled = _pendingActions.has(`memory:${btn.dataset.id}`);
    btn.setAttribute('aria-busy', String(btn.disabled));
  });
  const add = document.getElementById('mem-add-btn');
  if (add) {
    add.disabled = _memoryPolicy === 'off' || _pendingActions.has('add');
    add.setAttribute('aria-disabled', String(add.disabled));
    add.setAttribute('aria-busy', String(_pendingActions.has('add')));
  }
  const settingPending = _pendingActions.has('settings');
  document.querySelectorAll('[data-memory-policy]').forEach(btn => { btn.disabled = settingPending; });
  for (const [id, pending, unavailable] of [
    ['mem-pause-btn', settingPending, false],
    ['s-memory-inject-toggle', settingPending, _memoryPolicy === 'off'],
    ['mem-extract-btn', _pendingActions.has('extract'), _memoryPolicy === 'off'],
    ['mem-clear-btn', _pendingActions.has('clear'), false],
  ]) {
    const control = document.getElementById(id);
    if (!control) continue;
    control.disabled = pending || unavailable;
    control.setAttribute('aria-disabled', String(control.disabled));
    control.setAttribute('aria-busy', String(pending));
  }
}

function _renderCategoryFilter() {
  const el = document.getElementById('mem-category-filter');
  if (!el) return;
  el.innerHTML = CATEGORIES.map(c =>
    `<button type="button" class="mem-cat-btn${c === _activeCategory ? ' active' : ''}" data-cat="${c}" aria-pressed="${c === _activeCategory}">${c}</button>`
  ).join('');
  el.querySelectorAll('.mem-cat-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _activeCategory = btn.dataset.cat;
      _renderCategoryFilter();
      _renderCurrentMemories();
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
    btn.addEventListener('click', () => _withPending(`memory:${btn.dataset.id}`, async () => {
      const receipt = await _requestJson(`/api/memories/${btn.dataset.id}`, { method: 'DELETE' });
      _requireRemovalReceipt(receipt);
      _applyMemoryReceipt(null, btn.dataset.id);
      toast('memory removed', 'success');
      await loadMemories();
    }));
  });

  list.querySelectorAll('.mem-pin-btn').forEach(btn => {
    btn.addEventListener('click', () => _withPending(`memory:${btn.dataset.id}`, async () => {
      const pinned = btn.dataset.pinned === 'true';
      const memory = await _requestJson(`/api/memories/${btn.dataset.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pinned: !pinned }),
      });
      _requireMemoryReceipt(memory, { id: btn.dataset.id, pinned: !pinned });
      _applyMemoryReceipt(memory);
      await loadMemories();
    }));
  });
  list.querySelectorAll('.mem-edit-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const ownedFocus = document.activeElement === btn;
      await _withPending(`memory:${btn.dataset.id}`, async () => {
        const memory = (_searchResults ?? _memories).find(item => item.id === btn.dataset.id);
        if (!memory) return;
        let saved = false;
        const result = await fieldsDialog('edit memory', [{ id: 'text', label: 'memory', value: memory.text }], {
          submit: async ({ text }) => {
            if (!text.trim()) throw new Error('enter memory text before saving');
            if (text.trim() === memory.text) return;
            const updated = await _requestJson(`/api/memories/${memory.id}`, {
              method: 'PATCH', headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ text: text.trim() }),
            });
            _requireMemoryReceipt(updated, { id: memory.id, text: text.trim() });
            _applyMemoryReceipt(updated);
            saved = true;
          },
        });
        if (result && saved) {
          toast('memory updated', 'success');
          await loadMemories();
        }
      });
      if (ownedFocus && (document.activeElement === btn || document.activeElement === document.body)) {
        [...list.querySelectorAll('.mem-edit-btn')].find(control => control.dataset.id === btn.dataset.id)?.focus();
      }
    });
  });
  list.querySelectorAll('.mem-scope-btn').forEach(btn => {
    btn.addEventListener('click', () => _withPending(`memory:${btn.dataset.id}`, async () => {
      const useProject = btn.dataset.scope !== 'project';
      const projectId = window._currentSession?.project_id || '';
      if (useProject && !projectId) { toast('open a project chat first', 'error'); return; }
      const change = { scope: useProject ? 'project' : 'global', project_id: useProject ? projectId : null };
      const memory = await _requestJson(`/api/memories/${btn.dataset.id}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(change),
      });
      _requireMemoryReceipt(memory, { id: btn.dataset.id, ...change });
      _applyMemoryReceipt(memory);
      await loadMemories();
    }));
  });
  list.querySelectorAll('.mem-accept-btn').forEach(btn => {
    btn.addEventListener('click', () => _withPending(`memory:${btn.dataset.id}`, async () => {
      const memory = await _requestJson(`/api/memories/${btn.dataset.id}/accept`, { method: 'POST' });
      _requireMemoryReceipt(memory, { id: btn.dataset.id, status: 'active' });
      _applyMemoryReceipt(memory);
      toast('memory accepted', 'success');
      await loadMemories();
    }));
  });
  _renderPending();
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
  _renderPending();
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
    btn.addEventListener('click', () => _withPending('settings', async () => {
      try {
        await _requestJson('/api/settings', {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ memory_policy: btn.dataset.memoryPolicy }),
        });
        ++_loadGeneration;
        _memoryPolicy = btn.dataset.memoryPolicy;
        _renderPolicy();
        await loadMemories();
      } catch (error) { toast(error.message, 'error'); }
    }));
  });

  document.getElementById('s-memory-inject-toggle')?.addEventListener('click', event => _withPending('settings', async () => {
    if (_memoryPolicy === 'off') return;
    const next = !event.currentTarget.classList.contains('on');
    try {
      await _requestJson('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ memory_auto_inject: next }),
      });
      ++_loadGeneration;
      _memoryAutoInject = next;
      _renderPolicy();
    } catch (error) { toast(error.message, 'error'); }
  }));

  document.getElementById('mem-pause-btn')?.addEventListener('click', () => _withPending('settings', async () => {
    const next = _memoryPolicy === 'off' ? _memoryLastActivePolicy : 'off';
    try {
      await _requestJson('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ memory_policy: next }),
      });
      ++_loadGeneration;
      if (_memoryPolicy !== 'off') _memoryLastActivePolicy = _memoryPolicy;
      _memoryPolicy = next;
      _renderPolicy();
      await loadMemories();
    } catch (error) { toast(error.message, 'error'); }
  }));

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

  document.getElementById('mem-add-input')?.addEventListener('input', () => { ++_addRevision; });
  document.getElementById('mem-add-btn')?.addEventListener('click', () => _withPending('add', async () => {
    if (_memoryPolicy === 'off') return;
    const inp = document.getElementById('mem-add-input');
    const cat = document.getElementById('mem-cat-cycle-btn')?.dataset.val || 'general';
    const draft = inp?.value;
    const revision = _addRevision;
    const text = draft?.trim();
    if (!text) return;
    const change = {
      text,
      category: cat,
      scope: window._currentSession?.project_id ? 'project' : 'global',
      project_id: window._currentSession?.project_id || '',
    };
    try {
      const memory = await _requestJson('/api/memories', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(change),
      });
      _requireMemoryReceipt(memory, { ...change, project_id: change.project_id || null });
      if (revision === _addRevision && inp.value === draft) inp.value = '';
      _applyMemoryReceipt(memory);
      _showUndo(memory.id);
      toast('remembered', 'success');
      await loadMemories();
    } catch (error) { toast(error.message, 'error'); }
  }));

  document.getElementById('mem-add-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('mem-add-btn')?.click();
  });

  // search
  document.getElementById('mem-search')?.addEventListener('input', e => {
    clearTimeout(_searchTimeout);
    const generation = ++_searchGeneration;
    const q = e.target.value.trim();
    _clearReadError('search');
    if (!q) _searchResults = null;
    if (!q) { renderMemories(filterMemoriesByCategory(_memories)); return; }
    _searchTimeout = setTimeout(() => _searchMemories(q, generation), 300);
  });

  // extract from current session
  document.getElementById('mem-extract-btn')?.addEventListener('click', () => _withPending('extract', async () => {
    if (_memoryPolicy === 'off') return;
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
  }));

  document.getElementById('mem-clear-btn')?.addEventListener('click', () => _withPending('clear', async () => {
    if (!await confirmDialog('forget every saved and suggested memory?')) return;
    try {
      const result = await _requestJson('/api/memories', { method: 'DELETE' });
      _requireRemovalReceipt(result, true);
      ++_loadGeneration;
      ++_searchGeneration;
      _memories = [];
      if (_searchResults) _searchResults = [];
      _renderCurrentMemories();
      const undo = document.getElementById('mem-undo');
      if (undo) { undo.hidden = true; undo.dataset.memoryId = ''; }
      clearTimeout(_showUndo.timer);
      toast(`${result.deleted || 0} memories cleared`, 'success');
      await loadMemories();
    } catch (error) { toast(error.message, 'error'); }
  }));

  loadMemories();
}

function _showUndo(memoryId) {
  const el = document.getElementById('mem-undo');
  if (!el) return;
  el.hidden = false;
  el.dataset.memoryId = memoryId;
  const button = el.querySelector('button');
  button.disabled = false;
  button.onclick = () => _withPending(`memory:${memoryId}`, async () => {
    clearTimeout(_showUndo.timer);
    button.disabled = true;
    try {
      const receipt = await _requestJson(`/api/memories/${memoryId}`, { method: 'DELETE' });
      _requireRemovalReceipt(receipt);
      _applyMemoryReceipt(null, memoryId);
      if (el.dataset.memoryId === memoryId) el.hidden = true;
      toast('memory removed', 'success');
      await loadMemories();
    } finally {
      if (el.dataset.memoryId === memoryId) button.disabled = false;
    }
  });
  clearTimeout(_showUndo.timer);
  _showUndo.timer = setTimeout(() => {
    if (el.dataset.memoryId === memoryId) el.hidden = true;
  }, 10000);
}
