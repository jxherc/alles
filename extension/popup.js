// seal.js (key pair, sealed boxes) and fill.js (fillPage) load before this file.
const app = document.getElementById('app');
const where = document.getElementById('where');
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
  let text = String(raw || '').trim();
  if (text && !/^[a-z]+:\/\//i.test(text)) text = `https://${text}`;
  const url = new URL(text);
  if (url.username || url.password || url.search || url.hash || !['/', ''].includes(url.pathname)) throw new Error('just the address, like alles.example.ts.net');
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) throw new Error('alles needs https here (plain http works only on localhost)');
  return url.origin;
}

// the downloaded copy knows its alles (config.json, written by the download); a copy loaded
// straight from the repo asks once
async function bundledOrigin() {
  try {
    const config = await (await fetch(chrome.runtime.getURL('config.json'))).json();
    return normalizeAllesOrigin(config.origin);
  } catch { return ''; }
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
    const error = new Error(payload.message || payload.detail || 'alles said no');
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

async function ownsSessionToken(sessionToken) {
  if (!sessionToken) return false;
  const current = (await chrome.storage.session.get('sessionToken')).sessionToken;
  return current === sessionToken;
}

function setBusy(button, busy, label = '') {
  if (!button) return false;
  if (busy && button.getAttribute('aria-busy') === 'true') return false;
  if (busy) {
    button.dataset.restingLabel = button.textContent;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    if (label) button.textContent = label;
  } else {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (button.dataset.restingLabel) button.textContent = button.dataset.restingLabel;
    delete button.dataset.restingLabel;
  }
  return true;
}

function showHost(origin) {
  try { where.textContent = origin ? new URL(origin).host : ''; } catch { where.textContent = ''; }
}

// the place in alles where the owner approves: passwords, then settings, connected browsers.
// an alles tab that's already open is reused. the popup closes when the tab takes focus; opening
// it again picks up where it was (the request waits in session storage)
async function openAlles(origin) {
  const [open] = await chrome.tabs.query({ url: `${origin}/*` }).catch(() => []);
  if (open?.id) {
    await chrome.tabs.update(open.id, { active: true });
    if (open.windowId) await chrome.windows.update(open.windowId, { focused: true });
    return;
  }
  await chrome.tabs.create({ url: `${origin}/?app=vault` });
}

async function renderSetup(message = '') {
  // a failed try keeps what was typed
  const typed = document.getElementById('origin')?.value || '';
  const known = await bundledOrigin();
  showHost(known);
  app.innerHTML = `
    <h1>connect to alles</h1>
    ${known
      ? `<p class="quiet">you’ll approve this browser in your alles, signed in as usual.</p>`
      : `<label>alles address<input id="origin" value="${escapeHtml(typed)}" placeholder="alles.example.ts.net" spellcheck="false" autocomplete="url" inputmode="url"></label>`}
    ${message ? `<p class="error" role="alert">${escapeHtml(message)}</p>` : ''}
    <div class="actions"><button class="primary" id="pair">connect</button></div>`;
  const pair = document.getElementById('pair');
  pair.addEventListener('click', () => beginPair(pair, known));
  document.getElementById('origin')?.addEventListener('keydown', event => { if (event.key === 'Enter') beginPair(pair, known); });
  document.getElementById('origin')?.focus();
}

async function beginPair(button, known) {
  if (!setBusy(button, true, 'connecting…')) return;
  try {
    const origin = known || normalizeAllesOrigin(document.getElementById('origin')?.value);
    const granted = await chrome.permissions.request({ origins: [permissionPattern(origin)] });
    if (!granted) throw new Error('chrome needs your ok to reach alles');
    const key = await newPairingKey();
    const started = await request(origin, '/api/auth/browser/pair/start', {
      name: navigator.userAgentData?.brands?.find(item => !/not.a.brand/i.test(item.brand))?.brand || 'Chromium',
      public_key: key.publicKey,
    });
    await holdPairingKey(started.pairing_id, key.pair);
    const expiresIn = Number(started.expires_in);
    if (!Number.isFinite(expiresIn) || expiresIn <= 0) throw new Error('alles sent a pairing that already ended');
    const pairing = { origin, id: started.pairing_id, secret: started.pairing_secret, code: started.code, expiresAt: Date.now() + (expiresIn * 1000) };
    await chrome.storage.session.set({ pairing });
    renderPairing(pairing);
    openAlles(origin);
    pollPairing(pairing);
  } catch (error) {
    await chrome.storage.session.remove('pairing');
    renderSetup(error.message);
  }
}

function renderPairing(pairing) {
  showHost(pairing.origin);
  app.innerHTML = `
    <h1>approve in alles</h1>
    <p class="quiet">passwords › settings › connected browsers. approve it if you see this code:</p>
    <div class="code">${escapeHtml(pairing.code)}</div>
    <p class="quiet">waiting…</p>
    <div class="actions"><button id="open">open alles</button><button class="quiet-button push" id="cancel">cancel</button></div>`;
  document.getElementById('open').addEventListener('click', () => openAlles(pairing.origin));
  document.getElementById('cancel').addEventListener('click', async () => {
    await chrome.storage.session.remove('pairing');
    renderSetup();
  });
}

async function pollPairing(pairing) {
  const expiresAt = Number(pairing.expiresAt);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await chrome.storage.session.remove('pairing');
    renderSetup('that code ran out. connect again');
    return;
  }
  let credentialsDelivered = false;
  while (Date.now() < expiresAt) {
    try {
      const result = await request(pairing.origin, '/api/auth/browser/pair/poll', { pairing_id: pairing.id, pairing_secret: pairing.secret });
      if (result.status === 'approved') {
        const pendingBeforeWrite = (await chrome.storage.session.get('pairing')).pairing;
        // Inactivity clears session storage, but an explicitly approved pairing
        // only installs a locked browser identity. Let this live popup finish its
        // exact request while still rejecting a newer replacement pairing.
        const pairingWasClearedBeforeDelivery = !pendingBeforeWrite;
        if (pendingBeforeWrite && !samePairing(pendingBeforeWrite, pairing)) return;
        await keepPairingKey(pairing.id);
        await chrome.storage.local.set({ allesOrigin: pairing.origin, connectionId: result.connection_id, deviceSecret: result.device_secret });
        credentialsDelivered = true;
        const pendingAfterWrite = (await chrome.storage.session.get('pairing')).pairing;
        const pairingStayedCleared = pairingWasClearedBeforeDelivery && !pendingAfterWrite;
        if (!samePairing(pendingAfterWrite, pairing) && !pairingStayedCleared) {
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
  renderSetup('that code ran out. connect again');
}

async function renderLocked(message = '') {
  const state = await stores();
  showHost(state.allesOrigin);
  app.innerHTML = `
    <h1>locked</h1>
    <p class="quiet">unlock to fill from your vault. it locks again after 5 minutes or when the computer sleeps.</p>
    ${message ? `<p class="error" role="alert">${escapeHtml(message)}</p>` : ''}
    <div class="actions"><button class="primary" id="unlock">unlock</button><button class="quiet-button push" id="disconnect">disconnect</button></div>`;
  const disconnect = document.getElementById('disconnect');
  const unlock = document.getElementById('unlock');
  disconnect.addEventListener('click', () => resetBrowser(disconnect));
  unlock.addEventListener('click', () => beginUnlock(unlock));
}

async function resetBrowser(button = null, message = '') {
  if (button && !setBusy(button, true, 'disconnecting…')) return;
  let warning = message;
  try {
    try {
      const state = await stores();
      if (state.allesOrigin && state.connectionId && state.deviceSecret) {
        await request(state.allesOrigin, '/api/auth/browser/disconnect', {
          connection_id: state.connectionId,
          device_secret: state.deviceSecret,
        });
      }
    } catch (error) {
      if (!warning && !/invalid|revoked|not connected/i.test(error.message)) {
        warning = 'disconnected here. if that alles comes back, remove this browser there too';
      }
    }
    await chrome.storage.local.remove(['allesOrigin', 'connectionId', 'deviceSecret']);
    await chrome.storage.session.remove(['sessionToken', 'pairing', 'unlockRequest']);
    await forgetBrowserKey();
    renderSetup(warning);
  } catch (error) {
    renderLocked(`couldn’t clear this browser: ${error.message}`);
  }
}

async function beginUnlock(button = null) {
  if (button && !setBusy(button, true, 'asking…')) return;
  try {
    const state = await stores();
    const result = await request(state.allesOrigin, '/api/auth/browser/unlock/start', { connection_id: state.connectionId, device_secret: state.deviceSecret });
    const unlockRequest = { id: result.request_id, code: result.code };
    await chrome.storage.session.set({ unlockRequest });
    renderUnlock(unlockRequest, state.allesOrigin);
    openAlles(state.allesOrigin);
    pollUnlock(unlockRequest);
  } catch (error) { renderLocked(error.message); }
}

function renderUnlock(unlockRequest, origin) {
  app.innerHTML = `
    <h1>approve in alles</h1>
    <p class="quiet">passwords › settings › connected browsers. approve it if you see this code:</p>
    <div class="code">${escapeHtml(unlockRequest.code)}</div>
    <p class="quiet">waiting…</p>
    <div class="actions"><button id="open">open alles</button></div>`;
  document.getElementById('open').addEventListener('click', () => openAlles(origin));
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
  renderLocked('nobody approved it in time');
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) throw new Error('no page is open in this tab');
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
  let sessionToken = '';
  try {
    const state = await stores();
    sessionToken = state.sessionToken;
    showHost(state.allesOrigin);
    const tab = await activeTab();
    const url = new URL(tab.url);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('open a website first');
    const result = await request(state.allesOrigin, '/api/auth/browser/match', pageBody(state, tab));
    const found = await openSealed(result.sealed, fillAad(state.connectionId, tab.url));
    if (!await ownsSessionToken(sessionToken)) return;
    renderMatches(tab, found);
  } catch (error) {
    if (sessionToken && !await ownsSessionToken(sessionToken)) return;
    if (error.code === 'browser_needs_pairing') { await resetBrowser(null, 'connect this browser again, so fills stay encrypted'); return; }
    if (/locked|revoked|invalid/i.test(error.message) || error.code === 'browser_locked') {
      await chrome.storage.session.remove('sessionToken');
      renderLocked(error.message);
      return;
    }
    app.innerHTML = `<p class="error" role="alert">${escapeHtml(error.message)}</p><div class="actions"><button id="lock">lock</button></div>`;
    const lock = document.getElementById('lock');
    lock.addEventListener('click', () => lockBrowser(lock));
  }
}

const GROUPS = [
  { key: 'logins', title: 'logins for this site', empty: 'no login saved for this site', line: item => item.username || 'no username' },
  { key: 'cards', title: 'cards', line: item => `•••• ${item.last4}${item.expiry ? ` · ${item.expiry}` : ''}` },
  { key: 'addresses', title: 'addresses', line: item => item.line || '' },
];

function renderMatches(tab, found) {
  const host = new URL(tab.url).host;
  const groups = GROUPS.map(group => {
    const items = Array.isArray(found[group.key]) ? found[group.key] : [];
    if (!items.length && !group.empty) return '';
    return `
      <section class="group" aria-label="${escapeHtml(group.title)}">
        <h2>${escapeHtml(group.title)}</h2>
        ${items.length
          ? `<div class="list">${items.map(item => `<button class="item" data-entry="${escapeHtml(item.id)}" data-kind="${group.key}"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(group.line(item))}</small></button>`).join('')}</div>`
          : `<p class="quiet">${escapeHtml(group.empty)}</p>`}
      </section>`;
  }).join('');
  app.innerHTML = `
    <h1>${escapeHtml(host)}</h1>
    ${groups}
    <div class="actions"><button id="lock">lock</button></div>`;
  document.querySelectorAll('[data-entry]').forEach(button => button.addEventListener('click', () => fillSelected(tab, button.dataset.entry, button)));
  const lock = document.getElementById('lock');
  lock.addEventListener('click', () => lockBrowser(lock));
}

async function fillSelected(tab, entryId, button) {
  if (!setBusy(button, true)) return;
  button.parentElement.querySelector('.error')?.remove();
  try {
    const state = await stores();
    const result = await request(state.allesOrigin, '/api/auth/browser/release', { ...pageBody(state, tab), entry_id: entryId });
    const fill = await openSealed(result.sealed, fillAad(state.connectionId, tab.url));
    if (!await ownsSessionToken(state.sessionToken)) return;
    const [{ result: done }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [0] },
      func: fillPage,
      args: [fill.kind, fill, new URL(tab.url).origin],
    });
    if (!done?.ok) throw new Error(done?.error || 'nothing on this page to fill');
    window.close();
  } catch (error) {
    setBusy(button, false);
    const note = document.createElement('p');
    note.className = 'error';
    note.setAttribute('role', 'alert');
    note.textContent = error.message;
    button.after(note);
  }
}

async function lockBrowser(button = null) {
  if (button && !setBusy(button, true, 'locking…')) return;
  try {
    const state = await stores();
    await chrome.storage.session.remove(['sessionToken', 'unlockRequest']);
    if (state.allesOrigin && state.connectionId && state.deviceSecret) {
      await request(state.allesOrigin, '/api/auth/browser/lock', { connection_id: state.connectionId, device_secret: state.deviceSecret });
    }
    renderLocked();
  } catch (error) {
    if (button) setBusy(button, false);
    const note = document.createElement('p');
    note.className = 'error';
    note.textContent = `couldn’t lock this browser: ${error.message}`;
    app.prepend(note);
  }
}

async function start() {
  const state = await stores();
  if (state.pairing) { renderPairing(state.pairing); pollPairing(state.pairing); return; }
  if (!state.allesOrigin || !state.connectionId || !state.deviceSecret) { renderSetup(); return; }
  if (state.unlockRequest) { showHost(state.allesOrigin); renderUnlock(state.unlockRequest, state.allesOrigin); pollUnlock(state.unlockRequest); return; }
  if (!state.sessionToken) { renderLocked(); return; }
  await loadMatches();
}

start();
