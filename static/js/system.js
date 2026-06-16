// system monitor — neofetch (the real OS logo + a live spec list) on top of a
// btop-dense live dashboard: a block-char cpu history graph, a per-core grid,
// memory/swap breakdown, up/down network graphs, a disk panel, and a top-process
// table. all monospace + hand-rendered, polled live. no chart library.
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const HIST = 60;
const cpuHist = [], ramHist = [], netDownHist = [], netUpHist = [];

// ── os logos (neofetch-style, picked by the detected platform) ───────────────
const LOGOS = {
  // the real neofetch windows-10 logo
  windows: [
    "                                ..,",
    "                    ....,,:;+ccllll",
    "      ...,,+:;  cllllllllllllllllll",
    ",cclllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "                                   ",
    "llllllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "llllllllllllll  lllllllllllllllllll",
    "`'ccllllllllll  lllllllllllllllllll",
    "       `'*::.   :ccllllllllllllllll",
    "                       ````''*::cll",
  ].join('\n'),
  // the real neofetch apple logo
  darwin: [
    "                    'c.",
    "                 ,xNMM.",
    "               .OMMMMo",
    "               OMMM0,",
    "     .;loddo:' loolloddol;.",
    "   cKMMMMMMMMMMNWMMMMMMMMMM0:",
    " .KMMMMMMMMMMMMMMMMMMMMMMMWd.",
    " XMMMMMMMMMMMMMMMMMMMMMMMX.",
    ";MMMMMMMMMMMMMMMMMMMMMMMM:",
    ":MMMMMMMMMMMMMMMMMMMMMMMM:",
    ".MMMMMMMMMMMMMMMMMMMMMMMMX.",
    " kMMMMMMMMMMMMMMMMMMMMMMMMWd.",
    " .XMMMMMMMMMMMMMMMMMMMMMMMMMMk",
    "  .XMMMMMMMMMMMMMMMMMMMMMMMMK.",
    "    kMMMMMMMMMMMMMMMMMMMMMMd",
    "     ;KMMMMMMMWXXWMMMMMMMk.",
    "       .cooc,.    .,coo:.",
  ].join('\n'),
  // tux
  linux: [
    "         _nnnn_",
    "        dGGGGMMb",
    "       @p~qp~~qMb",
    "       M|@||@) M|",
    "       @,----.JM|",
    "      JS^\\__/  qKL",
    "     dZP        qKRb",
    "    dZP          qKKb",
    "   fZP            SMMb",
    "   HZM            MMMM",
    "   FqM            MMMM",
    "  .|.        |\\dS\"qML",
    "  |    `.       | `' \\Zq",
    " _)      \\.___.,|     .'",
    " \\____   )MMMMMM|   .'",
    "      `-'       `--'",
  ].join('\n'),
  generic: [
    "        #####",
    "       #######",
    "       ##0#0##",
    "       #######",
    "      ## ' '##",
    "     #'       '#",
    "    #           #",
    "    #   #   #   #",
    "    #           #",
    "     #         #",
    "      ##     ##",
  ].join('\n'),
};
function logoFor(plat) {
  const p = (plat || '').toLowerCase();
  if (p.includes('win')) return LOGOS.windows;
  if (p.includes('darwin') || p.includes('mac')) return LOGOS.darwin;
  if (p.includes('linux')) return LOGOS.linux;
  return LOGOS.generic;
}

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
const glyph = v => BLOCKS[Math.max(0, Math.min(8, Math.round((v / 100) * 8)))];

function meter(pct, width = 18, color) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const fill = Math.round((p / 100) * width);
  const c = color || heat(p);
  return `<span class="m-track">[<span style="color:${c}">${'█'.repeat(fill)}</span>` +
    `<span class="m-empty">${'░'.repeat(Math.max(0, width - fill))}</span>]</span>`;
}

// block area graph, `rows` tall; values scaled to `max`; each column coloured by
// `colorFn(value, pctOfMax)`.
function areaGraph(hist, rows, max, colorFn) {
  if (!hist || hist.length < 1) return '<span class="g-dim">gathering…</span>';
  const cols = hist.slice(-HIST), m = max || Math.max(1, ...cols);
  const lines = [];
  for (let r = rows - 1; r >= 0; r--) {
    let line = '';
    for (const v of cols) {
      const cells = (Math.min(v, m) / m) * rows;
      let ch;
      if (cells >= r + 1) ch = '█';
      else if (cells <= r) ch = ' ';
      else ch = BLOCKS[Math.max(1, Math.round((cells - r) * 8))];
      line += ch === ' ' ? ' ' : `<span style="color:${colorFn(v, (v / m) * 100)}">${ch}</span>`;
    }
    lines.push(line);
  }
  return lines.join('\n');
}
const loadGraph = (h, rows) => areaGraph(h, rows, 100, v => heat(v));

