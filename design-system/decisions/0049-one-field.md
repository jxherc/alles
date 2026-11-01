# one field

folds 0035 (one field style) and 0045 (focus brightens the border) into one rule, and fixes what
0045 left behind.

## context

0045 made every focused text field draw a 1px inset ring (`kokuen.css`). about 15 fields were
still bare underlines with zero side padding (model picker search, andromeda follow up, docs
search and dialogs, journal tags, plan board search, the shell box, gallery prompt and others),
so the ring landed on the words. about 12 more had their own odd boxes (a 28px add field, inline
styled number boxes). `revamp.css` then turned the ring purple with a comment that still
described 0030's bottom line, against 0045's own words. the docs source editor, a full page
writing surface, got the purple box around the whole editor. `.date-input` and `.cal-quick` had
no visible focus at all, because a later underline rule cleared the ring. the owner hit it three
times (27.04, 28.13, 28.40) and picked the focus color after a demo (c.02): dim neutral.

## decision

- one field: 44px, 12px between the text and the edge, 8px corners, the `--k-field` fill and a
  1px `--k-field-ring` inset ring. one selector list in `revamp.css` ("one field") names every
  text field outside a wrapper-owned entry; a new field joins that list or uses `.k-field`.
- focus recolors that ring to `--k-field-focus`, the muted grey (#9d948a dark, #6a625a light),
  in `kokuen.css`. nothing else draws: no outline, no second line, no glow. date fields are in
  the same rule.
- an invalid field (`aria-invalid="true"`) keeps a danger ring at rest, and focus on it stays
  danger.
- wrapper-owned entries (composer, command search, mail chips, home capture, andromeda search,
  the specialist capture, page footer rows, plan board add, reminder add, the ask panel, aide
  code entry) keep their fields bare; the wrapper's own edge shows focus with the same dim
  neutral ring, no accent, no outer bloom.
- long form editors are surfaces, not fields: the docs source editor, the note title and body,
  and the journal text take no box. the caret is their focus.
- the accent override in `revamp.css` and its stale comment are gone. dead field css
  (`.mem-view-search-wrap`, `.mem-view-footer`, `.wiki-qs-input`, `.doc-ai-bar`) is gone.

## checks

- `tests/pw_kit_rules.py` (webkit, 4 sizes, both themes, every route and the kit page): every
  focused field has at least 8px between its text and the edge that lights up, and a field and
  its wrapper never both light up.
- `tests/test_kit_page.py`: no text field in the css has zero side padding unless it is in the
  wrapper-owned list or the long form list.
- contrast: the muted ring against the field fill and the page passes 3:1 in both themes (the
  251af50e check, `tests/js/kokuen_finished_surfaces.test.mjs`).

## kept

- `--k-field-focus: var(--muted)`.
- forced colors still restores a system highlight.
- actions, choices, sliders and color controls keep their own focus rings.
