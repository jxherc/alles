// apps on paths (nov 6): on one address each app is /docs, /plan; the page reads the app from
// the path and writes it back there
import test from 'node:test';
import assert from 'node:assert/strict';

function at(href) {
  const url = new URL(href);
  globalThis.location = {
    hostname: url.hostname, port: url.port, protocol: url.protocol, pathname: url.pathname,
  };
}

at('https://alles.example.com/');
const sub = await import('../../static/js/subdomain.js');

test('a path names its app, an old name included, anything else names none', () => {
  assert.equal(sub.pathSub('/docs'), 'docs');
  assert.equal(sub.pathSub('/Plan/'), 'plan');
  assert.equal(sub.pathSub('/mail'), 'mail');
  assert.equal(sub.pathSub('/'), '');
  assert.equal(sub.pathSub('/static/js/app.js'), '');
  assert.equal(sub.pathSub('/constructor'), '');
  assert.equal(sub.pathSub('/__proto__'), '');
});

test('an app is written back as its own path, home as the root', () => {
  assert.equal(sub.appPath('docs'), '/docs');
  assert.equal(sub.appPath('passwords'), '/passwords');
  assert.equal(sub.appPath(''), '/');
  assert.equal(sub.appPath('mail'), '/');
});

test('the path choice keeps a real domain on one host', () => {
  sub.setBaseDomain('alles.example.com');
  sub.setAppUrls('');
  at('https://alles.example.com/docs');
  assert.equal(sub.singleHost(), false);
  assert.equal(sub.routeSub(), '');
  sub.setAppUrls('path');
  assert.equal(sub.singleHost(), true);
  assert.equal(sub.routeSub(), 'docs');
  sub.setAppUrls('sideways');
  assert.equal(sub.singleHost(), false);
});

test('an ip or a tailnet name reads its app from the path without any choice', () => {
  sub.setAppUrls('');
  at('http://100.79.59.4:6769/plan');
  assert.equal(sub.singleHost(), true);
  assert.equal(sub.routeSub(), 'plan');
  at('https://mac.tail1234.ts.net/inbox');
  assert.equal(sub.routeSub(), 'inbox');
});

test('a subdomain still names its app when apps live on subdomains', () => {
  sub.setAppUrls('subdomain');
  sub.setBaseDomain('alles.example.com');
  at('https://docs.alles.example.com/');
  assert.equal(sub.singleHost(), false);
  assert.equal(sub.routeSub(), 'docs');
});
