import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');
const strip = source => source.replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '').replace(/^export /gm, '');
const sessionsSource = strip(read('sessions')).replace("import('./aidebackground.js?v=246')", 'Promise.resolve({ reattachBackgroundWork() {} })');
const centralSource = strip(read('aidecentral'));
const app = read('app');
const chat = read('chat');
const functionSource = (source, name) => {
  const value = source.match(new RegExp(`^(?:export )?(?:async )?function ${name}\\([^]*?^}`, 'm'))?.[0];
  assert.ok(value, `execute the actual ${name} implementation`);
  return value.replace(/^export /gm, '');
};
function clickHandler(id) {
  const start = app.indexOf(`  document.getElementById('${id}')?.addEventListener('click', async () => {`);
  const end = app.indexOf('\n  });', start);
  assert.ok(start >= 0 && end > start);
  return app.slice(start, end + '\n  });'.length);
}
const searchSource = app.slice(app.indexOf('window._openSearchResult = async ('), app.indexOf('\nasync function revealLinkedRecord'));
const askSource = app.slice(app.indexOf('window._askInChat = async ('), app.indexOf('\nconst showModelsView'));
const flush = () => new Promise(resolve => setImmediate(resolve));
const history = (id, options = {}) => ({ session: { id, name: id, primary: id === 'primary', ...options }, messages: [{ role: 'assistant', content: `history for ${id}` }] });

