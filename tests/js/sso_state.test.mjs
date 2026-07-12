import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  addSsoAuthCode,
  buildApexBrokerUrl,
  normalizeSsoTarget,
  stripTransientParams,
} from '../../static/js/sso-state.js';

const localContext = {
  protocol: 'http:',
  port: '8000',
  baseDomain: 'localhost',
  allowedSubdomains: new Set([
    'aide', 'docs', 'files', 'gallery', 'notes', 'photos',
  ]),
};

test('apex broker carries the complete files target', () => {
  const target = 'http://files.localhost:8000/?p=work%2F2026&sort=name&tag=one&tag=two#preview';
  const broker = new URL(buildApexBrokerUrl(target, 'localhost'));

  assert.equal(broker.href.startsWith('http://localhost:8000/?_sso='), true);
  assert.equal(broker.searchParams.get('_sso'), new URL(target).href);
});

test('normalizer accepts full and encoded canonical or legacy targets', () => {
  const targets = [
    'http://docs.localhost:8000/#project%20roadmap',
    'http://aide.localhost:8000/#session-018fbe4d',
    'http://notes.localhost:8000/#legacy%20note',
    'http://photos.localhost:8000/?album=favorites',
  ];

  for (const target of targets) {
    assert.equal(normalizeSsoTarget(target, localContext), new URL(target).href);
    assert.equal(normalizeSsoTarget(encodeURIComponent(target), localContext), new URL(target).href);
  }
});

test('normalizer preserves ask and web state', () => {
  const target = 'http://aide.localhost:8000/?ask=what+changed%3F&web=1&source=palette#new';
  const normalized = normalizeSsoTarget(target, localContext);
  const url = new URL(normalized);

  assert.equal(url.searchParams.get('ask'), 'what changed?');
  assert.equal(url.searchParams.get('web'), '1');
  assert.equal(url.searchParams.get('source'), 'palette');
  assert.equal(url.hash, '#new');
});

test('auth code keeps unicode, duplicate query values, path, and hash', () => {
  const target = 'http://docs.localhost:8000/na%C3%AFve?q=%E4%BD%A0%E5%A5%BD&q=caf%C3%A9&_sso=old&_auth=stale&_auth=older#r%C3%A9sum%C3%A9';
  const result = new URL(addSsoAuthCode(target, 'once-123'));

  assert.equal(result.pathname, '/na%C3%AFve');
  assert.deepEqual(result.searchParams.getAll('q'), ['你好', 'café']);
  assert.equal(result.searchParams.has('_sso'), false);
  assert.deepEqual(result.searchParams.getAll('_auth'), ['once-123']);
  assert.equal(result.hash, '#r%C3%A9sum%C3%A9');
});

test('stripTransientParams removes only named state', () => {
  const target = 'http://files.localhost:8000/?p=docs&_auth=old&tag=a&tag=b&_sso=relay&web=1#preview';
  const result = new URL(stripTransientParams(target, ['_auth', '_sso']));

  assert.deepEqual([...result.searchParams], [
    ['p', 'docs'], ['tag', 'a'], ['tag', 'b'], ['web', '1'],
  ]);
  assert.equal(result.pathname, '/');
  assert.equal(result.hash, '#preview');
});

test('target validation rejects unsafe origins and malformed input', () => {
  const rejected = [
    'http://evil.test:8000/',
    'http://files.localhost.evil.test:8000/',
    'http://localhost:8000/',
    'https://files.localhost:8000/',
    'http://files.localhost:9000/',
    'http://owner@files.localhost:8000/',
    'http://owner:secret@files.localhost:8000/',
    'http://nested.files.localhost:8000/',
    'http://admin.localhost:8000/',
    'http://files..localhost:8000/',
    'http://files.localhost:8000/%zz',
    'http://files.localhost:8000/\\evil',
    '/relative/path',
    'javascript:alert(1)',
    'not a url',
    '',
  ];

  for (const target of rejected) {
    assert.equal(normalizeSsoTarget(target, localContext), null, target);
    assert.equal(normalizeSsoTarget(encodeURIComponent(target), localContext), null, `encoded ${target}`);
  }
});

test('normalizer enforces real-domain protocol, exact port, and direct app label', () => {
  const context = {
    protocol: 'https:',
    port: '8443',
    baseDomain: 'example.test',
    allowedSubdomains: ['aide', 'docs', 'notes'],
  };

  assert.equal(
    normalizeSsoTarget('https://docs.example.test:8443/guide#start', context),
    'https://docs.example.test:8443/guide#start',
  );
  assert.equal(normalizeSsoTarget('https://docs.example.test/guide', context), null);
  assert.equal(normalizeSsoTarget('https://evil.docs.example.test:8443/guide', context), null);
  assert.equal(normalizeSsoTarget('https://gallery.example.test:8443/guide', context), null);
});

test('URL transformations keep all ordinary query pairs across a state matrix', () => {
  const paths = ['/', '/folder/a', '/%E6%96%87%E4%BB%B6'];
  const hashes = ['', '#doc', '#session-123', '#%E4%BD%A0%E5%A5%BD'];
  const queries = [
    [['p', 'a/b']],
    [['q', 'one'], ['q', 'two']],
    [['ask', 'latest release'], ['web', '1']],
  ];

  for (const path of paths) for (const hash of hashes) for (const pairs of queries) {
    const target = new URL('http://aide.localhost:8000' + path + hash);
    for (const [name, value] of pairs) target.searchParams.append(name, value);
    target.searchParams.append('_sso', 'stale');

    const normalized = normalizeSsoTarget(encodeURIComponent(target.href), localContext);
    const authed = new URL(addSsoAuthCode(normalized, 'fresh'));
    assert.equal(authed.pathname, target.pathname);
    assert.equal(authed.hash, target.hash);
    assert.deepEqual(
      [...authed.searchParams].filter(([name]) => !name.startsWith('_')),
      pairs,
    );
    assert.equal(authed.searchParams.get('_auth'), 'fresh');
    assert.equal(authed.searchParams.has('_sso'), false);
  }
});
