import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const drafts = source.slice(source.indexOf('const _legacyDraftKey'), source.indexOf('export function newChat'));
const fresh = source.match(/^export function newChat\([^]*?^}/m)?.[0];
const rowState = source.match(/^function syncSessionRowState\([^]*?^}/m)?.[0];
assert.ok(drafts && fresh && rowState, 'exercise actual draft, newChat and row-state functions');

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const privateDay = app.match(/^async function showPrivateDayDraft\([^]*?^}/m)?.[0];
const askStart = app.indexOf('window._askInChat = async (');
const askEnd = app.indexOf('\nconst showModelsView', askStart);
assert.ok(privateDay && askStart >= 0 && askEnd > askStart);
const ask = app.slice(askStart, askEnd);
const dynamicImport = "import('./andromeda.js?v=248')";
assert.equal(ask.split(dynamicImport).length, 2, 'bind only this actual module import to the synthetic search dependency');
const boundAsk = ask.replace(dynamicImport, '__loadAndromeda()');
function clickHandler(id) {
  const start = app.indexOf("  document.getElementById('" + id + "')?.addEventListener('click', async () => {");
  const end = app.indexOf('\n  });', start);
  assert.ok(start >= 0 && end > start, 'exercise the actual ' + id + ' handler');
  return app.slice(start, end + '\n  });'.length);
}

const copy = value => JSON.parse(JSON.stringify(value));
const key = id => 'aide-draft-v2-' + (id || 'new');
const scope = name => ({ kind: 'vault_documents', documents: [{ path: name, expected_hash: 'synthetic-hash' }] });
const outgoing = { text: '  unfinished task\n中文  ', document_scope: scope('outgoing.md') };
const newDraft = { text: 'saved new-task question', document_scope: scope('new-task.md') };

function harness({ id = 'outgoing', privateMode = false, missingComposer = false, savedNew = newDraft } = {}) {
  const storage = new Map([[key(id), JSON.stringify({ text: 'older saved copy', document_scope: null })]]);
  if (id !== null && savedNew) storage.set(key(null), JSON.stringify(savedNew));
  const state = { failure: null, storageAccesses: 0, inputEvents: 0, navigateAllowed: true, canSend: true };
  const notices = [], effects = [], storageCalls = [], navigations = [], sends = [], searches = [], requests = [];
  const attachments = ['owned-attachment'];
  const enterButton = { addEventListener(_kind, handler) { this.click = handler; } };
  const exitButton = { addEventListener(_kind, handler) { this.click = handler; } };
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
    : name === 'composer-send-recovery' ? recovery : name === 'messages' ? messages
      : name === 'incognito-btn' ? enterButton : name === 'incognito-exit' ? exitButton : null;
  document.querySelectorAll = () => rows;
  const window = { _pendingDocumentScope: copy(outgoing.document_scope), _currentSession: { id, name: 'outgoing', project_id: 'old-project' },
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
    setIncognitoMode(value) { privateMode = value; effects.push(['privacy', value]); },
    discardAttachments: async () => { attachments.splice(0); effects.push('discard-attachments'); },
    navigateTo: async view => { navigations.push(view); return state.navigateAllowed; },
    canSendMessage: () => state.canSend,
    sendMessage: async text => sends.push([text, copy(window._pendingDocumentScope), window._pendingProjectId]),
    singleHost: () => true, urlForApp: () => 'http://127.0.0.1:1/',
    validatedProjectId: id => ['allowed-project', 'old-project'].includes(id) ? id : '',
    withProjectContext: (href, id) => { const url = new URL(href); url.searchParams.set('project_id', id); return url.href; },
    _replaceHistoryUrl(href) { effects.push(['search-context', href]); location.href = href; },
    __loadAndromeda: async () => {
      effects.push('load-andromeda');
      return { runAndromedaSearch: async (text, options) => searches.push([text, copy(options)]) };
    },
    getActiveId: () => context.subject.state().id,
    fetch: async (url, options) => {
      assert.match(url, /^\/api\/sessions\/[a-z-]+$/); assert.equal(options.method, 'DELETE');
      requests.push([url, options.method]); return { ok: true };
    },
    getProjects: () => [{ id: 'allowed-project' }, { id: 'old-project' }], selectAideDefault: () => effects.push('default-model'),
    showWelcome: () => effects.push('welcome'),
    replaceRouteUrl(url) { effects.push(['route', url.href]); location.href = url.href; },
  });
  Object.defineProperty(context, 'localStorage', { get() {
    state.storageAccesses++;
    if (state.failure === 'SecurityError') throw new DOMException('synthetic storage denial', state.failure);
    return storageAPI;
  } });
  vm.runInContext(`let _activeId = ${JSON.stringify(id)}; let _composerGeneration = 7;\n`
    + [drafts, rowState, fresh, privateDay, boundAsk, clickHandler('incognito-btn'), clickHandler('incognito-exit')].join('\n').replace(/^export /gm, '')
    + '\nglobalThis.subject = { save: saveDraft, fresh: newChat, day: showPrivateDayDraft, state: () => ({ id: _activeId, generation: _composerGeneration }) };', context);
  return { field, document, messages, window, storage, notices, effects, storageCalls, state, recovery, location,
    attachments, navigations, sends, searches, requests,
    day: text => context.subject.day(text), privateEntry: () => enterButton.click(), privateExit: () => exitButton.click(),
    ask: (...args) => context.window._askInChat(...args),
    fresh: options => context.subject.fresh(options), active: () => copy(context.subject.state()),
    snapshot: () => copy({ privateMode, attachments: [...attachments], field: { value: field.value, height: field.style.height, start: field.selectionStart, end: field.selectionEnd },
      scope: window._pendingDocumentScope, session: window._currentSession, active: context.subject.state(), href: location.href,
      project: window._pendingProjectId, workingDir: window._pendingWorkingDir, persona: window._pendingPersona,
      behavior: window._pendingChatBehavior, recoveryHidden: recovery.hidden, messages: messages.innerHTML,
      focused: document.activeElement?.id, inputEvents: state.inputEvents,
      rows: rows.map(row => ({ id: row.dataset.id, active: row.active, current: row.current })) }),
  };
}

