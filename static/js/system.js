// system monitor — neofetch-style header (ascii logo + spec list + palette) and
// btop-style live boxes (block-char cpu history graph, per-core block bars, block
// meters for memory + disk). all monospace, terminal-flavoured, polled live.
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const HIST = 56;
const cpuHist = [], ramHist = [];

// figlet 'alles' (standard font) — the neofetch logo
const LOGO = String.raw`       _ _
  __ _| | | ___  ___
 / _\` | | |/ _ \/ __|
| (_| | | |  __/\__ \
 \__,_|_|_|\___||___/`;

// load → colour, btop-style green→amber→orange→red gradient (load IS state here)
function heat(v) {
  if (v == null) return 'var(--muted)';
  if (v >= 90) return '#f87171';
  if (v >= 75) return '#f59e0b';
  if (v >= 55) return '#e3c64b';
  if (v >= 30) return '#8bd450';
  return '#4ade80';
}

const BLOCKS = [' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

// a single 1/8-resolution glyph for a 0-100 value (per-core bars)
const glyph = v => BLOCKS[Math.max(0, Math.min(8, Math.round((v / 100) * 8)))];

// a horizontal block meter: [██████░░░░] coloured by value
function meter(pct, width = 18) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const fill = Math.round((p / 100) * width);
  const c = heat(p);
  return `<span class="m-track">[<span style="color:${c}">${'█'.repeat(fill)}</span>` +
    `<span class="m-empty">${'░'.repeat(width - fill)}</span>]</span>`;
}

// a btop-style block area graph: `rows` tall, one column per history sample,
// each column coloured by its own value so the graph carries the gradient.
function areaGraph(hist, rows = 7) {
  if (!hist.length) return '<span class="g-dim">gathering…</span>';
  const cols = hist.slice(-HIST);
  const lines = [];
  for (let r = rows - 1; r >= 0; r--) {           // top row first
    let line = '';
    for (const v of cols) {
      const cells = (v / 100) * rows;             // how many cells tall this column is
      let ch;
      if (cells >= r + 1) ch = '█';               // fully filled at this row
      else if (cells <= r) ch = ' ';              // empty at this row
      else ch = BLOCKS[Math.round((cells - r) * 8)];   // partial top cell
      line += ch === ' ' ? ' ' : `<span style="color:${heat(v)}">${ch}</span>`;
    }
    lines.push(line);
  }
  return lines.join('\n');
}

function uptime(sec) {
  if (!sec) return '—';
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return (d ? `${d}d ` : '') + (h ? `${h}h ` : '') + `${m}m`;
}

// neofetch-style colour palette (two rows of 8)
function palette() {
  const top = ['#1a1a1a', '#f87171', '#8bd450', '#e3c64b', 'var(--accent)', '#c08cf8', '#5ec8d8', '#cfcfcf'];
  const bot = ['#4a4a4a', '#fca5a5', '#b6e88a', '#f0dd8a', '#a9b2f8', '#d8b6fb', '#9fe0ea', '#ffffff'];
  const row = arr => arr.map(c => `<span class="pal" style="background:${c}"></span>`).join('');
  return `<div class="nf-pal">${row(top)}</div><div class="nf-pal">${row(bot)}</div>`;
}

function kv(k, v) {
  return `<div class="nf-row"><span class="nf-key">${esc(k)}</span><span class="nf-val">${esc(v)}</span></div>`;
}

function render(s) {
  const body = $('system-body');
  if (!body) return;
  if (s.cpu.percent != null) { cpuHist.push(s.cpu.percent); if (cpuHist.length > HIST) cpuHist.shift(); }
  ramHist.push(s.memory.percent); if (ramHist.length > HIST) ramHist.shift();

  const cpu = s.cpu, mem = s.memory, h = s.host;
  const title = `${h.user || 'user'}@${h.hostname || 'host'}`;

  const host = $('system-host');
  if (host) host.textContent = s.live ? 'live' : 'static (no psutil)';

  const freq = cpu.freq_mhz ? `@ ${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : '';
  const cpuLine = `${cpu.name || 'cpu'} (${cpu.cores || '?'}) ${freq}`.trim();
  const gpuLine = s.gpu.has ? `${s.gpu.name || 'gpu'}${s.gpu.vram_gb ? ` · ${s.gpu.vram_gb} GB` : ''}` : 'none detected';
  const disk0 = (s.disks || [])[0];

  // ── neofetch header ──────────────────────────────────────────────
  const info = [
    `<div class="nf-title">${esc(title)}</div>`,
    `<div class="nf-rule">${'─'.repeat(Math.max(8, title.length))}</div>`,
    kv('os', h.os + (h.arch ? ` (${h.arch})` : '')),
    kv('host', h.hostname),
    kv('uptime', uptime(s.uptime_sec)),
    kv('cpu', cpuLine),
    kv('gpu', gpuLine),
    kv('memory', `${mem.used_gb} / ${mem.total_gb} GB (${Math.round(mem.percent)}%)`),
    disk0 ? kv('disk', `${disk0.used_gb} / ${disk0.total_gb} GB (${Math.round(disk0.percent)}%)`) : '',
    kv('backend', h.backend || '—'),
    kv('python', h.python || ''),
    palette(),
  ].join('');

  const neofetch = `<div class="neofetch">
    <pre class="nf-logo">${esc(LOGO)}</pre>
    <div class="nf-info">${info}</div>
  </div>`;

  // ── btop boxes ───────────────────────────────────────────────────
  const liveNote = s.live ? '' :
    `<div class="sys-note">live cpu% needs <code>psutil</code> (<code>pip install psutil</code>); ram + disk shown from the static readout.</div>`;

  const cores = (cpu.per_core || []).map((c, i) =>
    `<span class="core" title="core ${i}: ${c}%" style="color:${heat(c)}">${glyph(c)}</span>`).join('');

  const cpuBox = `<div class="btop-box" data-label="cpu">
    <div class="bx-line"><span class="bx-pct" style="color:${heat(cpu.percent)}">${cpu.percent == null ? '—' : Math.round(cpu.percent) + '%'}</span>
      <span class="bx-meta">${cpu.cores || '?'} threads ${freq}</span></div>
    <pre class="graph">${areaGraph(cpuHist)}</pre>
    ${cores ? `<div class="cores-row">${cores}</div>` : ''}
  </div>`;

  const memBox = `<div class="btop-box" data-label="mem">
    <div class="bx-line">${meter(mem.percent, 22)} <span class="bx-pct" style="color:${heat(mem.percent)}">${Math.round(mem.percent)}%</span>
      <span class="bx-meta">${mem.used_gb} / ${mem.total_gb} GB</span></div>
    <pre class="graph graph-sm">${areaGraph(ramHist, 4)}</pre>
  </div>`;

  const diskBox = `<div class="btop-box" data-label="disk">
    ${(s.disks || []).map(d => `<div class="bx-line">${meter(d.percent, 22)}
      <span class="bx-pct" style="color:${heat(d.percent)}">${Math.round(d.percent)}%</span>
      <span class="bx-meta">${esc(d.mount)} · ${d.used_gb}/${d.total_gb} GB</span></div>`).join('')
      || '<span class="g-dim">no disks reported</span>'}
  </div>`;

  body.innerHTML = liveNote + neofetch + `<div class="btop-grid">${cpuBox}${memBox}${diskBox}</div>`;
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
  $('system-body').innerHTML = '<div class="g-dim" style="padding:1rem;font-family:\'JetBrains Mono\',monospace">reading the machine…</div>';
  tick();
  if (!_wired) {
    _wired = true;
    _timer = setInterval(tick, 1500);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  }
}
