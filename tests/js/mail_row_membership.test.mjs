import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/mail.js', import.meta.url), 'utf8')
  .match(/function updateMailRows\(matches, changes, remove = false\) \{[\s\S]*?\r?\n}/)?.[0];
assert.ok(source);

function update(filter, view, remove = false) {
  let cache = [{ id: 'one', seen: false, flagged: true }, { id: 'two', seen: false, flagged: true }];
  const context = vm.createContext({
    _lastMsgs: cache, _filter: filter,
    _searchView: view === 'search' ? 'project' : '',
    _labelFilter: view === 'label' ? 'project' : '',
    readCache: () => cache, writeCache: value => { cache = value; },
    $: () => null,
  });
  vm.runInContext(source, context);
  const changes = filter === 'unread' ? { seen: true } : { flagged: false };
  context.updateMailRows(row => row.id === 'one', changes, remove);
  return { rows: context._lastMsgs, cache, changes };
}

for (const filter of ['unread', 'flagged']) {
  for (const view of ['mailbox', 'search', 'label']) {
    test(`${view} membership after changing a message from the ${filter} mailbox`, () => {
      const { rows, cache, changes } = update(filter, view);
      assert.deepEqual(Array.from(rows, row => row.id), view === 'mailbox' ? ['two'] : ['one', 'two']);
      assert.deepEqual(Array.from(cache, row => row.id), ['one', 'two']);
      assert.equal(cache[0][Object.keys(changes)[0]], Object.values(changes)[0]);
      if (view !== 'mailbox') assert.equal(rows[0][Object.keys(changes)[0]], Object.values(changes)[0]);
    });
  }
}

test('an explicit removal still removes the message from search results and cache', () => {
  const { rows, cache } = update('unread', 'search', true);
  assert.deepEqual(Array.from(rows, row => row.id), ['two']);
  assert.deepEqual(Array.from(cache, row => row.id), ['two']);
});
