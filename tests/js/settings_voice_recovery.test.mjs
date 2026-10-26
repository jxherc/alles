import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t as i18nT, tp as i18nTp } from '../../static/js/i18n.js';

const moduleSource = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  .replace(/^import [\s\S]*? from '[^']+';\n/gm, '')
  .replace(/^export \{[^\n]*\n/gm, '').replace(/^export /gm, '');
const source = moduleSource('../../static/js/settings/shared.js') + moduleSource('../../static/js/settings.js');
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const saved = { context_limit: 40, language: 'en', stt_provider: 'whisper_api',
  tts_provider: 'openai', tts_voice: 'shimmer', tts_speed: 2, stt_language: 'fr-FR', tts_auto_play: false };
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const elements = []; const routes = new Map(); const requests = []; const toasts = [];
  const storage = new Map(); let context;
  function element(id = '') {
    const events = new Map(); const attrs = new Map(); const classes = new Set();
    const el = {
      id, value: '', textContent: '', disabled: false, hidden: false, dataset: {}, style: {}, children: [],
      classList: { contains: key => classes.has(key), add: key => classes.add(key), remove: key => classes.delete(key),
        toggle(key, on = !classes.has(key)) { on ? classes.add(key) : classes.delete(key); } },
      setAttribute: (key, value) => attrs.set(key, String(value)), getAttribute: key => attrs.get(key),
      removeAttribute: key => attrs.delete(key), hasAttribute: key => attrs.has(key),
      addEventListener(name, fn) { events.set(name, [...(events.get(name) || []), fn]); },
      dispatchEvent(event) { return Promise.all((events.get(event.type) || []).map(fn => fn({ target: this, currentTarget: this, ...event }))); },
      async activate() { if (this.disabled || this.inert) return; const pending = this.onclick?.({ currentTarget: this }); await this.dispatchEvent({ type: 'click' }); return pending; },
      input(value) { this.value = value; return this.dispatchEvent({ type: 'input' }); },
      change(value) { this.value = value; this.dataset.value = value; return this.dispatchEvent({ type: 'change' }); },
      prepend(...children) { this.children.unshift(...children); }, append(...children) { this.children.push(...children); },
      querySelector(selector) { return this.children.find(child => selector.startsWith('.') ? child.className?.split(' ').includes(selector.slice(1)) : child.id === selector.slice(1)) || null; },
      querySelectorAll() { return []; }, focus() { context.document.activeElement = this; },
    };
    let disabled = false;
    Object.defineProperty(el, 'disabled', { get: () => disabled, set(value) {
      disabled = value;
      if (value && context?.document.activeElement === el) context.document.activeElement = null;
    } });
    elements.push(el); return el;
  }
  const get = id => elements.find(el => el.id === id) || null;
  const pane = element('s-pane-voice'); const modal = element('settings-modal'); modal.style.display = 'flex';
  for (const [id, value] of Object.entries({ 'stt-select': 'browser', 'tts-select': 'browser', 's-tts-voice': 'alloy', 's-tts-speed': '1', 's-stt-language': '', 'settings-openai-key': '', 's-mic-select': '' })) {
    const field = element(id); field.value = value; field.dataset.value = value;
  }
  element('s-tts-voice-row'); element('s-tts-enabled-toggle').setAttribute('role', 'switch'); element('s-voice-save-btn');
  let devices = async () => [];
  context = vm.createContext({ t: i18nT, tp: i18nTp,
    document: { getElementById: get, createElement: () => element(), activeElement: null,
      querySelector: selector => selector === '#settings-modal .s-pane.active' ? pane : null, querySelectorAll: () => [] },
    window: {}, localStorage: { getItem: key => storage.get(key) || '', setItem: (key, value) => storage.set(key, value) },
    navigator: { mediaDevices: { enumerateDevices: () => devices() } },
    fetch: async (url, options = {}) => { const method = options.method || 'GET'; requests.push({ url, ...options }); return (routes.get(`${method} ${url}`) || (() => response(saved)))(options); },
    toast: (message, kind) => toasts.push({ message, kind }),
    _endpointJson: async res => { const data = await res.json(); if (!res.ok) throw new Error(data?.detail || 'request failed'); return data; },
    homePane: {}, languagePane: {}, creditsPane: {}, providersPane: {}, andromedaPane: {}, connectionsPane: {}, createBackupPane: () => ({}),
    setDropdownValue: (el, value) => { if (el) { el.dataset.value = String(value); el.value = String(value); } },
    getDropdownValue: el => el?.dataset.value || '',
    populateDropdown: (el, options, value) => { el.options = options; el.dataset.value = value; },
  });
  vm.runInContext(source + `
    _activePane = 'voice';
    globalThis.subject = { load: loadVoicePane, save: saveVoiceSettings,
      leave() { _invalidateRetainedReads('voice'); _activePane = 'general'; },
      reopen() { _activePane = 'voice'; return loadVoicePane(); } };
  `, context);
  return { ...context.subject, get, pane, routes, requests, toasts, storage,
    status: () => pane.querySelector('.settings-save-state'),
    focused: () => context.document.activeElement,
    devices(fn) { devices = fn; },
  };
}

