import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CANONICAL_SUBDOMAIN_VIEWS,
  LEGACY_SUBDOMAIN_VIEWS,
  SUBDOMAIN_VIEWS,
  appForSub,
  shouldPollModels,
  viewToSub,
} from '../../static/js/subdomain.js';

test('model polling stays on aide, not app subdomains', () => {
  assert.equal(shouldPollModels('aide', false), true);
  for (const sub of ['', 'calendar', 'mail', 'docs', 'money'])
    assert.equal(shouldPollModels(sub, false), false);
});

test('single-host mode still polls models', () => {
  assert.equal(shouldPollModels('', true), true);
  assert.equal(shouldPollModels('calendar', true), true);
});

test('phase-three canonical hosts and compatibility aliases stay separate', () => {
  assert.deepEqual(Object.keys(CANONICAL_SUBDOMAIN_VIEWS), [
    '', 'aide', 'docs', 'files', 'finance', 'passwords', 'server', 'mail',
    'calendar', 'tasks', 'days', 'habits', 'read', 'books', 'health', 'contacts',
    'watch',
  ]);
  assert.deepEqual(Object.keys(LEGACY_SUBDOMAIN_VIEWS), [
    'home', 'today', 'system', 'secrets', 'vault', 'money', 'subs', 'subscriptions',
    'notes', 'wiki', 'journal', 'gallery', 'photos', 'activity', 'cowork', 'jarvis',
    'chat',
  ]);
  assert.equal(Object.keys(SUBDOMAIN_VIEWS).length, 34);
  assert.equal(appForSub('').app, 'alles');
  assert.equal(appForSub('notes').app, 'docs');
  assert.equal(appForSub('photos').app, 'files');
  assert.equal(appForSub('cowork').app, 'aide');
  assert.equal(viewToSub('wiki'), 'docs');
  assert.equal(viewToSub('photos'), 'files');
  assert.equal(viewToSub('gallery'), 'aide');
  assert.equal(viewToSub('money'), 'finance');
  assert.equal(viewToSub('vault'), 'passwords');
  assert.equal(viewToSub('system'), 'server');
});
