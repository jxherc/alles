import { requestId } from './request_id.js';
import { escapeHtml, toast } from './util.js';
import { icon } from './icons.js';
import { prompt as dlgPrompt } from './dialog.js';
import { t } from './i18n.js';

let active = null;
let readiness = null;
let statusRequest = null;
let surfaceOpen = false;
let detailsOpen = false;
let initialized = false;
let state = 'checking';
let message = '';
let lastDuration = 0;
let tick = null;
let returnFocus = null;
let transcripts = [];

const phone = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3H4.5A1.5 1.5 0 0 0 3 4.5C3 13.6 10.4 21 19.5 21a1.5 1.5 0 0 0 1.5-1.5V17l-5-2-2 2a15 15 0 0 1-7-7l2-2z"/></svg>';
const micOff = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 9v2a3 3 0 0 0 5.1 2.1M15 9V6a3 3 0 0 0-5.6-1.5M5.5 11.5a6.5 6.5 0 0 0 11.1 4.6M18.5 11.5a6.5 6.5 0 0 1-.3 2M12 18v3M3 3l18 18"/></svg>';

async function json(response, fallback) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || fallback);
  }
  return payload;
}

function elapsed() {
  return active?.connectedAt ? Math.max(0, Date.now() - active.connectedAt) : lastDuration;
}

