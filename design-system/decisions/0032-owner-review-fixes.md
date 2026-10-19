# owner review fixes

## context

The owner's own pass found what the scored audit missed: a switch with a purple knob sitting in a raised box, a Home shortcut whose hover tile hugged its text, a Settings sidebar where group labels and items read the same, and a setup status that turned red while it was only saving. They also asked for a model setup without suggestions, Startpage results inside Andromeda, and an install path for DeepSeek Harness.

## decision

- Every switch shares the Settings switch: raised track, strong line, text-colored knob when on. The shared selected tile never paints behind a switch.
- A hover tile has real padding on all sides. When that padding would push a label off its content edge, the row moves back by the same amount instead.
- Settings groups read as headings: 12px bold muted labels with a seam and room above, items at 14px in the soft text color, the selected item boxed with the strong line.
- Status text that reports work in progress uses the muted color and sits next to the action it describes. Only a message left after the work fails is red.
- A message never pushes the control that caused it. Status sits beside or below its buttons; where it has to sit above them (server cards), its line is reserved. A cleared error keeps its height until the next render.
- Selected chips, segments and tabs in a row keep their width. Emphasis is a thin text stroke, not a weight change, so a click does not nudge the neighbours.
- Names and breadcrumbs that sit flush with their column answer hover with an underline, not a tile.
- Andromeda sources sit on their own row under each claim instead of inside the sentence. The 44px target rule has no inline exception, and a 44px chip inside a line of text breaks the line. A source opens its quote in place, below the row, so nothing beside it moves.
- Follow-up suggestions are full-width-capable outlined choices; the follow-up field is the same one-line entry with a bottom rule as every compact field.
- Model setup is one alphabetical provider list with nothing pre-selected, plus "custom endpoint". Fields appear only for the picked provider. No preset buttons, no example placeholders. Local models lists only what is on this machine; anything else is pulled by name.
- Andromeda shows its own result list, from the keyless metasearch by default. Startpage is not an engine: it answers every server request with a captcha page, from home and cloud addresses alike, so Alles cannot fetch it, and a link out is not what the owner wants.
- A consent prompt (send this query or request to a remote model) uses a neutral confirm. Red stays for actions that delete, disconnect or send something for real.
- When DeepSeek Harness is missing, the coding connection view shows its official download and the Homebrew cask instead of a pairing form that cannot succeed.

## verification

The `ui-audit` gate now also checks, after each hover and click, that a hover tile keeps its label inset, that the clicked control does not move in the page (a scroll, or a form or panel that opens, does not count), and that in-progress status text is not drawn in the error color. The setup wizard is an audited route.
