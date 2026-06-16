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

// discrete heat ramp by VALUE — used for the numeric labels (cpu%, per-core, proc)
function heat(v) {
  if (v == null) return 'var(--muted)';
  if (v >= 90) return '#f87171';
  if (v >= 75) return '#fb923c';
  if (v >= 55) return '#fbbf24';
  if (v >= 30) return '#a3e635';
  return '#4ade80';
}

// btop-style gradients: colour comes from POSITION, in hard discrete steps (the
// "pixelized" terminal look — no smooth blend). vertical = by height for graphs,
// horizontal = along the bar for meters. cold (green) → hot (red).
const _RAMP = ['#4ade80', '#a3e635', '#fbbf24', '#fb923c', '#f87171'];
function _step(f, ramp) { return ramp[Math.min(ramp.length - 1, Math.max(0, Math.floor(f * ramp.length)))]; }
const vgrad = (r, rows) => _step(rows > 1 ? r / (rows - 1) : 0, _RAMP);
const hgrad = (i, w) => _step(w > 1 ? i / (w - 1) : 0, _RAMP);
const vgradDown = (r, rows) => _step(rows > 1 ? r / (rows - 1) : 0, ['#2dd4bf', '#39b3e5', '#5b8def']);
const vgradUp = (r, rows) => _step(rows > 1 ? r / (rows - 1) : 0, ['#a78bfa', '#c08cf8', '#e879f9']);

const BLOCKS = [' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
const glyph = v => BLOCKS[Math.max(0, Math.min(8, Math.round((v / 100) * 8)))];

// a bar meter — each filled cell coloured by its horizontal position (pixelized
// gradient), unless a solid `color` is given (cache/swap keep their identity).
function meter(pct, width = 18, color) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const fill = Math.round((p / 100) * width);
  let bar = '';
  for (let i = 0; i < width; i++) {
    bar += i < fill ? `<span style="color:${color || hgrad(i, width)}">█</span>` : '░';
  }
  return `<span class="m-track">[${bar}]</span>`;
}

