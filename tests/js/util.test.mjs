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

test('escaped source passages remain literal text, including Markdown and math', () => {
  const raw = '![image](https://invalid.test/a) **bold** $x$ <mark>literal</mark> [link](https://invalid.test)';
  const escaped = raw.replace(/[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/g, '\\$&');
  const html = mdToHtml('> ' + escaped);
  assert.doesNotMatch(html, /<(?:img|a|strong|mark|code)\b/);
  assert.match(html, /\*\*bold\*\*/);
  assert.match(html, /\$x\$/);
  assert.match(html, /&lt;mark&gt;literal&lt;\/mark&gt;/);
});

test('escaped punctuation in a URL cannot bypass the scheme check', () => {
  assert.doesNotMatch(mdToHtml('[link](javascript\\:alert)'), /href="javascript:/i);
  assert.doesNotMatch(mdToHtml('![image](data\\:text/html,payload)'), /src="data:/i);
});

test('TeX escapes stay intact inside math while surrounding prose escapes are literal', () => {
  const html = mdToHtml(String.raw`\*prose\* $\{x\}$ and $x\,y$`);
  assert.ok(html.includes(String.raw`\{x\}`), html);
  assert.ok(html.includes(String.raw`x\,y`), html);
  assert.ok(html.includes('*prose*'), html);
  assert.ok(!html.includes('ESCAPED'), html);
});

test('escaped ampersands cannot introduce URL entities after scheme validation', () => {
  const html = mdToHtml(String.raw`[x](javascript\&#58;alert\(1\))`);
  assert.ok(!html.includes('href="javascript&#58;'), html);
  assert.ok(html.includes('href="javascript&amp;#58;'), html);
  const query = mdToHtml('[source](/?app=docs&doc=one.md&doc_hash=abc)');
  assert.ok(query.includes('href="/?app=docs&amp;doc=one.md&amp;doc_hash=abc"'), query);
});

test('generated image and link attributes stay opaque to later Markdown passes', () => {
  const input = String.raw`![x](/missing/\[x\]\(onerror=window.name=7331//\))`;
  const html = mdToHtml(input);
  assert.equal(html, '<img class="md-img" src="/missing/[x](onerror=window.name=7331//)" alt="x">');
  for (const syntax of ['**bold**', '*italic*', '~~deleted~~', '==marked==', '`code`', '{color:red}color{/color}']) {
    const image = mdToHtml(`![label](/${syntax})`);
    const link = mdToHtml(`[**label**](/${syntax})`);
    assert.ok(image.includes(`src="/${syntax}"`), image);
    assert.ok(link.includes(`href="/${syntax}"`), link);
    assert.ok(link.includes('<strong>label</strong>'), link);
  }
});

test('image alt text cannot receive generated markup or executable attributes', () => {
  const html = mdToHtml(String.raw`![<mark>**label** " onerror="x</mark>](/local/\(image\).png)`);
  assert.equal(html, '<img class="md-img" src="/local/(image).png" alt="&lt;mark&gt;**label** &quot; onerror=&quot;x&lt;/mark&gt;">');
});

test('links retain image labels, formatting and safe escaped destinations', () => {
  const html = mdToHtml(String.raw`[![image](/image.png)](/source\(1\)?a=1&b=2)`);
  assert.equal(html, '<a href="/source(1)?a=1&amp;b=2" target="_blank" rel="noreferrer"><img class="md-img" src="/image.png" alt="image"></a>');
  const literal = '\x00MARKUP0\x00 **outside** [inside](/safe)';
  const output = mdToHtml(literal);
  assert.ok(output.includes('\x00MARKUP0\x00'), output);
  assert.ok(output.includes('<strong>outside</strong>'), output);
  assert.ok(output.includes('href="/safe"'), output);
});

test('math syntax stays literal in attributes while link labels still render math', () => {
  assert.equal(mdToHtml('![price $x$](/cost$x$.png)'),
    '<img class="md-img" src="/cost$x$.png" alt="price $x$">');
  const link = mdToHtml('[$x$](/cost$x$)');
  assert.ok(link.includes('href="/cost$x$"'), link);
  assert.ok(link.includes('<span class="md-math-inline" data-tex="x">x</span>'), link);
  assert.doesNotMatch(link, /\x00/);
});
