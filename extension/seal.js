// the extension's half of the sealed channel; the server half is seal() in
// services/browser_passwords.py. at pairing the extension makes an ecdh p-256 key pair whose
// private half can't be exported, keeps it in indexeddb (chrome.storage only holds json), and
// sends only the public half. every fill comes back as a box only that private key opens.

const SEAL_INFO = new TextEncoder().encode('alles browser fill v1');
const CURVE = { name: 'ECDH', namedCurve: 'P-256' };

function sealDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('alles-seal', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('keys');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function sealStore(mode, run) {
  const db = await sealDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('keys', mode);
      const request = run(tx.objectStore('keys'));
      tx.oncomplete = () => resolve(request?.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

const sealGet = name => sealStore('readonly', store => store.get(name));
const sealPut = (name, value) => sealStore('readwrite', store => store.put(value, name));
const sealDelete = name => sealStore('readwrite', store => store.delete(name));

function b64u(bytes) {
  let text = '';
  for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function unb64u(text) {
  const plain = String(text || '').replace(/-/g, '+').replace(/_/g, '/');
  const padded = plain + '='.repeat((4 - (plain.length % 4)) % 4);
  return Uint8Array.from(atob(padded), char => char.charCodeAt(0));
}

// a fresh key pair for one pairing request; it becomes the browser's key only once approved
async function newPairingKey() {
  const pair = await crypto.subtle.generateKey(CURVE, false, ['deriveBits']);
  return { pair, publicKey: b64u(await crypto.subtle.exportKey('raw', pair.publicKey)) };
}

async function holdPairingKey(pairingId, pair) {
  await sealPut(`pairing:${pairingId}`, pair);
}

async function keepPairingKey(pairingId) {
  const pair = await sealGet(`pairing:${pairingId}`);
  if (!pair) throw new Error('this browser lost its key. connect it again');
  await sealPut('current', pair);
  await sealDelete(`pairing:${pairingId}`);
}

async function forgetBrowserKey() {
  await sealStore('readwrite', store => store.clear());
}

// what the server binds each box to: this browser's connection and the page's exact origin
function fillAad(connectionId, pageUrl) {
  const url = new URL(pageUrl);
  const scheme = url.protocol.slice(0, -1);
  const host = url.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '').toLowerCase();
  const port = url.port ? Number(url.port) : (scheme === 'https' ? 443 : 80);
  return `alles-fill|${connectionId}|${scheme}://${host}:${port}`;
}

async function openSealed(sealed, aad) {
  const pair = await sealGet('current');
  if (!pair) throw Object.assign(new Error('connect this browser again'), { code: 'browser_needs_pairing' });
  if (!sealed || sealed.v !== 1) throw new Error('alles sent something this extension can’t open. update it');
  const epkRaw = unb64u(sealed.epk);
  const epk = await crypto.subtle.importKey('raw', epkRaw, CURVE, false, []);
  const bits = await crypto.subtle.deriveBits({ name: 'ECDH', public: epk }, pair.privateKey, 256);
  const hkdf = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'HKDF', hash: 'SHA-256', salt: epkRaw, info: SEAL_INFO },
    hkdf,
    { name: 'AES-GCM', length: 256 },
    false,
    ['decrypt'],
  );
  let plain;
  try {
    plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: unb64u(sealed.iv), additionalData: new TextEncoder().encode(aad) },
      key,
      unb64u(sealed.ct),
    );
  } catch {
    throw new Error('the page changed while alles answered. try again');
  }
  return JSON.parse(new TextDecoder().decode(plain));
}
