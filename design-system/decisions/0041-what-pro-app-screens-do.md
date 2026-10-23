# what professional app screens do

## context

The owner asked for the revamp to follow "how professional sites are designed" and to finish
every app (2026-10-22). We studied product screens, not marketing pages: Linear, Vercel
(Geist), Stripe, Notion, Raycast, Arc, GitHub (Primer), the Claude desktop app, opencode, and
dsh's CSS modules. Where we could, values came from real CSS or token files; the logged-in
Vercel, Stripe and Linear apps, claude.ai and Arc gave few or no numbers. The full notes, each
value marked verified, mock, reported or inferred, are in the session notes
(`pro-ui-research.md`).

Measured against them, alles differed in three ways that showed on every screen: one solid hover
colour that barely lifted rows on panels and darkened them on raised surfaces, underline fields
that read as heading rules (contacts' add fields looked like column titles), and section titles
spread from 12.5 to 16px at four weights.

## decision

- **see-through fills.** Hover is 6% of the text colour (5% in light), selected 11% (8%), a
  field 5% with a 12% ring. They read the same on page, panel, card and raised, and the picked
  pill uses the selected fill. Raycast ships 5% hover and 10% selected; opencode's lines are 8,
  10 and 20% white. The owner's text colour drives them, so a custom theme still tints them, but
  a custom hover colour no longer applies.
- **one filled field.** Text fields, the date picker, selects, textareas and toolbar searches
  are a filled box, 44px, radius 8, label above (Claude's field fill, Geist inputs). Focus is
  the accent ring with a soft glow. This replaces 0035's underline; the one-field-style rule
  stays. An add form is one filled row, like home's capture, and its fields drop their own fill.
- **one type scale.** Page title 20/28 600, section title 16/24 600, row title 14/20 500, label
  12/16 500, body 14/20 400 (Geist label-14, Primer title-small/medium). No 700 in chrome.
  Money, times, dates, sizes and counts use tabular digits (Geist's tabular label).
- **rows without dividers.** List rows sit 2px apart with no line; the hover fill is the row's
  shape, radius 8, inset past the words by the row's padding (Linear's issue rows). Tables and
  key-value lists (server, logs, files) keep their hairlines.
- **first row on one line.** Every app's first row starts 24px under the view tabs (Primer page
  spacing 16/24). Overviews, lists with no head row, the monitor and the server cards were 8 to
  36px off.
- **empty screens centred.** A 32px drawing, a title, one sentence of at most two lines and the
  one action, centred a third of the way down the space the rows will fill (Stripe Apps' empty
  state, Geist empty state). This replaces 0040's left-edge empty state.
- **purple stays scarce.** It marks the one primary action per view, focus, on-states, the caret
  and today; hover and selection are neutral (Linear).

## kept

- The 44px target everywhere. The products run rows at 28 to 40px; alles wins density back with
  14px text, 2px row gaps and no dividers instead.
- Inter, alles purple, the 6/8/12/16 corners, the ember palette and its contrast table.
- Hairlines stay the theme's `--faint` line. The research suggests white at 8 to 20%; the
  difference on the ember page is a few levels, so it was not worth moving every border.

## sources

- Linear: https://linear.app/now/how-we-redesigned-the-linear-ui,
  https://linear.app/changelog/2026-03-12-ui-refresh, https://static.linear.app/client/assets/style-XLjklEBw.css
- Vercel Geist: https://vercel.com/geist/typography, https://vercel.com/geist/colors,
  https://vercel.com/geist/materials, https://vercel.com/geist/empty-state
- Stripe: https://docs.stripe.com/stripe-apps/style, https://docs.stripe.com/stripe-apps/patterns/empty-state
- GitHub Primer: https://unpkg.com/@primer/primitives@11.10.0/dist/css/
- Raycast: https://raycast.com/blog/a-fresh-look-and-feel, https://developers.raycast.com/api-reference/user-interface/list
- opencode: https://github.com/anomalyco/opencode
- WCAG target size: https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html
