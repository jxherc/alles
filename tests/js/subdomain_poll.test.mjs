import test from 'node:test';
import assert from 'node:assert/strict';

import { shouldPollModels } from '../../static/js/subdomain.js';

test('model polling stays on aide, not app subdomains', () => {
  assert.equal(shouldPollModels('aide', false), true);
  for (const sub of ['', 'calendar', 'mail', 'docs', 'money'])
    assert.equal(shouldPollModels(sub, false), false);
});

test('single-host mode still polls models', () => {
  assert.equal(shouldPollModels('', true), true);
  assert.equal(shouldPollModels('calendar', true), true);
});
