import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CANONICAL_HOSTS,
  LEGACY_HOST_ALIASES,
  buildCompatibilityUrl,
  resolveCompatibilityRoute,
} from '../../static/js/routecompat.js';

const on = Object.freeze({ afterlife_shell: true, afterlife_today: true });
const off = Object.freeze({ afterlife_shell: false, afterlife_today: false });

const pick = route => route && {
  host: route.host,
  view: route.view,
  ...(route.section ? { section: route.section } : {}),
  ...(route.mode ? { mode: route.mode } : {}),
  hashOwner: route.hashOwner,
};

test('canonical hosts include the Stage 8 specialist groups and unchanged apps', () => {
  assert.deepEqual(Object.keys(CANONICAL_HOSTS).sort(), [
    '', 'aide', 'andromeda', 'docs', 'files', 'finance', 'health', 'inbox',
    'library', 'passwords', 'plan', 'server',
  ]);
  assert.equal(CANONICAL_HOSTS.docs.primary, 'wiki');
  assert.deepEqual(CANONICAL_HOSTS.plan.views, [
    'plan', 'plan-week', 'plan-board', 'calendar', 'tasks', 'reminders', 'days',
  ]);
  assert.ok(CANONICAL_HOSTS.aide.views.includes('aide-reminders'));
  assert.deepEqual(CANONICAL_HOSTS.inbox.views, ['inbox', 'mail', 'contacts']);
  assert.deepEqual(CANONICAL_HOSTS.library.views, ['library', 'books', 'read']);
  assert.deepEqual(CANONICAL_HOSTS.health.views, ['health', 'health-log', 'habits']);
  assert.deepEqual(CANONICAL_HOSTS.finance.views, ['finance', 'money', 'subs', 'imports']);
  assert.deepEqual(CANONICAL_HOSTS.files.views, ['files', 'files-list', 'files-gallery', 'photos']);
  assert.ok(CANONICAL_HOSTS.server.views.includes('activity'));
  assert.ok(CANONICAL_HOSTS.server.views.includes('watch'));
  for (const oldHost of ['calendar', 'tasks', 'mail', 'contacts', 'read', 'books', 'habits']) {
    assert.ok(!Object.hasOwn(CANONICAL_HOSTS, oldHost), oldHost);
  }
  assert.ok(!Object.hasOwn(CANONICAL_HOSTS, 'gallery'));
  assert.ok(!Object.hasOwn(CANONICAL_HOSTS, 'system'));
});

test('legacy hosts are separate aliases with complete route descriptors', () => {
  const expected = {
    home: ['', 'today'],
    today: ['', 'today'],
    activity: ['server', 'server'],
    system: ['server', 'system'],
    secrets: ['passwords', 'vault'],
    vault: ['passwords', 'vault'],
    watch: ['server', 'server'],
    money: ['finance', 'finance'],
    subs: ['finance', 'finance'],
    subscriptions: ['finance', 'finance'],
    calendar: ['plan', 'plan'],
    tasks: ['plan', 'plan'],
    reminders: ['plan', 'plan'],
    days: ['plan', 'plan'],
    mail: ['inbox', 'inbox'],
    contacts: ['inbox', 'inbox'],
    read: ['library', 'library'],
    books: ['library', 'library'],
    habits: ['health', 'health'],
    notes: ['docs', 'wiki'],
    wiki: ['docs', 'wiki'],
    journal: ['docs', 'journal'],
    gallery: ['files', 'photos'],
    photos: ['files', 'photos'],
    cowork: ['aide', 'chat'],
    jarvis: ['aide', 'chat'],
    chat: ['aide', 'chat'],
  };
  assert.deepEqual(Object.keys(LEGACY_HOST_ALIASES).sort(), Object.keys(expected).sort());
  for (const [alias, [host, view]] of Object.entries(expected)) {
    assert.equal(LEGACY_HOST_ALIASES[alias].host, host, alias);
    assert.equal(LEGACY_HOST_ALIASES[alias].view, view, alias);
    assert.equal(typeof LEGACY_HOST_ALIASES[alias].hashOwner, 'string', alias);
  }
});

