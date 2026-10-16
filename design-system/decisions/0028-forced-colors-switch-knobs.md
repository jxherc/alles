# forced-color switch knobs

the switch track and moving knob must remain visible in browser forced-color mode. the shared switch families retain their existing 44px target and position-based on/off state.

only the knob opts out of automatic color replacement, using the user's system `CanvasText` color and `GrayText` when disabled. the surrounding control and focus indicator continue to follow forced colors. this preserves the rounded track and circular knob without introducing another border around the target.

verify both positions through keyboard activation and inspect desktop and phone screenshots. a visible track alone does not prove that the state is visible.
