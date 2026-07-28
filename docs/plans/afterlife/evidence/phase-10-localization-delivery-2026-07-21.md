# Phase 10 localization delivery - 2026-07-21

Scope: the reviewed eight-language core-flow contract in `static/locales/manifest.json`. This does
not claim that owner-authored content, third-party text, legacy specialist apps, or advanced Calendar
and Andromeda administration are translated.

## Catalog and runtime contract

- `en`, `fr`, `es`, `zh-Hans`, `zh-Hant`, `ja`, `ko`, and `ar` each have 328 message keys and nine
  plural keys at source revision `phase10-canonical-2026-07-21`.
- Every catalog has a reviewer, review date, reviewed state, exact key and placeholder parity, and the
  locale's required plural categories. Arabic has zero, one, two, few, many, and other.
- All eight catalogs are local release assets and selectable. English remains the safe fallback when
  an unknown key or invalid requested locale is encountered.
- The checked core flows are the shell, Home, Aide primary conversation controls, Andromeda primary
  search, Plan Tasks, Plan Calendar primary controls, and Settings localization/Credits.
- Shared helpers own date, time, number, currency, list, relative-time, and plural formatting. A
  source contract rejects hard-coded `en-US` and direct locale formatter calls outside the helper.
- Language, region, timezone, clock, week start, and currency persist independently. Applying a
  language updates `lang` and `dir` while preserving the pane, focus, and recoverable form state.

Review state is an internal Phase 10 editorial and rendered review recorded in each catalog. No
independent native-speaker certification was commissioned, so the repository does not claim one.

## Local input and documentation

- Deterministic Task and Calendar parsers cover relative dates, explicit local dates, local time and
  duration forms, Arabic-Indic digits, and weekly recurrence in all eight languages.
- Unknown phrases remain owner text and are not guessed or sent to a model. Unsupported language
  identifiers fail closed.
- Seven translated READMEs live under `docs/readme/`; each names `README.md` as canonical, records
  the source revision, and records a reviewed date/state.
- Core interface fonts and language assets are local. Runtime UI paths do not require Google Fonts,
  Mermaid, KaTeX, or another UI CDN.

## Fresh rendered gate

`tests/pw_phase10_localization_credits_real.py` passed against a fresh throwaway `ALLES_DATA` server
on port 8974. It exercised every language at 1440 x 980 and 390 x 844 and proved:

- keyboard language selection, custom region/timezone listboxes, custom clock/week controls, save
  announcements, focus return, and persistence;
- primary Home, Aide, Andromeda, Tasks, and Calendar copy after each switch;
- Arabic RTL plus left-to-right isolation for paths, numbers, and technical values;
- Arabic and CJK input caret movement, glyph fallback, line breaking, wrapping, and no horizontal
  overflow;
- both themes, 200 percent zoom, reduced motion, 44px phone targets, request-error/retry, empty state,
  and a clean console apart from the deliberately asserted 503 and offline network events;
- service-worker precache and cold offline reload for all eight local catalogs.

Fresh screenshots for Arabic phone, Traditional Chinese phone, Japanese desktop, desktop
localization/Credits, and phone Credits were inspected at original resolution.

## Final anti-slop and design-system recheck

The entire repository anti-slop law and the applicable design-system QA checklist were rechecked
against the fresh renders:

- The Phase 10 work remains a functional Settings surface, not a hero, marketing stack, pricing,
  testimonial, CTA, fake app window, decorative card wall, or standard footer composition.
- App identity appears once in the compact header. There is no `<app>/alles` breadcrumb and no
  redundant oversized app or workbench title.
- No native select, checkbox, radio, context menu, sun/moon switch, pill-chip metadata field, dead
  control, or fake interactivity is present. Keyboard roles, states, disabled behavior, and focus
  return were exercised with real input.
- Content is visible by default. There is no entrance-opacity trap, clipped text, cut-off glow,
  background halo, gradient text, glass, card hover lift, button boop, animated underline, floating
  decoration, shadow duplicate, or grain over content.
- Typography stays inside the existing KOKUEN system; monospace is limited to real data. Copy is
  short, contrast is legible in both themes, mixed-direction values are isolated, and text has real
  gutters from every modal, row, and viewport edge.
- Desktop columns and phone reflow remain aligned; long licenses and paths stay inside their owning
  surface. At 200 percent zoom there is no horizontal overflow or sliced control.
- Reduced motion keeps every word and control visible. Loading, selected, unavailable, disabled,
  focus, empty, partial, error, and retry states remain distinguishable without glow or color alone.

Result: the applicable Phase 10 localization and visual gates pass. The prior Settings-foundation QA
remains useful history, but its English-only and incomplete-inventory limitations are superseded by
this evidence.
