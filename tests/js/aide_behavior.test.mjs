import assert from 'node:assert/strict';
import test from 'node:test';

const storage = new Map();
globalThis.localStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, String(value)),
};

const select = {
  value: '',
  title: '',
  attrs: {},
  setAttribute(name, value) { this.attrs[name] = value; },
  addEventListener() {},
};

globalThis.document = {
  getElementById(id) { return id === 'chat-behavior-select' ? select : null; },
};
globalThis.window = { _currentSession: null, _pendingChatBehavior: '' };

const { refreshAideBehavior, setDefaultAideBehavior } = await import('../../static/js/aidebehavior.js');

test('new conversations follow the saved default without pinning an override', () => {
  setDefaultAideBehavior('answer_only');
  refreshAideBehavior(null);
  assert.equal(select.value, '');
  assert.match(select.title, /follows settings: answer only/);
});

test('an explicit conversation override is visible', () => {
  setDefaultAideBehavior('answer_only');
  refreshAideBehavior({ chat_behavior: 'automatic_tools' });
  assert.equal(select.value, 'automatic_tools');
  assert.match(select.title, /this conversation uses automatic tools/);
});

test('unknown stored behavior fails closed to settings', () => {
  setDefaultAideBehavior('automatic_tools');
  refreshAideBehavior({ chat_behavior: 'do_everything' });
  assert.equal(select.value, '');
  assert.match(select.title, /follows settings: automatic tools/);
});
