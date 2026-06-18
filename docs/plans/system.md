# system — UI/UX polish (2026-06-18)

Evidence: `docs/evidence/system/` (findings + before/after). The `system` monitor's behavior must not break;
this is a CSS-only alignment fix touching the proc column + row alignment (no canvas / no JS changes).

## system-ui-1 — flush bottom edge (left graph stack ↔ proc column)
On desktop the left stack (mem+net+disk = 609px) hung 49px below the `max-height:560px` proc column. Fix
(`static/style.css`): `.btop-cols { align-items: stretch }` + `#box-proc { max-height:none; min-height:0 }`
so the proc column (no canvas, scrollable list) stretches to match the left stack — flush bottoms. Left
graphs keep fixed heights (no canvas runaway). Verify `pw_system_balance.py` (7 assertions): columns_same_height,
bottoms_flush, proc_renders_rows + graphs intact + zero console errors.