const incomingText = '  incoming question\n中文  ';
const incomingScope = scope('incoming.md');
const flows = [
  { name: 'private day', run: h => h.day(incomingText), view: 'chat', private: true, result: true },
  { name: 'incognito button', run: h => h.privateEntry(), view: null, private: true, result: undefined },
  { name: 'inline Aide project', run: h => h.ask(incomingText, false, incomingScope, 'allowed-project'), view: 'chat', private: false, result: true },
  { name: 'inline Andromeda project', run: h => h.ask(incomingText, true, incomingScope, 'allowed-project', true), view: 'andromeda', private: false, result: true },
];

for (const flow of flows) {
  for (const failure of ['QuotaExceededError', 'SecurityError']) {
    for (const scopeOnly of [false, true]) {
      test(`${flow.name}: ${failure} keeps ${scopeOnly ? 'scope-only' : 'text and scope'} outgoing work before destructive effects`, async () => {
        const h = harness(); h.state.failure = failure;
        if (scopeOnly) h.field.value = '';
        const before = h.snapshot(), stored = [...h.storage];
        assert.equal(await flow.run(h), false);
        assert.deepEqual(h.snapshot(), before);
        assert.deepEqual([...h.storage], stored);
        assert.deepEqual(h.effects, []);
        assert.deepEqual(h.sends, []); assert.deepEqual(h.searches, []); assert.deepEqual(h.requests, []);
        assert.deepEqual(h.navigations, flow.view ? [flow.view] : [], 'existing view navigation may precede the save guard');
        assert.equal(h.notices.length, 1);
        assert.match(h.notices[0], /could not keep this draft/);
      });
    }
  }

  test(`${flow.name}: the same request succeeds after storage recovers`, async () => {
    const h = harness(); h.state.failure = 'QuotaExceededError';
    assert.equal(await flow.run(h), false);
    h.state.failure = null;
    assert.equal(await flow.run(h), flow.result);
    assert.deepEqual(JSON.parse(h.storage.get(key('outgoing'))), outgoing);
    assert.deepEqual(h.active(), { id: null, generation: 8 });
    assert.equal(h.window._currentSession, null);
    assert.equal(h.snapshot().privateMode, flow.private);
    assert.equal(h.effects.filter(effect => effect === 'default-model').length, 1);
    assert.equal(h.recovery.hidden, true); assert.equal(h.messages.innerHTML, '');
    assert.deepEqual(h.requests, []);
    if (flow.private) {
      assert.deepEqual(h.attachments, []);
      assert.equal(h.field.value, flow.name === 'private day' ? incomingText : '');
      assert.equal(h.window._pendingDocumentScope, null);
      assert.deepEqual(JSON.parse(h.storage.get(key(null))), newDraft, 'private content must not replace the durable new-task draft');
      assert.deepEqual(h.sends, []); assert.deepEqual(h.searches, []);
    } else {
      assert.deepEqual(h.attachments, ['owned-attachment'], 'project callers retain their existing attachment behavior');
      assert.equal(h.window._pendingProjectId, 'allowed-project');
      if (flow.name === 'inline Aide project') {
        assert.equal(h.field.value, incomingText.trim());
        assert.deepEqual(copy(h.window._pendingDocumentScope), incomingScope);
        assert.deepEqual(h.sends, [[incomingText.trim(), incomingScope, 'allowed-project']]);
        assert.deepEqual(h.searches, []);
        assert.deepEqual(JSON.parse(h.storage.get(key(null))), { text: incomingText.trim(), document_scope: incomingScope });
      } else {
        assert.equal(h.field.value, newDraft.text);
        assert.deepEqual(copy(h.window._pendingDocumentScope), newDraft.document_scope);
        assert.deepEqual(h.searches, [[incomingText.trim(), { documentScope: incomingScope }]]);
        assert.equal(h.location.searchParams.get('project_id'), 'allowed-project');
        assert.equal(h.effects.filter(effect => effect === 'load-andromeda').length, 1);
        assert.deepEqual(h.sends, []);
      }
    }
  });
}

