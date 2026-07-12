import { confirm as dlgConfirm } from './dialog.js';
import { getSelected, getSelectionSource } from './models.js?v=210';
import { getAttachments, clearAttachments } from './uploads.js';
import {
  appendUserMsg,
  createStreamingAiRow,
  ensureSession,
  getActiveId,
  loadSessions,
  scrollDown,
  showMessages,
} from './sessions.js';
import { mdToHtml, toast } from './util.js';

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'interrupted', 'uncertain']);
let _submitting = false;

export function explicitHandoffSelection(selection = {}, source = '') {
  if (source !== 'explicit' && source !== 'session') return { endpoint_id: '', model: '' };
  return {
    endpoint_id: String(selection?.endpointId || selection?.endpoint_id || '').trim(),
    model: typeof selection?.model === 'string' ? selection.model.trim() : '',
  };
}

export function explicitHandoffModel(selection = {}, source = '') {
  return explicitHandoffSelection(selection, source).model;
}

export function handoffActionForState(state) {
  if (state === 'queued' || state === 'running') return 'cancel';
  if (state === 'failed' || state === 'cancelled' || state === 'interrupted') return 'retry';
  return '';
}

function safe(value = '') {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setCard(card, run, preview) {
  card.dataset.runId = run?.id || '';
  const state = run?.state || 'preparing';
  const action = handoffActionForState(state);
  const summary = run?.result_summary || run?.safe_error || '';
  card.innerHTML = `
    <div class="jarvis-card-head">
      <span class="jarvis-card-dot" aria-hidden="true"></span>
      <strong>jarvis</strong>
      <span class="jarvis-card-state">${safe(state.replaceAll('_', ' '))}</span>
    </div>
    <div class="jarvis-card-model">${safe(preview?.endpoint || 'model unavailable')} · ${safe(preview?.model || '')}${preview?.privacy_class ? ` · ${safe(preview.privacy_class)}` : ''}</div>
    ${summary ? `<div class="jarvis-card-result">${mdToHtml(summary)}</div>` : '<div class="jarvis-card-note">this run is durable. you can close the tab.</div>'}
    <div class="jarvis-card-actions">
      ${action ? `<button class="act-btn" data-jarvis-action="${action}">${action}</button>` : ''}
    </div>`;
  card.querySelector('[data-jarvis-action="cancel"]')?.addEventListener('click', () => cancel(card, preview));
  card.querySelector('[data-jarvis-action="retry"]')?.addEventListener('click', () => retry(card, preview));
  scrollDown();
}

async function readRun(runId) {
  const response = await fetch(`/api/jarvis/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) throw new Error('Jarvis run is unavailable');
  return response.json();
}

async function poll(card, preview) {
  const runId = card.dataset.runId;
  if (!runId) return;
  try {
    const run = await readRun(runId);
    setCard(card, run, preview);
    if (!TERMINAL.has(run.state)) setTimeout(() => poll(card, preview), 1500);
    else {
      await loadSessions();
      await import('./projects.js').then(module => module.loadProjects()).catch(() => {});
    }
  } catch (error) {
    card.querySelector('.jarvis-card-note')?.replaceChildren(error.message || 'run status unavailable');
  }
}

async function cancel(card, preview) {
  const response = await fetch(`/api/jarvis/runs/${encodeURIComponent(card.dataset.runId)}/cancel`, {
    method: 'POST',
  });
  if (!response.ok) { toast('Jarvis could not cancel this run', 'error'); return; }
  setCard(card, await response.json(), preview);
  setTimeout(() => poll(card, preview), 500);
}

async function retry(card, preview) {
  const response = await fetch(`/api/jarvis/runs/${encodeURIComponent(card.dataset.runId)}/retry`, {
    method: 'POST',
  });
  if (!response.ok) { toast('Jarvis could not retry this run', 'error'); return; }
  setCard(card, await response.json(), preview);
  poll(card, preview);
}

async function preview(sessionId, override = {}) {
  const params = new URLSearchParams({ session_id: sessionId });
  if (override.endpoint_id && override.model) {
    params.set('endpoint_override', override.endpoint_id);
    params.set('model_override', override.model);
  }
  const response = await fetch(`/api/jarvis/handoffs/preview?${params}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'configure a Jarvis model in Settings');
  return data;
}

export async function runWithJarvis(request) {
  request = String(request || '').trim();
  if (!request || _submitting) return null;
  _submitting = true;
  let card = null;
  try {
    const sessionId = getActiveId() || await ensureSession({ mode: 'jarvis' });
    if (!sessionId) return null;
    showMessages();
    appendUserMsg(request);
    const streamRow = createStreamingAiRow();
    card = document.createElement('div');
    card.className = 'jarvis-handoff-card';
    card.setAttribute('role', 'status');
    card.setAttribute('aria-live', 'polite');
    streamRow.body.appendChild(card);
    setCard(card, null, null);

    const modelOverride = explicitHandoffSelection(getSelected(), getSelectionSource());
    const shown = await preview(sessionId, modelOverride);
    setCard(card, null, shown);
    if (shown.privacy_class === 'remote') {
      const allowed = await dlgConfirm(
        `Run with ${shown.model} on ${shown.endpoint}? Project context may leave Alles.`,
      );
      if (!allowed) {
        card.innerHTML = '<div class="jarvis-card-note">not handed off. switch to Chat to keep working here.</div>';
        return null;
      }
    }

    const files = getAttachments();
    const response = await fetch('/api/jarvis/handoffs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        request,
        endpoint_override: modelOverride.endpoint_id,
        model_override: modelOverride.model,
        file_ids: files,
        confirmed_endpoint_id: shown.endpoint_id,
        confirmed_model: shown.model,
      }),
    });
    const run = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(run.detail || 'Jarvis handoff failed');
    clearAttachments();
    setCard(card, run, shown);
    poll(card, shown);
    toast('running with Jarvis', 'success');
    return run;
  } catch (error) {
    if (card) card.innerHTML = `<div class="jarvis-card-note error">${safe(error.message || 'Jarvis handoff failed')}</div>`;
    else toast(error.message || 'Jarvis handoff failed', 'error');
    return null;
  } finally {
    _submitting = false;
  }
}

export function runMessageWithJarvis(button) {
  const assistantRow = button?.closest('.msg-row');
  let previous = assistantRow?.previousElementSibling;
  while (previous && !previous.querySelector('.user-bubble')) previous = previous.previousElementSibling;
  const request = previous?.querySelector('.user-bubble')?.textContent?.trim();
  if (request) runWithJarvis(request);
}

window.runMessageWithJarvis = runMessageWithJarvis;
