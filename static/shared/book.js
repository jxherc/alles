// public booking page (/book/<token>). a file, not inline, so the page keeps the app's script-src
(function () {
  const token = document.body.dataset.token;
  const base = `/book/${encodeURIComponent(token)}`;
  let picked = null;
  const dEl = document.getElementById('date');
  dEl.addEventListener('change', loadSlots);
  document.getElementById('book-go').addEventListener('click', submit);

  async function loadSlots() {
    picked = null;
    const r = await fetch(`${base}/slots?date=${dEl.value}`).then(r => r.json()).catch(() => ({ slots: [] }));
    const box = document.getElementById('slots');
    box.innerHTML = r.slots.length ? '' : '<span class="slots-empty">no free times that day</span>';
    for (const s of r.slots) {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'slot'; b.textContent = s.start.slice(11, 16);
      b.setAttribute('aria-pressed', 'false');
      // a visitor in another zone also sees the time on their own clock
      if (s.at) {
        const at = new Date(s.at), hm = at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        const otherDay = at.toLocaleDateString('sv') !== s.start.slice(0, 10);
        if (hm !== s.start.slice(11, 16) || otherDay) {
          const mine = document.createElement('small');
          mine.textContent = (otherDay ? at.toLocaleDateString([], { weekday: 'short' }) + ' ' : '') + hm + ' your time';
          b.appendChild(mine);
        }
      }
      b.onclick = () => { box.querySelectorAll('.slot').forEach(x => { x.classList.remove('sel'); x.setAttribute('aria-pressed', 'false'); }); b.classList.add('sel'); b.setAttribute('aria-pressed', 'true'); picked = s.start.slice(11, 16); };
      box.appendChild(b);
    }
  }

  async function submit() {
    const m = document.getElementById('msg');
    if (!picked) { m.style.color = '#f87171'; m.textContent = 'pick a time first'; return; }
    const r = await fetch(base, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ date: dEl.value, time: picked, name: document.getElementById('name').value, email: document.getElementById('email').value }) });
    if (r.ok) { m.style.color = '#4ade80'; m.textContent = 'booked! see you then.'; loadSlots(); }
    else { const why = await r.json().catch(() => ({})); m.style.color = '#f87171'; m.textContent = (typeof why.detail === 'string' ? why.detail : "that time couldn't be booked") + ' — pick another'; loadSlots(); }
  }

  loadSlots();
})();
