import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { sourcesHtml } from '../../static/js/runs.js';
import { readRecordTarget } from '../../static/js/recordlinks.js';

const source = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const reply = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const article = (patch = {}) => ({
  id: 'article-1', position: 0.2, position_revision: '', content_hash: 'a'.repeat(64),
  text: 'synthetic saved text', title: 'synthetic article', read: false, ...patch,
});
const copy = value => JSON.parse(JSON.stringify(value));

// This exercises real open/cache/position controllers and recovery handlers;
// DOM doubles below do not claim browser layout, focus or scroll-event proof.
function harness() {
  const nodes = new Map(), writes = [], notices = [], timers = new Map();
  let context, serial = 0, timerId = 0, intercept;
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      id, hidden: false, disabled: false, textContent: '', innerHTML: '', scrollTop: 0,
      scrollHeight: 1200, clientHeight: 200, tabIndex: -1,
      classList: { toggle() {}, add() {}, remove() {} },
      getClientRects: () => [{}], setAttribute() {}, addEventListener() {}, removeEventListener() {},
      prepend() {}, append() {}, before() {}, remove() {},
      querySelector: selector => selector === '.read-source-notice' ? null : node(selector.replace(/^#/, '')),
      focus() { context.document.activeElement = this; },
    });
    return nodes.get(id);
  };
  context = vm.createContext({
    URL, URLSearchParams, console,
    document: { getElementById: node, createElement: () => node('bar'), body: node('document-body'),
      addEventListener() {}, removeEventListener() {} },
    window: { addEventListener() {}, removeEventListener() {} },
    ResizeObserver: class { observe() {} disconnect() {} },
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; }, clearTimeout: id => timers.delete(id),
    requestId: () => `00000000-0000-4000-8000-${String(++serial).padStart(12, '0')}`,
    toast: (...args) => notices.push(args),
    fetch: async (url, options = {}) => {
      if (options.method === 'PATCH') writes.push({ url, patch: JSON.parse(options.body) });
      return intercept(url, options);
    },
  });
  vm.runInContext(source('reading_place') + '\n' + source('read') + `
    _render = () => {
      _detachPlace();
      if (_open) _attachReadingPlace($('read-body'), _open);
    };
    globalThis.subject = {
      open: openReadItem,
      current: () => _open,
      place: id => _places.get(id)?.place,
      rerender: () => _render(),
      leave: () => { ++_openGeneration; _detachPlace(); _open = null; },
      replace: item => {
        const place = readingPlace(item, patch => _writeReadItem(item.id, patch, true));
        _places.set(item.id, { hash: item.content_hash, place });
        return place;
      },
    };
  `, context);
  const h = { ...context.subject, node, writes, notices, timers,
    intercept: fn => { intercept = fn; },
  };
  intercept = (_url, options) => reply(options.method === 'PATCH'
    ? { ...article(), ...JSON.parse(options.body) } : article());
  return h;
}

async function blocked(h, status = 409, expectedHash = '') {
  assert.equal(await h.open('article-1', () => true, expectedHash), true);
  const place = h.place('article-1');
  h.intercept(() => reply({ detail: 'synthetic changed reading place' }, status));
  place.set(0.6);
  assert.equal(await place.flush(), false);
  assert.equal(place.blocked, true);
  assert.equal(place.unsaved, true);
  return place;
}

test('same-text conflict recovery accepts the fresh revision and resumes real position writes', async () => {
  const h = harness(), previous = await blocked(h);
  const fresh = article({ position: 0.35, position_revision: '00000000-0000-4000-8000-000000000099:1' });
  h.intercept((_url, options) => reply(options.method === 'PATCH'
    ? { ...fresh, ...JSON.parse(options.body) } : { ...fresh }));
  assert.equal(h.node('read-position-retry').textContent, 'reopen article');
  assert.equal(await h.node('read-position-retry').onclick(), true);
  const current = h.place(fresh.id);
  assert.notEqual(current, previous);
  assert.equal(current.value, fresh.position);
  assert.equal(current.blocked, false);
  assert.equal(h.node('read-position-retry').hidden, true);
  assert.equal(h.writes.length, 1, 'reopening must not write or mark read');
  current.set(0.75);
  assert.equal(await current.drain(), true);
  assert.equal(h.writes.length, 2);
  assert.equal(h.writes[1].url, '/api/read/article-1');
  assert.equal(h.writes[1].patch.position, 0.75);
  assert.equal(h.writes[1].patch.position_base, fresh.position_revision);
  assert.equal(h.writes[1].patch.content_hash, fresh.content_hash);
  assert.notEqual(h.writes[1].patch.position_revision.split(':')[0], h.writes[0].patch.position_revision.split(':')[0]);
  assert.equal('read' in h.writes[1].patch, false);
});

