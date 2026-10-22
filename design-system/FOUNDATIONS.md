# foundations

Machine-readable values live in `tokens/`. This document explains how to use them.

## color roles

| role | dark | light | use |
|---|---:|---:|---|
| page | `#12100e` | `#f8f6f3` | main work surface |
| local panel | `#1a1714` | `#f1eeea` | app-local navigation or context |
| raised | `#23201c` | `#ffffff` | selected or raised state |
| hover | `#1f1c19` | `#ebe7e2` | quiet pointer feedback |
| text | `#f3efe9` | `#1d1a17` | primary content |
| soft text | `#cec6bc` | `#4b4540` | row titles and secondary actions |
| muted text | `#9d948a` | `#6a625a` | supporting information |
| quiet text | `#8f877d` | `#6e665e` | lowest-emphasis readable metadata |
| structural line | `#322d28` | `#e3ded8` | real boundaries only |
| strong line | `#463f39` | `#cbc4bc` | focused or raised boundary |
| focus | `#463f39` | `#cbc4bc` | visible neutral keyboard boundary |
| active | `#aaa6ff` | `#5650d0` | meaningful active state only |
| permission | `#e8b26c` | `#8a5a12` | full-access or authority state |
| danger | `#f2897f` | `#b3372f` | failure or destructive action |
| success | `#8cc79d` | `#276b40` | confirmed success only |
| link | `#8ab4f8` | `#1a0dab` | anything that opens a page: result titles, links in written content |
| visited link | `#c58af9` | `#681da8` | a link already opened |
| ai | active | active | the ai spark, the highlighted answer, ai at work |
| info | link | link | neutral notices |
| categorical | blue `#6fa3f2`, teal `#45b8ac`, amber `#d6a440`, pink `#e07aae`, violet `#a98bf0`, green `#86b86a` | `#2b5bb5`, `#0d6e65`, `#865700`, `#a6386f`, `#6e4cc2`, `#3a6b22` | telling data apart: money categories, chart series, weather marks |

The server system monitor holds a scoped palette exception for its meter and glyph colors; see `decisions/0010-server-monitor-aesthetic.md`.

At runtime the focus ring renders brighter than the strong-line value above (a faint/text mix): at the documented values the ring falls under the 3:1 non-text contrast that WCAG 2.4.11 asks of focus indicators, so visibility wins over token purity.

The warm ember values above come from `decisions/0040-warm-depth-and-motion.md`; an untouched
older default upgrades to them on its own.

Color says what a thing is or does, never decorates. Grey stays the base; see
`decisions/0034-color-with-meaning.md`. Runtime names: `--link`, `--link-visited`, `--ai`,
`--info`, `--success`, `--warning`, `--danger`, `--cat-blue` … `--cat-green` (and `--k-*` twins).

Never rely on color alone. Text, position, icon shape, or state wording must carry the same meaning.

`--faint` is a structural line token, never a text or placeholder color. Use `--muted`
for secondary text and full-opacity input hints. Quiet text needs a contrast check against
its actual surface; on raised selections and Files operation rows use muted instead.
Inline code uses a raised background, not the text color as its background. Server meter
colors may remain categorical, but numeric labels must remain readable in both themes.

## typography

- family: locally bundled Inter, with the system UI stack as fallback; explicit appearance font choices flow through the same shared token;
- body: 15px / 1.45 / regular; controls and buttons in specialist apps 14px (0040);
- conversation: 16px minimum;
- app name: 15px / medium;
- page or section title: 16px / semibold;
- row title: 14px or 15px / medium;
- action and label: 13px or 14px;
- helper and metadata: 12px or 13px, never lower;
- display data: 22px to 30px with tabular figures;
- greeting and specialist empty-state voice type may exceed this cap only as bounded in `decisions/0011-display-type-voice.md`;
- code and terminal: local monospace stack only.

Avoid fake hierarchy from accidental bold. Use weight 400 for body, 520 to 580 for emphasis, and 620 only for true headings.
The app name appears once in its local identity region. Never enlarge and repeat it as a content title.

## spacing

Use 0, 4, 8, 12, 16, 24, 32, 48, and 64px. These values express relationship:

- 0px: intentionally no relationship gap;
- 4px: tightly related metadata;
- 8px: control internals and small groups;
- 12px: row internals;
- 16px: normal stack gap, form-field separation, or compact page gutter;
- 24px: card padding and related content groups;
- 32px: page header to first work block;
- 48px: section separation;
- 64px: major page-block separation.

Fixed structural sizes are separate tokens: 52px app header, 44px product controls
and interactive rows, and 36px only for noninteractive dense data. Do not invent a spacing value to
repair a layout; fix the layout rule.

Compact search, capture, command, and composition entry starts at the 44px product-control height. A single-line entry stays 44px; it does not inherit the 52px app-header height or a large empty minimum height. An inline multiline entry starts at 44px, grows with content, and becomes internally scrollable at its documented cap or before it would consume the viewport. Use `data-kokuen-entry="compact"` or `data-kokuen-entry="autogrow"` with `static/js/text_entry.js` instead of one-off height code.

Long-form writing surfaces, source editors, notes, message bodies, and structured multi-row settings are exempt: their work needs determine their height. A field inside a visually bounded composer or search shell must not draw a second focus box; the owning boundary shows the one visible focus state.

The runtime numeric token names match their ordered KOKUEN step: `--k-space-1` through
`--k-space-8` resolve to 4, 8, 12, 16, 24, 32, 48, and 64px. Portable components may use the
equivalent `--ui-space-*` aliases. Page gutters remain a semantic product token because Alles uses
16px on small layouts and 24px on roomy layouts.

## shape

Balanced corners (decision 0040), through `--k-radius-*`:

- 0px: tables, grids, pane seams, and structural surfaces;
- 6px (`small`): tags, inline code, small marks;
- 8px (`control`): buttons, fields, rows, tabs;
- 12px (`surface`): cards, menus, toasts;
- 16px (`large`): composers and dialogs;
- round: filter chips, switches, a genuine circular mark, state dot, or avatar.

An inner corner is its outer corner minus the gap, so nested shapes stay concentric. No card
lift, glow, or shape change on hover.

## layout

- app-owned primary header: 52px;
- app-name navigation target: at least 44px;
- optional small-layout context or tab row: 44px;
- content begins on the same top and side baselines inside its workspace shape;
- page gutters: 16px small, 20px normal, 24px roomy;
- readable text measure: about 68 characters;
- list content: up to 880px;
- dashboard content: up to 1040px;
- local navigation: about 204px to 224px;
- detail pane: about 300px;
- use flexible tracks with `minmax(0, 1fr)` and explicit overflow ownership.

## elevation and boundaries

Prefer surface tone and space. Use a 1px line only for a real pane, table, focus, or state
boundary. Raised things (secondary buttons, the picked pill, filled cards one step up) add a 1px
light top edge (`--k-edge`) and one tight shadow tinted to the dark (`--k-lift`). Only menus,
dialogs and toasts float (`--k-float`). No big soft bloom (decision 0040).

## iconography

Every app has its own glyph (`appGlyph()` in `static/js/icons.js`, decision 0040) with one part
that moves while pointed at or focused. Use bare local SVG marks on a consistent 16px grid, with a quiet 1.4 to 1.5px stroke when line icons are appropriate. Do not place icons in decorative tiles. A 44px hit area surrounds every actionable mark without drawing a visible box at rest.
