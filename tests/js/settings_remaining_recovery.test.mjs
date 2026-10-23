import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const readModule = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  .replace(/^import [\s\S]*? from '[^']+';\n/gm, '')
  .replace(/^export \{[^\n]*\n/gm, '').replace(/^export /gm, '');
const settingsSource = readModule('../../static/js/settings.js');
const providersSource = readModule('../../static/js/settings/providers.js');
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const deferred = () => {
  let resolve; let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness(kind = 'settings') {
  const elements = new Map(); const routes = new Map(); const requests = []; const toasts = [];
  const timers = new Map(); const patches = []; const copied = []; const unhandled = [];
  let timerId = 0; let copy = async () => {};
  let context;
  function element(id) {
    const events = new Map(); const attrs = new Map(); const classes = new Set();
    let html = ''; let children = [];
    return {
      id, value: '', textContent: '', disabled: false, isConnected: true, dataset: {}, style: {},
      classList: { contains: key => classes.has(key), add: key => classes.add(key), remove: key => classes.delete(key),
        toggle(key, on = !classes.has(key)) { on ? classes.add(key) : classes.delete(key); } },
      setAttribute(key, value) { attrs.set(key, String(value)); }, getAttribute: key => attrs.get(key),
      removeAttribute: key => attrs.delete(key), hasAttribute: key => attrs.has(key),
      addEventListener(name, fn) { events.set(name, [...(events.get(name) || []), fn]); },
      removeEventListener(name, fn) { events.set(name, (events.get(name) || []).filter(other => other !== fn)); },
      dispatchEvent(event) { return Promise.all((events.get(event.type) || []).map(fn => fn({ target: this, currentTarget: this, ...event }))); },
      input(value) { this.value = value; return this.dispatchEvent({ type: 'input' }); },
      async activate() { const result = this.onclick?.call(this, { currentTarget: this }); await this.dispatchEvent({ type: 'click' }); return result; },
      querySelectorAll(selector) { return selector === '.wh-secret' ? children : []; }, querySelector: () => null,
      focus() { context.document.activeElement = this; },
      get innerHTML() { return html; },
      set innerHTML(value) {
        html = value; children.forEach(child => { child.isConnected = false; }); children = [];
        // The real renderer's copy targets are sufficient for these event tests.
        for (const match of value.matchAll(/<(code|button)\b([^>]*class="[^"]*\bwh-secret\b[^"]*"[^>]*)>([^<]*)<\/\1>/g)) {
          const child = element('webhook-copy'); child.textContent = match[3];
          const handler = match[2].match(/onclick="([^"]*)"/);
          if (handler) child.onclick = vm.runInContext(`(function(){ ${handler[1]} })`, context);
          children.push(child);
        }
      },
    };
  }
  const add = id => { const el = element(id); elements.set(id, el); return el; };
  const get = id => elements.get(id) || null;
  const fetch = async (url, options = {}) => {
    const method = options.method || 'GET'; requests.push({ url, ...options });
    const route = routes.get(`${method} ${url}`);
    if (!route) throw new Error(`unexpected ${method} ${url}`);
    return route(options);
  };
  context = vm.createContext({
    document: { getElementById: get, querySelector: () => null,
      querySelectorAll: selector => selector === '[data-token-scope].active' ? [{ dataset: { tokenScope: 'read' } }] : [],
      body: element('body'), documentElement: element('html'), activeElement: null,
    },
    window: {}, localStorage: { getItem: () => null },
    navigator: { clipboard: { writeText(value) { copied.push(value); return copy(value); } } },
    fetch, toast: (message, kind) => toasts.push({ message, kind }),
    _endpointJson: async response => { const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'request failed'); return data; },
    _patchSettings: value => { patches.push(value); return Promise.resolve(value); },
    _fetchWithRecentOwner: fetch, _getAppearance: () => ({}),
    _esc: value => String(value), _escAttr: value => String(value),
    homePane: {}, languagePane: {}, creditsPane: {}, providersPane: {}, connectionsPane: {}, createBackupPane: () => ({}),
    createSettingsPane: config => config, CSS: { escape: value => value }, loadModels() {},
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id),
  });
  vm.runInContext((kind === 'settings' ? settingsSource : providersSource) + (kind === 'settings' ? `
    globalThis.subject = { username: _loadThemeColorControls, token: generateToken, webhooks: loadWebhooks,
      personas: loadPersonas, rules() { _ruleOpts = { triggers: [], actions: [] }; return _renderRules(); },
      pane(name) { _activePane = name; } };
  ` : `globalThis.subject = { pull: pullCustomLocalModel, poll: pollLocalJob };`), context);
  add('settings-modal'); context.subject.pane?.('developer');
  return { ...context.subject, add, get, context, routes, requests, toasts, patches, copied, unhandled, timers,
    setCopy(fn) { copy = fn; },
    denyCopy() {
      // Rejection-aware thenable records a missing rejection consumer without
      // emitting a process-level unhandled rejection in the RED test run.
      copy = () => ({ then(resolve, reject) {
        const error = new Error('synthetic clipboard denied');
        if (reject) reject(error);
        else { unhandled.push(error); return { catch(fn) { unhandled.pop(); fn(error); } }; }
      } });
    },
    async runTimers() { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) await fn(); await settle(); },
  };
}

