// system monitor — neofetch (the real OS logo + a live spec list) on top of a
// btop-dense live dashboard: a block-char cpu history graph, a per-core grid,
// memory/swap breakdown, up/down network graphs, a disk panel, and a top-process
// table. all monospace + hand-rendered, polled live. no chart library.
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const HIST = 720;   // ~18min @1.5s — more history = each graph shows a wider span (zoomed out)
const cpuHist = [], ramHist = [], netDownHist = [], netUpHist = [], dioHist = [];
const coreHist = [];   // per-core %, coreHist[i] = that core's history

// how many monospace columns fit a graph element — so graphs FILL their box
// (btop sizes the graph to the box width and scrolls data in from the right).
const _cw = {};
function charW(small) {
  const k = small ? 'sm' : 'lg';
  if (_cw[k]) return _cw[k];
  const p = document.createElement('span');
  p.className = 'graph' + (small ? ' graph-sm' : '');
  p.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;padding:0;margin:0;border:0';
  p.textContent = '█'.repeat(40);
  document.body.appendChild(p);
  const w = p.getBoundingClientRect().width / 40;
  p.remove();
  if (w > 0) _cw[k] = w;
  return w || 8;
}
function colsFor(el, small) {
  if (!el || !el.clientWidth) return 60;
  return Math.max(8, Math.floor((el.clientWidth - 9) / charW(small)));
}
// how many text rows fit a graph box's height — so braille graphs FILL vertically too
const _chh = {};
function charH(small) {
  const k = small ? 'sm' : 'lg';
  if (_chh[k]) return _chh[k];
  const p = document.createElement('pre');
  p.className = 'graph' + (small ? ' graph-sm' : '');
  p.style.cssText = 'position:absolute;visibility:hidden;margin:0;padding:0;border:0;white-space:pre';
  p.textContent = ('⣿\n').repeat(10) + '⣿';   // 11 lines
  document.body.appendChild(p);
  const h = p.getBoundingClientRect().height / 11;
  p.remove();
  if (h > 0) _chh[k] = h;
  return h || 12;
}
function rowsFor(el, small, fallback) {
  if (!el || !el.clientHeight) return fallback || (small ? 4 : 9);
  return Math.max(2, Math.floor((el.clientHeight - 7) / charH(small)));   // 7 = vertical padding
}

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
const _RAMP = ['#4ade80', '#7ee05a', '#b6e84b', '#e8d23e', '#f6a738', '#f6783a', '#f25555'];
const _RAMP_DN = ['#2dd4bf', '#33c7cf', '#39b3e5', '#4a9bea', '#5b8def'];
const _RAMP_UP = ['#a78bfa', '#b58cf8', '#c08cf8', '#d479f4', '#e879f9'];
function _step(f, ramp) { return ramp[Math.min(ramp.length - 1, Math.max(0, Math.floor(f * ramp.length)))]; }
const vgrad = (r, rows) => _step(rows > 1 ? r / (rows - 1) : 0, _RAMP);
const hgrad = (i, w) => _step(w > 1 ? i / (w - 1) : 0, _RAMP);
const vgradDown = (r, rows) => _step(rows > 1 ? r / (rows - 1) : 0, _RAMP_DN);
const vgradUp = (r, rows) => _step(rows > 1 ? r / (rows - 1) : 0, _RAMP_UP);

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

// btop-style window: the last `n` real samples, newest on the right, left padded
// empty until the buffer fills. ONE sample per point — no stretching/interpolation,
// so it scrolls in like btop instead of looking like one smeared/zoomed graph.
function _window(hist, n) {
  if (!hist || !hist.length) return new Array(n).fill(0);
  if (hist.length >= n) return hist.slice(hist.length - n);
  return new Array(n - hist.length).fill(0).concat(hist);
}

