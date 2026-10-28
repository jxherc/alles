# header fills sit 8px in from the row edges

## context

A header control keeps a 44px target, and its hover or open fill was drawn at the full 44px. In the
52px header row that left 4px above and below, so the app name's fill, a view's fill and finance's
"finance guide" box looked pressed against the top of the page. Andromeda's header was 64px with a
52px search box, so its name and search sat on a different row from every other app.

## decision

- The app-name switcher, the specialist views on wide screens and the header actions (finance's
  guide) keep their 44px target but draw a 36px fill: 4px of transparent border, fill clipped to
  the padding box. The fill sits 8px from the top and bottom of the 52px row.
- Andromeda's header is the same 52px row. Beside the app name the search keeps a 44px entry and
  draws a 36px box the same way. The tall 52px box is for the idle page only.
- On the idle Andromeda page the app name sits top left, like every other app, not stacked on the
  search.
- Andromeda no longer shows a per-search engine or exact model row, or a saved searches block, on
  the page. Engine and models live in settings; saved searches get one shared place later.