test('late initial username read preserves typing and autosaves the authored value', async () => {
  const h = harness(); const field = h.add('s-username'); const held = deferred();
  h.routes.set('GET /api/auth/me', () => held.promise); h.username();
  await field.input('new-owner-B'); held.resolve(response({ username: 'saved-owner-A' })); await settle();
  assert.equal(field.value, 'new-owner-B'); await h.runTimers();
  assert.equal(h.patches[0].username, 'new-owner-B');
});

test('username debounce captures its input instead of rereading a later DOM replacement', async () => {
  const h = harness(); const field = h.add('s-username');
  h.routes.set('GET /api/auth/me', () => response({ username: 'saved-A' })); h.username(); await settle();
  await field.input('  authored-B  '); field.value = 'unrelated DOM value'; await h.runTimers();
  assert.equal(h.patches[0].username, 'authored-B');
});

test('initial username read respects a focused draft and an edit-away-and-back revision', async () => {
  for (const edited of [false, true]) {
    const h = harness(); const field = h.add('s-username'); field.value = 'retained'; const held = deferred();
    h.routes.set('GET /api/auth/me', () => held.promise); h.username();
    if (edited) { await field.input('other'); await field.input('retained'); } else field.focus();
    held.resolve(response({ username: 'saved-A' })); await settle(); assert.equal(field.value, 'retained');
  }
});

for (const [name, data, status] of [['refused', { detail: 'refused' }, 503], ['malformed', {}, 200]]) {
  test(`username ${name} read keeps the existing value and an explicit edit still saves`, async () => {
    const h = harness(); const field = h.add('s-username'); field.value = 'retained';
    h.routes.set('GET /api/auth/me', () => response(data, status)); h.username(); await settle();
    assert.equal(field.value, 'retained'); await field.input('retry-B'); await h.runTimers();
    assert.equal(h.patches[0].username, 'retry-B');
  });
}

test('unchanged username read initializes once and rapid typing saves only the latest input', async () => {
  const h = harness(); const field = h.add('s-username');
  h.routes.set('GET /api/auth/me', () => response({ username: 'saved-A' })); h.username(); h.username(); await settle();
  assert.equal(field.value, 'saved-A'); assert.equal(h.requests.length, 1);
  await field.input('B'); await field.input('C'); await h.runTimers();
  assert.equal(h.patches.length, 1); assert.equal(h.patches[0].username, 'C');
});

function pullHarness() {
  const h = harness('providers'); h.add('s-local-custom').value = 'fixture:model-A'; h.add('s-local-pull-btn');
  h.routes.set('POST /api/local-models/download_model', () => response({ id: 'job-A', model: 'fixture:model-A', status: 'queued' }));
  h.routes.set('GET /api/local-models/jobs/job-A', () => response({ id: 'job-A', model: 'fixture:model-A', status: 'done' }));
  return h;
}

test('custom Pull releases its control after done and can submit another model', async () => {
  const h = pullHarness(); await h.pull(); await settle();
  assert.equal(h.get('s-local-pull-btn').disabled, false); assert.equal(h.get('s-local-pull-btn').textContent, 'pull');
  assert.equal(h.get('s-local-custom').value, '');
  await h.get('s-local-custom').input('fixture:model-B'); await h.pull(); await settle();
  assert.equal(h.requests.filter(r => r.method === 'POST').length, 2);
});

test('custom Pull owns one pending request and keeps a newer draft through terminal success', async () => {
  const h = pullHarness(); const held = deferred();
  h.routes.set('GET /api/local-models/jobs/job-A', () => held.promise);
  await h.pull(); await h.pull(); await h.get('s-local-custom').input('fixture:model-B');
  held.resolve(response({ id: 'job-A', model: 'fixture:model-A', status: 'done' })); await settle();
  assert.equal(h.requests.filter(r => r.method === 'POST').length, 1);
  assert.equal(h.get('s-local-custom').value, 'fixture:model-B'); assert.equal(h.get('s-local-pull-btn').disabled, false);
});

