import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/docs.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const hash = content => createHash('sha256').update(content).digest('hex');
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const files = new Map();
  const drafts = new Map();
  const storage = new Map();
  const writes = [];
  let barrier = null;
  return {
    files, drafts, storage, writes,
    seed(path, content) {
      files.set(path, { path, content, hash: hash(content), exists: true, editable: true });
    },
    holdNextDraft() {
      let release;
      barrier = new Promise(resolve => { release = resolve; });
      return release;
    },
    async fetch(url, options = {}) {
      const parsed = new URL(url, 'http://fixture');
      const path = parsed.searchParams.get('path');
      const body = options.body ? JSON.parse(options.body) : null;
      let response = {};
      if (options.method) writes.push({ url, method: options.method, body, keepalive: !!options.keepalive });
      if (parsed.pathname === '/api/vault-md/file') response = files.get(path);
      else if (parsed.pathname === '/api/vault-md/safety/draft') {
        if (options.method === 'PUT') {
          const held = barrier;
          barrier = null;
          if (held) await held;
          const existing = drafts.get(body.path);
          if (!existing || existing.write_session !== body.write_session || existing.write_revision <= body.write_revision) {
            drafts.set(body.path, { ...body, draft_hash: hash(body.content), updated_at: 'fixture' });
          }
          // The real PUT response deliberately omits content; GET includes it.
          const { content, ...metadata } = drafts.get(body.path);
          response = metadata;
        } else if (options.method === 'DELETE') {
          assert.equal(parsed.searchParams.get('expected_hash'), drafts.get(path)?.draft_hash);
          drafts.delete(path);
        } else response = { draft: drafts.get(path) || null };
      } else if (parsed.pathname === '/api/vault-md/safety/save') {
        assert.equal(body.expected_hash, files.get(body.path).hash);
        response = { ...files.get(body.path), content: body.content, hash: hash(body.content) };
        files.set(body.path, response);
        if (drafts.get(body.path)?.draft_hash === response.hash) drafts.delete(body.path);
      } else if (parsed.pathname === '/api/vault-md/tree') response = { items: [] };
      else if (parsed.pathname === '/api/vault-md/backlinks') response = { backlinks: [] };
      else throw new Error(`unexpected request: ${url}`);
      return { ok: true, json: async () => structuredClone(response) };
    },
  };
}

function harness(server) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) {
      const classes = new Set();
      const attributes = new Map();
      elements.set(id, {
        id, value: '', textContent: '', hidden: false, disabled: false, dataset: {}, style: {}, children: [],
        classList: {
          toggle(name, enabled = !classes.has(name)) { enabled ? classes.add(name) : classes.delete(name); },
          add: (...names) => names.forEach(name => classes.add(name)),
          remove: (...names) => names.forEach(name => classes.delete(name)),
          contains: name => classes.has(name),
        },
        setAttribute: (name, value) => attributes.set(name, value),
        getAttribute: name => attributes.get(name), removeAttribute: name => attributes.delete(name),
        querySelectorAll: () => [], addEventListener() {}, replaceChildren() { this.children = []; },
        appendChild(child) { this.children.push(child); },
        focus() { document.activeElement = this; },
      });
    }
    return elements.get(id);
  };
  const document = { getElementById: get, querySelectorAll: () => [], createElement: () => get(Symbol()), body: {}, activeElement: null };
  const context = vm.createContext({ t, tp,
    document, fetch: server.fetch, URL, URLSearchParams, TextEncoder,
    setTimeout: () => 1, clearTimeout() {}, window: {}, location: new URL('http://fixture/'),
    matchMedia: () => ({ matches: false }), mdToHtml: value => value, enhanceMarkdown() {},
    readRecordTarget: () => null, replaceRouteUrl() {}, toast() {},
    localStorage: {
      getItem: key => server.storage.get(key), setItem: (key, value) => server.storage.set(key, value),
      removeItem: key => server.storage.delete(key),
    },
  });
  vm.runInContext(source + `
    _editorFactory = (_host, options) => {
      let value = options.doc;
      return { getValue: () => value, setValue: next => { value = next; options.onChange(next); }, focus() {}, destroy() {} };
    };
    globalThis.subject = {
      open: openNote, enter: enterEdit, done: exitEdit, flush: flushDraft, pagehide: persistDraftOnPageHide, save: saveCurrent,
      type: value => { setEditView('source'); $('wiki-source').value = value; sourceChanged(); },
      settled: () => _documentWrites,
      state: () => ({ path: _cur, content: currentContent(), draft: _draft, dirty: _dirty, base: _editBaseHash }),
    };
  `, context);
  return { ...context.subject, get };
}

