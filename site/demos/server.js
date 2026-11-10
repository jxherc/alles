// the server app's overview, as in shots/server.webp: live numbers, cores, memory and storage,
// plus the backups and updates tabs. every number is made up
import { h, ic, css, topbar, walk, spark, sparkSvg, live, toast } from './kit.js';

export default function build(root) {
  css('server');
  let cpu = 14, mem = 67, down = 16, up = 22, procs = 904;
  const cores = [39, 34, 20, 15, 7.4, 5.4, 6.6, 6.0, 4.0, 4.0];
  const hist = { cpu: [], mem: [], net: [] };
  for (let i = 0; i < 30; i++) {
    cpu = walk(cpu, 10, 4, 38); mem = walk(mem, 1.2, 60, 72); down = walk(down, 14, 2, 60);
    hist.cpu.push(cpu); hist.mem.push(mem); hist.net.push(down);
  }

  const liveBtn = h('button', { type: 'button', class: 'sv-live', 'aria-pressed': 'true' }, h('span', { class: 'sv-word', text: 'live' }), ' · ', h('span', { class: 'sv-procs' }), ' processes');
  const stat = (label, k) => h('div', { class: 'sv-stat', 'data-k': k }, h('span', { class: 'dm-muted', text: label }), h('strong', { class: 'sv-val' }), h('span', { class: 'sv-sub dm-muted' }), k === 'disk' ? h('span', { class: 'sv-bar' }, h('i', { style: 'width: 84%' })) : sparkSvg());
  const stats = h('div', { class: 'sv-stats dm-panel' }, stat('cpu', 'cpu'), stat('memory', 'mem'), stat('storage', 'disk'), stat('network', 'net'));
  const coreRows = cores.map((v, i) => h('div', { class: 'sv-core' }, h('span', { class: 'dm-muted', text: String(i + 1) }), h('span', { class: 'sv-bar' }, h('i')), h('span', { class: 'sv-pct' })));
  const coresPanel = h('div', { class: 'dm-panel sv-cores' }, h('div', { class: 'sv-head' }, h('span', { class: 'dm-h', text: 'cores' }), h('span', { class: 'dm-muted sv-loadline' })), h('div', { class: 'sv-grid' }, coreRows));
  const memPanel = h('div', { class: 'dm-panel' }, h('div', { class: 'sv-head' }, h('span', { class: 'dm-h', text: 'memory' })),
    h('div', { class: 'sv-line' }, h('span', { class: 'sv-memline' }), h('span', { class: 'sv-mempct dm-muted' })), h('span', { class: 'sv-bar sv-wide' }, h('i', { class: 'sv-membar' })),
    h('p', { class: 'sv-fact' }, h('span', { class: 'dm-muted', text: 'available' }), h('span', { class: 'sv-avail' })),
    h('p', { class: 'sv-fact' }, h('span', { class: 'dm-muted', text: 'free' }), h('span', { text: '0.2 GB' })));
  const diskPanel = h('div', { class: 'dm-panel' }, h('div', { class: 'sv-head' }, h('span', { class: 'dm-h', text: 'storage' })),
    h('div', { class: 'sv-line' }, h('span', { text: '/' }), h('span', { class: 'dm-muted', text: '84%' })), h('span', { class: 'sv-bar sv-wide' }, h('i', { style: 'width: 84%' })),
    h('p', { class: 'dm-muted sv-note', text: '80.7 GB free of 494.4 GB · apfs' }),
    h('p', { class: 'dm-muted sv-note sv-io' }));
  const overview = h('div', { class: 'sv-panel', 'data-tab': 'overview' }, h('div', { class: 'sv-liverow' }, liveBtn), stats, h('div', { class: 'sv-row' }, coresPanel, memPanel, diskPanel));

  // backups: the steps the real webdav card shows
  const status = h('p', { class: 'sv-status dm-soft', role: 'status' });
  const last = h('strong', { text: 'yesterday, 3:12 am' });
  const verified = h('strong', { text: 'yesterday, 3:12 am' });
  const run = h('button', { type: 'button', class: 'dm-btn', text: 'run encrypted backup' });
  run.addEventListener('click', () => {
    run.disabled = true;
    status.textContent = 'creating encrypted backup…';
    setTimeout(() => {
      const d = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      const stamp = `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
      status.textContent = `backup complete · alles-backup-${stamp}-${Math.random().toString(16).slice(2, 6)}.alles-backup`;
      last.textContent = 'just now';
      verified.textContent = 'just now';
      run.disabled = false;
    }, 1800);
  });
  const fact = (k, v) => h('p', { class: 'sv-fact' }, h('span', { class: 'dm-muted', text: k }), typeof v === 'string' ? h('strong', { text: v }) : v);
  const backups = h('div', { class: 'sv-panel sv-cards', 'data-tab': 'backups and storage', hidden: true },
    h('div', { class: 'dm-panel' }, h('p', { class: 'dm-h sv-title', text: 'webdav' }), fact('configured', 'yes'), fact('last backup', last), fact('last verified', verified), status, run),
    h('div', { class: 'dm-panel' }, h('p', { class: 'dm-h sv-title', text: 'automatic local backup' }), fact('enabled', 'yes'), fact('last success', 'today, 3:00 am')));

  // updates: the release card, and a check that answers the way the app does when nothing is waiting
  const check = h('button', { type: 'button', class: 'dm-btn', text: 'check now' });
  const upd = h('strong', { text: 'up to date' });
  check.addEventListener('click', () => {
    upd.textContent = 'checking…';
    setTimeout(() => { upd.textContent = 'up to date'; toast(root, 'you have the newest release'); }, 900);
  });
  const updates = h('div', { class: 'sv-panel sv-cards', 'data-tab': 'updates', hidden: true },
    h('div', { class: 'dm-panel' }, h('p', { class: 'dm-h sv-title', text: 'release and update status' }), fact('release', '4e1d9b2 · installed nov 8, 9:41 pm'), fact('updates', upd), check));

  const panels = [overview, backups, updates];
  const bar = topbar({
    app: 'server',
    tabs: ['overview', 'backups and storage', 'updates'],
    selected: 'overview',
    onTab: (name) => panels.forEach((p) => { p.hidden = p.dataset.tab !== name; }),
  });
  root.append(bar.el, ...panels);

  const paint = () => {
    const card = (k) => stats.querySelector(`[data-k="${k}"]`);
    card('cpu').querySelector('.sv-val').textContent = Math.round(cpu) + '%';
    card('cpu').querySelector('.sv-sub').textContent = `10 cores · load ${(cpu / 6 + 0.4).toFixed(2)}`;
    card('mem').querySelector('.sv-val').textContent = Math.round(mem) + '%';
    const used = ((mem / 100) * 25.8).toFixed(1);
    card('mem').querySelector('.sv-sub').textContent = `${used} of 25.8 GB`;
    card('disk').querySelector('.sv-val').textContent = '84%';
    card('disk').querySelector('.sv-sub').textContent = '80.7 GB free of 494.4 GB';
    card('net').querySelector('.sv-val').replaceChildren(ic('arrow-down'), ` ${down.toFixed(1)} `, h('small', { text: 'KiB/s' }));
    card('net').querySelector('.sv-sub').textContent = `up ${up.toFixed(1)} KiB/s · en1`;
    spark(card('cpu').querySelector('.dm-spark'), hist.cpu, 100);
    spark(card('mem').querySelector('.dm-spark'), hist.mem, 100);
    spark(card('net').querySelector('.dm-spark'), hist.net, 64);
    coreRows.forEach((row, i) => {
      row.querySelector('i').style.width = cores[i] + '%';
      row.querySelector('.sv-pct').textContent = cores[i] < 10 ? cores[i].toFixed(1) + '%' : Math.round(cores[i]) + '%';
    });
    root.querySelector('.sv-loadline').textContent = `load ${(cpu / 6 + 0.4).toFixed(2)} · ${(cpu / 5 + 1).toFixed(2)} · ${(cpu / 7 + 1).toFixed(2)}`;
    root.querySelector('.sv-memline').textContent = `${used} of 25.8 GB`;
    root.querySelector('.sv-mempct').textContent = Math.round(mem) + '%';
    root.querySelector('.sv-membar').style.width = mem + '%';
    root.querySelector('.sv-avail').textContent = (25.8 - used - 0.2).toFixed(1) + ' GB';
    root.querySelector('.sv-io').textContent = `read ${(down * 3).toFixed(1)} KiB/s · write ${(up * 9).toFixed(1)} KiB/s`;
    liveBtn.querySelector('.sv-procs').textContent = Math.round(procs);
  };
  const tick = () => {
    cpu = walk(cpu, 10, 4, 38); mem = walk(mem, 1.2, 60, 72); down = walk(down, 14, 2, 60); up = walk(up, 10, 2, 40); procs = walk(procs, 8, 880, 930);
    for (const [k, v] of [['cpu', cpu], ['mem', mem], ['net', down]]) { hist[k].push(v); hist[k].shift(); }
    for (let i = 0; i < cores.length; i++) cores[i] = walk(cores[i], 8, 1, 60);
    paint();
  };
  paint();
  const state = live(root, tick);
  const setLive = (on) => {
    state.on = on;
    liveBtn.setAttribute('aria-pressed', String(on));
    liveBtn.querySelector('.sv-word').textContent = on ? 'live' : 'paused';
  };
  setLive(state.on);
  liveBtn.addEventListener('click', () => setLive(!state.on));
}
