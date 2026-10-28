// unit tests for the system graph column-count fix (#40). a graph must never ask for more
// columns than HIST history slots, or the extra left columns stay permanently blank ("a
// third didn't finish") on wide screens.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  browserClientInfo,
  diskFullness,
  graphCols,
  HIST,
  pct,
  procCpu,
  storageVolumes,
} from '../../static/js/system.js';

const SYSTEM_CSS = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const SYSTEM_SOURCE = readFileSync(new URL('../../static/js/system.js', import.meta.url), 'utf8');

test('HIST is the history cap', () => {
  assert.equal(HIST, 720);
});

test('below the cap, columns track the width (one per 2px)', () => {
  assert.equal(graphCols(300), 150);
  assert.equal(graphCols(600), 300);
  assert.equal(graphCols(1000), 500);
});

test('exactly at the cap width', () => {
  assert.equal(graphCols(1440), 720);   // floor(1440/2) == HIST
});

test('never exceeds HIST — the bug: wide graphs used to ask for >720 columns', () => {
  for (const w of [1441, 1827, 2467, 3000, 3840, 8000]) {
    assert.ok(graphCols(w) <= HIST, `w=${w} gave ${graphCols(w)} > ${HIST}`);
  }
});

test('the measured failing widths now cap to HIST (were 913 / 1233)', () => {
  assert.equal(graphCols(1827), 720);   // vw=1920 cpu graph
  assert.equal(graphCols(2467), 720);   // vw=2560 cpu graph
});

test('at least 1 column for tiny/degenerate widths', () => {
  assert.equal(graphCols(1), 1);
  assert.equal(graphCols(0), 1);
  assert.equal(graphCols(-50), 1);
});

test('non-decreasing in width', () => {
  let prev = 0;
  for (let w = 0; w <= 4000; w += 137) {
    const n = graphCols(w);
    assert.ok(n >= prev, `dropped at w=${w}`);
    prev = n;
  }
});

test('full fill: a buffer of HIST samples covers every column (no permanent dead zone)', () => {
  // once history >= columns, _window returns no zero-padding -> every column has data.
  // graphCols caps columns to HIST, so a full buffer always covers the whole width.
  for (const w of [1827, 2467, 3840]) {
    const n = graphCols(w);
    assert.ok(HIST >= n, `w=${w}: HIST(${HIST}) < cols(${n}) would leave ${n - HIST} blank cols`);
  }
});

test('process cpu tolerates missing samples', () => {
  assert.equal(procCpu(null), '—');
  assert.equal(procCpu(undefined), '—');
  assert.equal(procCpu(7.4), '7%');
});

test('percent values keep one decimal only under 10', () => {
  assert.equal(pct(null), '—');
  assert.equal(pct(0), '0%');
  assert.equal(pct(7.34), '7.3%');
  assert.equal(pct(66.8), '67%');
});

// macOS lists its sealed system volumes beside /, all on one apfs container
const APFS = [
  { mount: '/', total_gb: 494.4, used_gb: 13.7, free_gb: 60.8, percent: 18.3, fstype: 'apfs' },
  { mount: '/System/Volumes/VM', total_gb: 494.4, used_gb: 7.5, free_gb: 60.8, percent: 11, fstype: 'apfs' },
  { mount: '/System/Volumes/xarts', total_gb: 0.5, used_gb: 0, free_gb: 0.5, percent: 1.2, fstype: 'apfs' },
  { mount: '/Volumes/Backup', total_gb: 2000, used_gb: 500, free_gb: 1500, percent: 25, fstype: 'apfs' },
];

test('storage shows one row per container and none of apple\'s internal volumes', () => {
  assert.deepEqual(storageVolumes(APFS).map(d => d.mount), ['/', '/Volumes/Backup']);
  const linux = [
    { mount: '/', total_gb: 100, free_gb: 40 },
    { mount: '/home', total_gb: 100, free_gb: 40 },
    { mount: '/data', total_gb: 900, free_gb: 100 },
  ];
  assert.deepEqual(storageVolumes(linux).map(d => d.mount), ['/', '/data']);
  assert.deepEqual(storageVolumes(undefined), []);
});

test('a disk is as full as everything that is not free', () => {
  // psutil said 18% for an apfs / whose container had 60.8 of 494.4 GB free
  assert.equal(Math.round(diskFullness(APFS[0])), 88);
  assert.equal(diskFullness({ percent: 42 }), 42);
  assert.equal(diskFullness({}), null);
});

test('browser identity stays explicitly client-side across major platforms', () => {
  const fixtures = [
    [{ platform: 'Win32', language: 'en-US', userAgent: 'Mozilla/5.0 Windows NT 10.0' }, 'Windows'],
    [{ platform: 'MacIntel', language: 'en-TW', userAgent: 'Mozilla/5.0 Macintosh' }, 'macOS'],
    [{ platform: 'Linux x86_64', language: 'fr-FR', userAgent: 'Mozilla/5.0 X11 Linux' }, 'Linux'],
  ];
  for (const [navigatorLike, expected] of fixtures) {
    assert.deepEqual(browserClientInfo(navigatorLike, 'Asia/Taipei'), {
      platform: expected,
      language: navigatorLike.language,
      timezone: 'Asia/Taipei',
    });
  }
});

// the overview reads like the rest of alles: the shared type, tabular figures, no terminal
// glyphs, and nothing that moves on its own (principle 17)
test('the server overview uses the shared type and has no decorative loop', () => {
  assert.doesNotMatch(SYSTEM_CSS, /logo-cycle|logo-pulse|logo-shimmer|sys-blink|hot-pulse|\.nf-logo|\.btop-/);
  assert.match(SYSTEM_CSS, /#system-body \.srv \{[^}]*font-family: var\(--k-font\)/);
  assert.doesNotMatch(SYSTEM_SOURCE, /[░█├└]/);
  assert.match(SYSTEM_SOURCE, /role="meter"/);
});

test('system refreshes keep using the scoped specialist fetcher', () => {
  assert.match(SYSTEM_SOURCE, /let _systemFetcher = fetch/);
  assert.match(SYSTEM_SOURCE, /_systemFetcher = fetcher/);
  assert.match(SYSTEM_SOURCE, /setInterval\(\(\) => tick\(_systemFetcher\), ms\)/);
  assert.match(SYSTEM_SOURCE, /visibilitychange[^]*tick\(_systemFetcher\)/);
});

test('managed SearXNG lifecycle actions use the health-aware endpoint', () => {
  assert.match(SYSTEM_SOURCE, /`\/api\/system\/searxng\/\$\{action\}`/);
  assert.doesNotMatch(SYSTEM_SOURCE, /`\/api\/system\/services\/searxng\/\$\{action\}`/);
});
