import assert from 'node:assert/strict';
import test from 'node:test';

import { CATALOG, GROUPS, HOW, catalogByGroup } from '../../static/js/connection_catalog.js';

test('every connection has a name, a group and a known way in, and ids are unique', () => {
  assert.equal(new Set(CATALOG.map(row => row.id)).size, CATALOG.length);
  for (const row of CATALOG) {
    assert.ok(row.name && row.name === row.name.toLowerCase(), row.id);
    assert.ok(GROUPS.includes(row.group), row.id);
    assert.ok(HOW.includes(row.how), row.id);
  }
});

test('oauth first: a sign in row names its provider, and anything else says why in one line', () => {
  for (const row of CATALOG) {
    if (row.how === 'signin') {
      assert.ok(row.provider && row.use, `${row.id} needs a provider and a use`);
      if (row.fallback) assert.ok(row.why, `${row.id} offers a fallback without saying why`);
    } else {
      assert.ok(row.why && row.why.length < 200 && !row.why.includes('\n'), `${row.id} needs its reason`);
    }
  }
});

test('google signs in for mail, calendar and gemini from the same provider', () => {
  const google = CATALOG.filter(row => row.provider === 'google').map(row => row.use).sort();
  assert.deepEqual(google, ['calendar', 'mail', 'models']);
});

test('the groups come out in a fixed order with no empty group', () => {
  const groups = catalogByGroup();
  assert.deepEqual(groups.map(entry => entry.group), GROUPS.filter(g => CATALOG.some(r => r.group === g)));
  assert.equal(groups.reduce((n, entry) => n + entry.rows.length, 0), CATALOG.length);
});
