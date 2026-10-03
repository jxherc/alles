import test from 'node:test';
import assert from 'node:assert/strict';
import { recordTarget, readRecordTarget, withRecordTarget, replaceLinkedRecord } from '../../static/js/recordlinks.js';

test('a record survives a cross-app URL round trip without losing unrelated parameters', () => {
  const target = recordTarget('calendar', 'event-abc', '2026-10-01');
  const url = withRecordTarget('https://plan.example.test/?view=calendar&keep=yes', target);
  assert.deepEqual(readRecordTarget(url), target);
  assert.equal(url.searchParams.get('keep'), 'yes');
  assert.equal(url.searchParams.get('view'), 'calendar');
});

test('only known record destinations and opaque ids are accepted', () => {
  for (const id of ['', null, '../secrets', 'a" onclick="', 'a'.repeat(161)]) {
    assert.equal(recordTarget('tasks', id), null);
  }
  for (const view of ['https://example.com', 'settings', '__proto__', null]) {
    assert.equal(recordTarget(view, 'task-1'), null);
  }
  assert.equal(readRecordTarget('https://example.test/?record=task-1'), null);
});

test('task links discard unrelated event occurrences', () => {
  const target = recordTarget('tasks', 'task-1', '2026-10-01');
  const url = withRecordTarget('https://example.test/?occurrence=2025-01-01', target);
  assert.equal(url.searchParams.has('occurrence'), false);
  assert.deepEqual(readRecordTarget(url), { view: 'tasks', id: 'task-1', occurrence: '' });
});

test('reading source links preserve exact item and text version without leaking it to other records', () => {
  const hash = 'a'.repeat(64);
  const target = recordTarget('read', 'article-1', '', hash);
  const url = withRecordTarget('https://library.example.test/?view=read', target);
  assert.deepEqual(readRecordTarget(url), { view: 'read', id: 'article-1', occurrence: '', hash });
  assert.equal(withRecordTarget(url, recordTarget('tasks', 'task-1')).searchParams.has('record_hash'), false);
  assert.equal(recordTarget('read', 'article-1', '', 'invalid').hash, undefined);
});

test('mail source links keep only the Plan record identity across hosts', () => {
  for (const kind of ['task', 'event']) {
    const target = recordTarget('mail', `${kind}-abc-123`);
    const url = withRecordTarget('https://inbox.example.test/?view=mail', target);
    assert.deepEqual(readRecordTarget(url), target);
    assert.equal(url.searchParams.get('record'), `${kind}-abc-123`);
  }
  assert.equal(recordTarget('mail', 'account-123'), null);
  assert.equal(recordTarget('mail', 'task-'), null);
});

test('saving a linked series keeps its selected day and follows an explicit date change', () => {
  const previousLocation = globalThis.location;
  const previousHistory = globalThis.history;
  globalThis.location = new URL('https://plan.example.test/?view=calendar&record_view=calendar&record=series-1&occurrence=2026-10-01');
  globalThis.history = { state: {}, replaceState(_state, _title, url) { globalThis.location = new URL(url, location); } };
  try {
    replaceLinkedRecord('calendar', 'series-1', 'series-1');
    assert.equal(readRecordTarget(location).occurrence, '2026-10-01');
    replaceLinkedRecord('calendar', 'series-1', 'series-1', '2026-10-02');
    assert.equal(readRecordTarget(location).occurrence, '2026-10-02');
    replaceLinkedRecord('calendar', 'series-1', 'child-1');
    assert.deepEqual(readRecordTarget(location), { view: 'calendar', id: 'child-1', occurrence: '' });
    replaceLinkedRecord('calendar', 'child-1', 'child-1', '');
    assert.equal(readRecordTarget(location).occurrence, '');
  } finally {
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
    if (previousHistory === undefined) delete globalThis.history;
    else globalThis.history = previousHistory;
  }
});