test('late Voice read preserves a language draft and initializes untouched fields', async () => {
  const h = harness(); const held = deferred(); h.routes.set('GET /api/settings', () => held.promise);
  const loading = h.load(); await h.get('s-stt-language').input('ja-JP');
  held.resolve(response(saved)); await loading;
  assert.equal(h.get('s-stt-language').value, 'ja-JP');
  assert.equal(h.get('tts-select').dataset.value, 'openai');
});

for (const [id, draft] of [['stt-select', 'local'], ['tts-select', 'browser'], ['s-tts-voice', 'echo'], ['s-tts-speed', '0.75']]) {
  test(`late Voice read preserves the ${id} choice, including edit-away-and-back`, async () => {
    const h = harness(); const held = deferred(); h.routes.set('GET /api/settings', () => held.promise);
    const loading = h.load(); await h.get(id).change('temporary'); await h.get(id).change(draft);
    held.resolve(response(saved)); await loading; assert.equal(h.get(id).dataset.value, draft);
  });
}

test('Voice reopens without losing unsaved language or write-only key drafts', async () => {
  const h = harness(); await h.load(); await h.get('s-stt-language').input('ja-JP'); await h.get('settings-openai-key').input('synthetic-key');
  h.leave(); await h.reopen(); assert.equal(h.get('s-stt-language').value, 'ja-JP'); assert.equal(h.get('settings-openai-key').value, 'synthetic-key');
});

test('a confirmed empty language clears a previous pristine value', async () => {
  const h = harness(); await h.load(); h.routes.set('GET /api/settings', () => response({ ...saved, stt_language: '' })); await h.load();
  assert.equal(h.get('s-stt-language').value, '');
});

for (const kind of ['refused', 'malformed', 'offline']) {
  test(`Voice ${kind} read keeps confirmed values, replaces saved receipt, and blocks saving defaults`, async () => {
    const h = harness(); await h.load(); await h.save();
    h.routes.set('GET /api/settings', () => kind === 'offline' ? Promise.reject(new Error('offline')) : response(kind === 'refused' ? { detail: 'refused' } : {}, kind === 'refused' ? 503 : 200));
    await h.load(); assert.equal(h.get('tts-select').dataset.value, 'openai');
    assert.equal(h.status()?.dataset.state, 'error'); assert.match(h.status()?.textContent || '', /could not load.*retry/i);
    assert.equal(h.get('s-voice-save-btn').disabled, true);
    const before = h.requests.length; await h.save(); assert.equal(h.requests.length, before);
    h.routes.set('GET /api/settings', () => response(saved)); await h.reopen(); assert.equal(h.get('s-voice-save-btn').disabled, false);
  });
}

test('first failed Voice read cannot save fabricated defaults; retry loads the real baseline', async () => {
  const h = harness(); h.routes.set('GET /api/settings', () => response({}, 503)); await h.load(); await h.save();
  assert.equal(h.requests.filter(r => r.method === 'PATCH').length, 0);
  const retry = h.get('s-voice-retry-btn'); assert.ok(retry && !retry.hidden);
  h.routes.set('GET /api/settings', () => response(saved)); await retry.activate();
  assert.equal(h.get('tts-select').dataset.value, 'openai'); assert.equal(h.get('s-voice-save-btn').disabled, false);
});

test('Save is unavailable during the initial Voice read', async () => {
  const h = harness(); const held = deferred(); h.routes.set('GET /api/settings', () => held.promise);
  const loading = h.load(); await h.save(); assert.equal(h.requests.filter(r => r.method === 'PATCH').length, 0);
  held.resolve(response(saved)); await loading;
});