function durationLabel(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function stateTitle() {
  return {
    checking: t('call.title_checking'), unavailable: t('call.title_unavailable'), ready: t('call.title_ready'),
    connecting: t('call.title_connecting'), connected: active?.muted ? t('call.title_muted') : t('common.connected'),
    reconnecting: t('call.title_reconnecting'), ended: t('call.title_ended'), error: t('call.title_error'),
  }[state] || t('call.title_unavailable');
}

function stateDescription() {
  if (message) return message;
  if (state === 'ready') return t('call.desc_ready');
  if (state === 'checking') return t('call.desc_checking');
  if (state === 'unavailable') return readiness?.reason || t('call.desc_unavailable');
  if (state === 'connecting') return active?.stream ? t('call.desc_connecting_voice') : t('call.desc_connecting_mic');
  if (state === 'reconnecting') return t('call.desc_reconnecting');
  if (state === 'connected') return active?.muted ? t('call.desc_muted') : t('call.desc_connected');
  if (state === 'ended') return t('call.desc_ended');
  return t('call.desc_error');
}

function updateButtons() {
  for (const id of ['aide-call-open', 'live-voice-btn']) {
    const button = document.getElementById(id);
    if (!button) continue;
    button.dataset.state = state;
    button.setAttribute('aria-expanded', String(surfaceOpen));
    button.setAttribute('aria-controls', 'aide-call-workspace');
    button.setAttribute('aria-label', active ? t('call.return_to_call_state', { state: stateTitle() }) : t('call.open'));
    button.title = active ? t('call.return_to_call') : t('call.voice_call');
    button.disabled = false;
    if (id === 'live-voice-btn') {
      button.hidden = Boolean(document.getElementById('aide-call-open'));
      button.setAttribute('aria-pressed', String(Boolean(active)));
    }
  }
  updateOngoingCall();
}

function updateOngoingCall() {
  let control = document.getElementById('aide-call-ongoing');
  if (!control && active && document.body) {
    control = document.createElement('div');
    control.id = 'aide-call-ongoing';
    control.dataset.kokuenSurface = 'ongoing-call';
    control.setAttribute('role', 'region');
    control.setAttribute('aria-label', t('call.ongoing'));
    control.innerHTML = `<button type="button" id="aide-call-return">${phone}<span>${t('call.return_to_call')}</span><span id="aide-call-global-state" role="status" aria-live="polite"></span></button><button type="button" id="aide-call-global-end" aria-label="${t('call.end_voice_call')}">${icon('close')}<span>${t('call.end')}</span></button>`;
    document.body.appendChild(control);
    document.getElementById('aide-call-return')?.addEventListener('click', openLiveVoiceSurface);
    document.getElementById('aide-call-global-end')?.addEventListener('click', async () => {
      await hangupLiveVoice();
      if (document.activeElement?.id === 'aide-call-global-end') {
        document.getElementById('app-drawer-btn')?.focus({ preventScroll: true });
      }
    });
  }
  if (!control) return;
  control.hidden = !active;
  control.dataset.state = state;
  const label = document.getElementById('aide-call-global-state');
  if (label && label.textContent !== stateTitle()) label.textContent = stateTitle();
  document.getElementById('aide-call-return')?.setAttribute('aria-label', t('call.return_to_voice_call_state', { state: stateTitle() }));
}

function emitState() {
  window.dispatchEvent(new CustomEvent('aide:call-state', {
    detail: { state, active: Boolean(active), muted: Boolean(active?.muted) },
  }));
}

function changeState(next, detail = '') {
  state = next;
  message = detail;
  render();
  emitState();
}

function render() {
  updateButtons();
  const surface = document.getElementById('aide-call-workspace');
  if (!surface) return;
  const focused = surface.contains(document.activeElement) ? document.activeElement?.id : null;
  surface.hidden = !surfaceOpen;
  surface.dataset.state = state;
  surface.dataset.kokuenSurface = 'aide-call';
  surface.setAttribute('aria-label', t('call.voice_call'));
  const canStart = !active && Boolean(readiness?.available) && state !== 'checking';
  const canMute = Boolean(active?.stream);
  const timeVisible = Boolean(active?.connectedAt) || (state === 'ended' && lastDuration > 0);
  surface.innerHTML = `
    <div class="aide-call-topline">
      <button type="button" id="aide-call-back" class="aide-call-text">${icon('chevron-left')}<span>${t('common.back')}</span></button>
      <button type="button" id="aide-call-details-toggle" class="aide-call-text" aria-expanded="${detailsOpen}" aria-controls="aide-call-details">${icon('info')}<span>${t('call.connection')}</span></button>
    </div>
    <div class="aide-call-body">
      <div class="aide-call-stage">
        <div class="aide-call-mark" aria-hidden="true">${active?.muted ? micOff : phone}</div>
        <div class="aide-call-state" role="status" aria-live="polite" aria-atomic="true">
          <h2 id="aide-call-title">${stateTitle()}</h2>
          <p id="aide-call-description">${escapeHtml(stateDescription())}</p>
        </div>
        <span class="aide-call-time" id="aide-call-time" aria-label="${t('call.duration')}"${timeVisible ? '' : ' hidden'}>${durationLabel(elapsed())}</span>
        <div class="aide-call-actions">
          ${canStart ? `<button type="button" id="aide-call-start" class="aide-call-action aide-call-primary">${phone}<span>${state === 'ready' ? t('call.start') : t('call.again')}</span></button>` : ''}
          ${canMute ? `<button type="button" id="aide-call-mute" class="aide-call-action" aria-pressed="${Boolean(active.muted)}" aria-label="${active.muted ? t('call.unmute_mic') : t('call.mute_mic')}">${active.muted ? micOff : icon('mic')}<span>${active.muted ? t('call.unmute') : t('call.mute')}</span></button>` : ''}
          ${active ? `<button type="button" id="aide-call-end" class="aide-call-action aide-call-end">${icon('close')}<span>${state === 'connecting' ? t('common.cancel') : t('call.end_call')}</span></button>` : ''}
          ${!active && (state === 'unavailable' || state === 'error') ? `<button type="button" id="aide-call-retry" class="aide-call-action">${icon('refresh')}<span>${t('call.check_again')}</span></button>` : ''}
        </div>
        <div class="aide-call-transcript" id="aide-call-transcript"${transcripts.length ? '' : ' hidden'} aria-label="${t('call.transcript')}">
          ${transcripts.slice(-2).map(item => `<p><span>${item.role === 'user' ? t('call.you') : t('call.aide')}</span>${escapeHtml(item.text)}</p>`).join('')}
        </div>
      </div>
      <section class="aide-call-details" id="aide-call-details" aria-label="${t('call.details')}"${detailsOpen ? '' : ' hidden'}>
        <dl><div><dt>${t('call.status')}</dt><dd>${readiness ? (readiness.available ? t('call.configured') : t('common.unavailable')) : t('call.checking')}</dd></div>${readiness?.model ? `<div><dt>${t('call.model')}</dt><dd>${escapeHtml(readiness.model)}</dd></div>` : ''}</dl>
        <p>${escapeHtml(readiness?.available ? t('call.details_configured') : readiness?.reason || t('call.details_needs_model'))} ${t('call.details_transcripts')}</p>
        <button type="button" id="aide-call-settings" class="aide-call-text">${icon('gear')}<span>${t('aide.model_settings')}</span></button>
      </section>
    </div>`;
  surface.querySelector('#aide-call-back')?.addEventListener('click', closeLiveVoiceSurface);
  surface.querySelector('#aide-call-details-toggle')?.addEventListener('click', () => { detailsOpen = !detailsOpen; render(); });
  surface.querySelector('#aide-call-start')?.addEventListener('click', startLiveVoice);
  surface.querySelector('#aide-call-mute')?.addEventListener('click', toggleLiveVoiceMute);
  surface.querySelector('#aide-call-end')?.addEventListener('click', hangupLiveVoice);
  surface.querySelector('#aide-call-retry')?.addEventListener('click', () => refreshReadiness());
  surface.querySelector('#aide-call-settings')?.addEventListener('click', () => window._openSettings?.('models'));
  if (focused && surfaceOpen) {
    const replacement = document.getElementById(focused)
      || surface.querySelector('#aide-call-end, #aide-call-start, #aide-call-retry, #aide-call-back');
    replacement?.focus({ preventScroll: true });
  }
}

async function refreshReadiness() {
  if (active) return readiness;
  if (statusRequest) return statusRequest;
  changeState('checking');
  statusRequest = (async () => {
    try {
      const capability = await json(await fetch('/api/voice/realtime/status'), t('call.check_failed'));
      const browserReady = Boolean(navigator.mediaDevices?.getUserMedia && typeof RTCPeerConnection === 'function');
      readiness = capability.available && !browserReady
        ? { ...capability, available: false, reason: t('call.browser_unsupported') }
        : capability;
      if (!active) changeState(readiness.available ? 'ready' : 'unavailable');
      return readiness;
    } catch (error) {
      readiness = { available: false, reason: error?.message || t('call.check_failed_retry') };
      if (!active) changeState('unavailable');
      return readiness;
    } finally {
      statusRequest = null;
    }
  })();
  return statusRequest;
}

export async function openLiveVoiceSurface() {
  const source = document.activeElement;
  // Returning from another app must honor its unsaved-edit navigation guard.
  if (document.body.dataset.space !== 'aide' && window._navigateTo) {
    if (!await window._navigateTo('chat', { preserveSession: true })) return false;
  }
  if (!surfaceOpen) returnFocus = source;
  surfaceOpen = true;
  window.dispatchEvent(new CustomEvent('aide:call-surface', { detail: { open: true } }));
  render();
  document.getElementById('aide-call-back')?.focus({ preventScroll: true });
  if (!active) await refreshReadiness();
}

function hideLiveVoiceSurface() {
  surfaceOpen = false;
  detailsOpen = false;
  render();
}

export function closeLiveVoiceSurface() {
  hideLiveVoiceSurface();
  window.dispatchEvent(new CustomEvent('aide:call-surface', { detail: { open: false } }));
  const target = returnFocus?.isConnected && returnFocus.getClientRects?.().length
    ? returnFocus : document.getElementById('aide-call-open');
  target?.focus({ preventScroll: true });
}

async function persistTranscript(current, role, text, providerEventId) {
  const { call } = current;
  if (!text?.trim() || !providerEventId) return;
  const result = await json(await fetch(`/api/aide/calls/${encodeURIComponent(call.id)}/transcripts`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ role, text: text.trim(), provider_event_id: providerEventId }),
  }), t('call.transcript_save_failed'));
  if (result.created !== false && (!active || active === current)) {
    transcripts.push({ role, text: text.trim() });
    transcripts = transcripts.slice(-2);
    render();
  }
}