test('old app and view identifiers retain their destination through the Stage 8 matrix', () => {
  const matrix = [
    ['home', { host: '', view: 'today', hashOwner: 'today' }],
    ['today', { host: '', view: 'today', hashOwner: 'today' }],
    ['system', { host: 'server', view: 'system', hashOwner: 'system' }],
    ['server', { host: 'server', view: 'system', hashOwner: 'system' }],
    ['secrets', { host: 'passwords', view: 'vault', hashOwner: 'vault' }],
    ['vault', { host: 'passwords', view: 'vault', hashOwner: 'vault' }],
    ['passwords', { host: 'passwords', view: 'vault', hashOwner: 'vault' }],
    ['money', { host: 'finance', view: 'finance', section: 'money', hashOwner: 'money' }],
    ['finance', { host: 'finance', view: 'finance', section: 'money', hashOwner: 'money' }],
    ['subs', { host: 'finance', view: 'finance', section: 'subs', hashOwner: 'subs' }],
    ['subscriptions', { host: 'finance', view: 'finance', section: 'subs', hashOwner: 'subs' }],
    ['notes', { host: 'docs', view: 'wiki', section: 'notes', hashOwner: 'notes' }],
    ['wiki', { host: 'docs', view: 'wiki', hashOwner: 'wiki' }],
    ['docs', { host: 'docs', view: 'wiki', hashOwner: 'wiki' }],
    ['journal', { host: 'docs', view: 'journal', hashOwner: 'journal' }],
    ['files', { host: 'files', view: 'files', hashOwner: 'files' }],
    ['photos', { host: 'files', view: 'photos', hashOwner: 'photos' }],
    ['gallery', { host: 'aide', view: 'gallery', section: 'creations', hashOwner: 'gallery' }],
    ['cowork', { host: 'aide', view: 'chat', mode: 'jarvis', hashOwner: 'session' }],
    ['jarvis', { host: 'aide', view: 'chat', mode: 'jarvis', hashOwner: 'session' }],
    ['chat', { host: 'aide', view: 'chat', hashOwner: 'session' }],
    ['aide', { host: 'aide', view: 'chat', hashOwner: 'session' }],
    ['aide-reminders', { host: 'aide', view: 'aide-reminders', hashOwner: 'aide-reminders' }],
    ['andromeda', { host: 'andromeda', view: 'andromeda', hashOwner: 'andromeda' }],
    ['activity', { host: 'server', view: 'server', section: 'activity', hashOwner: 'activity' }],
    ['health', { host: 'health', view: 'health', section: 'health', hashOwner: 'health-log' }],
  ];

  for (const [identifier, expected] of matrix) {
    assert.deepEqual(pick(resolveCompatibilityRoute({ app: identifier, flags: on })), expected, `app=${identifier}`);
    assert.deepEqual(pick(resolveCompatibilityRoute({ view: identifier, flags: on })), expected, `view=${identifier}`);
  }
});

test('specialist identifiers resolve to their Stage 8 group and preserve their section', () => {
  const matrix = {
    plan: ['plan', 'plan', null],
    calendar: ['plan', 'plan', 'calendar'],
    tasks: ['plan', 'plan', 'tasks'],
    reminders: ['plan', 'plan', 'reminders'],
    inbox: ['inbox', 'inbox', null],
    mail: ['inbox', 'inbox', 'mail'],
    contacts: ['inbox', 'inbox', 'contacts'],
    library: ['library', 'library', null],
    books: ['library', 'library', 'books'],
    read: ['library', 'library', 'read'],
    health: ['health', 'health', 'health', 'health-log'],
    'health-overview': ['health', 'health', null, 'health-overview'],
    'health-log': ['health', 'health', 'health', 'health-log'],
    habits: ['health', 'health', 'habits'],
    finance: ['finance', 'finance', 'money', 'money'],
    'finance-overview': ['finance', 'finance', null, 'finance-overview'],
    money: ['finance', 'finance', 'money'],
    subs: ['finance', 'finance', 'subs'],
    imports: ['finance', 'finance', 'imports'],
    days: ['plan', 'plan', 'days'],
    watch: ['server', 'server', 'watch'],
  };
  for (const [id, [host, view, section, hashOwner = id]] of Object.entries(matrix)) {
    assert.deepEqual(pick(resolveCompatibilityRoute({ app: id, flags: on })), {
      host, view, ...(section ? { section } : {}), hashOwner,
    }, id);
  }

  const aideViews = ['memory', 'compare', 'brain', 'models', 'cookbook', 'usage', 'skills'];
  for (const id of aideViews) {
    assert.deepEqual(pick(resolveCompatibilityRoute({ view: id, flags: on })), {
      host: 'aide', view: id, hashOwner: id,
    });
  }
});

