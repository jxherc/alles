// public vault share page (/sv/<token>). the key stays in the url fragment; the server only
// ever has the encrypted blob. a file, not inline, so the page keeps the app's script-src
(function () {
  const token = document.body.dataset.token;
  function b64ToBytes(b64) { const s = atob(b64.replace(/-/g, '+').replace(/_/g, '/')); const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }
  async function go() {
    const keyB64 = location.hash.slice(1);
    if (!keyB64) { document.getElementById('err').hidden = false; return; }
    try {
      const d = await fetch(`/sv/${encodeURIComponent(token)}/data`).then(r => r.json());
      const blob = b64ToBytes(d.blob);
      const iv = blob.slice(0, 12), ct = blob.slice(12);
      const key = await crypto.subtle.importKey('raw', b64ToBytes(keyB64), 'AES-GCM', false, ['decrypt']);
      const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
      const obj = JSON.parse(new TextDecoder().decode(pt));
      document.getElementById('title').firstChild.textContent = (obj.name || 'shared item') + ' ';
      const rows = Object.entries(obj.fields || {}).filter(([k, v]) => v).map(([k, v]) =>
        `<div class="row"><span class="k">${String(k).replace(/</g, '&lt;')}</span><span class="v">${String(v).replace(/</g, '&lt;')}</span></div>`).join('');
      document.getElementById('body').innerHTML = rows || '<div class="k">(empty)</div>';
    } catch (e) { document.getElementById('err').hidden = false; }
  }
  go();
})();