function sendToolResult(channel, callId, result) {
  if (channel.readyState !== 'open') return;
  channel.send(JSON.stringify({
    type: 'conversation.item.create',
    item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(result) },
  }));
  channel.send(JSON.stringify({ type: 'response.create' }));
}

async function startBackgroundTask(call, event) {
  let args = {};
  try { args = JSON.parse(event.arguments || '{}'); } catch {}
  const request = String(args.request || '').trim();
  if (!request) return { ok: false, error: t('call.task_empty') };
  const preview = await json(
    await fetch(`/api/jarvis/handoffs/preview?session_id=${encodeURIComponent(call.session_id)}`),
    t('call.background_unavailable'),
  );
  if (preview.privacy_class === 'remote') {
    return { ok: false, error: t('call.confirm_remote') };
  }
  const run = await json(await fetch('/api/jarvis/handoffs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      session_id: call.session_id,
      request_id: requestId(),
      request,
      permission_mode: 'approve',
      effort: 'medium',
      reasoning_mode: 'automatic',
      custom_effort: {},
    }),
  }), t('call.background_start_failed'));
  return { ok: true, run_id: run.id, state: run.state };
}

async function handleProviderEvent(current, event) {
  const { call, channel } = current;
  if (event.type === 'conversation.item.input_audio_transcription.completed') {
    await persistTranscript(current, 'user', event.transcript, event.event_id || `${event.item_id}:input`);
    await refreshCallConversation(call);
  } else if (event.type === 'response.output_audio_transcript.done') {
    await persistTranscript(current, 'assistant', event.transcript, event.event_id || `${event.item_id}:output`);
    await refreshCallConversation(call);
  } else if (
    event.type === 'response.function_call_arguments.done'
    && event.name === 'start_background_task'
  ) {
    if (active !== current || current.closed) return;
    let result;
    try { result = await startBackgroundTask(call, event); }
    catch (error) { result = { ok: false, error: error.message || t('call.background_unavailable_short') }; }
    sendToolResult(channel, event.call_id, result);
  } else if (event.type === 'error') {
    await finishCall(current, 'error', event.error?.message || t('call.provider_error'));
  }
}

