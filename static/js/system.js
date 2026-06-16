// system monitor — live cpu / ram / disk / gpu with svg ring gauges + sparklines.
// polls /api/system/stats every couple seconds while the view is open. hand-drawn
// svg so it matches the theme (no chart lib, no native gauges).
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const R = 52, C = 2 * Math.PI * R, HIST = 60;
const cpuHist = [], ramHist = [];

// usage colour: accent until it's getting hot, then warn → error (meaningful state)
const heat = pct => pct == null ? 'var(--muted)' : pct >= 92 ? 'var(--error)' : pct >= 80 ? '#d9a441' : 'var(--accent)';

function ring(pct, big, small) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const off = C * (1 - p / 100);
  return `<div class="sys-gauge">
    <svg viewBox="0 0 120 120">
      <circle class="sys-gauge-track" cx="60" cy="60" r="${R}"/>
      <circle class="sys-gauge-fill" cx="60" cy="60" r="${R}" transform="rotate(-90 60 60)"
        style="stroke-dasharray:${C.toFixed(1)};stroke-dashoffset:${off.toFixed(1)};stroke:${heat(pct)}"/>
      <text x="60" y="58" class="sys-gauge-val">${pct == null ? '—' : Math.round(pct)}<tspan class="sys-gauge-pct">%</tspan></text>
      <text x="60" y="76" class="sys-gauge-cap">${esc(big)}</text>
    </svg>
    <div class="sys-gauge-sub">${esc(small)}</div>
  </div>`;
}

function spark(hist, color) {
  if (hist.length < 2) return '';
  const w = 100, h = 26, step = w / (HIST - 1);
  const pts = hist.map((v, i) => `${(i * step).toFixed(1)},${(h - (v / 100) * h).toFixed(1)}`).join(' ');
  const off = (HIST - hist.length) * step;
  return `<svg class="sys-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${pts}" style="stroke:${color}" transform="translate(${off.toFixed(1)},0)"/></svg>`;
}

function bar(pct, label, sub) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  return `<div class="sys-bar-row">
    <div class="sys-bar-head"><span>${esc(label)}</span><span class="sys-bar-sub">${esc(sub)}</span></div>
    <div class="sys-bar-track"><div class="sys-bar-fill" style="width:${p}%;background:${heat(pct)}"></div></div>
  </div>`;
}

function uptime(sec) {
  if (!sec) return '';
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return (d ? `${d}d ` : '') + (h ? `${h}h ` : '') + `${m}m`;
}

function render(s) {
  const body = $('system-body');
  if (!body) return;
  if (s.cpu.percent != null) { cpuHist.push(s.cpu.percent); if (cpuHist.length > HIST) cpuHist.shift(); }
  ramHist.push(s.memory.percent); if (ramHist.length > HIST) ramHist.shift();

  const host = $('system-host');
  if (host) host.textContent = `${s.host.os} · ${s.host.hostname}` + (s.uptime_sec ? ` · up ${uptime(s.uptime_sec)}` : '');

  const cores = s.cpu.per_core?.length
    ? `<div class="sys-cores">${s.cpu.per_core.map(c =>
        `<span class="sys-core" title="${c}%"><span class="sys-core-fill" style="height:${Math.max(4, c)}%;background:${heat(c)}"></span></span>`).join('')}</div>`
    : '';

  const disks = (s.disks || []).map(d =>
    bar(d.percent, d.mount, `${d.used_gb} / ${d.total_gb} GB`)).join('') || '<div class="sys-dim">no disks reported</div>';

  const freq = s.cpu.freq_mhz ? ` · ${(s.cpu.freq_mhz / 1000).toFixed(1)} GHz` : '';
  const liveNote = s.live ? '' :
    '<div class="sys-note">live cpu% needs <code>psutil</code> — <code>pip install psutil</code>. ram + disk shown from the static readout.</div>';

  body.innerHTML = `
    ${liveNote}
    <div class="sys-gauges">
      ${ring(s.cpu.percent, 'cpu', `${esc(s.cpu.name || '')}`)}
      ${ring(s.memory.percent, 'memory', `${s.memory.used_gb} / ${s.memory.total_gb} GB`)}
    </div>
    <div class="sys-grid">
      <div class="sys-card">
        <div class="sys-card-h">cpu <span class="sys-dim">${s.cpu.cores || '?'} threads${freq}</span></div>
        ${cores}
        <div class="sys-spark-wrap">${spark(cpuHist, 'var(--accent)')}</div>
      </div>
      <div class="sys-card">
        <div class="sys-card-h">memory <span class="sys-dim">${s.memory.used_gb} / ${s.memory.total_gb} GB</span></div>
        <div class="sys-spark-wrap sys-spark-big">${spark(ramHist, '#8b9cf8')}</div>
      </div>
      <div class="sys-card">
        <div class="sys-card-h">disk</div>
        ${disks}
      </div>
      <div class="sys-card">
        <div class="sys-card-h">graphics</div>
        ${s.gpu.has
          ? `<div class="sys-kv"><span>gpu</span><b>${esc(s.gpu.name || 'gpu')}</b></div>
             ${s.gpu.vram_gb ? `<div class="sys-kv"><span>vram</span><b>${s.gpu.vram_gb} GB</b></div>` : ''}
             ${s.gpu.count > 1 ? `<div class="sys-kv"><span>count</span><b>${s.gpu.count}</b></div>` : ''}`
          : '<div class="sys-dim">no discrete gpu detected</div>'}
        <div class="sys-kv"><span>backend</span><b>${esc(s.host.backend || '—')}</b></div>
        <div class="sys-kv"><span>python</span><b>${esc(s.host.python || '')}</b></div>
      </div>
    </div>`;
}

let _timer = null, _wired = false, _ok = false;
async function tick() {
  const v = $('system-view');
  if (!v || v.style.display === 'none' || document.hidden) return;
  try {
    const r = await fetch('/api/system/stats');
    if (!r.ok) throw new Error(r.status === 404 ? 'the /api/system/stats route is missing' : `server returned ${r.status}`);
    const s = await r.json();
    if (!s || !s.cpu || !s.memory) throw new Error('unexpected response');
    render(s);
    _ok = true;
  } catch (e) {
    // don't wipe a working view over one transient blip; only show the error if
    // we never managed to load (e.g. the route isn't there yet)
    const b = $('system-body');
    if (b && !_ok) {
      const restart = /missing|404|unexpected/.test(e.message)
        ? ' if you just updated alles, restart the server so it picks up the new route: <code>python cli.py restart</code>'
        : '';
      b.innerHTML = `<div class="sys-note">couldn’t read system stats — ${esc(e.message)}.${restart}</div>`;
    }
  }
}

export function initSystem() {
  $('system-body').innerHTML = '<div class="sys-dim" style="padding:1rem">reading the machine…</div>';
  tick();
  if (!_wired) {
    _wired = true;
    _timer = setInterval(tick, 2000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  }
}
