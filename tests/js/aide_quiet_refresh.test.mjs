import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function response(text = 'saved receipt', id = 'primary', ok = true) {
  return { ok, json: async () => ({ session: { id, primary: id === 'primary' }, messages: [{ role: 'assistant', content: text }] }) };
}

function harness({ space = 'aide', mode = 'conversation', busy = false, scrollTop = 140 } = {}) {
  const requests = [], renders = [], events = [], effects = [], timers = new Map(), frames = [];
  const chat = { scrollTop, scrollHeight: 1200, clientHeight: 600 };
  const composer = { value: 'keep my unsent draft', selectionStart: 7, selectionEnd: 14 };
  const messages = { editor: null, querySelector() { return this.editor; } };
  const document = {
    activeElement: composer,
    body: { dataset: { space, aideMode: mode } },
    getElementById: id => id === 'chat' ? chat : id === 'composer-ta' ? composer : id === 'messages' ? messages : null,
    dispatchEvent: event => events.push(event.type),
  };
  const location = { href: 'http://isolated.test/?view=chat#primary', hash: '#primary', search: '?view=chat' };
  const draftStore = new Map([['aide-draft-v2-primary', '{"text":"keep my unsent draft","document_scope":null}']]);
  let timerId = 0;
  let available = !busy;
  const window = {
    _currentSession: { id: 'primary', primary: true },
    _pendingDocumentScope: { kind: 'vault_document', path: 'notes/owned.md', expected_hash: 'fixture' },
    _canRefreshAideMessages: () => available,
    _enterChatView: () => effects.push('navigate'),
    _setMode: () => effects.push('mode'),
    addEventListener() {},
  };
  const context = vm.createContext({
    document, location, window, URL, URLSearchParams, console,
    CustomEvent: class { constructor(type) { this.type = type; } },
    fetch: url => { const request = { url, ...deferred() }; requests.push(request); return request.promise; },
    setTimeout: (callback, ms) => { timers.set(++timerId, { callback, ms }); return timerId; },
    clearTimeout: id => timers.delete(id),
    requestAnimationFrame: callback => frames.push(callback),
    localStorage: {
      getItem: key => draftStore.get(key) ?? null,
      setItem: (key, value) => { effects.push('draft write'); draftStore.set(key, value); },
      removeItem: key => { effects.push('draft removal'); draftStore.delete(key); },
    },
    renders, effects,
  });
  vm.runInContext(source + `
    renderMessages = messages => renders.push(messages.map(message => message.content));
    showMessages = () => effects.push('messages visible');
    saveDraft = () => { effects.push('save draft'); return true; };
    restoreDraft = () => effects.push('restore draft');
    replaceRouteUrl = () => effects.push('route');
    globalThis.subject = {
      refresh: refreshActiveSessionQuietly,
      activate: id => { _activeId = id; },
      advanceComposer: () => ++_composerGeneration,
      state: () => ({ active: _activeId, generation: _composerGeneration }),
    };
    _activeId = 'primary';
  `, context);
  return {
    ...context.subject, requests, renders, events, effects, timers, frames,
    window, document, location, chat, composer, messages, draftStore,
    busy: value => { available = !value; },
    runTimer: () => {
      const [id, timer] = timers.entries().next().value;
      timers.delete(id);
      return timer.callback();
    },
    runFrames: () => { while (frames.length) frames.shift()(); },
    state: () => JSON.parse(JSON.stringify(context.subject.state())),
  };
}

test('a receipt only fetches the exact active conversation', async () => {
  const h = harness();
  assert.equal(await h.refresh(), false);
  assert.equal(await h.refresh('archived'), false);
  assert.equal(h.requests.length, 0);
  const refresh = h.refresh('primary');
  assert.equal(h.requests[0].url, '/api/sessions/primary/history');
  h.requests[0].resolve(response());
  assert.equal(await refresh, true);
  assert.deepEqual(h.renders.map(row => [...row]), [['saved receipt']]);
});

for (const [space, mode] of [['aide', 'call'], ['aide', 'coding'], ['today', 'conversation']]) {
  test(`receipt refresh preserves route, ${space}/${mode}, focus, selection and draft`, async () => {
    const h = harness({ space, mode });
    const before = {
      route: { ...h.location }, draft: [...h.draftStore],
      input: { ...h.composer }, scope: h.window._pendingDocumentScope,
    };
    const refresh = h.refresh('primary');
    h.requests[0].resolve(response());
    assert.equal(await refresh, true);
    h.runFrames();
    assert.deepEqual(h.location, before.route);
    assert.deepEqual(h.document.body.dataset, { space, aideMode: mode });
    assert.deepEqual(h.composer, before.input);
    assert.equal(h.document.activeElement, h.composer);
    assert.deepEqual([...h.draftStore], before.draft);
    assert.equal(h.window._pendingDocumentScope, before.scope);
    assert.deepEqual(h.state(), { active: 'primary', generation: 0 });
    assert.deepEqual(h.effects, ['messages visible']);
    assert.equal(h.chat.scrollTop, 140);
    assert.deepEqual(h.events, ['alles:aide-session']);
  });
}

