import assert from 'node:assert/strict';
import test from 'node:test';

import {
  confirmRecentOwner,
  openWithRecentOwner,
  requestWithRecentOwner,
} from '../../static/js/recent_owner.js';

function response(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('the shared prompt asks once with the caller words and sends the password to reauth only', async () => {
  const seen = [];
  const request = async (input, init) => {
    seen.push([input, init]);
    if (input === '/api/auth/me') return response(200, { enabled: true });
    if (input === '/api/auth/reauth') return response(200, { ok: true });
    return seen.filter(([url]) => url === '/api/protected').length === 1
      ? response(403, { code: 'recent_auth_required' })
      : response(200, { ok: true });
  };
  const asked = [];
  const result = await requestWithRecentOwner(request, '/api/protected', { method: 'POST' }, {
    prompt: 'enter your Alles password to use full access',
    confirmOwner: (asker, options) => confirmRecentOwner(asker, {
      ...options,
      ask: async (message, _default, box) => { asked.push([message, box]); return 'pw'; },
    }),
  });
  assert.equal(result.status, 200);
  assert.deepEqual(asked, [['enter your Alles password to use full access', { secret: true }]]);
  const reauth = seen.filter(([url]) => url === '/api/auth/reauth');
  assert.equal(reauth.length, 1);
  assert.equal(JSON.parse(reauth[0][1].body).password, 'pw');
});

test('with no password set the prompt never shows', async () => {
  let asked = 0;
  const ok = await confirmRecentOwner(
    async () => response(200, { enabled: false }),
    { ask: async () => { asked += 1; return 'x'; } },
  );
  assert.equal(ok, true);
  assert.equal(asked, 0);
});

test('a refused confirmation gives the 403 back, and only a wrong password says so', async () => {
  const toasts = [];
  const notify = (...args) => toasts.push(args);
  for (const [password, expected] of [[null, 0], ['wrong', 1]]) {
    toasts.length = 0;
    const refused = await requestWithRecentOwner(
      async (input) => {
        if (input === '/api/auth/me') return response(200, { enabled: true });
        if (input === '/api/auth/reauth') return response(401, { detail: 'invalid password' });
        return response(403, { code: 'recent_auth_required' });
      },
      '/api/protected',
      { method: 'POST' },
      {
        onRefused: 'response',
        notify,
        confirmOwner: (asker, options) => confirmRecentOwner(asker, { ...options, ask: async () => password }),
      },
    );
    assert.equal(refused.status, 403);
    assert.equal(toasts.length, expected);
  }
});

test('onRefused can name the error, and a caller that left never sends the password or the request again', async () => {
  const calls = [];
  const request = async (input) => {
    calls.push(input);
    if (input === '/api/auth/me') return response(200, { enabled: true });
    return response(403, { code: 'recent_auth_required' });
  };
  await assert.rejects(
    requestWithRecentOwner(request, '/api/protected', {}, {
      onRefused: why => new Error(`refused: ${why}`),
      confirmOwner: async () => false,
    }),
    /refused: cancelled/,
  );
  let wanted = true;
  calls.length = 0;
  const left = await requestWithRecentOwner(request, '/api/protected', {}, {
    onRefused: 'response',
    stillWanted: () => wanted,
    confirmOwner: (asker, options) => confirmRecentOwner(asker, {
      ...options,
      ask: async () => { wanted = false; return 'pw'; },
    }),
  });
  assert.equal(left.status, 403);
  assert.equal(calls.includes('/api/auth/reauth'), false);
  assert.equal(calls.filter(url => url === '/api/protected').length, 1);
});

test('a download opens once the server says no password is needed', async () => {
  const real = globalThis.fetch;
  const opened = [];
  try {
    globalThis.fetch = async (input) => (input === '/api/auth/me'
      ? response(200, { enabled: false }) : response(200, {}));
    assert.equal(await openWithRecentOwner('/api/backup', { open: url => opened.push(url) }), true);
    assert.deepEqual(opened, ['/api/backup']);
  } finally {
    globalThis.fetch = real;
  }
});
