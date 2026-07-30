# 0003: app-owned shell

Status: superseded by decision 0009

## decision

Every finished Alles app owns its visible shell. The app name and direct Home path live in the app
header or at the head of the app's local rail. Current context, tabs, and actions align with that
identity. A finished app must not retain the legacy `<app> / alles` breadcrumb above its own shell.
App identity appears once in that shell. A workbench must not repeat the app name as an oversized
landing title; content headings name the active section, document, date, selection, or task instead.

The normal identity row is 52px. A small layout may add one 44px context or tab row when the content
cannot fit safely beside the identity. Aide's task-context bar and the Docs, Files, and specialist
workbench headers are variants of this shared grammar.

## reason

The global breadcrumb made newer workbenches look nested inside an older product and disagreed with
the already approved Docs, Aide, and Files shells. Universal should mean predictable ownership,
navigation, sizing, and behavior, not forcing every app through one stale piece of chrome.

## consequence

New and redesigned apps hide the legacy global topbar, provide their own app identity and reachable
Home path, and test that boundary on desktop and small layouts. Older apps may retain the legacy crumb
until their own approved redesign; this decision does not authorize a mechanical rewrite of them.

Decision 0009 preserves one local app identity but moves the direct Home path into the persistent
universal navigation sheet. Local headers no longer repeat Home or an app picker.