test('custom Pull preserves an edit-away-and-back draft at terminal success', async () => {
  const h = pullHarness(); const held = deferred();
  h.routes.set('GET /api/local-models/jobs/job-A', () => held.promise); await h.pull();
  await h.get('s-local-custom').input('fixture:model-B'); await h.get('s-local-custom').input('fixture:model-A');
  held.resolve(response({ id: 'job-A', model: 'fixture:model-A', status: 'done' })); await settle();
  assert.equal(h.get('s-local-custom').value, 'fixture:model-A');
});

for (const failure of ['start-refused', 'start-malformed', 'job-refused', 'job-malformed', 'job-wrong-id', 'job-unknown-status', 'job-incomplete-done', 'job-error', 'offline']) {
  test(`custom Pull ${failure} preserves its draft, reports failure, and permits retry`, async () => {
    const h = pullHarness();
    if (failure.startsWith('start')) h.routes.set('POST /api/local-models/download_model', () => response({}, failure === 'start-refused' ? 503 : 200));
    else h.routes.set('GET /api/local-models/jobs/job-A', () => failure === 'offline' ? Promise.reject(new Error('offline'))
      : response({
        'job-error': { id: 'job-A', status: 'error', error: 'synthetic job failed' },
        'job-wrong-id': { id: 'other-job', status: 'done', model: 'fixture:model-A' },
        'job-unknown-status': { id: 'job-A', status: 'unknown' },
        'job-incomplete-done': { id: 'job-A', status: 'done' },
      }[failure] || {}, failure === 'job-refused' ? 503 : 200));
    await h.pull(); await settle();
    assert.equal(h.get('s-local-pull-btn').disabled, false); assert.equal(h.get('s-local-pull-btn').textContent, 'pull');
    assert.equal(h.get('s-local-custom').value, 'fixture:model-A'); assert.equal(h.toasts.at(-1)?.kind, 'error');
    assert.equal(h.timers.size, 0);
    h.routes.set('POST /api/local-models/download_model', () => response({ id: 'job-A' }));
    h.routes.set('GET /api/local-models/jobs/job-A', () => response({ id: 'job-A', model: 'fixture:model-A', status: 'done' }));
    await h.pull(); await settle(); assert.equal(h.get('s-local-pull-btn').disabled, false);
    assert.equal(h.toasts.at(-1)?.kind, 'success');
  });
}

test('custom Pull keeps ownership through running polls and releases at the terminal poll', async () => {
  const h = pullHarness(); let polls = 0;
  h.routes.set('GET /api/local-models/jobs/job-A', () => response({ id: 'job-A', model: 'fixture:model-A', status: ++polls === 1 ? 'running' : 'done' }));
  await h.pull(); await settle(); assert.equal(h.get('s-local-pull-btn').disabled, true);
  await h.pull(); assert.equal(h.requests.filter(r => r.method === 'POST').length, 1);
  await h.runTimers(); assert.equal(h.get('s-local-pull-btn').disabled, false);
});

async function copyHarness(kind) {
  const h = harness();
  if (kind === 'token') {
    h.add('token-name').value = 'fixture'; h.add('token-add-btn'); h.add('token-reveal');
    h.routes.set('POST /api/tokens', () => response({ token: 'synthetic-token' })); await h.token();
    h.target = h.get('token-reveal');
  } else {
    const list = h.add('webhook-list');
    h.routes.set('GET /api/webhooks', () => response([{ id: 'fixture', name: 'fixture', events: [], secret: 'synthetic-webhook-secret' }]));
    await h.webhooks(); h.target = list.querySelectorAll('.wh-secret')[0];
  }
  h.toasts.length = 0; return h;
}

