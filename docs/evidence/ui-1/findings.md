# Stage 1 — home / global chrome — findings

Audited the home at 1280px (`home-before.png`): 3-col grid squished to ~696px content with ~292px dead
margin each side; ask placeholder "ask aide about your day…"; single-target breadcrumb.

## Shipped
- **ui-1a** breadcrumb is now two anchors — app part → its subdomain root, "alles" → hub. Real `href`s
  so **middle/ctrl-click opens a new tab natively**; left-click does in-session SPA nav (modifier clicks
  fall through). Same treatment on aide's sidebar wordmark. Verified hrefs on `calendar.localhost`:
  app→`calendar.localhost:8870/`, alles→`localhost:8870/`.
- **ui-1b** grid → 5-per-row, `.home-inner` 760→1080px, less side padding, breakpoints 5→4→3→2→1.
- **ui-1c** removed the redundant aide tile (the quick-message bar is aide); moved the tile grid directly
  under the logo, above the message/ask area. After: 14 tiles, 5/row, grid above ask (`home-after.png`).
- **ui-1d** input → "quick message…"; **send** is a plain message; a kept **"about my day"** button still
  injects today's context (and asks for a rundown when the box is empty).
- **ui-1e** customize mode jiggles movable tiles like iOS edit-home-screen (`home-jiggle`, desynced,
  respects reduced-motion). Verified: customize → `editing` class + `home-jiggle` animation active.
- **ui-1f** new `brandlogo.js`: per-provider glowing brand marks in the company colour (reuses the
  provider palette); the custom dropdown now supports a per-option logo; the home model selector tags
  each option with its provider. Verified the dropdown renders a glowing `brandlogo` in trigger + panel.

## Verified
- `tests.test_home` (13) + `tests.test_brandlogo` (9) green; node --check on all touched JS; ruff clean.
- Playwright: 5 tiles/row, grid above ask, jiggle on customize, split-crumb hrefs, dropdown logos —
  **0 console errors** throughout.
