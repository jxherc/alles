# anti-slop rules

what makes a screen read as generated without thought, and what alles does instead. sources: the
owner's oct 27 bug list, paralect's "signs of ai slop in design" and uxdesign.cc's "how to
de-slopify your designs" (2026-09-29). check every rule before calling a ui change done; the qa
checklist's final pass points here.

## the owner's own calls (oct 27)

- one indicator per state. a focus line drawn over a field's border, or a hover that looks like
  the picked option, is two signals fighting. focus recolors the field's own edge (0045); hover
  only brightens a label, the pill alone means picked.
- notices that confirm something finish on their own: they clear after a few seconds and have a
  close button. only a notice that needs an action stays.
- a work page holds the work. settings (engine and model pickers, provider rows) live in
  settings, not above the results.
- every control has a reason to be there. a button that repeats what the layout already shows
  ("back to messages" beside the list, "browse" beside the tree) goes.
- no native tooltips as labels. if a control needs words, the words are on it.
- spacing follows the scale (0, 4, 8, 12, 16, 24, 32, 48, 64). nothing touches a divider or the
  page edge, and a hint never sits flush on the field under it.
- a long list is never open by default. it opens from a trigger that shows the current pick,
  takes typed letters, and closes on a pick.

## slop tells and what to do

| tell | instead |
| --- | --- |
| a border around every section, row and nested box | group with spacing and headings; border only what is selected or a form field |
| a colored stripe on one side of a card | colored edges only for errors, warnings and things that need action |
| badges and dots that mean nothing (new, beta, live, a type pill on every row) | a badge only for real status; plain muted text for a type |
| a small all-caps label above every heading | drop it, or fold the useful part into the heading |
| monospace on labels, tags and buttons | monospace only for code, ids and numbers that line up |
| emoji or text glyphs as icons (⌄ ✓ ☆ ×) | the svg set in `static/js/icons.js`; css glyphs use the `--ic-*` masks. content emoji (a habit's icon, a mood) stay |
| the same radius and shadow on everything | radius by role (control, surface); no decorative shadows |
| light gray secondary text below 4.5:1 | muted text still meets 4.5:1; only skippable text goes lighter |
| decorative motion (pulsing dots, bouncing, a fade on every block) | animate what changes, under 300ms, never content waiting on motion; reduced motion turns it off |
| gradients, glow, neon edges, grid backgrounds | solid tokens; weight and size for emphasis |
| frosted glass over color blobs | blur only for overlays |
| screens stuffed with cards, banners and links | remove anything the owner doesn't act on |
| placeholder initials, grey boxes, empty frames | real content or nothing |
| headings that describe a product category | short names of the thing or a verb |
| numbers written as words | digits |

## how to check

- name each tell you can find on the screen before changing anything; "it looks off" is not a
  finding.
- remove first, then decide color, type and icons on purpose.
- look at the rendered screen with real content, in webkit at ipad and phone sizes as well as
  desktop, in every hover, pressed, open and loading state.
