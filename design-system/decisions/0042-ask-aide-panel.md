# ask aide from any app

## context

The owner picked "aide keeps its full app, and a panel slides in from the right on any screen
(one key) so you can ask about what you're looking at" during the revamp (2026-10-21). Until
now each app had its own handoff (home's "ask Aide about today", docs' ask, andromeda's explain)
that left the app for Aide's chat.

## decision

- **one panel, every app.** An "ask" button with the sparkle glyph sits beside the app name;
  `Ctrl+.` toggles it (a free, unreserved combination; Alt+letter fails on mac keyboards). It
  is in the shortcut registry, rebindable, and listed in aide's help.
- **a floating layer.** 420px from the right edge with 8px clearance, radius 16, the raised tone
  and the one floating shadow (decision 0041). Full screen on a phone. It slides in over 280ms
  and doesn't move under reduced motion. Esc stops an answer, then closes; focus returns to
  the button.
- **what aide sees is shown.** A line above the composer says "sees plan · agenda"; one tap
  turns screen sharing off for the next question. The panel sends a plain chat turn (`simple`,
  no tools) with the app, view and up to 3,000 characters of the screen's words. Aide itself
  and the vault have no panel, and the vault never shares its screen.
- **same session in aide.** The answer streams into the panel; "continue in aide" opens that
  session in the full app.

## kept

- The existing handoffs stay; they carry richer context (a day plan, selected notes, results).
- The 44px target on every panel control.
