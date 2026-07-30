# 0009: establish the KOKUEN v5 universal runtime

Status: accepted

## decision

Use one persistent 52px structural rail with one 44px global navigation trigger on every authenticated
Alles surface. The trigger opens one modal sheet containing Home, Aide, Andromeda, and exactly the nine
specialist apps: Plan, Inbox, Docs, Files, Library, Health, Finance, Vault, and Server. The universal
command consumes the same destination registry.

Centralize primitive identity, the 14-state vocabulary, busy repeat rejection, overlay focus
boundaries, menus, and tabs in `static/js/kokuen.js`. Keep the custom single-select implementation in
`static/js/dropdown.js`, governed by the same stable contract. Store the full machine-readable contract
in `design-system/components/contracts.json`.

Local app headers show the app name once and contain only local context and actions. Remove duplicate
Home buttons, repeated launchers, oversized app-name titles, and `<app> / alles` breadcrumbs.

## reason

KOKUEN v3 established the visual language but left cross-app movement duplicated in app-owned headers
and left primitive behavior distributed without one auditable state contract. A universal trigger
makes movement predictable while leaving each app free to use its correct list, timeline, workspace,
or dashboard shape. A runtime contract gives every app the same minimum target, state, focus, motion,
and boundary behavior without moving product authority into a framework.

## alternatives considered

- Keep Home buttons and app pickers in every app header. Rejected because they duplicate global
  movement, consume local context space, and drift between apps.
- Restore a conventional wide global sidebar. Rejected because it crowds the quiet workbench and
  repeats local app navigation.
- Build separate navigation registries for the sheet and command. Rejected because destinations and
  naming would diverge.
- Add a frontend framework. Rejected because the vanilla runtime can centralize the contract without
  changing Alles architecture or adding a dependency.

## consequences

All discrete product controls and interactive rows have a 44px minimum target. The runtime exposes
resting, hover, pressed, selected, disabled, busy, invalid, loading, empty, permission, offline, stale,
partial, and error. App modules keep their existing API and data ownership. Future components must add
or update a machine-readable contract and prove pointer, keyboard, responsive, reduced-motion, and
forced-colors behavior before adoption.