function fmtRate(bps) {
  bps = bps || 0;
  if (bps < 1024) return `${bps.toFixed(0)} B/s`;
  if (bps < 1048576) return `${(bps / 1024).toFixed(1)} KiB/s`;
  return `${(bps / 1048576).toFixed(2)} MiB/s`;
}
function fmtBytes(n) {
  n = n || 0;
  for (const [u, s] of [['TiB', 1099511627776], ['GiB', 1073741824], ['MiB', 1048576], ['KiB', 1024]]) {
    if (n >= s) return `${(n / s).toFixed(1)} ${u}`;
  }
  return `${n} B`;
}
function uptime(sec) {
  if (!sec) return '—';
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return (d ? `${d}d ` : '') + (h ? `${h}h ` : '') + `${m}m`;
}

function palette() {
  const top = ['#1a1a1a', '#f87171', '#8bd450', '#e3c64b', 'var(--accent)', '#c08cf8', '#5ec8d8', '#cfcfcf'];
  const bot = ['#4a4a4a', '#fca5a5', '#b6e88a', '#f0dd8a', '#a9b2f8', '#d8b6fb', '#9fe0ea', '#ffffff'];
  const row = a => a.map(c => `<span class="pal" style="background:${c}"></span>`).join('');
  return `<div class="nf-pal">${row(top)}</div><div class="nf-pal">${row(bot)}</div>`;
}
const kv = (k, v) => `<div class="nf-row"><span class="nf-key">${esc(k)}</span><span class="nf-val">${esc(v)}</span></div>`;

