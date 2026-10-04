import test from 'node:test';
import assert from 'node:assert/strict';
import { readingPlace } from '../../static/js/reading_place.js';

const item = () => ({ position: 0.2, content_hash: 'local-text-version' });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('opening and restoring a saved place causes no write', async () => {
  const place = readingPlace(item(), () => assert.fail('unexpected write'));
  place.set(0.2);
  assert.equal(await place.drain(), true);
  assert.equal(place.unsaved, false);
});

test('a delayed acknowledgment cannot drop a newer reading place', async () => {
  const gate = deferred();
  const writes = [];
  const source = item();
  const place = readingPlace(source, async patch => {
    writes.push(patch);
    if (writes.length === 1) await gate.promise;
  });
  place.set(0.4);
  const first = place.flush();
  place.set(0.7);
  const overlapping = place.flush();
  assert.equal(writes.length, 1);
  gate.resolve();
  await Promise.all([first, overlapping]);
  assert.equal(source.position, 0.4);
  assert.equal(place.value, 0.7);
  assert.equal(await place.drain(), true);
  assert.deepEqual(writes.map(patch => patch.position), [0.4, 0.7]);
  assert.equal(source.position, 0.7);
});

test('returning to the earlier place while a write is pending persists that return', async () => {
  const gate = deferred();
  const writes = [];
  const place = readingPlace(item(), async patch => {
    writes.push(patch);
    if (writes.length === 1) await gate.promise;
  });
  place.set(0.6);
  const first = place.flush();
  place.set(0.2);
  gate.resolve();
  await first;
  assert.equal(await place.drain(), true);
  assert.deepEqual(writes.map(patch => patch.position), [0.6, 0.2]);
});

test('an uncertain save retries the same version and position', async () => {
  const writes = [];
  const place = readingPlace(item(), async patch => {
    writes.push(patch);
    if (writes.length === 1) throw new TypeError('local lost reply');
  });
  place.set(0.625);
  assert.equal(await place.flush(), false);
  assert.equal(place.unsaved, true);
  assert.equal(await place.drain(), true);
  assert.deepEqual(writes[0], writes[1]);
  assert.equal(writes[0].position, 0.625);
  assert.equal(writes[0].content_hash, 'local-text-version');
});

test('changed or deleted text blocks retries against the old version', async () => {
  for (const status of [409, 404]) {
    let writes = 0;
    let last;
    const place = readingPlace(item(), async () => {
      writes++;
      throw Object.assign(new Error('local changed text'), { status });
    });
    place.listen(state => { last = state; });
    place.set(0.6);
    assert.equal(await place.flush(), false);
    place.set(0.8);
    assert.equal(await place.drain(), false);
    assert.equal(writes, 1);
    assert.equal(last.blocked, true);
    assert.equal(place.blocked, true);
    assert.equal(place.value, 0.8);
  }
});

test('returning to the last confirmed place still reconciles an uncertain write', async () => {
  const writes = [];
  let stored = 0.2;
  const place = readingPlace(item(), async patch => {
    writes.push(patch.position);
    stored = patch.position;
    if (writes.length === 1) throw new TypeError('local lost reply after commit');
  });
  place.set(0.6);
  assert.equal(await place.flush(), false);
  place.set(0.2);
  assert.equal(await place.drain(), true);
  assert.equal(stored, 0.2);
  assert.deepEqual(writes, [0.6, 0.2]);
});

for (const late of ['success', 'rejected']) {
  test(`leaving sends the newest place immediately and ignores an older ${late}`, async () => {
    const gate = deferred();
    const source = item();
    const writes = [];
    const place = readingPlace(source, async patch => {
      writes.push(patch);
      if (writes.length === 1) {
        await gate.promise;
        if (late === 'rejected') throw Object.assign(new Error('superseded'), { status: 409 });
      }
    });
    place.set(0.6);
    const first = place.flush();
    place.set(0.75);
    assert.equal(await place.flush(true), true);
    assert.equal(writes.length, 2);
    assert.equal(writes[0].position_revision.split(':')[0], writes[1].position_revision.split(':')[0]);
    assert.ok(writes[1].position_revision.endsWith(':2'));
    assert.equal(source.position, 0.75);
    gate.resolve();
    await first;
    assert.equal(source.position, 0.75);
    assert.equal(place.unsaved, false);
    assert.equal(place.blocked, false);
    assert.equal(await place.drain(), true);
    assert.equal(writes.length, 2);
  });
}

test('leaving sends an intentional return to the original saved place', async () => {
  const gate = deferred();
  const source = item();
  const writes = [];
  const place = readingPlace(source, async patch => {
    writes.push(patch);
    if (writes.length === 1) await gate.promise;
  });
  place.set(0.6);
  const first = place.flush();
  place.set(0.2);
  await place.flush(true);
  assert.deepEqual(writes.map(p => p.position), [0.6, 0.2]);
  gate.resolve();
  await first;
  assert.equal(source.position, 0.2);
  assert.equal(place.unsaved, false);
});

test('visibility and pagehide reuse the pending final write', async () => {
  const gate = deferred();
  let writes = 0;
  const place = readingPlace(item(), async () => { writes++; await gate.promise; });
  place.set(0.6);
  const hidden = place.flush(true);
  const pagehide = place.flush(true);
  assert.equal(writes, 1);
  gate.resolve();
  await Promise.all([hidden, pagehide]);
  assert.equal(place.unsaved, false);
});

test('a failed final write stays retryable even when an earlier write succeeds', async () => {
  const gate = deferred();
  const writes = [];
  const place = readingPlace(item(), async patch => {
    writes.push(patch);
    const attempt = writes.length;
    if (attempt === 1) await gate.promise;
    if (attempt === 2) throw new TypeError('lost final reply');
  });
  place.set(0.6);
  const first = place.flush();
  place.set(0.8);
  assert.equal(await place.flush(true), false);
  gate.resolve();
  await first;
  assert.equal(place.unsaved, true);
  assert.equal(await place.drain(), true);
  assert.deepEqual(writes[1], writes[2]);
});