test('gallery query context means Aide creations while gallery host means Files photos', () => {
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: 'gallery', flags: on })), {
    host: 'files', view: 'photos', hashOwner: 'photos',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: 'photos', flags: on })), {
    host: 'files', view: 'photos', hashOwner: 'photos',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: 'gallery', app: 'gallery', flags: on })), {
    host: 'aide', view: 'gallery', section: 'creations', hashOwner: 'gallery',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: 'gallery', view: 'photos', flags: on })), {
    host: 'files', view: 'photos', hashOwner: 'photos',
  });
});

test('app wins view and identifiers are trimmed and lower-case normalized', () => {
  assert.deepEqual(pick(resolveCompatibilityRoute({
    sub: 'SYSTEM', app: '  NoTeS ', view: 'gallery', flags: on,
  })), {
    host: 'docs', view: 'wiki', section: 'notes', hashOwner: 'notes',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: ' SeCrEtS ', flags: on })), {
    host: 'passwords', view: 'vault', hashOwner: 'vault',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ app: '', view: ' JaRvIs ', flags: on })), {
    host: 'aide', view: 'chat', mode: 'jarvis', hashOwner: 'session',
  });
});

test('unknown explicit identifiers and unknown hosts are no-ops', () => {
  assert.equal(resolveCompatibilityRoute({ sub: 'unknown', flags: on }), null);
  assert.equal(resolveCompatibilityRoute({ sub: 'gallery', app: 'unknown', view: 'photos', flags: on }), null);
  assert.equal(resolveCompatibilityRoute({ sub: 'system', view: 'unknown', flags: on }), null);
  assert.equal(resolveCompatibilityRoute(), null);
});

test('Today keeps its flag-off fallback while Activity always consolidates into Server', () => {
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: 'home', flags: off })), {
    host: '', view: 'home', hashOwner: 'home',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ app: 'today', flags: off })), {
    host: '', view: 'home', hashOwner: 'home',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ sub: 'activity', flags: off })), {
    host: 'server', view: 'server', section: 'activity', hashOwner: 'activity',
  });
  assert.deepEqual(pick(resolveCompatibilityRoute({ app: 'activity', flags: off })), {
    host: 'server', view: 'server', section: 'activity', hashOwner: 'activity',
  });
});

test('canonical hosts are idempotent and cannot request another redirect by themselves', () => {
  for (const host of Object.keys(CANONICAL_HOSTS)) {
    assert.equal(resolveCompatibilityRoute({ sub: host, flags: on }), null, host || 'apex');
  }

  for (const alias of ['system', 'secrets', 'money', 'subs', 'notes', 'journal', 'gallery', 'cowork']) {
    const first = resolveCompatibilityRoute({ sub: alias, flags: on });
    assert.ok(first, alias);
    assert.equal(resolveCompatibilityRoute({ sub: first.host, flags: on }), null, alias);
  }
});

test('URL builder preserves raw deep-link state and removes only routing and stale SSO params', () => {
  const route = resolveCompatibilityRoute({ sub: 'gallery', flags: on });
  const currentUrl = 'https://gallery.localhost:9443/deep/%E9%9B%AA'
    + '?app=photos&tag=a&tag=b&text=%E9%9B%AA%20%E2%98%83'
    + '&literal=%25%23%26&_auth=old&_sso=stale&empty='
    + '#folder%2F%E9%9B%AA%26x';
  assert.equal(buildCompatibilityUrl({ currentUrl, route }),
    'https://files.localhost:9443/deep/%E9%9B%AA'
    + '?tag=a&tag=b&text=%E9%9B%AA%20%E2%98%83&literal=%25%23%26&empty='
    + '&view=photos#folder%2F%E9%9B%AA%26x');
});

test('URL cleanup keeps similarly named, duplicate, Unicode, percent, hash, and ampersand values', () => {
  const currentUrl = 'http://docs.localhost/path'
    + '?application=notes&preview=wiki&APP=keep&x=%E7%8C%AB&x=%25&x=%23&x=%26'
    + '&view=notes&_auth=a&_auth=b&_sso=c&auth=keep#note%20%E7%8C%AB%23%26';
  const route = resolveCompatibilityRoute({ view: 'notes', flags: on });
  assert.equal(buildCompatibilityUrl({ currentUrl, route }),
    'http://docs.localhost/path'
    + '?application=notes&preview=wiki&APP=keep&x=%E7%8C%AB&x=%25&x=%23&x=%26'
    + '&auth=keep#note%20%E7%8C%AB%23%26');
});

