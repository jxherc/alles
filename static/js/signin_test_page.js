// every sign in state on one page, against a fake server that answers the contract
// (static/js/signin_fake.js). ?state=waiting shows one; no query shows all. ?freeze stops the
// clock so a countdown reads the same in every screenshot. served only when ALLES_TEST_DATA=1.
import { prepareLocalization } from './i18n.js';
import { initKokuenPrimitives } from './kokuen.js?v=5';
import { mountSignin } from './signin.js';
import { account, fakeSignin } from './signin_fake.js';

const params = new URLSearchParams(location.search);
const frozen = params.has('freeze');
const t0 = Date.now();
const fallback = { label: 'use an app password instead', reason: 'outlook.com accounts can also use an app password.', onClick() {} };

const STATES = {
  idle: { scenario: { provider: 'github' }, use: 'github', fallback },
  'not-ready': { scenario: { provider: 'github', ready: false }, use: 'github', fallback },
  starting: { scenario: { provider: 'microsoft', start: 'never' }, use: 'mail' },
  waiting: { scenario: { provider: 'microsoft', outcome: 'waiting' }, use: 'mail' },
  redirect: { scenario: { provider: 'google' }, use: 'mail' },
  paste: { scenario: { provider: 'anthropic' }, use: 'models' },
  'paste-error': { scenario: { provider: 'anthropic', codeError: 'that code was not accepted' }, use: 'models' },
  done: { scenario: { provider: 'github', outcome: 'done', afterMs: 300 }, use: 'github', doneClearMs: 0 },
  expired: { scenario: { provider: 'microsoft', outcome: 'expired', afterMs: 300 }, use: 'mail' },
  denied: { scenario: { provider: 'github', outcome: 'denied', afterMs: 300 }, use: 'github' },
  error: { scenario: { provider: 'github', start: 'provider_error' }, use: 'github' },
  lost: { scenario: { provider: 'microsoft', outcome: 'lost', afterMs: 300 }, use: 'mail' },
  'signed-in': { scenario: { provider: 'github', accounts: [account('github', 'github', { login: 'jxherc' })] }, use: 'github' },
  'signed-in-mail': {
    scenario: { provider: 'google', accounts: [account('google', 'mail', { login: 'jxherc', email: 'owner.with.a.long.address@example-mail.test' }), account('google', 'calendar', { login: 'jxherc' })] },
    use: 'mail',
    fallback: { label: 'use an app password instead', reason: 'gmail also takes an app password.', onClick() {} },
  },
  'needs-sign-in': {
    scenario: { provider: 'microsoft', accounts: [{ ...account('microsoft', 'mail', { login: 'owner@outlook.test' }), state: 'needs_sign_in', error: { code: 'refresh_failed', text: 'microsoft wants you to sign in again' } }] },
    use: 'mail',
  },
  'account-error': {
    scenario: { provider: 'github', accounts: [{ ...account('github', 'github'), state: 'error', error: { code: 'provider_error', text: "github didn't answer, try again later" } }] },
    use: 'github',
  },
};

await prepareLocalization({ language: params.get('lang') || 'en' });
// the app wires every button as a kokuen action (app.js); without it the page drew the old
// muted .btn, so copy read as disabled next to the primary
initKokuenPrimitives(document);
const names = params.get('state') ? [params.get('state')] : Object.keys(STATES);
if (names.length === 1) document.body.classList.add('single');
const root = document.getElementById('states');
window.__signin = {};
for (const name of names) {
  const state = STATES[name];
  if (!state) continue;
  const section = document.createElement('section');
  section.dataset.state = name;
  section.innerHTML = `<h2>${name}</h2><div></div>`;
  root.append(section);
  const fake = fakeSignin({ pollEvery: 0, ...state.scenario }); // answers at once so a state shows quickly
  window.__signin[name] = fake;
  mountSignin(section.lastElementChild, {
    use: state.use,
    fallback: state.fallback || null,
    fetch: fake,
    pollMinMs: 150,
    doneClearMs: state.doneClearMs ?? 6000,
    ...(frozen ? { now: () => t0 } : {}),
    openUrl: () => {},
  });
}
document.documentElement.dataset.ready = '1';
