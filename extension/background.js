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
