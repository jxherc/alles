# responsive behavior

Responsive design is content-priority reflow. Breakpoints follow the point where the current layout stops working, not a device brand.

## reference ranges

- large: above 820px, multi-pane and full toolbar when content fits;
- compact: 621px to 820px, fewer simultaneous panes and lower-priority actions in overflow;
- small: 620px and below, one main pane and 44px touch targets.

These are defaults, not permission to keep a broken layout until the exact pixel boundary.

## shell

- preserve the 52px app-owned identity row;
- keep app identity in that row; never add a second oversized app-name title at any width;
- never reintroduce the legacy `<app> / alles` crumb as a mobile fallback;
- hide optional middle context before identity or actions become cramped;
- keep `home`, the current app identity, the primary action, and Settings reachable;
- when local tabs need their own small-layout row, make it 44px and horizontally contained rather than
  shrinking labels or causing page overflow;
- move low-priority actions into a custom overflow menu;
- never expose horizontal page scrolling.

## workspace shapes

- list: keep the title and main filter, let secondary columns hide by priority, never shrink titles into unreadable text;
- timeline: move local navigation into a horizontal strip or one active view; keep the time surface scroll inside its region;
- workspace: show one active pane on small screens with a clear back path and preserved selection;
- dashboard: stack comparable regions while keeping labels and values aligned.

## content behavior

Define each region as fixed, flexible, wrapping, stacked, collapsed, internally scrollable, replaced, or removed. Long labels wrap when meaning matters and truncate only when the full value remains available.

## mobile state

Opening and closing a panel must preserve the user's task, scroll, selection, and input. Browser Back follows the visible navigation state when practical.

## verification sizes

Check at least one wide desktop, one narrow desktop or tablet, and one phone width. Also check 200% zoom separately; it is not equivalent to a phone viewport.
