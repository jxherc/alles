# export / import — unify (2026-06-18)

Evidence: `docs/evidence/exportimport/` (findings + screenshot).

## io-ui-1 — unify export/import/upload controls
Export controls were `<a class="btn" download>` and rendered underlined (browser default) next to plain
`<button class="btn">` imports — looked mismatched. Fix in `static/style.css` `.btn`: `text-decoration:none`
+ `display:inline-block` + `box-sizing:border-box` + `vertical-align:middle`, so every `<a class=btn>`
export renders pixel-identical to its `<button class=btn>` import sibling. Intentionally-distinct controls
(backup primary CTA, session icon-btn, docs `export ▾` menu) left alone.

**Verify (`pw_io_unify.py`, 10 assertions):** calendar / money / contacts export+import are both `.btn`,
export has no underline, and each pair is the same height (±1px); zero console errors.
