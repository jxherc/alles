// fills a login form when the popup hands us a {username, password} match.
// kept dumb on purpose — the popup does the vault talking, this just types.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type !== 'alles-fill') return;
  const cred = msg.cred || {};
  const userSel = 'input[type=email], input[name*=user i], input[id*=user i], input[autocomplete=username]';
  const passSel = 'input[type=password]';
  const u = document.querySelector(userSel);
  const p = document.querySelector(passSel);
  let filled = 0;
  if (u && cred.username) { u.value = cred.username; u.dispatchEvent(new Event('input', { bubbles: true })); filled++; }
  if (p && cred.password) { p.value = cred.password; p.dispatchEvent(new Event('input', { bubbles: true })); filled++; }
  reply({ filled });
  return true;
});
