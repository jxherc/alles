# theme / appearance overhaul — stage plan (2026-06-23)

covers the user's bug-list items #33 (inline editor), #34 (lock/default/bg), #35 (settings reorg).
#39 (contrast) already shipped + tested (see docs/evidence/theme/findings.md). builds on the
audit there. tests run with `node --test tests/js/*.mjs` + the playwright guards.

## root cause (the dual-system fight, #34)
two appearance systems overlap: the advanced one (`alles-appearance` localStorage, theme.js
applyAppearance, persists /api/appearance) and a legacy simple one (`aide-theme` / `aide-accent`
localStorage, settings.js applyThemeMode/applyAccent, persists /api/settings theme+accent).
the pre-paint head script applies the advanced object and RETURNS, ignoring aide-accent — so the
simple accent picker is silently lost on reload whenever a full appearance is cached (always,
after the editor is ever used). fix: the simple controls must write INTO the appearance object.

## tasks

### T1 — theme.js: unify + inline API  (color/theme module)
- export `getAppearance()` (= loadLocal), `setMode(mode)`, `setAccent(hex|'')`, `BASE_PRESETS`.
- `setMode`: only meaningful on the default theme; swaps colors to dark/light preset base while
  KEEPING the current accent; sets preset 'dark'|'light'; bg stays none; save+apply.
- `setAccent`: overrides colors.accent (''=restore the active preset's own accent); save+apply.
- `renderThemeEditorInto(el, {onChange})`: renders the editor body (presets grid minus
  dark/light, colors, harmony, font, density, background, frosted, custom, import/export) inline
  into `el` and wires it; reuses _renderEditor/_wireEditor internals. no overlay/head/foot.
- keep `openThemeEditor()` working (thin modal wrapper) for any other callers.
- tests (tests/js/theme_api.test.mjs, jsdom-free pure asserts where possible): setMode keeps
  accent; setAccent overrides; getAppearance round-trips; BASE_PRESETS excludes fancy ones.

### T2 — settings.js: reorg panes + lock  (general/security/themes)
- split loadAppearancePane -> loadGeneralPane (name + toggles + sidebar vis),
  loadSecurityPane (password + auth), loadThemesPane (default mode/accent + inline editor).
- applyAccent/applyThemeMode delegate to theme.setAccent/setMode (kill aide-* writes; keep the
  /api/settings persist for cross-subdomain back-compat).
- lock: when getAppearance().preset is a fancy preset (not dark/light), disable the mode buttons
  + accent swatches/hex and show "set by <preset>" note; picking 'default' (mode) unlocks.
- _onPaneOpen + openSettings default pane -> 'general' for alles-scope.

### T3 — index.html: split the pane + nav  (markup)
- nav: rename appearance->general, add security + themes nav items (alles-scope only).
- split #s-pane-appearance into #s-pane-general (profile + chat-bar + sidebar cards),
  #s-pane-security (password card), #s-pane-themes (default theme card w/ mode+accent +
  `<div id="theme-editor-inline">`). remove the "open theme editor" button.

### T4 — style.css + cache bump  (styling)
- alles-scope nav rule -> general/security/themes/backup; hide the 3 in aide-scope.
- inline editor: `.te-inline-editor` reuses the .te-* inner styles (no overlay/modal chrome).
- locked-control styling (.theme-mode-row.locked, dimmed + not-allowed).
- bump sw.js VERSION+STAMP + index.html style.css?v= + _v together.

### T5 — verify
- node tests green; playwright: open alles-scope settings, see general/security/themes/backup;
  themes shows inline editor (no button); pick sakura -> mode/accent lock + petals bg on;
  pick default -> unlock; set accent -> reload -> accent persists (the #34 reload bug); contrast
  guard still PASS. screenshots to docs/evidence/theme/overhaul-*.
