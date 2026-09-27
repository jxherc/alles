# App-name switcher

Status: accepted, 2026-09-27.

The visible app name opens the existing universal navigation sheet. One button moves between the
active app headers; the persistent 52px rail is removed. The sheet still lists the same 12
destinations and keeps its focus trap, Escape and scrim dismissal, inert background, and focus return.
The universal command and local app navigation stay separate.

This replaces decision 0009's structural-rail placement and its ban on a global action in local
headers. It keeps 0009's one-trigger, one-registry, and accessibility rules. Decision 0012's
compact-workspace goal and all 12 destinations stay. Decision 0013's rail-relative dialog insets
become full-viewport dialogs; its save, retry, focus, and recovery requirements do not change.
Decision 0010's server-monitor and meaningful data-color exceptions remain. Decision 0005's
neutral focus rule remains; its purple selected-state allowance is a separate monochrome follow-up,
not silently changed by moving the switcher.

The trigger keeps its DOM ID and moves rather than being copied, so Home, Aide, Andromeda, the nine
workbenches, deep links, and single-host transitions share the same control. Local app names remain
accessible as headings where their sections need a heading, but only the switcher is shown visually
as app identity. Settings stays a modal over the current app; leaving it returns to that app.

The isolated browser gates covered desktop and phone, both host shapes, keyboard focus return,
old deep links, dark/light, reduced motion, and settings/overlay geometry. The 720px layout check
is equivalent to a 1440px viewport at 200% zoom for responsive layout; native browser zoom and
assistive-technology certification remain separate checks.
