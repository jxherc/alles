const $ = id => document.getElementById(id);

chrome.storage.session.get('tok').then(d => { if (d.tok) $('tok').value = d.tok; });

$('go').addEventListener('click', async () => {
  const token = $('tok').value.trim();
  if (!token) { $('out').textContent = 'need a token'; return; }
  chrome.storage.session.set({ tok: token });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const domain = new URL(tab.url).hostname;
  const list = await chrome.runtime.sendMessage({ type: 'alles-match', domain, token });
  if (!list || !list.length) { $('out').textContent = 'no logins for ' + domain; return; }
  $('out').innerHTML = '';
  for (const cred of list) {
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<span>${cred.name}</span>`;
    const b = document.createElement('button');
    b.textContent = 'fill';
    b.onclick = () => chrome.tabs.sendMessage(tab.id, { type: 'alles-fill', cred });
    row.appendChild(b);
    $('out').appendChild(row);
  }
});
