import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import { resolveCompatibilityRoute } from '../../static/js/routecompat.js';
import { GROUP_DEFINITIONS, groupRouteFor, normalizeGroupSection } from '../../static/js/specialist_groups.js';
import { appForSub, viewToSub } from '../../static/js/subdomain.js';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const sync = app.match(/function _syncLocalViewUrl\([^]*?\n}/)?.[0];
assert.ok(sync);

function navigate(href, identifier, { single = true, sub = '', withState = false, replace = false } = {}) {
  const calls = [];
  const history = {
    state: { __allesRoutePosition: 0, anotherOwner: 'kept' },
    replaceState(state, _title, path) {
      this.state = state;
      calls.push(['replace', path]);
    },
    pushState(state, _title, path) {
      this.state = state;
      calls.push(['push', path]);
    },
  };
  const context = vm.createContext({
    URL, location: new URL(href), resolveCompatibilityRoute, groupRouteFor, normalizeGroupSection, viewToSub, appForSub,
    _afterlifeFlags: { afterlife_today: true },
    singleHost: () => single, currentSub: () => sub,
    history,
    replaceRouteUrl: path => history.replaceState(history.state, '', path),
    pushRouteUrl: path => history.pushState({
      ...history.state,
      __allesRoutePosition: history.state.__allesRoutePosition + 1,
    }, '', path),
  });
  vm.runInContext(sync, context);
  const route = resolveCompatibilityRoute({ view: identifier, flags: { afterlife_today: true } });
  context._syncLocalViewUrl(route, identifier, { replace });
  return withState ? { calls, state: history.state } : calls;
}

test('leaving a document for Home removes its fragment and records Home', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?view=docs#notes%2Fproof', 'today'), [
    ['push', '/?view=today'],
  ]);
});

test('canonicalizing an Aide alias preserves its session fragment', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?app=aide#session-123', 'aide'), [
    ['push', '/?view=aide#session-123'],
  ]);
});

test('canonicalizing a Docs alias preserves the exact document fragment', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?app=wiki#notes%2Fproof', 'docs'), [
    ['push', '/?view=docs#notes%2Fproof'],
  ]);
});

test('same-host Aide tools remain reloadable and retain session context', () => {
  assert.deepEqual(navigate('http://aide.localhost/#session-123', 'models', { single: false, sub: 'aide' }), [
    ['push', '/?view=models#session-123'],
  ]);
});

test('canonical Docs host keeps its document fragment without a redundant view', () => {
  assert.deepEqual(navigate('http://docs.localhost/?app=wiki#proof', 'docs', { single: false, sub: 'docs' }), [
    ['push', '/#proof'],
  ]);
});

test('reselecting the current route does not add a history entry', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?view=today', 'today'), []);
});

test('a docs section that is not its front page stays in the address, so reload keeps it', () => {
  assert.deepEqual(navigate('http://docs.localhost/', 'journal', { single: false, sub: 'docs' }), [
    ['push', '/?view=journal'],
  ]);
});

test('the drawer\'s jump to today lands on the bare home address, not ?view=today', () => {
  // files -> drawer -> today loads localhost/?view=today; boot cleans it like any front page
  assert.deepEqual(navigate('http://localhost/?view=today', 'today', { single: false, replace: true }), [
    ['replace', '/'],
  ]);
  assert.deepEqual(navigate('http://localhost/?view=today', 'home', { single: false, replace: true }), [
    ['replace', '/'],
  ]);
  // aide's conversation is aide's front page too; its session stays
  assert.deepEqual(navigate('http://aide.localhost/?view=skills#session-1', 'chat', { single: false, sub: 'aide' }), [
    ['push', '/#session-1'],
  ]);
});

test('a grouped section keeps view= while an app front page drops it', () => {
  assert.deepEqual(navigate('http://docs.localhost/', 'journal', { single: false, sub: 'docs', replace: true }), [
    ['replace', '/?view=journal'],
  ]);
  assert.deepEqual(navigate('http://docs.localhost/?view=journal', 'docs', { single: false, sub: 'docs' }), [
    ['push', '/'],
  ]);
  assert.deepEqual(navigate('http://plan.localhost/', 'calendar', { single: false, sub: 'plan' }), [
    ['push', '/?view=calendar'],
  ]);
  // on one host every view keeps its name, there is no other way to tell them apart
  assert.deepEqual(navigate('http://127.0.0.1/?view=files', 'today'), [['push', '/?view=today']]);
});