for (const flow of flows.filter(flow => flow.private)) {
  test(`${flow.name}: already-private entry retains the undefined-save bypass`, async () => {
    const h = harness({ privateMode: true }); h.state.failure = 'SecurityError'; const stored = [...h.storage];
    assert.equal(await flow.run(h), flow.result);
    assert.equal(h.state.storageAccesses, 0); assert.deepEqual([...h.storage], stored);
    assert.equal(h.snapshot().privateMode, true); assert.deepEqual(h.active(), { id: null, generation: 8 });
    assert.deepEqual(h.attachments, []); assert.equal(h.window._pendingDocumentScope, null);
    assert.equal(h.field.value, flow.name === 'private day' ? incomingText : '');
    assert.deepEqual(h.notices, []);
  });
}

test('incognito entry retains the missing-composer undefined-save bypass', async () => {
  const h = harness({ missingComposer: true }); h.state.failure = 'SecurityError';
  assert.equal(await h.privateEntry(), undefined);
  assert.equal(h.state.storageAccesses, 0); assert.equal(h.snapshot().privateMode, true);
  assert.deepEqual(h.active(), { id: null, generation: 8 }); assert.deepEqual(h.attachments, []);
  assert.equal(h.effects.includes('focus-composer'), false);
});

test('unchanged private exit uses skipDraft and restores the normal new-task draft at quota', async () => {
  const h = harness({ privateMode: true }); h.state.failure = 'QuotaExceededError';
  const storedOutgoing = h.storage.get(key('outgoing'));
  assert.equal(await h.privateExit(), undefined);
  assert.deepEqual(h.requests, [['/api/sessions/outgoing', 'DELETE']]);
  assert.equal(h.snapshot().privateMode, false); assert.deepEqual(h.attachments, []);
  assert.deepEqual(h.active(), { id: null, generation: 8 });
  assert.equal(h.storage.get(key('outgoing')), storedOutgoing);
  assert.equal(h.storageCalls.some(([method, name]) => method === 'set' && name === key('outgoing')), false);
  assert.equal(h.field.value, newDraft.text);
  assert.deepEqual(copy(h.window._pendingDocumentScope), newDraft.document_scope);
});

for (const web of [false, true]) {
  test(`same-project ${web ? 'Andromeda' : 'Aide'} retains the existing path without a new task reset`, async () => {
    const h = harness(), active = h.active();
    assert.equal(await h.ask(incomingText, web, incomingScope, 'old-project', true), true);
    assert.deepEqual(h.active(), active); assert.equal(h.window._currentSession.id, 'outgoing');
    assert.equal(h.effects.includes('default-model'), false); assert.deepEqual(h.attachments, ['owned-attachment']);
    if (web) {
      assert.equal(h.field.value, outgoing.text);
      assert.deepEqual(h.searches, [[incomingText.trim(), { documentScope: incomingScope }]]);
      assert.equal(h.location.searchParams.get('project_id'), 'old-project');
      assert.deepEqual(h.sends, []);
    } else {
      assert.equal(h.field.value, incomingText.trim());
      assert.deepEqual(h.sends, [[incomingText.trim(), incomingScope, 'old-project']]);
      assert.deepEqual(h.searches, []);
    }
  });
}

for (const flow of flows.filter(flow => flow.view)) {
  test(`${flow.name}: existing declined navigation stops before saving or replacing work`, async () => {
    const h = harness(); h.state.navigateAllowed = false; const before = h.snapshot(), stored = [...h.storage];
    assert.equal(await flow.run(h), false); assert.deepEqual(h.snapshot(), before);
    assert.deepEqual([...h.storage], stored); assert.equal(h.state.storageAccesses, 0);
    assert.deepEqual(h.effects, []); assert.deepEqual(h.sends, []); assert.deepEqual(h.searches, []);
    assert.deepEqual(h.navigations, [flow.view]);
  });
}

test('inline Aide retains its busy-answer check before navigation or storage', async () => {
  const h = harness(); h.state.canSend = false; const before = h.snapshot();
  assert.equal(await h.ask(incomingText, false, incomingScope, 'allowed-project'), false);
  assert.deepEqual(h.snapshot(), before); assert.equal(h.state.storageAccesses, 0);
  assert.deepEqual(h.navigations, []); assert.deepEqual(h.effects, []); assert.deepEqual(h.sends, []);
  assert.match(h.notices[0], /wait for the current answer/);
});
