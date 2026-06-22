# skills ui redesign — design

## context

the skills view (`static/js/skills.js` → `initSkills`, styled in `static/style.css`)
is a master/detail layout:

- a fixed **240px** left column (`.skills-side`) holds the search box, four stacked
  buttons (new / browse library / github / upload), and the whole skill list
  (`#skl-list`) — 252 installed skills bucketed into 18 collapsible category groups.
- a wide right column (`.skills-main`) is the editor form (name / description /
  when-to-use / markdown body + save·export·update·delete + git source).
- the library (`_showLibrary`) **replaces** the installed list inside that same skinny
  column, rendering ~250 catalog rows in a single column.

### problems
- 252 skills in a 240px column = endless vertical scrolling to find or manage anything.
- browsing the library nukes the installed list and is itself a 250-row single-column scroll.
- the wide editor pane is idle whenever you're just browsing/managing, so horizontal
  space is wasted while the list is cramped.

## goals
- stop the scrolling: jump to a category instead of scrolling past everything.
- use the horizontal space: a multi-column card grid, not one skinny column.
- make the library a first-class part of the same surface, not a destructive mode swap.
- let basic management (pin, delete, add) happen without opening the editor.

## non-goals
- no backend changes. every field needed is already served:
  `/api/skills` and `/api/skills/catalog` both return `category`, `pinned`, `uses`,
  `source`, etc. this is a frontend-only redesign (`skills.js` + `style.css`).
- no change to the skill data model, install/import/pin/delete endpoints, or the
  agent-side skill loading.
- not touching the editor *fields* — same inputs, just relocated into a drawer.

## layout

a header row on top, a two-column body beneath it. all built in JS inside
`#skills-body` (as today — `index.html` is untouched).

```
skills                       [ search...... ]        [ + new ]
┌───────────┬─────────────────────────────────────────────────┐
│ all   252 │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐     │
│ ▸coding 14│  │ card   │ │ card   │ │ card   │ │ card   │     │
│  writing14│  └────────┘ └────────┘ └────────┘ └────────┘     │
│  research │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐     │
│  data&sql │  │ card   │ │ card   │ │ card   │ │ card   │     │
│  …        │  └────────┘ └────────┘ └────────┘ └────────┘     │
│───────────│                                                  │
│ ⊕ library │                                                  │
│ ↳ github  │                                                  │
│ ↑ upload  │                                                  │
└───────────┴─────────────────────────────────────────────────┘
```

### components

**header** (`.skills-head`)
- `skills` title, a wide search input, a `+ new` button.
- search is debounced (~200ms), filters across name/description/when-to-use.

**category rail** (`.skl-rail`, ~160px, left)
- `all (N)` first; then only categories that actually have items, with per-category
  counts, in the existing `_CAT_ORDER`; `pinned` floats above `all` when pins exist,
  `custom` sits last.
- clicking a row filters the grid; the active row gets the kokuen accent marker.
- a divider, then the rail foot: `⊕ library` (mode toggle), `↳ github`, `↑ upload`.
- the rail is short enough (≤20 rows) that it doesn't itself scroll on desktop.

**card grid** (`.skl-grid`, right)
- `grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))` → 2–4 columns by width.
- **card** (`.skl-card`): name (bold, truncated), 2-line clamped description, a row of
  small badges (`uses ×N`, `git` when source-backed).
  - hover reveals quick actions: **★ pin** (toggles, pinned cards float to the rail's
    `pinned` group) and **🗑 delete** (confirm dialog).
  - clicking the card body opens the editor drawer for that slug.

**library mode**
- toggled by `⊕ library` in the rail. the grid switches to the catalog
  (`/api/skills/catalog`); the *same rail* filters the catalog by category.
- header gains `library · N` and `add all (N remaining)`.
- catalog cards: not-installed show **+ add** (installs via `/api/skills/install`);
  installed show `✓ added` (dimmed, `--signal`). adding refreshes the catalog in place.
- the rail's `⊕ library` shows an active state while in this mode; clicking `all` or any
  category, or a `← my skills` affordance, returns to the installed grid.

**editor drawer** (`.skl-drawer`, slides in from the right, ~480px)
- holds the existing fields: name, description, when-to-use, markdown body textarea,
  and the save / export / update / delete actions + git-source line.
- opens on card click or `+ new` (empty). closes on ✕, Esc, or click on the backdrop.
- the grid stays mounted behind it so you keep your place.

## state

`skills.js` keeps a small module state object:
- `mode`: `'installed' | 'library'`
- `cat`: selected category key, or `'all'`
- `q`: current search string
- `editing`: slug open in the drawer, or `null` (new)

render is driven off this state: `_render()` picks the data source by `mode`, filters by
`cat` + `q`, groups/sorts (pinned first, then the existing score sort), paints the grid,
and repaints the rail counts. search, when non-empty, shows a flat result grid and a
"results (N)" rail state rather than a category filter.

## styling (kokuen)
- greyscale base, tiny text, 1px borders, 2–3px radii.
- accent only for the active rail row + interactive affordances; `--signal` for `✓ added`.
- the house `cubic-bezier(0.2,0.7,0.2,1)` easing on the drawer slide-in and card hover.
- cards are hand-built (no native controls), consistent with the rest of alles.

## responsive (<720px)
- rail collapses to a horizontal, scrollable chip bar above the grid.
- grid drops to 1–2 columns.
- drawer becomes a full-screen sheet.

## testing
extend `tests/pw_verify_notes_skills.py` (or a sibling) to assert, against a fresh
seeded server with the service worker blocked:
- the rail renders ≥6 category rows with counts > 0, plus `all`.
- clicking a category filters the grid (card count changes, all cards belong to it).
- the grid is multi-column (cards share rows — compare bounding-box `top`s).
- `⊕ library` switches to catalog cards; an `+ add` installs and flips to `✓ added`.
- clicking a card opens the drawer with the fields populated; Esc closes it.
- `+ new` opens an empty drawer and save creates a skill.
- no console errors.

## files touched
- `static/js/skills.js` — replace the list/library/editor rendering: header + rail +
  grid + drawer, driven by the state object. reuse all existing `_api` calls
  (`/api/skills`, `/catalog`, `/install`, `/{slug}`, `/{slug}/pin`, `/{slug}/export`,
  `/{slug}/update`, delete, upsert) and the existing `_CAT_LABEL` / `_CAT_ORDER`.
- `static/style.css` — new `.skills-head`, `.skl-rail`, `.skl-grid`, `.skl-card`,
  `.skl-drawer` rules; retire the now-unused `.skills-side` / `.skl-list` / `.skl-row`
  list styles (and the `.skl-group*` grouping styles added earlier).
- bump the SW cache version + stamp on ship (see `sw.js` VERSION/STAMP + `index.html` `_v`).

no `index.html` change — `#skills-body` is populated entirely by `initSkills`.
