import { mdToHtml, toast } from './util.js';
import { requestId } from './request_id.js';

let _comparison = null;
let _startRead = 0;
let _catalogRead = 0;

function discardRequest(id) {
  if (id) void fetch(`/api/compare/${encodeURIComponent(id)}`, { method: 'DELETE' }).catch(() => {});
}

function disposeComparison(comparison) {
  if (!comparison) return;
  for (const column of comparison.columns) {
    const controller = column.controller;
    column.controller = null;
    controller?.abort();
  }
  for (const id of comparison.ids) discardRequest(id);
}

async function startRequest(message, models, signal) {
  const response = await fetch('/api/compare', {
    method: 'POST', headers: { 'content-type': 'application/json' }, signal,
    body: JSON.stringify({ message, models }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: comparison was not accepted`);
  const result = await response.json();
  if (typeof result.compare_id !== 'string' || !result.compare_id || result.count !== models.length) {
    if (typeof result.compare_id === 'string') discardRequest(result.compare_id);
    throw new Error('comparison models were not accepted');
  }
  return result.compare_id;
}

export async function runCompare(message, modelList) {
  if (!message.trim() || !modelList.length) return false;
  const read = ++_startRead;
  const models = modelList.map(model => ({ ...model }));
  let id;
  try {
    id = await startRequest(message, models);
  } catch {
    if (read === _startRead) toast('could not start comparison — check the selected models and try again', 'error');
    return false;
  }
  if (read !== _startRead) { discardRequest(id); return false; }
  disposeComparison(_comparison);
  const comparison = {
    prompt: message, ids: new Set([id]), vote: null,
    columns: models.map((model, index) => ({ model, index, id, streamIndex: index,
      state: 'streaming', text: '', detail: '', message: 'waiting for response…', controller: null, nodes: null })),
  };
  _comparison = comparison;
  renderComparison(comparison);
  for (const column of comparison.columns) void streamColumn(comparison, column);
  return true;
}

function renderComparison(comparison) {
  const grid = document.getElementById('compare-grid');
  if (!grid) return;
  const results = document.getElementById('compare-results');
  if (results) results.hidden = false;
  const prompt = document.getElementById('compare-submitted-prompt');
  if (prompt) prompt.textContent = comparison.prompt;
  grid.style.gridTemplateColumns = `repeat(${comparison.columns.length}, minmax(280px, 1fr))`;
  grid.innerHTML = comparison.columns.map(column => `
    <section class="compare-col" id="compare-col-${column.index}" aria-label="${_esc(column.model.model)} response">
      <div class="compare-col-head"><span class="compare-model-label">${_esc(column.model.model)}</span></div>
      <div class="compare-body" id="compare-body-${column.index}" tabindex="0" aria-label="${_esc(column.model.model)} answer"></div>
      <div class="compare-col-foot">
        <p class="compare-column-status" role="status" tabindex="-1"></p>
        <details class="compare-error-detail" hidden><summary>error details</summary><pre></pre></details>
        <div class="compare-response-actions">
          <button type="button" class="btn" data-compare-stop>stop response</button>
          <button type="button" class="btn" data-compare-retry hidden>retry</button>
          <button type="button" class="btn" data-compare-settings hidden>model settings</button>
          <button type="button" class="btn" data-compare-winner disabled>pick winner</button>
        </div>
      </div>
    </section>`).join('');
  for (const column of comparison.columns) {
    const root = document.getElementById(`compare-col-${column.index}`);
    column.nodes = {
      root, body: root.querySelector('.compare-body'), status: root.querySelector('.compare-column-status'),
      detail: root.querySelector('.compare-error-detail'), stop: root.querySelector('[data-compare-stop]'),
      retry: root.querySelector('[data-compare-retry]'), settings: root.querySelector('[data-compare-settings]'),
      winner: root.querySelector('[data-compare-winner]'),
    };
    column.nodes.stop.addEventListener('click', () => {
      if (_comparison !== comparison || column.state !== 'streaming') return;
      const controller = column.controller;
      column.controller = null;
      column.state = 'stopped';
      column.message = 'stopped. retry this model when you are ready.';
      controller?.abort();
      updateComparison(comparison);
    });
    column.nodes.retry.addEventListener('click', () => {
      if (_comparison === comparison && ['error', 'stopped'].includes(column.state) && !comparison.vote) {
        void streamColumn(comparison, column, true);
      }
    });
    column.nodes.settings.addEventListener('click', () => window._openSettings?.('models'));
    column.nodes.winner.addEventListener('click', () => void pickWinner(comparison, column.index));
  }
  updateComparison(comparison);
}

function updateComparison(comparison) {
  if (_comparison !== comparison) return;
  const ready = comparison.columns.filter(column => column.state === 'complete').length;
  const running = comparison.columns.some(column => column.state === 'streaming');
  const vote = comparison.vote;
  const status = document.getElementById('compare-results-status');
  if (status) status.textContent = vote?.saved ? 'winner saved to the leaderboard.'
    : vote?.pending ? 'saving your vote…'
    : vote ? 'your vote may be partly saved. retry the same vote to confirm it without counting it twice.'
    : comparison.columns.length < 2 ? 'select at least two models and compare again to choose a winner.'
    : running ? `${ready} of ${comparison.columns.length} responses ready. wait or stop unfinished responses before choosing a winner.`
    : ready < 2 ? `${ready} of ${comparison.columns.length} responses ready. finish at least two responses to choose a winner.`
    : `${ready} responses ready. choose the answer you prefer.`;
  for (const column of comparison.columns) {
    const n = column.nodes;
    if (!n) continue;
    const focused = document.activeElement;
    n.status.textContent = column.message;
    n.body.setAttribute('aria-busy', String(column.state === 'streaming'));
    n.root.dataset.state = column.state;
    n.stop.hidden = column.state !== 'streaming';
    n.retry.hidden = !['error', 'stopped'].includes(column.state) && !column.retrying;
    n.retry.textContent = column.retrying && column.state === 'streaming' ? 'retrying…' : 'retry';
    n.retry.setAttribute('aria-disabled', String(column.state === 'streaming' || Boolean(vote)));
    n.settings.hidden = column.state !== 'error';
    n.detail.hidden = !column.detail;
    n.detail.querySelector('pre').textContent = column.detail;
    n.winner.disabled = column.state !== 'complete' || ready < 2 || running
      || Boolean(vote?.pending || vote?.saved || (vote && vote.index !== column.index));
    n.winner.textContent = vote?.index === column.index ? (vote.saved ? 'winner saved' : vote.pending ? 'saving…' : 'retry vote') : 'pick winner';
    n.root.classList.toggle('compare-winner', Boolean(vote?.saved && vote.index === column.index));
    n.root.classList.toggle('compare-loser', Boolean(vote?.saved && vote.index !== column.index && column.state === 'complete'));
    if ([n.stop, n.retry, n.settings, n.winner].includes(focused) && (focused.hidden || focused.disabled)) {
      const target = [n.retry, n.winner, n.settings].find(el => !el.hidden && !el.disabled && el.getAttribute('aria-disabled') !== 'true');
      (target || n.status).focus();
    }
  }
}

function failureMessage(detail, status) {
  if (globalThis.navigator?.onLine === false) return 'you are offline. reconnect, then retry this model.';
  const code = status || Number(String(detail).match(/HTTP\s+(\d{3})/i)?.[1]);
  if ([401, 403].includes(code)) return 'this model did not authorize the request. check its credentials in model settings, then retry.';
  if (code === 429) return 'this model is busy or has reached its limit. wait a moment, then retry.';
  if (code === 404) return 'this response is unavailable. retry with the saved prompt, or check the connection in model settings.';
  if (code >= 500) return 'this model is temporarily unavailable. retry it, or check its connection in model settings.';
  return 'this model could not finish its response. retry it, or check its connection in model settings.';
}

async function streamColumn(comparison, column, retry = false) {
  if (!column.nodes || _comparison !== comparison) return;
  const controller = new AbortController();
  column.controller = controller;
  const owns = () => _comparison === comparison && column.controller === controller;
  column.state = 'streaming'; column.detail = ''; column.retrying = retry;
  column.message = retry ? (column.text ? 'retrying… previous partial answer remains until this model responds.' : 'retrying this model…') : 'waiting for response…';
  updateComparison(comparison);
  let reader, acc = '', terminal = false;
  try {
    if (retry) {
      const id = await startRequest(comparison.prompt, [column.model], controller.signal);
      if (!owns()) { discardRequest(id); return; }
      comparison.ids.add(id); column.id = id; column.streamIndex = 0;
    }
    const response = await fetch(`/api/compare/${encodeURIComponent(column.id)}/stream/${column.streamIndex}`, { signal: controller.signal });
    if (!owns()) return;
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}: ${await response.text()}`);
      error.status = response.status;
      throw error;
    }
    if (!response.body) throw new Error('the model returned no response stream');
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const line = value => {
      if (!value.startsWith('data:')) return;
      const raw = value.slice(5).trim();
      if (!raw) return;
      if (raw === '[DONE]') { terminal = true; return; }
      const chunk = JSON.parse(raw);
      if ('error' in chunk) throw new Error(String(chunk.error || 'the model reported an error without details'));
      if (typeof chunk.delta === 'string' && chunk.delta.length) {
        acc += chunk.delta;
        if (acc.trim()) {
          column.text = acc;
          column.nodes.body.innerHTML = mdToHtml(acc);
          column.nodes.body.scrollTop = column.nodes.body.scrollHeight;
          if (column.message !== 'responding…') { column.message = 'responding…'; updateComparison(comparison); }
        }
      }
      if (chunk.done === true) terminal = true;
    };
    while (!terminal) {
      const { done, value } = await reader.read();
      if (!owns()) return;
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const value of lines) { line(value); if (terminal) break; }
      if (done) { if (!terminal && buffer) line(buffer); break; }
    }
    if (!owns()) return;
    if (!terminal) throw new Error('the response stopped before it finished');
    if (!acc.trim()) throw new Error('the model finished without returning an answer');
    column.state = 'complete'; column.message = 'response ready';
  } catch (error) {
    if (!owns()) return;
    column.state = 'error';
    column.detail = String(error.message || error).slice(0, 2000);
    column.message = failureMessage(column.detail, error.status);
  } finally {
    if (reader) { try { await reader.cancel(); } catch {} reader.releaseLock(); }
    if (owns()) { column.controller = null; column.retrying = false; updateComparison(comparison); }
  }
}

