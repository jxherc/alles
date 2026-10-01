import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/docs.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '')
  .replace(/^export /gm, '');
const hash = value => createHash('sha256').update(value).digest('hex');
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

function harness() {
  const elements = new Map();
  function element(id = '') {
    return {
      id, hidden: id === 'wiki-inline-state', value: '', textContent: '', innerHTML: '',
      style: {}, dataset: {}, children: [], disabled: false,
      classList: { toggle() {}, add() {}, remove() {} },
      setAttribute() {}, removeAttribute() {}, querySelectorAll: () => [],
      replaceChildren() { this.children = []; },
      appendChild(child) { this.children.push(child); },
      addEventListener() {}, focus() {},
    };
  }
  const get = id => {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  };
  const disk = new Map();
  const requests = [];
  const notices = [];
  const routeLocation = { pathname: '/', search: '', hash: '' };
  let stream;
  let intercept = null;
  function write(path, content) {
    const doc = { path, content, hash: hash(content), exists: true, editable: true };
    disk.set(path, doc);
    return doc;
  }
  const fetcher = async (url, options = {}) => {
    requests.push({ url, options });
    if (intercept) {
      const response = await intercept(url, options);
      if (response) return response;
    }
    let body;
    if (url === '/api/vault-md/tree') body = { items: [] };
    else if (url.startsWith('/api/vault-md/backlinks')) body = { backlinks: [] };
    else if (url.startsWith('/api/vault-md/safety/draft')) body = { draft: null };
    else if (url.startsWith('/api/vault-md/file?')) {
      const path = new URL(url, 'http://local').searchParams.get('path');
      body = disk.get(path) || { path, content: '', hash: '', exists: false };
    } else if (url === '/api/vault-md/file' && options.method === 'POST') {
      const request = JSON.parse(options.body);
      body = write(request.path, `# ${request.path}\n`);
    } else if (url === '/api/vault-md/safety/save') {
      const request = JSON.parse(options.body);
      assert.equal(request.expected_hash, disk.get(request.path).hash);
      body = write(request.path, request.content);
    } else throw new Error(`unexpected request ${url}`);
    return { ok: true, json: async () => structuredClone(body) };
  };
  const context = vm.createContext({
    fetch: fetcher, URL, URLSearchParams, TextEncoder, console,
    setTimeout: () => 1, clearTimeout() {},
    document: { getElementById: get, querySelectorAll: () => [], createElement: () => element() },
    window: {}, location: routeLocation, history: { replaceState() {} },
    replaceRouteUrl(url) {
      const route = new URL(url, 'http://local');
      routeLocation.pathname = route.pathname;
      routeLocation.search = route.search;
      routeLocation.hash = route.hash;
    },
    matchMedia: () => ({ matches: false }),
    mdToHtml: value => value, enhanceMarkdown() {}, toast: (...args) => notices.push(args),
    EventSource: class { constructor() { stream = this; } },
  });
  vm.runInContext(source + `
    _editorFactory = (_host, options) => {
      let value = options.doc;
      return { getValue: () => value, setValue: next => { value = next; }, focus() {}, destroy() {} };
    };
    globalThis.subject = {
      watch: _watch, open: openNote, save: saveCurrent,
      newDocument: async name => { promptText = async () => ({ action: 'confirm', value: name }); await newDoc(); },
      edit: async value => { if (_mode !== 'edit') await enterEdit(); setEditView('source'); $('wiki-source').value = value; sourceChanged(); },
      state: () => ({ path: _cur, hash: _doc?.hash, content: currentContent(), dirty: _dirty, mode: _mode }),
    };
  `, context);
  context.subject.watch();
  return {
    ...context.subject, get, disk, requests, notices, write,
    open: async path => {
      const opened = await context.subject.open(path);
      assert.equal(opened, true, JSON.stringify(notices));
      return opened;
    },
    intercept: value => { intercept = value; },
    event: (path, { kind = 'changed', origin = 'alles', revision = disk.get(path)?.hash || '' } = {}) => stream.onmessage({
      data: JSON.stringify({
        changed: kind === 'changed' ? [path] : [], removed: kind === 'removed' ? [path] : [],
        events: [{ path, kind, origin, hash: revision }],
      }),
    }),
    hello: () => stream.onmessage({ data: '{"hello":1}' }),
  };
}

test('own creation event does not report a conflict with the new empty draft', async () => {
  const h = harness();
  await h.newDocument('created.md');
  assert.equal(h.state().dirty, true, JSON.stringify(h.notices));
  assert.equal(h.state().content, '');
  await h.event('created.md');
  assert.equal(h.get('wiki-inline-state').hidden, true);
  assert.equal(h.state().content, '');
});

test('own save event leaves newer unsaved text alone', async () => {
  const h = harness();
  h.write('proof.md', 'original');
  await h.open('proof.md');
  await h.edit('saved text');
  assert.equal(await h.save(), true);
  await h.edit('next unsaved text');
  await h.event('proof.md');
  assert.equal(h.get('wiki-inline-state').hidden, true);
  assert.equal(h.state().content, 'next unsaved text');
  assert.equal(h.state().dirty, true);
});

