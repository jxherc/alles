// unit tests for the system graph column-count fix (#40). a graph must never ask for more
// columns than HIST history slots, or the extra left columns stay permanently blank ("a
// third didn't finish") on wide screens.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  browserClientInfo,
  graphCols,
  HIST,
  logoFor,
  logoGrid,
  logoPlatform,
  procCpuLabel,
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

test('process cpu label tolerates missing samples', () => {
  assert.equal(procCpuLabel(null), '  —');
  assert.equal(procCpuLabel(undefined), '  —');
  assert.equal(procCpuLabel(7.4), '  7');
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

test('darwin uses the macOS logo instead of matching the win suffix', () => {
  assert.match(logoFor('Darwin'), /KMMMMMMMMMMNWMMMMMMMMMM0/);
  assert.doesNotMatch(logoFor('Darwin'), /cllllllllllllllllll/);
});

test('linux gets the tux logo and an exact linux platform key', () => {
  assert.equal(logoPlatform('Linux'), 'linux');
  assert.match(logoFor('Linux'), /_nnnn_/);
  assert.doesNotMatch(logoFor('Linux'), /#####/);
});

test('logo grids measure the printed neofetch columns and rows', () => {
  assert.deepEqual(logoGrid('Darwin'), {
    columns: 30,
    rows: 17,
    rowHeightCh: 30 / 17,
  });
  assert.equal(logoFor('Darwin').split('\n')[0], "                    c.'");
  assert.equal(logoFor('Darwin').split('\n').at(-1), '       "cooc*"    "*coo\'');
});

test('system logos render in a square stage and square art canvas with reduced-motion support', () => {
  assert.match(SYSTEM_CSS, /\.nf-logo\s*\{[^}]*aspect-ratio:\s*1\s*;/s);
  assert.match(SYSTEM_CSS, /\.nf-logo-art\s*\{[^}]*aspect-ratio:\s*1\s*;/s);
  assert.match(SYSTEM_CSS, /\.nf-logo-glyphs\s*\{[^}]*logo-cycle/s);
  assert.match(SYSTEM_CSS, /prefers-reduced-motion:[^)]+\)[^{]*\{[^}]*\.nf-logo-glyphs/s);
  assert.doesNotMatch(SYSTEM_CSS, /\.nf-logo::before/);
});

test('the restored shimmer and pulse share one seamless animation timeline', () => {
  assert.match(SYSTEM_CSS, /repeating-linear-gradient\(90deg,[\s\S]*?480px\)/);
  assert.match(SYSTEM_CSS, /@keyframes logo-cycle\s*\{[\s\S]*?0%\s*\{[^}]*background-position:\s*0 0;[^}]*filter:/s);
  assert.match(SYSTEM_CSS, /50%\s*\{[^}]*background-position:\s*-240px 0;[^}]*filter:/s);
  assert.match(SYSTEM_CSS, /100%\s*\{[^}]*background-position:\s*-480px 0;[^}]*filter:/s);
  assert.doesNotMatch(SYSTEM_CSS, /logo-pulse|logo-shimmer/);
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
