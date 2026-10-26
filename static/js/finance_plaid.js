import { requestWithRecentOwner } from './recent_owner.js';
import { t } from './i18n.js';

const RETURN_PATH = '/api/finance/connections/plaid/return';
const SESSION_KEY = 'alles:finance-plaid-link';
let sdkPending = null;

export async function bankRequest(path, options = {}) {
  const init = { ...options };
  if (init.body && typeof init.body !== 'string') {
    init.headers = { 'content-type': 'application/json', ...(init.headers || {}) };
    init.body = JSON.stringify(init.body);
  }
  const response = await requestWithRecentOwner(fetch, path, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || t('finance.request_failed_status', { status: response.status }));
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error(t('finance.bank_response_unconfirmed'));
  }
  return payload;
}

export function plaidSdk() {
  if (window.Plaid?.create) return Promise.resolve(window.Plaid);
  if (sdkPending) return sdkPending;
  sdkPending = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js';
    script.async = true;
    script.dataset.allesPlaidLink = '1';
    const finish = error => {
      clearTimeout(timer);
      script.onload = script.onerror = null;
      if (error) { script.remove(); reject(error); }
      else resolve(window.Plaid);
    };
    const timer = setTimeout(() => finish(new Error(t('finance.plaid_not_loaded'))), 20000);
    script.onload = () => finish(window.Plaid?.create ? null : new Error(t('finance.plaid_not_loaded')));
    script.onerror = () => finish(new Error(t('finance.plaid_not_loaded_connection')));
    document.head.append(script);
  }).finally(() => { sdkPending = null; });
  return sdkPending;
}

function clearBinding(binding) {
  try {
    const current = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
    if (!binding || current?.link_token === binding.link_token) sessionStorage.removeItem(SESSION_KEY);
  } catch {}
}

function returnUrl(value) {
  const url = new URL(value);
  if (url.origin !== location.origin || url.pathname !== RETURN_PATH || url.hash || url.username || url.password) {
    throw new Error(t('finance.plaid_return_mismatch'));
  }
  return url;
}

export function plaidReturnBinding(href = location.href) {
  try {
    const received = returnUrl(href);
    if (received.searchParams.getAll('oauth_state_id').length !== 1
      || !received.searchParams.get('oauth_state_id')
      || [...received.searchParams.keys()].some(key => key !== 'oauth_state_id')) throw new Error();
    const binding = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null');
    if (!binding || typeof binding.connection_id !== 'string' || !binding.connection_id
      || typeof binding.link_token !== 'string' || !binding.link_token
      || !Number.isFinite(binding.expires_at) || binding.expires_at <= Date.now()
      || binding.redirect_uri !== received.origin + RETURN_PATH) throw new Error();
    return binding;
  } catch {
    clearBinding();
    throw new Error(t('finance.plaid_session_expired'));
  }
}

export function cancelPlaidReturn() { clearBinding(); }

export async function openPlaidLink(connection, { request = bankRequest, signal, binding = null, receivedRedirectUri } = {}) {
  signal?.throwIfAborted();
  if (!binding) {
    const token = await request(`/api/finance/connections/${encodeURIComponent(connection.id)}/plaid/link-token`, { method: 'POST' });
    signal?.throwIfAborted();
    const redirect = returnUrl(token.redirect_uri);
    const expiration = Date.parse(token.expiration);
    if (!token.link_token || typeof token.link_token !== 'string' || redirect.search
      || !Number.isFinite(expiration) || expiration <= Date.now()) throw new Error(t('finance.plaid_invalid_session'));
    binding = { connection_id: connection.id, link_token: token.link_token,
      expires_at: expiration, redirect_uri: redirect.href, update_mode: token.update_mode === true };
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(binding)); }
    catch { throw new Error(t('finance.plaid_storage_blocked')); }
  }
  let Plaid;
  try {
    Plaid = await plaidSdk();
    signal?.throwIfAborted();
  } catch (error) {
    if (!receivedRedirectUri || signal?.aborted) clearBinding(binding);
    throw error;
  }
  return new Promise((resolve, reject) => {
    let handler, settled = false, completing = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', abort);
      clearBinding(binding);
      handler?.destroy();
      if (error) reject(error); else resolve(result);
    };
    const abort = () => finish(new DOMException(t('finance.bank_dialog_closed'), 'AbortError'));
    signal?.addEventListener('abort', abort, { once: true });
    try {
      handler = Plaid.create({
        token: binding.link_token,
        ...(receivedRedirectUri ? { receivedRedirectUri } : {}),
        onSuccess: async publicToken => {
          if (settled || completing) return;
          completing = true;
          try {
            const path = binding.update_mode ? 'update-complete' : 'exchange';
            if (!binding.update_mode && (typeof publicToken !== 'string' || !publicToken)) {
              throw new Error(t('finance.plaid_no_token'));
            }
            const result = await request(`/api/finance/connections/${encodeURIComponent(binding.connection_id)}/plaid/${path}`, {
              method: 'POST', ...(binding.update_mode ? {} : { body: { public_token: publicToken } }),
            });
            if (result?.id !== binding.connection_id || result.status !== 'connected') {
              throw new Error(t('finance.plaid_unconfirmed'));
            }
            finish(null, { connection: result });
          } catch (error) { finish(error); }
        },
        onExit: error => {
          if (completing) return;
          finish(error ? new Error(error.display_message || error.error_message || t('finance.plaid_closed_error')) : null, { cancelled: true });
        },
      });
      handler.open();
    } catch (error) { finish(error); }
  });
}
