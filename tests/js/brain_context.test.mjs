import assert from 'node:assert/strict';
import test from 'node:test';

const nodes = {};
const node = id => (nodes[id] ??= { id, innerHTML: '', textContent: '', addEventListener() {}, querySelectorAll: () => [] });
globalThis.document = {
  getElementById: id => (id === 'model-label' ? null : node(id)),
  querySelectorAll: () => [],
};
globalThis.window = {};
const { loadBrainPanel } = await import('../../static/js/brain.js');

function fetcher(history) {
  return async url => {
    if (url.startsWith('/api/sessions/')) return { ok: true, json: async () => history };
    if (url === '/api/settings') return { ok: true, json: async () => ({}) };
    return { ok: true, json: async () => [] };
  };
}

test('the brain names the current task', async () => {
  window._currentSession = { id: 'task-1', name: 'fix the header', model: 'fixture-coder' };
  await loadBrainPanel(fetcher({ session: { name: 'fix the header', model: 'fixture-coder' }, messages: [] }));
  assert.match(nodes['brain-context'].innerHTML, /<span>task<\/span><strong>fix the header<\/strong>/);
  assert.doesNotMatch(nodes['brain-context'].innerHTML, /session|none/);
});

test('with no task open the line is left out instead of saying none', async () => {
  window._currentSession = null;
  await loadBrainPanel(fetcher(null));
  assert.doesNotMatch(nodes['brain-context'].innerHTML, /<span>(task|session)<\/span>/);
  assert.doesNotMatch(nodes['brain-context'].innerHTML, />none</);
  assert.match(nodes['brain-context'].innerHTML, /<span>model<\/span>/);
});
