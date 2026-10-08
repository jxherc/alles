import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/filesphase7.js', import.meta.url), 'utf8');
const functions = ['renderAppStatus', 'renderLocationStatus', 'startIndexing', 'loadIndexStatus'].map(name => {
  const signature = source.indexOf(`function ${name}(`);
  return source.slice(source.lastIndexOf('\n', signature) + 1, source.indexOf('\n}', signature) + 2);
}).join('\n');

for (const connectionMessage of ['', 'ready']) {
  test(`an index retry clears its error and preserves connection status ${JSON.stringify(connectionMessage)}`, async () => {
    const nodes = new Map();
    const node = id => {
      if (!nodes.has(id)) nodes.set(id, { textContent: '', dataset: {}, hidden: false, disabled: false });
      return nodes.get(id);
    };
    node('files-location-status').querySelector = selector => node(selector);
    const location = { id: 'default-local', name: 'on this server', kind: 'local', access: 'managed', is_default: true };
    let attempts = 0;
    const context = {
      $: node,
      document: { activeElement: null },
      state: { locationId: location.id, indexStatus: new Map() },
      currentLocation: () => location,
      locationLabel: () => '/synthetic/files',
      indexRevision: new Map(),
      scheduleIndexPoll() {},
      fetch() {},
      request: async (_path, { method } = {}) => {
        if (method !== 'POST') return { location_id: location.id, state: 'idle', files_indexed: 0 };
        if (++attempts === 1) throw new Error('synthetic index unavailable');
        return { location_id: location.id, state: 'completed', files_indexed: 2, error: '' };
      },
    };
    vm.runInNewContext(functions, context);
    context.renderLocationStatus(connectionMessage);
    await context.startIndexing();
    assert.equal(node('files-app-status').textContent, 'indexing failed');
    assert.equal(node('.files-location-index-state').textContent, 'synthetic index unavailable');
    await context.loadIndexStatus();
    assert.equal(node('.files-location-index-state').textContent, 'synthetic index unavailable');
    await context.startIndexing();
    assert.equal(attempts, 2);
    assert.equal(node('files-app-status').textContent, '');
    assert.equal(node('.files-location-index-state').textContent, '2 files indexed');
    assert.equal(node('files-location-message').textContent, connectionMessage);
    context.renderLocationStatus();
    assert.equal(node('files-location-message').textContent, connectionMessage);
  });
}
