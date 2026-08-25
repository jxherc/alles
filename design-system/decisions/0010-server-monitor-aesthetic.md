# 0010: server system monitor keeps its terminal aesthetic

Status: accepted

## decision

The server space's system overview keeps its neofetch-style presentation: the ASCII
glyph logo, the rainbow capability swatches, and the green/amber/red meter bars. This
is a scoped exception to the FOUNDATIONS palette and to the 12px type floor for the
glyph art only. Everywhere else in the server space (navigation, forms, tabs, policy
screens) the standard tokens and type rules apply unchanged.

## reason

The system monitor is a deliberate specialist surface: it answers "what is this
machine doing" in the visual language of the terminal tools it replaces (neofetch,
btop). Recoloring it to the neutral palette would remove the one piece of character
the surface owns without making the information clearer. The rest of the product
gains nothing from forcing this one screen into the same voice.

The exception is narrow on purpose: it covers decorative meter colors and the glyph
art. It does not cover text colors, controls, focus, spacing, or states, which stay
on tokens so the space still reads as Alles.

## consequence

- `static/js/system.js` chart and meter colors are exempt from palette-token review.
- The glyph `pre` may render below 12px; it is decorative art, not text content.
- Any new server screen follows the standard rules; the exception does not spread.
- Data-visualization categorical palettes (event colors, file color dots, chart
  series) follow the same principle: category colors are user-meaningful data, not
  UI chrome, and are exempt from the neutral palette.