async function refreshCallConversation(call) {
  if (call?.session_id && window._currentSession?.id === call.session_id) {
    await window._refreshAideSessionQuietly?.(call.session_id);
  }
}

function releaseMedia(current) {
  current.closed = true;
  clearTimeout(current.connectTimer);
  clearTimeout(current.reconnectTimer);
  current.stream?.getTracks().forEach(track => track.stop());
  current.channel?.close();
  current.peer?.close();
  if (current.audio) { current.audio.pause?.(); current.audio.srcObject = null; }
}

async function endRecord(current) {
  if (!current.call?.id || current.recordEnded) return;
  current.recordEnded = true;
  try {
    await json(await fetch(`/api/aide/calls/${encodeURIComponent(current.call.id)}/hangup`, { method: 'POST' }), t('call.ending_save_failed'));
  } catch (error) {
    current.recordEnded = false;
    toast(error?.message || t('call.ending_save_failed'), 'error');
  }
}

async function finishCall(current, next = 'ended', detail = '') {
  if (!current || current.closed) return;
  lastDuration = current.connectedAt ? Date.now() - current.connectedAt : 0;
  if (active === current) active = null;
  clearInterval(tick);
  tick = null;
  releaseMedia(current);
  changeState(next, detail);
  await endRecord(current);
}

function observeConnection(current) {
  if (active !== current || current.closed) return;
  const connection = current.peer.connectionState;
  if (connection === 'connected') {
    clearTimeout(current.connectTimer);
    clearTimeout(current.reconnectTimer);
    current.reconnectTimer = null;
    current.connectedAt ||= Date.now();
    if (!tick) tick = setInterval(() => {
      const timer = document.getElementById('aide-call-time');
      if (timer) timer.textContent = durationLabel(elapsed());
    }, 1000);
    changeState('connected');
  } else if (connection === 'disconnected') {
    changeState('reconnecting');
    current.reconnectTimer ||= setTimeout(() => {
      void finishCall(current, 'error', t('call.recover_failed'));
    }, 15000);
  } else if (connection === 'failed' || connection === 'closed') {
    void finishCall(current, 'error', t('call.ended_unexpectedly'));
  }
}

async function negotiateWithOwner(current, offer) {
  const send = () => fetch(`/api/aide/calls/${encodeURIComponent(current.call.id)}/offer`, {
    method: 'POST', headers: { 'content-type': 'application/sdp' }, body: offer.sdp,
  });
  const response = await send();
  if (current.closed || response.status !== 403) return response;
  const error = await response.clone().json().catch(() => ({}));
  if (error.code !== 'recent_auth_required') return response;
  const password = await dlgPrompt(t('call.password_prompt'), '', { secret: true });
  if (current.closed) return response;
  if (password == null) throw new Error(t('call.cancelled_before'));
  const confirmed = await fetch('/api/auth/reauth', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password }),
  });
  if (current.closed) return response;
  if (!confirmed.ok) throw new Error(t('call.password_failed'));
  // Only this explicit pre-provider rejection is safe to resend. A timeout or
  // lost answer may have started provider work and must never be replayed here.
  return send();
}

