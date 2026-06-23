// 5d - offline outbox queue logic: which requests to stash when offline, and how to collapse the
// queue so a reconnect flush replays the minimal, correct set. pure ESM, node-testable; the service
// worker can use the same decisions.

const _MUT = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
// streaming / long-running endpoints that must NOT be replayed from an offline queue
const _SKIP = ['/api/agent', '/api/chat/stream', '/api/research', '/api/voice'];

export function isQueueable(method, url) {
  const m = (method || '').toUpperCase();
  if (!_MUT.has(m)) return false;
  if (!(url || '').startsWith('/api')) return false;
  return !_SKIP.some((s) => url.startsWith(s));
}

export function dedupe(queue) {
  // collapse only IDEMPOTENT ops on the same resource url: a later PUT/PATCH/DELETE supersedes an
  // earlier write to that url (last-write-wins). POST is a CREATE - two POSTs to the same collection
  // are two distinct new resources, so they never collapse. distinct urls keep first-seen order.
  const byUrl = new Map(); // url -> index in `out` (only tracked for idempotent ops)
  const out = [];
  for (const op of queue || []) {
    const url = op.url;
    const method = (op.method || '').toUpperCase();
    const idempotent = method === 'PUT' || method === 'PATCH' || method === 'DELETE';
    if (idempotent && byUrl.has(url)) {
      out[byUrl.get(url)] = op; // supersede the earlier write to this resource
    } else {
      if (idempotent) byUrl.set(url, out.length);
      out.push(op);
    }
  }
  return out.filter(Boolean);
}

export function summarize(queue) {
  return { count: (queue || []).length };
}
