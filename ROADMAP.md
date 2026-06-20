# alles — UI/UX overhaul roadmap (active)

## Context

The product was built feature-first and never had a real human-style click-through pass. The user
found a long backlog of UI/UX defects by actually *using* it: broken toggle corner radii, icons pulled
from three sources (emoji / Unicode / a few SVGs) with no central system, features with no live view,
dead buttons, panels that don't behave like real toggles, plus genuine functional bugs (research mode
won't send, a 2nd "ask your docs" answer overwrites the 1st, usage only counts on Anthropic).

The bar is **higher than "works"**: every surface must **work AND look good AND look unified** —
verified by clicking every button in every app, not just loading the page. This roadmap is built
**depth-first, one microversion at a time, in order** — each fully finished, tested, and made
good-looking + unified before the next starts. **docs is the biggest job — most time + tokens there.**

Full microstage detail + file/selector map lives in the approved plan:
`C:/Users/jxh/.claude/plans/twinkling-riding-allen.md`. The prior delivered roadmap is archived at
`docs/plans/roadmap-delivered-v1.md`.

Two locked decisions: **(a)** one central custom **SF-style inline-SVG icon set** replaces all
emoji/Unicode glyphs app-wide (home tiles excluded) — SF Symbols itself can't be embedded in a web
app. **(b)** docs gets **Obsidian-style inline live preview** in CodeMirror 6 (render in place, reveal
markdown only at the cursor), not a separate preview pane.

## Build discipline (every microversion)

1. **Audit by using it** — boot `python app.py` on an isolated `ALLES_DATA` + throwaway `PORT` (never
   real `data/`), curl real flows, and in Playwright click every button / open every menu, context
   menu, popup / exercise every flow with varied input / drive every view. Judge on **both** axes:
   does it work AND does it look good + unified. Evidence → `docs/evidence/<microversion>/`:
   screenshots of every view, console logs, request/response dumps, `findings.md` listing what was
   exercised + every bug / UI error / UX-visual imperfection / server error.
2. **Plan + decompose** → `docs/plans/<microversion>.md` + `progress.json` (≥8 tests each); build only
   genuinely missing/broken things, never rebuild what works.
3. **Strict TDD** per task: tests first (RED) → implement (GREEN) → `ruff check` + `ruff format
   --check` + `node --check` on touched JS. No fake passes, stubbed assertions, or skips. Update
   `progress.json`.
4. **Regress** — full-app Playwright regression with seeded data (zero functional bugs, zero
   UI/visual/UX problems, everything unified) + `python -m unittest discover -s tests`. Capture
   evidence, fix anything found, then continue.

**Parallelism + right-sized models:** spin up subagents for independent work (auditing different
views, running the suite, searching, scaffolding) and match model to task — cheapest model that can do
each job (search, log scanning, boilerplate, repetitive edits, running commands), strong model only
for the hard reasoning/implementation. Parallelism speeds up work *inside* a microversion; never
half-finish several at once.

No commits / pushes / tags / releases — all git/release work left to the user.

## Microversions (in order)

