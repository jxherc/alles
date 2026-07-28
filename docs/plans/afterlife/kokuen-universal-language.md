# kokuen universal app language

status: starter pending owner approval

## the problem

Alles has shared colors, but it does not yet have a shared interface language. The current real app has:

- 18 specialist app surfaces;
- 34 different header variants;
- 91 separate font-size declarations;
- 348 inline style blocks;
- several unrelated sidebar, tab, toolbar, empty-state, and action patterns.

Fixing one screen at a time cannot solve this. New work keeps inheriting a different local pattern.

## the direction

The visual idea is **one quiet workbench**.

Alles is a daily-use, self-hosted personal system. It should feel calm, precise, and connected. The interface stays compact without becoming tiny. Motion is short and functional. The system uses the existing KOKUEN black, warm white, quiet gray, and Alles purple.

The signature is not decoration. It is the repeated relationship between the route, the work surface, and the local context panel. Every app begins on the same baseline and uses the same interaction grammar.

## shared shell

Every specialist app uses the same 52px top bar:

- `home` is a plain text action on the left;
- the current app name opens the custom app picker;
- the middle shows the current local context when useful;
- the right holds search, one primary action, and `settings`;
- theme belongs inside Settings, never in the page header;
- the shell never adds the old global sidebar.

The header may omit actions that do not apply. It may not invent a different height, radius, font scale, or settings placement.

## four workspace shapes

Universal does not mean identical. Each app chooses one of four shapes.

### list

For Tasks, Contacts, Books, Habits, Watchlist, Subs, and similar collections.

- one filter row;
- one readable list;
- optional quick capture at the bottom;
- details open inline or in a local context pane.

### timeline

For Calendar, Days, Journal history, Activity, and Health history.

- time controls live in one shared tool row;
- the timeline or calendar owns the work surface;
- secondary navigation stays local to the app.

### workspace

For Docs, Files, Mail, Gallery, and Secrets.

- two or three panes are allowed;
- the left pane is app-local navigation, never global navigation;
- pane widths and top edges align with the universal header;
- mobile collapses to one active pane with a clear back path.

### dashboard

For Money, Health summary, System, and Watch.

- key facts use rows or a real data grid, not a wall of cards;
- one primary visualization at most;
- supporting data stays readable and comparable.

## tokens

### type

- interface body: 15px / 1.45;
- app name: 15px / medium;
- page or section title: 16px / semibold;
- row title: 14px / medium;
- secondary text: 12px to 13px;
- data uses tabular figures, not a decorative monospace house voice;
- specialist screens do not use oversized marketing headlines.

### space

Use only 4, 8, 12, 16, 24, and 32px. A dense row is 36px. A normal row is 44px. The top bar is 52px.

### shape

- 0px for structural seams and tables;
- 2px for small controls;
- 4px for menus and contained surfaces;
- no pills unless the content is truly a status;
- no card hover lift, glow, or all-around shadow.

### color

- background: `#090909`;
- local panel: `#0d0d0d`;
- raised or selected surface: `#171717`;
- main text: `#eceae6`;
- muted text: `#85817c`;
- quiet text: `#5f5c58`;
- structural line: `#292929`;
- focus: the neutral strong-line role, visible without recoloring the whole control;
- accent: `#9298ff`, used for meaningful active state only;
- orange, red, and green are reserved for permission, failure, and confirmed success.

Light mode uses the same roles. Apps do not invent separate palettes.

## controls

- text actions are preferred when the label is clearer than an icon;
- bare icons are allowed when the shape is universally understood;
- one primary action per screen;
- custom menus use `role=menu`, keyboard movement, Escape, focus return, and disabled states;
- custom choices use buttons with `aria-checked` or `aria-pressed`;
- browser-native selects, dropdowns, checkboxes, radios, and context menus are forbidden;
- focus is always visible;
- controls do not move, grow, glow, or lift on hover.

## common states

Every app uses the same language for:

- loading: skeletons that match the real layout;
- empty: one short explanation and at most one useful action;
- partial: data remains usable with one quiet status line;
- error: a short cause and a retry action in the affected area;
- offline: existing local data remains visible;
- disabled: the reason is available without relying on color alone.

## migration rule

The standalone starter must be approved before the real app shell changes. After approval, migrate apps in small groups by workspace shape. Preserve specialist behavior and tests. Do not replace an app's information architecture just to make it look uniform.
