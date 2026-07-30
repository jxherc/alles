---
name: ui-product-designer
description: Design or review responsive Alles product interfaces, user flows, screens, components, and implementation QA using the project KOKUEN design system. Use for new or changed app UI, navigation, settings, forms, dashboards, empty or error states, responsive behavior, accessibility reviews, HTML starters, and visual consistency work. Do not use for logos, standalone illustration, or promotional graphics.
---

# Alles UI product designer

Build complete product experiences from the user's task, not from a visual trend. Preserve Alles' vanilla JavaScript and CSS stack and treat the KOKUEN design system as the interface source of truth.

## Load the right sources

Always read:

- `design-system/PRODUCT.md`
- `design-system/PRINCIPLES.md`
- `design-system/FOUNDATIONS.md`
- `design-system/QA-CHECKLIST.md`

Then load only what the task needs:

- components: `design-system/COMPONENTS.md`
- complete flows and workspace shapes: `design-system/PATTERNS.md`
- copy: `design-system/CONTENT.md`
- accessibility: `design-system/ACCESSIBILITY.md`
- responsive behavior: `design-system/RESPONSIVE.md`
- motion: `design-system/MOTION.md`
- visual character: `design-system/BRAND.md`
- handoff format: `design-system/OUTPUT-CONTRACT.md`

Check `specifications.md` for shipped behavior and `docs/plans/afterlife/` for planned behavior. Never describe planned behavior as shipped.

Use `design-system/UI-BRIEF.md` when the request needs a structured brief. Use `references/screen-spec-template.md` for screen handoff and `references/component-spec-template.md` when a new shared component is justified.

## Work in this order

### 1. Define the problem

Write the user, situation, goal, obstacle, entry point, and successful ending. State only assumptions that materially affect the result.

### 2. Map the flow

Cover the main path, alternate path, recovery path, exit, and completion state. Remove steps that can safely be combined or automated.

### 3. Inventory screens and states

For every screen, identify its purpose, primary action, supporting information, and applicable states. Include loading, empty, partial, error, offline, permission denied, long content, small viewport, light theme, and reduced motion when relevant.

### 4. Reuse before inventing

Search `static/index.html`, `static/style.css`, and neighboring `static/js/` modules before proposing a component. Use semantic tokens. If composition cannot solve the problem, define a new component's purpose, anatomy, properties, variants, behavior, accessibility, responsive behavior, code mapping, and tests.

### 5. Choose the workspace shape

Use the documented list, timeline, workspace, or dashboard shape. Universal means shared rules, not identical screens. Preserve the specialist app's task and information architecture.

### 6. Specify interactions

For each control define trigger, feedback, state change, validation, recovery, keyboard behavior, focus destination, loading, and completion feedback. Never ship a control that only looks interactive.

### 7. Define reflow

Say what stays, grows, wraps, stacks, collapses, becomes scrollable, changes component, moves to overflow, or is removed. Do not describe mobile as a smaller desktop.

### 8. Use a starter only when it earns its cost

A standalone KOKUEN HTML starter under `docs/mockups/` is optional. Use one when it materially improves
design reasoning or lets the owner compare a risky direction. Keep it fake-data-only and local. It is
not an approval gate and never substitutes for the real UI, real behavior, or rendered verification.

### 9. Verify the rendered result

Test the real pointer and keyboard behavior, not only source code. Check desktop, mobile, 200% zoom, light and dark themes, reduced motion, focus order, overflow, clipping, console errors, and all applicable states. Run the project's focused tests before broader checks.

## Hard rules

- Use KOKUEN tokens instead of arbitrary colors, radii, spacing, type sizes, or motion.
- Never use visible native selects, dropdowns, checkboxes, radios, or context menus.
- Keep content visible if animation or JavaScript fails.
- Keep one clear primary action per screen.
- Prefer hierarchy and grouping over boxes, borders, or decorative rules.
- Do not add a font, icon pack, remote asset, framework, or animation library without explicit product fit and license, privacy, and performance checks.
- Do not hide important actions for visual cleanliness.
- Do not call a result accessible without testable evidence.
- Do not claim completion without fresh verification output.

## Output

For a material feature or rework, follow `design-system/OUTPUT-CONTRACT.md`. For a small correction, provide the goal, affected components and states, exact behavior change, responsive/accessibility impact, and verification evidence.
