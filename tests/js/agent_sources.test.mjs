import assert from 'node:assert/strict';
import test from 'node:test';
import { sourcesHtml } from '../../static/js/runs.js';
import { readRecordTarget } from '../../static/js/recordlinks.js';

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

test('recorded reading versions survive confirmed-read and recall source links', () => {
  const hash = 'a'.repeat(64);
  const item = { kind: 'read', ref: 'article-1', label: 'saved article', hash };
  for (const sources of [[item], [{ kind: 'search', tool: 'recall', query: 'owned', results: [item] }]]) {
    const html = render({ sources });
    const href = html.match(/href="([^"]+)"/)[1].replaceAll('&amp;', '&');
    const url = new URL(href, 'http://synthetic.invalid/');
    assert.deepEqual(readRecordTarget(url), { view: 'read', id: item.ref, occurrence: '', hash });
    assert.equal(url.searchParams.get('app'), 'read');
    assert.equal(url.searchParams.has('doc_hash'), false);
    assert.match(html, /read version/);
  }
});

test('unversioned and invalid-hash reading links still open the live article', () => {
  for (const hash of [undefined, null, '', 'a'.repeat(63), 'a'.repeat(65), 'A'.repeat(64), 'g'.repeat(64), ' a'.repeat(32)]) {
    const html = render({ sources: [{ kind: 'read', ref: 'article-1', hash }] });
    const href = html.match(/href="([^"]+)"/)[1].replaceAll('&amp;', '&');
    assert.equal(href, '/?app=read&record_view=read&record=article-1');
    assert.deepEqual(readRecordTarget(new URL(href, 'http://synthetic.invalid/')), {
      view: 'read', id: 'article-1', occurrence: '',
    });
    assert.doesNotMatch(html, /record_hash|doc_hash|read version/);
  }
});

test('a valid source hash cannot make an invalid reading identity navigable', () => {
  for (const ref of ['', '../article', 'article?extra', 'a'.repeat(161)]) {
    const html = render({ sources: [{ kind: 'read', ref, hash: 'b'.repeat(64) }] });
    assert.doesNotMatch(html, /<a |record_hash/);
    assert.match(html, /<span class="run-src-item">/);
  }
});

test('ordinary document and web source links keep their existing destinations', () => {
  const hash = 'b'.repeat(64);
  const html = render({ sources: [
    { kind: 'doc', ref: 'notes/one.md', hash },
    { kind: 'document', path: 'notes/two.md' },
    { kind: 'url', url: 'https://example.invalid/article?edition=2', hash },
  ] });
  assert.match(html, /href="\/\?app=docs&amp;doc=notes%2Fone.md&amp;doc_hash=b{64}"/);
  assert.match(html, /href="\/\?app=docs&amp;doc=notes%2Ftwo.md"/);
  assert.match(html, /href="https:\/\/example.invalid\/article\?edition=2" target="_blank" rel="noopener noreferrer"/);
  assert.doesNotMatch(html, /record_hash/);
});
