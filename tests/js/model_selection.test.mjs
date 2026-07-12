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
}

const elements = new Map([
  ['model-label', new FakeElement()],
  ['live-dot', new FakeElement()],
  ['model-list', new FakeElement()],
  ['sidebar-model-list', new FakeElement()],
  ['model-modal', new FakeElement()],
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
const response = value => ({ ok: true, json: async () => structuredClone(value) });
globalThis.fetch = async url => {
  if (url === '/api/models') return response(endpoints);
  if (url === '/api/models/roles') return response({ aide_chat: aideRole });
  throw new Error(`unexpected request: ${url}`);
};

const models = await import('../../static/js/models.js');

test('fresh chat uses the effective aide role and drops a removed browser model', async () => {
  await models.loadModels();
  assert.deepEqual(models.getSelected(), { endpointId: 'local', model: 'role-model' });
  assert.equal(models.getSelectionSource(), 'role');
  assert.equal(elements.get('model-label').textContent, 'role model');
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
});

test('an unavailable session model stays broken instead of switching providers', () => {
  models.restoreSessionModel({ endpoint_id: 'remote', model: 'removed-model' });
  assert.equal(models.getSelected(), null);
  assert.equal(models.getCurrentEndpoint(), null);
  assert.equal(models.getSelectionSource(), 'broken');
  assert.equal(elements.get('model-label').textContent, 'no model');
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