function render(s) {
  const body = $('system-body');
  if (!body) return;
  if (s.cpu.percent != null) push(cpuHist, s.cpu.percent);
  push(ramHist, s.memory.percent);
  push(netDownHist, (s.net?.down_bps || 0));
  push(netUpHist, (s.net?.up_bps || 0));

  const cpu = s.cpu, mem = s.memory, h = s.host, sw = s.swap, net = s.net || {};
  const title = `${h.user || 'user'}@${h.hostname || 'host'}`;
  const freq = cpu.freq_mhz ? `@ ${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : '';
  const disk0 = (s.disks || [])[0];

  const hostEl = $('system-host');
  if (hostEl) hostEl.textContent = s.live ? `live · ${s.proc_count || 0} procs` : 'static (no psutil)';

  // ── neofetch header ──────────────────────────────────────────────
  const info = [
    `<div class="nf-title">${esc(title)}</div>`,
    `<div class="nf-rule">${'─'.repeat(Math.max(10, title.length))}</div>`,
    kv('os', h.os + (h.arch ? ` (${h.arch})` : '')),
    kv('host', h.hostname),
    kv('uptime', uptime(s.uptime_sec)),
    kv('cpu', `${cpu.name || 'cpu'} (${cpu.cores || '?'}) ${freq}`.trim()),
    kv('gpu', s.gpu.has ? `${s.gpu.name}${s.gpu.vram_gb ? ` · ${s.gpu.vram_gb} GB` : ''}` : 'none detected'),
    kv('memory', `${mem.used_gb} / ${mem.total_gb} GB (${Math.round(mem.percent)}%)`),
    sw && sw.total_gb ? kv('swap', `${sw.used_gb} / ${sw.total_gb} GB (${Math.round(sw.percent)}%)`) : '',
    disk0 ? kv('disk', `${disk0.used_gb} / ${disk0.total_gb} GB (${Math.round(disk0.percent)}%)`) : '',
    s.load ? kv('load', s.load.map(x => x.toFixed(2)).join(' ')) : '',
    kv('procs', s.proc_count || '—'),
    kv('backend', h.backend || '—'),
    kv('shell', `python ${h.python || ''}`),
    palette(),
  ].join('');
  const neofetch = `<div class="neofetch">
    <pre class="nf-logo">${esc(logoFor(h.platform))}</pre>
    <div class="nf-info">${info}</div>
  </div>`;

  // ── cpu box ──────────────────────────────────────────────────────
  const cores = (cpu.per_core || []).map((c, i) =>
    `<span class="core"><span class="core-id">${String(i).padStart(2, '0')}</span>` +
    `${meter(c, 7)}<span class="core-pct" style="color:${heat(c)}">${String(Math.round(c)).padStart(3)}%</span></span>`).join('');
  const liveNote = s.live ? '' :
    `<div class="sys-note">live cpu% + processes + net need <code>psutil</code> (<code>pip install psutil</code>); ram + disk shown from the static readout.</div>`;
  const cpuBox = `<div class="btop-box span2" data-label="cpu  ${cpu.cores || '?'} threads ${freq}${s.temp_c ? '  ' + s.temp_c + '°C' : ''}">
    <div class="bx-line"><span class="bx-pct" style="color:${heat(cpu.percent)}">${cpu.percent == null ? '—' : Math.round(cpu.percent) + '%'}</span>
      ${meter(cpu.percent, 30)}</div>
    <pre class="graph">${loadGraph(cpuHist, 8)}</pre>
    <div class="cores-grid">${cores}</div>
  </div>`;

  // ── memory box ───────────────────────────────────────────────────
  const memRow = (lbl, used, total, pct, color) =>
    `<div class="bx-line"><span class="bx-tag">${lbl}</span>${meter(pct, 20, color)}` +
    `<span class="bx-meta">${used} / ${total} GB</span></div>`;
  const memBox = `<div class="btop-box" data-label="mem">
    ${memRow('ram', mem.used_gb, mem.total_gb, mem.percent)}
    ${mem.cached_gb ? `<div class="bx-line"><span class="bx-tag">cache</span>${meter(mem.total_gb ? mem.cached_gb / mem.total_gb * 100 : 0, 20, '#5ec8d8')}<span class="bx-meta">${mem.cached_gb} GB</span></div>` : ''}
    ${sw && sw.total_gb ? memRow('swap', sw.used_gb, sw.total_gb, sw.percent, '#c08cf8') : ''}
    <pre class="graph graph-sm">${loadGraph(ramHist, 4)}</pre>
  </div>`;

  // ── network box ──────────────────────────────────────────────────
  const netBox = `<div class="btop-box" data-label="net">
    <div class="bx-line"><span class="bx-tag" style="color:#5ec8d8">↓ dn</span><span class="bx-rate">${fmtRate(net.down_bps)}</span>
      <span class="bx-meta">${fmtBytes(net.recv_total)} total</span></div>
    <pre class="graph graph-sm">${areaGraph(netDownHist, 3, 0, () => '#5ec8d8')}</pre>
    <div class="bx-line"><span class="bx-tag" style="color:#c08cf8">↑ up</span><span class="bx-rate">${fmtRate(net.up_bps)}</span>
      <span class="bx-meta">${fmtBytes(net.sent_total)} total</span></div>
    <pre class="graph graph-sm">${areaGraph(netUpHist, 3, 0, () => '#c08cf8')}</pre>
  </div>`;

  // ── disk box ─────────────────────────────────────────────────────
  const io = s.disk_io || {};
  const diskBox = `<div class="btop-box" data-label="disk">
    ${(s.disks || []).map(d => `<div class="bx-line"><span class="bx-tag">${esc(d.mount)}</span>${meter(d.percent, 16)}
      <span class="bx-meta">${d.used_gb}/${d.total_gb} GB</span></div>`).join('') || '<span class="g-dim">no disks</span>'}
    ${(io.read_bps != null) ? `<div class="bx-line io"><span class="bx-tag">io</span><span class="bx-meta">r ${fmtRate(io.read_bps)} · w ${fmtRate(io.write_bps)}</span></div>` : ''}
  </div>`;

  // ── process table ────────────────────────────────────────────────
  const rows = (s.procs || []).map(p => `<div class="proc-row">
    <span class="p-pid">${p.pid}</span>
    <span class="p-name">${esc(p.name)}</span>
    <span class="p-cpu" style="color:${heat(p.cpu)}">${p.cpu.toFixed(1)}</span>
    <span class="p-mem">${p.mem.toFixed(1)}</span>
  </div>`).join('');
  const procBox = `<div class="btop-box span2" data-label="processes  (top ${(s.procs || []).length} of ${s.proc_count || 0})">
    <div class="proc-row proc-head"><span>pid</span><span>name</span><span>cpu%</span><span>mem%</span></div>
    ${rows || '<span class="g-dim">no process data — needs psutil</span>'}
  </div>`;

  body.innerHTML = liveNote + neofetch + `<div class="btop-grid">${cpuBox}${memBox}${netBox}${diskBox}${procBox}</div>`;
}

function push(arr, v) { arr.push(v); if (arr.length > HIST) arr.shift(); }

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