test('local navigation marks the new history entry and preserves existing state', () => {
  const { calls, state } = navigate('http://127.0.0.1/?view=docs', 'journal', { withState: true });
  assert.deepEqual(calls, [['push', '/?view=journal']]);
  assert.equal(state.__allesRoutePosition, 1);
  assert.equal(state.anotherOwner, 'kept');
});

test('an andromeda search in ?q does not follow you into activity on one host', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?view=andromeda&q=knee+surgery', 'activity'), [
    ['push', '/?view=activity'],
  ]);
  // and an activity filter doesn't start a web search
  assert.deepEqual(navigate('http://127.0.0.1/?view=activity&q=login', 'andromeda'), [
    ['push', '/?view=andromeda'],
  ]);
});

test('reselecting andromeda keeps its search in the address', () => {
  assert.deepEqual(navigate('http://127.0.0.1/?view=andromeda&q=knee', 'andromeda'), []);
  // on its own host andromeda is the front page: the address is already right
  assert.deepEqual(navigate('http://andromeda.localhost/?q=knee', 'andromeda', { single: false, sub: 'andromeda' }), []);
});

// boot renders the primary, a tab pushes a section, back lands on the bare address again
function backHarness(sub) {
  const head = app.match(/function renderLocalView\(v, route = \{\}\) \{\n[^]*?_lastLocalView = [^\n]*\n/)?.[0];
  const route = app.match(/function renderLocalRoute\(route\) \{[^]*?\n}/)?.[0];
  const key = app.match(/function _localViewKey\([^]*?\n}/)?.[0];
  const back = app.match(/    const primary = appForSub\(currentSub\(\)\)\.primary;\n[^]*?\n    }\n/)?.[0];
  assert.ok(head && route && key && back);
  const context = vm.createContext({
    GROUP_DEFINITIONS, groupRouteFor, normalizeGroupSection, appForSub, currentSub: () => sub, calls: [], URL,
  });
  vm.runInContext(`let _lastLocalView = '';
    ${head}  calls.push([v, route.section]);\n}
    ${route}
    ${key}
    async function backToBare(previousUrl = new URL('http://app.localhost/'), url = previousUrl) {\n${back}}
    globalThis.subject = { render: renderLocalRoute, back: backToBare };`, context);
  // calls are made in the vm realm; copy them out so deepEqual compares plain arrays
  return { ...context.subject, get calls() { return Array.from(context.calls, call => Array.from(call)); } };
}

test('back to bare docs renders the docs group, not the old standalone view', async () => {
  const docs = backHarness('docs');
  docs.render({ view: 'wiki', hashOwner: 'wiki' });
  docs.render({ host: 'docs', view: 'docs', section: 'journal', hashOwner: 'journal' });
  await docs.back();
  assert.deepEqual(docs.calls, [['docs', 'notes'], ['docs', 'journal'], ['docs', 'notes']]);
  // a hash change inside docs (another doc) is not a view change
  await docs.back();
  assert.equal(docs.calls.length, 3);
});

test('back to bare server renders its overview inside the workbench', async () => {
  const server = backHarness('server');
  server.render({ view: 'system', hashOwner: 'system' });
  server.render({ host: 'server', view: 'server', section: 'services', hashOwner: 'server-services' });
  await server.back();
  assert.deepEqual(server.calls.at(-1), ['server', 'overview']);
});

test('back from a plan section to bare plan leaves that section', async () => {
  const plan = backHarness('plan');
  plan.render({ view: 'plan', hashOwner: 'plan' });
  plan.render({ host: 'plan', view: 'plan', section: 'week', hashOwner: 'plan-week' });
  await plan.back();
  assert.deepEqual(plan.calls, [['plan', 'overview'], ['plan', 'week'], ['plan', 'overview']]);
});

test('back to bare aide still opens the conversation', async () => {
  const aide = backHarness('aide');
  aide.render({ host: 'aide', view: 'skills', hashOwner: 'skills' });
  await aide.back();
  assert.deepEqual(aide.calls.at(-1), ['chat', undefined]);
});

test('back from a files subfolder on its own host reloads the folder the address names', async () => {
  const files = backHarness('files');
  files.render({ view: 'files', hashOwner: 'files' });
  await files.back(new URL('http://files.localhost/?p=a%2Fb'), new URL('http://files.localhost/?p=a'));
  assert.deepEqual(files.calls, [['files', 'files'], ['files', 'files']]);
  // only the hash moved (another doc in docs, another conversation in aide): no reload
  await files.back(new URL('http://files.localhost/?p=a#one'), new URL('http://files.localhost/?p=a#two'));
  assert.equal(files.calls.length, 2);
});

