import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');
const moduleBody = source => source.replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '').replace(/^export /gm, '');
const settle = async () => { for (let index = 0; index < 10; index++) await Promise.resolve(); };

function fixture({ space = 'aide', mode = 'conversation', busy = false } = {}) {
  const requests = [], effects = [], renders = [], timers = [], errors = [];
  const archive = { hidden: false };
  const composer = { value: 'keep this exact newer draft', selectionStart: 3, selectionEnd: 9 };
  const chat = { scrollTop: 120, scrollHeight: 900, clientHeight: 400 };
  const messages = { querySelector: () => null };
  const scope = { kind: 'vault_document', path: 'owned.md', expected_hash: 'synthetic' };
  const location = new URL('http://127.0.0.1:1/?view=' + space + '#owner');
  const document = {
    activeElement: archive,
    body: { dataset: { space, aideMode: mode } },
    getElementById: id => ({ 'composer-ta': composer, chat, messages, 'aide-sidebar': archive })[id] || null,
    querySelectorAll: () => [], dispatchEvent() {},
  };
  const window = {
    _currentSession: { id: 'owner' }, _pendingDocumentScope: scope,
    _canRefreshAideMessages: () => !busy,
    _enterChatView() { effects.push('navigate'); archive.hidden = true; document.body.dataset.space = 'aide'; document.body.dataset.aideMode = 'conversation'; },
    _setMode: () => effects.push('mode'), addEventListener() {},
  };
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    window, document, location, URL, URLSearchParams,
    console: { error: (...args) => errors.push(args.map(String).join(' ')) },
    CustomEvent: class { constructor(type) { this.type = type; } },
    fetch: url => new Promise(resolve => requests.push({ url, resolve })),
    setTimeout: callback => { timers.push(callback); return timers.length; }, clearTimeout() {},
    requestAnimationFrame: callback => callback(),
    restoreSessionModel: () => effects.push('model'),
    renders, effects,
  });
  vm.runInContext(moduleBody(read('sessions')) + `
    renderMessages = messages => renders.push(messages.map(message => message.content));
    showMessages = () => effects.push('messages visible');
    updateSessionHeader = () => {};
    replaceRouteUrl = () => effects.push('route');
    _activeId = 'owner';
    globalThis.activate = id => { _activeId = id; window._currentSession = { id }; };
  `, context);
  return { window, document, location, archive, composer, scope, requests, effects, renders, timers, errors,
    activate: context.activate,
    reload: (...args) => window._reloadActiveSession(...args),
    reply(index = 0, id = 'owner', ok = true) {
      requests[index].resolve({ ok, json: async () => ({ session: { id }, messages: [{ role: 'assistant', content: 'saved completion' }] }) });
    },
  };
}

for (const [space, mode] of [['aide', 'conversation'], ['aide', 'coding'], ['aide', 'call'], ['today', 'conversation']]) {
  test(`real background reload preserves archive, ${space}/${mode}, focus and draft owner`, async () => {
    const h = fixture({ space, mode }); const before = h.location.href;
    const reload = h.reload(); assert.equal(h.requests[0].url, '/api/sessions/owner/history');
    h.reply(); await reload; await settle();
    assert.equal(h.archive.hidden, false, 'background completion must not dismiss the archive');
    assert.deepEqual(h.document.body.dataset, { space, aideMode: mode });
    assert.equal(h.document.activeElement, h.archive);
    assert.equal(h.location.href, before);
    assert.equal(h.composer.value, 'keep this exact newer draft');
    assert.deepEqual([h.composer.selectionStart, h.composer.selectionEnd], [3, 9]);
    assert.equal(h.window._pendingDocumentScope, h.scope);
    assert.equal(h.window._currentSession.id, 'owner');
    assert.deepEqual(h.renders.map(row => [...row]), [['saved completion']]);
    assert.deepEqual(h.effects, ['messages visible']);
    assert.deepEqual(h.errors, []);
  });
}

test('a completion from an old owner does not reload the newly active conversation', async () => {
  const h = fixture(); h.activate('new-owner'); await h.reload('owner');
  assert.equal(h.requests.length, 0); assert.equal(h.window._currentSession.id, 'new-owner');
  assert.equal(h.composer.value, 'keep this exact newer draft');
});

test('a late history response cannot replace a newly selected owner', async () => {
  const h = fixture(); const reload = h.reload('owner'); h.activate('new-owner');
  h.reply(); await reload; await settle();
  assert.equal(h.window._currentSession.id, 'new-owner'); assert.equal(h.renders.length, 0);
  assert.equal(h.archive.hidden, false);
});

test('background reload defers while a foreground response owns the message tree', async () => {
  const h = fixture({ busy: true }); await h.reload('owner');
  assert.equal(h.requests.length, 0); assert.equal(h.timers.length, 1);
  assert.equal(h.archive.hidden, false); assert.equal(h.renders.length, 0);
});

test('failed background history leaves archive, current route and draft intact', async () => {
  const h = fixture({ space: 'today' }); const reload = h.reload();
  h.reply(0, 'owner', false); await reload; await settle();
  assert.equal(h.archive.hidden, false); assert.equal(h.renders.length, 0);
  assert.equal(h.document.body.dataset.space, 'today'); assert.equal(h.composer.value, 'keep this exact newer draft');
});

test('legacy delayed completion forwards the original owner to the real global boundary', async () => {
  const owner = fixture(); const timers = [], intervals = [];
  const status = { textContent: '' }, text = { textContent: '' };
  const box = { remove() {}, querySelector: selector => selector.endsWith('status') ? status : text };
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    window: owner.window,
    document: { getElementById: () => box },
    fetch: async url => ({ json: async () => url.includes('/active?')
      ? { id: 'owned-run', status: 'running' } : { done: true, text: 'complete' } }),
    setTimeout: callback => { timers.push(callback); return timers.length; },
    setInterval: callback => { intervals.push(callback); return intervals.length; }, clearInterval() {},
  });
  vm.runInContext(moduleBody(read('bgrun')) + '\nglobalThis.attach = reattach;', context);
  await context.attach('owner'); assert.equal(timers.length, 1);
  owner.activate('new-owner'); timers[0](); await settle();
  assert.equal(owner.requests.length, 0, 'delayed completion must retain its captured owner');
});

test('modern fallback forwards its receipt owner when the quiet helper is unavailable', async () => {
  const source = read('aidebackground');
  const fn = name => source.match(new RegExp(`^(?:export )?(?:async )?function ${name}\\([^]*?^}`, 'm'))[0].replace(/^export /, '');
  const timeouts = [], calls = [];
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    fetch: async () => ({ ok: true, json: async () => ({ id: 'run', state: 'succeeded', session_id: 'owner' }) }),
    window: { _reloadActiveSession: id => calls.push(id) },
    setTimeout: callback => { timeouts.push(callback); return timeouts.length; }, clearTimeout() {},
    renderCard() {},
  });
  vm.runInContext("const timers = new Map(); const TERMINAL = new Set(['succeeded']);\n"
    + ['safeMessage', 'readJson', 'stopPolling', 'readRun', 'poll'].map(fn).join('\n')
    + '\nglobalThis.poll = poll;', context);
  await context.poll({ isConnected: true, dataset: { runId: 'run' } });
  timeouts[0](); assert.deepEqual(calls, ['owner']);
});