test('older Voice reads cannot overwrite a newer successful opening', async () => {
  const h = harness(); const held = deferred(); h.routes.set('GET /api/settings', () => held.promise); const first = h.load();
  h.routes.set('GET /api/settings', () => response({ ...saved, stt_language: 'de-DE' })); await h.load();
  held.resolve(response(saved)); await first; assert.equal(h.get('s-stt-language').value, 'de-DE');
});

test('leaving Voice invalidates pending reads and suppresses stale failure feedback', async () => {
  for (const fail of [false, true]) {
    const h = harness(); const held = deferred(); h.routes.set('GET /api/settings', () => held.promise); const loading = h.load(); h.leave();
    const before = h.status()?.textContent; held.resolve(response(fail ? {} : saved, fail ? 503 : 200)); await loading;
    assert.equal(h.get('s-stt-language').value, ''); assert.equal(h.status()?.textContent, before); assert.equal(h.toasts.length, 0);
  }
});

test('Voice save owns one request and an acknowledgment preserves newer edits', async () => {
  const h = harness(); await h.load(); const held = deferred(); h.routes.set('PATCH /api/settings', () => held.promise);
  await h.get('s-stt-language').input('ja-JP'); const save = h.save(); const duplicate = h.save(); await settle();
  await h.get('s-stt-language').input('de-DE'); held.resolve(response({ ...saved, stt_language: 'ja-JP' })); await Promise.all([save, duplicate]);
  assert.equal(h.requests.filter(r => r.method === 'PATCH').length, 1); assert.equal(h.get('s-stt-language').value, 'de-DE');
  assert.match(h.status()?.textContent || '', /latest edits.*saving|unsaved/i);
  await h.reopen(); assert.equal(h.get('s-stt-language').value, 'de-DE');
});

test('reopening while Voice save is pending waits for that write before reading', async () => {
  const h = harness(); await h.load(); const held = deferred(); let persisted = saved;
  h.routes.set('PATCH /api/settings', async () => { await held.promise; persisted = { ...saved, stt_language: 'ja-JP' }; return response(persisted); });
  h.routes.set('GET /api/settings', () => response(persisted)); await h.get('s-stt-language').input('ja-JP');
  const save = h.save(); await settle(); h.leave(); const reopening = h.reopen(); await settle();
  assert.equal(h.requests.filter(r => !r.method).length, 1);
  held.resolve(); await Promise.all([save, reopening]); assert.equal(h.get('s-stt-language').value, 'ja-JP');
});

test('failed Voice save preserves the draft and allows an explicit retry', async () => {
  const h = harness(); await h.load(); await h.get('s-stt-language').input('ja-JP');
  h.routes.set('PATCH /api/settings', () => response({ detail: 'refused' }, 503)); await h.save();
  assert.equal(h.get('s-stt-language').value, 'ja-JP'); assert.equal(h.get('s-voice-save-btn').disabled, false);
  assert.equal(h.status()?.dataset.state, 'error');
  h.routes.set('PATCH /api/settings', () => response({ ...saved, stt_language: 'ja-JP' })); await h.save();
  assert.equal(h.status()?.dataset.state, 'saved');
});

test('microphone enumeration cannot update a closed Voice pane', async () => {
  const h = harness(); const held = deferred(); h.devices(() => held.promise); await h.load(); h.leave();
  held.resolve([{ kind: 'audioinput', deviceId: 'old-device', label: '' }]); await settle();
  assert.equal(h.get('s-mic-select').options, undefined);
});

test('microphone enumeration retains the latest local choice without requesting recording', async () => {
  const h = harness(); const held = deferred(); h.devices(() => held.promise); await h.load();
  await h.get('s-mic-select').change('new-device'); held.resolve([{ kind: 'audioinput', deviceId: 'new-device', label: 'new mic' }]); await settle();
  assert.equal(h.storage.get('alles-mic-id'), 'new-device'); assert.equal(h.get('s-mic-select').dataset.value, 'new-device');
});

test('auto-play cannot write during a failed or pending Voice read', async () => {
  const h = harness(); await h.load(); const held = deferred(); h.routes.set('GET /api/settings', () => held.promise);
  const loading = h.load(); await h.get('s-tts-enabled-toggle').activate();
  assert.equal(h.requests.filter(r => r.method === 'PATCH').length, 0);
  held.resolve(response({}, 503)); await loading; await h.get('s-tts-enabled-toggle').activate();
  assert.equal(h.requests.filter(r => r.method === 'PATCH').length, 0);
});

