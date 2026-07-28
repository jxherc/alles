# Phase 10 design review - localization and release hardening

## Problem

At the Phase 10 baseline, Alles had a careful English-only localization foundation but was not yet a
localized product. The browser catalog contained one English message, the server rejected every
non-English interface language, most interface copy and date formatting bypassed the helper, and Task
and Calendar natural-language input was English-only. The then-current remote font and
document-rendering dependencies also did not satisfy the offline language gate.

Release credits were similarly partial. `ACKNOWLEDGMENTS.md` named the main inspirations and several
dependencies, but there was no structured source of truth, complete third-party notice, license-text
bundle, or in-app Credits surface. Existing security, recovery, accessibility, and performance tests
were useful foundations, not fresh Phase 10 release evidence.

Successful ending: English plus French, Spanish, Simplified Chinese, Traditional Chinese, Japanese,
Korean, and Arabic cover every core flow with reviewed local catalogs; locale-sensitive input and
formatting work; the interface remains usable offline in LTR, RTL, CJK, and Arabic; every shipped
third-party item has a notice and required license text; and each hardening gate has current evidence.

## Baseline found on 2026-07-21

- `static/js/i18n.js` contains one locale and one translated message key.
- Settings offers only English, and `routes/settings.py` rejects every other language.
- The shared formatter is used by the shell clock and scheduled-message confirmation; many app
  modules still call browser locale methods directly or force `en-US`.
- Task and Calendar quick-add use the English deterministic parsers.
- The root has one English README, `ACKNOWLEDGMENTS.md`, and the project `LICENSE`.
- xterm and the managed Actual integration include local license/third-party files. Vendored
  CodeMirror and Leaflet do not yet have local license texts.
- Google Fonts, Mermaid, and KaTeX still load from remote origins in normal interface paths.
- There is no `THIRD_PARTY_NOTICES.md`, `licenses/` bundle, structured credits manifest, or Settings
  Credits view.

The detailed checked/unchecked baseline is in
[`evidence/phase-10-baseline-2026-07-21.md`](evidence/phase-10-baseline-2026-07-21.md).

## Decisions

### Canonical locale identifiers

Choice: use `en`, `fr`, `es`, `zh-Hans`, `zh-Hant`, `ja`, `ko`, and `ar` as the eight interface
catalog identifiers. Keep region, timezone, clock, first-day-of-week, and currency independent.

Reason: script tags distinguish the two written Chinese catalogs without pretending a region is a
language. A region can still produce `zh-Hant-TW` or `zh-Hans-SG` formatting.

### Reviewed local catalogs

Choice: English is the canonical key set. Every catalog has metadata for source revision, reviewer,
review date, and state. CI compares all keys, placeholders, and plural forms. A language is visible as
complete only when core-flow coverage is 100 percent and its locale-specific parser and rendered gate
pass.

Rejected: runtime machine translation, DOM-wide string replacement, or silently presenting an
English-fallback screen as translated.

### Explicit translation boundaries

Choice: static markup uses stable translation keys and safe text assignment. JavaScript renderers use
the same catalog API. User content, mail, documents, filenames, search results, provider errors, and
logs remain in their source language unless the owner explicitly asks Aide to translate a copy.

Reason: owner data must never be rewritten by interface localization, and arbitrary third-party text
cannot be safely treated as trusted interface HTML.

### Locale-aware deterministic input

Choice: Task and Calendar quick-add accept the active interface locale and dispatch to separately
tested deterministic locale parsers. Unsupported phrases remain plain titles instead of being guessed
or sent to a model.

Reason: the feature must stay local, predictable, and useful without AI.

### Offline typography and assets

Choice: remove runtime font/CDN requirements from core interface paths. Use a reviewed local/system
font stack or bundled licensed fonts with complete notices, then verify Arabic and CJK shaping,
fallback, weight, wrapping, and 200 percent zoom offline.

Reason: a language is not supported if its glyphs or document UI disappear without network access.

### One credits source of truth

Choice: a structured manifest records every direct dependency, vendored asset, font, model, dataset,
skill source, managed companion, and adapted project. A deterministic generator produces
`ACKNOWLEDGMENTS.md`, `THIRD_PARTY_NOTICES.md`, the `licenses/` bundle index, packaged notices, and the
in-app Credits data.

Reason: hand-maintained lists drift and cannot prove that release artifacts are complete.

### Hardening evidence stays separated

Choice: compatibility, accessibility, performance, security/privacy, backup/restore, recovery,
capability, and architecture reconciliation each get their own evidence section and pass/fail status.

Reason: one broad green test run cannot prove eight different release properties.

## Interface direction

- Keep the current Settings structure and KOKUEN control language.
- Language selection is a custom keyboard-operable choice control, never a native select or radio.
- Each language shows a plain review state. Missing coverage is called beta or unavailable, never
  complete.
- Language, region, timezone, clock, week start, and currency remain separate fields.
- Add a compact About/Credits Settings pane driven by the manifest. It provides searchable categories,
  exact versions/licenses, source links, and local license text without card walls or decorative
  badges.
- RTL changes reading direction, not information order blindly. Numbers, code, paths, URLs, terminal
  output, and mixed-direction values keep deliberate direction isolation.
- Content is visible by default. Translation loading failures keep the last reviewed language and show
  an inline recovery action.

## Responsive and accessibility contract

- All eight languages pass desktop and 390 x 844 layouts, 200 percent zoom, keyboard-only use, focus
  return, both themes, reduced motion, and clean-console checks.
- Arabic passes real RTL navigation, dialogs, tables, mixed numbers/paths, and input-caret behavior.
- Simplified/Traditional Chinese, Japanese, and Korean pass line breaking, truncation, font fallback,
  and minimum text sizes with the network disabled.
- Language switching announces the result, updates `lang` and `dir`, preserves the current pane, and
  never strands focus.

## Approval boundary

Catalog infrastructure, notice inventory, generators, parsers, and non-visual hardening work may
proceed from this review. The language selector and new About/Credits pane materially change Settings,
so they require one standalone KOKUEN fake-data starter and explicit owner approval before the real
interface changes. No Phase 9 mockup waiver is carried into Phase 10.

The browser-verified starter is
[`../../mockups/afterlife-release/localization-credits.html`](../../mockups/afterlife-release/localization-credits.html).
The owner explicitly approved this exact starter on 2026-07-21. Real Settings implementation may now
proceed without enabling any language that has not passed the catalog, parser, and rendered gates.

## Delivered implementation - 2026-07-21

The approved structure is implemented in real Settings. All eight internally reviewed catalogs are
selectable. Region and timezone default to automatic browser detection and use custom
keyboard-operated listboxes for overrides; clock, week start, and currency remain independent custom
choices. The universal week preference drives Calendar, and shared locale helpers own product date,
time, number, currency, list, relative-time, and plural output for the named core flows.

The Credits pane reads the complete 432-entry `credits/manifest.json`, provides search, category tabs,
source links, and lazy local license/notice text. The deterministic generator produces the readable
acknowledgments, third-party notices, and exact 465-file release notice set. Fresh isolated browser,
native, container, performance, security, recovery, capability, architecture, Python, JavaScript,
Ruff, and index gates are recorded in the linked Phase 10 evidence documents. Internal catalog review
does not claim independent native-speaker certification, and the manifest records the untranslated
owner, third-party, legacy specialist, and advanced administration boundaries.
