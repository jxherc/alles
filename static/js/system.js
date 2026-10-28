// server overview: the machine at a glance. four vitals with a short live line each, the
// busiest processes, then cores, memory and storage as bars and what the machine is. polled
// live; the lines are one neutral color and only a value past 90% turns to the danger color.
import { plainError } from './util.js';
import { confirm as confirmDialog } from './dialog.js';
import { resolvedTimeZone, t, tp } from './i18n.js';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

export const HIST = 720;   // ~18min @1.5s of samples kept in the page

// how many samples a chart of pixel width `w` shows at `bw` px each, capped at HIST: a chart
// wider than the history kept would otherwise pad its left side with zeros forever (#40)
export function graphCols(w, bw = 2) {
  return Math.min(HIST, Math.max(1, Math.floor((w || 0) / bw)));
}
const cpuHist = [], ramHist = [], netDownHist = [], netUpHist = [], dioHist = [];
const coreHist = [];   // per-core %, coreHist[i] = that core's history

const HOT = 90;
const WINDOW = 80;   // samples a vitals line shows: two minutes at 1.5s, so a fresh page fills in two
const isHot = v => v != null && v >= HOT;
const clamp = v => Math.max(0, Math.min(100, Number(v) || 0));
export function pct(v) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  const n = Number(v);
  return `${n > 0 && n < 10 ? n.toFixed(1) : Math.round(n)}%`;
}

