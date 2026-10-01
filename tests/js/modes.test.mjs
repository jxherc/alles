// unit tests for the perm-mode label + per-model reasoning-effort logic in static/js/modes.js.
// modes.js is a browser module (reads localStorage), so we shim the browser globals BEFORE
// importing it. run: node --test tests/js/modes.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

const _store = new Map();
globalThis.localStorage = {
  getItem: k => (_store.has(k) ? _store.get(k) : null),
  setItem: (k, v) => _store.set(k, String(v)),
  removeItem: k => _store.delete(k),
};
globalThis.document = {
  getElementById: () => null,
  querySelector: () => null,
  body: { classList: { toggle() {}, contains() { return false; } } },
};

const {
  permLabel,
  getPermMode,
  setPermMode,
  EFFORTS,
  getEffort,
  setEffort,
  REASONING_MODES,
  getReasoningMode,
  setReasoningMode,
  getCustomEffort,
  setCustomEffort,
} = await import('../../static/js/modes.js');

beforeEach(() => _store.clear());

test('permLabel maps each mode', () => {
  assert.equal(permLabel('plan'), 'plan');
  assert.equal(permLabel('approve'), 'ask for approval');
  assert.equal(permLabel('something-else'), 'ask for approval');  // unknown → safe default
  assert.equal(permLabel('full_access'), 'full access');
  assert.equal(permLabel('full_auto'), 'auto mode');
});

test('a fresh browser defaults to safe auto mode', () => {
  assert.equal(getPermMode(), 'full_auto');
  assert.equal(permLabel(), 'auto mode');
});

test('invalid permission values fail closed to ask for approval', () => {
  setPermMode('unrestricted');
  assert.equal(getPermMode(), 'approve');
  assert.equal(_store.get('aide-perm-mode'), 'approve');
});

test('EFFORTS is the expected ladder', () => {
  assert.deepEqual(EFFORTS, ['low', 'medium', 'high', 'xhigh', 'max', 'deep_work', 'custom']);
});

test('reasoning is independent and remembered per model', () => {
  assert.deepEqual(REASONING_MODES, ['automatic', 'on', 'off']);
  assert.equal(getReasoningMode('deepseek-v4'), 'automatic');
  setReasoningMode('off', 'deepseek-v4');
  setReasoningMode('on', 'claude-sonnet');
  assert.equal(getReasoningMode('deepseek-v4'), 'off');
  assert.equal(getReasoningMode('claude-sonnet'), 'on');
});

test('invalid reasoning fails back to automatic', () => {
  setReasoningMode('pretend', 'model');
  assert.equal(getReasoningMode('model'), 'automatic');
});

test('custom effort is bounded and remembered per model', () => {
  setCustomEffort('model-a', {
    maxTurns: 999,
    verification: 'thorough',
    delegation: 'auto',
    workflows: 'auto',
  });
  assert.deepEqual(getCustomEffort('model-a'), {
    maxTurns: 64,
    verification: 'thorough',
    delegation: 'auto',
    workflows: 'auto',
  });
  assert.equal(getCustomEffort('model-b').maxTurns, 24);
});

test('getEffort defaults to medium when nothing is stored', () => {
  assert.equal(getEffort(), 'medium');
  assert.equal(getEffort('some-model'), 'medium');
});

test('setEffort without a model sets the global last-used', () => {
  setEffort('high');
  assert.equal(getEffort(), 'high');
  assert.equal(getEffort('unseen-model'), 'high');  // unseen model falls back to last
});

test('per-model efforts are independent; explicit values are preserved', () => {
  setEffort('low', 'claude');   // claude = low
  setEffort('max', 'gpt-5');    // gpt-5 = max
  assert.equal(getEffort('claude'), 'low');   // each model keeps its own
  assert.equal(getEffort('gpt-5'), 'max');
});

test('any setEffort also updates the global last-used (drives the unseen-model fallback)', () => {
  setEffort('low', 'claude');
  setEffort('max', 'gpt-5');                   // most recent pick — even per-model — becomes last-used
  assert.equal(getEffort('unseen'), 'max');    // a model with no stored effort inherits it
  assert.equal(getEffort(), 'max');
});

test('invalid effort values reset to medium instead of reaching the runtime', () => {
  setEffort('turbo', 'gpt-5');
  assert.equal(getEffort('gpt-5'), 'medium');
  assert.equal(getEffort(), 'medium');
});