test('auto-play save does not mark unrelated Voice drafts saved', async () => {
  const h = harness(); await h.load(); await h.get('s-stt-language').input('ja-JP');
  h.routes.set('PATCH /api/settings', () => response({ ...saved, tts_auto_play: true }));
  await h.get('s-tts-enabled-toggle').activate(); assert.equal(h.get('s-stt-language').value, 'ja-JP');
  assert.equal(h.status()?.dataset.state, 'dirty');
  assert.deepEqual(JSON.parse(h.requests.at(-1).body), { tts_auto_play: true });
});

test('reopening waits for pending auto-play save before binding its confirmed state', async () => {
  const h = harness(); await h.load(); const held = deferred(); let persisted = saved;
  h.routes.set('PATCH /api/settings', async () => { await held.promise; persisted = { ...saved, tts_auto_play: true }; return response(persisted); });
  h.routes.set('GET /api/settings', () => response(persisted));
  const save = h.get('s-tts-enabled-toggle').activate(); await settle(); h.leave(); const reopening = h.reopen();
  held.resolve(); await Promise.all([save, reopening]);
  assert.equal(h.get('s-tts-enabled-toggle').getAttribute('aria-checked'), 'true');
});

test('a Voice save does not cancel independent microphone discovery in the same opening', async () => {
  const h = harness(); const held = deferred(); h.devices(() => held.promise); await h.load(); await h.save();
  held.resolve([{ kind: 'audioinput', deviceId: 'new-device', label: 'new mic' }]); await settle();
  assert.equal(h.get('s-mic-select').options?.[1].value, 'new-device');
});

test('microphone enumeration failure preserves the previous device choices', async () => {
  const h = harness(); h.devices(async () => [{ kind: 'audioinput', deviceId: 'known-device', label: 'known mic' }]); await h.load(); await settle();
  h.devices(async () => { throw new Error('enumeration unavailable'); }); await h.load(); await settle();
  assert.equal(h.get('s-mic-select').options?.[1]?.value, 'known-device');
});

test('keyboard Retry retains focus while pending and returns it to the loaded Voice form', async () => {
  const h = harness(); h.routes.set('GET /api/settings', () => response({}, 503)); await h.load();
  const held = deferred(); h.routes.set('GET /api/settings', () => held.promise);
  const retry = h.get('s-voice-retry-btn'); assert.ok(retry, 'failed reads need an explicit Retry action');
  retry.focus(); const loading = retry.activate();
  assert.equal(h.focused(), retry); await retry.activate();
  assert.equal(h.requests.filter(r => !r.method).length, 2);
  held.resolve(response(saved)); await loading;
  assert.equal(h.focused(), h.get('stt-select')); assert.equal(retry.hidden, true);
});

test('later Voice saves do not resubmit a previously saved write-only key', async () => {
  const h = harness(); await h.load(); await h.get('settings-openai-key').input('synthetic-key-A');
  h.routes.set('PATCH /api/settings', () => response({ ...saved, openai_api_key_configured: true }));
  await h.save(); assert.equal(JSON.parse(h.requests.at(-1).body).openai_api_key, 'synthetic-key-A');
  // The read reveals only configured status, even if another flow changed the key.
  h.routes.set('GET /api/settings', () => response({ ...saved, openai_api_key_configured: true }));
  h.leave(); await h.reopen(); await h.get('s-stt-language').input('ja-JP'); await h.save();
  assert.equal(Object.hasOwn(JSON.parse(h.requests.at(-1).body), 'openai_api_key'), false);
});

test('saving an older key never discards a newer key draft', async () => {
  const h = harness(); await h.load(); await h.get('settings-openai-key').input('synthetic-key-A');
  const held = deferred(); h.routes.set('PATCH /api/settings', () => held.promise); const saving = h.save();
  await h.get('settings-openai-key').input('synthetic-key-B');
  held.resolve(response({ ...saved, openai_api_key_configured: true })); await saving;
  assert.equal(h.get('settings-openai-key').value, 'synthetic-key-B');
  h.routes.set('PATCH /api/settings', () => response({ ...saved, openai_api_key_configured: true }));
  await h.save(); assert.equal(JSON.parse(h.requests.at(-1).body).openai_api_key, 'synthetic-key-B');
});
