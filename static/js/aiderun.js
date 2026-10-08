import { createFocusBoundary } from './kokuen.js?v=1';
import { renderAideQuestion } from './aidequestions.js';
import { requestWithRecentOwner } from './recent_owner.js';
import { replaceRouteUrl } from './route_history.js';
import { formatDateTime } from './i18n.js';

let current = null;
const STATES = new Set(['queued', 'running', 'waiting_input', 'waiting_approval', 'paused', 'succeeded', 'failed', 'cancelled', 'interrupted', 'uncertain']);
const ACTIVE = new Set(['queued', 'running', 'waiting_input', 'waiting_approval', 'paused']);
const RETRY_PREFIX = 'alles.aide.retry.v1:';
function requestIdentity() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const enc = encodeURIComponent;
const jsonOptions = body => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
const stable = value => JSON.stringify(value, function (_key, item) {
  return item && !Array.isArray(item) && typeof item === 'object' ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item;
});

function el(tag, text = '', className = '') {
  const node = document.createElement(tag); node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(label, action) {
  const node = el('button', label, 'btn'); node.type = 'button'; node.onclick = action; return node;
}
async function json(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.message || data.detail?.message || (typeof data.detail === 'string' ? data.detail : 'could not load this job'));
    error.status = response.status; throw error;
  }
  return data;
}
function date(value) {
  if (!value) return '';
  const parsed = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + 'Z');
  return Number.isNaN(parsed.getTime()) ? '' : formatDateTime(parsed, { dateStyle: 'medium', timeStyle: 'short' });
}
function checkedRun(data, id) {
  if (data?.id !== id || !STATES.has(data.state) || !Array.isArray(data.prompts) || !Array.isArray(data.events)) throw new Error('could not confirm this job');
  return data;
}

export function closeAideRun({ clearTarget = true, restoreFocus = true } = {}) {
  const owner = current;
  if (!owner) return;
  current = null; owner.closed = true; clearTimeout(owner.timer);
  owner.boundary.deactivate({ restoreFocus: false }); owner.boundary.destroy();
  owner.overlay.remove();
  for (const [node, inert] of owner.inert) if (node.isConnected) node.inert = inert;
  if (clearTarget) {
    const url = new URL(location.href);
    if (url.searchParams.get('record_view') === 'chat' && url.searchParams.get('record') === owner.id) {
      for (const key of ['record_view', 'record', 'occurrence']) url.searchParams.delete(key);
      replaceRouteUrl(url.pathname + url.search + url.hash);
    }
  }
  if (restoreFocus) document.getElementById('composer-ta')?.focus();
}

