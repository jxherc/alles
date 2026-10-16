# borderless control grammar

## context

Alles accumulated selected tabs, quick-capture fields, nested settings cards, and icon-only actions with different visible boxes. The density made ordinary navigation look like a wall of controls and let feature modules fall back to platform text glyphs.

## decision

- Selected tabs use tone and type, not a filled tile.
- Quick-capture inputs use a single bottom structural rail; long-form editors and the Aide composer keep their workspace boundary.
- Icon-only actions use one bare 16px SVG centered in a 44px target. The shared KOKUEN runtime upgrades explicit `data-kokuen-icon` controls and legacy single-glyph controls, including dynamically inserted rows.
- Settings sections group with headings, rhythm, and row separators instead of nested outer card borders.
- Dialog edges, pane seams, data-grid lines, editor boundaries, and visible keyboard focus remain because they communicate structure or interaction state.

## verification

Check Plan, Inbox, Health, Finance, Settings, Docs, and Aide at desktop and phone widths. Selected navigation and icon actions must have transparent resting backgrounds; icon SVGs must be centered; discrete controls remain at least 44px; focus stays visible; long-form editing and the Aide composer must not collapse into compact fields.