// canvas graph: same data model as btop (1 real sample per column, newest on the
// right, height = value/max, colour = vertical gradient by height) but drawn as solid
// thin bars on a canvas. braille/blocks can't render solid in a browser font — this
// gives the clean "vertical strokes" btop look with no floating dots / fat pixels.
function drawGraph(canvas, hist, ramp, max) {
  if (!canvas || !canvas.getContext) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const bw = 2;                                  // bar pitch in px
  const n = Math.max(1, Math.floor(w / bw));
  const data = _window(hist, n);                 // scrolls in from the right
  const m = max || Math.max(1, ...data);
  // bottom→top gradient; a short bar only shows the cool low end, a tall one runs hot
  const g = ctx.createLinearGradient(0, h, 0, 0);
  ramp.forEach((c, i) => g.addColorStop(Math.min(1, i / (ramp.length - 1)), c));
  ctx.fillStyle = g;
  for (let i = 0; i < n; i++) {
    const v = Math.min(Math.max(data[i], 0), m) / m;
    if (v <= 0) continue;
    const bh = Math.max(1, v * h);
    ctx.fillRect(i * bw, h - bh, bw - 0.6, bh);  // 0.6px gap → discrete strokes
  }
}

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
          <canvas class="graph-canvas" id="cpu-graph"></canvas>
          <div class="cores-grid" id="cpu-cores"></div>
        </div>
        <div class="btop-cols">
          <div class="btop-left">
            <div class="btop-box" id="box-mem"><div id="mem-lines"></div><canvas class="graph-canvas" id="mem-graph"></canvas></div>
            <div class="btop-box" id="box-net"><div id="net-head"></div><canvas class="graph-canvas" id="net-dn-graph"></canvas><div id="net-mid"></div><canvas class="graph-canvas" id="net-up-graph"></canvas></div>
            <div class="btop-box" id="box-disk"><div id="disk-body"></div><canvas class="graph-canvas" id="disk-graph"></canvas></div>
          </div>
          <div class="btop-box span2" id="box-proc"><div id="proc-body"></div></div>
        </div>
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
  push(dioHist, (s.disk_io?.read_bps || 0) + (s.disk_io?.write_bps || 0));
  (s.cpu.per_core || []).forEach((c, i) => { if (!coreHist[i]) coreHist[i] = []; push(coreHist[i], c); });

  const cpu = s.cpu, mem = s.memory, sw = s.swap, net = s.net || {}, io = s.disk_io || {};
  const freq = cpu.freq_mhz ? `@ ${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : '';
  const disk0 = (s.disks || [])[0];

  const hostEl = $('system-host');
  if (hostEl) hostEl.textContent = s.live ? `live · ${s.proc_count || 0} procs` : 'static (no psutil)';

  $('nf-info').innerHTML = buildInfo(s, freq, disk0);

  // cpu
  $('box-cpu').dataset.label = `cpu  ${cpu.cores || '?'} threads ${freq}${s.temp_c ? '  ' + s.temp_c + '°C' : ''}`;
  $('cpu-top').innerHTML = `<span class="bx-pct ${cpu.percent >= 90 ? 'hot' : ''}" style="color:${heat(cpu.percent)}">${cpu.percent == null ? '—' : Math.round(cpu.percent) + '%'}</span>${meter(cpu.percent, 30)}`;
  drawGraph($('cpu-graph'), cpuHist, _RAMP, 100);
  $('cpu-cores').innerHTML = (cpu.per_core || []).map((c, i) =>
    `<span class="core"><span class="core-id">${String(i).padStart(2, '0')}</span>` +
    `${meter(c, 8)}<span class="core-pct" style="color:${heat(c)}">${String(Math.round(c)).padStart(3)}%</span></span>`).join('');

  // mem — total + a bar per segment (used / avail / cached / free / swap)
  const memBar = (lbl, pct, val, color) =>
    `<div class="bx-line"><span class="bx-tag">${lbl}</span>${meter(pct, 14, color)}<span class="bx-pctv" style="color:${color || heat(pct)}">${Math.round(pct)}%</span><span class="bx-meta">${val}</span></div>`;
  const tot = mem.total_gb || 0, pctOf = g => tot ? g / tot * 100 : 0;
  $('box-mem').dataset.label = 'mem';
  $('mem-lines').innerHTML =
    `<div class="bx-line bx-total"><span class="bx-tag">total</span><span class="bx-meta">${tot} GB</span></div>` +
    memBar('used', mem.percent, `${mem.used_gb} GB`) +
    (mem.available_gb != null ? memBar('avail', pctOf(mem.available_gb), `${mem.available_gb} GB`, '#4ade80') : '') +
    (mem.cached_gb ? memBar('cached', pctOf(mem.cached_gb), `${mem.cached_gb} GB`, '#5ec8d8') : '') +
    (mem.free_gb != null ? memBar('free', pctOf(mem.free_gb), `${mem.free_gb} GB`, '#7ee05a') : '') +
    (sw && sw.total_gb ? memBar('swap', sw.percent, `${sw.used_gb} / ${sw.total_gb} GB`, '#c08cf8') : '');
  drawGraph($('mem-graph'), ramHist, _RAMP, 100);

  // net — interface/ip header, rate + peak + total, a graph each way (filling the box)
  $('box-net').dataset.label = 'net';
  const peakDn = Math.max(1, ...netDownHist), peakUp = Math.max(1, ...netUpHist);
  $('net-head').innerHTML =
    (net.iface ? `<div class="bx-line bx-netif"><span class="bx-tag" style="color:var(--accent)">${esc(net.iface)}</span><span class="bx-meta">${esc(net.ip || '')}${net.link_mbps ? ` · ${net.link_mbps} Mb/s` : ''}</span></div>` : '') +
    `<div class="bx-line"><span class="bx-tag" style="color:#5ec8d8">↓ dn</span><span class="bx-rate">${fmtRate(net.down_bps)}</span><span class="bx-meta">▲ ${fmtRate(peakDn)} · Σ ${fmtBytes(net.recv_total)}</span></div>`;
  drawGraph($('net-dn-graph'), netDownHist, _RAMP_DN, 0);
  $('net-mid').innerHTML =
    `<div class="bx-line"><span class="bx-tag" style="color:#c08cf8">↑ up</span><span class="bx-rate">${fmtRate(net.up_bps)}</span><span class="bx-meta">▲ ${fmtRate(peakUp)} · Σ ${fmtBytes(net.sent_total)}</span></div>`;
  drawGraph($('net-up-graph'), netUpHist, _RAMP_UP, 0);

  // disk — per mount (used% · size · fs · free) + io rate + an io activity graph
  $('box-disk').dataset.label = 'disk';
  $('disk-body').innerHTML =
    ((s.disks || []).map(d => `<div class="bx-line"><span class="bx-tag">${esc(d.mount)}</span>${meter(d.percent, 12)}<span class="bx-pctv" style="color:${heat(d.percent)}">${Math.round(d.percent)}%</span><span class="bx-meta">${d.used_gb}/${d.total_gb} GB${d.fstype ? ` · ${esc(d.fstype)}` : ''}${d.free_gb != null ? ` · ${d.free_gb} free` : ''}</span></div>`).join('') || '<span class="g-dim">no disks</span>') +
    ((io.read_bps != null) ? `<div class="bx-line io"><span class="bx-tag">io</span><span class="bx-meta">r ${fmtRate(io.read_bps)} · w ${fmtRate(io.write_bps)}</span></div>` : '');
  drawGraph($('disk-graph'), dioHist, _RAMP, 0);

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

let _sysGen = 0;
export async function initSystem() {
  const gen = ++_sysGen;   // a later call wins the await race so we never leak a 2nd timer
  $('system-body').innerHTML = '<div class="g-dim" style="padding:1rem;font-family:\'JetBrains Mono\',monospace">reading the machine…</div>';
  if (_timer) { clearInterval(_timer); _timer = null; }
  tick();
  let ms = 1500;
  try { ms = Math.max(250, Number((await fetch('/api/settings').then(r => r.json())).system_refresh) || 1500); } catch {}
  if (gen !== _sysGen) return;   // superseded while awaiting — bail, the newer call owns the timer
  _timer = setInterval(tick, ms);
  if (!_wired) {
    _wired = true;
    document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  }
}
