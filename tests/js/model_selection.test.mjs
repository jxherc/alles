import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const store = new Map([
  ['aide-model', JSON.stringify({ endpointId: 'old', model: 'removed-model' })],
]);
globalThis.localStorage = {
  getItem: key => store.get(key) ?? null,
  setItem: (key, value) => store.set(key, String(value)),
  removeItem: key => store.delete(key),
};

class FakeElement {
  constructor() {
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
    this.style = {};
    this.textContent = '';
    this.innerHTML = '';
  }
  querySelectorAll() { return []; }
  appendChild() {}
  remove() {}
}

const elements = new Map([
  ['model-label', new FakeElement()],
  ['aide-model-choice-label', new FakeElement()],
  ['aide-model-choice-logo', new FakeElement()],
  ['live-dot', new FakeElement()],
  ['model-list', new FakeElement()],
  ['sidebar-model-list', new FakeElement()],
  ['model-modal', new FakeElement()],
  ['toast-container', new FakeElement()],
]);
globalThis.document = {
  getElementById: id => elements.get(id) || null,
  querySelectorAll: () => [],
  createElement: () => new FakeElement(),
  body: { classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } } },
};
globalThis.window = { addEventListener() {}, location: { hostname: 'aide.localhost' } };

const endpoints = [
  {
    id: 'local', name: 'Local', base_url: 'http://localhost:11434', provider: 'ollama',
    models: ['role-model', 'next-role'], image_models: [], unavailable_models: [],
  },
  {
    id: 'remote', name: 'Remote', base_url: 'https://models.test', provider: 'openai',
    models: ['session-model', 'manual-model'], image_models: [], unavailable_models: [],
  },
];
let aideRole = {
  status: 'ready',
  effective: { endpoint_id: 'local', model: 'role-model', reason: 'role_default' },
};
let modelPatchOk = true;
let modelPatchHandler = null;
const response = value => ({ ok: true, json: async () => structuredClone(value) });
globalThis.fetch = async (url, options = {}) => {
  if (url === '/api/models') return response(endpoints);
  if (url === '/api/models/roles') return response({ aide_chat: aideRole });
  if (url.startsWith('/api/sessions/') && options.method === 'PATCH') {
    if (modelPatchHandler) return modelPatchHandler(url, options);
    return { ok: modelPatchOk, json: async () => ({}) };
  }
  throw new Error(`unexpected request: ${url}`);
};

const models = await import('../../static/js/models.js');

test('fresh chat uses the effective aide role and drops a removed browser model', async () => {
  await models.loadModels();
  assert.deepEqual(models.getSelected(), { endpointId: 'local', model: 'role-model' });
  assert.equal(models.getSelectionSource(), 'role');
  assert.equal(elements.get('model-label').textContent, 'role model');
  assert.equal(elements.get('aide-model-choice-label').textContent, 'role model');
  assert.equal(store.has('aide-model'), false);
  assert.deepEqual(
    models.modelOverrideForNewSession('role-model', 'local'),
    { model: '', endpointId: '' },
  );
});

