// mail and calendar servers from an email address (POST /api/setup/detect, services/setup_detect.py).
// one read per address: typing the same address again reuses the answer
const _seen = new Map();

export async function detectSetup(email, doFetch = (...args) => globalThis.fetch(...args)) {
  const address = String(email || '').trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(address)) return null;
  if (_seen.has(address)) return _seen.get(address);
  const read = (async () => {
    try {
      const response = await doFetch('/api/setup/detect', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email: address }),
      });
      return response.ok ? await response.json() : null;
    } catch { return null; }
  })();
  _seen.set(address, read);
  const found = await read;
  if (!found) _seen.delete(address);
  return found;
}