for (const kind of ['token', 'webhook']) {
  test(`${kind} copy denial is caught, gives recovery feedback, and permits retry`, async () => {
    const h = await copyHarness(kind); h.denyCopy(); await h.target.activate(); await settle();
    assert.equal(h.unhandled.length, 0); assert.equal(h.toasts.at(-1)?.kind, 'error');
    assert.match(h.toasts.at(-1)?.message || '', /copy.*(failed|could not)|could not.*copy/);
    assert.match(h.toasts.at(-1)?.message || '', /try again|manually|select/);
    assert.ok(h.target.textContent.startsWith('synthetic-'));
    h.setCopy(async () => {}); await h.target.activate(); await settle(); assert.equal(h.toasts.at(-1)?.kind, 'success');
  });

  test(`${kind} pending copy suppresses duplicate activation and waits before success`, async () => {
    const h = await copyHarness(kind); const held = deferred(); h.setCopy(() => held.promise);
    const first = h.target.activate(); const duplicate = h.target.activate(); await settle();
    assert.equal(h.copied.length, 1); assert.equal(h.toasts.length, 0);
    held.resolve(); await Promise.all([first, duplicate]); await settle();
    assert.equal(h.toasts.filter(item => item.kind === 'success').length, 1);
  });

  test(`${kind} late copy completion cannot announce a replacement value as copied`, async () => {
    const h = await copyHarness(kind); const held = deferred(); h.setCopy(() => held.promise);
    const pending = h.target.activate(); h.target.textContent = 'replacement-value';
    held.resolve(); await pending; await settle(); assert.equal(h.toasts.length, 0);
  });

  test(`${kind} late clipboard refusal after leaving the pane is caught without stale feedback`, async () => {
    const h = await copyHarness(kind); const held = deferred(); h.setCopy(() => held.promise);
    const pending = h.target.activate(); h.pane('general'); held.reject(new Error('synthetic clipboard denied'));
    await pending; await settle(); assert.equal(h.toasts.length, 0);
    assert.equal(h.target.hasAttribute('aria-busy'), false);
  });

  test(`${kind} unavailable clipboard reports recovery without throwing`, async () => {
    const h = await copyHarness(kind); h.context.navigator.clipboard = undefined;
    await h.target.activate(); assert.equal(h.toasts.at(-1)?.kind, 'error');
    assert.equal(h.target.hasAttribute('aria-busy'), false);
  });
}

test('malformed token receipt preserves its name and never exposes an undefined copy value', async () => {
  const h = harness(); h.add('token-name').value = 'fixture'; h.add('token-add-btn'); const reveal = h.add('token-reveal');
  reveal.textContent = 'previous-synthetic-token';
  h.routes.set('POST /api/tokens', () => response({})); await h.token();
  assert.equal(h.get('token-name').value, 'fixture'); assert.equal(reveal.textContent, 'previous-synthetic-token');
  assert.equal(h.toasts.at(-1)?.kind, 'error'); assert.equal(h.get('token-add-btn').disabled, false);
});

test('Persona renders a separate native Edit button without nesting duplicate or remove actions', async () => {
  const h = harness(); const list = h.add('persona-list'); h.pane('personas');
  h.routes.set('GET /api/personas', () => response([{ id: 'persona-A', name: 'Persona A', system_prompt: 'authored fixture' }]));
  await h.personas();
  const button = list.innerHTML.match(/<button\b[^>]*data-persona-edit[^>]*>edit<\/button>/)?.[0] || '';
  assert.match(button, /type="button"/); assert.match(button, /aria-label="edit Persona A"/);
  assert.match(button, /event\.stopPropagation\(\);window\._editPersona\('persona-A'\)/);
  assert.match(list.innerHTML, /<button[^>]*data-persona-duplicate/);
  assert.match(list.innerHTML, /<button[^>]*data-persona-remove/);
});

test('Rules renders its existing edit target as a named native button with separate actions', async () => {
  const h = harness(); const list = h.add('rules-list');
  h.routes.set('GET /api/automations', () => response([{ id: 'rule-A', name: 'Rule A', trigger: 'daily_at', trigger_arg: '09:00', action: 'push', action_arg: 'fixture', enabled: true }]));
  await h.rules();
  const button = list.innerHTML.match(/<button\b[^>]*class="rule-row-main"[^>]*>[\s\S]*?<\/button>/)?.[0] || '';
  assert.match(button, /type="button"/); assert.match(button, /aria-label="edit rule Rule A"/);
  assert.match(button, /rule-row-name/); assert.doesNotMatch(button, /data-act=/);
  for (const action of ['test', 'toggle', 'del']) assert.match(list.innerHTML, new RegExp(`<button[^>]*data-act="${action}"`));
});

test('webhook Copy is a named native button with no secret interpolated into executable code', async () => {
  const h = await copyHarness('webhook'); const markup = h.get('webhook-list').innerHTML;
  assert.match(markup, /<button type="button" class="wh-secret act-btn" aria-label="copy webhook signing key"/);
  assert.doesNotMatch(markup, /onclick="[^\"]*clipboard/);
});
