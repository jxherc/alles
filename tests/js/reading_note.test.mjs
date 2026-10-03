import test from 'node:test';
import assert from 'node:assert/strict';
import { readingNoteText, readingSourceUrl } from '../../static/js/reading_note.js';
import { mdToHtml } from '../../static/js/util.js';
import { readRecordTarget } from '../../static/js/recordlinks.js';
import { setBaseDomain } from '../../static/js/subdomain.js?v=237';

const source = { id: 'article-1', title: 'A [source] with *formatting* & $math$', content_hash: 'a'.repeat(64) };

test('a reading note keeps the user text and an escaped exact source link', () => {
  const previous = globalThis.location;
  globalThis.location = new URL('http://127.0.0.1:1234/?view=read');
  try {
    const text = '    my note\n\n**keep this**  ';
    const result = readingNoteText(source, text);
    assert.ok(result.startsWith(text + '\n\nsource: '));
    const html = mdToHtml(result);
    assert.match(html, /A \[source\] with \*formatting\* &amp; \$math\$/);
    const href = html.match(/href="([^"]+)"/)[1].replace(/&amp;/g, '&');
    assert.deepEqual(readRecordTarget(new URL(href, location)), { view: 'read', id: source.id, occurrence: '', hash: source.content_hash });
    assert.ok(href.startsWith('/?view=read&'));
    assert.throws(() => readingNoteText(source, ' \n'), /write a note/);
    assert.throws(() => readingSourceUrl({ ...source, content_hash: '' }), /source could not be confirmed/);
  } finally { globalThis.location = previous; }
});

test('a source link targets the canonical library host in a subdomain deployment', () => {
  const previous = globalThis.location;
  globalThis.location = new URL('https://docs.example.test:8443/?view=wiki');
  setBaseDomain('example.test');
  try {
    const url = new URL(readingSourceUrl(source));
    assert.equal(url.origin, 'https://library.example.test:8443');
    assert.equal(url.searchParams.get('view'), 'read');
    assert.equal(readRecordTarget(url).hash, source.content_hash);
  } finally { globalThis.location = previous; setBaseDomain('localhost'); }
});


test('an unfinished fenced note cannot swallow its generated source link', () => {
  const previous = globalThis.location;
  globalThis.location = new URL('http://127.0.0.1:1234/?view=read');
  try {
    const note = '```js\nconst unfinished = true;';
    const result = readingNoteText(source, note);
    assert.ok(result.includes(note));
    assert.match(mdToHtml(result), /<a href="[^"]*record=article-1/);
  } finally { globalThis.location = previous; }
});
