import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';

import { sha256Fallback, sha256Hex } from '../../static/js/sha256.js';

const samples = ['', 'abc', 'a'.repeat(55), 'a'.repeat(56), 'a'.repeat(64), 'a'.repeat(1000),
  'plan the trip to montréal 🧳\nline two', 'x'.repeat(6000)];

test('the plain-http fallback matches real sha-256 at every padding edge', () => {
  for (const sample of samples) {
    const expected = createHash('sha256').update(sample, 'utf8').digest('hex');
    assert.equal(sha256Fallback(new TextEncoder().encode(sample)), expected, `length ${sample.length}`);
  }
});

test('sha256Hex agrees with node when web crypto is there', async () => {
  assert.equal(await sha256Hex('abc'), createHash('sha256').update('abc').digest('hex'));
});
