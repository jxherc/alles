# KOKUEN design system

KOKUEN is the shared interface language for Alles. It keeps every app coherent without forcing every app into the same layout.

Status: the system contract is active for design and implementation work. Standalone starters are
optional reasoning tools; current source, shipped behavior, and rendered real-application proof remain
authoritative.

## source order

1. user and product requirements
2. safety, privacy, and accessibility requirements
3. `specifications.md` for behavior that exists now
4. these design-system rules and tokens
5. relevant KOKUEN starters and existing working components
6. platform conventions
7. a new documented decision

Call out conflicts. Do not silently pick one.

## map

- `PRODUCT.md`: users, jobs, product spaces, and constraints
- `PRINCIPLES.md`: decision rules
- `BRAND.md`: visual character and forbidden directions
- `FOUNDATIONS.md`: tokens, type, color, spacing, shape, and layout
- `COMPONENTS.md`: reusable control contracts
- `PATTERNS.md`: shells, workspace shapes, and complete states
- `CONTENT.md`: interface writing
- `ACCESSIBILITY.md`: WCAG and interaction requirements
- `RESPONSIVE.md`: reflow behavior
- `MOTION.md`: purposeful motion and reduced motion
- `OUTPUT-CONTRACT.md`: required design and handoff output
- `QA-CHECKLIST.md`: completion gate
- `UI-BRIEF.md`: the input template for material UI work
- `tokens/`: machine-readable primitive, semantic, and component tokens
- `decisions/`: reasons behind system-level choices

## change rule

Reuse first. Change a shared component only when the current contract cannot serve the user task. Record system-wide changes in `decisions/`, update the token or component source, and test every affected state.
