// 5b - typed API client: named methods, query-string building, consistent error throwing, and a
// lightweight runtime response-shape validator. injectable fetch so it's node-testable.

function qs(params) {
  if (!params) return '';
  const parts = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.length ? '?' + parts.join('&') : '';
}

export function validate(data, shape) {
  const errors = [];
  const typeOf = (v) => (Array.isArray(v) ? 'array' : typeof v);
  for (const [field, spec] of Object.entries(shape || {})) {
    const optional = spec.startsWith('?');
    const want = optional ? spec.slice(1) : spec;
    if (!(field in (data || {})) || data[field] === undefined || data[field] === null) {
      if (!optional) errors.push(`missing field: ${field}`);
      continue;
    }
    const got = typeOf(data[field]);
    if (got !== want) errors.push(`field ${field}: expected ${want}, got ${got}`);
  }
  return { ok: errors.length === 0, errors };
}

export function createClient({ base = '', fetchFn } = {}) {
  const doFetch = fetchFn || (typeof fetch !== 'undefined' ? fetch : null);

  async function request(method, path, { params, body, shape, headers } = {}) {
    const url = base + path + qs(params);
    const opts = { method, headers: { ...(headers || {}) } };
    if (body !== undefined) {
      opts.headers['content-type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await doFetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}` + (data && data.detail ? `: ${data.detail}` : ''));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    if (shape) {
      const v = validate(data, shape);
      if (!v.ok) {
        const err = new Error(`response shape mismatch: ${v.errors.join('; ')}`);
        err.shapeErrors = v.errors;
        throw err;
      }
    }
    return data;
  }

  return {
    request,
    get: (path, opts) => request('GET', path, opts),
    post: (path, opts) => request('POST', path, opts),
    patch: (path, opts) => request('PATCH', path, opts),
    del: (path, opts) => request('DELETE', path, opts),
  };
}
