import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/docs.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '')
  .replace(/^export /gm, '')
  .replace("import('../vendor/cm6.bundle.js')", '__loadEditor()');

const links = readFileSync(new URL('../../static/js/recordlinks.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');

function harness({ mobile = false } = {}) {
  const elements = new Map();
  const loads = [];
  const disk = new Map();
  const storage = new Map();
  const writes = [];
  const mounted = [];
  let saveBarrier = null;
  let document;
  const documentEvents = new Map();
  function element(id = '') {
    const attrs = new Map();
    const classes = new Set();
    const events = new Map();
    return {
      id, value: '', textContent: '', hidden: false, disabled: false, style: {}, dataset: {},
      classList: {
        toggle(name, enabled = !classes.has(name)) { if (enabled) classes.add(name); else classes.delete(name); },
        remove: (...names) => names.forEach(name => classes.delete(name)),
        add: (...names) => names.forEach(name => classes.add(name)), contains: name => classes.has(name),
      },
      setAttribute: (name, value) => attrs.set(name, value),
      getAttribute: name => attrs.get(name), removeAttribute() {},
      querySelectorAll: () => [], replaceChildren() {}, appendChild() {},
      insertBefore(node) { elements.set(node.id, node); },
      contains(target) {
        return target === this || (id === 'docs-nav-panel' && ['wiki-nav-close', 'wiki-new-btn', 'wiki-folder-btn', 'wiki-search'].includes(target?.id))
          || (id === 'docs-dialog' && target?.id === 'docs-dialog-input');
      },
      focus() { document.activeElement = this; documentEvents.get('focusin')?.({ target: this }); },
      addEventListener(name, listener) { events.set(name, listener); },
      click() { events.get('click')?.({ target: this }); },
    };
  }
  function get(id) {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  }
  document = {
    getElementById: get, createElement: () => element(), querySelectorAll: () => [], activeElement: get('wiki-edit-btn'),
    addEventListener(name, listener) { documentEvents.set(name, listener); },
  };
  get('docs-dialog').hidden = true;
  get('wiki-more-menu').hidden = true;
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
      if (saveBarrier) await saveBarrier;
      assert.equal(body.expected_hash, disk.get(body.path).hash);
      response = { ...disk.get(body.path), content: body.content, hash: `saved-${writes.length}` };
      disk.set(body.path, response);
    } else throw new Error(`unexpected request: ${url}`);
    return { ok: true, json: async () => response };
  };
  const routeLocation = new URL('http://local/');
  const context = vm.createContext({
    document, fetch: fetcher, URL, URLSearchParams, TextEncoder, console,
    setTimeout: () => 1, clearTimeout() {},
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: {}, location: routeLocation, history: { replaceState() {} },
    replaceRouteUrl(url) {
      const route = new URL(url, 'http://local');
      routeLocation.pathname = route.pathname;
      routeLocation.search = route.search;
      routeLocation.hash = route.hash;
    },
    matchMedia: () => ({ matches: mobile }), addEventListener() {}, mdToHtml: value => value, enhanceMarkdown() {}, toast() {},
    __loadEditor: () => new Promise((resolve, reject) => loads.push({ resolve: () => resolve({ createDocEditor: factory }), reject })),
  });
  vm.runInContext(links, context);
  vm.runInContext(source + `
    globalThis.subject = {
      wire: _wire,
      open: openNote, enter: enterEdit, done: exitEdit, save: saveCurrent, view: setEditView,
      discard: async () => { openDialog = async () => ({ action: 'discard' }); return discardDraft(); },
      type: value => { $('wiki-source').value = value; sourceChanged(); },
      state: () => ({ content: currentContent(), mode: _mode, view: _editView, revision: _editRevision, dirty: _dirty }),
    };
  `, context);
  return {
    ...context.subject, get, loads, mounted, disk, writes, storage, document,
    holdSave() {
      let finish;
      saveBarrier = new Promise((resolve, reject) => {
        finish = failure => failure ? reject(new Error('synthetic save interruption')) : resolve();
      });
      return finish;
    },
    escape() { documentEvents.get('keydown')?.({ key: 'Escape', preventDefault() {} }); },
    seed(path, content) { disk.set(path, { path, content, hash: path + '-base', exists: true, editable: true }); },
  };
}

test('mobile document navigation moves focus inside and close returns to browse', () => {
  const h = harness({ mobile: true }); h.wire();
  h.get('wiki-tree-toggle').focus(); h.get('wiki-tree-toggle').click();
  assert.equal(h.document.activeElement, h.get('wiki-nav-close'));
  assert.equal(h.get('wiki-tree-toggle').getAttribute('aria-expanded'), 'true');
  h.get('wiki-nav-close').click();
  assert.equal(h.document.activeElement, h.get('wiki-tree-toggle'));
  assert.equal(h.get('wiki-tree-toggle').getAttribute('aria-expanded'), 'false');
});

