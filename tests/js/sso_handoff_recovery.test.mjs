import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';
import { addSsoAuthCode } from '../../static/js/sso-state.js';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const handoff = app.slice(app.indexOf('async function _ssoRedirect('), app.indexOf('\nfunction _storedContextHandoffCode('));
const login = app.slice(app.indexOf('function _showLoginScreen()'), app.indexOf('\ninit();'));
const target = 'http://inbox.localhost:8000/folder?tag=one&tag=two#message';
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness(request, pending = target) {
  const elements = new Map(); const requests = []; const navigations = []; const stripped = [];
  let boots = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: 'authored-password', textContent: '', disabled: false,
      style: {}, dataset: {}, attributes: {}, listeners: {},
      addEventListener(type, handler) { this.listeners[type] = handler; },
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this.attributes[key]; },
      click() { if (!this.disabled) return this.listeners.click(); },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    t, tp,
    document: { getElementById: element, body: { classList: { add() {}, remove() {} } } },
    fetch: async (url, options) => { requests.push({ url, options }); return request(url, options); },
    location: { replace: url => navigations.push(url) }, addSsoAuthCode,
    _pendingSso: pending, _stripParam: key => stripped.push(key),
    _boot: () => { boots += 1; },
  });
  vm.runInContext(handoff + login + '\n_showLoginScreen();', context);
  return { context, element, requests, navigations, stripped, boots: () => boots,
    submit: () => element('login-submit').click(), redirect: () => context._ssoRedirect(target) };
}

for (const [name, refusal] of [
  ['HTTP refusal', () => response({ detail: 'authored refusal' }, 503)],
  ['offline', () => { throw new TypeError('offline'); }],
  ['missing code', () => response({})],
  ['invalid code type', () => response({ code: 42 })],
  ['invalid JSON', () => ({ ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } })],
]) {
  test(`SSO ${name} reports handoff failure without blaming the password`, async () => {
    const h = harness(url => url === '/api/auth/login' ? response({ ok: true }) : refusal());
    await h.submit(); await settle();
    assert.match(h.element('login-error').textContent, /signed in.*(?:could not|couldn't).*try again/i);
    assert.doesNotMatch(h.element('login-error').textContent, /wrong password/i);
    assert.equal(h.element('login-pw').attributes['aria-invalid'], undefined);
    assert.equal(h.element('login-pw').value, 'authored-password');
    assert.equal(h.element('login-submit').disabled, false);
    assert.equal(h.element('login-screen').style.display, 'flex');
    assert.equal(h.context._pendingSso, target);
    assert.deepEqual(h.stripped, [], 'keep the validated destination available after reload');
    assert.deepEqual(h.navigations, []);
    assert.equal(h.boots(), 0);
  });
}

test('an already-authenticated failed handoff retains its destination for retry', async () => {
  let attempts = 0;
  const h = harness(url => url === '/api/auth/login' ? response({ ok: true })
    : ++attempts === 1 ? response({}, 503) : response({ code: 'authored-once' }), null);
  await h.redirect();
  assert.equal(h.context._pendingSso, target);
  await h.submit(); await settle();
  assert.equal(h.element('login-error').textContent, '');
  assert.deepEqual(h.navigations, [addSsoAuthCode(target, 'authored-once')]);
  assert.equal(h.boots(), 0);
});

test('pending handoff keeps sign-in busy and suppresses repeated click and Enter', async () => {
  const held = deferred();
  const h = harness(url => url === '/api/auth/login' ? response({ ok: true }) : held.promise);
  const pending = h.submit(); await settle();
  assert.equal(h.element('login-submit').disabled, true);
  assert.equal(h.element('login-submit').attributes['aria-busy'], 'true');
  await h.submit(); h.element('login-pw').listeners.keydown({ key: 'Enter' });
  assert.equal(h.requests.filter(row => row.url === '/api/auth/login').length, 1);
  assert.equal(h.requests.filter(row => row.url === '/api/auth/handoff').length, 1);
  held.resolve(response({ code: 'authored-once' })); await pending; await settle();
  assert.equal(h.element('login-submit').disabled, false);
  assert.equal(h.element('login-submit').attributes['aria-busy'], undefined);
  assert.deepEqual(h.navigations, [addSsoAuthCode(target, 'authored-once')]);
});

test('handoff failure then retry keeps the full safe path, repeated query and hash', async () => {
  let attempts = 0;
  const h = harness(url => url === '/api/auth/login' ? response({ ok: true })
    : ++attempts === 1 ? response({}, 503) : response({ code: 'authored-retry' }));
  await h.submit(); await settle();
  await h.submit(); await settle();
  assert.deepEqual(h.navigations, [addSsoAuthCode(target, 'authored-retry')]);
  assert.equal(h.element('login-error').textContent, '');
  assert.equal(h.boots(), 0);
});
