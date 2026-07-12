# Afterlife Phase 3 — product shell, Today, Aide Projects, and Settings

- **Status:** in progress
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** Phase 2 delivered
- **Checkbox rule:** `[x]` means implemented and freshly tested, not merely discussed.

## Goal

Give Alles one clear daily shape without removing any existing feature.

At the end of this phase:

- Today is the useful default home and works without a model;
- Today, Aide, and Andromeda form the permanent three-space shell when their feature gates allow it;
- every current app stays reachable in at most two actions through shortcuts, search, or the app drawer;
- General and folder Projects appear inside Aide instead of becoming another app;
- Settings has one clear home for product, model, memory, connection, privacy, and server choices;
- old bookmarks, view names, and subdomains still land on the expected feature.

The first release changes navigation and composition. It does not delete old tables, routes, APIs, or
specialist views.

## Design direction

The shell is a **quiet control rail** for one owner who uses Alles every day.

- **Feel:** calm, precise, compact.
- **Palette:** keep the existing near-black surfaces, off-white text, restrained purple accent, muted
  gray, and existing success/warning colors.
- **Type:** keep the current typography until the local/system-font review; use weight, spacing, and
  alignment instead of adding a display font.
- **Density:** medium on desktop and touch-safe on mobile.
- **Motion:** one short destination transition at most; no decorative movement; respect reduced motion.
- **Signature:** the three permanent spaces read as one narrow route line, with the active space marked
  by a small accent notch. The rest of the shell stays visually quiet.

The layout preserves the current vanilla JavaScript/CSS stack, existing icons, themes, subdomain
support, command palette, and specialist app views. No new font, image, icon pack, framework, or remote
asset is part of this phase.

## 3A — shell and app drawer

- [x] Load the strict server feature flags once during boot and keep safe all-off behavior when the
  runtime endpoint is unavailable.
- [x] Build the three-space shell behind `afterlife_shell`.
  - Today is visible when `afterlife_today` is enabled.
  - Aide keeps working but is promoted only after its shell route is ready.
  - Andromeda is shown only when `afterlife_andromeda` is enabled.
  - Jarvis never becomes a fourth permanent destination.
- [x] Add a keyboard-accessible app drawer for specialist destinations and the legacy launcher.
- [x] Keep every current app reachable in at most two actions.
- [x] Keep global search on `Cmd/Ctrl + K` and Settings on `Cmd/Ctrl + ,`.
- [x] Keep the current launcher reachable as **All apps** during the compatibility window.
- [x] Preserve single-host and subdomain navigation, authentication handoff, modified-click new tabs,
  focus return, mobile drawer behavior, and reduced motion.

### 3A gate

With all flags off, the current interface is unchanged. With the shell flag on, unavailable spaces are
not advertised, every current app is reachable in at most two actions, and navigation works on the
apex, app subdomains, a single host, desktop, mobile, and keyboard only.

Current 3A evidence: four focused JavaScript flag tests and the existing subdomain tests pass. Isolated
Playwright checks prove flag-off compatibility plus flag-on desktop and 390×844 layouts, keyboard focus
loop and return, app-drawer access to all 20 current apps, single-host Aide and Tasks navigation, reduced
motion, no horizontal overflow, and zero console, page, or server errors.

## 3B — deterministic Today

- [x] Make Today the apex default only when `afterlife_today` is enabled.
- [x] Compose five ordered sections:
  - **Needs you** — approvals, choices, conflicts, uncertain outcomes, and failed work;
  - **Today** — events, due and overdue tasks, reminders, habits, renewals, and important dates;
  - **In progress** — active Jarvis runs and long Aide work;
  - **Briefs** — completed research, news, and scheduled reports;
  - **Shortcuts** — pinned apps, Project folders, approved folders, and saved searches.
- [x] Keep core cards deterministic and useful with no configured model.
- [x] Add clear loading, empty, partial, offline, and error states per section.
- [x] Keep Activity available as the compatibility History view.
- [x] Add **Customize Today** for visibility, order, density, and shortcuts.
- [x] Store customization safely and preserve older launcher tile preferences during the transition.
- [x] Keep quick capture only where it supports the daily flow; do not keep a second competing Aide
  composer on Today.

### 3B gate

Today shows useful synthetic data without a model, survives one failed data source, explains empty and
offline states, restores customization after restart, and never hides an approval or uncertain result.

Current 3B evidence: the flag-gated Today response and interface have the five stable sections. Focused
tests cover empty shape, flag-off compatibility, pending and expired prompts, failed delivery,
uncertain and active runs, completed briefs, habits, and saved customization without a model. Isolated
desktop and 390×844 browser passes cover default routing, the legacy launcher, order/visibility/density
persistence, keyboard focus, reduced motion, error/retry state, no overflow, and zero unexpected
console, page, or server errors.

