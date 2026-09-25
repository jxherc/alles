# Minimal workspace

Status: implementation in progress, 2026-09-25. Supersedes the decorative greeting
and empty-state allowances in decision 0011 for Home and Docs.

The owner asked for simple shapes, plain text, a minimal layout, and less interface
churn. Existing features remain available; secondary tools appear in context.

## Layout contract

- Keep the existing universal launcher and all twelve destinations.
- Use a compact local header and a horizontal, contained section strip instead of
  a second full-height navigation column. The views control only toggles this
  strip; it must never hide document trees, file locations, or task filters.
- Keep one primary working surface. Editors and file browsers retain their useful
  list/detail split. On small screens, use the existing single-pane back paths.
- Put Home capture before the overview. Empty background-work sections stay out of
  the way; attention, schedule, errors and configured shortcuts remain reachable.
- Use plain, left-aligned document empty states and ordinary-sized headings.
- Overview regions use space and headings, not a wall of shaded cards. Do not
  hide permissions, unavailable sources, saving state, or recovery actions.

## Shared behavior

Retain existing APIs, identifiers, stored preferences and deep links. Section tabs
retain keyboard activation and selected state. Controls use system typography,
semantic colors, 44px targets and visible focus. No new fonts, icons or animation
dependencies. Errors preserve input and identify an available next action.

## Verification

Verify list, document and conversation layouts before applying the rules to the
specialists. Check desktop, phone, both themes, keyboard, reduced motion, zoom,
long content, overlays and persisted results. Automated WebKit is not physical
iPhone acceptance. Changes to these rules stop during the seven-day candidate trial.