test('escape closes mobile document navigation and restores its trigger', () => {
  const h = harness({ mobile: true }); h.wire();
  h.get('wiki-tree-toggle').click(); h.get('wiki-search').focus(); h.escape();
  assert.equal(h.document.activeElement, h.get('wiki-tree-toggle'));
  assert.equal(h.get('wiki-view').classList.contains('docs-nav-open'), false);
});

test('moving focus outside mobile navigation dismisses it without stealing focus', () => {
  const h = harness({ mobile: true }); h.wire();
  h.get('wiki-tree-toggle').click(); h.get('wiki-empty-new').focus();
  assert.equal(h.document.activeElement, h.get('wiki-empty-new'));
  assert.equal(h.get('wiki-view').classList.contains('docs-nav-open'), false);
});

test('a document dialog keeps its navigation available for focus restoration', () => {
  const h = harness({ mobile: true }); h.wire();
  h.get('wiki-tree-toggle').click(); h.get('wiki-new-btn').focus();
  h.get('docs-dialog-input').focus();
  assert.equal(h.get('wiki-view').classList.contains('docs-nav-open'), true);
  h.get('wiki-new-btn').focus();
  assert.equal(h.get('wiki-view').classList.contains('docs-nav-open'), true);
});

test('desktop navigation retains its trigger focus and ordinary collapse behavior', () => {
  const h = harness(); h.wire(); h.get('wiki-tree-toggle').focus();
  h.get('wiki-tree-toggle').click();
  assert.equal(h.document.activeElement, h.get('wiki-tree-toggle'));
  assert.equal(h.get('wiki-view').classList.contains('docs-nav-hidden'), true);
  h.get('wiki-tree-toggle').click();
  assert.equal(h.get('wiki-view').classList.contains('docs-nav-hidden'), false);
});

async function opened(content = 'original') {
  const h = harness(); h.seed('proof.md', content); await h.open('proof.md'); return h;
}

test('opening a document moves focus into its rendered content', async () => {
  const h = await opened();
  assert.equal(h.document.activeElement, h.get('wiki-preview'));
});

test('quiet document refresh preserves the current control focus', async () => {
  const h = await opened();
  h.get('wiki-search').focus();
  await h.open('proof.md', { quiet: true });
  assert.equal(h.document.activeElement, h.get('wiki-search'));
});

test('document loading does not take focus from a newer user action', async () => {
  const h = harness(); h.seed('proof.md', 'original');
  const opening = h.open('proof.md');
  h.get('wiki-search').focus();
  await opening;
  assert.equal(h.document.activeElement, h.get('wiki-search'));
});

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

async function editingDraft() {
  const h = await opened();
  const entering = h.enter(); h.loads[0].resolve(); await entering;
  h.view('source'); h.type('updated draft');
  return h;
}

for (const failure of [false, true]) {
  test(`focused save keeps a useful keyboard position through ${failure ? 'rejection' : 'success'}`, async () => {
    const h = await editingDraft();
    const finish = h.holdSave(); h.get('wiki-save-btn').focus();
    const saving = h.save();
    assert.equal(h.get('wiki-save-btn').disabled, true);
    assert.equal(h.document.activeElement, h.get('wiki-save-state'));
    finish(failure); assert.equal(await saving, !failure);
    assert.equal(h.document.activeElement, h.get('wiki-save-btn'));
    assert.equal(h.get('wiki-save-btn').disabled, false);
    assert.equal(h.state().content, 'updated draft');
    assert.equal(h.disk.get('proof.md').content, failure ? 'original' : 'updated draft');
  });
}

test('finishing a save does not take focus back from a chosen control', async () => {
  const h = await editingDraft(); const finish = h.holdSave();
  h.get('wiki-save-btn').focus(); const saving = h.save();
  h.get('wiki-search').focus(); finish(true); await saving;
  assert.equal(h.document.activeElement, h.get('wiki-search'));
});

test('saving from outside the save button preserves that keyboard position', async () => {
  const h = await editingDraft(); const finish = h.holdSave();
  const saving = h.save();
  assert.equal(h.document.activeElement, h.get('wiki-source'));
  finish(false); await saving;
  assert.equal(h.document.activeElement, h.get('wiki-source'));
});

test('discarding returns keyboard focus to the unchanged document', async () => {
  const h = await editingDraft(); h.get('wiki-discard-btn').focus();
  await h.discard();
  assert.equal(h.document.activeElement, h.get('wiki-preview'));
  assert.equal(h.state().mode, 'view');
  assert.equal(h.disk.get('proof.md').content, 'original');
});

test('discard completion preserves a different chosen focus target', async () => {
  const h = await editingDraft(); h.get('wiki-discard-btn').focus();
  const discarding = h.discard(); h.get('wiki-search').focus(); await discarding;
  assert.equal(h.document.activeElement, h.get('wiki-search'));
});

test('the visual editor keyboard hint is hidden in source mode', async () => {
  const h = await editingDraft();
  assert.equal(h.get('wiki-keyboard-hint').hidden, true);
  h.view('visual'); assert.equal(h.get('wiki-keyboard-hint').hidden, false);
  h.view('source'); assert.equal(h.get('wiki-keyboard-hint').hidden, true);
});
