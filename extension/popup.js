const app = document.getElementById('app');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function escapeHtml(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function permissionPattern(origin) {
  const url = new URL(origin);
  // Chrome host-permission match patterns have no port component; one host
  // pattern covers every port on that exact hostname.
  return `${url.protocol}//${url.hostname}/*`;
}

function normalizeAllesOrigin(raw) {
  const url = new URL(String(raw || '').trim());
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('enter the Alles origin only, without a path');
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) throw new Error('use HTTPS, except for localhost');
  return url.origin;
}

async function stores() {
  const local = await chrome.storage.local.get(['allesOrigin', 'connectionId', 'deviceSecret']);
  const session = await chrome.storage.session.get(['sessionToken', 'pairing', 'unlockRequest']);
  return { ...local, ...session };
}

async function request(origin, path, body) {
  const response = await fetch(`${origin}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  let payload = {};
  try { payload = await response.json(); } catch { /* status fallback below */ }
  if (!response.ok) {
    const error = new Error(payload.message || payload.detail || 'Alles refused the request');
    error.status = response.status;
    error.code = payload.code || '';
    throw error;
  }
  return payload;
}

function isTerminalPairingError(error) {
  return error?.code === 'pairing_not_found'
    || (error?.status >= 400 && error.status < 500 && error.status !== 429);
}

function samePairing(left, right) {
  return Boolean(
    left && right
    && left.id === right.id
    && left.secret === right.secret
    && left.origin === right.origin
  );
}

function sameUnlockRequest(left, right) {
  return Boolean(left && right && left.id === right.id);
}

function isTerminalUnlockError(error) {
  return error?.code === 'unlock_request_not_found'
    || (error?.status >= 400 && error.status < 500 && error.status !== 429);
}

async function clearUnlockRequest(unlockRequest) {
  const pending = (await chrome.storage.session.get('unlockRequest')).unlockRequest;
  if (sameUnlockRequest(pending, unlockRequest)) {
    await chrome.storage.session.remove('unlockRequest');
  }
}

function renderSetup(message = '') {
  app.innerHTML = `
    <h1>connect this browser</h1>
    <p class="quiet">Enter the exact address of your Alles server. You will approve the browser inside Passwords.</p>
    <label>Alles origin<input id="origin" value="http://localhost:6769" spellcheck="false" autocomplete="off"></label>
    ${message ? `<p class="error">${escapeHtml(message)}</p>` : ''}
    <div class="actions"><span></span><button class="primary" id="pair">pair browser</button></div>`;
  document.getElementById('pair').addEventListener('click', beginPair);
}

async function beginPair() {
  const button = document.getElementById('pair');
  try {
    button.disabled = true;
    const origin = normalizeAllesOrigin(document.getElementById('origin').value);
    const granted = await chrome.permissions.request({ origins: [permissionPattern(origin)] });
    if (!granted) throw new Error('Alles host permission was not granted');
    const started = await request(origin, '/api/auth/browser/pair/start', { name: navigator.userAgentData?.brands?.[0]?.brand || 'Chromium browser' });
    const expiresIn = Number(started.expires_in);
    if (!Number.isFinite(expiresIn) || expiresIn <= 0) throw new Error('Alles returned an invalid pairing lifetime');
    const pairing = { origin, id: started.pairing_id, secret: started.pairing_secret, code: started.code, expiresAt: Date.now() + (expiresIn * 1000) };
    await chrome.storage.session.set({ pairing });
    renderPairing(pairing);
    pollPairing(pairing);
  } catch (error) {
    await chrome.storage.session.remove('pairing');
    renderSetup(error.message);
  }
}

function renderPairing(pairing) {
  app.innerHTML = `
    <h1>approve in Passwords</h1>
    <p class="quiet">Open Passwords → manage this vault → connected browsers. Match this code before approving.</p>
    <div class="code">${escapeHtml(pairing.code)}</div>
    <p class="quiet">Waiting for approval…</p>`;
}

async function pollPairing(pairing) {
  const expiresAt = Number(pairing.expiresAt);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await chrome.storage.session.remove('pairing');
    renderSetup('Pairing expired. Start a new pairing request.');
    return;
  }
  let credentialsDelivered = false;
  while (Date.now() < expiresAt) {
    try {
      const result = await request(pairing.origin, '/api/auth/browser/pair/poll', { pairing_id: pairing.id, pairing_secret: pairing.secret });
      if (result.status === 'approved') {
        const pendingBeforeWrite = (await chrome.storage.session.get('pairing')).pairing;
        if (!samePairing(pendingBeforeWrite, pairing)) return;
        await chrome.storage.local.set({ allesOrigin: pairing.origin, connectionId: result.connection_id, deviceSecret: result.device_secret });
        credentialsDelivered = true;
        const pendingAfterWrite = (await chrome.storage.session.get('pairing')).pairing;
        if (!samePairing(pendingAfterWrite, pairing)) {
          await request(pairing.origin, '/api/auth/browser/disconnect', {
            connection_id: result.connection_id,
            device_secret: result.device_secret,
          }).catch(() => {});
          await chrome.storage.local.remove(['allesOrigin', 'connectionId', 'deviceSecret']);
          return;
        }
        try {
          await request(pairing.origin, '/api/auth/browser/pair/ack', { pairing_id: pairing.id, pairing_secret: pairing.secret });
        } catch (error) {
          // A missing pairing means the acknowledgement itself succeeded but its
          // response was lost. Other failures keep the session request so reload
          // can retry and close the credential-delivery window.
          if (error?.code !== 'pairing_not_found' && !isTerminalPairingError(error)) {
            await sleep(Math.min(1500, Math.max(0, expiresAt - Date.now())));
            continue;
          }
          if (error?.code !== 'pairing_not_found') {
            await request(pairing.origin, '/api/auth/browser/disconnect', {
              connection_id: result.connection_id,
              device_secret: result.device_secret,
            }).catch(() => {});
            await chrome.storage.local.remove(['allesOrigin', 'connectionId', 'deviceSecret']);
            await chrome.storage.session.remove('pairing');
            renderSetup(error.message);
            return;
          }
        }
        await chrome.storage.session.remove('pairing');
        renderLocked();
        return;
      }
    } catch (error) {
      if (credentialsDelivered && error?.code === 'pairing_not_found') {
        await chrome.storage.session.remove('pairing');
        renderLocked();
        return;
      }
      if (isTerminalPairingError(error)) {
        await chrome.storage.session.remove('pairing');
        renderSetup(error.message);
        return;
      }
    }
    await sleep(Math.min(1500, Math.max(0, expiresAt - Date.now())));
  }
  await chrome.storage.session.remove('pairing');
  if (credentialsDelivered) {
    renderLocked();
    return;
  }
  renderSetup('Pairing expired. Start a new pairing request.');
}

function renderLocked(message = '') {
  app.innerHTML = `
    <h1>browser locked</h1>
    <p class="quiet">Request a short Passwords session, then approve it inside Alles. Closing or locking the browser clears local access.</p>
    ${message ? `<p class="error">${escapeHtml(message)}</p>` : ''}
    <div class="actions"><button id="disconnect">disconnect browser</button><button class="primary" id="unlock">request access</button></div>`;
  document.getElementById('disconnect').addEventListener('click', resetBrowser);
  document.getElementById('unlock').addEventListener('click', beginUnlock);
}

async function resetBrowser() {
  const state = await stores();
  let warning = '';
  try {
    if (state.allesOrigin && state.connectionId && state.deviceSecret) {
      await request(state.allesOrigin, '/api/auth/browser/disconnect', {
        connection_id: state.connectionId,
        device_secret: state.deviceSecret,
      });
    }
  } catch (error) {
    if (!/invalid|revoked|not connected/i.test(error.message)) {
      warning = 'Disconnected here. If that Alles server comes back, revoke this browser there too.';
    }
  }
  try {
    await chrome.storage.local.remove(['allesOrigin', 'connectionId', 'deviceSecret']);
    await chrome.storage.session.remove(['sessionToken', 'pairing', 'unlockRequest']);
    renderSetup(warning);
  } catch (error) {
    renderLocked(`Could not clear this browser: ${error.message}`);
  }
}

async function beginUnlock() {
  const state = await stores();
  try {
    const result = await request(state.allesOrigin, '/api/auth/browser/unlock/start', { connection_id: state.connectionId, device_secret: state.deviceSecret });
    const unlockRequest = { id: result.request_id, code: result.code };
    await chrome.storage.session.set({ unlockRequest });
    renderUnlock(unlockRequest);
    pollUnlock(unlockRequest);
  } catch (error) { renderLocked(error.message); }
}

function renderUnlock(unlockRequest) {
  app.innerHTML = `
    <h1>approve short access</h1>
    <p class="quiet">In connected browsers, approve the request with this code.</p>
    <div class="code">${escapeHtml(unlockRequest.code)}</div>
    <p class="quiet">Waiting for approval…</p>`;
}

async function pollUnlock(unlockRequest) {
  const state = await stores();
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const result = await request(state.allesOrigin, '/api/auth/browser/unlock/poll', { request_id: unlockRequest.id, connection_id: state.connectionId, device_secret: state.deviceSecret });
      if (result.status === 'approved') {
        const pendingBeforeWrite = (await chrome.storage.session.get('unlockRequest')).unlockRequest;
        if (!sameUnlockRequest(pendingBeforeWrite, unlockRequest)) return;
        await chrome.storage.session.set({ sessionToken: result.session_token });
        const pendingAfterWrite = (await chrome.storage.session.get('unlockRequest')).unlockRequest;
        if (!sameUnlockRequest(pendingAfterWrite, unlockRequest)) {
          await chrome.storage.session.remove('sessionToken');
          return;
        }
        await chrome.storage.session.remove('unlockRequest');
        await loadMatches();
        return;
      }
    } catch (error) {
      if (isTerminalUnlockError(error)) await clearUnlockRequest(unlockRequest);
      renderLocked(error.message);
      return;
    }
    await sleep(1500);
  }
  await clearUnlockRequest(unlockRequest);
  renderLocked('Access request expired.');
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) throw new Error('No active page is available.');
  return tab;
}

function pageBody(state, tab) {
  return {
    connection_id: state.connectionId,
    device_secret: state.deviceSecret,
    session_token: state.sessionToken,
    page_url: tab.url,
    top_url: tab.url,
    frame_url: tab.url,
  };
}

async function loadMatches() {
  const state = await stores();
  try {
    const tab = await activeTab();
    const url = new URL(tab.url);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Open an HTTP or HTTPS login page first.');
    const result = await request(state.allesOrigin, '/api/auth/browser/match', pageBody(state, tab));
    renderMatches(tab, result.matches || []);
  } catch (error) {
    if (/locked|revoked|invalid/i.test(error.message)) {
      await chrome.storage.session.remove('sessionToken');
      renderLocked(error.message);
    } else app.innerHTML = `<p class="error">${escapeHtml(error.message)}</p><div class="actions"><button id="lock">lock</button></div>`;
    document.getElementById('lock')?.addEventListener('click', lockBrowser);
  }
}

function renderMatches(tab, matches) {
  app.innerHTML = `
    <h1>choose one login</h1>
    <div class="site">${escapeHtml(new URL(tab.url).origin)}</div>
    ${matches.length ? `<div class="credential-list">${matches.map(item => `<button class="credential" data-entry="${escapeHtml(item.id)}"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.username || 'no username')}</small></button>`).join('')}</div>` : '<p class="quiet">No exact-site login matches this page.</p>'}
    <div class="actions"><button id="lock">lock</button><button id="refresh">refresh</button></div>`;
  document.querySelectorAll('[data-entry]').forEach(button => button.addEventListener('click', () => fillSelected(tab, button.dataset.entry, button)));
  document.getElementById('lock').addEventListener('click', lockBrowser);
  document.getElementById('refresh').addEventListener('click', loadMatches);
}

async function fillSelected(tab, entryId, button) {
  const state = await stores();
  button.disabled = true;
  try {
    const credential = await request(state.allesOrigin, '/api/auth/browser/release', { ...pageBody(state, tab), entry_id: entryId });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [0] },
      func: fillLogin,
      args: [credential.username, credential.password, new URL(tab.url).origin],
    });
    if (!result?.ok) throw new Error(result?.error || 'This page has no safe single-password login form.');
    window.close();
  } catch (error) {
    button.disabled = false;
    const note = document.createElement('p'); note.className = 'error'; note.textContent = error.message;
    button.after(note);
  }
}

function fillLogin(username, password, expectedOrigin) {
  if (location.origin !== expectedOrigin) return { ok: false, error: 'The page origin changed before fill.' };
  const visible = input => !input.disabled && input.type !== 'hidden' && input.getClientRects().length > 0;
  const passwordInputs = [...document.querySelectorAll('input[type="password"]')].filter(visible);
  if (passwordInputs.length !== 1) return { ok: false, error: 'Alles refuses forms with zero or multiple password fields.' };
  const passwordInput = passwordInputs[0];
  const form = passwordInput.form || passwordInput.closest('form') || document;
  const formPasswords = [...form.querySelectorAll('input[type="password"]')].filter(visible);
  if (formPasswords.length !== 1 || /new-password/i.test(passwordInput.autocomplete || '')) return { ok: false, error: 'Alles refuses new-password and multi-password forms.' };
  const candidates = [...form.querySelectorAll('input')].filter(input => visible(input) && input !== passwordInput && ['text', 'email', ''].includes(input.type));
  const usernameInput = candidates.find(input => /^(username|email)$/i.test(input.autocomplete || '')) || candidates.find(input => input.type === 'email') || candidates[0];
  const set = (input, value) => {
    if (!input || !value) return;
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    descriptor?.set.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  set(usernameInput, username); set(passwordInput, password); passwordInput.focus();
  return { ok: true };
}

async function lockBrowser() {
  const state = await stores();
  await chrome.storage.session.remove(['sessionToken', 'unlockRequest']);
  if (state.allesOrigin && state.connectionId && state.deviceSecret) {
    request(state.allesOrigin, '/api/auth/browser/lock', { connection_id: state.connectionId, device_secret: state.deviceSecret }).catch(() => {});
  }
  renderLocked();
}

async function start() {
  const state = await stores();
  if (state.pairing) { renderPairing(state.pairing); pollPairing(state.pairing); return; }
  if (!state.allesOrigin || !state.connectionId || !state.deviceSecret) { renderSetup(); return; }
  if (state.unlockRequest) { renderUnlock(state.unlockRequest); pollUnlock(state.unlockRequest); return; }
  if (!state.sessionToken) { renderLocked(); return; }
  await loadMatches();
}

start();