function harness({ active = 'archived', hash = '', view = 'today', index = [], privateMode = false } = {}) {
  const requests = [], renders = [], events = [], newChats = [], sends = [], notices = [], shown = [], failures = [];
  const state = { privateMode, view, mode: 'conversation', saveAllowed: true };
  const location = new URL(`http://isolated.test/?view=${view}${hash ? '#' + hash : ''}`);
  const storage = new Map([['aide-draft-v2-primary', JSON.stringify({ text: 'main draft', document_scope: null })]]);
  const nodes = new Map();
  const document = {
    body: { dataset: { space: view === 'chat' ? 'aide' : view, aideMode: 'conversation' } },
    activeElement: null,
    getElementById: id => {
      if (!nodes.has(id)) nodes.set(id, {
        id, value: id === 'composer-ta' ? 'archived draft' : '', style: { display: id === 'wiki-view' ? 'none' : '' },
        hidden: false, inert: false, attributes: {}, listeners: {}, innerHTML: '',
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, handler) { this.listeners[name] = handler; },
        dispatchEvent() {},
        focus() { document.activeElement = this; },
      });
      return nodes.get(id);
    },
    querySelectorAll: () => [],
    dispatchEvent: event => { events.push(event.type); },
  };
  const window = {
    _currentSession: active ? { id: active, incognito: privateMode } : null,
    _pendingDocumentScope: null,
    addEventListener() {},
    _setAideArchiveOpen() {},
    _setAideDocumentScope: scope => { window._pendingDocumentScope = scope; },
    _setMode: mode => { state.mode = mode; },
  };
  const showChatView = ({ preserveRecord = false } = {}) => {
    if (!preserveRecord) {
      location.searchParams.delete('record');
      location.searchParams.delete('record_view');
    }
    state.view = 'chat'; document.body.dataset.space = 'aide';
    state.mode = document.body.dataset.aideMode = 'conversation';
  };
  window._enterChatView = showChatView;
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    window, document, location, URL, URLSearchParams, Event: class {},
    CustomEvent: class { constructor(type) { this.type = type; } },
    console: { error: (...args) => failures.push(args) },
    fetch: (url, options = {}) => {
      let resolve;
      const promise = new Promise(done => { resolve = done; });
      requests.push({ url, options, resolve, settled: false });
      if (options.method === 'DELETE') resolve({ ok: true, json: async () => ({}) });
      return promise;
    },
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => { if (!state.saveAllowed) throw new Error('storage unavailable'); storage.set(key, value); },
      removeItem: key => storage.delete(key),
    },
    replaceRouteUrl: url => { location.href = String(url); },
    toast: message => notices.push(message),
    isIncognitoMode: () => state.privateMode,
    setIncognitoMode: value => { state.privateMode = value; },
    loadAnswerNoteRecovery() {}, loadAnswerTaskRecovery() {},
    getProjects: () => [{ id: 'project-one' }], selectAideDefault() {}, restoreSessionModel() {},
    showChatView, discardAttachments: async () => {},
    prepareMailNavigation: async () => state.navigateAllowed !== false, prepareTaskNavigation: async () => true,
    singleHost: () => true, groupRouteFor: () => null,
    resolveCompatibilityRoute: ({ view: target }) => ({ host: target === 'chat' ? 'aide' : '', view: target }),
    _syncLocalViewUrl: (_route, target) => { location.searchParams.set('view', target); },
    renderLocalView: async target => {
      state.view = target; shown.push(target); document.body.dataset.space = target === 'chat' ? 'aide' : target;
      state.afterRender?.();
    },
    readRecordTarget: () => null, openSettings() {},
    withRecordTarget: (url, record) => { const target = new URL(url); target.searchParams.set('record', record.id); return target; },
    _replaceHistoryUrl: url => { location.href = String(url); },
    urlForApp: () => 'http://isolated.test/',
    index, renders, newChats, sends, state,
  });
  const sessions = vm.runInContext(`(() => {
    ${sessionsSource}
    _activeId = ${JSON.stringify(active)};
    loadSessions = async () => { _allSessions = index; _sessionsLoaded = true; return true; };
    renderMessages = messages => renders.push(messages.map(message => message.content));
    showMessages = () => {};
    scrollDown = () => true;
    showWelcome = () => {};
    updateSessionHeader = () => {};
    focusSessionMessage = id => { state.message = id; return true; };
    const originalNewChat = newChat;
    newChat = options => { newChats.push(options || {}); return originalNewChat(options); };
    return { initSessions, selectSession, newChat, saveDraft, setPrimaryConversationUnavailable, getActiveId,
      generation: () => _composerGeneration, setActive: id => { _activeId = id; } };
  })()`, context);
  Object.assign(context, sessions);
  const central = vm.runInContext(`(() => {
    ${centralSource}
    closeContext = () => {};
    syncHistory = () => {};
    setMode = async value => { state.mode = value; document.body.dataset.aideMode = value; };
    return { openPrimaryConversation };
  })()`, context);
  window._showPrimaryAide = central.openPrimaryConversation;
  vm.runInContext(`let _streaming = false, _backgroundLaunching = false;
    ${functionSource(chat, 'getSendBlockReason')}
    ${functionSource(chat, 'canSendMessage')}
    ${functionSource(chat, 'sendMessage')}
    globalThis.sendWhenBlocked = sendMessage;
    globalThis.showSendIssue = message => state.sendIssue = message;
    globalThis.setBusy = ({ streaming = false, backgroundLaunching = false } = {}) => {
      _streaming = streaming; _backgroundLaunching = backgroundLaunching;
    };
  `, context);
  // Successful sends are captured at the existing application boundary; no
  // provider request or database mutation is needed to exercise handoff routing.
  context.sendMessage = async text => sends.push({ text, session: sessions.getActiveId(), project: window._pendingProjectId, privateMode: state.privateMode });
  vm.runInContext(`let _navigationGeneration = 0; const _afterlifeFlags = {};
    ${functionSource(app, 'navigateTo')}
    ${searchSource}
    ${askSource}
    ${functionSource(app, 'showPrivateDayDraft')}
    ${clickHandler('incognito-btn')}
    ${clickHandler('incognito-exit')}
    globalThis.navigation = { navigateTo, showPrivateDayDraft };
  `, context);
  return {
    ...sessions, ...central, ...context.navigation, window, state, nodes, document, location,
    storage, requests, renders, events, newChats, sends, notices, shown, failures,
    canSend: context.canSendMessage, blockedSend: context.sendWhenBlocked,
    setBusy: context.setBusy,
    openSearch: (...args) => window._openSearchResult(...args),
    ask: (...args) => window._askInChat(...args),
    privateEntry: () => nodes.get('incognito-btn').listeners.click(),
    privateExit: () => nodes.get('incognito-exit').listeners.click(),
    reply: async (url, payload, ok = true) => {
      for (let attempt = 0; attempt < 5 && !requests.some(item => item.url === url && !item.settled); attempt++) await flush();
      const request = requests.find(item => item.url === url && !item.settled);
      assert.ok(request, `expected request for ${url}`);
      request.settled = true; request.resolve({ ok, json: async () => payload });
      await flush();
    },
  };
}

