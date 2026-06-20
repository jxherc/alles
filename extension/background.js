// thin relay: the popup asks us to fetch matches from the localhost vault, using
// the unlock token the user pasted into the popup (kept in session storage only).
const API = 'http://secrets.localhost:8000';

async function matches(domain, token) {
  const r = await fetch(`${API}/api/vault/match?domain=${encodeURIComponent(domain)}`, {
    headers: { 'X-Vault-Token': token },
  });
  if (!r.ok) throw new Error('vault locked or unreachable');
  return r.json();
}

chrome.runtime.onMessage.addListener((msg, _s, reply) => {
  if (msg?.type !== 'alles-match') return;
  matches(msg.domain, msg.token).then(reply).catch(() => reply([]));
  return true; // async reply
});
