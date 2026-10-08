import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createSettingsPane } from '../../static/js/settings/pane.js';

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('pane loads bind once and only the latest opening may apply a response', async () => {
  let bindings = 0;
  const requests = [];
  const rendered = [];
  const pane = createSettingsPane({
    init() { bindings += 1; },
    async load(isCurrent) {
      const request = deferred();
      requests.push(request);
      const value = await request.promise;
      if (isCurrent()) rendered.push(value);
    },
  });
  const old = pane.load();
  pane.dispose();
  const current = pane.load();
  requests[1].resolve('reopened');
  await current;
  requests[0].resolve('closed');
  await old;
  assert.deepEqual(rendered, ['reopened']);
  assert.equal(bindings, 1);
});

test('disposal releases temporary UI while the owning pane keeps its draft and save', async () => {
  const pendingSave = deferred();
  const state = { draft: 'owner edit', saved: '', menuOpen: true };
  const pane = createSettingsPane({
    load() { state.menuOpen = true; },
    dispose() { state.menuOpen = false; },
  });
  pane.load();
  const saving = pendingSave.promise.then(() => { state.saved = state.draft; });
  pane.dispose();
  assert.equal(state.menuOpen, false);
  assert.equal(state.draft, 'owner edit');
  pendingSave.resolve();
  await saving;
  pane.load();
  assert.equal(state.saved, 'owner edit');
  assert.equal(state.draft, 'owner edit');
});

test('a newer load invalidates earlier reads without closing the pane', async () => {
  const requests = [];
  const rendered = [];
  const pane = createSettingsPane({
    async load(isCurrent) {
      const request = deferred();
      requests.push(request);
      const value = await request.promise;
      if (isCurrent()) rendered.push(value);
    },
  });
  const first = pane.load();
  const retry = pane.load();
  requests[0].resolve('old');
  requests[1].resolve('retry');
  await Promise.all([first, retry]);
  assert.deepEqual(rendered, ['retry']);
});
