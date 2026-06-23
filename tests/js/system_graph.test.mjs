// unit tests for the system graph column-count fix (#40). a graph must never ask for more
// columns than HIST history slots, or the extra left columns stay permanently blank ("a
// third didn't finish") on wide screens.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { graphCols, HIST } from '../../static/js/system.js';

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