test('a newer same-article draft survives a delayed reopen and remains explicitly recoverable', async () => {
  const h = harness(), previous = await blocked(h), held = deferred();
  h.intercept(() => held.promise);
  const opening = h.node('read-position-retry').onclick();
  previous.set(0.8);
  held.resolve(reply(article({ position: 0.35 })));
  await opening;
  assert.equal(h.place('article-1'), previous);
  assert.equal(previous.value, 0.8);
  assert.equal(previous.blocked, true);
  assert.equal(h.writes.length, 1);
  h.intercept(() => reply(article({ position: 0.35 })));
  await h.node('read-position-retry').onclick();
  assert.notEqual(h.place('article-1'), previous);
  assert.equal(h.place('article-1').value, 0.35);
});

test('a newer controller for the same article survives the old reopen response', async () => {
  const h = harness(); await blocked(h);
  const held = deferred(); h.intercept(() => held.promise);
  const opening = h.open('article-1');
  const replacement = h.replace(article({ position: 0.9, position_revision: 'newer-owner:1' }));
  held.resolve(reply(article({ position: 0.35 })));
  await opening;
  assert.equal(h.place('article-1'), replacement);
  assert.equal(replacement.value, 0.9);
});

test('rerendering alone does not dismiss the conflict', async () => {
  const h = harness(), previous = await blocked(h);
  h.rerender();
  assert.equal(h.place('article-1'), previous);
  assert.equal(previous.blocked, true);
  assert.equal(h.node('read-position-retry').textContent, 'reopen article');
  assert.equal(h.writes.length, 1);
});

test('late reopen success or failure cannot replace a newer article', async () => {
  for (const fails of [false, true]) {
    const h = harness(), previous = await blocked(h), held = deferred();
    const other = article({ id: 'article-2', position: 0.9 });
    h.intercept(url => url.endsWith('/article-1') ? held.promise : reply({ ...other }));
    const opening = h.node('read-position-retry').onclick();
    await h.open(other.id);
    const owner = h.current(), place = h.place(other.id);
    if (fails) held.reject(new Error('synthetic unavailable'));
    else held.resolve(reply(article({ position: 0.35 })));
    assert.equal(await opening, false);
    assert.equal(h.current(), owner);
    assert.equal(h.place(other.id), place);
    assert.equal(h.place('article-1'), previous);
    assert.equal(h.notices.length, 0);
  }
});

test('navigation away or an expired caller leaves blocked recovery intact', async () => {
  for (const leave of [false, true]) {
    const h = harness(), previous = await blocked(h), held = deferred();
    let current = true;
    h.intercept(() => held.promise);
    const opening = h.open('article-1', () => current);
    if (leave) h.leave(); else current = false;
    held.resolve(reply(article({ position: 0.35 })));
    assert.equal(await opening, false);
    assert.equal(h.place('article-1'), previous);
    assert.equal(previous.blocked, true);
  }
});

test('failed or wrong-article reopen never clears the blocked place', async () => {
  for (const response of [reply({}, 404), reply({}, 503), reply(article({ id: 'article-2' }))]) {
    const h = harness(), previous = await blocked(h);
    h.intercept(() => response);
    assert.equal(await h.open('article-1'), false);
    assert.equal(h.place('article-1'), previous);
    assert.equal(previous.blocked, true);
    assert.equal(h.place('article-2'), undefined);
    assert.equal(h.writes.length, 1);
  }
});

