# ui-7d — journal toolbar alignment

The journal toolbar's three controls were different heights: search input 31px / export 25px / lock
26px, with three different font sizes — a ragged row. Unified them.

`static/style.css`: one rule sizes `.jrnl-toolbar .jrnl-search` + `.jrnl-toolbar .btn` to `height:30px`
/ `font-size:0.74rem` / `box-sizing:border-box`; buttons inline-flex center their content; the search
input's leaked `.jrnl-tags` `margin-top` is zeroed so all three tops line up.

Tests: `tests/test_journal_toolbar.py` (3 CSS contract) + `docs/evidence/ui-7d/verify.py` (computed
heights all 30px and tops within 1px, 0 console errors).