test('own save event arriving before its HTTP acknowledgment waits for that write', async () => {
  const h = harness();
  h.write('proof.md', 'original');
  await h.open('proof.md');
  await h.edit('saving text');
  const written = deferred();
  const acknowledgment = deferred();
  h.intercept((url, options) => {
    if (url === '/api/vault-md/safety/save') {
      const request = JSON.parse(options.body);
      h.write(request.path, request.content);
      written.resolve();
      return acknowledgment.promise.then(() => ({ ok: true, json: async () => h.disk.get(request.path) }));
    }
  });
  const save = h.save();
  await written.promise;
  const event = h.event('proof.md');
  acknowledgment.resolve();
  await Promise.all([save, event]);
  assert.equal(h.get('wiki-inline-state').hidden, true);
  assert.equal(h.state().hash, h.disk.get('proof.md').hash);
  assert.equal(h.state().content, 'saving text');
});

test('other-tab and external edits still report a conflict without naming an editor', async () => {
  for (const origin of ['alles', 'external']) {
    const h = harness();
    h.write('proof.md', 'original');
    await h.open('proof.md');
    await h.edit('local edits');
    h.write('proof.md', 'another writer');
    await h.event('proof.md', { origin });
    assert.equal(h.get('wiki-inline-state').hidden, false);
    assert.match(h.get('wiki-inline-message').textContent, /changed.*draft/i);
    assert.doesNotMatch(h.get('wiki-inline-message').textContent, /Obsidian/);
    assert.equal(h.state().content, 'local edits');
  }
});

test('stale events and remove-then-recreate events are checked against current disk contents', async () => {
  const h = harness();
  h.write('proof.md', 'already opened version');
  await h.open('proof.md');
  await h.edit('local changes');
  await h.event('proof.md', { revision: 'older-event-hash' });
  assert.equal(h.get('wiki-inline-state').hidden, true);
  await h.event('proof.md', { kind: 'removed' });
  assert.equal(h.get('wiki-inline-state').hidden, true);
  h.disk.delete('proof.md');
  await h.event('proof.md', { kind: 'removed' });
  assert.equal(h.get('wiki-inline-state').hidden, false);
  assert.match(h.get('wiki-inline-message').textContent, /removed/i);
  assert.equal(h.state().content, 'local changes');
});

test('an event waiting for tree refresh cannot apply to a document opened afterwards', async () => {
  const h = harness();
  h.write('first.md', 'first');
  h.write('second.md', 'second');
  await h.open('first.md');
  await h.edit('first local');
  h.write('second.md', 'second external');
  const tree = deferred();
  h.intercept(url => url === '/api/vault-md/tree' ? tree.promise : undefined);
  const event = h.event('second.md', { origin: 'external' });
  await h.open('second.md');
  await h.edit('second local');
  tree.resolve();
  await event;
  assert.equal(h.get('wiki-inline-state').hidden, true);
  assert.equal(h.state().content, 'second local');
});

test('typing during an external refresh keeps the editor and its new input', async () => {
  const h = harness();
  h.write('proof.md', 'original');
  await h.open('proof.md');
  h.write('proof.md', 'external text');
  const started = deferred();
  const backlinks = deferred();
  h.intercept(url => {
    if (url.startsWith('/api/vault-md/backlinks')) {
      started.resolve();
      return backlinks.promise;
    }
  });
  const event = h.event('proof.md', { origin: 'external' });
  await started.promise;
  await h.edit('typed while refreshing');
  backlinks.resolve();
  await event;
  assert.equal(h.state().mode, 'edit');
  assert.equal(h.state().content, 'typed while refreshing');
  assert.equal(h.state().dirty, true);
  assert.equal(h.get('wiki-inline-state').hidden, false);
});

test('the latest current-document event supersedes an older disk check', async () => {
  const h = harness();
  h.write('proof.md', 'original');
  await h.open('proof.md');
  await h.edit('local text');
  const older = h.write('proof.md', 'temporarily different');
  const started = deferred();
  const check = deferred();
  h.intercept(url => {
    if (url.startsWith('/api/vault-md/file?')) {
      started.resolve();
      return check.promise.then(() => ({ ok: true, json: async () => older }));
    }
  });
  const event = h.event('proof.md');
  await started.promise;
  h.write('proof.md', 'original');
  await h.event('proof.md');
  check.resolve();
  await event;
  assert.equal(h.get('wiki-inline-state').hidden, true);
  assert.equal(h.state().content, 'local text');
});

test('stream hello reconciles missed disk changes and clean documents still refresh', async () => {
  const h = harness();
  h.write('proof.md', 'before connection');
  await h.open('proof.md');
  h.write('proof.md', 'after connection');
  await h.hello();
  assert.equal(h.state().content, 'after connection');
  assert.equal(h.get('wiki-save-state').textContent, 'updated from disk');
  assert.ok(h.requests.some(request => request.url === '/api/vault-md/tree'));
  h.write('proof.md', 'changed again');
  await h.event('proof.md', { origin: 'external' });
  assert.equal(h.state().content, 'changed again');
  assert.equal(h.state().dirty, false);
});
