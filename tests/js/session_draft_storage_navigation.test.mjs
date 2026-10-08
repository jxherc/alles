import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const drafts = sessions.slice(sessions.indexOf('const _legacyDraftKey'), sessions.indexOf('export function newChat'));
const select = sessions.match(/^export async function selectSession\([^]*?^}/m)?.[0];
const sidebar = sessions.match(/^async function selectSidebarSession\([^]*?^}/m)?.[0];
const rowState = sessions.match(/^function syncSessionRowState\([^]*?^}/m)?.[0];
assert.ok(drafts && select && sidebar && rowState, 'exercise the maintained draft and navigation functions');
const scope = name => ({ kind: 'vault_documents', documents: [{ path: name, expected_hash: 'synthetic-saved-hash' }] });
const outgoing = { text: '  unsaved question\n中文  ', document_scope: scope('outgoing.md') };
const destination = { text: 'destination question', document_scope: scope('destination.md') };
const key = id => 'aide-draft-v2-' + (id || 'new');
const copy = value => JSON.parse(JSON.stringify(value));

function harness({ id = 'outgoing', privateMode = false, missingComposer = false, destinationDraft = destination } = {}) {
  const storage = new Map([[key(id), JSON.stringify({ text: 'older saved copy', document_scope: null })]]);
  if (destinationDraft) storage.set(key('destination'), JSON.stringify(destinationDraft));
  const state = { failure: null, storageAccesses: 0, inputEvents: 0 };
  const notices = [], effects = [], storageCalls = [];
  const location = new URL('http://127.0.0.1:1/?view=chat&message=old');
  location.hash = id || '';
  const recovery = { hidden: false, setAttribute(name) { if (name === 'hidden') this.hidden = true; } };
  const field = { value: outgoing.text, style: { height: '66px' }, selectionStart: 2, selectionEnd: 8,
    dispatchEvent() { state.inputEvents++; context.subject.save(); } };
  const rows = ['outgoing', 'destination'].map(rowId => {
    const row = { dataset: { id: rowId }, active: rowId === id, current: rowId === id ? 'true' : 'false' };
    row.classList = { toggle(_name, on) { row.active = on; } };
    row.querySelector = () => ({ setAttribute(_name, value) { row.current = value; } });
    return row;
  });
  const window = { _pendingDocumentScope: copy(outgoing.document_scope), _currentSession: { id, name: 'outgoing' },
    _enterChatView: () => effects.push('enter-chat'),
    _setMode: mode => effects.push(['mode', mode]),
    _closeCompactAideSidebar: () => effects.push('close-sidebar'),
    _setAideDocumentScope(value) { this._pendingDocumentScope = value; context.subject.save(); } };
  const storageAPI = {
    getItem(name) { storageCalls.push(['get', name]); return storage.get(name) ?? null; },
    setItem(name, value) {
      storageCalls.push(['set', name]);
      if (state.failure === 'QuotaExceededError') throw new DOMException('synthetic quota', state.failure);
      storage.set(name, value);
    },
    removeItem(name) { storageCalls.push(['remove', name]); storage.delete(name); },
  };
  const context = vm.createContext({
    window, location, URL, Event: class {},
    document: { getElementById: name => name === 'composer-ta' ? (missingComposer ? null : field)
      : name === 'composer-send-recovery' ? recovery : null, querySelectorAll: () => rows },
    isIncognitoMode: () => privateMode, toast: text => notices.push(text),
    replaceRouteUrl(url) { effects.push(['route', url.href]); location.href = url.href; },
    fetch: async url => {
      effects.push(['fetch', url]);
      return { json: async () => ({ session: { id: url.split('/')[3], mode: 'chat' }, messages: [] }) };
    },
    renderMessages: () => effects.push('render'), showMessages: () => effects.push('show'),
    restoreSessionModel: () => effects.push('model'), updateSessionHeader: () => effects.push('header'),
    focusSessionMessage: () => true, console: { error: (...args) => effects.push(['error', ...args]) },
  });
  Object.defineProperty(context, 'localStorage', { get() {
    state.storageAccesses++;
    if (state.failure === 'SecurityError') throw new DOMException('synthetic storage denial', state.failure);
    return storageAPI;
  } });
  vm.runInContext(`let _activeId = ${JSON.stringify(id)}; let _composerGeneration = 7;\n`
    + [drafts, rowState, select, sidebar].join('\n').replace(/^export /gm, '')
    + '\nglobalThis.subject = { save: saveDraft, select: selectSession, sidebar: selectSidebarSession, state: () => ({ id: _activeId, generation: _composerGeneration }) };',
  context, { importModuleDynamically: async () => { throw new Error('background reattachment outside this unit'); } });
  return { field, window, storage, notices, effects, storageCalls, state, recovery, location,
    save: () => context.subject.save(), select: (...args) => context.subject.select(...args),
    open: id => context.subject.sidebar(id), active: () => copy(context.subject.state()),
    snapshot: () => copy({ field: { value: field.value, height: field.style.height,
      start: field.selectionStart, end: field.selectionEnd }, scope: window._pendingDocumentScope,
    session: window._currentSession, active: context.subject.state(), href: location.href,
    recoveryHidden: recovery.hidden, inputEvents: state.inputEvents,
    rows: rows.map(row => ({ id: row.dataset.id, active: row.active, current: row.current })) }),
  };
}

