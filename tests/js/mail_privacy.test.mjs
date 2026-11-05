import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.localStorage = {
  getItem() { return null; },
  setItem() {},
  removeItem() {},
};
globalThis.window = {};

const { mailBodySrcdoc } = await import('../../static/js/mail.js');

test('html email bodies block remote resources before untrusted markup', () => {
  const srcdoc = mailBodySrcdoc('<img src="https://tracker.example/open.gif"><p>hello</p>');

  assert.match(srcdoc, /default-src 'none'/);
  assert.match(srcdoc, /img-src data: cid:/);
  assert.match(srcdoc, /base-uri 'none'/);
  assert.match(srcdoc, /form-action 'none'/);
  assert.ok(srcdoc.indexOf('Content-Security-Policy') < srcdoc.indexOf('tracker.example'));
});

test('html email bodies strip automatic meta refresh navigation', () => {
  const srcdoc = mailBodySrcdoc(
    '<META HTTP-EQUIV="refresh" content="0;url=https://tracker.example/view"><p>hello</p>',
  );
  assert.doesNotMatch(srcdoc, /http-equiv=["']refresh/i);
  assert.match(srcdoc, /<p>hello<\/p>/);

  const encoded = mailBodySrcdoc(
    '<meta http-equiv="ref&#x72;esh" content="0;url=https://tracker.example/encoded"><p>safe</p>',
  );
  assert.doesNotMatch(encoded, /tracker\.example\/encoded/);
});

// nov 5: the notice said remote images were blocked and offered no way to see them
test('show images allows pictures from the web for that message only', async () => {
  const { mailHasRemoteImages } = await import('../../static/js/mail.js');
  const html = '<img src="https://cdn.example/hero.png"><p>hello</p>';
  assert.match(mailBodySrcdoc(html), /img-src data: cid:;/);
  const shown = mailBodySrcdoc(html, { images: true });
  assert.match(shown, /img-src data: cid: https: http:;/);
  assert.match(shown, /default-src 'none'/);
  assert.match(shown, /form-action 'none'/);
  assert.ok(mailHasRemoteImages(html));
  assert.ok(mailHasRemoteImages('<td background="https://x.example/bg.png">'));
  assert.ok(mailHasRemoteImages('<div style="background:url(//x.example/a.png)">'));
  assert.ok(mailHasRemoteImages('<img srcset="a.png 1x, b.png 2x">'));
  assert.ok(!mailHasRemoteImages('<img src="cid:logo"><p>no web pictures</p>'));
  assert.ok(!mailHasRemoteImages('<img src="data:image/png;base64,AAAA">'));
  assert.ok(!mailHasRemoteImages('<a href="https://example.com">a link is not a picture</a>'));
});