export async function startLiveVoice() {
  if (active) return;
  // Readiness is metadata only. Microphone and provider work starts after this explicit action.
  const capability = await refreshReadiness();
  if (active || !capability?.available) return;
  const current = { closed: false, muted: false, connectedAt: null };
  active = current;
  transcripts = [];
  lastDuration = 0;
  changeState('connecting');
  try {
    current.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (current.closed) { current.stream.getTracks().forEach(track => track.stop()); return; }
    for (const track of current.stream.getTracks()) track.addEventListener?.('ended', () => {
      if (!current.closed) void finishCall(current, 'error', t('call.mic_ended'));
    });
    render();
    current.call = await json(await fetch('/api/aide/calls', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ request_id: requestId() }),
    }), t('call.unavailable_short'));
    if (current.closed) { await endRecord(current); return; }
    const peer = current.peer = new RTCPeerConnection();
    const audio = current.audio = document.createElement('audio');
    audio.autoplay = true;
    peer.ontrack = event => { audio.srcObject = event.streams[0]; };
    peer.addEventListener('connectionstatechange', () => observeConnection(current));
    current.stream.getTracks().forEach(track => peer.addTrack(track, current.stream));
    const channel = current.channel = peer.createDataChannel('oai-events');
    channel.addEventListener('message', incoming => {
      try {
        void handleProviderEvent(current, JSON.parse(incoming.data)).catch(error => {
          const detail = error?.message || t('call.partial_save_failed');
          if (active === current) changeState(state, detail);
          toast(detail, 'error');
        });
      } catch {}
    });
    channel.addEventListener('close', () => {
      if (!current.closed) void finishCall(current, 'error', t('call.session_ended'));
    });
    const offer = await peer.createOffer();
    if (current.closed) return;
    await peer.setLocalDescription(offer);
    if (current.closed) return;
    const response = await negotiateWithOwner(current, offer);
    if (current.closed) { await endRecord(current); return; }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload?.detail?.message || payload?.detail || t('call.connect_failed'));
    }
    await peer.setRemoteDescription({ type: 'answer', sdp: await response.text() });
    if (current.closed) return;
    current.connectTimer = setTimeout(() => {
      void finishCall(current, 'error', t('call.connect_timeout'));
    }, 30000);
    observeConnection(current);
  } catch (error) {
    if (current.closed) return;
    const reason = error?.name === 'NotAllowedError'
      ? t('call.mic_denied')
      : error?.name === 'NotFoundError'
        ? t('call.mic_missing')
        : error?.message || t('call.unavailable_retry');
    await finishCall(current, 'error', reason);
  }
}

export function toggleLiveVoiceMute() {
  if (!active?.stream) return;
  active.muted = !active.muted;
  active.stream.getAudioTracks().forEach(track => { track.enabled = !active.muted; });
  render();
  emitState();
}

export async function hangupLiveVoice() {
  await finishCall(active);
}

export async function initLiveVoice() {
  if (initialized) { render(); return; }
  initialized = true;
  window._hideLiveVoiceSurface = hideLiveVoiceSurface;
  for (const id of ['aide-call-open', 'live-voice-btn']) {
    document.getElementById(id)?.addEventListener('click', openLiveVoiceSurface);
  }
  document.getElementById('aide-call-workspace')?.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.defaultPrevented) {
      event.preventDefault();
      closeLiveVoiceSurface();
    }
  });
  window.addEventListener('pagehide', () => {
    if (!active) return;
    const current = active;
    lastDuration = elapsed();
    active = null;
    releaseMedia(current);
    clearInterval(tick);
    tick = null;
    changeState('ended');
    if (current.call?.id) fetch(`/api/aide/calls/${encodeURIComponent(current.call.id)}/hangup`, { method: 'POST', keepalive: true }).catch(() => {});
  });
  render();
  await refreshReadiness();
}