for (const failure of ['QuotaExceededError', 'SecurityError']) {
  for (const scopeOnly of [false, true]) {
    test(`${failure} refuses a task switch without replacing the ${scopeOnly ? 'scope-only' : 'text and scope'} draft`, async () => {
      const h = harness();
      if (scopeOnly) h.field.value = ' \n ';
      h.state.failure = failure;
      assert.equal(h.save(), false, 'the actual autosave reports storage failure');
      const before = h.snapshot(), stored = [...h.storage];
      assert.equal(await h.open('destination'), false);
      assert.deepEqual(h.snapshot(), before);
      assert.deepEqual([...h.storage], stored);
      assert.deepEqual(h.effects, [], 'no route, fetch, render, model or sidebar mutation');
      assert.equal(h.notices.length, 1, 'retain the existing warning without repeated notices');
      assert.match(h.notices[0], /keep this tab open/);
    });
  }
}

for (const id of [null, 'outgoing']) {
  test(`a failed save keeps ${id || 'new task'} input when the destination has no draft`, async () => {
    const h = harness({ id, destinationDraft: null }); h.state.failure = 'QuotaExceededError';
    const before = h.snapshot();
    assert.equal(await h.open('destination'), false);
    assert.deepEqual(h.snapshot(), before);
    assert.deepEqual(h.effects, []);
  });
}

test('storage recovery permits one switch and restores each task\'s exact draft on return', async () => {
  const h = harness(); h.state.failure = 'QuotaExceededError';
  assert.equal(await h.open('destination'), false);
  h.state.failure = null;
  assert.equal(await h.open('destination'), true);
  assert.deepEqual(h.active(), { id: 'destination', generation: 8 });
  assert.deepEqual(JSON.parse(h.storage.get(key('outgoing'))), outgoing);
  assert.equal(h.field.value, destination.text);
  assert.deepEqual(copy(h.window._pendingDocumentScope), destination.document_scope);
  assert.equal(h.location.hash, '#destination');
  assert.equal(h.recovery.hidden, true);
  assert.equal(h.effects.filter(value => value === 'close-sidebar').length, 1);
  assert.equal(await h.open('outgoing'), true);
  assert.equal(h.field.value, outgoing.text);
  assert.deepEqual(copy(h.window._pendingDocumentScope), outgoing.document_scope);
});

test('private task switching still bypasses durable draft storage', async () => {
  const h = harness({ privateMode: true }); h.state.failure = 'SecurityError';
  const stored = [...h.storage];
  assert.equal(await h.open('destination'), true);
  assert.equal(h.state.storageAccesses, 0);
  assert.deepEqual([...h.storage], stored);
  assert.equal(h.field.value, '');
  assert.equal(h.window._pendingDocumentScope, null);
});

test('a missing composer does not turn an undefined save result into a refusal', async () => {
  const h = harness({ missingComposer: true }); h.state.failure = 'SecurityError';
  assert.equal(await h.open('destination'), true);
  assert.deepEqual(h.active(), { id: 'destination', generation: 8 });
  assert.equal(h.state.storageAccesses, 0);
});

test('explicit startup skipDraft retains its existing bypass', async () => {
  const h = harness(); h.state.failure = 'QuotaExceededError';
  assert.equal(await h.select('destination', '', { skipDraft: true }), true);
  assert.equal(h.field.value, destination.text);
  assert.equal(h.storageCalls.some(([method, name]) => method === 'set' && name === key('outgoing')), false);
});

test('empty draft cleanup at quota still permits switching when removal succeeds', async () => {
  const h = harness(); h.field.value = ''; h.window._pendingDocumentScope = null;
  h.state.failure = 'QuotaExceededError';
  assert.equal(await h.open('destination'), true);
  assert.equal(h.storage.has(key('outgoing')), false);
  assert.equal(h.field.value, destination.text);
});

test('denied empty-draft cleanup returns false before changing the active task', async () => {
  const h = harness(); h.field.value = ''; h.window._pendingDocumentScope = null;
  h.state.failure = 'SecurityError'; const before = h.snapshot();
  assert.equal(await h.open('destination'), false);
  assert.deepEqual(h.snapshot(), before);
  assert.deepEqual(h.effects, []);
});
