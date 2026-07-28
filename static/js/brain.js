import { formatNumber } from './i18n.js';

export async function loadBrainPanel(fetcher = fetch) {
  const statsEl = document.getElementById('brain-stats');
  const contextEl = document.getElementById('brain-context');
  const memoriesEl = document.getElementById('brain-memories');
  if (!statsEl || !contextEl || !memoriesEl) return;

  const [memories, history, insights, distilled, settings] = await Promise.all([
    fetcher('/api/memories').then(r => r.ok ? r.json() : Promise.reject(new Error('memories unavailable'))).catch(() => []),
    _loadCurrentHistory(fetcher),
    fetcher('/api/insights').then(r => r.ok ? r.json() : Promise.reject(new Error('insights unavailable'))).catch(() => []),
    fetcher('/api/memory/distilled').then(r => r.ok ? r.json() : Promise.reject(new Error('memory model unavailable'))).catch(() => []),
    fetcher('/api/settings').then(r => r.ok ? r.json() : Promise.reject(new Error('settings unavailable'))).catch(() => ({})),
  ]);

  const messages = history?.messages || [];
  const session = history?.session || window._currentSession || null;
  const userCount = messages.filter(m => m.role === 'user').length;
  const aiCount = messages.filter(m => m.role === 'assistant').length;
  const chars = messages.reduce((sum, m) => sum + String(m.content || '').length, 0);
  const approxTokens = Math.ceil(chars / 4);
  const pinned = memories.filter(m => m.pinned).length;

  statsEl.innerHTML = [
    _stat('memories', memories.length),
    _stat('pinned', pinned),
    _stat('messages', messages.length),
    _stat('tokens', formatNumber(approxTokens)),
  ].join('');

  contextEl.innerHTML = `
    <div><span>session</span><strong>${_esc(session?.name || 'none')}</strong></div>
    <div><span>model</span><strong>${_esc(session?.model || document.getElementById('model-label')?.textContent || 'no model')}</strong></div>
    <div><span>turns</span><strong>${userCount} user / ${aiCount} ai</strong></div>
    <div><span>context estimate</span><strong>${formatNumber(approxTokens)} tokens</strong></div>
  `;

  const recent = memories.slice(0, 6);
  memoriesEl.innerHTML = recent.length
    ? recent.map(m => `<div class="brain-memory">
        <span>${_esc(m.category || 'memory')}</span>
        <div>${_esc(m.text || '')}</div>
      </div>`).join('')
    : '<div class="sidebar-model-empty">no memories yet</div>';

  _renderInsights(insights, settings);
  _renderUserModel(distilled, settings);
  _bindButtons();
}

function _renderInsights(items, settings) {
  const el = document.getElementById('brain-insights');
  if (!el) return;
  if (!items.length) {
    el.innerHTML = settings.insights_enabled
      ? '<div class="brain-empty">nothing yet - hit generate to look for cross-domain patterns.</div>'
      : _disabledHint('insights are off', 'intelligence');
    return;
  }
  el.innerHTML = items.map(i => {
    const ev = (i.evidence || []).map(e => `<span class="ev-tag">${_esc(String(e))}</span>`).join('');
    return `<div class="brain-insight${i.pinned ? ' pinned' : ''}">
      <div class="brain-insight-main">
        <div class="brain-insight-title">${_esc(i.title || '')}</div>
        ${i.body ? `<div class="brain-insight-body">${_esc(i.body)}</div>` : ''}
        ${ev ? `<div class="brain-insight-ev">${ev}</div>` : ''}
      </div>
      <div class="brain-insight-acts">
        <button class="act-btn" data-ins-pin="${i.id}">${i.pinned ? 'unpin' : 'pin'}</button>
        <button class="act-btn" data-ins-dismiss="${i.id}">dismiss</button>
      </div>
    </div>`;
  }).join('');
  el.querySelectorAll('[data-ins-pin]').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/insights/${b.dataset.insPin}/pin`, { method: 'POST' }).catch(() => {});
    loadBrainPanel();
  }));
  el.querySelectorAll('[data-ins-dismiss]').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/insights/${b.dataset.insDismiss}/dismiss`, { method: 'POST' }).catch(() => {});
    loadBrainPanel();
  }));
}

