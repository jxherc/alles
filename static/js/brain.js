export async function loadBrainPanel() {
  const statsEl = document.getElementById('brain-stats');
  const contextEl = document.getElementById('brain-context');
  const memoriesEl = document.getElementById('brain-memories');
  if (!statsEl || !contextEl || !memoriesEl) return;

  const [memories, history] = await Promise.all([
    fetch('/api/memories').then(r => r.json()).catch(() => []),
    _loadCurrentHistory(),
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
    _stat('tokens', approxTokens.toLocaleString()),
  ].join('');

  contextEl.innerHTML = `
    <div><span>session</span><strong>${_esc(session?.name || 'none')}</strong></div>
    <div><span>model</span><strong>${_esc(session?.model || document.getElementById('model-label')?.textContent || 'no model')}</strong></div>
    <div><span>turns</span><strong>${userCount} user / ${aiCount} ai</strong></div>
    <div><span>context estimate</span><strong>${approxTokens.toLocaleString()} tokens</strong></div>
  `;

  const recent = memories.slice(0, 6);
  memoriesEl.innerHTML = recent.length
    ? recent.map(m => `<div class="brain-memory">
        <span>${_esc(m.category || 'memory')}</span>
        <div>${_esc(m.text || '')}</div>
      </div>`).join('')
    : '<div class="sidebar-model-empty">no memories yet</div>';
}

async function _loadCurrentHistory() {
  const sid = window._currentSession?.id;
  if (!sid) return null;
  const r = await fetch(`/api/sessions/${sid}/history`);
  if (!r.ok) return null;
  return r.json();
}

function _stat(label, value) {
  return `<div class="brain-stat"><span>${label}</span><strong>${value}</strong></div>`;
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
