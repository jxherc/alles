# accessibility

Target WCAG 2.2 Level AA as the baseline. Automated checks help but never replace keyboard, zoom, screen-reader, contrast, and human visual review.

## semantics and names

- use the correct native semantic element when it does not violate the product-control rules;
- use ARIA only to express a custom control's real behavior;
- every control has a stable accessible name;
- headings and landmarks follow the visible hierarchy;
- status, error, and progress changes are announced at the right urgency.

## keyboard

- every task works without a pointer;
- focus order follows reading and task order;
- focus is always visible and never clipped;
- menus, tabs, radio groups, dialogs, and switches follow their ARIA keyboard patterns;
- closing a temporary surface returns focus to the trigger;
- focus is never trapped outside a true modal.

## contrast and meaning

- normal text, large text, controls, focus, and state indicators meet AA contrast;
- color never carries meaning alone;
- muted and quiet text remains readable in both themes;
- disabled state remains legible and exposes why it is unavailable.

## size and zoom

- core text never falls below the foundation roles;
- mobile targets are 44px when space allows;
- 200% zoom preserves content, actions, and reading order without two-dimensional page scrolling;
- text resizing does not clip fixed-height controls.

## motion

Respect `prefers-reduced-motion`. Never require animation to reveal content, announce state, or complete a task. Stop nonessential loops and use static equivalents.

## forms and authentication

Use visible labels, programmatic error association, preserved input, and useful recovery. Do not block paste or password managers. Authentication must avoid memory-only puzzles and provide an accessible alternative when a method fails.

## testing record

Record what was tested manually and what still requires implementation testing. Never write `accessible` as a visual opinion.
