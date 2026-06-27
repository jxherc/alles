// unit tests for the artifact parsers in static/js/artifacts.js.
// run: node --test tests/js/artifacts.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { extractArtifacts, stripArtifacts } from '../../static/js/artifacts.js';

test('extracts a single artifact with attrs', () => {
  const a = extractArtifacts('hi <aide-artifact type="html" title="Page" lang="html">＜div＞</aide-artifact> bye');
  assert.equal(a.length, 1);
  assert.equal(a[0].type, 'html');
  assert.equal(a[0].title, 'Page');
  assert.equal(a[0].lang, 'html');
  assert.equal(a[0].content, '＜div＞');
});

test('applies defaults when attrs are missing', () => {
  const a = extractArtifacts('<aide-artifact>body</aide-artifact>');
  assert.equal(a[0].type, 'code');
  assert.equal(a[0].title, 'artifact');
  assert.equal(a[0].lang, '');
});

test('extracts multiple artifacts in order', () => {
  const a = extractArtifacts('<aide-artifact title="one">a</aide-artifact> mid <aide-artifact title="two">b</aide-artifact>');
  assert.equal(a.length, 2);
  assert.deepEqual(a.map(x => x.title), ['one', 'two']);
  assert.deepEqual(a.map(x => x.content), ['a', 'b']);
});

test('no artifacts → empty list', () => {
  assert.deepEqual(extractArtifacts('just regular text'), []);
});

test('stripArtifacts removes the blocks and trims', () => {
  const out = stripArtifacts('before <aide-artifact title="x">stuff</aide-artifact> after');
  assert.equal(out, 'before  after');
});

test('stripArtifacts on multiline content', () => {
  const out = stripArtifacts('keep\n<aide-artifact>\nline1\nline2\n</aide-artifact>\nkeep2');
  assert.ok(!out.includes('line1'));
  assert.ok(out.includes('keep'));
  assert.ok(out.includes('keep2'));
});
