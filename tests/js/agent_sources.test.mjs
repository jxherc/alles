import assert from 'node:assert/strict';
import test from 'node:test';
import { sourcesHtml } from '../../static/js/runs.js';

const render = patch => sourcesHtml({ sources: [], actions: [], outcomes: {}, history_complete: true, ...patch });

test('confirmed document links retain the exact path and read version', () => {
  const html = render({ sources: [{ kind: 'document', path: 'notes/a & b.md', hash: 'a'.repeat(64) }] });
  assert.match(html, /href="\/\?app=docs&amp;doc=notes%2Fa%20%26%20b.md&amp;doc_hash=a{64}"/);
  assert.match(html, /read version/);
});

test('search excerpts and completed changes stay separate from reads', () => {
  const html = render({ sources: [{ kind: 'search', tool: 'docs_search', query: 'local', results: [{ kind: 'document', path: 'found.md' }] }], actions: [{ tool: 'write_file', path: 'saved.md' }] });
  assert.match(html, /search results/);
  assert.match(html, /other completed tools/);
  assert.doesNotMatch(html, /confirmed reads|read version/);
  assert.match(html, /do not verify every claim/);
});

test('failed, unfinished and unknown history never implies a clean empty run', () => {
  const html = render({ outcomes: { failed: 2, unfinished: 1, unknown: 3 }, history_complete: false });
  assert.match(html, /2 failed or denied/);
  assert.match(html, /1 without a final result/);
  assert.match(html, /3 with an unknown outcome/);
  assert.match(html, /incomplete history/);
  assert.doesNotMatch(html, /nothing external touched/);
  assert.match(sourcesHtml({}), /source history unavailable/);
});

test('source labels are escaped and only HTTP links become external anchors', () => {
  const html = render({ sources: [
    { kind: 'url', url: 'javascript:localSyntheticMarker', label: '<synthetic>' },
    { kind: 'url', url: 'http://127.0.0.1:1/owned?a=1&b=2', label: 'owned "fixture"' },
  ] });
  assert.doesNotMatch(html, /href="javascript:|<synthetic>/);
  assert.match(html, /&lt;synthetic&gt;/);
  assert.match(html, /target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /a=1&amp;b=2/);
});

test('recall links use exact Docs and saved-reader destinations', () => {
  const html = render({ sources: [{ kind: 'search', tool: 'recall', query: 'owned', results: [
    { kind: 'doc', ref: 'Research/one.md', label: 'one' },
    { kind: 'read', ref: 'article-1', label: 'saved article' },
  ] }] });
  assert.match(html, /doc=Research%2Fone.md/);
  assert.match(html, /record_view=read&amp;record=article-1/);
});
