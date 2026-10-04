import { requestId } from './request_id.js';

// Ordinary saves are serialized; page exit can supersede an unconfirmed write.
export function readingPlace(item, write) {
  let value = item.position || 0;
  let saved = value;
  let timer = null;
  let pending = null;
  let error = '';
  let blocked = false;
  let listener = () => {};
  const owner = requestId();
  const base = item.position_revision || '';
  let sequence = 0;
  let request = null;
  const notify = () => listener({ value, pending: !!pending, error, blocked, unsaved: value !== saved });
  const schedule = () => { clearTimeout(timer); timer = setTimeout(() => void flush(), 600); };

  async function flush(leaving = false) {
    clearTimeout(timer);
    if (pending && (!leaving || request.position === value)) return pending;
    if (blocked) return false;
    if (!pending && value === saved && !error) return true;
    // Keep an uncertain request's identity when retrying exactly the same place.
    const patch = request?.position === value ? request : {
      position: value, content_hash: item.content_hash,
      position_revision: `${owner}:${++sequence}`, position_base: base,
    };
    request = patch;
    error = '';
    pending = (async () => {
      try {
        await write(patch);
        if (request === patch) {
          saved = patch.position;
          item.position = saved;
          item.position_revision = patch.position_revision;
        }
        return true;
      } catch (failure) {
        if (request === patch) {
          blocked = failure.status === 409 || failure.status === 404;
          error = blocked ? 'saved text changed, reading place changed or article was removed; reopen the article' : 'could not confirm reading place; retry';
        }
        return false;
      } finally {
        if (request === patch) {
          pending = null;
          if (!error && value !== saved) schedule();
          notify();
        }
      }
    })();
    notify();
    return pending;
  }

  return {
    get value() { return value; },
    get unsaved() { return value !== saved || !!error; },
    get pending() { return !!pending; },
    get blocked() { return blocked; },
    set(position) {
      const next = Math.round(Math.max(0, Math.min(1, position)) * 1e6) / 1e6;
      if (next === value) return;
      value = next;
      if (!blocked && !error) schedule();
      notify();
    },
    listen(callback) { listener = callback; notify(); },
    flush,
    async drain() {
      do { if (!(await flush())) return false; } while (value !== saved);
      return true;
    },
  };
}
