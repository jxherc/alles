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
