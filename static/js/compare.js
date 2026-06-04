import { mdToHtml, toast } from './util.js';
import { getSelected, getCurrentEndpoint } from './models.js';

let _compareId = null;

export async function runCompare(message, modelList) {
  if (!message.trim() || !modelList.length) return;

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
  if (_compareId) {
    await fetch(`/api/compare/${_compareId}`, { method: 'DELETE' }).catch(() => {});
    _compareId = null;
  }
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
    const checks = document.querySelectorAll('.compare-model-check:checked');
    const modelList = [...checks].map(c => ({
      endpoint_id: c.dataset.ep,
      model: c.dataset.model,
    }));
    if (!modelList.length) { toast('select at least one model', 'error'); return; }
    await runCompare(msg, modelList);
  });
}

export async function loadCompareModels() {
  const container = document.getElementById('compare-model-picker');
  if (!container) return;
  try {
    const r = await fetch('/v1/models');
    const { data } = await r.json();
    container.innerHTML = data.map(m => {
      const [ep, model] = m.id.split('/', 2);
      const epRow = window._allEndpoints?.find(e => e.name === ep);
      return `<label class="compare-model-row">
        <input type="checkbox" class="compare-model-check"
          data-ep="${epRow?.id || ''}" data-model="${_esc(model)}">
        <span>${_esc(m.id)}</span>
      </label>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div class="page-empty">no models</div>';
  }
}