### Stage 0 — Foundations (consumed by every later stage)
- **ui-0a** central SF-style icon set (`static/js/icons.js`) + replace emoji/Unicode app-wide (home tiles excluded)
- **ui-0b** fix `.s-switch` toggle to a real pill; converge all ad-hoc toggles on it
- **ui-0c** reusable `.seg` segmented control (promote activity's `.act-range`)
- **ui-0d** "no model" copy everywhere; "alles isn't running" boot state instead of black/login wall

### Stage 1 — Overall UI / home / global chrome
- **ui-1a** breadcrumb split-nav (app-name → its subdomain, "alles" → hub) + middle/ctrl-click opens hub in new tab
- **ui-1b** home grid 5-per-row, wider, less side padding, graceful breakpoints
- **ui-1c** remove standalone aide bar entry; move tile grid directly under logo, above ask bar
- **ui-1d** rename quick-ask → "quick message"; keep separate "ask aide about my day" button
- **ui-1e** customize mode: iOS shake on movable/removable tiles
- **ui-1f** home model selector gets the glowing brand-logo treatment (shares Stage-2f)

### Stage 2 — aide
- **ui-2a** research/docs mode won't send on a new message — create session first
- **ui-2b** "ask your docs": 2nd/3rd answer lands in 1st box — scope result nodes per query
- **ui-2c** research blank-while-waiting — skeleton/searching state + error surface
- **ui-2d** usage tracking for non-Anthropic providers (deepseek/openai/etc)
- **ui-2e** voice UI → Apple Voice Memos feel
- **ui-2f** model brand logos that glow in brand color (modal/sidebar/topbar/home) + deepseek→"v4 pro"/"v4 flash"

### Stage 3 — docs (largest; most time/tokens)
- **ui-3a** toolbar split (left: tree/all-docs/name/stats · right: the rest) + header spacing
- **ui-3b** outline/properties/query → one mutually-exclusive accordion w/ glow + explainers
- **ui-3c** CM6 inline live-preview engine — 3c-1 inline marks · 3c-2 block widgets · 3c-3 lists
- **ui-3d** images render live + insert dialog (paste URL / pick local file)
- **ui-3e** links: hide URL when text present, custom (non-native) UI, fix text+url bug
- **ui-3f** tables render live + restyle
- **ui-3g** live views for numbered (w/ style options)/bullet/inline-code/check/quote/callout/code/columns/separator
- **ui-3h** selection bleed across lines (content-column constraint)
- **ui-3i** custom right-click context menu (Word-like, incl. AI + font)
- **ui-3j** native spellcheck / typo underline
- **ui-3k** move canvas/board/bookmark/tasks out of the in-doc toolbar (new-doc options + outside bookmark)
- **ui-3l** history popup spacing/redesign
- **ui-3m** comments: make the select→comment flow work
- **ui-3n** remove publish + CSS buttons
- **ui-3o** split view: 50/50 draggable divider + pick-doc picker (all vs open toggle)
- **ui-3p** export fidelity (tables/links/code) + live ≈ html/pdf
- **ui-3q** recently-opened tabs redesign (outline-on-open squircle, separators, drop deleted doc)
- **ui-3r** outline clarity (populate + empty explainer)
- **ui-3s** todos-extraction + backlinks explainers
- **ui-3t** docs settings pane (AI model picker + AI status) + remove Guide button

### Stage 4 — mail
- **ui-4a** toolbar: live search, remove threads, compose rightmost, rules+accounts → settings
- **ui-4b** Gmail-style toggleable category sidebar w/ unified icons
- **ui-4c** centered search + left account picker + always-available "all accounts"
- **ui-4d** compose: bigger, chip/token To/CC/BCC, date+time schedule picker, dirty-close confirm, multi-CC, autocomplete
- **ui-4e** rules + accounts re-homed in mail settings (proper spacing)

### Stage 5 — files & calendar
- **ui-5a** real free-disk display (Docker-aware)
- **ui-5b** unify/remove files smart-folder + hover-action icons
- **ui-5c** calendar view switcher → segmented control

### Stage 6 — gallery
- **ui-6a** overall UI rebuild (header/grid/lightbox spacing + typography)
- **ui-6b** icon unification (share/generate/trash/fav + lightbox actions)

### Stage 7 — contacts / journal / activity
- **ui-7a** contacts layout fix + de-icon top buttons
- **ui-7b** carddav → settings + real contacts settings pane
- **ui-7c** journal "lock now" fix
- **ui-7d** journal search-row alignment
- **ui-7e** de-icon cross-app top nav (journal/tasks/calendar)

### Stage 8 — secrets
- **ui-8a** vault chip behaves as a button + settings rightmost
- **ui-8b** main-vault / per-vault password model + inline rename in settings
- **ui-8c** 2FA: passkeys AND authenticator-app (TOTP) + biometrics-vs-passkey explainers
- **ui-8d** watchtower: explain + fix toggled UI + real toggle (indicate on / re-click hides)
- **ui-8e** customizable entry types — per-type placeholders + visual type/field editor in settings
- **ui-8f** "how to load it" on its own line

### Stage 9 — Final regression
- **ui-9** full unittest + broad 16-host sweep + deep click-through sweep of every button + cache-stamp bump + gate green

## Out of scope
- `system` monitor app · real WebAuthn/biometric/hardware-key round-trips needing physical authenticators
  (UI built + unit-tested) · any git commit/push/tag/release.
