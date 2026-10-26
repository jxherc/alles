import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');
const sessions = read('sessions').replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '').replace("import('./aidebackground.js?v=246')", 'Promise.resolve({ reattachBackgroundWork() {} })');
const app = read('app');
const noticeStart = app.indexOf("  const sourceMessage = new URLSearchParams(location.search).get('message');");
const noticeEnd = app.indexOf('\n\n', noticeStart);
assert.ok(noticeStart >= 0 && noticeEnd > noticeStart, 'execute the real boot source-link notice');
const sourceNotice = app.slice(noticeStart, noticeEnd);

function fixture({ hash = 'deleted-owner', message = 'deleted-reply', historical = false } = {}) {
  const requests = [], notices = [], renders = [];
  const location = new URL('http://127.0.0.1:1/?view=chat'); location.hash = hash;
  if (message) location.searchParams.set('message', message);
  const field = { value: '', style: {}, focus() {} };
  const nodes = { 'composer-ta': field, messages: { innerHTML: '' }, 'composer-outer': { inert: false } };
  const index = [{ id: 'primary', primary: true }, ...(historical ? [{ id: hash }] : [])];
  const document = {
    body: { classList: { contains: name => name === 'is-aide' } },
    getElementById: id => nodes[id] || null,
    querySelectorAll: () => [], dispatchEvent() {},
  };
  const window = { addEventListener() {}, _enterChatView() {}, _setMode() {}, _currentSession: null };
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    window, document, location, URL, URLSearchParams,
    console: { error() {} }, CustomEvent: class {},
    fetch: async url => {
      requests.push(url);
      const id = url.split('/')[3];
      return { ok: true, json: async () => ({ session: { id, primary: id === 'primary' }, messages: [] }) };
    },
    replaceRouteUrl: url => { location.href = String(url); },
    toast: message => notices.push(message),
    loadAnswerNoteRecovery() {}, loadAnswerTaskRecovery() {},
    restoreSessionModel() {}, selectAideDefault() {}, getProjects: () => [],
    index, renders,
  });
  vm.runInContext(sessions + `
    loadSessions = async () => { _allSessions = index; _sessionsLoaded = true; return true; };
    renderMessages = messages => renders.push(messages);
    showMessages = () => {};
    scrollDown = () => true;
    showWelcome = () => {};
    updateSessionHeader = () => {};
    restoreDraft = () => {};
    saveDraft = () => true;
    focusSessionMessage = () => ${historical};
    globalThis.subject = { init: initSessions, select: selectSession, fresh: newChat,
      notice: () => { ${sourceNotice} } };
  `, context);
  return { ...context.subject, location, requests, notices, window, renders, field };
}

for (const hash of ['deleted-owner', '']) {
  test(`missing source ${hash ? 'conversation' : 'owner'} retains the original message and reports unavailable`, async () => {
    const h = fixture({ hash }); await h.init(); h.notice();
    assert.equal(h.location.searchParams.get('message'), 'deleted-reply', 'fallback must preserve evidence for boot source recovery');
    assert.equal(h.location.hash, hash ? '#' + hash : '');
    assert.deepEqual(h.notices, ['the original conversation or reply is unavailable']);
    assert.equal(h.window._currentSession.id, 'primary', 'keep the established fallback-owner contract');
  });
}

test('reloading a deleted source keeps its identity and unavailable notice until explicit new task', async () => {
  const h = fixture();
  for (let reload = 0; reload < 2; reload++) {
    await h.init(); h.notice();
    assert.equal(h.location.searchParams.get('message'), 'deleted-reply');
    assert.equal(h.location.hash, '#deleted-owner');
  }
  assert.equal(h.notices.length, 2);
  h.fresh();
  assert.equal(h.location.searchParams.has('message'), false);
  assert.equal(h.location.hash, ''); assert.equal(h.window._currentSession, null);
});

test('intentional conversation selection clears a previously missing source link', async () => {
  const h = fixture(); await h.init(); h.notice();
  assert.equal(await h.select('other'), true);
  assert.equal(h.location.hash, '#other'); assert.equal(h.location.searchParams.has('message'), false);
});

test('available historical source still selects and focuses its exact owner without fallback notice', async () => {
  const h = fixture({ hash: 'available-owner', message: 'available-reply', historical: true });
  await h.init(); h.notice();
  assert.equal(h.window._currentSession.id, 'available-owner');
  assert.deepEqual(h.requests, ['/api/sessions/available-owner/history']);
  assert.equal(h.location.searchParams.get('message'), 'available-reply');
  assert.deepEqual(h.notices, []);
});

test('a missing plain conversation link keeps the existing primary fallback behavior', async () => {
  const h = fixture({ message: '' }); await h.init(); h.notice();
  assert.equal(h.location.hash, '#primary'); assert.deepEqual(h.notices, []);
  assert.equal(h.location.searchParams.has('message'), false);
});