async function pickWinner(comparison, index) {
  if (!comparison || _comparison !== comparison || !Number.isInteger(index)) return;
  const ready = comparison.columns.filter(column => column.state === 'complete');
  if (ready.length < 2 || comparison.columns.some(column => column.state === 'streaming')
    || comparison.columns[index]?.state !== 'complete') return;
  if (comparison.vote && (comparison.vote.index !== index || comparison.vote.pending || comparison.vote.saved)) return;
  if (!comparison.vote) comparison.vote = { index, pending: false, saved: false,
    pairs: ready.filter(column => column.index !== index).map(column => ({
      request_id: requestId(), winner: comparison.columns[index].model.model, loser: column.model.model,
    })), confirmed: new Set() };
  const vote = comparison.vote;
  vote.pending = true; updateComparison(comparison);
  try {
    for (const pair of vote.pairs) {
      if (vote.confirmed.has(pair.request_id)) continue;
      const response = await fetch('/api/compare/vote', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pair),
      });
      if (!response.ok || (await response.json()).ok !== true) throw new Error('vote not confirmed');
      vote.confirmed.add(pair.request_id);
    }
    vote.saved = true;
    disposeComparison(comparison);
    if (_comparison === comparison) { toast('winner saved', 'success'); void loadCompareLeaderboard(); }
  } catch {
    // Keep the same vote identities; the inline state offers a safe retry.
  } finally {
    vote.pending = false; updateComparison(comparison);
  }
}

window._pickWinner = index => pickWinner(_comparison, index);

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
      if (accepted && draftRevision === revision && inp.value === draft) {
        inp.value = '';
        const submitted = document.getElementById('compare-submitted-prompt');
        if (ownsFocus && submitted?.getClientRects().length) submitted.focus();
      }
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
