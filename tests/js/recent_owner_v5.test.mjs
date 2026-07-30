import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isRecentOwnerChallenge,
  requestWithRecentOwner,
} from '../../static/js/recent_owner.js';

function response(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('recent-owner retry is limited to the exact backend challenge code', async () => {
  assert.equal(await isRecentOwnerChallenge(response(403, { code: 'recent_auth_required' })), true);
  assert.equal(await isRecentOwnerChallenge(response(403, { code: 'permission_denied' })), false);
  assert.equal(await isRecentOwnerChallenge(response(401, { code: 'recent_auth_required' })), false);
});

test('a confirmed recent-owner challenge retries the original request exactly once', async () => {
  const calls = [];
  const request = async (input, init) => {
    calls.push([input, init]);
    return calls.length === 1
      ? response(403, { code: 'recent_auth_required' })
      : response(200, { ok: true });
  };
  let confirmations = 0;
  const init = { method: 'POST', body: JSON.stringify({ preserved: true }) };
  const result = await requestWithRecentOwner(request, '/api/protected', init, {
    confirmOwner: async () => { confirmations += 1; return true; },
  });
  assert.equal(result.status, 200);
  assert.equal(confirmations, 1);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0], calls[1]);
});

test('another 403 never prompts and cancellation never retries', async () => {
  let calls = 0;
  let confirmations = 0;
  const denied = await requestWithRecentOwner(
    async () => { calls += 1; return response(403, { code: 'permission_denied' }); },
    '/api/protected',
    { method: 'POST' },
    { confirmOwner: async () => { confirmations += 1; return true; } },
  );
  assert.equal(denied.status, 403);
  assert.equal(calls, 1);
  assert.equal(confirmations, 0);

  calls = 0;
  await assert.rejects(
    requestWithRecentOwner(
      async () => { calls += 1; return response(403, { code: 'recent_auth_required' }); },
      '/api/protected',
      { method: 'POST' },
      { confirmOwner: async () => false },
    ),
    /owner confirmation cancelled/,
  );
  assert.equal(calls, 1);
});