export async function openAideRun(id, isCurrent = () => true) {
  closeAideRun({ clearTarget: false, restoreFocus: false });
  const overlay = el('div', '', 'capture-overlay');
  const panel = el('section', '', 'capture-review aide-run-detail');
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'aide-run-title'); panel.dataset.runId = id;
  const title = el('h2', 'aide work'); title.id = 'aide-run-title';
  const state = el('p'); state.dataset.runState = ''; state.setAttribute('role', 'status');
  const result = el('div', '', 'aide-run-result');
  const prompts = el('div', '', 'aide-run-prompts');
  const events = el('details', '', 'aide-run-events'); events.append(el('summary', 'activity'), el('ol'));
  const status = el('p', 'loading job…', 'aide-run-status'); status.setAttribute('role', 'status'); status.tabIndex = -1;
  const actions = el('div', '', 'capture-actions');
  const close = button('close', () => closeAideRun());
  const refresh = button('refresh', () => load());
  const openSession = button('open conversation', async () => {
    const sessionId = owner.run?.session_id;
    if (!sessionId) return;
    closeAideRun({ restoreFocus: false });
    await window._openSearchResult?.('chat', sessionId);
  });
  const cancel = button('cancel job', () => act(async () => {
    try {
      const data = checkedRun(await json(`/api/jarvis/runs/${enc(id)}/cancel`, { method: 'POST' }), id);
      if (data.state !== 'cancelled' && !(data.state === 'running' && data.events.some(event => event.kind === 'cancel_requested'))) throw new Error('cancel was not confirmed');
      status.textContent = data.state === 'cancelled' ? 'job cancelled' : 'cancellation requested';
    } catch (error) {
      const data = checkedRun(await json(`/api/jarvis/runs/${enc(id)}`), id);
      if (data.state !== 'cancelled' && !(data.state === 'running' && data.events.some(event => event.kind === 'cancel_requested'))) throw error;
      status.textContent = data.state === 'cancelled' ? 'job cancelled' : 'cancellation requested';
    }
    await load({ quiet: true });
  }));
  const retry = button('retry job', () => act(async () => {
    const key = RETRY_PREFIX + id;
    const requestId = sessionStorage.getItem(key) || requestIdentity();
    if (!/^[a-f0-9-]{36}$/.test(requestId)) throw new Error('could not read the pending retry');
    sessionStorage.setItem(key, requestId);
    if (sessionStorage.getItem(key) !== requestId) throw new Error('could not keep this retry');
    const confirmed = data => {
      checkedRun(data, requestId);
      if (!data.events.some(event => event.kind === 'handoff_requested' && event.data?.previous_run_id === id && event.data?.retry_request_id === requestId)) throw new Error('could not confirm the retry');
      return data;
    };
    let data;
    try { data = confirmed(await json(`/api/jarvis/runs/${enc(id)}/retry`, jsonOptions({ request_id: requestId }))); }
    catch {
      try { data = confirmed(await json(`/api/jarvis/runs/${enc(requestId)}`)); }
      catch { throw new Error('could not confirm the retry; try again to check the same job'); }
    }
    if (!live()) return;
    if (!await window._openRecord?.('chat', data.id)) throw new Error('retry saved; could not open the job. retry to open the same job');
    const target = new URL(location.href).searchParams;
    if (current?.id !== data.id || target.get('record_view') !== 'chat' || target.get('record') !== data.id) return;
    try { if (sessionStorage.getItem(key) === requestId) sessionStorage.removeItem(key); } catch { /* The saved identity still resolves this child. */ }
  }));
  openSession.hidden = cancel.hidden = retry.hidden = true;
  actions.append(close, refresh, openSession, cancel, retry);
  panel.append(title, state, result, prompts, events, status, actions); overlay.append(panel);
  const inert = [...document.body.children].map(node => [node, node.inert]);
  for (const [node] of inert) node.inert = true;
  document.body.append(overlay);
  const owner = { id, overlay, inert, closed: false, busy: false, timer: null, generation: 0, run: null, promptSignature: '', boundary: createFocusBoundary(panel, { onEscape: () => closeAideRun() }) };
  current = owner;
  const live = () => !owner.closed && current === owner && isCurrent();
  overlay.onclick = event => { if (event.target === overlay) closeAideRun(); };
  owner.boundary.activate({ focus: close });
  function poll() {
    clearTimeout(owner.timer);
    if (live() && ACTIVE.has(owner.run?.state)) owner.timer = setTimeout(() => { if (owner.busy) poll(); else void load({ quiet: true }); }, 3000);
  }
  function lock(busy) {
    owner.busy = busy;
    if (busy) { ++owner.generation; clearTimeout(owner.timer); }
    panel.setAttribute('aria-busy', String(busy));
    for (const control of [refresh, cancel, retry]) control.disabled = busy;
  }

  async function act(callback) {
    if (owner.busy || !live()) return;
    lock(true);
    try { await callback(); }
    catch (error) { if (live()) status.textContent = error.message || 'could not confirm this action; refresh to check'; }
    finally {
      owner.busy = false;
      if (live()) { lock(false); poll(); }
    }
  }
  async function answer(prompt, payload, structured) {
    if (owner.busy || !live()) throw new Error('this job is already updating');
    lock(true);
    try {
      const body = structured ? payload : { answer: prompt.options.length ? prompt.options[Number(payload.answers.choice.selected[0])] : payload.answers.choice.free_text };
      const matches = data => data?.id === prompt.id && data.state === 'answered' && (structured ? stable(data.answer_data) === stable(body) : data.answer === body.answer);
      let data;
      try { data = await json(`/api/jarvis/prompts/${enc(prompt.id)}/answer`, jsonOptions(body)); }
      catch { /* A lost response is checked against the current durable answer. */ }
      if (!matches(data)) {
        const run = checkedRun(await json(`/api/jarvis/runs/${enc(id)}`), id);
        data = run.prompts.find(item => item.id === prompt.id);
      }
      if (!matches(data)) throw new Error('answer was not confirmed');
      return { ok: true };
    } finally {
      owner.busy = false;
      if (live()) { lock(false); poll(); }
    }
  }
  async function approval(prompt, host) {
    try {
      const action = await json(`/api/delegation/actions/${enc(prompt.delegated_action_id)}`);
      if (!live() || !host.isConnected) return;
      if (action.id !== prompt.delegated_action_id || action.run_id !== id || !action.exact_hash) throw new Error('approval details did not match this job');
      const details = el('dl');
      for (const [label, value] of [['action', action.action], ['target', action.target], ['data', action.data_summary], ['privacy', action.privacy_effect], ['cost', action.cost], ['expires', date(action.expires_at)]]) {
        details.append(el('dt', label), el('dd', value || 'not specified'));
      }
      host.append(details);
      if (action.state !== 'pending') { host.append(el('p', action.state.replaceAll('_', ' '))); return; }
      const expiry = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(action.expires_at) ? action.expires_at : action.expires_at + 'Z');
      if (Number.isNaN(expiry.getTime()) || expiry.getTime() <= Date.now()) { host.append(el('p', 'approval expired; it cannot be used')); return; }
      const decision = async allow => {
        let response, saved;
        const matches = value => value?.id === action.id && value.exact_hash === action.exact_hash && (allow ? Boolean(value.approved_at) : value.state === 'denied');
        try {
          response = await requestWithRecentOwner(fetch, `/api/delegation/actions/${enc(action.id)}/decision`, jsonOptions({ allow, exact_hash: action.exact_hash }));
          if (response.ok) saved = await response.json();
        } catch (error) {
          if (error.message === 'owner confirmation cancelled') throw error;
        }
        if (!matches(saved)) saved = await json(`/api/delegation/actions/${enc(action.id)}`);
        if (!matches(saved)) throw new Error('approval was not confirmed; refresh its current details');
        if (live()) { status.textContent = allow ? 'approval saved' : 'action denied'; owner.promptSignature = ''; await load({ quiet: true }); }
      };
      const choices = el('div', '', 'capture-actions');
      const deny = button('deny', () => act(() => decision(false)));
      const allow = button('allow this action', () => act(() => decision(true)));
      choices.append(deny, allow); host.append(choices);
    } catch (error) { if (live() && host.isConnected) host.append(el('p', error.message || 'could not load approval details; refresh to retry')); }
  }
  function showPrompts(data) {
    const signature = stable(data);
    if (signature === owner.promptSignature) return;
    const previousFocus = document.activeElement;
    const hadFocus = prompts.contains(previousFocus);
    const previous = new Map([...prompts.children].map(host => [host.dataset.promptId, host]));
    owner.promptSignature = signature; prompts.replaceChildren();
    for (const prompt of data) {
      const prior = previous.get(prompt.id);
      if (prompt.kind === 'choice' && prompt.state === 'pending' && prior?.dataset.signature === stable(prompt)) { prompts.append(prior); continue; }
      const host = el('section', '', 'aide-run-prompt'); host.dataset.promptId = prompt.id; host.dataset.signature = stable(prompt); prompts.append(host);
      if (prompt.state !== 'pending') { host.append(el('h3', prompt.question), el('p', `${prompt.state}: ${prompt.answer || ''}`)); continue; }
      if (prompt.kind === 'approval') {
        host.append(el('h3', prompt.question));
        if (prompt.delegated_action_id) void approval(prompt, host);
        else host.append(el('p', 'approval details are unavailable; refresh to check'));
      } else if (prompt.kind === 'choice') {
        const structured = Array.isArray(prompt.question_schema?.questions);
        const request = structured ? { ...prompt.question_schema, id: prompt.id } : {
          id: prompt.id, title: prompt.question,
          questions: [{ id: 'choice', prompt: prompt.question, selection: 'single', allow_free_text: !prompt.options.length, choices: prompt.options.map((label, index) => ({ id: String(index), label })) }],
        };
        renderAideQuestion(host, request, { focus: false, allowCancel: structured, sendAnswer: payload => answer(prompt, payload, structured), onResolved: payload => { if (live()) { status.textContent = payload.cancelled ? 'question cancelled' : 'answer saved'; void load({ quiet: true }); } } });
      }
    }
    if (hadFocus && live()) (previousFocus.isConnected ? previousFocus : status).focus();
  }
  async function load({ quiet = false } = {}) {
    if (!live()) return;
    const generation = ++owner.generation;
    clearTimeout(owner.timer);
    if (!quiet) { status.textContent = 'loading job…'; owner.promptSignature = ''; }
    try {
      const data = checkedRun(await json(`/api/jarvis/runs/${enc(id)}`), id);
      if (!live() || generation !== owner.generation) return;
      owner.run = data;
      title.textContent = data.title || 'aide work';
      state.textContent = data.state.replaceAll('_', ' ');
      const blocks = [];
      if (data.safe_error) blocks.push(el('p', data.safe_error));
      if (data.result_summary) blocks.push(el('p', data.result_summary));
      if (data.state === 'uncertain') blocks.push(el('p', 'the outcome is unknown. inspect the result before starting more work.'));
      result.replaceChildren(...blocks);
      openSession.hidden = !data.session_id;
      cancel.hidden = !['queued', 'running'].includes(data.state);
      retry.hidden = !data.can_retry;
      events.querySelector('ol').replaceChildren(...data.events.map(event => el('li', [date(event.created_at), event.summary || event.kind.replaceAll('_', ' ')].filter(Boolean).join(' · '))));
      showPrompts(data.prompts);
      if (!quiet) status.textContent = '';
      poll();
    } catch (error) {
      if (live() && generation === owner.generation) status.textContent = error.status === 404 ? 'this job is no longer available' : error.message || 'could not load this job; refresh to retry';
    }
  }
  await load();
  return true;
}
