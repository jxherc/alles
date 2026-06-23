# system — audit findings (2026-06-18)

Drove `system.localhost:8799` (uses `domcontentloaded` — the monitor polls continuously so `networkidle`
never settles). Live stats, cpu/mem/net/disk graphs, and the process list all render and update. Zero
console errors. Before/after screenshots saved.

## The imbalance (confirmed, Image #5: "the bottom shapes are different")
On desktop (≥860px) the layout is: full-width cpu graph on top, then a row of the left graph stack
(mem + net + disk) beside the processes box. The left stack measured **609px** tall while `#box-proc` was
capped at **max-height:560px** → the left column hung **49px below** the proc column (`.btop-cols` used
`align-items:flex-start`). Uneven bottom edge.

## Fix (`system-ui-1`, style.css only — behavior untouched)
`.btop-cols` (≥860px): `align-items:flex-start` → **`align-items:stretch`**, and `#box-proc` drops its
`max-height:560px` (→ `max-height:none; min-height:0`). The proc box (which has **no canvas**, just a
scrollable `flex:1` list) stretches to match the left graph stack's height, giving the two columns a flush
bottom. The left graphs keep their **fixed** pixel heights (cpu 130 / mem 64 / net 50+50 / disk 96) so no
canvas runaway — only the proc column flexes.

**Verify (`pw_system_balance.py`, 7 assertions, screenshot, 0 console err):** columns_same_height (±3),
bottoms_flush (±3), proc_renders_rows (≥10, behavior intact), cpu/mem/disk graphs still have their heights,
zero_console_errors.

---

# system — re-audit (2026-06-23): graphs never finish filling on wide screens (#40)

## bug (high)
the live graphs (drawGraph) use one canvas column per ~2px of width: `n = floor(w/2)`. but
history is capped at `HIST = 720` samples. when a graph is wider than ~1440px, `n > 720`, so
`_window(hist, n)` left-pads with zeros for the `(n-720)` columns it can never fill — that
left strip stays BLANK forever. the cpu graph is full-width (span2), so it's the worst hit.

measured live (psutil active) via playwright:
- vw=1920: cpu-graph 1827px -> n=913 cols, 193 cols (21%) permanently empty on the left
- vw=2560: cpu-graph 2467px -> n=1233 cols, 513 cols (42%) permanently empty on the left
at ~2200px the empty strip is ~1/3 — exactly the user's "a third didn't finish running". the
graph appears to fill in from the right and stop short, looking unfinished/"reset".

root cause: `HIST` (720) < the column count of a wide graph. fix: cap the column count to the
history we actually keep and stretch the bar pitch to fill the box, so the graph always fills
its full width (no permanent dead zone) regardless of screen width.

## RESOLVED (#40)
extracted `graphCols(w)` = min(HIST, floor(w/2)) (exported, unit-tested) and used it in
drawGraph; bar pitch is now `w/n` so the bars stretch to fill the full box width. a graph
never asks for more columns than HIST history slots, so once the buffer fills it covers the
whole width with no permanent dead zone. verified live at vw=2560: cpu-graph cols 1233 -> 720,
pitch 3.43px, full-width. tests: tests/js/system_graph.test.mjs (8) + test_api_system 10/10.