test('saved sessions restore the internal model, not only the visible label', () => {
  models.restoreSessionModel({ endpoint_id: 'remote', model: 'session-model' });
  assert.deepEqual(models.getSelected(), { endpointId: 'remote', model: 'session-model' });
  assert.equal(models.getCurrentEndpoint().id, 'remote');
  assert.equal(models.getSelectionSource(), 'session');
  assert.equal(elements.get('model-label').textContent, 'session model');
  assert.equal(elements.get('aide-model-choice-label').textContent, 'session model');
  assert.match(elements.get('aide-model-choice-logo').innerHTML, /class="brandlogo/);
});

test('an unavailable session model stays broken instead of switching providers', () => {
  models.restoreSessionModel({ endpoint_id: 'remote', model: 'removed-model' });
  assert.equal(models.getSelected(), null);
  assert.equal(models.getCurrentEndpoint(), null);
  assert.equal(models.getSelectionSource(), 'broken');
  assert.equal(elements.get('model-label').textContent, 'no model');
  assert.equal(elements.get('aide-model-choice-label').textContent, 'no model');
});

test('a missing endpoint never falls through to another provider with the same model', () => {
  models.restoreSessionModel({ endpoint_id: 'removed-provider', model: 'role-model' });
  assert.equal(models.getSelected(), null);
  assert.equal(models.getSelectionSource(), 'broken');
  assert.equal(elements.get('model-label').textContent, 'no model');
});

test('explicit chat picks remain session overrides', () => {
  models.selectModel('remote', 'manual-model');
  assert.equal(models.getSelectionSource(), 'explicit');
  assert.deepEqual(
    models.modelOverrideForNewSession('manual-model', 'remote'),
    { model: 'manual-model', endpointId: 'remote' },
  );
});

test('a failed saved-session model change restores the real model', async () => {
  window._currentSession = { id: 'saved', endpoint_id: 'remote', model: 'session-model' };
  models.restoreSessionModel(window._currentSession);
  modelPatchOk = false;
  await models.selectModel('local', 'role-model');
  assert.deepEqual(models.getSelected(), { endpointId: 'remote', model: 'session-model' });
  assert.equal(window._currentSession.endpoint_id, 'remote');
  assert.equal(window._currentSession.model, 'session-model');
  modelPatchOk = true;
  window._currentSession = null;
});

test('saved-session model changes are serialized and latest intent wins', async () => {
  window._currentSession = { id: 'saved', endpoint_id: 'remote', model: 'session-model' };
  models.restoreSessionModel(window._currentSession);
  const pending = [];
  const bodies = [];
  modelPatchHandler = (_url, options) => {
    bodies.push(JSON.parse(options.body));
    return new Promise(resolve => pending.push(resolve));
  };

  const first = models.selectModel('remote', 'manual-model');
  const second = models.selectModel('local', 'role-model');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 1);
  pending.shift()({ ok: true, json: async () => ({}) });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 1);
  pending.shift()({ ok: true, json: async () => ({}) });
  await Promise.all([first, second]);

  assert.deepEqual(bodies, [
    { model: 'manual-model', endpoint_id: 'remote' },
    { model: 'role-model', endpoint_id: 'local' },
  ]);
  assert.deepEqual(models.getSelected(), { endpointId: 'local', model: 'role-model' });
  assert.equal(window._currentSession.endpoint_id, 'local');
  assert.equal(window._currentSession.model, 'role-model');
  modelPatchHandler = null;
  window._currentSession = null;
});

test('a delayed model save cannot replace the newly opened session selection', async () => {
  const oldSession = { id: 'old-session', endpoint_id: 'remote', model: 'session-model' };
  const newSession = { id: 'new-session', endpoint_id: 'local', model: 'role-model' };
  window._currentSession = oldSession;
  models.restoreSessionModel(oldSession);
  let resolvePatch;
  modelPatchHandler = () => new Promise(resolve => { resolvePatch = resolve; });

  const pending = models.selectModel('remote', 'manual-model');
  await new Promise(resolve => setTimeout(resolve, 0));
  window._currentSession = newSession;
  models.restoreSessionModel(newSession);
  resolvePatch({ ok: true, json: async () => ({}) });
  await pending;

  assert.deepEqual(models.getSelected(), { endpointId: 'local', model: 'role-model' });
  assert.deepEqual(newSession, { id: 'new-session', endpoint_id: 'local', model: 'role-model' });
  assert.deepEqual(oldSession, { id: 'old-session', endpoint_id: 'remote', model: 'manual-model' });
  modelPatchHandler = null;
  window._currentSession = null;
});