test('ordinary Aide entry selects primary and preserves the archived draft', async () => {
  const h = harness();
  const navigation = h.navigateTo('chat');
  await h.reply('/api/aide/conversation', { id: 'primary' });
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await navigation, true);
  assert.equal(h.getActiveId(), 'primary');
  assert.equal(h.window._currentSession.id, 'primary');
  assert.equal(JSON.parse(h.storage.get('aide-draft-v2-archived')).text, 'archived draft');
  assert.equal(h.nodes.get('composer-ta').value, 'main draft');
  assert.equal(h.location.hash, '#primary');
  assert.equal(h.location.searchParams.get('view'), 'chat');
  assert.equal(h.newChats.length, 0);
});

test('canonical startup failure blocks sending instead of creating a second default conversation', async () => {
  const h = harness({ active: null, view: 'chat' });
  const boot = h.initSessions();
  await h.reply('/api/aide/conversation', { detail: 'unavailable' }, false);
  await boot;
  assert.equal(h.window._aidePrimaryUnavailable, true);
  assert.equal(h.nodes.get('composer-outer').inert, true);
  assert.equal(h.canSend(), false);
  await h.blockedSend('a question during recovery');
  assert.match(h.state.sendIssue, /reopen your main conversation/);
  assert.equal(h.newChats.length, 0);
  assert.ok(h.requests.every(request => !request.options.method));
  assert.ok(h.events.includes('alles:aide-primary-unavailable'));
});

test('failed primary history retains no owner and retries the same canonical id', async () => {
  const h = harness({ active: null, view: 'chat', index: [{ id: 'primary', name: 'Aide', primary: true }] });
  const boot = h.initSessions();
  await h.reply('/api/sessions/primary/history', { detail: 'unavailable' }, false);
  await boot;
  assert.equal(h.getActiveId(), null);
  assert.equal(h.window._currentSession, null);
  assert.equal(h.canSend(), false);
  const retry = h.openPrimaryConversation();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await retry, true);
  assert.equal(h.window._currentSession.id, 'primary');
  assert.equal(h.canSend(), true);
  assert.equal(h.nodes.get('composer-outer').inert, false);
  assert.equal(h.newChats.length, 0);
});

test('an exact historical message link loads its original thread without consulting primary', async () => {
  const h = harness({ active: null, hash: 'archived', view: 'chat', index: [{ id: 'archived', name: 'Earlier' }] });
  h.location.searchParams.set('message', 'original-reply');
  const boot = h.initSessions();
  await h.reply('/api/sessions/archived/history', history('archived'));
  await boot;
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.state.message, 'original-reply');
  assert.equal(h.location.hash, '#archived');
  assert.equal(h.location.searchParams.get('message'), 'original-reply');
  assert.deepEqual(h.requests.map(request => request.url), ['/api/sessions/archived/history']);
});

test('opening an exact search result preserves its session owner', async () => {
  const h = harness({ active: 'primary' });
  const open = h.openSearch('chat', 'archived', 'original-reply');
  await h.reply('/api/sessions/archived/history', history('archived'));
  assert.equal(await open, true);
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.state.message, 'original-reply');
  assert.equal(h.requests.some(request => request.url === '/api/aide/conversation'), false);
});

