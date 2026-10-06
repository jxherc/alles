import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const drafts = source.slice(source.indexOf('const _legacyDraftKey'), source.indexOf('export function newChat'));
const fresh = source.match(/^export function newChat\([^]*?^}/m)?.[0];
const rowState = source.match(/^function syncSessionRowState\([^]*?^}/m)?.[0];
assert.ok(drafts && fresh && rowState, 'exercise actual draft, newChat and row-state functions');
const copy = value => JSON.parse(JSON.stringify(value));
const key = id => 'aide-draft-v2-' + (id || 'new');
const scope = name => ({ kind: 'vault_documents', documents: [{ path: name, expected_hash: 'synthetic-hash' }] });
const outgoing = { text: '  unfinished task\n中文  ', document_scope: scope('outgoing.md') };
const newDraft = { text: 'saved new-task question', document_scope: scope('new-task.md') };

function harness({ id = 'outgoing', privateMode = false, missingComposer = false, savedNew = newDraft } = {}) {
  const storage = new Map([[key(id), JSON.stringify({ text: 'older saved copy', document_scope: null })]]);
  if (id !== null && savedNew) storage.set(key(null), JSON.stringify(savedNew));
  const state = { failure: null, storageAccesses: 0, inputEvents: 0 };
  const notices = [], effects = [], storageCalls = [];
  const location = new URL('http://127.0.0.1:1/?view=chat&message=old'); location.hash = id || '';
  const document = { activeElement: { id: 'new-chat-btn' } };
  const recovery = { hidden: false, setAttribute(name) { if (name === 'hidden') this.hidden = true; } };
  const messages = { innerHTML: '<article>retained conversation</article>' };
  const field = { id: 'composer-ta', value: outgoing.text, style: { height: '66px' }, selectionStart: 3, selectionEnd: 9,
    focus() { document.activeElement = this; effects.push('focus-composer'); },
    dispatchEvent() { state.inputEvents++; context.subject.save(); } };
  const rows = ['outgoing', 'destination'].map(rowId => {
    const row = { dataset: { id: rowId }, active: rowId === id, current: rowId === id ? 'true' : 'false' };
    row.classList = { toggle(_name, on) { row.active = on; } };
    row.querySelector = () => ({ setAttribute(_name, value) { row.current = value; } });
    return row;
  });
  document.getElementById = name => name === 'composer-ta' ? (missingComposer ? null : field)
    : name === 'composer-send-recovery' ? recovery : name === 'messages' ? messages : null;
  document.querySelectorAll = () => rows;
  const window = { _pendingDocumentScope: copy(outgoing.document_scope), _currentSession: { id, name: 'outgoing' },
    _pendingProjectId: 'old-project', _pendingWorkingDir: '/synthetic/work',
    _pendingPersona: { id: 'synthetic-persona' }, _pendingChatBehavior: 'old-behavior',
    _refreshPersonaBtn: () => effects.push('refresh-persona'),
    _syncAideNewTaskContext: value => effects.push(['sync-context', value]),
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
  const context = vm.createContext({ window, document, location, URL, URLSearchParams, Event: class {},
    isIncognitoMode: () => privateMode, toast: text => notices.push(text),
    getProjects: () => [{ id: 'allowed-project' }], selectAideDefault: () => effects.push('default-model'),
    showWelcome: () => effects.push('welcome'),
    replaceRouteUrl(url) { effects.push(['route', url.href]); location.href = url.href; },
  });
  Object.defineProperty(context, 'localStorage', { get() {
    state.storageAccesses++;
    if (state.failure === 'SecurityError') throw new DOMException('synthetic storage denial', state.failure);
    return storageAPI;
  } });
  vm.runInContext(`let _activeId = ${JSON.stringify(id)}; let _composerGeneration = 7;\n`
    + [drafts, rowState, fresh].join('\n').replace(/^export /gm, '')
    + '\nglobalThis.subject = { save: saveDraft, fresh: newChat, state: () => ({ id: _activeId, generation: _composerGeneration }) };', context);
  return { field, document, messages, window, storage, notices, effects, storageCalls, state, recovery, location,
    fresh: options => context.subject.fresh(options), active: () => copy(context.subject.state()),
    snapshot: () => copy({ field: { value: field.value, height: field.style.height, start: field.selectionStart, end: field.selectionEnd },
      scope: window._pendingDocumentScope, session: window._currentSession, active: context.subject.state(), href: location.href,
      project: window._pendingProjectId, workingDir: window._pendingWorkingDir, persona: window._pendingPersona,
      behavior: window._pendingChatBehavior, recoveryHidden: recovery.hidden, messages: messages.innerHTML,
      focused: document.activeElement?.id, inputEvents: state.inputEvents,
      rows: rows.map(row => ({ id: row.dataset.id, active: row.active, current: row.current })) }),
  };
}

for (const failure of ['QuotaExceededError', 'SecurityError']) {
  for (const id of ['outgoing', null]) {
    for (const scopeOnly of [false, true]) {
      test(`${failure}: newChat preserves ${id || 'new-task'} ${scopeOnly ? 'scope-only' : 'text and scope'} before any reset`, () => {
        const h = harness({ id }); if (scopeOnly) h.field.value = ' \n ';
        h.state.failure = failure; const before = h.snapshot(), stored = [...h.storage];
        assert.equal(h.fresh({ projectId: 'allowed-project' }), false);
        assert.deepEqual(h.snapshot(), before);
        assert.deepEqual([...h.storage], stored);
        assert.deepEqual(h.effects, [], 'no model, route, welcome, persona, focus or context reset');
        assert.equal(h.notices.length, 1); assert.match(h.notices[0], /keep this tab open/);
      });
    }
  }
}

for (const failure of ['QuotaExceededError', 'SecurityError']) {
  test(`${failure}: recovery saves the outgoing draft and permits the same newChat request`, () => {
    const h = harness(); h.state.failure = failure;
    assert.equal(h.fresh({ projectId: 'allowed-project' }), false);
    h.state.failure = null;
    assert.equal(h.fresh({ projectId: 'allowed-project' }), undefined, 'retain the successful call return contract');
    assert.deepEqual(JSON.parse(h.storage.get(key('outgoing'))), outgoing);
    assert.deepEqual(h.active(), { id: null, generation: 8 });
    assert.equal(h.field.value, newDraft.text); assert.deepEqual(copy(h.window._pendingDocumentScope), newDraft.document_scope);
    assert.equal(h.window._currentSession, null); assert.equal(h.window._pendingProjectId, 'allowed-project');
    assert.equal(h.window._pendingWorkingDir, ''); assert.equal(h.window._pendingPersona, null);
    assert.equal(h.window._pendingChatBehavior, ''); assert.equal(h.messages.innerHTML, '');
    assert.equal(h.recovery.hidden, true); assert.equal(h.document.activeElement, h.field);
    assert.equal(h.location.hash, ''); assert.equal(h.location.searchParams.has('message'), false);
    assert.equal(h.effects.filter(effect => effect === 'default-model').length, 1);
    assert.equal(h.effects.filter(effect => effect === 'welcome').length, 1);
    assert.ok(h.snapshot().rows.every(row => !row.active && row.current === 'false'));
  });
}

test('retrying from an unsaved new task preserves its exact text and scope', () => {
  const h = harness({ id: null }); h.state.failure = 'QuotaExceededError';
  assert.equal(h.fresh(), false); h.state.failure = null;
  assert.equal(h.fresh(), undefined); assert.deepEqual(JSON.parse(h.storage.get(key(null))), outgoing);
  assert.equal(h.field.value, outgoing.text); assert.deepEqual(copy(h.window._pendingDocumentScope), outgoing.document_scope);
  assert.deepEqual(h.active(), { id: null, generation: 8 });
});

test('private newChat bypasses denied durable storage and clears the private composer', () => {
  const h = harness({ privateMode: true }); h.state.failure = 'SecurityError'; const stored = [...h.storage];
  assert.equal(h.fresh(), undefined); assert.equal(h.state.storageAccesses, 0);
  assert.deepEqual([...h.storage], stored); assert.equal(h.field.value, '');
  assert.equal(h.window._pendingDocumentScope, null); assert.deepEqual(h.active(), { id: null, generation: 8 });
});

test('a missing composer retains the undefined-save bypass without storage access', () => {
  const h = harness({ missingComposer: true }); h.state.failure = 'SecurityError';
  assert.equal(h.fresh(), undefined); assert.equal(h.state.storageAccesses, 0);
  assert.deepEqual(h.active(), { id: null, generation: 8 }); assert.equal(h.messages.innerHTML, '');
  assert.equal(h.effects.includes('focus-composer'), false);
});

test('explicit skipDraft and preserveHash retain startup behavior at quota', () => {
  const h = harness(); h.state.failure = 'QuotaExceededError'; const before = h.location.href, stored = h.storage.get(key('outgoing'));
  assert.equal(h.fresh({ skipDraft: true, preserveHash: true }), undefined);
  assert.equal(h.location.href, before); assert.equal(h.storage.get(key('outgoing')), stored);
  assert.equal(h.storageCalls.some(([method, name]) => method === 'set' && name === key('outgoing')), false);
  assert.equal(h.field.value, newDraft.text); assert.deepEqual(h.active(), { id: null, generation: 8 });
});

test('empty-draft removal at quota still allows a fresh empty task', () => {
  const h = harness({ savedNew: null }); h.field.value = ''; h.window._pendingDocumentScope = null;
  h.state.failure = 'QuotaExceededError'; assert.equal(h.fresh(), undefined);
  assert.equal(h.storage.has(key('outgoing')), false); assert.equal(h.field.value, '');
  assert.equal(h.window._pendingDocumentScope, null); assert.deepEqual(h.active(), { id: null, generation: 8 });
});

test('denied empty-draft cleanup refuses newChat before state changes', () => {
  const h = harness(); h.field.value = ''; h.window._pendingDocumentScope = null; h.state.failure = 'SecurityError';
  const before = h.snapshot(), stored = [...h.storage];
  assert.equal(h.fresh(), false); assert.deepEqual(h.snapshot(), before);
  assert.deepEqual([...h.storage], stored); assert.deepEqual(h.effects, []);
});

for (const [requested, expected] of [['allowed-project', 'allowed-project'], ['unknown-project', '']]) {
  test(`normal newChat validates project ${requested} and saves the outgoing draft`, () => {
    const h = harness({ savedNew: null }); h.location.searchParams.set('project_id', requested);
    assert.equal(h.fresh(), undefined); assert.equal(h.window._pendingProjectId, expected);
    assert.deepEqual(JSON.parse(h.storage.get(key('outgoing'))), outgoing);
    assert.equal(h.field.value, ''); assert.equal(h.window._pendingDocumentScope, null);
    assert.equal(h.location.searchParams.get('project_id'), requested);
  });
}
