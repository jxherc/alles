import { mdToHtml, toast } from './util.js';

let _compareId = null;
let _models = [];   // model list for the active comparison, for vote recording

export async function runCompare(message, modelList) {
  if (!message.trim() || !modelList.length) return;
  _models = modelList;

  const r = await fetch('/api/compare', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message, models: modelList }),
  });
  if (!r.ok) { toast('compare failed', 'error'); return; }
  const { compare_id, count } = await r.json();
  _compareId = compare_id;

  _renderGrid(modelList);

  for (let i = 0; i < count; i++) {
    _streamColumn(compare_id, i, modelList[i]);
  }
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
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

export function initCompareView() {
  const btn = document.getElementById('compare-send-btn');
  const inp = document.getElementById('compare-input');
  if (!btn || !inp) return;

  btn.addEventListener('click', async () => {
    const msg = inp.value.trim();
    if (!msg) return;
    inp.value = '';

    // collect selected models from checkboxes
    const checks = document.querySelectorAll('.compare-model-check[aria-checked="true"]');
    const modelList = [...checks].map(c => ({
      endpoint_id: c.dataset.ep,
      model: c.dataset.model,
    }));
    if (!modelList.length) { toast('select at least one model', 'error'); return; }
    await runCompare(msg, modelList);
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
  const eps = window._endpoints || [];
  if (!eps.length) {
    container.innerHTML = '<div style="font-size:0.72rem;color:var(--muted)">no endpoints — add one via the model picker</div>';
    return;
  }
  let html = '';
  for (const ep of eps) {
    if (!ep.models.length) continue;
    html += `<div style="font-size:0.68rem;color:var(--muted);margin:0.5rem 0 0.2rem;text-transform:lowercase">${_esc(ep.name)}</div>`;
    for (const m of ep.models) {
      html += `<div class="compare-model-row">
        <span class="chk compare-model-check" data-ep="${ep.id}" data-model="${_esc(m)}" aria-checked="false"></span>
        <span title="${_esc(m)}">${_esc(m.split('/').pop())}</span>
      </div>`;
    }
  }
  container.innerHTML = html || '<div style="font-size:0.72rem;color:var(--muted)">no models</div>';
  container.querySelectorAll('.compare-model-row').forEach(row => row.addEventListener('click', () => {
    const c = row.querySelector('.chk');
    c.setAttribute('aria-checked', c.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
  }));
}
