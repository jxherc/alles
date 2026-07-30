# foundations

Machine-readable values live in `tokens/`. This document explains how to use them.

## color roles

| role | dark | light | use |
|---|---:|---:|---|
| page | `#090909` | `#f4f3f0` | main work surface |
| local panel | `#0d0d0d` | `#eeece8` | app-local navigation or context |
| raised | `#171717` | `#e4e1dc` | selected or raised state |
| hover | `#141414` | `#e9e7e2` | quiet pointer feedback |
| text | `#eceae6` | `#242321` | primary content |
| soft text | `#b9b5b0` | `#55514c` | row titles and secondary actions |
| muted text | `#85817c` | `#68635e` | supporting information |
| quiet text | `#7d7974` | `#746e68` | lowest-emphasis readable metadata |
| structural line | `#292929` | `#d5d0c9` | real boundaries only |
| strong line | `#3a3a3a` | `#bbb4ac` | focused or raised boundary |
| focus | `#3a3a3a` | `#bbb4ac` | visible neutral keyboard boundary |
| active | `#9298ff` | `#5960c7` | meaningful active state only |
| permission | `#d5a265` | `#906323` | full-access or authority state |
| danger | `#df7474` | `#b54d4d` | failure or destructive action |
| success | `#7ea98b` | `#437650` | confirmed success only |

Never rely on color alone. Text, position, icon shape, or state wording must carry the same meaning.

## typography

- family: local system UI stack;
- body: 15px / 1.45 / regular;
- conversation: 16px minimum;
- app name: 15px / medium;
- page or section title: 16px / semibold;
- row title: 14px or 15px / medium;
- action and label: 13px or 14px;
- helper and metadata: 12px or 13px, never lower;
- display data: 22px to 30px with tabular figures;
- code and terminal: local monospace stack only.

Avoid fake hierarchy from accidental bold. Use weight 400 for body, 520 to 580 for emphasis, and 620 only for true headings.
The app name appears once in the app-owned shell. Never enlarge and repeat it as a content title.

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

Fixed structural sizes are separate tokens: 52px top bar, 36px dense row/control, 44px normal row and minimum mobile target. Do not invent a spacing value to repair a layout; fix the layout rule.

The runtime numeric token names match their ordered KOKUEN step: `--k-space-1` through
`--k-space-8` resolve to 4, 8, 12, 16, 24, 32, 48, and 64px. Portable components may use the
equivalent `--ui-space-*` aliases. Page gutters remain a semantic product token because Alles uses
16px on small layouts and 24px on roomy layouts.

## shape

- 0px: tables, grids, pane seams, and structural surfaces;
- 2px: small controls and active rows;
- 3px: normal interactive containers;
- 4px: menus and larger contained surfaces;
- circles only for a genuine circular mark, state dot, or avatar;
- pills only for status whose contained shape carries meaning.

No card lift, all-around shadow, glow, or shape change on hover.

## layout

- app-owned primary header: 52px;
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

Prefer surface tone and space. Use a 1px line only for a real pane, table, focus, or state boundary. Shadows are absent from normal product UI.

## iconography

Use bare local SVG marks on a consistent 16px grid, with a quiet 1.4 to 1.5px stroke when line icons are appropriate. Do not place icons in decorative tiles. A 32px desktop hit area or 44px mobile hit area may surround a bare mark without drawing a visible box at rest.
