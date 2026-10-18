# owner review fixes

## context

The owner's own pass found what the scored audit missed: a switch with a purple knob sitting in a raised box, a Home shortcut whose hover tile hugged its text, a Settings sidebar where group labels and items read the same, and a setup status that turned red while it was only saving. They also asked for a model setup without suggestions, Startpage as the search engine, and an install path for DeepSeek Harness.

## decision

- Every switch shares the Settings switch: raised track, strong line, text-colored knob when on. The shared selected tile never paints behind a switch.
- A hover tile has real padding on all sides. When that padding would push a label off its content edge, the row moves back by the same amount instead.
- Settings groups read as headings: 12px bold muted labels with a seam and room above, items at 14px in the soft text color, the selected item boxed with the strong line.
- Status text that reports work in progress uses the muted color and sits next to the action it describes. Only a message left after the work fails is red.
- A message never pushes the control that caused it. Status sits beside or below its buttons; where it has to sit above them (server cards), its line is reserved. A cleared error keeps its height until the next render.
- Selected chips, segments and tabs in a row keep their width. Emphasis is a thin text stroke, not a weight change, so a click does not nudge the neighbours.
- Names and breadcrumbs that sit flush with their column answer hover with an underline, not a tile.
- Model setup is one alphabetical provider list with nothing pre-selected, plus "custom endpoint". Fields appear only for the picked provider. No preset buttons, no example placeholders. Local models lists only what is on this machine; anything else is pulled by name.
- Startpage is the default engine and is link-only: Alles never fetches it. Overviews use the keyless chain behind it, and the result list becomes one link to the same query on startpage.com.
- When DeepSeek Harness is missing, the coding connection view shows its official download and the Homebrew cask instead of a pairing form that cannot succeed.

## verification

The `ui-audit` gate now also checks, after each hover and click, that a hover tile keeps its label inset, that the clicked control does not move in the page (a scroll, or a form or panel that opens, does not count), and that in-progress status text is not drawn in the error color. The setup wizard is an audited route.
