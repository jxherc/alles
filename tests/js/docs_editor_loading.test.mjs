import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/docs.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '')
  .replace(/^export /gm, '')
  .replace("import('../vendor/cm6.bundle.js')", '__loadEditor()');

function harness() {
  const elements = new Map();
  const loads = [];
  const disk = new Map();
  const storage = new Map();
  const writes = [];
  const mounted = [];
  let document;
  function element(id = '') {
    const attrs = new Map();
    return {
      id, value: '', textContent: '', hidden: false, disabled: false, style: {}, dataset: {},
      classList: { toggle() {}, remove() {}, add() {} },
      setAttribute: (name, value) => attrs.set(name, value),
      getAttribute: name => attrs.get(name), removeAttribute() {},
      querySelectorAll: () => [], replaceChildren() {}, appendChild() {},
      insertBefore(node) { elements.set(node.id, node); },
      focus() { document.activeElement = this; }, addEventListener() {},
    };
  }
  function get(id) {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }
  document = { getElementById: get, createElement: () => element(), querySelectorAll: () => [], activeElement: get('wiki-edit-btn') };
  const factory = (_host, options) => {
    let value = options.doc;
    const editor = {
      getValue: () => value,
      setValue: next => { value = next; options.onChange(next); },
      focus: () => get('visual-content').focus(), destroy() {},
    };
    mounted.push(editor);
    return editor;
  };
  const fetcher = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    let response = {};
    if (options.method) writes.push({ url, ...body });
    if (url.startsWith('/api/vault-md/file?')) response = disk.get(new URL(url, 'http://local').searchParams.get('path'));
    else if (url === '/api/vault-md/tree') response = { items: [] };
    else if (url.startsWith('/api/vault-md/backlinks')) response = { backlinks: [] };
    else if (url.startsWith('/api/vault-md/safety/draft')) response = { draft: null };
    else if (url === '/api/vault-md/safety/save') {
      assert.equal(body.expected_hash, disk.get(body.path).hash);
      response = { ...disk.get(body.path), content: body.content, hash: `saved-${writes.length}` };
      disk.set(body.path, response);
    } else throw new Error(`unexpected request: ${url}`);
    return { ok: true, json: async () => response };
  };
  const context = vm.createContext({
    document, fetch: fetcher, URL, URLSearchParams, TextEncoder, console,
    setTimeout: () => 1, clearTimeout() {},
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: {}, location: { pathname: '/', search: '', hash: '' }, history: { replaceState() {} },
    matchMedia: () => ({ matches: false }), mdToHtml: value => value, enhanceMarkdown() {}, toast() {},
    __loadEditor: () => new Promise((resolve, reject) => loads.push({ resolve: () => resolve({ createDocEditor: factory }), reject })),
  });
  vm.runInContext(source + `
    globalThis.subject = {
      open: openNote, enter: enterEdit, done: exitEdit, save: saveCurrent, view: setEditView,
      discard: async () => { openDialog = async () => ({ action: 'discard' }); return discardDraft(); },
      type: value => { $('wiki-source').value = value; sourceChanged(); },
      state: () => ({ content: currentContent(), mode: _mode, view: _editView, revision: _editRevision, dirty: _dirty }),
    };
  `, context);
  return {
    ...context.subject, get, loads, mounted, disk, writes, storage, document,
    seed(path, content) { disk.set(path, { path, content, hash: path + '-base', exists: true, editable: true }); },
  };
}

async function opened(content = 'original') {
  const h = harness(); h.seed('proof.md', content); await h.open('proof.md'); return h;
}

test('source is initialized before visual loading and late completion preserves text, mode, focus and revision', async () => {
  const h = await opened(); const pending = h.enter();
  assert.equal(h.get('wiki-source').value, 'original');
  h.view('source');
  const draft = '---\ntitle: 中文\n---\n# Latest 日本語 📝\n';
  h.type(draft); const revision = h.state().revision;
  assert.ok([...h.storage.values()].some(value => JSON.parse(value).content === draft));
  h.loads[0].resolve(); await pending;
  assert.equal(h.get('wiki-source').value, draft);
  assert.equal(h.state().content, draft);
  assert.equal(h.state().view, 'source');
  assert.equal(h.document.activeElement, h.get('wiki-source'));
  assert.equal(h.state().revision, revision);
  h.view('visual'); assert.equal(h.state().content, draft);
  await h.save(); assert.equal(h.disk.get('proof.md').content, draft);
});

test('empty edits remain authoritative when the visual module finishes', async () => {
  const h = await opened(); const pending = h.enter(); h.view('source'); h.type('');
  h.loads[0].resolve(); await pending;
  assert.equal(h.state().content, ''); assert.equal(h.get('wiki-source').value, '');
  h.view('visual'); assert.equal(h.state().content, '');
  await h.save(); assert.equal(h.disk.get('proof.md').content, '');
});

test('visual completion does not take focus back from another control', async () => {
  const h = await opened(); const pending = h.enter(); h.get('wiki-search').focus();
  h.loads[0].resolve(); await pending;
  assert.equal(h.state().view, 'visual'); assert.equal(h.document.activeElement, h.get('wiki-search'));
});

for (const departure of ['done', 'discard']) {
  test(`${departure} and same-file reentry reject an earlier editor initialization`, async () => {
    const h = await opened(); const oldEntry = h.enter(); h.view('source'); h.type('first draft');
    await h[departure](); const newEntry = h.enter(); h.view('source'); h.type('second draft');
    const revision = h.state().revision;
    h.loads[0].resolve(); await oldEntry;
    assert.equal(h.mounted.length, 0, 'obsolete entry must not mount an editor');
    assert.equal(h.state().content, 'second draft');
    h.loads[1].resolve(); await newEntry;
    assert.equal(h.mounted.length, 1); assert.equal(h.state().content, 'second draft');
    assert.equal(h.state().revision, revision); assert.equal(h.state().view, 'source');
  });
}

test('opening another document abandons a delayed editor without changing the new buffer', async () => {
  const h = await opened(); const pending = h.enter(); h.seed('other.md', 'other document');
  await h.open('other.md'); h.loads[0].resolve(); await pending;
  assert.equal(h.mounted.length, 0); assert.equal(h.state().mode, 'view');
  assert.equal(h.state().content, 'other document');
});

test('a failed visual import exposes usable Source with a visible message and preserves save/reopen', async () => {
  const h = await opened(); const pending = h.enter(); h.view('source'); h.type('safe draft');
  h.loads[0].reject(new Error('synthetic module failure')); await pending;
  assert.equal(h.state().content, 'safe draft'); assert.equal(h.state().view, 'source');
  assert.equal(h.get('wiki-source').hidden, false); assert.equal(h.get('wiki-visual-btn').disabled, true);
  assert.match(h.get('wiki-editor-load-state').textContent, /could not load.*source/);
  assert.equal(h.get('wiki-editor-load-state').hidden, false);
  h.type('still editable after failure'); await h.save(); await h.open('proof.md');
  assert.equal(h.state().content, 'still editable after failure');
});

test('a failed obsolete import cannot replace a newer editor or its focus', async () => {
  const h = await opened(); const oldEntry = h.enter(); h.done(); const newEntry = h.enter();
  h.view('source'); h.type('latest'); h.loads[1].resolve(); await newEntry;
  h.loads[0].reject(new Error('obsolete load')); await oldEntry;
  assert.equal(h.state().content, 'latest'); assert.equal(h.get('wiki-editor-load-state').hidden, true);
  assert.equal(h.get('wiki-visual-btn').disabled, false); assert.equal(h.document.activeElement, h.get('wiki-source'));
});
