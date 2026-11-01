// a fake /api/signin that answers exactly the contract in tests/test_signin_contract.py, for the
// test page (static/signin-test.html) and the node tests. served only when ALLES_TEST_DATA=1.
// a scenario says how one provider behaves; everything else is the same for every scenario.

export const PROVIDERS = {
  github: { id: 'github', name: 'GitHub', flow: 'device', uses: [{ id: 'github', name: 'repos and issues' }] },
  microsoft: { id: 'microsoft', name: 'Microsoft', flow: 'device', uses: [{ id: 'mail', name: 'outlook mail' }] },
  google: { id: 'google', name: 'Google', flow: 'redirect', uses: [{ id: 'mail', name: 'gmail' }, { id: 'calendar', name: 'calendar' }, { id: 'models', name: 'gemini' }] },
  anthropic: { id: 'anthropic', name: 'Anthropic', flow: 'paste_code', uses: [{ id: 'models', name: 'claude models' }] },
};

const iso = ms => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

export function account(provider, use, extra = {}) {
  const base = Date.now();
  extra = Object.fromEntries(Object.entries(extra).filter(([, value]) => value !== undefined));
  return {
    id: `acc-${provider}-${use}`, provider, use, login: extra.login ?? 'jxherc', email: extra.email ?? null,
    scopes: ['read:user'], state: 'ok', error: null,
    signed_in_at: iso(base - 3 * 86400000), refreshed_at: null, expires_at: iso(base + 8 * 3600000),
    ...extra,
  };
}

// scenario: {provider, ready, notReadyText, accounts, start: 'device'|'redirect'|'paste_code'|'never'|'not_ready'|'provider_error',
//            outcome: 'waiting'|'done'|'expired'|'denied'|'error'|'lost', afterMs, codeError}
export function fakeSignin(scenario = {}) {
  const attempts = new Map();
  const calls = [];
  const accounts = (scenario.accounts || []).map(a => ({ ...a }));
  const p = PROVIDERS[scenario.provider || 'github'];
  const ready = scenario.ready !== false;
  const answer = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  const noReason = ready ? null : { code: 'no_client_id', text: scenario.notReadyText || `alles's ${p.name} sign in isn't set up yet` };

  async function fetcher(url, init = {}) {
    const method = (init.method || 'GET').toUpperCase();
    const path = String(url).replace(/^\/api\/signin/, '');
    const body = init.body ? JSON.parse(init.body) : {};
    calls.push({ method, path, body });
    if (method === 'GET' && path === '/providers') {
      return answer(200, { providers: [{ ...p, ready, not_ready: noReason }] });
    }
    if (method === 'GET' && path === '/accounts') return answer(200, { accounts });
    if (method === 'POST' && path === '/start') {
      const kind = ready ? scenario.start || p.flow : 'not_ready';
      if (kind === 'never') return new Promise(() => {});
      if (kind === 'not_ready') return answer(409, { detail: noReason?.text || 'not ready', code: 'not_ready' });
      if (kind === 'provider_error') return answer(502, { detail: scenario.providerError || 'device flow is disabled for this app', code: 'provider_error' });
      const id = `a${attempts.size + 1}`;
      const at = Date.now();
      attempts.set(id, { at, state: 'waiting', use: body.use, provider: body.provider });
      const common = { attempt: id, provider: body.provider, use: body.use };
      if (kind === 'device') {
        return answer(200, {
          ...common, flow: 'device', user_code: 'ABCD-EFGH', verify_url: 'https://github.com/login/device',
          verify_url_complete: null, expires_at: iso(at + 872000), poll_every: scenario.pollEvery ?? 5,
        });
      }
      return answer(200, { ...common, flow: kind, url: `https://${p.id}.example/authorize?state=${id}` });
    }
    let match = path.match(/^\/attempts\/([^/]+)$/);
    if (method === 'GET' && match) {
      const attempt = attempts.get(match[1]);
      if (!attempt || scenario.outcome === 'lost') return answer(404, { detail: 'that sign in is gone', code: 'attempt_not_found' });
      let state = 'waiting';
      if (attempt.state !== 'waiting') state = attempt.state;
      else if (Date.now() - attempt.at >= (scenario.afterMs ?? 600)) state = scenario.outcome || 'waiting';
      if (state === 'lost') state = 'waiting';
      if (state === 'done' && !attempt.account) {
        attempt.account = account(attempt.provider, attempt.use, { login: scenario.login });
        accounts.unshift(attempt.account);
      }
      attempt.state = state;
      const error = state === 'denied' ? { code: 'access_denied', text: `you said no on ${p.name}'s page` }
        : state === 'error' ? { code: 'provider_error', text: scenario.providerError || `${p.name} sent something alles couldn't read` } : null;
      return answer(200, { attempt: match[1], provider: attempt.provider, use: attempt.use, state, error, account: state === 'done' ? attempt.account : null });
    }
    match = path.match(/^\/attempts\/([^/]+)\/cancel$/);
    if (method === 'POST' && match) {
      const attempt = attempts.get(match[1]);
      if (attempt) attempt.state = 'cancelled';
      return answer(200, { attempt: match[1], state: 'cancelled' });
    }
    match = path.match(/^\/attempts\/([^/]+)\/code$/);
    if (method === 'POST' && match) {
      const attempt = attempts.get(match[1]);
      if (!attempt) return answer(404, { detail: 'that sign in is gone', code: 'attempt_not_found' });
      if (scenario.codeError) return answer(502, { detail: scenario.codeError, code: 'provider_error' });
      attempt.state = 'done';
      attempt.account = account(attempt.provider, attempt.use, { login: scenario.login || 'owner@claude.test' });
      accounts.unshift(attempt.account);
      return answer(200, { attempt: match[1], provider: attempt.provider, use: attempt.use, state: 'done', error: null, account: attempt.account });
    }
    match = path.match(/^\/accounts\/([^/]+)\/check$/);
    if (method === 'POST' && match) {
      const found = accounts.find(a => a.id === match[1]);
      if (!found) return answer(404, { detail: 'no such account', code: 'account_not_found' });
      if (scenario.checkFails) { found.state = 'needs_sign_in'; found.error = { code: 'refresh_failed', text: `${p.name} wants you to sign in again` }; }
      else found.refreshed_at = iso(Date.now());
      return answer(200, found);
    }
    match = path.match(/^\/accounts\/([^/]+)$/);
    if (method === 'DELETE' && match) {
      const at = accounts.findIndex(a => a.id === match[1]);
      if (at < 0) return answer(404, { detail: 'no such account', code: 'account_not_found' });
      accounts.splice(at, 1);
      return answer(200, { id: match[1], signed_out: true, revoked: scenario.revoked !== false });
    }
    return answer(404, { detail: 'not found', code: 'not_found' });
  }
  fetcher.calls = calls;
  return fetcher;
}
