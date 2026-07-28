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

test('Stage 8 canonical groups and compatibility aliases stay separate', () => {
  assert.deepEqual(Object.keys(CANONICAL_SUBDOMAIN_VIEWS), [
    '', 'aide', 'andromeda', 'docs', 'files', 'plan', 'inbox', 'library', 'health',
    'finance', 'passwords', 'server',
  ]);
  assert.deepEqual(Object.keys(LEGACY_SUBDOMAIN_VIEWS), [
    'home', 'today', 'system', 'secrets', 'vault', 'money', 'subs', 'subscriptions',
    'notes', 'wiki', 'journal', 'gallery', 'photos', 'activity', 'watch', 'days', 'cowork', 'jarvis',
    'chat', 'calendar', 'tasks', 'reminders', 'mail', 'contacts', 'read', 'books',
    'habits',
  ]);
  assert.equal(Object.keys(SUBDOMAIN_VIEWS).length, 39);
  assert.equal(appForSub('').app, 'alles');
  assert.equal(appForSub('notes').app, 'docs');
  assert.equal(appForSub('photos').app, 'files');
  assert.equal(appForSub('cowork').app, 'aide');
  assert.ok(CANONICAL_SUBDOMAIN_VIEWS.plan.views.includes('plan-week'));
  assert.ok(CANONICAL_SUBDOMAIN_VIEWS.plan.views.includes('plan-board'));
  assert.equal(viewToSub('wiki'), 'docs');
  assert.equal(viewToSub('andromeda'), 'andromeda');
  assert.equal(viewToSub('photos'), 'files');
  assert.equal(viewToSub('gallery'), 'aide');
  assert.equal(viewToSub('proactive'), 'aide');
  assert.equal(viewToSub('aide-reminders'), 'aide');
  assert.equal(viewToSub('reminders'), 'plan');
  assert.equal(viewToSub('days'), 'plan');
  assert.equal(viewToSub('money'), 'finance');
  assert.equal(viewToSub('calendar'), 'plan');
  assert.equal(viewToSub('plan-week'), 'plan');
  assert.equal(viewToSub('plan-board'), 'plan');
  assert.equal(viewToSub('mail'), 'inbox');
  assert.equal(viewToSub('books'), 'library');
  assert.equal(viewToSub('habits'), 'health');
  assert.equal(viewToSub('vault'), 'passwords');
  assert.equal(viewToSub('system'), 'server');
});
