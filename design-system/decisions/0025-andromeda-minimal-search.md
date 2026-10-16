# 0025 — Andromeda is a typography-led search surface

## Status

Accepted for the Andromeda surface.

## Decision

Andromeda uses one compact search line, one quiet category and result-count line, and a single readable result column. Ordinary results are expressed through URL, title, snippet, and an optional contextual menu. They do not add favicon tiles, card backgrounds, section banners, result-type labels, or decorative dividers.

The global app switcher and settings action remain available but visually quiet. Result actions keep 44px targets, keyboard selection remains visible as a one-pixel rail, and summaries expand inline without creating a second card.

Image, news, and video results retain their content-specific layouts. Shared app chrome, provider behavior, overview consent, search state, and Library behavior are unchanged.

## Reference boundary

The Blackout for Startpage project informed the typography-first result order and contextual menu pattern. Alles keeps its own theme, markup, assets, data flows, and implementation; no reference code or visual assets are copied.
