# form-field focus

replaced by 0045: the field's own border brightens instead of a bottom line.

## context

The shared primitive outline overrode the login and Settings fields' existing
bottom boundary, drawing a two-pixel rectangle as soon as text entry received
focus. Several older app selectors repeated the same all-around input outline.

## decision

- Text, search, email, URL, telephone, password and number inputs, plus textareas,
  custom-select combobox triggers and locale-choice dropdown triggers keep their
  resting boundary and use one inset bottom line on visible focus.
- The shared rule owns this treatment across legacy app selectors. It does not
  change sizes, padding, input behavior, or authentication.
- Action buttons, checkbox/radio choices, sliders, date inputs and color controls retain their existing
  focus outlines, including color swatches implemented as read-only text inputs
  with the button role.
- The field-focus token uses the neutral muted color, with at least 4.56:1
  contrast against the standard page, panel and raised surfaces in both themes.
  Invalid text entry uses the danger color and retains its associated error.
- Composer, command search, Inbox recipients, Home capture, Archive search and
  Andromeda retain their single wrapper-owned indicator; inner fields add none.
- Forced colors restores a system Highlight outline for standalone fields and
  an owner indicator for wrapped fields, because inset shadows are suppressed.

## verification

Check the served login and Settings fields with keyboard and pointer input.
Verify provider, authentication, adapter and role dropdowns open, navigate,
select, cancel and return focus while retaining their listbox semantics.
Check standalone and wrapped fields, plus unchanged button/choice focus. Cover
phone and desktop, 200% zoom, dark and light, invalid state, reduced motion and
forced colors with synthetic data. Keep owner data and authentication unchanged.
