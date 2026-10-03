// One writer per article keeps delayed acknowledgments behind the latest scroll.
export function readingPlace(item, write) {
  let value = item.position || 0;
  let saved = value;
  let timer = null;
  let pending = null;
  let error = '';
  let blocked = false;
  let listener = () => {};
  const notify = () => listener({ value, pending: !!pending, error, blocked, unsaved: value !== saved });
  const schedule = () => { clearTimeout(timer); timer = setTimeout(() => void flush(), 600); };

  async function flush() {
    clearTimeout(timer);
    if (pending) return pending;
    if (blocked) return false;
    if (value === saved && !error) return true;
    const position = value;
    error = '';
    pending = (async () => {
      try {
        await write({ position, content_hash: item.content_hash });
        saved = position;
        item.position = position;
        return true;
      } catch (failure) {
        blocked = failure.status === 409 || failure.status === 404;
        error = blocked ? 'saved text changed or was removed; reopen the article' : 'could not confirm reading place; retry';
        return false;
      } finally {
        pending = null;
        if (!error && value !== saved) schedule();
        notify();
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