test('a pending model save cannot block a different session', async () => {
  const oldSession = { id: 'blocked-session', endpoint_id: 'remote', model: 'session-model' };
  const newSession = { id: 'current-session', endpoint_id: 'local', model: 'role-model' };
  const pending = new Map();
  modelPatchHandler = (url, options) => new Promise(resolve => {
    pending.set(url, { resolve, body: JSON.parse(options.body) });
  });

  window._currentSession = oldSession;
  models.restoreSessionModel(oldSession);
  const oldSave = models.selectModel('remote', 'manual-model');
  await new Promise(resolve => setTimeout(resolve, 0));

  window._currentSession = newSession;
  models.restoreSessionModel(newSession);
  const newSave = models.selectModel('remote', 'session-model');
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.equal(pending.size, 2);
  pending.get('/api/sessions/current-session').resolve({ ok: true, json: async () => ({}) });
  await newSave;
  assert.deepEqual(models.getSelected(), { endpointId: 'remote', model: 'session-model' });
  pending.get('/api/sessions/blocked-session').resolve({ ok: true, json: async () => ({}) });
  await oldSave;

  assert.deepEqual(newSession, {
    id: 'current-session', endpoint_id: 'remote', model: 'session-model',
  });
  assert.deepEqual(oldSession, {
    id: 'blocked-session', endpoint_id: 'remote', model: 'manual-model',
  });
  modelPatchHandler = null;
  window._currentSession = null;
});

test('persona models display without becoming explicit session overrides', () => {
  models.selectPersonaModel('session-model');
  assert.deepEqual(models.getSelected(), { endpointId: 'remote', model: 'session-model' });
  assert.equal(models.getSelectionSource(), 'persona');
  assert.deepEqual(
    models.modelOverrideForNewSession('session-model', 'remote'),
    { model: '', endpointId: '' },
  );
});

test('refresh hook updates a role-driven new chat and safely clears a broken role', async () => {
  models.selectAideDefault();
  aideRole = {
    status: 'ready',
    effective: { endpoint_id: 'local', model: 'next-role', reason: 'role_default' },
  };
  await window._refreshAideModelDefault();
  assert.deepEqual(models.getSelected(), { endpointId: 'local', model: 'next-role' });
  assert.equal(elements.get('model-label').textContent, 'next role');

  window._currentSession = { id: 'saved', endpoint_id: 'remote', model: 'session-model' };
  aideRole = {
    status: 'ready',
    effective: { endpoint_id: 'local', model: 'role-model', reason: 'role_default' },
  };
  await window._refreshAideModelDefault();
  assert.deepEqual(models.getSelected(), { endpointId: 'remote', model: 'session-model' });

  window._currentSession = null;
  models.selectAideDefault();

  aideRole = { status: 'broken', error_code: 'model_unavailable' };
  await window._refreshAideModelDefault();
  assert.equal(models.getSelected(), null);
  assert.equal(models.getCurrentEndpoint(), null);
  assert.equal(elements.get('model-label').textContent, 'no model');
});

test('session wiring resets new chats, restores saved models, and avoids role pinning', () => {
  const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
  assert.match(source, /newChat[\s\S]*?selectAideDefault\(\)/);
  assert.match(source, /restoreSessionModel\(data\.session\)/);
  assert.match(source, /const override = modelOverrideForNewSession\(model, endpointId\)/);
  assert.match(source, /model: override\.model,[\s\S]*?endpoint_id: override\.endpointId/);
  const appSource = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  assert.match(appSource, /session\?\.model\) restoreSessionModel\(session\)/);
  assert.match(appSource, /active\?\.model\) selectPersonaModel\(active\.model\)/);
});

test('model picker uses named buttons, listbox semantics, roving keys, and modal focus return', () => {
  const source = readFileSync(new URL('../../static/js/models.js', import.meta.url), 'utf8');
  const markup = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const appSource = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  assert.match(source, /<button type="button" role="option" aria-selected=/);
  assert.match(source, /event\.key === 'ArrowDown'/);
  assert.match(source, /event\.key === 'ArrowRight'/);
  assert.match(source, /setAttribute\('aria-checked', String\(_newestOnly\)\)/);
  assert.match(markup, /id="model-modal" role="dialog" aria-modal="true"/);
  assert.match(markup, /id="model-list" role="listbox" aria-label="available models"/);
  assert.match(appSource, /createFocusBoundary\(modal,[\s\S]*onEscape: closeModelModal/);
  assert.match(appSource, /_modelModalFocusBoundary\.activate/);
});