test('explicit project handoff retains project ownership without resolving primary', async () => {
  const h = harness();
  assert.equal(await h.ask('review this project', false, null, 'project-one'), true);
  assert.equal(h.window._pendingProjectId, 'project-one');
  assert.equal(h.getActiveId(), null);
  assert.equal(h.newChats.length, 1);
  assert.deepEqual(h.sends, [{ text: 'review this project', session: null, project: 'project-one', privateMode: false }]);
  assert.equal(h.requests.length, 0);
});

test('private draft and private entry leave coding mode without consulting primary', async () => {
  const h = harness({ view: 'chat' });
  h.state.mode = h.document.body.dataset.aideMode = 'coding';
  await h.privateEntry();
  assert.equal(h.state.mode, 'conversation');
  assert.equal(h.state.privateMode, true);
  assert.equal(h.getActiveId(), null);
  assert.equal(h.requests.length, 0);
  assert.equal(await h.showPrivateDayDraft('private day question'), true);
  assert.equal(h.nodes.get('composer-ta').value, 'private day question');
  assert.equal(h.state.privateMode, true);
  assert.equal(h.requests.length, 0);
});

test('private exit deletes only its private thread and returns to the canonical conversation', async () => {
  const h = harness({ active: 'private-thread', view: 'chat', privateMode: true });
  const exit = h.privateExit();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  await h.reply('/api/sessions/primary/history', history('primary'));
  await exit;
  assert.deepEqual(h.requests.filter(request => request.options.method).map(request => [request.url, request.options.method]), [['/api/sessions/private-thread', 'DELETE']]);
  assert.equal(h.state.privateMode, false);
  assert.equal(h.getActiveId(), 'primary');
  assert.equal(h.nodes.get('composer-ta').value, 'main draft');
});

test('a failed canonical return after private exit remains blocked and never posts a replacement session', async () => {
  const h = harness({ active: 'private-thread', view: 'chat', privateMode: true });
  const exit = h.privateExit();
  await h.reply('/api/aide/conversation', { detail: 'unavailable' }, false);
  await exit;
  assert.equal(h.state.privateMode, false);
  assert.equal(h.canSend(), false);
  assert.equal(h.nodes.get('composer-outer').inert, true);
  await h.blockedSend('do not create another default');
  assert.equal(h.requests.some(request => request.options.method === 'POST'), false);
});

test('navigation superseded during primary resolution cannot take over the newer app', async () => {
  const h = harness();
  const first = h.navigateTo('chat');
  await flush();
  assert.equal(await h.navigateTo('today'), true);
  await h.reply('/api/aide/conversation', { id: 'primary' });
  assert.equal(await first, false);
  assert.equal(h.state.view, 'today');
  assert.equal(h.renders.length, 0);
  assert.equal(h.requests.some(request => request.url.includes('/history')), false);
});

test('navigation superseded during history loading cannot render into the newer app', async () => {
  const h = harness();
  const first = h.navigateTo('chat');
  await h.reply('/api/aide/conversation', { id: 'primary' });
  assert.equal(await h.navigateTo('today'), true);
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await first, false);
  assert.equal(h.state.view, 'today');
  assert.equal(h.renders.length, 0);
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.window._aidePrimaryUnavailable, undefined);
});

test('a stale exact-session selection cannot replace the newer selected history', async () => {
  const h = harness();
  const first = h.selectSession('older');
  const second = h.selectSession('newer');
  await h.reply('/api/sessions/newer/history', history('newer'));
  assert.equal(await second, true);
  await h.reply('/api/sessions/older/history', history('older'));
  assert.equal(await first, false);
  assert.equal(h.window._currentSession.id, 'newer');
  assert.deepEqual(h.renders.map(row => [...row]), [['history for newer']]);
});

test('failed archive history keeps the visible conversation, draft and send owner together', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  const route = h.location.href;
  const draft = h.document.getElementById('composer-ta').value;
  const selection = h.selectSession('unavailable-archive');
  await h.reply('/api/sessions/unavailable-archive/history', { detail: 'unavailable' }, false);
  assert.equal(await selection, false);
  assert.equal(h.getActiveId(), 'archived');
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.location.href, route);
  assert.equal(h.nodes.get('composer-ta').value, draft);
  assert.equal(h.renders.length, 0);
  assert.equal(h.canSend(), true);
});