const original = '# Original file\n';
const exactDraft = '---\ntitle: "文档"\n---\n# KEEP THIS UNSAVED TEXT\n\n日本語 📝\n\tindent  \n';

for (const [name, content] of [['Unicode and Markdown', exactDraft], ['intentional empty text', '']]) {
  test(`Done → pagehide → reload recovers exact ${name} and its original base hash`, async () => {
    const server = fixture(); server.seed('proof.md', original);
    const h = harness(server); await h.open('proof.md'); await h.enter(); h.type(content);
    h.done(); await tick(); await h.settled();
    assert.equal(h.get('wiki-save-state').textContent, 'draft kept locally');
    assert.equal(server.drafts.get('proof.md').content, content, 'initial server draft');
    h.pagehide(); await tick();
    assert.equal(server.writes.at(-1).body.content, content, 'pagehide must not serialize original file bytes');
    const reloaded = harness(server); await reloaded.open('proof.md');
    assert.equal(reloaded.get('wiki-inline-message').textContent, 'a private local draft is waiting.');
    await reloaded.enter();
    assert.equal(reloaded.state().content, content);
    assert.equal(reloaded.state().base, hash(original));
    assert.equal(server.files.get('proof.md').content, original);
  });
}

test('a late draft receipt preserves newer edits before Done and reload', async () => {
  const server = fixture(); server.seed('proof.md', original);
  const h = harness(server); await h.open('proof.md'); await h.enter(); h.type('first draft');
  const release = server.holdNextDraft(); const saving = h.flush(); await tick();
  h.type(exactDraft); h.done(); release(); await saving; await tick(); await h.settled();
  assert.equal(h.state().content, exactDraft);
  assert.equal(server.drafts.get('proof.md').content, exactDraft);
  h.pagehide(); await tick();
  const reloaded = harness(server); await reloaded.open('proof.md'); await reloaded.enter();
  assert.equal(reloaded.state().content, exactDraft);
});

test('navigation waits for a pending draft and preserves both document identities', async () => {
  const server = fixture(); server.seed('a.md', original); server.seed('b.md', '# B\n');
  const h = harness(server); await h.open('a.md'); await h.enter(); h.type('first A draft');
  const release = server.holdNextDraft(); h.done(); await tick();
  const opening = h.open('b.md'); await tick();
  assert.equal(h.state().path, 'a.md', 'pending draft owns departure');
  await h.enter(); h.type(exactDraft); release(); assert.equal(await opening, true);
  await h.enter(); h.type('B draft'); h.done(); await tick(); await h.settled(); h.pagehide(); await tick();
  assert.equal(h.state().path, 'b.md');
  assert.equal(server.drafts.get('a.md').content, exactDraft);
  assert.equal(server.drafts.get('b.md').content, 'B draft');
  const reloaded = harness(server); await reloaded.open('a.md'); await reloaded.enter();
  assert.equal(reloaded.state().content, exactDraft);
});

test('Save after Done commits the retained draft bytes and clears their recovery copy', async () => {
  const server = fixture(); server.seed('proof.md', original);
  const h = harness(server); await h.open('proof.md'); await h.enter(); h.type(exactDraft);
  h.done(); await tick(); await h.settled(); assert.equal(await h.save(), true);
  assert.equal(server.files.get('proof.md').content, exactDraft);
  assert.equal(server.drafts.has('proof.md'), false);
  const count = server.writes.length; h.pagehide(); await tick();
  assert.equal(server.writes.length, count, 'saved document has no draft to send');
});
