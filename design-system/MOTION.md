# motion

Motion explains state, continuity, or direct manipulation, and every touch gets an answer: by the
owner's direction (decisions 0036 and 0040) alles should feel alive, so controls give under the
pointer, picked things slide, and things that arrive grow in.

## tokens

- instant: 0ms for reduced motion or immediate state;
- fast: 120ms for hover, press, and small state changes;
- normal: 180ms for menus, panels, and local layout continuity;
- easing: `cubic-bezier(.2,.7,.2,1)` for normal interface motion;
- press: 120ms down on `cubic-bezier(.23,1,.32,1)`, back on a spring (`--k-motion-press`);
- slide: 420ms on `--k-spring`, a css `linear()` spring with about 4% overshoot (`--k-motion-slide`).

## rules

- content is visible by default;
- never begin essential content at opacity 0;
- a press scales a control by 1 − min(0.035, 5px ÷ width) and springs back; hover changes tone,
  never position or size;
- the selection pill (tabs, segments, settings nav) slides; chips take the accent tint;
- menus grow from their corner, dialogs spring in, toasts rise and fade out, a view settles in
  with opacity only, totals count up, glyphs move one part on hover;
- prefer tone, transform of an already-visible element, or a stable clip with fixed caps;
- motion must be interruptible and leave the interface in a valid state;
- streaming, progress, and skeleton motion must not cause layout jumps or rebuild stable elements;
- seamless loops are rare and must have a static reduced-motion mark.

## reduced motion

Remove nonessential transforms and loops. Automated browsers get final numbers at once. Keep state changes immediate. Preserve the same information, focus movement, and completion feedback.
