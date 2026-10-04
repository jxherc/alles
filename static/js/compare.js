import { mdToHtml, toast } from './util.js';

let _compareId = null;
let _models = [];   // model list for the active comparison, for vote recording
let _catalogRead = 0;

export async function runCompare(message, modelList) {
  if (!message.trim() || !modelList.length) return false;
  let compare_id, count;
  try {
    const r = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message, models: modelList }),
    });
    if (!r.ok) throw new Error('comparison was not accepted');
    ({ compare_id, count } = await r.json());
    if (typeof compare_id !== 'string' || !compare_id || count !== modelList.length) {
      throw new Error('comparison models were not accepted');
    }
  } catch {
    toast('could not start comparison — check the selected models and try again', 'error');
    return false;
  }

  _compareId = compare_id;
  _models = modelList;
  _renderGrid(modelList);

  for (let i = 0; i < count; i++) {
    _streamColumn(compare_id, i, modelList[i]);
  }
  return true;
}

function _renderGrid(modelList) {
  const grid = document.getElementById('compare-grid');
  if (!grid) return;
  grid.style.gridTemplateColumns = `repeat(${modelList.length}, minmax(280px, 1fr))`;
  grid.innerHTML = modelList.map((m, i) => `
    <div class="compare-col" id="compare-col-${i}">
      <div class="compare-col-head">
        <span class="compare-model-label">${_esc(m.model)}</span>
      </div>
      <div class="compare-body" id="compare-body-${i}"></div>
      <div class="compare-col-foot">
        <button class="btn" onclick="window._pickWinner(${i})">pick winner</button>
      </div>
    </div>`).join('');
}

async function _streamColumn(compareId, idx, modelInfo) {
  const body = document.getElementById(`compare-body-${idx}`);
  if (!body) return;

  const r = await fetch(`/api/compare/${compareId}/stream/${idx}`);
  if (!r.ok) { body.textContent = 'error'; return; }

  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '', acc = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      if (raw === '[DONE]') return;
      try {
        const chunk = JSON.parse(raw);
        if (chunk.delta) {
          acc += chunk.delta;
          body.innerHTML = mdToHtml(acc);
          body.scrollTop = body.scrollHeight;
        }
      } catch {}
    }
  }
}

window._pickWinner = async (idx) => {
  document.querySelectorAll('.compare-col').forEach((col, i) => {
    col.classList.toggle('compare-winner', i === idx);
    col.classList.toggle('compare-loser', i !== idx);
  });
  toast('winner picked', 'success');
  // record the win against each other model so the leaderboard builds up over time
  const winner = _models[idx]?.model;
  if (winner) {
    for (let i = 0; i < _models.length; i++) {
      if (i === idx) continue;
      fetch('/api/compare/vote', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ winner, loser: _models[i]?.model || '' }),
      }).catch(() => {});
    }
  }
  if (_compareId) {
    await fetch(`/api/compare/${_compareId}`, { method: 'DELETE' }).catch(() => {});
    _compareId = null;
  }
  loadCompareLeaderboard();   // reflect the vote just cast
};

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function initCompareView() {
  const btn = document.getElementById('compare-send-btn');
  const inp = document.getElementById('compare-input');
  if (!btn || !inp || btn.dataset.compareBound) return;
  btn.dataset.compareBound = 'true';
  let draftRevision = 0;
  inp.addEventListener('input', () => { draftRevision++; });
  document.getElementById('compare-model-setup')?.addEventListener('click', () => window._openSettings?.('models'));
  document.getElementById('compare-model-refresh')?.addEventListener('click', loadCompareModels);

  btn.addEventListener('click', async () => {
    const draft = inp.value;
    const msg = draft.trim();
    if (!msg || btn.disabled) return;

    // collect selected models from checkboxes
    const checks = document.querySelectorAll('.compare-model-check[aria-checked="true"]');
    const modelList = [...checks].map(c => ({
      endpoint_id: c.dataset.ep,
      model: c.dataset.model,
    }));
    if (!modelList.length) {
      toast('select a model first, or choose “set up models”', 'error');
      inp.focus();
      return;
    }
    const revision = draftRevision;
    let ownsFocus = document.activeElement === btn || document.activeElement === inp;
    const trackFocus = event => {
      if (event.target !== btn && event.target !== inp) ownsFocus = false;
    };
    document.addEventListener('focusin', trackFocus);
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    btn.textContent = 'starting…';
    try {
      const accepted = await runCompare(msg, modelList);
      if (accepted && draftRevision === revision && inp.value === draft) inp.value = '';
      if (!accepted && ownsFocus && draftRevision === revision && inp.getClientRects().length) inp.focus();
    } finally {
      document.removeEventListener('focusin', trackFocus);
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.textContent = 'compare';
    }
  });
}