## 3C — Aide Projects rail

- [x] Show **General** and folder-backed Projects in the Aide sidebar.
- [x] Group each Project's threads beneath it without creating a Projects app.
- [x] Show Available, Folder missing, and Relink required clearly.
- [x] Keep active and recent Jarvis tasks visible in the same Aide shell without making Jarvis global
  navigation.
- [x] Preserve Project selection across Chat/Jarvis mode changes and page reloads.
- [x] Keep current Project workspace actions and thread history reachable during the migration.

### 3C gate

General and every Project can open by keyboard, a missing folder can be relinked without losing threads,
and no Project is silently pointed at another folder or widened into a cross-app membership container.

Current 3C evidence: focused JavaScript tests cover General, folder states, expanded threads, Jarvis
status, keyboard opening, and moving a thread back to General. Isolated desktop and 390×844 browser
passes use real Available, Folder missing, and Relink required Projects; preserve the selected Project
thread and hash across mode changes and reload; keep the existing Project workspace reachable; show a
mocked active Jarvis run; respect reduced motion; fit without overflow; and report no console or page
errors.

## 3D — consolidated Settings

- [ ] Move Settings into the Alles/profile menu while keeping `Cmd/Ctrl + ,`.
- [ ] Group existing controls into clear sections:
  - General and appearance;
  - Aide and default chat behavior;
  - Models and providers;
  - Memory and owner instructions;
  - Connections and MCP;
  - Privacy and security;
  - Notifications and language;
  - Server, backups, and data.
- [ ] Add separate defaults for Aide Chat, Andromeda overview, and Aide → Jarvis.
- [ ] Reuse the Phase 1 model resolver, endpoint catalogs, refresh status, and unavailable-model flow.
- [ ] Keep global, per-endpoint, and manual model refresh behavior consistent.
- [ ] Show accepted provider account connections with quota/credits warning and Disconnect; do not add
  an OAuth flow rejected by the Phase 1 spike.
- [ ] Add **Automatic tools** and **Answer only** as the default chat behavior choice.
- [ ] Keep Memory Off/Ask/Auto, incognito exclusion, memory review, and owner instructions separate and
  understandable.

### 3D gate

The effective model and behavior choices match everywhere, survive restart, and degrade per endpoint.
One unavailable provider does not break another or leave a misleading enabled control.

## 3E — compatibility redirects and gate

- [ ] Add explicit aliases for old names, views, and subdomains:
  - Home → Today;
  - System → Server;
  - Secrets → Passwords;
  - Money and Subs → Finance;
  - Notes and Journal → Docs;
  - personal-media Gallery and Photos → Files → Photos;
  - AI-image Gallery → Aide → Creations;
  - old Cowork or standalone Jarvis identifiers → Aide with Jarvis selected.
- [ ] Preserve current deep links and query/hash state through redirects.
- [ ] Record the compatibility window; do not remove an alias in this phase.
- [ ] Add focused source, unit, API, JavaScript, and browser tests for flags, routes, focus, keyboard,
  mobile layout, reduced motion, empty/error/partial states, and all old bookmarks.
- [ ] Run the full Python and JavaScript suites with throwaway `ALLES_DATA`.
- [ ] Run isolated browser checks at representative desktop and mobile widths with console and server
  error inspection.
- [ ] Re-run backup/restore checks for any new persisted customization or setting.
- [ ] Run Ruff checks without rewriting unrelated legacy files.

## Phase 3 exit gate

Phase 3 is delivered only when all of these are true:

1. Today works without AI and does not hide approvals, failures, conflicts, or uncertain work.
2. Every current app is reachable in at most two actions.
3. Unavailable permanent spaces are not advertised before their feature flag and gate pass.
4. General and folder Projects live inside Aide and keep their existing threads and folder safety.
5. Model, provider, memory, and default-behavior settings show one consistent effective state.
6. Every supported old bookmark, view name, and subdomain still lands on its feature.
7. Desktop, mobile, keyboard, reduced-motion, offline, empty, partial, and error checks pass with isolated
   data and no new console or server errors.
8. No existing specialist behavior, private data boundary, recovery path, or safe network default is
   removed or weakened.

## Not part of Phase 3

- the final Aide Chat/Jarvis interaction model;
- the Andromeda search result page or managed SearXNG;
- Discord pairing, News collection, or external delivery channels;
- Docs, Files, Finance, or other specialist data migration;
- removal of legacy routes, APIs, tables, subdomains, or the launcher.
