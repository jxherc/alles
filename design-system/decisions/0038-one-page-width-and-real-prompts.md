# one page width, and prompts that are real dialogs

## context

The same review found each specialist app at its own width, most hugging the left edge on a
wide screen. Every "name it" or "how many minutes" question was the bare prompt box: one line of
text, a field and "ok". The image editor still used the browser's own prompt.

## decision

- List and settings-like pages in the specialist apps read in one centered 880px column (the
  documented list width). The overview and Aide's tool pages center the same way. Calendar, the
  task board, files and the gallery keep the full width their work needs.
- A prompt is a small form: a title that names the task ("new folder"), a label on the field
  ("name"), an optional hint under it, cancel, and a button that says what happens ("create").
  Plain "ok" is gone.
- A password check is titled "confirm it’s you", labels the field "Alles password", says what
  it's for in the hint, and continues with "continue".
- No screen uses the browser's own prompt.

## verification

`node --test tests/js/*.test.mjs` passes. In the browser the dialog opens with focus in the
field, Enter submits, Escape cancels, and a books page sits centered at 928px in a 1280px window.