test('URL builder supports apex, custom wildcard domains, and ports', () => {
  const home = resolveCompatibilityRoute({ sub: 'home', flags: on });
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://home.localhost:8000/nested?view=home&keep=1#day',
    route: home,
  }), 'http://localhost:8000/nested?keep=1&view=today#day');

  const vault = resolveCompatibilityRoute({ sub: 'secrets', flags: on });
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'https://secrets.alles.example/private?app=vault&next=%2Fsafe#item',
    route: vault,
    baseDomain: 'alles.example',
  }), 'https://passwords.alles.example/private?next=%2Fsafe&view=vault#item');
});

test('cross-host handoffs carry exact Notes and Jarvis destinations', () => {
  const notes = resolveCompatibilityRoute({ sub: 'notes', flags: on });
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://notes.localhost:8000/?keep=1#Folder%2FNote.md',
    route: notes,
  }), 'http://docs.localhost:8000/?keep=1&view=notes#Folder%2FNote.md');

  const jarvis = resolveCompatibilityRoute({ sub: 'cowork', flags: on });
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://cowork.localhost:8000/?keep=1#session-id',
    route: jarvis,
  }), 'http://aide.localhost:8000/?keep=1&view=jarvis#session-id');

  const aideReminders = resolveCompatibilityRoute({
    app: 'aide-reminders', flags: on,
  });
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://localhost:8000/?app=aide-reminders&keep=1',
    route: aideReminders,
  }), 'http://aide.localhost:8000/?keep=1&view=aide-reminders');
});

test('cross-host specialist handoffs carry the legacy section identifier', () => {
  for (const [legacyHost, groupHost] of [
    ['calendar', 'plan'], ['tasks', 'plan'], ['reminders', 'plan'], ['days', 'plan'],
    ['mail', 'inbox'], ['contacts', 'inbox'],
    ['read', 'library'], ['books', 'library'], ['habits', 'health'],
    ['money', 'finance'], ['subs', 'finance'],
  ]) {
    const route = resolveCompatibilityRoute({ sub: legacyHost, flags: on });
    assert.equal(buildCompatibilityUrl({
      currentUrl: `http://${legacyHost}.localhost:8000/?keep=1#detail`,
      route,
    }), `http://${groupHost}.localhost:8000/?keep=1&view=${legacyHost}#detail`, legacyHost);
  }
});

test('cross-host group overview handoffs keep their non-colliding identifier', () => {
  for (const identifier of ['health-overview', 'finance-overview']) {
    const route = resolveCompatibilityRoute({ app: identifier, flags: on });
    assert.equal(buildCompatibilityUrl({
      currentUrl: `http://localhost:8000/?app=${identifier}&keep=1`,
      route,
    }), `http://${route.host}.localhost:8000/?keep=1&view=${identifier}`, identifier);
  }
});

test('cross-host Plan handoffs preserve week and board destinations', () => {
  for (const identifier of ['plan-week', 'plan-board']) {
    const route = resolveCompatibilityRoute({ app: identifier, flags: on });
    assert.equal(buildCompatibilityUrl({
      currentUrl: `http://localhost:8000/?app=${identifier}&keep=1`,
      route,
    }), `http://plan.localhost:8000/?keep=1&view=${identifier}`, identifier);
  }
});

test('URL builder returns null for invalid routes and unchanged canonical targets', () => {
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://server.localhost/system?keep=1#status',
    route: { host: 'server', view: 'system', hashOwner: 'system' },
  }), null);
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://server.localhost/system?app=system&keep=1#status',
    route: { host: 'server', view: 'system', hashOwner: 'system' },
  }), 'http://server.localhost/system?keep=1#status');
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'http://system.localhost/',
    route: { host: 'made-up', view: 'system', hashOwner: 'system' },
  }), null);
  assert.equal(buildCompatibilityUrl({
    currentUrl: 'not a url',
    route: { host: 'server', view: 'system', hashOwner: 'system' },
  }), null);
});
