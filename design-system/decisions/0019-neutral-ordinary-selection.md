# Neutral ordinary selection

Status: accepted for Settings, 2026-09-27. Other surfaces migrate in separate tested slices.

Ordinary selected and on states use the existing raised, strong-line, and text roles. Purple remains
available where it carries a distinct product or data meaning; permission, danger, success, focus,
and categorical data keep their own roles. This supersedes decision 0005 only where it allowed
purple for an ordinary selected state. Its neutral focus rule stays.

The first slice covers Settings mode buttons, Settings switches, Home settings switches,
and language choices. It does not change saved preferences. Theme mode exposes `aria-pressed` and
uses weight as well as tone; a switch still has a 44px target and a 42px rounded track, with a knob
that moves and changes tone. The selected language keeps its checked radio state and filled dot.
Other selected controls remain on their
current rules until their workbench is checked in both themes and on a phone. A global accent-token
swap would also recolor permissions, status, and data signals, so it is not part of this decision.

The next slice covers the appearance theme editor only. Preset tiles and font, density, background,
and harmony choices use raised surfaces, strong lines, readable text, and checked radio state. The
preview swatches still show each theme's real colors; Books' separate shelf selector keeps its existing
styling until that workbench is reviewed. Settings mode and accent changes refresh the inline editor's
draft so its next edit cannot reapply an older theme. Desktop and phone behavior in both themes,
keyboard selection, reduced motion, and 200% layout are checked on isolated data.
