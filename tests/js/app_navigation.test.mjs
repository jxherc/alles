import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import { resolveCompatibilityRoute } from '../../static/js/routecompat.js';
import { groupRouteFor } from '../../static/js/specialist_groups.js';
import { viewToSub } from '../../static/js/subdomain.js';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const sync = app.match(/function _syncLocalViewUrl\([^]*?\n}/)?.[0];
assert.ok(sync);

function navigate(href, identifier, { single = true, sub = '' } = {}) {
  const calls = [];
  const context = vm.createContext({
    URL, location: new URL(href), resolveCompatibilityRoute, groupRouteFor, viewToSub,
    _afterlifeFlags: { afterlife_today: true },
    singleHost: () => single, currentSub: () => sub,
    history: {
      replaceState: (_state, _title, path) => calls.push(['replace', path]),
      pushState: (_state, _title, path) => calls.push(['push', path]),
    },
  });
  vm.runInContext(sync, context);
  const route = resolveCompatibilityRoute({ view: identifier, flags: { afterlife_today: true } });
  context._syncLocalViewUrl(route, identifier, { replace: false });
  return calls;
}

test('leaving a document for Home removes its fragment and records Home', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?view=docs#notes%2Fproof', 'today'), [
    ['push', '/?view=today'],
  ]);
});

test('canonicalizing an Aide alias preserves its session fragment', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?app=aide#session-123', 'aide'), [
    ['push', '/?view=aide#session-123'],
  ]);
});

test('canonicalizing a Docs alias preserves the exact document fragment', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?app=wiki#notes%2Fproof', 'docs'), [
    ['push', '/?view=docs#notes%2Fproof'],
  ]);
});

test('same-host Aide tools remain reloadable and retain session context', () => {
  assert.deepEqual(navigate('http://aide.localhost/#session-123', 'models', { single: false, sub: 'aide' }), [
    ['push', '/?view=models#session-123'],
  ]);
});

test('canonical Docs host keeps its document fragment without a redundant view', () => {
  assert.deepEqual(navigate('http://docs.localhost/?app=wiki#proof', 'docs', { single: false, sub: 'docs' }), [
    ['push', '/#proof'],
  ]);
});

test('reselecting the current route does not add a history entry', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?view=today', 'today'), []);
});
