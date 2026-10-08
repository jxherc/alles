import assert from 'node:assert/strict';
import { test } from 'node:test';

function browser({ index, state, navigation = true }) {
  const calls = [];
  let currentIndex = index;
  globalThis.window = navigation
    ? { navigation: { currentEntry: { get index() { return currentIndex; } } } }
    : { navigation: undefined };
  globalThis.location = new URL('http://127.0.0.1/?view=docs');
  globalThis.history = {
    state,
    replaceState(next, _title, url) {
      this.state = next;
      globalThis.location = new URL(url, globalThis.location);
      calls.push(['replace', url]);
    },
    pushState(next, _title, url) {
      this.state = next;
      globalThis.location = new URL(url, globalThis.location);
      currentIndex += 1;
      calls.push(['push', url]);
    },
    go(delta) { calls.push(['go', delta]); },
  };
  return {
    calls,
    enterUnmarkedForward() {
      currentIndex += 1;
      history.state = null;
      globalThis.location = new URL('/?view=journal', globalThis.location);
    },
  };
}

test('an unmarked forward entry uses the real browser index to reverse a denied route', async () => {
  const { calls, enterUnmarkedForward } = browser({ index: 2, state: { other: 'kept' } });
  const route = await import('../../static/js/route_history.js?native-index');
  assert.equal(history.state.__allesRoutePosition, 2);
  assert.equal(history.state.other, 'kept');
  enterUnmarkedForward();
  const target = route.targetRoutePosition(history.state);
  assert.equal(target, 3);
  assert.equal(route.restoreDeniedRoute(target), true);
  assert.deepEqual(calls.at(-1), ['go', -1]);
});

test('without a browser index, an unmarked entry keeps the edited view and URL together', async () => {
  const { calls, enterUnmarkedForward } = browser({
    index: 7, state: { __allesRoutePosition: 7, other: 'kept' }, navigation: false,
  });
  const route = await import('../../static/js/route_history.js?no-index');
  enterUnmarkedForward();
  assert.equal(route.targetRoutePosition(history.state), null);
  assert.equal(route.restoreDeniedRoute(null), false);
  assert.equal(location.pathname + location.search, '/?view=docs');
  assert.equal(route.visibleRouteUrl(), '/?view=docs');
  assert.deepEqual(calls.at(-1), ['replace', '/?view=docs']);
  route.pushRouteUrl('/?view=journal');
  assert.equal(history.state.__allesRoutePosition, 8);
  assert.equal(route.visibleRouteUrl(), '/?view=journal');
});
