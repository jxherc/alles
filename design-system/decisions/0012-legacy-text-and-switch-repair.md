# 0012: readable legacy text and independent switch targets

Status: accepted

## decision

Use foreground tokens for legacy text and opaque placeholders. Structural border colors are not
secondary text colors. Validate the actual foreground/background pair in both themes.

Shared rounded switches use a 44px interaction target containing a 42 × 24px track and centered
16px circular knob. The selected-state fill belongs to the track, not the whole target. A pending
save keeps keyboard focus and rejects repeated activation while exposing its busy state.

## reason

The real-app sweep found almost invisible legacy text, and the universal target-size rule enlarged
older switch tracks into malformed controls. Disabling a focused Andromeda switch during saving
also removed keyboard focus. Separating these concerns preserves existing layout and semantics.

## consequence

The foreground contrast gate and pointer/keyboard switch gate supplement the source lint audit.
Do not brighten all borders or shrink interaction targets to repair local rendering defects.
This restores the approved switch treatment; it does not introduce a new product direction.
