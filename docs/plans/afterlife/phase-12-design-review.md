# Phase 12 design review - exact approval starters

- **Status:** exact starter approved on 2026-07-24 and implemented in the real application on 2026-07-25
- **Date:** 2026-07-24
- **Scope:** approved standalone starters plus the matching runtime implementation and rendered audit
- **Runtime impact:** nine canonical workbenches, shared navigation/focus fixes, Andromeda verification,
  secure Server management, and canonical Home customization
- **Git impact:** not staged, committed, or pushed

## Direction

One continuous workbench: calm, precise, grounded, and recognizably KOKUEN. Apps preserves the established
full-screen grouped format instead of replacing it with a stripped directory. The structural signature is
the compact 52px identity row connected directly to local navigation and work. System type, warm black,
off-white, restrained active purple, and neutral focus carry the interface. Data and controls dominate;
there are no landing heroes, repeated giant app names, decorative cards, glows, gradients, or remote
assets.

## Exact files for approval

- `docs/mockups/afterlife-phase12/workbenches.html`: the nine-entry grouped Apps directory and all nine
  representative workbenches.
- `docs/mockups/afterlife-phase12/andromeda.html`: one-search idle view, results, compact cited answer,
  normal results, and independent verification states.
- `docs/mockups/afterlife-phase12/server.html`: management information architecture, separate answer and
  verifier settings, owned-only authority, policy editing, validation, and typed confirmation.
- `docs/mockups/afterlife-phase12/starter.css`: isolated KOKUEN tokens, desktop/compact/phone reflow, and
  light/dark behavior.
- `docs/mockups/afterlife-phase12/starter.js`: local prototype interactions only.
- `docs/mockups/afterlife-phase12/verify.py`: isolated rendered behavior gate.

The owner approved these exact files on 2026-07-24. Approval does not extend to later visual changes
automatically.

## Product and flow proof

- Apps keeps the earlier three-group format and shows exactly Plan, Inbox, Docs, Files, Library, Health,
  Finance, Vault, and Server.
- Each destination owns one compact identity row, names the app once, and links Home from that row.
- Browser Back returns a workbench to Apps. Files/Gallery has an explicit phone back action and matching
  history behavior.
- Andromeda has no visible logo or repeated app name. Idle shows one centered search. The full-width search,
  compact cited answer, and normal results share one 920px axis, while a major gap, explicit Web results
  heading, and structural boundary keep ordinary links visually independent from the AI answer. Textual
  Home is the rightmost header action with a stable outer gutter.
- Andromeda highlights only the decisive evidence-backed substring inside the key answer, such as `3.50.4`;
  ordinary web-result rows use whitespace instead of divider lines.
- Andromeda keeps the answer/results usable in loading, partial, offline, error, long-query, corrected, and
  verifier-failure states.
- Server covers Overview, Services, Search and models, Backups and storage, Updates, Logs and activity,
  and Access policy. Background verification is independently toggleable and defaults to
  freshness-sensitive.
- Server Overview preserves the original neofetch host readout and btop-style live resource monitor. Its
  process table spans the monitor width and uses the available vertical space for a longer list. The
  management workbench adds structure around those views; it does not replace them with generic metrics.
- The runtime Server migration reuses `static/js/system.js` directly. The starter's fake-data snapshot uses
  that module's exact Darwin logo and btop process columns rather than inventing a replacement graphic.
- Server policy defaults to `owned_only`. The prototype editor accepts only the bounded schema, shows the
  canonical `${ALLES_DATA}/server-policy.json` path, rejects a wrong confirmation phrase, and returns focus
  after save or cancel.

## Design-system and anti-slop recheck

- No visible native select, checkbox, radio, dropdown, or context menu exists.
- Focus and active selection use separate tokens. Focus is a stable neutral 2px edge; active selection is
  the only restrained purple role.
- Dark and light normal-text token pairs meet WCAG AA. The lowest checked normal pair is light active text
  on the raised surface at 4.97:1.
- No external font, icon pack, remote image, gradient, background glow, glass, hover lift, entrance reveal,
  oversized specialist-app heading, badge wall, floating card, or default CTA pair is present. The larger
  `apps` label belongs only to the established directory composition the owner chose to preserve.
- Content is visible by default. The only transform-hidden control is the standard skip link until keyboard
  focus.
- Surfaces use squared KOKUEN geometry, spacing, tonal elevation, and real information hierarchy instead of
  nested card decoration.
- One unnecessary Gallery gradient and the duplicate Andromeda idle search were found in rendered review
  and removed before this handoff.
- The corrected nine-app directory was re-rendered after restoring the three groups. An inherited 8px row
  overhang was found through desktop inspection and removed; the directory and page now have equal client
  and scroll widths.

## Fresh verification

Checked:

- JavaScript syntax;
- all exact starter buttons with real Playwright pointer clicks;
- Browser and independent Chrome/Computer Use navigation;
- exactly nine Apps buttons in three groups of three, including Library;
- keyboard radio and switch behavior, focus visibility, focus return, and live announcements;
- desktop 1280x720, compact 760x800, phone 390x844, and 200% zoom;
- dark/light themes and reduced motion;
- Apps/workbench history, Files/Gallery explicit back, Andromeda states, Server policy confirmation;
- no horizontal page overflow and no browser console/page errors;
- loading, empty, partial, offline, error, permission, disabled, correction, and long-content examples.

Command:

```text
python3 docs/mockups/afterlife-phase12/verify.py
phase 12 starters: rendered behavior checks passed
desktop 1280x720, compact 760x800, phone 390x844, 200% zoom, reduced motion
```

Runtime checks completed after approval:

- the real Apps surface exposes exactly nine destinations in three groups and canonical Home pins use the
  same nine workbenches;
- legacy routes preserve their intended subsection, including Days to Plan/Countdowns, Gallery to Files,
  Journal to Docs, and System/Watch/Activity to Server;
- Files/Gallery explicit back, browser Back, keyboard tabs, and phone reflow work without duplicate chrome;
- the real Andromeda gate covers eight initial results, capped continuation, compact cited answer,
  separately confirmed background verification, failure states, desktop/mobile alignment, and clean logs;
- the Server policy service and API cover owned-only defaults, schema validation, symlink/ownership/mode
  rejection, atomic owner-only writes, typed widening confirmation, and exact policy-path binding;
- Server Overview still uses the original `static/js/system.js` neofetch and btop renderer, with the process
  table occupying the available width;
- the full real Phase 8 gate passes desktop/mobile, dark/light, keyboard, focus return, reduced motion,
  control size, type floor, contrast, overflow, errors, and compatibility routes;
- Home Settings now renders all nine canonical app switches and passes desktop/mobile save, restore,
  reflow, contrast, and deliberate failure-state checks;
- all 534 JavaScript tests pass, focused Python/cache/route/security suites pass, and browser warning/error
  logs are empty.

Final capstone evidence: the clean isolated repository-wide suite ran 5,488 tests in 3,078.444 seconds with
15 documented skips and zero failures or errors. The full anti-slop law and applicable design-system QA
checklist were re-read point by point against fresh rendered evidence; no additional Phase 12 defect
remained after the recorded mobile workbench and Home Settings corrections. Ruff was unavailable in the
worktree environment. External model/provider quality, network availability, OS supervisor actions, and
physical-device behavior remain environment-dependent and are not converted into local guarantees.