test('an ordinary unsaved or uncertain position keeps its controller and retry identity', async () => {
  for (const uncertain of [false, true]) {
    const h = harness(); await h.open('article-1');
    const previous = h.place('article-1'); previous.set(0.6);
    if (uncertain) {
      h.intercept(() => { throw new TypeError('synthetic lost reply'); });
      assert.equal(await previous.flush(), false);
    }
    h.intercept((_url, options) => reply(options.method === 'PATCH'
      ? { ...article(), ...JSON.parse(options.body) } : article({ position: 0.35 })));
    await h.open('article-1');
    assert.equal(h.place('article-1'), previous);
    assert.equal(previous.value, 0.6);
    assert.equal(await previous.drain(), true);
    if (uncertain) assert.deepEqual(h.writes[1], h.writes[0]);
  }
});

test('pending writes and a conflict learned during the fetch cannot be discarded by reopen', async () => {
  for (const conflictBeforeReply of [false, true]) {
    const h = harness(); await h.open('article-1');
    const previous = h.place('article-1'), write = deferred(), get = deferred();
    h.intercept((_url, options) => options.method === 'PATCH' ? write.promise : get.promise);
    previous.set(0.6); const saving = previous.flush();
    const opening = h.open('article-1');
    if (conflictBeforeReply) { write.resolve(reply({}, 409)); await saving; }
    get.resolve(reply(article({ position: 0.35 }))); await opening;
    assert.equal(h.place('article-1'), previous);
    assert.equal(previous.value, 0.6);
    if (!conflictBeforeReply) { write.resolve(reply({}, 409)); await saving; }
    assert.equal(previous.blocked, true);
  }
});

test('a newer place saved during a delayed GET keeps its controller and value', async () => {
  const h = harness(); await h.open('article-1');
  const previous = h.place('article-1'), get = deferred();
  h.intercept((_url, options) => options.method === 'PATCH'
    ? reply({ ...article(), ...JSON.parse(options.body) }) : get.promise);
  const opening = h.open('article-1');
  previous.set(0.8);
  assert.equal(await previous.drain(), true);
  get.resolve(reply(article())); await opening;
  assert.equal(h.place('article-1'), previous);
  assert.equal(previous.value, 0.8);
  assert.equal(previous.unsaved, false);
});

test('changed text still creates a new controller with the fresh content hash', async () => {
  const h = harness(), previous = await blocked(h);
  const fresh = article({ content_hash: 'b'.repeat(64), position: 0 });
  h.intercept(() => reply({ ...fresh }));
  await h.open(fresh.id);
  assert.notEqual(h.place(fresh.id), previous);
  assert.equal(h.place(fresh.id).value, 0);
  assert.equal(h.current().content_hash, fresh.content_hash);
});

test('source href and record parser carry the expected version through open and conflict recovery', async () => {
  for (const currentHash of ['a'.repeat(64), 'b'.repeat(64)]) {
    const h = harness(), expectedHash = 'a'.repeat(64);
    const html = sourcesHtml({ sources: [{ kind: 'read', ref: 'article-1', hash: expectedHash }],
      outcomes: {}, history_complete: true });
    const href = html.match(/href="([^"]+)"/)[1].replaceAll('&amp;', '&');
    const target = readRecordTarget(new URL(href, 'http://synthetic.invalid/'));
    h.intercept(() => reply(article({ content_hash: currentHash })));
    await h.open(target.id, () => true, target.hash || '');
    assert.equal(h.current().sourceHash, expectedHash);
    assert.equal(h.current().sourceChanged, expectedHash !== currentHash);
    h.intercept(() => reply({}, 409));
    const previous = h.place(target.id); previous.set(0.6); await previous.flush();
    h.intercept(() => reply(article({ content_hash: currentHash, position: 0.35 })));
    await h.node('read-position-retry').onclick();
    assert.equal(h.current().sourceHash, expectedHash);
    assert.equal(h.current().sourceChanged, expectedHash !== currentHash);
    assert.notEqual(h.place(target.id), previous);
  }
});

test('ordinary live opening does not claim a changed source', async () => {
  const h = harness();
  await h.open('article-1');
  assert.deepEqual(copy({ hash: h.current().sourceHash, changed: h.current().sourceChanged }), {
    hash: '', changed: false,
  });
  assert.equal(h.writes.length, 0);
});