test('typing while archive history loads is saved to the outgoing conversation before switching', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  const selection = h.selectSession('other-archive');
  h.document.getElementById('composer-ta').value = 'new text while the history request is pending';
  await h.reply('/api/sessions/other-archive/history', history('other-archive'));
  assert.equal(await selection, true);
  assert.equal(JSON.parse(h.storage.get('aide-draft-v2-archived')).text, 'new text while the history request is pending');
  assert.equal(h.getActiveId(), 'other-archive');
  assert.equal(h.window._currentSession.id, 'other-archive');
});

for (const [label, payload] of [
  ['wrong conversation owner', history('wrong-archive')],
  ['missing messages array', { session: { id: 'other-archive' }, messages: null }],
]) {
  test(`${label} cannot commit a misleading archive selection`, async () => {
    const h = harness({ hash: 'archived', view: 'chat' });
    const route = h.location.href;
    const selection = h.selectSession('other-archive');
    await h.reply('/api/sessions/other-archive/history', payload);
    assert.equal(await selection, false);
    assert.equal(h.getActiveId(), 'archived');
    assert.equal(h.window._currentSession.id, 'archived');
    assert.equal(h.location.href, route);
    assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
    assert.equal(h.renders.length, 0);
  });
}

test('a storage failure after history fetch preserves input typed during the request', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  const route = h.location.href;
  const selection = h.selectSession('other-archive');
  h.nodes.get('composer-ta').value = 'new text that must stay in this tab';
  h.state.saveAllowed = false;
  await h.reply('/api/sessions/other-archive/history', history('other-archive'));
  assert.equal(await selection, false);
  assert.equal(h.getActiveId(), 'archived');
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.location.href, route);
  assert.equal(h.nodes.get('composer-ta').value, 'new text that must stay in this tab');
  assert.equal(h.renders.length, 0);
});

test('an intentional new conversation invalidates pending archive history', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  const selection = h.selectSession('other-archive');
  h.newChat();
  h.nodes.get('composer-ta').value = 'a new independent draft';
  await h.reply('/api/sessions/other-archive/history', history('other-archive'));
  assert.equal(await selection, false);
  assert.equal(h.getActiveId(), null);
  assert.equal(h.window._currentSession, null);
  assert.equal(h.nodes.get('composer-ta').value, 'a new independent draft');
  assert.equal(h.renders.length, 0);
});

test('a storage veto prevents canonical switching before its history can overwrite an archived draft', async () => {
  const h = harness();
  h.state.saveAllowed = false;
  const open = h.openPrimaryConversation();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  assert.equal(await open, false);
  assert.equal(h.getActiveId(), 'archived');
  assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
  assert.equal(h.renders.length, 0);
  assert.equal(h.requests.some(request => request.url.includes('/history')), false);
});

const documentScope = path => ({ kind: 'vault_documents', documents: [{ path, expected_hash: 'saved-hash' }] });
const copy = value => JSON.parse(JSON.stringify(value));
const assertNotBusyWarning = h => assert.equal(h.notices.some(message => /current answer|stop it first/i.test(message)), false,
  'an unavailable conversation is not a running answer');