// block area graph, `rows` tall, scaled to `max`. each CELL is coloured by its
// height via `grad(row, rows)` → a vertical pixelized gradient like btop's.
function areaGraph(hist, rows, max, grad) {
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
      line += ch === ' ' ? ' ' : `<span style="color:${grad(r, rows)}">${ch}</span>`;
    }
    lines.push(line);
  }
  return lines.join('\n');
}
const loadGraph = (h, rows) => areaGraph(h, rows, 100, vgrad);

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
const memMB = b => (b >= 1073741824) ? `${(b / 1073741824).toFixed(1)}G` : `${Math.round((b || 0) / 1048576)}M`;
// a tiny pixelized cpu bar for a process row
function cpuBar(pct) {
  const w = 5, f = Math.round(Math.min(100, pct || 0) / 100 * w);
  let s = '';
  for (let i = 0; i < w; i++) s += i < f ? `<span style="color:${hgrad(i, w)}">█</span>` : '░';
  return s;
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
// talljoe-style grouped tree: a header (with optional value) + ├/└ branch rows
function group(header, headerVal, rows) {
  let out = `<div class="nf-grp"><span class="nf-head">${esc(header)}</span>` +
    (headerVal ? `<span class="nf-val">${esc(headerVal)}</span>` : '') + `</div>`;
  rows.filter(Boolean).forEach((r, i, a) => {
    out += `<div class="nf-row"><span class="nf-branch">${i === a.length - 1 ? '└' : '├'}</span>` +
      `<span class="nf-key">${esc(r[0])}</span><span class="nf-val">${esc(r[1])}</span></div>`;
  });
  return out;
}

// build the static shell ONCE (logo + box frames) so animations run smoothly and
// the page doesn't flash every tick; update() only rewrites the dynamic guts.
function buildShell(s) {
  const note = s.live ? '' :
    `<div class="sys-note">live cpu% + processes + net need <code>psutil</code> (<code>pip install psutil</code>); ram + disk shown from the static readout.</div>`;
  $('system-body').innerHTML = `${note}
    <div id="sys-shell">
      <div class="neofetch">
        <pre class="nf-logo">${esc(logoFor(s.host.platform))}</pre>
        <div class="nf-info" id="nf-info"></div>
      </div>
      <div class="btop-grid">
        <div class="btop-box span2" id="box-cpu">
          <div class="bx-line" id="cpu-top"></div>
          <pre class="graph" id="cpu-graph"></pre>
          <div class="cores-grid" id="cpu-cores"></div>
        </div>
        <div class="btop-box" id="box-mem"><div id="mem-lines"></div><pre class="graph graph-sm" id="mem-graph"></pre></div>
        <div class="btop-box" id="box-net"><div id="net-body"></div></div>
        <div class="btop-box" id="box-disk"><div id="disk-body"></div></div>
        <div class="btop-box span2" id="box-proc"><div id="proc-body"></div></div>
      </div>
    </div>`;
}

function buildInfo(s, freq, disk0) {
  const cpu = s.cpu, mem = s.memory, h = s.host, sw = s.swap;
  const title = `${h.user || 'user'}@${h.hostname || 'host'}`;
  return [
    `<div class="nf-title">${esc(title)}</div>`,
    `<div class="nf-rule">${'─'.repeat(Math.max(10, title.length))}</div>`,
    group('OS', h.os, [
      ['arch', h.arch || '—'],
      ['uptime', uptime(s.uptime_sec)],
      ['procs', String(s.proc_count || '—')],
    ]),
    group('PC', h.hostname, [
      ['cpu', `${cpu.name || 'cpu'} (${cpu.cores || '?'}) ${freq}`.trim()],
      ['memory', `${mem.used_gb} / ${mem.total_gb} GB (${Math.round(mem.percent)}%)`],
      ['gpu', s.gpu.has ? `${s.gpu.name}${s.gpu.vram_gb ? ` · ${s.gpu.vram_gb} GB` : ''}` : 'none detected'],
      disk0 ? ['disk', `${disk0.used_gb} / ${disk0.total_gb} GB (${Math.round(disk0.percent)}%)`] : null,
    ]),
    group('SYS', '', [
      s.load ? ['load', s.load.map(x => x.toFixed(2)).join('  ')] : null,
      sw && sw.total_gb ? ['swap', `${sw.used_gb} / ${sw.total_gb} GB (${Math.round(sw.percent)}%)`] : null,
      ['backend', h.backend || '—'],
      ['shell', `python ${h.python || ''}`],
    ]),
    palette(),
  ].join('');
}

function render(s) {
  if (!$('sys-shell')) buildShell(s);
  if (s.cpu.percent != null) push(cpuHist, s.cpu.percent);
  push(ramHist, s.memory.percent);
  push(netDownHist, (s.net?.down_bps || 0));
  push(netUpHist, (s.net?.up_bps || 0));

  const cpu = s.cpu, mem = s.memory, sw = s.swap, net = s.net || {}, io = s.disk_io || {};
  const freq = cpu.freq_mhz ? `@ ${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : '';
  const disk0 = (s.disks || [])[0];

  const hostEl = $('system-host');
  if (hostEl) hostEl.textContent = s.live ? `live · ${s.proc_count || 0} procs` : 'static (no psutil)';

  $('nf-info').innerHTML = buildInfo(s, freq, disk0);

  // cpu
  $('box-cpu').dataset.label = `cpu  ${cpu.cores || '?'} threads ${freq}${s.temp_c ? '  ' + s.temp_c + '°C' : ''}`;
  $('cpu-top').innerHTML = `<span class="bx-pct ${cpu.percent >= 90 ? 'hot' : ''}" style="color:${heat(cpu.percent)}">${cpu.percent == null ? '—' : Math.round(cpu.percent) + '%'}</span>${meter(cpu.percent, 30)}`;
  $('cpu-graph').innerHTML = loadGraph(cpuHist, 10);
  $('cpu-cores').innerHTML = (cpu.per_core || []).map((c, i) =>
    `<span class="core"><span class="core-id">${String(i).padStart(2, '0')}</span>` +
    `${meter(c, 7)}<span class="core-pct" style="color:${heat(c)}">${String(Math.round(c)).padStart(3)}%</span></span>`).join('');

  // mem
  const memRow = (lbl, used, total, pct, color) =>
    `<div class="bx-line"><span class="bx-tag">${lbl}</span>${meter(pct, 20, color)}<span class="bx-meta">${used} / ${total} GB</span></div>`;
  $('box-mem').dataset.label = 'mem';
  $('mem-lines').innerHTML =
    memRow('ram', mem.used_gb, mem.total_gb, mem.percent) +
    (mem.cached_gb ? `<div class="bx-line"><span class="bx-tag">cache</span>${meter(mem.total_gb ? mem.cached_gb / mem.total_gb * 100 : 0, 20, '#5ec8d8')}<span class="bx-meta">${mem.cached_gb} GB</span></div>` : '') +
    (sw && sw.total_gb ? memRow('swap', sw.used_gb, sw.total_gb, sw.percent, '#c08cf8') : '');
  $('mem-graph').innerHTML = loadGraph(ramHist, 5);

  // net
  $('box-net').dataset.label = 'net';
  $('net-body').innerHTML =
    `<div class="bx-line"><span class="bx-tag" style="color:#5ec8d8">↓ dn</span><span class="bx-rate">${fmtRate(net.down_bps)}</span><span class="bx-meta">${fmtBytes(net.recv_total)} total</span></div>` +
    `<pre class="graph graph-sm">${areaGraph(netDownHist, 4, 0, vgradDown)}</pre>` +
    `<div class="bx-line"><span class="bx-tag" style="color:#c08cf8">↑ up</span><span class="bx-rate">${fmtRate(net.up_bps)}</span><span class="bx-meta">${fmtBytes(net.sent_total)} total</span></div>` +
    `<pre class="graph graph-sm">${areaGraph(netUpHist, 4, 0, vgradUp)}</pre>`;

  // disk
  $('box-disk').dataset.label = 'disk';
  $('disk-body').innerHTML =
    ((s.disks || []).map(d => `<div class="bx-line"><span class="bx-tag">${esc(d.mount)}</span>${meter(d.percent, 16)}<span class="bx-meta">${d.used_gb}/${d.total_gb} GB</span></div>`).join('') || '<span class="g-dim">no disks</span>') +
    ((io.read_bps != null) ? `<div class="bx-line io"><span class="bx-tag">io</span><span class="bx-meta">r ${fmtRate(io.read_bps)} · w ${fmtRate(io.write_bps)}</span></div>` : '');

  // proc — btop-style table: pid · program · threads · user · mem · cpu(bar+%)
  $('box-proc').dataset.label = `processes  (top ${(s.procs || []).length} of ${s.proc_count || 0})`;
  $('proc-body').innerHTML =
    `<div class="proc-row proc-head"><span>pid</span><span>program</span><span>thr</span><span>user</span><span>mem</span><span>cpu%</span></div>` +
    ((s.procs || []).map(p => `<div class="proc-row">
      <span class="p-pid">${p.pid}</span>
      <span class="p-name">${esc(p.name)}</span>
      <span class="p-thr">${p.threads || ''}</span>
      <span class="p-user">${esc(p.user || '')}</span>
      <span class="p-mem">${memMB(p.rss)}</span>
      <span class="p-cpu"><span class="p-cpubar">${cpuBar(p.cpu)}</span><b style="color:${heat(p.cpu)}">${String(p.cpu.toFixed(0)).padStart(3)}</b></span>
    </div>`).join('') || '<span class="g-dim">no process data — needs psutil</span>');
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
