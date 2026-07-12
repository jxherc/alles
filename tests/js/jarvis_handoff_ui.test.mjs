import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.window = {};
globalThis.document = {};
globalThis.localStorage = {
  getItem() { return null; },
  setItem() {},
  removeItem() {},
};

const {
  explicitHandoffModel,
  explicitHandoffSelection,
  handoffActionForState,
} = await import('../../static/js/jarvishandoff.js');

test('active handoffs can cancel', () => {
  assert.equal(handoffActionForState('queued'), 'cancel');
  assert.equal(handoffActionForState('running'), 'cancel');
});

test('safe terminal handoffs can retry while uncertain work cannot', () => {
  assert.equal(handoffActionForState('failed'), 'retry');
  assert.equal(handoffActionForState('interrupted'), 'retry');
  assert.equal(handoffActionForState('cancelled'), 'retry');
  assert.equal(handoffActionForState('uncertain'), '');
  assert.equal(handoffActionForState('succeeded'), '');
});

test('handoffs send only an explicit conversation model override', () => {
  const selection = { endpointId: 'local', model: 'picked-model' };
  assert.equal(explicitHandoffModel(selection, 'explicit'), 'picked-model');
  assert.equal(explicitHandoffModel(selection, 'session'), 'picked-model');
  assert.equal(explicitHandoffModel(selection, 'role'), '');
  assert.equal(explicitHandoffModel(selection, 'persona'), '');
  assert.equal(explicitHandoffModel(null, 'explicit'), '');
});

test('explicit handoffs keep the endpoint and model together', () => {
  assert.deepEqual(
    explicitHandoffSelection({ endpointId: 'endpoint-2', model: 'shared-model' }, 'explicit'),
    { endpoint_id: 'endpoint-2', model: 'shared-model' },
  );
  assert.deepEqual(
    explicitHandoffSelection({ endpointId: 'endpoint-1', model: 'role-model' }, 'role'),
    { endpoint_id: '', model: '' },
  );
});

test('the same explicit override is used for preview and handoff creation', () => {
  const source = readFileSync(new URL('../../static/js/jarvishandoff.js', import.meta.url), 'utf8');
  assert.match(source, /preview\(sessionId, modelOverride\)/);
  assert.match(source, /params\.set\('endpoint_override', override\.endpoint_id\)/);
  assert.match(source, /endpoint_override: modelOverride\.endpoint_id/);
  assert.match(source, /model_override: modelOverride\.model/);
});
