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
