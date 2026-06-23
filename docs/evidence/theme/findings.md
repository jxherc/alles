# advanced theme editor — audit findings

Ported odysseus's theme system into alles, mapped to alles tokens (bg/text/panel/faint/accent) and
built an alles-native editor. Isolated server `:8913`, fresh data. `audit.py` drives every control.

## What was exercised (works ✓)
- **Open** from settings → appearance → "open theme editor" — `02-settings-appearance`, `03-editor-open`.
- **Presets** (16) — gallery with quad swatches; clicking `ocean` recolors the whole UI live and
  auto-selects its constellations background — `04-preset-ocean`.
- **Base colors** — bg/text/panel/faint/accent via the in-house color picker (HSV square, hue bar, hex,
  eyedropper, recent + harmony suggestions); live preview on every change.
- **Harmony generator** — accent + type (comp/anal/tria/mono) + dark/light → full palette — `05-harmony`.
- **Fonts** (sans/mono/serif) + **density** (comfortable/compact/spacious) — segmented controls, applied
  live (serif heading + compact spacing visible in `09-light`).
- **Backgrounds** — none/dots + canvas effects synapse/rain/constellations/sparkles/petals, with effect
  color + intensity (auto-shown for animated patterns); **frosted glass** toggle — `06-sparkles-frosted`.
- **Custom themes** — save current (named), apply, delete; chip list — `07-custom-saved`.
- **Import / export** — JSON download + file import (round-trips the whole appearance object).
- **Light preset** — full light-mode flip through the editor — `09-light`.
- **Persistence** — survives reload (theme, font, density, background all retained) — `08-persisted`.
- **All 17 hosts** still boot clean with theme.js loading at boot (regression sweep).

## Issues found + fixed
1. **Theme reverted on reload** — `initAppearance` blindly overwrote the local cache with the server's
   response, but a fire-and-forget PUT that hadn't landed yet meant the server returned the default and
   clobbered the just-set theme. **Fixed**: GET `/api/appearance` now reports `_stored` (whether a theme is
   actually saved server-side); the client only adopts the server theme when `_stored` is true (or there's
   no local cache). Re-verified — `08-persisted-after-reload` now holds the theme.
2. **No-native-widgets rule** — replaced the native frosted checkbox with a custom toggle button and
   custom-styled the intensity range slider (themed track/thumb), per the house rule.

## Console / errors
- `console.log` — **0 real console errors** across the whole flow + a 17-host regression sweep.

## Verdict
Decisively beats the old two-control editor and matches odysseus's depth, while staying kokuen: custom
controls only, design tokens, no decorative shadows. Defaults are unchanged (comfortable/sans/no
pattern), so users who never open the editor see no difference — low regression risk.

---

# theme stage — re-audit (2026-06-23, contrast + ux pass)

re-ran the area for the user's bug list. isolated instance :8823 (AUTH off), driven with
playwright. exercised 14 themes (12 light-bg + 2 dark baselines) × 7 views (home, journal,
money, wiki, calendar, aide, login). for every visible text node the real background was
composited (DOM walk honoring rgba alpha) and the WCAG contrast ratio computed.
data: `contrast.json`. screenshots: `journal-*.png`, `login-blossom.png`.

## bugs found (judged on both axes: looks-right AND works-right)

### B1 — `--muted` unreadable on every light theme  [#39, high]
`applyAppearance` sets `--muted = mix(text, bg, 0.5)`. a 50% blend gives ~4.5 contrast on a
dark bg but only **2.78** on a light bg (gamma asymmetry). journal chrome leans on
`var(--muted)` for 15 elements (stats, export/lock, heatmap labels+arrows+year, month ticks,
prev/next/today, prompt, reflect, mood title, empty) — all 15 fail (<3.0) on
blossom/sakura/paper/lavender/solarlight/sand/steel/coral/ice/peach/cute. that is the
"journal invisible on light themes" report; it also faintly hits secondary text everywhere.
root cause: the fixed 0.5 mix. fix: derive muted adaptively with a contrast floor.

