# warm ember, real depth, and motion on every touch

## context

The owner asked for a total UI revamp (2026-10-21): "deslop", better colour, "make everything
alive", and "user friendly is key". An audit of 72 screens (18 apps at 1280×800 and iPad
1194×834, both themes, sample data) found one flat plane (page #090909 and panel #0d0d0d can't be
told apart), outlined rectangles as the main button look, empty 44px squares as checkboxes, the
accent almost absent, beige paper as the light theme, and nothing that moved on rest or on press.

The owner picked from a direction page: warmer and softer, alles purple, balanced corners, airy
density. They took the recommended "ember" palette by asking to start building.

## decision

- **palette (ember).** Dark: page `#12100e`, panel `#1a1714`, raised `#23201c`, hover `#1f1c19`,
  line `#322d28`, strong line `#463f39`, text `#f3efe9`, soft `#cec6bc`, muted `#9d948a`, quiet
  `#8f877d`, accent `#aaa6ff`, success `#8cc79d`, danger `#f2897f`, permission `#e8b26c`. Light:
  page `#f8f6f3`, panel `#f1eeea`, raised `#ffffff`, hover `#ebe7e2`, line `#e3ded8`, strong line
  `#cbc4bc`, text `#1d1a17`, soft `#4b4540`, muted `#6a625a`, quiet `#6e665e`, accent `#5650d0`,
  success `#276b40`, danger `#b3372f`, permission `#8a5a12`. Every text colour clears 4.5:1 on
  page, panel, raised and hover. Link blue, the ai tint and the data colours (0034) stay.
- **untouched old defaults upgrade.** A stored theme that still equals the kokuen graphite
  default (matched on bg, text, panel, line, accent) moves to ember on the server and in the
  browser cache. Derived roles still at their old value move too; one the owner changed stays.
- **corners.** `--k-radius-small/control/surface/large` = 6 / 8 / 12 / 16px (were 2 / 3 / 4).
  Every literal 2/3/4/6px radius in the stylesheets now uses these tokens. Chips are round. An
  inner corner is its outer corner minus the gap.
- **depth.** Surfaces separate by tone first. Raised things add a 1px light top edge
  (`--k-edge`) and one tight shadow tinted to the dark (`--k-lift`); only menus, dialogs and
  toasts float (`--k-float`). This replaces "shadows are absent from normal product UI" and the
  kokuen.css shadow ban for the surfaces listed here; kokuen.css itself still draws none, the
  depth lives in `static/revamp.css`.