// macOS lists its sealed system volumes (/System/Volumes/*) beside /, all on one container: same
// size, same free space. one row per container, none of apple's internals
export function storageVolumes(disks = []) {
  const seen = new Set();
  return (disks || []).filter(d => {
    if (String(d?.mount || '').startsWith('/System/Volumes/')) return false;
    const key = `${d?.total_gb}|${d?.free_gb}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// how full a disk is: all that isn't free. psutil's percent counts only the volume's own files,
// so an apfs / read 18% on a container that was 88% full
export function diskFullness(d) {
  if (d?.total_gb > 0 && d.free_gb != null) return clamp((1 - d.free_gb / d.total_gb) * 100);
  return d?.percent == null ? null : clamp(d.percent);
}

export function procCpu(cpu) {
  if (cpu == null || cpu === '') return '—';
  const n = Number(cpu);
  return Number.isFinite(n) ? `${Math.round(n)}%` : '—';
}

function _window(hist, n) {
  if (!hist || !hist.length) return new Array(n).fill(0);
  if (hist.length >= n) return hist.slice(hist.length - n);
  return new Array(n - hist.length).fill(0).concat(hist);
}

// a live line: the newest sample on the right edge, a faint fill under it and a baseline so a
// fresh chart still reads as one. colors come from the canvas's css, so both themes hold
function drawLine(canvas, series, max) {
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
  const css = getComputedStyle(canvas);
  // until the window fills, the samples there are span the whole width: a fresh page shows a
  // line from the first seconds instead of a sliver at the right edge of an empty box
  const longest = Math.max(0, ...series.map(s => s.hist.length));
  const n = Math.max(2, Math.min(WINDOW, graphCols(w, 3), longest));
  canvas.dataset.cols = n;
  ctx.strokeStyle = css.getPropertyValue('--srv-baseline').trim() || css.color;
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, h - 0.5); ctx.lineTo(w, h - 0.5); ctx.stroke();
  const windows = series.map(s => _window(s.hist, n));
  const top = max || Math.max(1, ...windows.flat());
  const x = i => n > 1 ? (i / (n - 1)) * w : w;
  const y = v => h - 1 - (Math.min(Math.max(v, 0), top) / top) * (h - 4);
  series.forEach((s, k) => {
    const have = Math.min(s.hist.length, n);
    if (have < 2) return;
    const data = windows[k], start = n - have;
    const color = css.getPropertyValue(s.color).trim() || css.color;
    ctx.beginPath();
    for (let i = start; i < n; i++) { if (i === start) ctx.moveTo(x(i), y(data[i])); else ctx.lineTo(x(i), y(data[i])); }
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.lineJoin = 'round'; ctx.setLineDash(s.dash || []);
    ctx.stroke();
    ctx.setLineDash([]);
    if (s.fill === false) return;
    ctx.lineTo(x(n - 1), h); ctx.lineTo(x(start), h); ctx.closePath();
    ctx.globalAlpha = 0.08; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1;
  });
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
const fmtMem = b => (b >= 1073741824) ? `${(b / 1073741824).toFixed(1)} GB` : `${Math.round((b || 0) / 1048576)} MB`;

// a bar that says how full something is; its words sit beside it, so the bar itself is a meter
function bar(value, label) {
  const v = value == null ? 0 : clamp(value);
  return `<span class="srv-bar${isHot(value) ? ' is-hot' : ''}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(v)}" aria-label="${esc(label)}"><span style="--srv-fill:${v.toFixed(1)}%"></span></span>`;
}

function rows(pairs) {
  return pairs.filter(pair => pair && pair[1] != null && pair[1] !== '').map(([k, v]) => `<div class="srv-row"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
}

export function browserClientInfo(source = globalThis.navigator || {}, timeZone = '') {
  const platformValue = String(source.userAgentData?.platform || source.platform || 'unknown');
  const userAgent = String(source.userAgent || '');
  const identity = `${platformValue} ${userAgent}`.toLowerCase();
  let platform = platformValue || 'unknown';
  if (identity.includes('android')) platform = 'Android';
  else if (identity.includes('iphone')) platform = 'iOS';
  else if (identity.includes('ipad')) platform = 'iPadOS';
  else if (identity.includes('win')) platform = 'Windows';
  else if (identity.includes('mac')) platform = 'macOS';
  else if (identity.includes('linux')) platform = 'Linux';
  const language = String(source.language || 'unknown');
  let zone = String(timeZone || '');
  if (!zone) {
    zone = resolvedTimeZone();
  }
  return { platform, language, timezone: zone };
}
function uptime(sec) {
  if (!sec) return '—';
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return (d ? `${t('server.system_days', { count: d })} ` : '') + (h ? `${t('server.system_hours', { count: h })} ` : '') + t('server.system_minutes', { count: m });
}

// the frame is built once and only its contents change on each tick, so nothing flashes
function buildShell(s) {
  const note = s.live ? '' : `<div class="sys-note">${esc(t('server.system_psutil_note'))}</div>`;
  const vital = (id, label, chart) => `
        <div class="srv-vital" id="box-${id}">
          <span class="srv-vital-label">${esc(label)}</span>
          <strong class="srv-vital-value" id="v-${id}"></strong>
          <span class="srv-vital-sub" id="v-${id}-sub"></span>
          ${chart ? `<canvas class="srv-chart" id="${chart}" aria-hidden="true"></canvas>` : `<span class="srv-vital-bar" id="v-${id}-bar"></span>`}
        </div>`;
  const card = (id, title, body, extra = '') => `
        <section class="srv-card" id="${id}" aria-labelledby="${id}-title">
          <div class="srv-card-head"><h2 id="${id}-title">${esc(title)}</h2>${extra}</div>${body}
        </section>`;
  $('system-body').innerHTML = `${note}
    <div id="sys-shell" class="srv">
      <div class="srv-card srv-vitals">${vital('cpu', t('server.system_cpu'), 'cpu-graph')}${vital('mem', t('server.system_memory'), 'mem-graph')}${vital('disk', t('server.overview_storage'), '')}${vital('net', t('server.overview_network'), 'net-graph')}
      </div>
      <div class="srv-row3">${card('srv-cores', t('server.overview_cores'), '<div class="srv-cores" id="cpu-cores"></div>', '<span class="srv-card-meta" id="srv-load"></span>')}${card('srv-memory', t('server.system_memory'), '<div id="mem-lines"></div>')}${card('srv-storage', t('server.overview_storage'), '<div id="disk-body"></div>')}
      </div>
      <div class="srv-card srv-procs" id="box-proc">
        <div class="srv-card-head"><h2 id="box-proc-title">${esc(t('server.overview_processes'))}</h2><span class="srv-card-meta" id="srv-procs-count"></span></div>
        <div class="srv-table-wrap" id="proc-body" role="region" aria-labelledby="box-proc-title" tabindex="0"></div>
      </div>
      <div class="srv-pair">${card('srv-machine', t('server.overview_machine'), '<dl class="srv-list srv-list-2" id="nf-info"></dl>')}${card('srv-browser', t('server.overview_browser'), '<dl class="srv-list" id="srv-client"></dl>')}
      </div>
    </div>`;
}

async function loadManagedSearxng(fetcher = fetch) {
  const statusEl = $('server-searxng-status');
  const actions = $('server-searxng-actions');
  if (!statusEl || !actions) return;
  try {
    const response = await fetcher('/api/system/searxng');
    if (!response.ok) throw new Error(t('server.system_health_unavailable'));
    const service = await response.json();
    const runtime = service.available ? service.docker_version ? t('server.system_docker_version', { version: service.docker_version }) : t('server.system_docker_ready') : t('server.system_docker_unavailable');
    const state = !service.support_verified && !service.installed ? t('server.system_managed_unavailable') : !service.installed ? t('server.system_not_installed') : !service.owned ? t('server.system_ownership_failed') : service.healthy ? t('server.system_healthy') : service.running ? t('server.system_unhealthy') : t('server.system_stopped');
    statusEl.textContent = `${state} · ${runtime} · ${service.bind} · ${service.version} · ${service.license}`;
    const buttons = [];
    if (!service.installed && service.support_verified) buttons.push(['install', t('server.system_install')]);
    if (service.installed && service.owned) {
      buttons.push([service.running ? 'stop' : 'start', service.running ? t('server.system_stop') : t('server.system_start')]);
      buttons.push(['restart', t('server.system_restart')], ['test', t('server.system_test_search')], ['update', t('server.system_safe_update')], ['rollback', t('server.system_rollback')], ['uninstall', t('server.system_uninstall_keep')]);
    }
    actions.innerHTML = buttons.map(([action, label]) => `<button class="btn" type="button" data-searxng-action="${action}"${!service.available && action !== 'uninstall' ? ' disabled' : ''}>${label}</button>`).join('');
  } catch (error) {
    statusEl.textContent = t('server.system_external_remain', { reason: plainError(error.message) });
    actions.replaceChildren();
  }
}

async function manageSearxng(action, button) {
  if (action === 'uninstall' && !await confirmDialog(t('server.system_uninstall_confirm'))) return;
  button.disabled = true;
  const statusEl = $('server-searxng-status');
  if (statusEl) statusEl.textContent = t('server.system_in_progress', { action: t(`server.system_act_${action}`) });
  const path = `/api/system/searxng/${action}`;
  try {
    const response = await fetch(path, { method: 'POST' });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || t('server.system_action_failed', { action: t(`server.system_act_${action}`) }));
    if (statusEl && action === 'test') statusEl.textContent = tp('server.system_json_passed', body.results);
    else await loadManagedSearxng();
  } catch (error) {
    if (statusEl) statusEl.textContent = plainError(error.message);
  } finally { button.disabled = false; }
}

function setText(id, text) { const el = $(id); if (el && el.textContent !== text) el.textContent = text; }
function setHot(id, value) { $(id)?.classList.toggle('is-hot', isHot(value)); }

function render(s, fetcher = fetch) {
  if (!$('sys-shell')) buildShell(s);
  if ([t('server.system_checking'), 'checking…'].includes($('server-searxng-status')?.textContent)) loadManagedSearxng(fetcher);
  if (s.cpu.percent != null) push(cpuHist, s.cpu.percent);
  push(ramHist, s.memory.percent);
  push(netDownHist, (s.net?.down_bps || 0));
  push(netUpHist, (s.net?.up_bps || 0));
  push(dioHist, (s.disk_io?.read_bps || 0) + (s.disk_io?.write_bps || 0));
  (s.cpu.per_core || []).forEach((c, i) => { if (!coreHist[i]) coreHist[i] = []; push(coreHist[i], c); });

  const cpu = s.cpu, mem = s.memory, sw = s.swap, net = s.net || {}, io = s.disk_io || {}, h = s.host || {};
  // some chips report a placeholder clock (0 or a few mhz); "0.00 GHz" says nothing true
  const ghz = cpu.freq_mhz >= 100 ? `${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : '';
  const volumes = storageVolumes(s.disks);
  const main = volumes[0];
  const load = s.load ? s.load.map(x => x.toFixed(2)).join(' · ') : '';

  const hostEl = $('system-host');
  if (hostEl) {
    hostEl.textContent = s.live ? tp('server.system_live_procs', s.proc_count || 0) : t('server.system_live_unavailable');
    hostEl.dataset.state = s.live ? 'live' : 'static';
  }

  // vitals
  setText('v-cpu', pct(cpu.percent)); setHot('v-cpu', cpu.percent);
  setText('v-cpu-sub', tp('server.overview_cpu_sub', cpu.cores || 0, { load: s.load ? s.load[0].toFixed(2) : '—' }));
  drawLine($('cpu-graph'), [{ hist: cpuHist }], 100);
  setText('v-mem', pct(mem.percent)); setHot('v-mem', mem.percent);
  setText('v-mem-sub', t('server.overview_of_gb', { used: mem.used_gb, total: mem.total_gb }));
  drawLine($('mem-graph'), [{ hist: ramHist }], 100);
  const full = main ? diskFullness(main) : null;
  setText('v-disk', pct(full)); setHot('v-disk', full);
  setText('v-disk-sub', main ? t('server.overview_free_of', { free: main.free_gb, total: main.total_gb }) : t('server.system_no_disks'));
  const diskBar = $('v-disk-bar');
  if (diskBar) diskBar.innerHTML = main ? bar(full, main.mount) : '';
  const netValue = $('v-net');
  if (netValue) {
    const label = t('server.overview_down', { rate: fmtRate(net.down_bps) });
    // the unit sits smaller beside the number, so a rate never wraps onto a second line
    const [num, unit] = fmtRate(net.down_bps).split(' ');
    const html = `${_si('arrow-down')}<span>${esc(num)}</span><small>${esc(unit || '')}</small>`;
    if (netValue.dataset.html !== html) { netValue.innerHTML = html; netValue.dataset.html = html; }
    netValue.setAttribute('aria-label', label);
  }
  setText('v-net-sub', [t('server.overview_up', { rate: fmtRate(net.up_bps) }), net.iface].filter(Boolean).join(' · '));
  drawLine($('net-graph'), [{ hist: netDownHist }, { hist: netUpHist, color: '--srv-second', dash: [3, 3], fill: false }], 0);

  // cores
  setText('srv-load', load ? `${t('server.system_load')} ${load}` : '');
  const cores = cpu.per_core || [];
  $('cpu-cores').innerHTML = cores.map((c, i) => {
    const name = t('server.overview_core', { n: i + 1 });
    return `<div class="srv-core"><span class="srv-core-id" aria-hidden="true">${i + 1}</span>${bar(c, name)}<span class="srv-num${isHot(c) ? ' is-hot' : ''}">${pct(c)}</span></div>`;
  }).join('') || `<p class="srv-empty">${esc(t('server.system_no_proc_details'))}</p>`;

  // memory: one bar of what's in use, then what's left and swap
  $('mem-lines').innerHTML =
    `<div class="srv-meter-head"><span>${esc(t('server.overview_of_gb', { used: mem.used_gb, total: mem.total_gb }))}</span><span class="srv-num${isHot(mem.percent) ? ' is-hot' : ''}">${pct(mem.percent)}</span></div>` +
    bar(mem.percent, t('server.system_memory')) +
    `<dl class="srv-list">${rows([
      [t('server.system_avail'), mem.available_gb != null ? `${mem.available_gb} GB` : null],
      [t('server.system_cached'), mem.cached_gb ? `${mem.cached_gb} GB` : null],
      [t('server.system_free'), mem.free_gb != null ? `${mem.free_gb} GB` : null],
      [t('server.system_swap'), sw && sw.total_gb ? t('server.overview_of_gb', { used: sw.used_gb, total: sw.total_gb }) : null],
    ])}</dl>`;

  // storage: one bar per container, filled by what isn't free
  $('disk-body').innerHTML =
    (volumes.map(d => {
      const used = diskFullness(d);
      return `<div class="srv-volume"><div class="srv-meter-head"><span class="srv-mount">${esc(d.mount)}</span><span class="srv-num${isHot(used) ? ' is-hot' : ''}">${pct(used)}</span></div>` +
        bar(used, d.mount) +
        `<span class="srv-sub">${esc([t('server.overview_free_of', { free: d.free_gb, total: d.total_gb }), d.fstype].filter(Boolean).join(' · '))}</span></div>`;
    }).join('') || `<p class="srv-empty">${esc(t('server.system_no_disks'))}</p>`) +
    (io.read_bps != null ? `<p class="srv-sub srv-io">${esc(t('server.overview_io', { read: fmtRate(io.read_bps), write: fmtRate(io.write_bps) }))}</p>` : '');

  // processes, busiest first, as a real table
  const procs = s.procs || [];
  setText('srv-procs-count', procs.length ? t('server.overview_shown_of', { shown: procs.length, total: s.proc_count || procs.length }) : '');
  const head = [t('server.system_program'), t('server.system_cpu'), t('server.system_memory'), t('server.system_threads'), t('server.system_user'), t('server.system_pid')];
  $('proc-body').innerHTML = procs.length
    ? `<table class="srv-table"><thead><tr>${head.map(cell => `<th scope="col">${esc(cell)}</th>`).join('')}</tr></thead><tbody>${procs.map(p => `<tr>
        <td class="srv-proc-name">${esc(p.name)}</td>
        <td class="srv-num${isHot(p.cpu) ? ' is-hot' : ''}">${procCpu(p.cpu)}</td>
        <td class="srv-num">${fmtMem(p.rss)}</td>
        <td class="srv-num">${p.threads || ''}</td>
        <td>${esc(p.user || '')}</td>
        <td class="srv-num srv-quiet">${p.pid}</td>
      </tr>`).join('')}</tbody></table>`
    : `<p class="srv-empty">${esc(s.live ? t('server.system_no_proc_details') : t('server.system_proc_need_psutil'))}</p>`;

  // what the machine is, and what this browser is
  const client = browserClientInfo();
  $('nf-info').innerHTML = rows([
    [t('server.system_host'), h.hostname],
    [t('server.system_os'), [h.os, h.arch].filter(Boolean).join(' · ')],
    [t('server.system_cpu'), [cpu.name, cpu.cores ? tp('server.overview_cpu_cores', cpu.cores) : '', ghz].filter(Boolean).join(' · ')],
    [t('server.system_gpu'), s.gpu?.has ? [s.gpu.name, s.gpu.vram_gb ? `${s.gpu.vram_gb} GB` : ''].filter(Boolean).join(' · ') : t('server.system_none_detected')],
    [t('server.system_memory'), mem.total_gb != null ? `${mem.total_gb} GB` : null],
    [t('server.system_uptime'), uptime(s.uptime_sec)],
    [t('server.overview_procs'), s.proc_count ? String(s.proc_count) : null],
    [t('server.system_user'), h.user],
    [t('server.overview_python'), h.python],
    [t('server.system_backend'), h.backend],
  ]);
  $('srv-client').innerHTML = rows([
    [t('server.system_platform'), client.platform],
    [t('server.system_language'), client.language],
    [t('server.system_time_zone'), client.timezone],
  ]);
}

function push(arr, v) { arr.push(v); if (arr.length > HIST) arr.shift(); }

let _timer = null, _wired = false;
let _systemFetcher = fetch;
async function tick(fetcher = _systemFetcher) {
  const v = $('system-view');
  if (!v || v.style.display === 'none' || document.hidden) return;
  const gen = _sysGen;
  try {
    const r = await fetcher('/api/system/stats');
    if (!r.ok) { const failure = new Error(r.status === 404 ? t('server.system_route_missing') : t('server.system_server_returned', { status: r.status })); failure.restart = r.status === 404; throw failure; }
    const s = await r.json();
    if (!s || !s.cpu || !s.memory) { const failure = new Error(t('server.system_unexpected')); failure.restart = true; throw failure; }
    if (gen !== _sysGen || v.style.display === 'none') return;
    render(s, fetcher);
  } catch (e) {
    if (gen !== _sysGen || v.style.display === 'none') return;
    const host = $('system-host');
    if (host) { host.textContent = t('common.unavailable'); host.dataset.state = 'unavailable'; }
    const b = $('system-body');
    if (b) {
      const restart = e.restart
        ? ` ${esc(t('server.system_restart_hint', { command: '@@cmd@@' })).replace('@@cmd@@', '<code>python cli.py restart</code>')}`
        : '';
      b.innerHTML = `<div class="sys-note" role="status">${esc(t('server.system_read_failed', { reason: e.message, restart: '@@restart@@' })).replace('@@restart@@', restart)}</div>`;
    }
  }
}

let _sysGen = 0;
export async function initSystem(fetcher = fetch) {
  const gen = ++_sysGen;
  _systemFetcher = fetcher;
  const host = $('system-host');
  if (host) { host.textContent = t('server.system_loading'); host.dataset.state = 'loading'; }
  $('system-body').innerHTML = `<div class="g-dim" style="padding:1rem">${esc(t('server.system_reading'))}</div>`;
  if (_timer) { clearInterval(_timer); _timer = null; }
  void tick(fetcher);
  _timer = setInterval(() => tick(_systemFetcher), 1500);
  if (!_wired) {
    _wired = true;
    document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(_systemFetcher); });
    $('system-body')?.addEventListener('click', event => {
      const button = event.target.closest('[data-searxng-action]');
      if (button) manageSearxng(button.dataset.searxngAction, button);
    });
  }
  void (async () => {
    let ms = 1500;
    try { ms = Math.max(250, Number((await fetcher('/api/settings').then(r => r.json())).system_refresh) || 1500); } catch {}
    if (gen !== _sysGen || ms === 1500) return;
    if (_timer) clearInterval(_timer);
    _timer = setInterval(() => tick(_systemFetcher), ms);
  })();
}