### B2 — login screen is dark-on-dark on light themes  [#39, high]
`.login-screen` / `.notrunning-screen` / `.drop-overlay` hardcode `rgba(10,10,10,0.72)` (dark
scrim) but their text uses `var(--text)`. on a light theme text is dark → dark-on-dark. probe
on blossom: brand/input `rgb(74,44,52)` over screen bg `rgba(10,10,10,0.72)` → ~1.6 contrast,
invisible. (`.modal-overlay` already had a `[data-theme=light]` override; these bare-text
overlays were missed.) fix: derive the scrim from the theme bg via color-mix.

### B3 [#33] editor is a modal behind a button — should be inline on the appearance screen.
### B4 [#34] the `.theme-mode-btn` + accent-swatch controls are independent of the active preset
and fight it; presets like sakura should lock mode+accent. dark/light should read as one
"default"; default bg = none; switching to a preset with a pattern should auto-enable bg.
### B5 [#35] alles-scope settings mix appearance+theme+security; reorganize into
general / security / themes / backup.

## clean
- dark themes: only the giant decorative `#home-clock` reads low (1.46), and it is low on
  EVERY theme incl. dark by design — not a bug.

## fix order
B1 + B2 first (surgical, isolated, highest impact), then B4, then B3 + B5 together.

## RESOLVED — B1 + B2 (#39)
- B1: added `relLum`/`contrast`/`mutedFor` to color.js (pure, unit-tested). `applyAppearance`
  now sets `--muted = mutedFor(text, bg, panel)` — nudges the 0.5 blend toward text until it
  clears 3.2:1 against the harder of bg/panel. dark themes are untouched (already pass at 0.5).
  also bumped the CSS `[data-theme=light]` fallback `--muted` #888 -> #767676.
- B2: `.login-screen` / `.notrunning-screen` / `.drop-overlay` scrims changed from a hardcoded
  dark rgba to `color-mix(in srgb, var(--bg) 82-88%, transparent)` so they track the theme.
- evidence: re-audit dropped journal contrast fails 15 -> 0 on every light theme (194 -> 28
  total, the 28 being the by-design decorative #home-clock, 2/theme). login probe on blossom:
  scrim now `color(srgb 0.98 0.96 0.96 / 0.82)` (light) with dark text -> readable.
- tests: tests/js/contrast.test.mjs (11) + tests/pw_theme_contrast.py (PASS, 7 light themes x
  4 views + login). node suite 27/27.
- known-minor (NOT #39, tracked separately): `.hc-mode.active` and other accent-on-accent-tint
  active chips read ~2.4 on the palest accent (solarlight) — legible + clearly marked; a global
  accent-legibility pass is out of scope for the journal/login fix.

## RESOLVED — B3 + B4 + B5 (appearance overhaul, #33/#34/#35)
plan: docs/plans/theme-appearance-overhaul.md
- B5 (#35): alles-scope settings split into general / security / themes / backup (was one
  "appearance" pane). aide-scope unchanged + verified no leak of the 3 new alles-only panes.
- B3 (#33): the full theme editor now renders INLINE in the themes pane (theme.js
  renderThemeEditorInto) — the "open theme editor" button is gone.
- B4 (#34): unified the two appearance systems. accent + mode now write into the appearance
  object (theme.setAccent/setMode) instead of the legacy aide-accent/aide-theme that the
  pre-paint script silently clobbered — so a picked accent now SURVIVES reload (the core bug).
  a fancy preset locks the mode + accent controls (with a note); the editor leads with a
  "default" tile (dark/light folded into it) that unlocks them; picking a preset turns its
  background on, and clears any stale pattern when it has none.
- verify: tests/pw_theme_overhaul.py 15/15 PASS (reorg nav, inline editor, lock, bg auto-on,
  accent-survives-reload, no console errors). visual QA of the 3 panes: clean, nothing cramped
  (the "clipped preset row" a screenshot fold — pane scrolls, editor foot reachable).
  contrast guard still PASS. node suite 27/27.
- also fixed 2 stale suite failures surfaced by the stage regression (NOT theme bugs):
  test_docs canvas/board test (those were removed in #36) + a journal prompt that wasn't a
  question (rephrased "Describe a small moment…" -> "What's a small moment…?").