test('handoff after canonical failure requires explicit retry before a repeated request can send', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  const outgoingScope = documentScope('unfinished-note.md');
  h.window._pendingDocumentScope = outgoingScope;
  h.setPrimaryConversationUnavailable(true);
  assert.equal(await h.ask('use the selected source', false, documentScope('selected-note.md')), false);
  assert.equal(h.sends.length, 0);
  assert.equal(h.requests.length, 0, 'a blocked handoff must not automatically retry or send');
  assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
  assert.deepEqual(copy(h.window._pendingDocumentScope), outgoingScope);
  assertNotBusyWarning(h);
  assert.match(h.notices.at(-1), /conversation.*retry/i);
  assert.equal(h.events.filter(type => type === 'alles:aide-primary-unavailable').length, 2,
    'the blocked handoff reveals the existing recovery UI again');
  const retry = h.openPrimaryConversation();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  assert.equal(h.sends.length, 0);
  assert.equal(h.getActiveId(), 'archived');
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await retry, true);
  assert.equal(h.sends.length, 0, 'retry restores ownership without replaying the rejected handoff');
  assert.equal(await h.ask('use the selected source', false, documentScope('selected-note.md')), true);
  assert.deepEqual(h.sends, [{ text: 'use the selected source', session: 'primary', project: undefined, privateMode: false }]);
  assert.deepEqual(JSON.parse(h.storage.get('aide-draft-v2-archived')), { text: 'archived draft', document_scope: outgoingScope });
  assert.equal(h.window._aidePrimaryUnavailable, false);
  assert.equal(h.nodes.get('composer-outer').inert, false);
  assert.equal(h.newChats.length, 0);
  assertNotBusyWarning(h);
});

for (const stage of ['resolution', 'history']) {
  test(`handoff recovery ${stage} failure keeps the original draft and owner without sending`, async () => {
    const h = harness({ hash: 'archived', view: 'chat' });
    const outgoingScope = documentScope('unfinished-note.md');
    h.window._pendingDocumentScope = outgoingScope;
    h.setPrimaryConversationUnavailable(true);
    const beforeUrl = h.location.href;
    assert.equal(await h.ask('a source question', false, documentScope('selected-note.md')), false);
    assert.equal(h.requests.length, 0);
    const retry = h.openPrimaryConversation();
    if (stage === 'resolution') await h.reply('/api/aide/conversation', { detail: 'unavailable' }, false);
    else {
      await h.reply('/api/aide/conversation', { id: 'primary' });
      await h.reply('/api/sessions/primary/history', { detail: 'unavailable' }, false);
    }
    assert.equal(await retry, false);
    const requestCount = h.requests.length;
    assert.equal(await h.ask('a source question', false, documentScope('selected-note.md')), false);
    assert.equal(h.requests.length, requestCount, 'another handoff cannot silently retry a failed recovery');
    assert.equal(h.getActiveId(), 'archived');
    assert.equal(h.window._currentSession.id, 'archived');
    assert.equal(h.location.href, beforeUrl);
    assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
    assert.deepEqual(copy(h.window._pendingDocumentScope), outgoingScope);
    assert.equal(h.sends.length, 0);
    assert.equal(h.newChats.length, 0);
    assert.equal(h.window._aidePrimaryUnavailable, true);
    assert.equal(h.nodes.get('composer-outer').inert, true);
    assertNotBusyWarning(h);
  });
}

test('project handoff stays blocked until explicit primary recovery then establishes the requested project owner', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  h.setPrimaryConversationUnavailable(true);
  assert.equal(await h.ask('review this project', false, null, 'project-one'), false);
  assert.equal(h.getActiveId(), 'archived');
  assert.equal(h.newChats.length, 0);
  assert.equal(h.requests.length, 0);
  assert.equal(h.sends.length, 0);
  assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
  assertNotBusyWarning(h);
  const retry = h.openPrimaryConversation();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await retry, true);
  assert.equal(await h.ask('review this project', false, null, 'project-one'), true);
  assert.equal(h.window._pendingProjectId, 'project-one');
  assert.equal(h.window._aidePrimaryUnavailable, false);
  assert.equal(h.getActiveId(), null);
  assert.equal(h.newChats.length, 1);
  assert.deepEqual(h.sends, [{ text: 'review this project', session: null, project: 'project-one', privateMode: false }]);
  assert.equal(JSON.parse(h.storage.get('aide-draft-v2-archived')).text, 'archived draft');
  assert.equal(h.requests.length, 2, 'only the explicit retry resolves and loads the canonical conversation');
  assertNotBusyWarning(h);
});