- **three button tiers.** Primary: filled accent with dark text in dark and white in light, one
  per surface (`.btn.primary`, Files' upload, Docs' new document, the board's add, the code
  view's primary). Secondary: raised fill (`.btn`, `.act-btn`). Text: plain (`.link-btn`,
  calendar's arrows, icon buttons). This replaces 0031's bare text action and strong-line
  primary, and its settings outline pass.
- **picked things.** Tabs, segments, settings nav and the aide mode switch share one pill that
  slides to the picked item (`static/js/motion.js` sets `--pill-*` on the group; the pill is the
  group's `::before`, so no element is added). In a row of 44px tabs the pill sits 4px inside
  the target. Filter chips take the accent tint and ring instead.
- **checkboxes and switches.** A 20px rounded box with a drawn tick inside the 44px target;
  switches that are on are the accent, and the knob springs.
- **motion.** Press: a control scales to 1 − min(0.035, 5px ÷ width) in 120ms and springs back
  (Web Animations, so no element's own transition list is touched). Menus grow from their
  corner, dialogs spring in over a blur, toasts rise and fade out, a view settles in when it
  opens (opacity only), money's totals count up, app glyphs and everyday icons move on hover.
  Drawers (the app list, Aide's archive) slide in from their edge in 380ms with no overshoot, since
  a bounce opens a gap at the screen edge; the app list's groups follow about 30ms apart, and
  closing slides back out before the drawer hides (2026-10-26).
  Easing `cubic-bezier(.23,1,.32,1)`; springs as css `linear()` from Open Props (MIT). This widens
  MOTION.md's "motion only for feedback" by the owner's direction, as 0036 began for Aide. All of
  it stops under reduced motion, and automated browsers get final numbers at once.
- **icons.** Each app has its own glyph (`appGlyph()` in `static/js/icons.js`) on the existing
  24 grid and 1.6 stroke, used in the app switcher and on home's pinned apps. Each has one part
  that moves while pointed at or focused. No icon pack was added.
- **airy type.** Controls in specialist apps read at 14px (was a 13px floor); buttons 14px.
- **per screen.** Calendar events are tints with a bar, not solid blocks. Outlined cards become
  filled panels. Overviews sit in three filled columns within 1040px. Home's capture is a soft
  filled box with a mode chip and a send that fills when there's text, both 6px from every edge;
  pinned apps are tiles. Settings reads "settings / home" on one line. Andromeda's search gets a
  filled shape and focus glow (replaces 0025's bare line). An empty saved chat shows the
  greeting and starts. The loading line takes no room: a thin bar, shown only after 260ms.

## second pass: one frame, tasteskill v2 (2026-10-22)

The owner found the spacing inconsistent everywhere and called the Aide step cards slop, and
asked for everything to go through tasteskill v2's app-screen rules. Measured first: content
started anywhere from 7 to 557px in and stopped 17 to 901px short of the right edge, because each
app family had its own centred column (880, 928, 1040, 1080px) or padding.

- **one frame.** Every app runs the full width with one gutter on both sides (`--k-gutter`, 24px,
  16px on a phone). The header's app name starts on that same edge. List pages, overviews, aide's
  tool pages, home and the server monitor follow it; home sits in two columns over 1100px. Only
  the aide conversation keeps its reading column, and the andromeda landing stays centred.
- **no shadows at rest.** This replaces the depth bullet above: buttons, cards and the picked pill
  are tone steps, light adds a 1px line (`--k-btn-line`, `--k-card-line`), and only menus,
  dialogs and toasts float with one shadow. The primary is a flat accent fill.
- **picked things are neutral.** Chips take the same neutral pill as tabs (`--k-pill`), not the
  accent tint. Underline tabs get one 2px underline that slides.
- **switches.** ~~A switch that is on is ink with a page-coloured knob.~~ Reverted 2026-10-26: the owner's
  standing rule is a soft alles-purple track with a text-coloured knob, and the ink version left
  andromeda's switches with a knob the colour of its track. Every switch uses the kokuen on state.
- **no entrance.** Screens no longer fade in; a total counts only when its value changes.
- **a title.** The app name in the header row is each screen's h1 (home's greeting and
  andromeda's own heading keep that role there).
- **aide steps.** A step is a 44px line (mark, what, where, time), not a card; what changed
  something has an amber mark instead of an amber bar; its output sits once in an indented well.
  A reply's own actions are quiet words.
- **the code view's projects rail** resizes (drag, or arrow keys on its edge) and hides; both are
  remembered.
- **a page's own sidebar** (docs, journal, files, gallery, calendar, the code view's projects) is
  a filled panel with a 12px top corner and no line beside it, as in the direction demo; its
  picked row is one tone up. A permanent sidebar of every app was tried and dropped: the owner
  kept the app switcher and the view tabs.
- **files and gallery** share one frame: the sidebar runs from the top, and the main column has
  one toolbar on the sidebar's top line, the folder or view name as its title on the left and
  search and actions on the right. Files' select boxes take the same box and tick as tasks, a
  file's actions are one row of equal buttons, and up is disabled at the top folder.
- **filled buttons don't pull back.** The old -12px pull-back was for buttons drawn as bare words;
  a filled button sits on the gutter.
- **alles purple stays** although tasteskill bans violet: the skill marks that as its author's
  taste, and the owner chose it. So do the 8/12/16 corners.

## kept

- Inter, the 44px target, kokuen's spacing scale, the server monitor's own palette (0010).
- "currency not set" stays visible on money totals with an unknown currency: it is a safety
  label, not decoration.

## verification

See the branch's commits: JS tests, the python suite, ruff, the browser gates (ui-audit and the
Aide, home, shell, calendar and gallery gates) and screenshots at 1280×800 and 1194×834 in both
themes.
