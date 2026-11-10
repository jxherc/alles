# a line under a label must prevent a mistake

## context

owner (vault, dont.md): "no intro text. let the thing teach itself through layout, order and good
labels." and "no helper text under headings, labels or toggles unless it prevents a real mistake."
his example: a "dark mode" switch with "switch between light and dark themes" under it.

a read of the settings panes found 126 helper lines on screen. most restated their label or their
pane title, described the feature, or said "saved" and "loaded" for good.

## decision

- a line under a pane title, card title, label or switch stays only when it does one of these:
  - says data leaves this machine, or who can see it
  - warns about something that can't be undone, or that costs money or tokens
  - gives a required input format ("one per line", "{query}")
  - gives setup steps for another service
  - says why a control is disabled, and shows only while it is disabled
  - says why a key is asked for when the provider has no sign in
- everything else goes: lines that repeat the label, describe the feature, narrate, or introduce
  the pane. no pane intro paragraphs.
- when a label only makes sense with its line, the label is rewritten so it stands alone (short plain
  words, lowercase: "read replies aloud", not "auto-play TTS" + "speak AI replies automatically").
  the line is then deleted. the new label changes in the english source and all 8 locale files.
- a value the browser detects goes into the option that uses it ("automatic (CA)"), not into a line
  under the label.
- a status line shows nothing at rest. it shows unsaved changes, saving, or a failure with what to
  do. "saved" clears itself after about three seconds, and a "loaded" line does not exist. a status
  that can appear sits where it shifts nothing.
- a line that stays is role 14 (0.875rem, 16px on touch), muted, 4px (`--k-space-1`) under what it
  belongs to. one rule draws it (`.s-card-hint`, `.s-toggle-desc`, `.s-field-note`, `.s-role-desc`).
