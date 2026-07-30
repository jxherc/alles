# output contract

Use the full package for a new feature or material rework. Scale it down only for a targeted correction.

## required package

1. **problem:** user, situation, goal, obstacle, and successful ending
2. **assumptions:** only missing facts that affect the direction
3. **flow:** main, alternate, recovery, exit, and completion paths
4. **screen inventory:** every screen, panel, dialog, and important state
5. **screen specifications:** purpose, hierarchy, layout, components, actions, content, states, reflow, and accessibility
6. **component mapping:** reused components, variants, and justified additions
7. **state matrix:** loading, empty, partial, success, warning, error, disabled, offline, permission, and interrupted states as applicable
8. **responsive specification:** what stays, wraps, stacks, collapses, scrolls, moves, changes, or disappears
9. **interaction specification:** trigger, feedback, validation, focus, keyboard, loading, recovery, and completion
10. **final copy:** headings, labels, help, errors, confirmations, and statuses
11. **decisions:** reasoning, tradeoffs, and rejected alternatives
12. **QA:** testable design and implementation checks

## Alles implementation artifact

For a new app interface or material rework, use a standalone KOKUEN HTML starter under
`docs/mockups/` only when it improves design reasoning or de-risks a material choice. It must use fake
data, local-only interactions, no owner data, no backend changes, and no remote assets. It is optional,
not an approval gate, and never replaces verification of the real app.

## handoff quality

Use semantic token and component names, exact interaction behavior, realistic content, and acceptance criteria. Avoid a screenshot-only handoff and avoid claiming behavior that was not tested.
