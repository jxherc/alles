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
