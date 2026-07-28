# Decision — approve interface starters before implementation

- **Status:** accepted
- **Accepted:** July 13, 2026
- **Applies to:** every new Alles interface and every material app rework

## Decision

For each upcoming visual part or app rework:

1. make a small standalone HTML starter using the KOKUEN design rules;
2. let the owner try it and request changes;
3. treat it as approved only after the owner clearly approves it;
4. then implement the approved direction in the real vanilla JavaScript/CSS app.

The starter may use fake data and only the small local interactions needed to understand the flow. It
must stay primarily visual and must not change the real app, its data, or its backend behavior. An older
approval does not automatically approve a later rework.

Targeted bug fixes may proceed without a new starter only when they preserve an already approved
direction. They still need a focused regression test and rendered browser verification. A bug fix may
not be used to quietly introduce a new layout or app flow.

Every starter also follows these interface rules:

- do not show browser-default selects, checkboxes, radios, or other unstyled controls;
- use KOKUEN controls with correct keyboard behavior and accessibility roles;
- keep normal interface text and controls at 14 pixels or larger, conversation text at 16 pixels or
  larger, and helper text at 12 pixels or larger;
- smaller text is reserved for citations, timestamps, and other secondary metadata;
- test desktop and mobile layouts, keyboard use, reduced motion, console errors, and image fallbacks
  before presenting the starter.

## Why

This makes visual decisions cheap to change and prevents time from being spent implementing an
interface the owner does not want.

## Approved and implemented starters

- `docs/mockups/afterlife-navigation/home.html` — approved direction; implemented in Home
- `docs/mockups/afterlife-navigation/andromeda.html` — approved direction; implemented in Andromeda
- `docs/mockups/afterlife-navigation/andromeda-results.html` — approved direction; implemented in Andromeda results
- `docs/mockups/afterlife-navigation/aide-projects.html` — compact KOKUEN Aide canvas with a
  desktop-open split-sidebar control, mobile-closed overlay, loose conversations directly under Tasks,
  exact conversation/Project top-bar context, stronger Tasks/Projects hierarchy, text-first Brain/Skills/
  Reminders with restrained icons inside the primary navigation, background checks in Settings, expanding Search, text-only Settings plus Home,
  text-only permissions, 1-pixel borders with tight
  corners, label-free messages, steps before answers, a centered five-message rail with pointer-proximity
  scaling and scroll-aware current state, aligned speech/send controls, and a real right task-tools sidebar
  whose Terminal state shows only the terminal; approved direction and implemented in Aide
- `docs/mockups/afterlife-navigation/apps.html` — approved direction and implemented as the current Apps directory

## Next starters

- Phase 6 creates a fresh Docs starter before changing the real Docs interface.
- Any new Apps-directory polish gets a fresh or revised starter first. The requested pass is a small
  consistency update, not a new app architecture.