// blind-vote win rates — so the votes you cast on "pick winner" actually show up
export async function loadCompareLeaderboard() {
  const el = document.getElementById('compare-leaderboard');
  if (!el) return;
  let stats;
  try { stats = await (await fetch('/api/compare/stats')).json(); }
  catch { el.innerHTML = ''; return; }
  if (!stats.models?.length) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="compare-lb-head">leaderboard · ${stats.votes} votes</div>
    ${stats.models.map(m => `
      <div class="compare-lb-row">
        <span class="compare-lb-name">${_esc(m.model)}</span>
        <span class="compare-lb-rate">${Math.round(m.win_rate * 100)}%</span>
        <span class="compare-lb-wl">${m.wins}–${m.losses}</span>
      </div>`).join('')}`;
}

export async function loadCompareModels() {
  const container = document.getElementById('compare-model-picker');
  if (!container) return;
  const read = ++_catalogRead;
  const refresh = document.getElementById('compare-model-refresh');
  const status = document.getElementById('compare-model-status');
  if (refresh) refresh.disabled = true;
  if (status) status.textContent = 'loading models…';
  let eps;
  try {
    const response = await fetch('/api/models');
    if (!response.ok) throw new Error('models unavailable');
    eps = await response.json();
    if (!Array.isArray(eps) || eps.some(ep => !ep || !Array.isArray(ep.models))) throw new Error('invalid model list');
  } catch {
    if (read === _catalogRead && status) status.textContent = 'could not load models — refresh to try again';
    return;
  } finally {
    if (read === _catalogRead && refresh) refresh.disabled = false;
  }
  if (read !== _catalogRead) return;
  const selected = new Set([...container.querySelectorAll('.compare-model-check[aria-checked="true"]')]
    .map(c => JSON.stringify([c.dataset.ep, c.dataset.model])));
  let html = '';
  for (const ep of eps) {
    if (ep.enabled === false || !ep.models.length) continue;
    html += `<div style="font-size:0.75rem;color:var(--muted);margin:0.5rem 0 0.2rem;text-transform:lowercase">${_esc(ep.name)}</div>`;
    for (const m of ep.models) {
      if (ep.unavailable_models?.includes(m)) continue;
      const checked = selected.has(JSON.stringify([ep.id, m]));
      html += `<button type="button" class="compare-model-row compare-model-check" role="checkbox" data-ep="${_esc(ep.id)}" data-model="${_esc(m)}" aria-checked="${checked}" aria-label="${_esc(m)}">
        <span class="chk" aria-hidden="true" aria-checked="${checked}"></span>
        <span title="${_esc(m)}">${_esc(m.split('/').pop())}</span>
      </button>`;
    }
  }
  const focused = container.contains(document.activeElement) && document.activeElement.matches('.compare-model-check')
    ? JSON.stringify([document.activeElement.dataset.ep, document.activeElement.dataset.model]) : null;
  container.innerHTML = html;
  if (status) status.textContent = container.querySelector('.compare-model-row')
    ? 'select models to answer the same prompt'
    : 'no models available — set up a connection, then refresh this list';
  container.querySelectorAll('.compare-model-row').forEach(row => row.addEventListener('click', () => {
    const checked = row.getAttribute('aria-checked') === 'true' ? 'false' : 'true';
    row.setAttribute('aria-checked', checked);
    row.querySelector('.chk').setAttribute('aria-checked', checked);
  }));
  if (focused) {
    const replacement = [...container.querySelectorAll('.compare-model-check')]
      .find(row => JSON.stringify([row.dataset.ep, row.dataset.model]) === focused);
    const target = replacement || refresh;
    if (target?.getClientRects().length) target.focus();
  }
}
