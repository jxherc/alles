# one name, one title, rows that hold still

amends 0036 (the reading column), 0037 (one header row) and 0051 (gaps).

## context

the nov 10 design audit found the same few causes on three screens.

- files: hovering or focusing a location row grew it from 44px to 75px and pushed every row below
  it down. row dividers ran to the screen edge while the buttons stopped 24px short, because the
  rows took the gutter as padding. the selected-files bar was five bare words.
- docs: an open note's name showed three times in the main column (the header, the path line and
  the rendered h1), and import sat alone at the far end of the header. docs cards were the only
  cards at 8px.
- titles: five things were forced to 20px with an important rule; journal and gallery drew their
  name right under the tab with the same name.
- aide: replies wrapped at 621px while code blocks ran to 760.

## decision

- a row never changes size or moves on hover, focus or press. hover and focus change the fill
  only. what a row needs at rest is shown at rest: a location row shows its name (role 14), the
  kind only when it is not local, and "read only" as plain muted text. "managed" is the normal
  state and has no label.
- a name or title shows once. an open note's name is its h1; the header names only the folder
  when the note is in one. a title that only repeats its tab (journal, photos) is screen reader
  only, and the controls on its row stay.
- one page title role: 1rem, weight 600. only the home greeting is display type (1.25rem).
- files dividers sit on the content's edges: rows and the table head take the gutter as margin, so
  the line starts at the checkbox column and ends at the last cell, which is where the header's
  last button ends.
- a bulk action is a button with the shared quiet look, 8px apart, delete in the danger color.
- import sits beside new document in the docs sidebar head: the two ways to make a document are
  together.
- aide: replies, code, tables and the owner's messages share the column's two edges. there is no
  prose-only max-width. the actions under a message sit one control gap apart.

## not done here

the phone locations strip still scrolls sideways by design; the gallery toolbar order on a phone
is unchanged except that the search no longer sits beside a title.