for (const busy of ['streaming', 'backgroundLaunching']) {
  test(`real ${busy} still blocks a handoff before navigation even with canonical failure`, async () => {
    const h = harness({ hash: 'archived', view: 'chat' });
    h.setPrimaryConversationUnavailable(true);
    h.setBusy({ [busy]: true });
    const beforeUrl = h.location.href;
    assert.equal(await h.ask('review this project', false, null, 'project-one'), false);
    assert.equal(h.requests.length, 0);
    assert.equal(h.sends.length, 0);
    assert.equal(h.newChats.length, 0);
    assert.equal(h.location.href, beforeUrl);
    assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
    assert.equal(h.getActiveId(), 'archived');
    assert.match(h.notices.at(-1), /current answer|busy/i);
  });
}

test('a response that becomes busy during recovery cannot receive the pending handoff', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  const ask = h.ask('do not send into a concurrent response');
  await h.reply('/api/aide/conversation', { id: 'primary' });
  h.setBusy({ streaming: true });
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await ask, false);
  assert.equal(h.sends.length, 0);
  assert.notEqual(h.nodes.get('composer-ta').value, 'do not send into a concurrent response');
  assert.equal(h.newChats.length, 0);
});

test('explicit handoff recovery preserves newer outgoing text and scope typed during history loading', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  h.setPrimaryConversationUnavailable(true);
  assert.equal(await h.ask('original requested handoff', false, documentScope('selected-note.md')), false);
  const retry = h.openPrimaryConversation();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  h.nodes.get('composer-ta').value = 'newer unsent outgoing text';
  h.window._pendingDocumentScope = documentScope('newer-note.md');
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await retry, true);
  assert.deepEqual(JSON.parse(h.storage.get('aide-draft-v2-archived')), {
    text: 'newer unsent outgoing text', document_scope: documentScope('newer-note.md'),
  });
  assert.equal(h.sends.length, 0);
  assert.equal(await h.ask('original requested handoff', false, documentScope('selected-note.md')), true);
  assert.equal(h.sends.length, 1);
  assert.equal(h.sends[0].session, 'primary');
  assert.equal(h.sends[0].text, 'original requested handoff');
});

for (const stage of ['before history', 'after history request']) {
  test(`storage denial ${stage} aborts handoff recovery without replacing the pending draft`, async () => {
    const h = harness({ hash: 'archived', view: 'chat' });
    h.setPrimaryConversationUnavailable(true);
    if (stage === 'before history') h.state.saveAllowed = false;
    assert.equal(await h.ask('do not replace my draft'), false);
    const retry = h.openPrimaryConversation();
    await h.reply('/api/aide/conversation', { id: 'primary' });
    if (stage === 'after history request') {
      h.nodes.get('composer-ta').value = 'newer text that cannot be saved';
      h.window._pendingDocumentScope = documentScope('newer-note.md');
      h.state.saveAllowed = false;
      await h.reply('/api/sessions/primary/history', history('primary'));
    }
    assert.equal(await retry, false);
    assert.equal(h.sends.length, 0);
    assert.equal(h.newChats.length, 0);
    assert.equal(h.getActiveId(), 'archived');
    assert.equal(h.window._currentSession.id, 'archived');
    assert.equal(h.nodes.get('composer-ta').value, stage === 'before history' ? 'archived draft' : 'newer text that cannot be saved');
    if (stage === 'after history request') assert.deepEqual(copy(h.window._pendingDocumentScope), documentScope('newer-note.md'));
    assert.match(h.notices.join(' '), /keep this tab open/i);
    assertNotBusyWarning(h);
  });
}

test('project handoff cannot bypass unavailable ownership even when draft storage is denied', async () => {
  const h = harness({ hash: 'archived', view: 'chat' });
  h.setPrimaryConversationUnavailable(true);
  h.state.saveAllowed = false;
  assert.equal(await h.ask('review this project', false, null, 'project-one'), false);
  assert.equal(h.getActiveId(), 'archived');
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
  assert.equal(h.window._pendingProjectId, undefined);
  assert.equal(h.sends.length, 0);
  assert.equal(h.requests.length, 0);
  assert.match(h.notices.join(' '), /conversation|retry|reopen/i);
  assertNotBusyWarning(h);
});