test('back onto aide chat re-selects the conversation the hash names', () => {
  const pop = app.slice(app.indexOf("window.addEventListener('popstate'"), app.indexOf('function renderLocalRoute('));
  assert.match(pop, /if \(_lastLocalView === 'chat' && generation === _popstateGeneration\) \{\n    const navigation = _navigationGeneration;\n    await selectSessionFromRoute\(/);
  // after every render branch, so the bare aide address (no re-render) still swaps the thread
  assert.ok(pop.indexOf('selectSessionFromRoute') > pop.indexOf('await renderLocalRoute({ view: primary, hashOwner: primary })'));
});

// sessions.js with its imports stubbed, history kept as a list so back can be played
const sessionsSource = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '')
  .replace("import('./aidebackground.js?v=247')", 'Promise.resolve({ reattachBackgroundWork() {} })');

function aideHistory({ primary = 'P', sessions = ['P', 'A', 'B'], start = 'http://aide.localhost/#P', active = 'P' } = {}) {
  const location = new URL(start);
  const entries = [location.href];
  let index = 0;
  let left = false;
  const window = {
    addEventListener() {},
    _currentSession: { id: active, primary: active === primary },
    _enterChatView() {},
    _showPrimaryAide: async ({ isCurrent }) => context.selectSession(primary, '', { isCurrent }),
  };
  const node = () => ({ style: {}, setAttribute() {}, addEventListener() {}, focus() {}, value: '', hidden: false, inert: false });
  const document = { activeElement: null, getElementById: () => node(), querySelectorAll: () => [], querySelector: () => null, dispatchEvent() {} };
  const context = vm.createContext({
    window, document, location, URL, URLSearchParams,
    CustomEvent: class { constructor(type) { this.type = type; } },
    console: { error() {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async url => {
      const id = String(url).match(/sessions\/([^/]+)\/history/)?.[1];
      return { ok: true, json: async () => ({ session: { id, name: id, primary: id === primary }, messages: [] }) };
    },
    routeHistoryPosition: () => index,
    replaceRouteUrl: url => { location.href = String(url); entries[index] = location.href; },
    pushRouteUrl: url => { location.href = String(url); entries.splice(index + 1, Infinity, location.href); index += 1; },
    isIncognitoMode: () => false, toast() {}, t: key => key,
    restoreSessionModel() {}, selectAideDefault() {}, getProjects: () => [], renderProjectFolders() {},
    applyResponsePrivacy() {}, stripEmojis: text => text, welcomeEnabled: () => false,
  });
  vm.runInContext(`${sessionsSource}
    _activeId = ${JSON.stringify(active)};
    _allSessions = ${JSON.stringify(sessions.map(id => ({ id, name: id, primary: id === primary })))};
    _sessionsLoaded = true;
    renderMessages = () => {}; showMessages = () => {}; showWelcome = () => {}; scrollDown = () => true;
    updateSessionHeader = () => {}; saveDraft = () => true; restoreDraft = () => {};
    globalThis.subject = { openFromArchive: selectSidebarSession, selectSession, fromRoute: selectSessionFromRoute, active: () => _activeId };`, context);
  const subject = context.subject;
  return {
    ...subject,
    location,
    get length() { return entries.length; },
    // what app.js popstate does on the bare aide address: the view stays, the hash picks the thread
    async back() {
      if (index === 0) { left = true; return; }
      index -= 1;
      location.href = entries[index];
      await subject.fromRoute();
    },
    get left() { return left; },
  };
}

test('back from an archived conversation returns to the one before, then leaves aide', async () => {
  const aide = aideHistory();
  await aide.openFromArchive('A');
  await aide.openFromArchive('B');
  assert.equal(aide.location.hash, '#B');
  assert.equal(aide.length, 3);
  await aide.back();
  assert.equal(aide.active(), 'A');
  assert.equal(aide.location.hash, '#A');
  await aide.back();
  assert.equal(aide.active(), 'P');
  await aide.back();
  assert.equal(aide.left, true);
});

test('reopening the conversation that already shows adds no history entry', async () => {
  const aide = aideHistory();
  await aide.openFromArchive('P');
  assert.equal(aide.length, 1);
  // a plain selection (boot, the main conversation button) replaces too
  await aide.selectSession('A');
  assert.equal(aide.length, 1);
  assert.equal(aide.location.hash, '#A');
});

test('a bare aide address shows the main conversation, a new unsaved task stays put', async () => {
  const archived = aideHistory({ start: 'http://aide.localhost/', active: 'A' });
  await archived.fromRoute();
  assert.equal(archived.active(), 'P');
  const fresh = aideHistory({ start: 'http://aide.localhost/', active: null });
  await fresh.fromRoute();
  assert.equal(fresh.active(), null);
});
