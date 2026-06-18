# export / import buttons — audit findings (2026-06-18)

Audited every export/import/upload control (calendar, money, contacts, docs, files, photos).

## The inconsistency (confirmed)
Export controls are `<a class="btn" download>` while imports are `<button class="btn">`. `.btn` set no
`text-decoration`, so the browser default underlined every export anchor — `export` rendered underlined
next to a plain `import`, and the `<a>`/`<button>` box models drifted slightly. That's the user's "they
look different and uncomfortable / not unified".

## Fix (`io-ui-1`, markup/CSS only)
`.btn`: add `text-decoration:none` (export links now match import buttons exactly) + `display:inline-block`
+ `box-sizing:border-box` + `vertical-align:middle` so `<a>` and `<button>` size identically. Intentionally
distinct controls left alone (backup = `btn primary` full-width CTA; session = icon-btn; the docs `export ▾`
keeps its caret since it opens a menu).

**Verify (`pw_io_unify.py`, 10 assertions, screenshot, 0 console err):** for calendar / money / contacts —
`<exportTag>`/`<importTag>` are both `.btn`, export `text-decoration:none` (no underline), and the pair has
identical height (±1px).