function _renderUserModel(facts, settings) {
  const el = document.getElementById('brain-usermodel');
  if (!el) return;
  const live = (facts || []).filter(f => !f.vetoed);
  if (!live.length) {
    el.innerHTML = settings.user_model_distill
      ? '<div class="brain-empty">nothing distilled yet - hit refresh once you have some chat history.</div>'
      : _disabledHint('learning about you is off', 'intelligence');
    return;
  }
  el.innerHTML = live.map(f => {
    const pct = Math.max(0, Math.min(100, Math.round((Number(f.confidence) || 0) * 100)));
    return `<div class="um-fact${f.pinned ? ' pinned' : ''}">
      <div class="um-fact-main">
        <div class="um-fact-text">${_esc(f.text || '')}</div>
        <div class="um-fact-meta">
          <span class="um-conf"><i style="width:${pct}%"></i></span>
          <span>${pct}%${f.provenance ? ' - ' + _esc(f.provenance) : ''}</span>
        </div>
      </div>
      <div class="um-fact-acts">
        <button class="act-btn" data-um-pin="${f.id}">${f.pinned ? 'unpin' : 'pin'}</button>
        <button class="act-btn" data-um-veto="${f.id}">veto</button>
      </div>
    </div>`;
  }).join('');
  el.querySelectorAll('[data-um-pin]').forEach(b => b.addEventListener('click', async () => {
    const fact = live.find(f => f.id === b.dataset.umPin);
    await fetch(`/api/memories/${b.dataset.umPin}`, {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pinned: !(fact && fact.pinned) }),
    }).catch(() => {});
    loadBrainPanel();
  }));
  el.querySelectorAll('[data-um-veto]').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/memory/${b.dataset.umVeto}/veto`, { method: 'POST' }).catch(() => {});
    loadBrainPanel();
  }));
}

function _disabledHint(label, pane) {
  return `<div class="brain-empty">${_esc(label)}.
    <button class="act-btn brain-enable" data-open-pane="${pane}">turn it on</button></div>`;
}

let _bound = false;
function _bindButtons() {
  // delegate the "turn it on" links (they get re-rendered, so guard each)
  document.querySelectorAll('#brain-view [data-open-pane]').forEach(b => {
    if (b.dataset.bound) return;
    b.dataset.bound = '1';
    b.addEventListener('click', () => window._openSettings?.(b.dataset.openPane));
  });
  if (_bound) return;
  _bound = true;
  const gen = document.getElementById('brain-insights-run');
  if (gen) gen.addEventListener('click', async () => {
    gen.disabled = true; gen.textContent = 'thinking...';
    try { await fetch('/api/insights/run', { method: 'POST' }); } catch {}
    gen.disabled = false; gen.textContent = 'generate';
    loadBrainPanel();
  });
  const ref = document.getElementById('brain-usermodel-run');
  if (ref) ref.addEventListener('click', async () => {
    ref.disabled = true; ref.textContent = 'thinking...';
    try { await fetch('/api/memory/distill/run', { method: 'POST' }); } catch {}
    ref.disabled = false; ref.textContent = 'refresh';
    loadBrainPanel();
  });
}

async function _loadCurrentHistory(fetcher = fetch) {
  const sid = window._currentSession?.id;
  if (!sid) return null;
  const r = await fetcher(`/api/sessions/${sid}/history`);
  if (!r.ok) return null;
  return r.json();
}

function _stat(label, value) {
  return `<div class="brain-stat"><span>${label}</span><strong>${value}</strong></div>`;
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