test('an active foreground response defers receipt loading until it becomes idle', async () => {
  const h = harness({ busy: true });
  assert.equal(await h.refresh('primary'), false);
  assert.equal(h.requests.length, 0);
  assert.equal(h.timers.size, 1);
  assert.equal(await h.runTimer(), false);
  assert.equal(h.requests.length, 0);
  assert.equal(h.timers.size, 1);
  h.busy(false);
  const refresh = h.runTimer();
  h.requests[0].resolve(response());
  assert.equal(await refresh, true);
  assert.equal(h.timers.size, 0);
  assert.equal(h.renders.length, 1);
});

test('a response that starts while history is loading defers the fetched receipt', async () => {
  const h = harness();
  const refresh = h.refresh('primary');
  h.busy(true);
  h.requests[0].resolve(response('stale before stream finished'));
  assert.equal(await refresh, false);
  assert.equal(h.renders.length, 0);
  assert.equal(h.timers.size, 1);
  h.busy(false);
  const retry = h.runTimer();
  h.requests[1].resolve(response('new history after stream finished'));
  assert.equal(await retry, true);
  assert.deepEqual(h.renders.map(row => [...row]), [['new history after stream finished']]);
});

for (const tagName of ['TEXTAREA', 'INPUT', 'DIV']) {
  test(`an open inline ${tagName === 'DIV' ? 'contenteditable' : tagName.toLowerCase()} edit keeps its draft until the editor closes`, async () => {
    const h = harness();
    const editor = { tagName, value: 'unsent change to an earlier message', selectionStart: 4, selectionEnd: 9 };
    if (tagName === 'DIV') editor.contentEditable = 'true';
    h.messages.editor = editor;
    // The edit remains protected even while focus is on another control.
    assert.equal(h.document.activeElement, h.composer);
    assert.equal(await h.refresh('primary'), false);
    assert.equal(h.requests.length, 0);
    assert.equal(h.messages.editor, editor);
    assert.equal(editor.value, 'unsent change to an earlier message');
    assert.equal(await h.runTimer(), false);
    assert.equal(h.renders.length, 0);
    h.messages.editor = null;
    const refresh = h.runTimer();
    h.requests[0].resolve(response('receipt after edit closed'));
    assert.equal(await refresh, true);
    assert.deepEqual(h.renders.map(row => [...row]), [['receipt after edit closed']]);
    assert.equal(h.composer.value, 'keep my unsent draft');
  });
}

test('an inline edit opened during the history request prevents the returned tree from replacing it', async () => {
  const h = harness();
  const refresh = h.refresh('primary');
  const editor = { tagName: 'TEXTAREA', value: 'new unsent message edit' };
  h.messages.editor = editor;
  h.document.activeElement = editor;
  h.requests[0].resolve(response('history before the edit'));
  assert.equal(await refresh, false);
  assert.equal(h.renders.length, 0);
  assert.equal(h.document.activeElement, editor);
  assert.equal(h.messages.editor.value, 'new unsent message edit');
  h.messages.editor = null;
  h.document.activeElement = h.composer;
  const retry = h.runTimer();
  h.requests[1].resolve(response('history after the edit'));
  assert.equal(await retry, true);
  assert.deepEqual(h.renders.map(row => [...row]), [['history after the edit']]);
});

test('switching conversations discards an in-flight receipt without touching the new owner', async () => {
  const h = harness();
  const refresh = h.refresh('primary');
  h.activate('archived');
  h.window._currentSession = { id: 'archived' };
  h.requests[0].resolve(response());
  assert.equal(await refresh, false);
  assert.equal(h.window._currentSession.id, 'archived');
  assert.equal(h.renders.length, 0);
  assert.equal(h.events.length, 0);
});

test('a deferred receipt expires when its conversation is no longer active', async () => {
  const h = harness({ busy: true });
  await h.refresh('primary');
  h.activate('archived');
  h.busy(false);
  assert.equal(await h.runTimer(), false);
  assert.equal(h.requests.length, 0);
  assert.equal(h.timers.size, 0);
});

test('a newer composer generation discards an in-flight history response', async () => {
  const h = harness();
  const refresh = h.refresh('primary');
  h.advanceComposer();
  h.requests[0].resolve(response());
  assert.equal(await refresh, false);
  assert.equal(h.renders.length, 0);
  assert.deepEqual(h.state(), { active: 'primary', generation: 1 });
});

test('an older overlapping history request cannot replace the latest receipt', async () => {
  const h = harness();
  const first = h.refresh('primary');
  const second = h.refresh('primary');
  h.requests[1].resolve(response('latest'));
  assert.equal(await second, true);
  h.requests[0].resolve(response('older'));
  assert.equal(await first, false);
  assert.deepEqual(h.renders.map(row => [...row]), [['latest']]);
});

test('history failure preserves the currently rendered conversation and draft', async () => {
  for (const failure of ['http', 'network']) {
    const h = harness();
    const session = h.window._currentSession;
    const refresh = h.refresh('primary');
    if (failure === 'http') h.requests[0].resolve(response('', 'primary', false));
    else h.requests[0].reject(new Error('offline'));
    assert.equal(await refresh, false);
    assert.equal(h.window._currentSession, session);
    assert.equal(h.renders.length, 0);
    assert.equal(h.composer.value, 'keep my unsent draft');
  }
});

test('receipt rendering retains the reader position or follows the existing end position', async () => {
  const h = harness({ scrollTop: 590 });
  const refresh = h.refresh('primary');
  h.requests[0].resolve(response());
  assert.equal(await refresh, true);
  h.chat.scrollHeight = 1500;
  h.runFrames();
  assert.equal(h.chat.scrollTop, 1500);
});
