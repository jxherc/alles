import test from 'node:test';
import assert from 'node:assert/strict';

import {
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

test('phase-zero subdomain and compatibility-alias map stays stable', () => {
  assert.deepEqual(Object.keys(SUBDOMAIN_VIEWS), [
    '', 'aide', 'mail', 'docs', 'gallery', 'calendar', 'tasks', 'subs', 'money',
    'days', 'journal', 'activity', 'system', 'watch', 'habits', 'read', 'books',
    'health', 'files', 'contacts', 'secrets', 'notes', 'photos',
  ]);
  assert.equal(appForSub('').app, 'alles');
  assert.equal(appForSub('notes').app, 'docs');
  assert.equal(appForSub('photos').app, 'gallery');
  assert.equal(viewToSub('wiki'), 'docs');
  assert.equal(viewToSub('photos'), 'gallery');
});
