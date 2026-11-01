import assert from 'node:assert/strict';
import test from 'node:test';

import { timeLeft, signinReturn } from '../../static/js/signin.js';
import { account, fakeSignin } from '../../static/js/signin_fake.js';

// the keys of every answer, copied from tests/test_signin_contract.py (the backend's own pin of
// the contract). the fake server behind the test page must match them exactly, or the page would
// show states the real server can't produce.
const PROVIDER = ['id', 'name', 'flow', 'ready', 'not_ready', 'uses'];
const DEVICE = ['attempt', 'provider', 'use', 'flow', 'user_code', 'verify_url', 'verify_url_complete', 'expires_at', 'poll_every'];
const REDIRECT = ['attempt', 'provider', 'use', 'flow', 'url'];
const ATTEMPT = ['attempt', 'provider', 'use', 'state', 'error', 'account'];
const ACCOUNT = ['id', 'provider', 'use', 'login', 'email', 'scopes', 'state', 'error', 'signed_in_at', 'refreshed_at', 'expires_at'];
const DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const keys = value => Object.keys(value).sort();
const same = (value, expected) => assert.deepEqual(keys(value), [...expected].sort());
const call = async (fake, method, path, body) => {
  const response = await fake(`/api/signin${path}`, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
  return { status: response.status, body: await response.json() };
};

test('providers and a device start have exactly the contract fields', async () => {
  const fake = fakeSignin({ provider: 'github' });
  const providers = (await call(fake, 'GET', '/providers')).body;
  same(providers, ['providers']);
  same(providers.providers[0], PROVIDER);
  assert.equal(providers.providers[0].not_ready, null);
  const started = (await call(fake, 'POST', '/start', { provider: 'github', use: 'github' })).body;
  same(started, DEVICE);
  assert.match(started.expires_at, DATE);
  assert.equal(typeof started.poll_every, 'number');
  const waiting = (await call(fake, 'GET', `/attempts/${started.attempt}`)).body;
  same(waiting, ATTEMPT);
  assert.equal(waiting.state, 'waiting');
});

test('a not ready provider says why in the contract shape, and start refuses with a 409', async () => {
  const fake = fakeSignin({ provider: 'github', ready: false });
  const provider = (await call(fake, 'GET', '/providers')).body.providers[0];
  assert.equal(provider.ready, false);
  assert.deepEqual(keys(provider.not_ready), ['code', 'text']);
  const refused = await call(fake, 'POST', '/start', { provider: 'github', use: 'github' });
  assert.equal(refused.status, 409);
  assert.deepEqual(keys(refused.body), ['code', 'detail']);
  assert.equal(refused.body.code, 'not_ready');
});

test('redirect and paste code starts, then finishing with a code, give an account', async () => {
  const redirect = await call(fakeSignin({ provider: 'google' }), 'POST', '/start', { provider: 'google', use: 'mail' });
  same(redirect.body, REDIRECT);
  assert.equal(redirect.body.flow, 'redirect');
  const fake = fakeSignin({ provider: 'anthropic' });
  const paste = (await call(fake, 'POST', '/start', { provider: 'anthropic', use: 'models' })).body;
  same(paste, REDIRECT);
  assert.equal(paste.flow, 'paste_code');
  const done = (await call(fake, 'POST', `/attempts/${paste.attempt}/code`, { code: 'x#y' })).body;
  same(done, ATTEMPT);
  assert.equal(done.state, 'done');
  same(done.account, ACCOUNT);
  assert.deepEqual((await call(fake, 'GET', '/accounts')).body.accounts.map(a => a.id), [done.account.id]);
});

test('every terminal attempt state carries its error in the contract shape', async () => {
  for (const [outcome, code] of [['denied', 'access_denied'], ['error', 'provider_error']]) {
    const fake = fakeSignin({ provider: 'github', outcome, afterMs: 0 });
    const started = (await call(fake, 'POST', '/start', { provider: 'github', use: 'github' })).body;
    const attempt = (await call(fake, 'GET', `/attempts/${started.attempt}`)).body;
    same(attempt, ATTEMPT);
    assert.equal(attempt.state, outcome);
    assert.deepEqual(keys(attempt.error), ['code', 'text']);
    assert.equal(attempt.error.code, code);
  }
  const expired = fakeSignin({ provider: 'github', outcome: 'expired', afterMs: 0 });
  const started = (await call(expired, 'POST', '/start', { provider: 'github', use: 'github' })).body;
  assert.equal((await call(expired, 'GET', `/attempts/${started.attempt}`)).body.state, 'expired');
  const lost = await call(fakeSignin({ outcome: 'lost' }), 'GET', '/attempts/nope');
  assert.equal(lost.status, 404);
  assert.deepEqual(keys(lost.body), ['code', 'detail']);
});

test('accounts: check, sign out with and without a revoke, and the cancel answer', async () => {
  const fake = fakeSignin({ provider: 'github', accounts: [account('github', 'github')], revoked: false });
  const [first] = (await call(fake, 'GET', '/accounts')).body.accounts;
  same(first, ACCOUNT);
  assert.match(first.signed_in_at, DATE);
  const checked = await call(fake, 'POST', `/accounts/${first.id}/check`);
  same(checked.body, ACCOUNT);
  const out = await call(fake, 'DELETE', `/accounts/${first.id}`);
  assert.deepEqual(keys(out.body), ['id', 'revoked', 'signed_out']);
  assert.equal(out.body.revoked, false);
  const started = (await call(fake, 'POST', '/start', { provider: 'github', use: 'github' })).body;
  assert.deepEqual((await call(fake, 'POST', `/attempts/${started.attempt}/cancel`)).body, { attempt: started.attempt, state: 'cancelled' });
});

test('time left reads m:ss and never goes below zero', () => {
  assert.equal(timeLeft(872000), '14:32');
  assert.equal(timeLeft(61000), '1:01');
  assert.equal(timeLeft(-5000), '0:00');
});

test('the redirect return reads only a plain attempt id from the address', () => {
  assert.equal(signinReturn('https://alles.example/?signin=a1b2'), 'a1b2');
  assert.equal(signinReturn('https://alles.example/?signin=a1b2%20x'), '');
  assert.equal(signinReturn('https://alles.example/'), '');
  assert.equal(signinReturn('not a url'), '');
});
