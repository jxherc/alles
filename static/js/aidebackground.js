import { createStreamingAiRow, scrollDown } from './sessions.js';
import { confirm as confirmDialog } from './dialog.js';
import { t as tr } from './i18n.js';

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'interrupted', 'uncertain']);
const timers = new Map();

function safeMessage(value, fallback = 'background work is unavailable') {
  return String(value || fallback).replace(/jarvis/gi, 'Aide');
}

async function readJson(response, fallback) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(safeMessage(typeof detail === 'string' ? detail : detail?.message, fallback));
  }
  return payload;
}

function selectionOverride(selection = {}, source = '') {
  if (!['explicit', 'session'].includes(source)) return { endpoint_id: '', model: '' };
  return {
    endpoint_id: String(selection?.endpointId || selection?.endpoint_id || '').trim(),
    model: String(selection?.model || '').trim(),
  };
}

function actionForState(state) {
  if (['queued', 'running'].includes(state)) return 'cancel';
  if (['failed', 'cancelled', 'interrupted'].includes(state)) return 'retry';
  return '';
}

function makeCard() {
  const { row, body } = createStreamingAiRow();
  const card = document.createElement('section');
  card.className = 'aide-background-card';
  card.setAttribute('role', 'status');
  card.setAttribute('aria-live', 'polite');
  body.append(card);
  row.dataset.backgroundWork = 'true';
  return card;
}

function renderCard(card, run = {}, preview = {}) {
  card.dataset.runId = run.id || card.dataset.runId || '';
  const state = run.state || 'preparing';
  const head = document.createElement('div');
  head.className = 'aide-background-head';
  const title = document.createElement('strong');
  title.textContent = TERMINAL.has(state) ? 'background work' : 'working in background';
  const stateText = document.createElement('span');
  stateText.className = 'aide-background-state';
  stateText.textContent = state.replaceAll('_', ' ');
  head.append(title, stateText);

  const details = document.createElement('div');
  details.className = 'aide-background-details';
  details.textContent = preview.model
    ? `${preview.endpoint || 'model'} · ${preview.model}`
    : 'this stays attached to this task';

  card.replaceChildren(head, details);
  const summary = run.result_summary || run.safe_error;
  if (summary && state !== 'succeeded') {
    const note = document.createElement('div');
    note.className = 'aide-background-note';
    note.textContent = safeMessage(summary);
    card.append(note);
  }

  const action = card.dataset.runId ? actionForState(state) : '';
  if (action) {
    const actions = document.createElement('div');
    actions.className = 'aide-background-actions';
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = action;
    button.dataset.backgroundAction = action;
    button.addEventListener('click', () => act(card, action, preview));
    actions.append(button);
    card.append(actions);
  }
  scrollDown();
}

function stopPolling(runId) {
  const timer = timers.get(runId);
  if (timer) clearTimeout(timer);
  timers.delete(runId);
}

async function readRun(runId) {
  return readJson(await fetch(`/api/jarvis/runs/${encodeURIComponent(runId)}`), 'background status is unavailable');
}

async function poll(card, preview = {}) {
  const runId = card.dataset.runId;
  if (!runId || !card.isConnected) return;
  const pollVersion = card.dataset.pollVersion || '0';
  try {
    const run = await readRun(runId);
    // A cancel/retry may finish while this request is in flight. Never let that
    // stale status overwrite the action response that the user just received.
    if ((card.dataset.pollVersion || '0') !== pollVersion) return;
    renderCard(card, run, preview);
    if (TERMINAL.has(run.state)) {
      stopPolling(runId);
      if (run.state === 'succeeded') {
        setTimeout(() => window._reloadActiveSession?.(), 650);
      }
      return;
    }
  } catch (error) {
    const note = card.querySelector('.aide-background-details');
    if (note) note.textContent = safeMessage(error.message);
  }
  timers.set(runId, setTimeout(() => poll(card, preview), 1400));
}

async function act(card, action, preview) {
  const runId = card.dataset.runId;
  const button = card.querySelector('[data-background-action]');
  if (!runId || !button) return;
  card.dataset.pollVersion = String(Number(card.dataset.pollVersion || 0) + 1);
  stopPolling(runId);
  button.disabled = true;
  try {
    const run = await readJson(
      await fetch(`/api/jarvis/runs/${encodeURIComponent(runId)}/${action}`, { method: 'POST' }),
      `could not ${action} this work`,
    );
    renderCard(card, run, preview);
    if (!TERMINAL.has(run.state)) poll(card, preview);
  } catch (error) {
    button.disabled = false;
    const note = card.querySelector('.aide-background-details');
    if (note) note.textContent = safeMessage(error.message);
  }
}

async function previewWork(sessionId, override) {
  const params = new URLSearchParams({ session_id: sessionId });
  if (override.endpoint_id && override.model) {
    params.set('endpoint_override', override.endpoint_id);
    params.set('model_override', override.model);
  }
  return readJson(
    await fetch(`/api/jarvis/handoffs/preview?${params}`),
    'configure a background model in Settings',
  );
}

export async function startBackgroundWork({
  sessionId,
  request,
  fileIds = [],
  selection = {},
  selectionSource = '',
  permissionMode = 'approve',
  effort = 'medium',
  reasoningMode = 'automatic',
  customEffort = null,
} = {}) {
  const card = makeCard();
  renderCard(card);
  try {
    const override = selectionOverride(selection, selectionSource);
    const preview = await previewWork(sessionId, override);
    renderCard(card, {}, preview);
    const confirmation = {};
    if (preview.privacy_class === 'remote') {
      const allowed = await confirmDialog(tr('aide.remote_background_confirm', {
        endpoint: preview.endpoint,
        model: preview.model,
      }));
      if (!allowed) {
        card.closest('[data-background-work="true"]')?.remove();
        return null;
      }
      confirmation.confirmed_endpoint_id = preview.endpoint_id;
      confirmation.confirmed_model = preview.model;
    }
    const run = await readJson(await fetch('/api/jarvis/handoffs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        request,
        endpoint_override: override.endpoint_id,
        model_override: override.model,
        file_ids: fileIds,
        ...confirmation,
        permission_mode: permissionMode,
        effort,
        reasoning_mode: reasoningMode,
        custom_effort: customEffort,
      }),
    }), 'could not start background work');
    renderCard(card, run, preview);
    poll(card, preview);
    return run;
  } catch (error) {
    renderCard(card, { state: 'failed', safe_error: error.message });
    return null;
  }
}

export async function reattachBackgroundWork(sessionId) {
  document.querySelectorAll('[data-background-work="true"]').forEach(row => row.remove());
  try {
    const runs = await readJson(await fetch('/api/jarvis/runs?limit=100'), '');
    const relevantRuns = runs.filter(item => (
      item.session_id === sessionId
      && ['queued', 'running', 'failed', 'cancelled', 'interrupted', 'uncertain'].includes(item.state)
    ));
    if (relevantRuns.length) {
      relevantRuns.forEach(run => {
        const card = makeCard();
        renderCard(card, run);
        if (!TERMINAL.has(run.state)) poll(card);
      });
    }
    import('./bgrun.js').then(module => module.reattach(sessionId)).catch(() => {});
    return relevantRuns.length ? relevantRuns : null;
  } catch {}
  import('./bgrun.js').then(module => module.reattach(sessionId)).catch(() => {});
  return null;
}
