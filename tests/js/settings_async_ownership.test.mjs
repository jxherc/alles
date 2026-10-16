import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { eventToShortcut, isReservedShortcut } from '../../static/js/shortcuts.js';

const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8')
  .replace(/^import [\s\S]*? from '[^']+';\n/gm, '')
  .replace(/^export \{[^\n]*\n/gm, '').replace(/^export /gm, '');
const response = (data = {}, status = 200) => ({ ok: status < 400, status, json: async () => data });
const deferred = () => {
  let resolve; let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function harness() {
  const elements = new Map(); const requests = []; const toasts = []; const routes = new Map();
  const mediaCalls = [];
  const shortcutWrites = [];
  const mediaDevices = {
    enumerateDevices: async () => { mediaCalls.push('enumerate'); return [{ kind: 'audioinput', deviceId: 'fixture-mic', label: '' }]; },
    getUserMedia: async () => { mediaCalls.push('getUserMedia'); return { getTracks: () => [{ stop() {} }] }; },
  };
  function element(id) {
    const listeners = new Map(); const attrs = new Map(); const classes = new Set();
    return {
      id, value: '', disabled: false, textContent: '', dataset: {}, style: {}, children: [],
      classList: { contains: key => classes.has(key), add: key => classes.add(key), toggle(key, on = !classes.has(key)) { on ? classes.add(key) : classes.delete(key); } },
      setAttribute: (key, value) => attrs.set(key, value), getAttribute: key => attrs.get(key),
      removeAttribute: key => attrs.delete(key), hasAttribute: key => attrs.has(key),
      addEventListener(name, listener) { listeners.set(name, [...(listeners.get(name) || []), listener]); },
      dispatchEvent(event) { return Promise.all((listeners.get(event.type) || []).map(fn => fn({ target: this, currentTarget: this, ...event }))); },
      activate() { return this.dispatchEvent({ type: 'click' }); },
      input(value) { this.value = value; return this.dispatchEvent({ type: 'input' }); },
      querySelectorAll: () => [], querySelector: () => null,
      focus() {}, blur() {}, getBoundingClientRect: () => ({ left: 0, width: 200 }),
    };
  }
  const add = id => { const el = element(id); elements.set(id, el); return el; };
  const get = id => elements.get(id) || null;
  const fetch = async (url, options = {}) => {
    const method = options.method || 'GET'; requests.push({ url, ...options });
    const handler = routes.get(`${method} ${url}`);
    if (handler) return handler(options);
    if (url === '/api/settings') return response({ context_limit: 57, stream_thinking: false, artifacts_enabled: false, auto_compact: false });
    if (url === '/api/automations') return response([]);
    if (url === '/api/automations/options') return response({ triggers: [], actions: [] });
    if (url === '/api/recall/stats' || url === '/api/proactive/stats') return response({});
    throw new Error(`unexpected ${method} ${url}`);
  };
  const context = vm.createContext({
    document: { getElementById: get,
      querySelectorAll: selector => selector === '.shortcut-input' ? [...elements.values()].filter(el => el.dataset.shortcut) : [],
      querySelector: () => null, addEventListener() {}, body: element('body'), documentElement: element('html') },
    window: { addEventListener() {} }, localStorage: { getItem: () => null }, navigator: { mediaDevices }, fetch,
    homePane: {}, languagePane: {}, creditsPane: {}, providersPane: {}, connectionsPane: {}, createBackupPane: () => ({}),
    toast: (message, kind) => toasts.push({ message, kind }),
    _bindSwitch: (el, getter) => { if (el) { el.classList.toggle('on', getter()); el.setAttribute('aria-checked', String(getter())); } },
    _setSwitch: (el, value) => el?.classList.toggle('on', value),
    _endpointJson: async res => { const data = await res.json(); if (!res.ok) throw new Error(data.detail || 'request failed'); return data; },
    _esc: value => String(value), _escAttr: value => String(value),
    setDropdownValue: (el, value) => { if (el) el.dataset.value = value; },
    getDropdownValue: el => el?.dataset.value || '',
    populateDropdown: (el, options) => { if (el) el.options = options; },
    initCustomDropdowns() {}, eventToShortcut, isReservedShortcut, saveShortcuts: value => shortcutWrites.push(value),
    _getAppearance: () => ({}), isBasePreset: () => true,
    sensitiveBlurEnabled() {}, textOnlyEmojisEnabled() {}, welcomeEnabled() {}, setSensitiveBlur() {}, setTextOnlyEmojis() {}, setWelcomeEnabled() {},
    setTimeout: () => 1, clearTimeout() {}, Event: class { constructor(type) { this.type = type; } },
  });
  vm.runInContext(source + `
    globalThis.subject = { ai: loadAiPane, appearance: loadAppearancePane, rules: loadRulesPane,
      addRule: _addRule, fillRule: _fillRuleForm, resetRule: _resetRuleForm, renderRules: _renderRules,
      recall: loadRecallPane, proactive: loadProactivePane, intelligence: loadIntelligencePane, voice: loadVoicePane,
      init: _initSettings, setTemperature: _setPersonaTemp };
  `, context);
  return { ...context.subject, add, get, routes, requests, toasts, mediaCalls, shortcutWrites,
    password(suffix) {
      get('s-pw-old').input(`old-${suffix}`); get('s-pw-new').input(`long-new-password-${suffix}`); get('s-pw-new2').input(`long-new-password-${suffix}`);
    },
    passwordFields: () => ['s-pw-old', 's-pw-new', 's-pw-new2'].map(id => get(id).value),
  };
}

test('AI read refusal preserves confirmed values and reports an actionable error', async () => {
  const h = harness(); h.add('settings-context-limit'); h.add('s-thinking-toggle');
  await h.ai(); assert.equal(h.get('settings-context-limit').value, 57);
  h.routes.set('GET /api/settings', () => response({ detail: 'synthetic read refused' }, 503));
  await h.ai();
  assert.equal(h.get('settings-context-limit').value, 57);
  assert.equal(h.get('s-thinking-toggle').getAttribute('aria-checked'), 'false');
  assert.match(h.toasts.at(-1)?.message || '', /failed|refused|could not/);
});

async function passwordHarness() {
  const h = harness(); ['s-pw-save', 's-pw-old', 's-pw-new', 's-pw-new2'].forEach(h.add);
  h.appearance(); h.password('A'); return h;
}

test('pending password change owns one request and leaves newer fields intact', async () => {
  const h = await passwordHarness(); const held = deferred();
  h.routes.set('POST /api/auth/change-password', () => held.promise);
  const first = h.get('s-pw-save').activate(); const duplicate = h.get('s-pw-save').activate();
  h.password('B'); held.resolve(response({ ok: true })); await Promise.all([first, duplicate]);
  assert.equal(h.requests.filter(r => r.url === '/api/auth/change-password').length, 1);
  assert.deepEqual(h.passwordFields(), ['old-B', 'long-new-password-B', 'long-new-password-B']);
  assert.equal(h.get('s-pw-save').disabled, false);
});

test('password acknowledgment cannot clear fields edited away and back while pending', async () => {
  const h = await passwordHarness(); const held = deferred();
  h.routes.set('POST /api/auth/change-password', () => held.promise);
  const first = h.get('s-pw-save').activate(); h.password('B'); h.password('A');
  held.resolve(response({ ok: true })); await first;
  assert.deepEqual(h.passwordFields(), ['old-A', 'long-new-password-A', 'long-new-password-A']);
});

for (const kind of ['offline', 'refused', 'malformed']) {
  test(`password ${kind} preserves inputs, releases its control, and allows explicit retry`, async () => {
    const h = await passwordHarness();
    h.routes.set('POST /api/auth/change-password', () => kind === 'offline' ? Promise.reject(new Error('offline')) : response(kind === 'refused' ? { detail: 'refused' } : {}, kind === 'refused' ? 503 : 200));
    await h.get('s-pw-save').activate();
    assert.deepEqual(h.passwordFields(), ['old-A', 'long-new-password-A', 'long-new-password-A']);
    assert.equal(h.get('s-pw-save').disabled, false); assert.equal(h.toasts.at(-1).kind, 'error');
    h.routes.set('POST /api/auth/change-password', () => response({ ok: true }));
    await h.get('s-pw-save').activate(); assert.deepEqual(h.passwordFields(), ['', '', '']);
  });
}

const ruleA = { name: 'Rule A', trigger: 'daily_at', trigger_arg: '09:00', action: 'push', action_arg: 'Action A' };
async function ruleHarness() {
  const h = harness(); ['rule-name', 'rule-trigger', 'rule-trigger-arg', 'rule-action', 'rule-action-arg', 'rule-add-btn', 'rule-cancel-btn'].forEach(h.add);
  await h.rules(); h.fillRule(ruleA, null); return h;
}

test('pending rule save suppresses duplicate creates and preserves a newer draft', async () => {
  const h = await ruleHarness(); const held = deferred();
  h.routes.set('POST /api/automations', () => held.promise);
  const first = h.addRule(); const duplicate = h.addRule();
  h.get('rule-name').input('New rule B'); h.get('rule-action-arg').input('New action B');
  held.resolve(response({ id: 'created-A', ...ruleA })); await Promise.all([first, duplicate]);
  assert.equal(h.requests.filter(r => r.method === 'POST').length, 1);
  assert.equal(h.get('rule-name').value, 'New rule B'); assert.equal(h.get('rule-action-arg').value, 'New action B');
  assert.equal(h.get('rule-add-btn').disabled, false);
});

test('rule save cannot reset another edited rule with identical fields', async () => {
  const h = await ruleHarness(); const held = deferred(); h.fillRule(ruleA, 'A');
  h.routes.set('PATCH /api/automations/A', () => held.promise);
  const first = h.addRule(); h.fillRule(ruleA, 'B'); held.resolve(response({ id: 'A', ...ruleA })); await first;
  assert.equal(h.get('rule-name').value, 'Rule A'); assert.equal(h.get('rule-add-btn').textContent, 'save changes');
  h.routes.set('PATCH /api/automations/B', () => response({ id: 'B', ...ruleA })); await h.addRule();
  assert.equal(h.requests.at(-1).url, '/api/automations/B'); assert.equal(h.get('rule-name').value, '');
});

test('offline rule save retains its draft and restores retry without rejecting the event', async () => {
  const h = await ruleHarness(); h.routes.set('POST /api/automations', () => Promise.reject(new Error('offline')));
  await h.addRule(); assert.equal(h.get('rule-name').value, 'Rule A');
  assert.equal(h.get('rule-add-btn').disabled, false); assert.equal(h.toasts.at(-1).kind, 'error');
});

test('offline rule Test restores its button and explicit retry can succeed', async () => {
  const h = await ruleHarness(); const list = h.add('rules-list'); const row = h.add('fixture-row');
  const button = h.add('fixture-test'); button.dataset.act = 'test'; row.dataset.id = 'A';
  list.querySelectorAll = () => [row]; row.querySelectorAll = () => [button];
  h.routes.set('GET /api/automations', () => response([{ id: 'A', enabled: true, ...ruleA }]));
  await h.renderRules(); h.routes.set('POST /api/automations/A/test', () => Promise.reject(new Error('offline')));
  await button.activate(); assert.equal(button.disabled, false); assert.equal(h.toasts.at(-1).kind, 'error');
  h.routes.set('POST /api/automations/A/test', () => response({ ok: true }));
  await button.activate(); assert.equal(button.disabled, false); assert.equal(h.toasts.at(-1).kind, 'success');
});

test('offline Recall reindex restores its button and reports failure before retry', async () => {
  const h = harness(); const button = h.add('s-pidx-reindex'); await h.recall();
  h.routes.set('POST /api/recall/reindex', () => Promise.reject(new Error('offline')));
  await button.activate(); assert.equal(button.disabled, false); assert.equal(h.toasts.at(-1).kind, 'error');
  h.routes.set('POST /api/recall/reindex', () => response({ indexed: {} })); await button.activate(); assert.equal(button.disabled, false);
});

for (const [pane, id, path, status] of [
  ['proactive', 's-prox-run', '/api/proactive/run', 's-prox-status'],
  ['intelligence', 's-intel-insights-run', '/api/insights/run', 's-intel-status'],
  ['intelligence', 's-intel-distill-run', '/api/memory/distill/run', 's-intel-status'],
]) {
  for (const kind of ['refused', 'malformed', 'offline']) {
    test(`${id} ${kind} reports failure and restores retry without fabricated completion`, async () => {
      const h = harness(); const button = h.add(id); const message = h.add(status); await h[pane]();
      h.routes.set(`POST ${path}`, () => kind === 'offline' ? Promise.reject(new Error('offline')) : response(kind === 'refused' ? { detail: 'synthetic refused' } : {}, kind === 'refused' ? 503 : 200));
      await button.activate(); assert.equal(button.disabled, false);
      assert.match(message.textContent, /failed|refused|unavailable/); assert.doesNotMatch(message.textContent, /done|undefined/);
      h.routes.set(`POST ${path}`, () => response({ ran: true, written: 2, signals: 3, count: 2 })); await button.activate();
      assert.match(message.textContent, /done - 2/);
    });
  }
}

test('a skipped intelligence run is distinct from completed zero results', async () => {
  const h = harness(); const button = h.add('s-intel-insights-run'); const message = h.add('s-intel-status'); await h.intelligence();
  h.routes.set('POST /api/insights/run', () => response({ ran: false, reason: 'memory_off', count: 0 }));
  await button.activate(); assert.match(message.textContent, /not run.*memory/); assert.doesNotMatch(message.textContent, /done/);
});

test('opening Voice lists unnamed microphones without requesting recording permission', async () => {
  const h = harness(); const picker = h.add('s-mic-select'); await h.voice();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.mediaCalls, ['enumerate']);
  assert.equal(picker.options[1].value, 'fixture-mic');
  assert.equal(picker.options[1].label, 'microphone 1');
  assert.equal(picker.dataset.micBound, '1');
});

async function keydown(element, key, modifiers = {}) {
  const observed = { prevented: false, stopped: false };
  await element.dispatchEvent({ type: 'keydown', key, ...modifiers,
    preventDefault() { observed.prevented = true; }, stopPropagation() { observed.stopped = true; } });
  return observed;
}

for (const shiftKey of [false, true]) {
  test(`shortcut ${shiftKey ? 'Shift+Tab' : 'Tab'} keeps native focus traversal and the existing binding`, async () => {
    const h = harness(); h.add('settings-modal'); const field = h.add('shortcut-search');
    field.dataset.shortcut = 'search'; field.value = 'Ctrl+K'; h.init();
    assert.deepEqual(await keydown(field, 'Tab', { shiftKey }), { prevented: false, stopped: false });
    assert.equal(field.value, 'Ctrl+K'); assert.equal(h.shortcutWrites.length, 0);
  });
}

test('shortcut key capture and Escape clearing still save deliberate changes', async () => {
  const h = harness(); h.add('settings-modal'); const field = h.add('shortcut-search');
  field.dataset.shortcut = 'search'; h.init();
  assert.equal((await keydown(field, 'k', { ctrlKey: true })).prevented, true);
  assert.equal(field.value, 'Ctrl+K'); assert.equal(h.shortcutWrites.at(-1).search, 'Ctrl+K');
  await keydown(field, 'Escape'); assert.equal(field.value, ''); assert.equal(h.shortcutWrites.at(-1).search, '');
});

function temperatureHarness() {
  const h = harness(); ['settings-modal', 'persona-temp', 'persona-temp-pin', 'persona-temp-val'].forEach(h.add);
  h.init(); return h;
}

test('temperature slider keyboard steps snap, clamp, and announce the same manual values', async () => {
  const h = temperatureHarness(); const bar = h.get('persona-temp'); h.setTemperature(0.7);
  for (const [key, expected] of [['ArrowRight', '0.8'], ['ArrowUp', '0.9'], ['ArrowLeft', '0.8'], ['ArrowDown', '0.7'], ['Home', '0.0'], ['ArrowDown', '0.0'], ['End', '2.0'], ['ArrowUp', '2.0']]) {
    assert.equal((await keydown(bar, key)).prevented, true);
    assert.equal(bar.getAttribute('aria-valuenow'), expected);
    assert.equal(bar.getAttribute('aria-valuetext'), expected);
    assert.equal(h.get('persona-temp-val').textContent, expected);
    assert.equal(h.get('persona-temp-pin').classList.contains('on'), true);
  }
  assert.deepEqual(await keydown(bar, 'Tab'), { prevented: false, stopped: false });
});

test('temperature keyboard pins auto mode, and pointer and auto restore remain consistent', async () => {
  const h = temperatureHarness(); const bar = h.get('persona-temp');
  assert.equal(bar.getAttribute('aria-valuenow'), '0.7');
  assert.equal(bar.getAttribute('aria-valuetext'), 'auto');
  await keydown(bar, 'ArrowRight'); assert.equal(bar.classList.contains('is-auto'), false);
  assert.equal(bar.getAttribute('aria-valuenow'), '0.8');
  await bar.dispatchEvent({ type: 'pointerdown', clientX: 150, preventDefault() {} });
  assert.equal(bar.getAttribute('aria-valuenow'), '1.5');
  await keydown(bar, 'ArrowLeft'); assert.equal(bar.getAttribute('aria-valuenow'), '1.4');
  await h.get('persona-temp-pin').activate(); assert.equal(bar.classList.contains('is-auto'), true);
  assert.equal(bar.getAttribute('aria-valuetext'), 'auto');
  assert.equal(h.get('persona-temp-val').textContent, 'auto');
});
