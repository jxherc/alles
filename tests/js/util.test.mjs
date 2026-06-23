// unit tests for url-scheme filtering in markdown rendering (static/js/util.js).
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { _safeUrl, escapeHtml, mdToHtml } from '../../static/js/util.js';

test('escapeHtml escapes quotes (attribute-injection defense)', () => {
  const out = escapeHtml('" onfocus=alert(1) x="<b>');
  assert.ok(!out.includes('"')); // no raw double-quote can break out of value="..."
  assert.ok(!out.includes("'"));
  assert.ok(out.includes('&quot;'));
  assert.ok(out.includes('&lt;b&gt;'));
});

test('_safeUrl blocks dangerous schemes', () => {
  assert.equal(_safeUrl('javascript:alert(1)'), '#');
  assert.equal(_safeUrl('  JavaScript:alert(1)'), '#');
  assert.equal(_safeUrl('vbscript:x'), '#');
  assert.equal(_safeUrl('data:text/html,<script>'), '#');
  assert.equal(_safeUrl('file:///etc/passwd'), '#');
});

test('_safeUrl keeps safe urls', () => {
  assert.equal(_safeUrl('https://example.com'), 'https://example.com');
  assert.equal(_safeUrl('/relative/path'), '/relative/path');
  assert.equal(_safeUrl('#anchor'), '#anchor');
  assert.equal(_safeUrl('mailto:a@b.com'), 'mailto:a@b.com');
});

test('mdToHtml neutralizes a javascript: link', () => {
  const html = mdToHtml('[click me](javascript:alert(document.cookie))');
  assert.ok(!/javascript:/i.test(html)); // no clickable script link survives
  assert.ok(html.includes('href="#"'));
});

test('mdToHtml keeps a normal link', () => {
  const html = mdToHtml('[site](https://example.com)');
  assert.ok(html.includes('href="https://example.com"'));
});
