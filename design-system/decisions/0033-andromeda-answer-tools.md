# andromeda answer tools

## context

Andromeda's answer cards grew into working tools: translator, dictionary, converters, clocks,
timer, dice, color picker, formula 1, the periodic table. They need choices, steppers, look-up fields
and primary actions inside one card, and the owner's review found a selected choice box sticking out
past the card's left edge, because the row was pulled back so its first label lined up.

## decision

- A tool card opens with a 12px muted heading naming the tool, then its content. The card has no box;
  one line under it separates it from the overview, as before.
- Asking for a tool opens it empty. Nothing is translated, rolled, fetched or started that the owner
  didn't ask for. "5 minute timer" starts; "timer" waits.
- Choices inside a tool are one bordered segment group (°C/°F, timer/stopwatch, die sides). The group's
  box sits on the content edge, labels sit evenly inside, segments are 44px tall and split by a hairline.
  The selected segment uses the raised surface and a thin text stroke, never the accent.
- A count is a stepper in the same box: − value +, 44px buttons.
- Plain text actions keep no box at rest; a row that starts with one moves back by its padding plus its
  1px transparent border (13px), so the label lines up. A bordered primary never moves back.
- Look-up fields span the card: the field grows, the primary sits at the right edge, lined up with the
  widest content above it (day boxes, pickers).
- Pickers are the shared custom select (`static/js/dropdown.js`), drawn with one quiet line.
- Big answers use 32px tabular figures; what they are measured from sits underneath in muted 14px.
- A source that is down says so in the card with "try again"; nothing is made up to fill it.

- The owner found the parts hard to tell apart, so the page now has three regions: the tool card stays
  plain, the ai overview gets its own tinted surface (4px radius, 16px/20px padding) and the web results
  get a small "web results" label like the tool and overview headings. This relaxes 0025's "no section
  banners" for these three labels only.
- Periodic table cells are grid cells with one tab stop and arrow keys, like the calendar grids, so they
  fill their column exactly; the runtime's 44px button minimum is lifted for them alone, because it
  pushed every box into its neighbour.
- Settings panel: one section-title style (12px muted), text actions at 13px with 12px padding pulled
  back to the edges, fields as tall as the pickers (44px).

## verification

A script measured, for every tool card on desktop and phone, the left edge of each visible row
(boxes by their border, plain text by its glyphs) against the card edge, plus 44px targets and inner
padding of every button. Screenshots of each card in dark and light were read by eye.
