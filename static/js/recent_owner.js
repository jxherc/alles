// the one password prompt for every request the server protects with a recent owner sign in.
// every caller goes through requestWithRecentOwner (or fetchWithRecentOwner / openWithRecentOwner
// below); tests/test_recent_owner_routes_scan.py fails when a protected route is reached any
// other way, or when another file posts to /api/auth/reauth itself.
import { prompt as promptDialog } from './dialog.js';
import { t } from './i18n.js';
import { toast } from './util.js';

let confirmationInFlight = null;

async function payloadFrom(response) {
  try { return await response.clone().json(); }
  catch { return {}; }
}

export async function isRecentOwnerChallenge(response) {
  if (response?.status !== 403) return false;
  const payload = await payloadFrom(response);
  return payload?.code === 'recent_auth_required';
}

// ask and notify are the dialog and the toast; tests hand in their own
// stillWanted: the caller can drop out while the box is open (a call that was hung up), and
// then the password is never sent
async function performRecentOwnerConfirmation(
  request,
  { prompt = '', ask = promptDialog, stillWanted = () => true } = {},
) {
  const meResponse = await request('/api/auth/me').catch(() => null);
  const me = meResponse?.ok ? await meResponse.json().catch(() => null) : null;
  if (me?.enabled === false) return true;

  const password = await ask(
    prompt || t('settings.reauth_prompt'),
    '',
    { secret: true },
  );
  if (password == null || !stillWanted()) return false;

  const response = await request('/api/auth/reauth', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    const payload = await payloadFrom(response);
    throw new Error(payload?.message || payload?.detail || t('settings.reauth_failed'));
  }
  return true;
}

export async function confirmRecentOwner(request = fetch, options = {}) {
  if (!confirmationInFlight) {
    confirmationInFlight = performRecentOwnerConfirmation(request, options)
      .finally(() => { confirmationInFlight = null; });
  }
  return confirmationInFlight;
}

// onRefused decides what a cancelled or failed confirmation does:
//   unset: throw (the caller handles the error)
//   'response': give back the original refusal so the caller shows its own error. a wrong
//     password also toasts, a cancel is silent
//   a function: throw what it returns, called with 'cancelled' or 'failed'
// prompt: the sentence the password box asks with, for a caller that can say why
export async function requestWithRecentOwner(
  request,
  input,
  init = {},
  {
    confirmOwner = confirmRecentOwner,
    prompt = '',
    onRefused = null,
    notify = toast,
    stillWanted = () => true,
  } = {},
) {
  let response = await request(input, init);
  if (!await isRecentOwnerChallenge(response)) return response;
  let confirmed = false;
  let failure = null;
  try { confirmed = await confirmOwner(request, { prompt, stillWanted }); }
  catch (error) { failure = error; }
  if (!confirmed) {
    if (onRefused === 'response') {
      if (failure) notify(failure.message || t('settings.reauth_failed'), 'error');
      return response;
    }
    if (typeof onRefused === 'function') throw onRefused(failure ? 'failed' : 'cancelled');
    throw failure || new Error('owner confirmation cancelled');
  }
  // dropped out while the box was open: nothing is sent a second time
  if (!stillWanted()) return response;
  response = await request(input, init);
  return response;
}

// fetch that asks for the password when the server wants a recent one, then sends again.
// never throws for a refused confirmation: the 403 comes back
export function fetchWithRecentOwner(input, init = {}, options = {}) {
  return requestWithRecentOwner((...args) => fetch(...args), input, init, {
    onRefused: 'response',
    ...options,
  });
}

// a download or page the browser opens itself (it cannot retry a 403 for us): confirm first,
// then open it. returns whether it opened
export async function openWithRecentOwner(
  url,
  { prompt = '', open = target => { window.location = target; }, notify = toast } = {},
) {
  let confirmed = false;
  try { confirmed = await confirmRecentOwner(fetch, { prompt }); }
  catch (error) { notify(error.message || t('settings.reauth_failed'), 'error'); }
  if (confirmed) open(url);
  return confirmed;
}
