# compact text-entry sizing

## context

Search and quick capture are frequent, bounded actions. Letting those fields inherit app-header height or a large textarea minimum creates empty visual weight and pushes useful work down the page. One-off resize handlers also drift across surfaces and can lose focus, overflow, and viewport behavior.

## decision

- Single-line search, capture, command, and composition entry uses the 44px product-control height.
- Short multiline capture or composition starts at 44px, grows to its content, and becomes internally scrollable at its declared cap or before it consumes the viewport.
- Components opt in with `data-kokuen-entry="compact"` or `data-kokuen-entry="autogrow"`; multiline behavior uses `static/js/text_entry.js`.
- A bounded wrapper and its input expose one focus treatment, never nested focus rectangles.
- Long-form writing, source, notes, mail-body, and other deliberate editor surfaces remain workspace-sized and do not opt in.

## first adopters

- Andromeda search is compact at rest, in results, on phone, and at 200% zoom.
- Home quick capture starts at one row and grows only when its content needs more room.

## verification

Check empty and multiline states, keyboard focus, error and disabled states where present, phone width, reduced motion, and native 200% zoom. A compact field may not gain empty height from an app header; an autogrow field may not grow beyond the visible viewport.
