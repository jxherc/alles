# motion

Motion explains state, continuity, or direct manipulation. It never exists only to make the interface feel alive.

## tokens

- instant: 0ms for reduced motion or immediate state;
- fast: 120ms for hover, press, and small state changes;
- normal: 180ms for menus, panels, and local layout continuity;
- easing: `cubic-bezier(.2,.7,.2,1)` for normal interface motion.

## rules

- content is visible by default;
- never begin essential content at opacity 0;
- do not animate button position, scale, border radius, or shadow;
- prefer tone, transform of an already-visible element, or a stable clip with fixed caps;
- motion must be interruptible and leave the interface in a valid state;
- streaming, progress, and skeleton motion must not cause layout jumps or rebuild stable elements;
- seamless loops are rare and must have a static reduced-motion mark.

## reduced motion

Remove nonessential transforms and loops. Keep state changes immediate. Preserve the same information, focus movement, and completion feedback.
