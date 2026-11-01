async function lockStoredBrowser() {
  const local = await chrome.storage.local.get(['allesOrigin', 'connectionId', 'deviceSecret']);
  await chrome.storage.session.remove(['sessionToken', 'unlockRequest', 'pairing']);
  if (!local.allesOrigin || !local.connectionId || !local.deviceSecret) return;
  try {
    await fetch(`${local.allesOrigin}/api/auth/browser/lock`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ connection_id: local.connectionId, device_secret: local.deviceSecret }),
      cache: 'no-store',
    });
  } catch { /* local session was already cleared; server expiry is the fallback */ }
}

chrome.runtime.onInstalled.addListener(() => chrome.idle.setDetectionInterval(60));
chrome.idle.onStateChanged.addListener(state => {
  if (state === 'idle' || state === 'locked') lockStoredBrowser();
});

// the alles this extension belongs to: the one it paired with, else the one it was downloaded from
async function allesOrigin() {
  const { allesOrigin: paired } = await chrome.storage.local.get('allesOrigin');
  if (paired) return paired;
  try {
    const config = await (await fetch(chrome.runtime.getURL('config.json'))).json();
    return typeof config.origin === 'string' ? config.origin : '';
  } catch { return ''; }
}

// "al <words>" in the address bar searches andromeda; the downloaded copy can also make it the
// browser's default search (chrome_settings_overrides, added by the download)
async function searchAndromeda(text, disposition = 'currentTab') {
  const origin = await allesOrigin();
  const query = String(text || '').trim();
  const target = origin
    ? `${origin}/?app=andromeda${query ? `&q=${encodeURIComponent(query)}` : ''}`
    : chrome.runtime.getURL('popup.html');
  if (disposition === 'currentTab') {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) return chrome.tabs.update(tab.id, { url: target });
  }
  return chrome.tabs.create({ url: target, active: disposition !== 'newBackgroundTab' });
}

chrome.omnibox.setDefaultSuggestion({ description: 'search andromeda for %s' });
chrome.omnibox.onInputEntered.addListener((text, disposition) => { searchAndromeda(text, disposition); });
