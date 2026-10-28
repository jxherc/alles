# field focus: the border brightens

replaces 0030's bottom line.

## context

0030 showed text-field focus as a 2px line painted inside the bottom edge. on rounded fields the
line curved into the corners and read as a second border laid over the first. the owner called it
out (2026-10-27): "do not have this type of design where one overlaps the other... have another
way of indication, its everywhere".

## decision

- text, search, email, url, telephone, password and number inputs, textareas, custom-select
  combobox triggers, locale-choice triggers and date fields show focus by turning their own border
  to `--k-field-focus`. no outline, no inset line, no ring.
- underline fields (date pickers, the compact rails) have only a bottom border, so that one line
  brightens.
- invalid fields keep `--k-field-focus` as the danger color, so focus on an invalid field turns its
  border red.
- wrapper-owned fields (composer, command search, inbox recipients, home capture, andromeda) keep
  their single wrapper indicator; the command search draws it as the divider under the input
  getting brighter instead of a box around the input row.
- actions, choices, sliders and color controls keep their focus rings.

## kept

- `--k-field-focus` stays the neutral muted color with at least 4.5:1 against page, panel and
  raised surfaces.
- forced colors still restores a system highlight.
