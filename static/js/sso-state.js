// Pure URL helpers for the cross-subdomain login relay. Keep the full target
// intact so a login bounce does not lose app state carried in its path/query/hash.

function _baseDomain(value) {
  const base = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (!base || base.length > 253 || base.endsWith('.') || base.includes('..')) return null;
  if (base === 'localhost') return base;
  if (!base.includes('.') || /^\d{1,3}(?:\.\d{1,3}){3}$/.test(base)) return null;
  const labels = base.split('.');
  if (labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
  return base;
}

function _targetText(value) {
  if (value instanceof URL) return value.href;
  if (typeof value !== 'string' || !value || value !== value.trim()) return null;

  let text = value;
  if (!/^https?:\/\//i.test(text)) {
    try { text = decodeURIComponent(text); }
    catch { return null; }
  }
  if (!/^https?:\/\//i.test(text)) return null;
  if (/[\u0000-\u001f\u007f\\]/.test(text) || /%(?![0-9a-f]{2})/i.test(text)) return null;
  return text;
}

function _url(value) {
  const text = _targetText(value);
  if (!text) return null;
  try { return new URL(text); }
  catch { return null; }
}

function _allowedSet(values) {
  if (typeof values === 'string') values = [values];
  if (!values || typeof values[Symbol.iterator] !== 'function') return null;
  const allowed = new Set();
  for (const value of values) {
    const sub = typeof value === 'string' ? value.toLowerCase() : '';
    if (/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(sub)) allowed.add(sub);
  }
  return allowed.size ? allowed : null;
}

function _subdomain(hostname, base) {
  if (hostname === base || !hostname.endsWith('.' + base)) return null;
  const sub = hostname.slice(0, -('.' + base).length);
  return sub && !sub.includes('.') ? sub : null;
}

/** Build the apex relay URL while carrying the complete current app URL. */
export function buildApexBrokerUrl(currentTarget, baseDomain) {
  const target = _url(currentTarget);
  const base = _baseDomain(baseDomain);
  if (!target || !base || !['http:', 'https:'].includes(target.protocol) ||
      target.username || target.password || !_subdomain(target.hostname, base)) {
    throw new TypeError('invalid sso source url');
  }

  const broker = new URL(target.origin);
  broker.hostname = base;
  broker.pathname = '/';
  broker.search = '';
  broker.hash = '';
  broker.searchParams.set('_sso', target.href);
  return broker.href;
}

/**
 * Accept an encoded or full target only when it is an approved direct child of
 * the configured apex. Returns a normalized full URL, or null when rejected.
 */
export function normalizeSsoTarget(target, {
  protocol,
  port = '',
  baseDomain,
  allowedSubdomains,
} = {}) {
  const url = _url(target);
  const base = _baseDomain(baseDomain);
  const allowed = _allowedSet(allowedSubdomains);
  const expectedProtocol = typeof protocol === 'string'
    ? protocol.toLowerCase().replace(/:?$/, ':')
    : '';
  const expectedPort = String(port ?? '');

  if (!url || !base || !allowed || !['http:', 'https:'].includes(expectedProtocol)) return null;
  if (!/^$|^\d{1,5}$/.test(expectedPort)) return null;
  if (url.protocol !== expectedProtocol || url.port !== expectedPort) return null;
  if (url.username || url.password) return null;

  const sub = _subdomain(url.hostname, base);
  if (!sub || !allowed.has(sub)) return null;
  return url.href;
}

/** Add the one-time login code without losing any non-SSO app state. */
export function addSsoAuthCode(target, code) {
  const url = _url(target);
  if (!url || typeof code !== 'string' || !code) throw new TypeError('invalid sso auth target');
  url.searchParams.delete('_sso');
  url.searchParams.set('_auth', code);
  return url.href;
}

/** Remove only the requested query names and leave every other URL part alone. */
export function stripTransientParams(target, names) {
  const url = _url(target);
  if (!url) throw new TypeError('invalid url');
  const selected = typeof names === 'string' ? [names] : names;
  if (!selected || typeof selected[Symbol.iterator] !== 'function') {
    throw new TypeError('invalid transient parameter names');
  }
  for (const name of selected) {
    if (typeof name === 'string' && name) url.searchParams.delete(name);
  }
  return url.href;
}
