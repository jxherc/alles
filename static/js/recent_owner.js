import { prompt as promptDialog } from './dialog.js';

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

async function performRecentOwnerConfirmation(request) {
  const meResponse = await request('/api/auth/me').catch(() => null);
  const me = meResponse?.ok ? await meResponse.json().catch(() => null) : null;
  if (me?.enabled === false) return true;

  const password = await promptDialog(
    'enter your Alles password to continue',
    '',
    { secret: true },
  );
  if (password == null) return false;

  const response = await request('/api/auth/reauth', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    const payload = await payloadFrom(response);
    throw new Error(payload?.message || payload?.detail || 'password confirmation failed');
  }
  return true;
}

export async function confirmRecentOwner(request = fetch) {
  if (!confirmationInFlight) {
    confirmationInFlight = performRecentOwnerConfirmation(request)
      .finally(() => { confirmationInFlight = null; });
  }
  return confirmationInFlight;
}

export async function requestWithRecentOwner(
  request,
  input,
  init = {},
  { confirmOwner = confirmRecentOwner } = {},
) {
  let response = await request(input, init);
  if (!await isRecentOwnerChallenge(response)) return response;
  if (!await confirmOwner(request)) throw new Error('owner confirmation cancelled');
  response = await request(input, init);
  return response;
}
