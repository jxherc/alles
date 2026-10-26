# larger type for reading

## context

On an ipad (2026-10-26) the owner found alles hard to read. Every font size was a fixed px value
from a 12 to 15px scale built for a mouse at arm's length. Touch screens got no larger size, and 111
inline `font-size: 0.75rem` styles in `index.html` and the js sat outside the css entirely. Google
search reads at about 16px body and 14px small text on a computer. iOS reads at 17px body. alles sat
2 to 4px under both.

## decision

- Every font size is rem on one role scale: 13, 14, 15, 16, 18, 20, 22, 24, 28 and 32 (base-16 px).
  Nothing under 13 except glyphs drawn as text (ascii art, icon letters).
- The root sets the whole scale: 109.375% on a fine pointer (role 15 reads 16.4px, role 13 reads
  14.2px) and 115% on a coarse pointer (role 15 reads 17.25px, role 13 reads 14.95px).
- Percentages keep the browser's own text-size setting in charge. The small and large settings and
  the density modes scale from the same root.
- A touch text field is never under 16px, so a phone doesn't zoom in on focus.
- Inline styles in html and js use the same rem roles. Fixed px widths on form fields became rem,
  so a field grows with its words.
- Layout sized in px around text (image rows, form fields) is checked at every size: a label stays
  on one line and its field grows to fit it.

## kept

- 0040's control sizes as roles (14), the 44px target, and the display-type bounds in 0011.
