# design QA checklist

Do not mark a design or implementation complete until every applicable item passes with fresh evidence.

## product and flow

- [ ] the user, goal, entry point, and successful ending are clear
- [ ] the primary task can be completed
- [ ] alternate, recovery, cancel, and interrupted paths work
- [ ] the design preserves shipped behavior or names an approved behavior change
- [ ] one primary action is clear without hiding necessary secondary actions

## system consistency

- [ ] the screen uses the correct list, timeline, workspace, or dashboard shape
- [ ] existing components were checked before a new component was added
- [ ] colors, type, spacing, radii, rows, and motion use documented tokens
- [ ] one universal shell trigger reaches all 3 primary spaces and exactly 9 specialist apps
- [ ] the shell sheet traps focus, supports Escape, makes the workbench inert, and restores focus
- [ ] local headers contain no duplicate Home or app-picker action
- [ ] header, route, local context, and settings placement match KOKUEN
- [ ] a finished app owns its local identity and does not show the legacy `<app> / alles` crumb
- [ ] the app name appears once and is not repeated as an oversized landing or workbench title
- [ ] there is no old global sidebar, accidental bold, decorative line, nested box clutter, or dead space
- [ ] no visible native select, dropdown, checkbox, radio, or context menu exists

## content and states

- [ ] labels name the action or destination plainly
- [ ] errors state the cause and next action
- [ ] loading matches the final layout
- [ ] empty, partial, error, offline, permission, disabled, and long-content states work where relevant
- [ ] realistic data fits without clipping or misleading truncation

## accessibility

- [ ] semantic roles, accessible names, reading order, and announcements are correct
- [ ] the full task works by keyboard with visible focus and sensible focus return
- [ ] meaning does not depend on color alone
- [ ] text and controls meet WCAG 2.2 AA contrast requirements
- [ ] 200% zoom and text resizing do not hide content or actions
- [ ] every discrete product control and interactive row has at least a 44px target
- [ ] reduced motion keeps every control and piece of content usable

## responsive and visual quality

- [ ] desktop and mobile use deliberate reflow, not simple scaling
- [ ] no horizontal page overflow, clipped text, overlap, or cut-off control exists
- [ ] parallel rows and columns align across variable content
- [ ] the hierarchy reads at a glance and secondary information stays readable
- [ ] resting, hover, pressed, selected, disabled, busy, invalid, loading, empty, permission, offline,
      stale, partial, and error states do not shift layout
- [ ] light and dark themes preserve hierarchy and contrast

## technical proof

- [ ] every visible control was clicked or used with a real pointer
- [ ] keyboard, mobile, zoom, theme, and reduced-motion checks were run
- [ ] browser console has no new errors
- [ ] focused regression tests pass
- [ ] broader checks were run in proportion to risk
- [ ] browser and integration tests used throwaway data, never the owner's normal data
- [ ] any optional HTML starter uses fake data and the exact real app was verified separately
- [ ] raw layout spacing was checked against 0, 4, 8, 12, 16, 24, 32, 48, and 64px; documented
      semantic or structural exceptions remain explicit

## final anti-slop pass

- [ ] every visual choice serves this product and could not be pasted unchanged into an unrelated app
- [ ] one unnecessary flourish was removed
- [ ] content is visible by default without waiting for animation
- [ ] no trend, generic template, or reference product was copied as a complete design
