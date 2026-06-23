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
  // walk in order; for each resource url keep only what matters. a DELETE wipes earlier writes to the
  // same url; a later write to a url supersedes an earlier write (last-write-wins). distinct urls keep
  // their first-seen order.
  const byUrl = new Map(); // url -> index in `out`
  const out = [];
  for (const op of queue || []) {
    const url = op.url;
    const isDelete = (op.method || '').toUpperCase() === 'DELETE';
    if (byUrl.has(url)) {
      const idx = byUrl.get(url);
      out[idx] = op; // supersede (covers write->write and write->delete)
    } else {
      byUrl.set(url, out.length);
      out.push(op);
    }
    // a delete leaves the slot as the delete; nothing else needed
    void isDelete;
  }
  return out.filter(Boolean);
}

export function summarize(queue) {
  return { count: (queue || []).length };
}