test('same-owner canonical recovery preserves newer primary input before applying a handoff', async () => {
  const h = harness({ active: 'primary', hash: 'primary', view: 'chat' });
  h.setPrimaryConversationUnavailable(true);
  assert.equal(await h.ask('a separate source handoff'), false);
  const retry = h.openPrimaryConversation();
  await h.reply('/api/aide/conversation', { id: 'primary' });
  h.nodes.get('composer-ta').value = 'latest unsent primary draft';
  h.window._pendingDocumentScope = documentScope('primary-note.md');
  await h.reply('/api/sessions/primary/history', history('primary'));
  assert.equal(await retry, true);
  assert.equal(h.nodes.get('composer-ta').value, 'latest unsent primary draft');
  assert.deepEqual(copy(h.window._pendingDocumentScope), documentScope('primary-note.md'));
  assert.equal(h.sends.length, 0);
  assert.equal(await h.ask('a separate source handoff'), true);
  assert.equal(h.sends.length, 1);
  assert.equal(h.sends[0].session, 'primary');
  assert.equal(h.sends[0].text, 'a separate source handoff');
});

test('a declined navigation leaves canonical recovery and the source draft in their original app', async () => {
  const h = harness({ hash: 'archived', view: 'today' });
  h.setPrimaryConversationUnavailable(true);
  h.state.navigateAllowed = false;
  h.window._pendingDocumentScope = documentScope('unfinished-note.md');
  const beforeUrl = h.location.href;
  const eventCount = h.events.length;
  assert.equal(await h.ask('do not discard the pending work', false, documentScope('selected-note.md')), false);
  assert.equal(h.state.view, 'today');
  assert.equal(h.location.href, beforeUrl);
  assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
  assert.deepEqual(copy(h.window._pendingDocumentScope), documentScope('unfinished-note.md'));
  assert.equal(h.events.length, eventCount, 'no recovery dialog is opened over an app that refused navigation');
  assert.equal(h.requests.length, 0);
  assert.equal(h.sends.length, 0);
  assert.equal(h.newChats.length, 0);
  assert.equal(h.notices.length, 0);
});

test('canonical failure that appears during guarded navigation blocks a project handoff before owner or draft changes', async () => {
  const h = harness({ hash: 'archived', view: 'today' });
  h.window._pendingDocumentScope = documentScope('unfinished-note.md');
  h.state.afterRender = () => { h.setPrimaryConversationUnavailable(true); };
  assert.equal(await h.ask('do not send this late handoff', false, documentScope('selected-note.md'), 'project-one'), false);
  assert.equal(h.getActiveId(), 'archived');
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.nodes.get('composer-ta').value, 'archived draft');
  assert.deepEqual(copy(h.window._pendingDocumentScope), documentScope('unfinished-note.md'));
  assert.equal(h.window._pendingProjectId, undefined);
  assert.equal(h.newChats.length, 0);
  assert.equal(h.sends.length, 0);
  assert.equal(h.requests.length, 0);
  assert.match(h.notices.at(-1), /conversation.*retry/i);
  assertNotBusyWarning(h);
});

test('boot retains a linked run while an intentional conversation switch clears it', async () => {
  const h = harness({ active: null, view: 'chat', index: [{ id: 'primary', primary: true }] });
  h.location.searchParams.set('record', 'saved-run');
  h.location.searchParams.set('record_view', 'chat');
  const boot = h.initSessions();
  await h.reply('/api/sessions/primary/history', history('primary'));
  await boot;
  assert.equal(h.location.searchParams.get('record'), 'saved-run');
  const selected = h.selectSession('archived');
  await h.reply('/api/sessions/archived/history', history('archived'));
  assert.equal(await selected, true);
  assert.equal(h.location.searchParams.has('record'), false);
});
