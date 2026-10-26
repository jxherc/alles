import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { t as i18nT, tp as i18nTp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/livevoice.js', import.meta.url), 'utf8');
const style = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');

test('live voice uses the Alles call boundary and browser WebRTC', () => {
  assert.match(source, /navigator\.mediaDevices\.getUserMedia/);
  assert.match(source, /new RTCPeerConnection\(\)/);
  assert.match(source, /\/api\/aide\/calls/);
  assert.match(source, /\/offer/);
  assert.match(source, /\/transcripts/);
  assert.match(source, /\/hangup/);
  assert.match(style, /#live-voice-btn\[hidden\]\s*\{\s*display:\s*none;/);
});

test('the browser never receives provider credentials or cancels work on hangup', () => {
  assert.doesNotMatch(source, /api\.openai\.com|Authorization|api[_-]?key/i);
  assert.doesNotMatch(source, /\/api\/chat\/stop|\/runs\/[^'"`]+\/cancel/);
  assert.match(source, /call\.desc_ended/);
});

function fixture({ available = true, browserReady = true, microphone, fetchOverride, prompt = async () => null, sessionId = 'primary' } = {}) {
  const requests = [];
  const events = [];
  const notices = [];
  const listeners = {};
  const nodes = new Map();
  const timers = new Map();
  let timerId = 0;
  let microphoneCalls = 0;
  let reloads = 0;
  const quietRefreshes = [];
  class Node {
    constructor(id) { this.id = id; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.hidden = false; this.isConnected = true; }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(key, callback) { this.listeners[key] = callback; }
    focus() { document.activeElement = this; }
    contains(node) { return node?.id?.startsWith('aide-call-') && node.id !== 'aide-call-open'; }
    querySelector(selector) { return selector.split(', ').map(item => nodes.get(item.slice(1))).find(Boolean); }
    set innerHTML(html) {
      this.html = html;
      for (const key of this.childIds || []) nodes.delete(key);
      this.childIds = [];
      for (const match of html.matchAll(/id="([^"]+)"/g)) {
        nodes.set(match[1], new Node(match[1]));
        this.childIds.push(match[1]);
      }
    }
    get innerHTML() { return this.html; }
  }
  for (const id of ['aide-call-open', 'aide-call-workspace', 'live-voice-btn']) nodes.set(id, new Node(id));
  const document = {
    activeElement: null,
    getElementById: id => nodes.get(id),
    createElement: tag => tag === 'audio' ? { pause() {} } : new Node(''),
    body: { dataset: { space: 'aide' }, appendChild(node) { nodes.set(node.id, node); } },
  };
  const track = { enabled: true, stopped: false, stop() { this.stopped = true; }, addEventListener(type, callback) { this[type] = callback; } };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  class Peer {
    static instances = [];
    constructor() { this.connectionState = 'new'; this.listeners = {}; Peer.instances.push(this); }
    addEventListener(type, callback) { this.listeners[type] = callback; }
    addTrack() {}
    createDataChannel() {
      return this.channel = { readyState: 'open', listeners: {}, sent: [], addEventListener(type, callback) { this.listeners[type] = callback; }, close() { this.readyState = 'closed'; this.listeners.close?.(); }, send(data) { this.sent.push(JSON.parse(data)); } };
    }
    async createOffer() { return { type: 'offer', sdp: 'v=0\nmock offer' }; }
    async setLocalDescription() {}
    async setRemoteDescription() { this.connectionState = 'connecting'; }
    setState(next) { this.connectionState = next; this.listeners.connectionstatechange?.(); }
    close() { this.setState('closed'); }
  }
  const response = (payload, ok = true, status = ok ? 200 : 400) => ({ ok, status, clone: () => response(payload, ok, status), json: async () => payload, text: async () => 'v=0\nmock answer' });
  const context = vm.createContext({
    t: i18nT,
    document,
    window: {
      _currentSession: { id: sessionId },
      dispatchEvent(event) { events.push(event); },
      addEventListener(type, callback) { listeners[type] = callback; },
      _reloadActiveSession() { reloads += 1; },
      _refreshAideSessionQuietly(id) { quietRefreshes.push(id); },
      _openSettings(pane) { events.push({ settings: pane }); },
    },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    navigator: browserReady ? { mediaDevices: { async getUserMedia() { microphoneCalls += 1; return microphone ? microphone(stream) : stream; } } } : {},
    RTCPeerConnection: Peer,
    fetch: async (url, options = {}) => {
      requests.push({ url, ...options });
      const override = await fetchOverride?.(url, options, response);
      if (override) return override;
      if (url === '/api/voice/realtime/status') return response({ available, model: available ? 'synthetic-realtime' : '', reason: available ? '' : 'no realtime-capable OpenAI model configured' });
      if (url === '/api/aide/calls') return response({ id: 'synthetic-call', session_id: 'primary' });
      if (url.endsWith('/transcripts')) return response({ created: true });
      if (url.includes('/preview')) return response({ privacy_class: 'local' });
      if (url === '/api/jarvis/handoffs') return response({ id: 'synthetic-run', state: 'queued' });
      return response({});
    },
    requestId: () => '00000000-0000-4000-8000-000000000000',
    toast: (...args) => notices.push(args),
    dlgPrompt: prompt,
    escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
    icon: name => `<svg data-icon="${name}"></svg>`,
    setTimeout: (callback, ms) => { timers.set(++timerId, { callback, ms }); return timerId; },
    clearTimeout: id => timers.delete(id),
    setInterval: (callback, ms) => { timers.set(++timerId, { callback, ms, interval: true }); return timerId; },
    clearInterval: id => timers.delete(id),
    Date, console,
  });
  vm.runInContext(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '') + '\n globalThis.api = { initLiveVoice, openLiveVoiceSurface, closeLiveVoiceSurface, startLiveVoice, hangupLiveVoice, toggleLiveVoiceMute, handleProviderEvent, getActive: () => active, getState: () => state };', context);
  return { ...context.api, requests, events, notices, listeners, nodes, timers, track, Peer, response, quietRefreshes, document, window: context.window,
    get microphoneCalls() { return microphoneCalls; }, get reloads() { return reloads; },
    get markup() { return nodes.get('aide-call-workspace').innerHTML; },
  };
}

test('opening and inspecting unavailable calling never requests media or creates a call', async () => {
  const f = fixture({ available: false });
  await f.initLiveVoice();
  await f.openLiveVoiceSurface();
  assert.equal(f.getState(), 'unavailable');
  assert.equal(f.microphoneCalls, 0);
  assert.ok(f.requests.every(item => item.url === '/api/voice/realtime/status'));
  assert.match(f.markup, /calling unavailable/);
  assert.doesNotMatch(f.markup, /id="aide-call-start"|id="aide-call-mute"|id="aide-call-end"/);
  assert.match(f.markup, /id="aide-call-details"[^>]+hidden/);
  assert.equal(f.nodes.get('aide-call-open').disabled, false);
});

test('configured calling checks browser support without requesting permission', async () => {
  const f = fixture({ browserReady: false });
  await f.initLiveVoice();
  assert.equal(f.getState(), 'unavailable');
  assert.match(f.markup, /secure connection and microphone support/);
  assert.equal(f.microphoneCalls, 0);
});

test('ready state waits for explicit start and actual WebRTC connectivity', async () => {
  const f = fixture();
  await f.initLiveVoice();
  await f.openLiveVoiceSurface();
  assert.equal(f.getState(), 'ready');
  assert.equal(f.microphoneCalls, 0);
  assert.match(f.markup, /id="aide-call-start"/);
  await f.startLiveVoice();
  assert.equal(f.microphoneCalls, 1);
  assert.equal(f.getState(), 'connecting');
  assert.match(f.markup, /id="aide-call-end"/);
  const peer = f.Peer.instances[0];
  peer.setState('connected');
  assert.equal(f.getState(), 'connected');
  assert.match(f.markup, /id="aide-call-time" aria-label="call duration">/);
  await f.hangupLiveVoice();
});

test('mute controls the microphone track and ending releases media without stopping tasks', async () => {
  const f = fixture();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('connected');
  f.toggleLiveVoiceMute();
  assert.equal(f.track.enabled, false);
  assert.match(f.markup, /microphone muted/);
  assert.match(f.markup, /aria-pressed="true" aria-label="unmute microphone"/);
  f.toggleLiveVoiceMute();
  assert.equal(f.track.enabled, true);
  await f.hangupLiveVoice();
  assert.equal(f.getState(), 'ended');
  assert.equal(f.track.stopped, true);
  assert.equal(f.Peer.instances[0].connectionState, 'closed');
  assert.ok(f.requests.some(item => item.url.endsWith('/hangup')));
  assert.ok(!f.requests.some(item => /cancel|chat\/stop/.test(item.url)));
  assert.equal(f.timers.size, 0);
});

test('temporary connection loss exposes reconnecting and recovers without a new call', async () => {
  const f = fixture();
  await f.startLiveVoice();
  const peer = f.Peer.instances[0];
  peer.setState('connected');
  peer.setState('disconnected');
  assert.equal(f.getState(), 'reconnecting');
  assert.match(f.markup, /id="aide-call-mute"/);
  peer.setState('connected');
  assert.equal(f.getState(), 'connected');
  assert.equal(f.requests.filter(item => item.url === '/api/aide/calls').length, 1);
  assert.ok(![...f.timers.values()].some(timer => timer.ms === 15000));
  await f.hangupLiveVoice();
});

test('connection failure releases the microphone and displays a recoverable error', async () => {
  const f = fixture();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('failed');
  assert.equal(f.getState(), 'error');
  assert.equal(f.track.stopped, true);
  assert.equal(f.getActive(), null);
  assert.match(f.markup, /ended unexpectedly/);
  assert.match(f.markup, /call again/);
});

test('permission denial never creates a provider call', async () => {
  const f = fixture({ microphone: () => { const error = new Error('denied'); error.name = 'NotAllowedError'; throw error; } });
  await f.startLiveVoice();
  assert.equal(f.getState(), 'error');
  assert.match(f.markup, /microphone access was denied/);
  assert.ok(!f.requests.some(item => item.url === '/api/aide/calls'));
});

test('cancelling pending microphone permission releases a late stream and never creates a call', async () => {
  let resolveMedia;
  const f = fixture({ microphone: stream => new Promise(resolve => { resolveMedia = () => resolve(stream); }) });
  const start = f.startLiveVoice();
  for (let i = 0; i < 12 && !resolveMedia; i++) await Promise.resolve();
  assert.equal(f.getState(), 'connecting');
  await f.hangupLiveVoice();
  resolveMedia();
  await start;
  assert.equal(f.getState(), 'ended');
  assert.equal(f.track.stopped, true);
  assert.ok(!f.requests.some(item => item.url === '/api/aide/calls'));
});

test('cancelling a pending call record ends the late record without negotiating', async () => {
  let resolveCall;
  const f = fixture({ fetchOverride: (url, _, response) => url === '/api/aide/calls'
    ? new Promise(resolve => { resolveCall = () => resolve(response({ id: 'late-call', session_id: 'primary' })); }) : null });
  const start = f.startLiveVoice();
  for (let i = 0; i < 20 && !resolveCall; i++) await Promise.resolve();
  assert.equal(typeof resolveCall, 'function');
  await f.hangupLiveVoice();
  resolveCall();
  await start;
  assert.equal(f.getState(), 'ended');
  assert.ok(f.requests.some(item => item.url === '/api/aide/calls/late-call/hangup'));
  assert.ok(!f.requests.some(item => item.url.endsWith('/offer')));
});

test('final transcripts persist and refresh the conversation without rendering provider HTML', async () => {
  const f = fixture();
  await f.startLiveVoice();
  await f.handleProviderEvent(f.getActive(), {
    type: 'response.output_audio_transcript.done', transcript: '<script>synthetic</script>', event_id: 'final-1',
  });
  const request = f.requests.find(item => item.url.endsWith('/transcripts'));
  assert.deepEqual(JSON.parse(request.body), { role: 'assistant', text: '<script>synthetic</script>', provider_event_id: 'final-1' });
  assert.equal(f.reloads, 0);
  assert.deepEqual(f.quietRefreshes, ['primary']);
  assert.match(f.markup, /&lt;script&gt;synthetic&lt;\/script&gt;/);
  assert.doesNotMatch(f.markup, /<script>/);
  await f.hangupLiveVoice();
});

test('closing the view preserves a connected call and signals the parent surface', async () => {
  const f = fixture();
  await f.openLiveVoiceSurface();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('connected');
  f.closeLiveVoiceSurface();
  assert.equal(f.getState(), 'connected');
  assert.equal(f.track.stopped, false);
  assert.equal(f.nodes.get('aide-call-workspace').hidden, true);
  assert.ok(f.events.some(event => event.type === 'aide:call-surface' && event.detail.open === false));
  await f.hangupLiveVoice();
});

test('repeated initialization does not duplicate listeners or start media', async () => {
  const f = fixture();
  await f.initLiveVoice();
  await f.initLiveVoice();
  assert.equal(f.requests.length, 1);
  assert.equal(f.microphoneCalls, 0);
});

test('final transcript does not refresh a different archived conversation or navigate', async () => {
  const f = fixture({ sessionId: 'historical-chat' });
  await f.startLiveVoice();
  await f.handleProviderEvent(f.getActive(), {
    type: 'conversation.item.input_audio_transcription.completed', transcript: 'saved to primary', event_id: 'input-final',
  });
  assert.equal(f.reloads, 0);
  assert.deepEqual(f.quietRefreshes, []);
  assert.equal(f.requests.filter(item => item.url.endsWith('/transcripts')).length, 1);
  await f.hangupLiveVoice();
});

test('final transcript quiet refresh preserves the call surface and selected app', async () => {
  const f = fixture();
  await f.openLiveVoiceSurface();
  await f.startLiveVoice();
  const surfaceEvents = f.events.filter(event => event.type === 'aide:call-surface').length;
  f.document.body.dataset.space = 'today';
  await f.handleProviderEvent(f.getActive(), {
    type: 'response.output_audio_transcript.done', transcript: 'synthetic answer', event_id: 'output-final',
  });
  assert.equal(f.document.body.dataset.space, 'today');
  assert.equal(f.events.filter(event => event.type === 'aide:call-surface').length, surfaceEvents);
  assert.equal(f.reloads, 0);
  assert.deepEqual(f.quietRefreshes, ['primary']);
  await f.hangupLiveVoice();
});

test('the persistent call control returns through the explicit open event and can end the microphone', async () => {
  const f = fixture();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('connected');
  f.document.body.dataset.space = 'today';
  assert.equal(f.nodes.get('aide-call-ongoing').hidden, false);
  assert.equal(f.nodes.get('aide-call-global-state').textContent, 'connected');
  await f.nodes.get('aide-call-return').listeners.click();
  assert.ok(f.events.some(event => event.type === 'aide:call-surface' && event.detail.open));
  await f.nodes.get('aide-call-global-end').listeners.click();
  assert.equal(f.track.stopped, true);
  assert.equal(f.nodes.get('aide-call-ongoing').hidden, true);
  assert.equal(f.getState(), 'ended');
});

test('pagehide clears active controls as well as media for a restored browser page', async () => {
  const f = fixture();
  await f.initLiveVoice();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('connected');
  f.listeners.pagehide();
  assert.equal(f.track.stopped, true);
  assert.equal(f.getState(), 'ended');
  assert.equal(f.nodes.get('aide-call-ongoing').hidden, true);
  assert.equal(f.getActive(), null);
  assert.ok(f.requests.some(item => item.url.endsWith('/hangup') && item.keepalive));
});

test('returning to a call respects the current app unsaved-edit refusal', async () => {
  const f = fixture();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('connected');
  f.document.body.dataset.space = 'docs';
  const before = f.events.length;
  f.window._navigateTo = async (view, options) => {
    assert.equal(view, 'chat');
    assert.equal(options.preserveSession, true);
    return false;
  };
  assert.equal(await f.openLiveVoiceSurface(), false);
  assert.equal(f.events.length, before);
  assert.equal(f.getState(), 'connected');
  assert.equal(f.track.stopped, false);
  assert.equal(f.document.body.dataset.space, 'docs');
});

test('accepted call return navigates before opening the call surface', async () => {
  const f = fixture();
  f.document.body.dataset.space = 'today';
  f.window._navigateTo = async () => {
    assert.ok(!f.events.some(event => event.type === 'aide:call-surface'));
    f.document.body.dataset.space = 'aide';
    return true;
  };
  await f.openLiveVoiceSurface();
  assert.ok(f.events.some(event => event.type === 'aide:call-surface' && event.detail.open));
  assert.equal(f.microphoneCalls, 0);
});

test('leaving Aide hides the live surface through later renders without ending the call', async () => {
  const f = fixture();
  await f.initLiveVoice();
  await f.openLiveVoiceSurface();
  await f.startLiveVoice();
  const peer = f.Peer.instances[0];
  peer.setState('connected');
  const before = f.events.filter(event => event.type === 'aide:call-surface').length;
  const focus = f.document.activeElement;
  f.window._hideLiveVoiceSurface();
  assert.equal(f.nodes.get('aide-call-workspace').hidden, true);
  peer.setState('disconnected');
  assert.equal(f.nodes.get('aide-call-workspace').hidden, true);
  peer.setState('connected');
  assert.equal(f.nodes.get('aide-call-workspace').hidden, true);
  assert.equal(f.events.filter(event => event.type === 'aide:call-surface').length, before);
  assert.equal(f.document.activeElement, focus);
  assert.equal(f.track.stopped, false);
  assert.equal(f.getState(), 'connected');
  assert.equal(f.requests.some(item => item.url.endsWith('/hangup')), false);
  await f.hangupLiveVoice();
});

test('an unrecovered disconnect ends the call and releases all media', async () => {
  const f = fixture();
  await f.startLiveVoice();
  const peer = f.Peer.instances[0];
  peer.setState('connected');
  peer.setState('disconnected');
  const deadline = [...f.timers.values()].find(timer => timer.ms === 15000);
  assert.ok(deadline);
  deadline.callback();
  for (let index = 0; index < 8; index++) await Promise.resolve();
  assert.equal(f.getState(), 'error');
  assert.match(f.markup, /could not recover/);
  assert.equal(f.track.stopped, true);
  assert.equal(f.getActive(), null);
  assert.equal(f.requests.filter(item => item.url === '/api/aide/calls').length, 1);
  assert.equal(f.requests.filter(item => item.url.endsWith('/hangup')).length, 1);
});

test('revoking the microphone during a call ends it without starting more work', async () => {
  const f = fixture();
  await f.startLiveVoice();
  f.Peer.instances[0].setState('connected');
  f.track.ended();
  assert.equal(f.getState(), 'error');
  assert.match(f.markup, /microphone access ended/);
  assert.equal(f.track.stopped, true);
  assert.equal(f.getActive(), null);
});

test('cancelling a pending provider offer does not accept its late answer', async () => {
  let answer;
  const f = fixture({ fetchOverride: (url, _, response) => url.endsWith('/offer')
    ? new Promise(resolve => { answer = () => resolve(response({})); }) : null });
  const start = f.startLiveVoice();
  for (let index = 0; index < 30 && !answer; index++) await Promise.resolve();
  assert.equal(typeof answer, 'function');
  await f.hangupLiveVoice();
  answer();
  await start;
  assert.equal(f.getState(), 'ended');
  assert.equal(f.Peer.instances[0].connectionState, 'closed');
  assert.equal(f.track.stopped, true);
  assert.equal(f.requests.filter(item => item.url.endsWith('/hangup')).length, 1);
});

test('a recent-owner offer challenge confirms once then retries the same SDP', async () => {
  let offers = 0, prompts = 0;
  const f = fixture({
    prompt: async () => { prompts++; return 'synthetic owner password'; },
    fetchOverride: (url, _, response) => url.endsWith('/offer') && ++offers === 1
      ? response({ code: 'recent_auth_required' }, false, 403) : null,
  });
  await f.startLiveVoice();
  assert.equal(prompts, 1);
  assert.equal(offers, 2);
  assert.equal(f.requests.filter(item => item.url === '/api/aide/calls').length, 1);
  const requests = f.requests.filter(item => item.url.endsWith('/offer'));
  assert.equal(requests[0].body, requests[1].body);
  assert.equal(f.requests.filter(item => item.url === '/api/auth/reauth').length, 1);
  assert.equal(f.getState(), 'connecting');
  await f.hangupLiveVoice();
});

test('cancelled or failed owner confirmation never resends the provider offer', async () => {
  for (const password of [null, 'wrong synthetic password']) {
    let offers = 0;
    const f = fixture({
      prompt: async () => password,
      fetchOverride: (url, _, response) => {
        if (url.endsWith('/offer')) { offers++; return response({ code: 'recent_auth_required' }, false, 403); }
        if (url === '/api/auth/reauth') return response({}, false, 401);
      },
    });
    await f.startLiveVoice();
    assert.equal(offers, 1);
    assert.equal(f.track.stopped, true);
    assert.equal(f.getActive(), null);
    assert.equal(f.getState(), 'error');
    assert.equal(f.requests.filter(item => item.url.endsWith('/hangup')).length, 1);
  }
});

test('hangup while owner confirmation is open cannot resurrect provider work', async () => {
  let resolvePassword;
  const f = fixture({
    prompt: () => new Promise(resolve => { resolvePassword = resolve; }),
    fetchOverride: (url, _, response) => url.endsWith('/offer')
      ? response({ code: 'recent_auth_required' }, false, 403) : null,
  });
  const start = f.startLiveVoice();
  for (let index = 0; index < 45 && !resolvePassword; index++) await Promise.resolve();
  assert.equal(typeof resolvePassword, 'function');
  await f.hangupLiveVoice();
  resolvePassword('synthetic password');
  await start;
  assert.equal(f.getState(), 'ended');
  assert.equal(f.requests.filter(item => item.url.endsWith('/offer')).length, 1);
  assert.equal(f.requests.some(item => item.url === '/api/auth/reauth'), false);
});
