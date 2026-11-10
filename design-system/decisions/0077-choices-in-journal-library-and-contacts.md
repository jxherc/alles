# choices in journal, library and contacts follow the owner's three rules

## context

the nov 10 audit found choice controls that broke the owner's rule (2 or 3 options flipped often
are a pill switch, a rating is a row of numbers, 4 or more options or a list that can grow is the
dropdown): a library card showed its shelf as three bordered boxes and its rating as five star
glyphs 45px apart, the journal's ten moods were bare words in a row, and contacts had four filter
pills that never showed which one was picked.

## decision

- a book card's shelf (want, reading, read) is a pill switch and its rating is the kit's number row
  1 to 5. the row's readout is left out on the card, since it would repeat the picked number.
- the books grid is `repeat(auto-fill, minmax(min(100%, 21rem), 1fr))`, wide enough for the number row
  and the pill switch, with the 12px surface gap.
- the library overview is one list: its filter chips (everything, saved, books with counts) repeated the
  tabs and are gone. when every row has the same kind the kind column ("book") says nothing, so it
  carries the status (reading, want to read, read) and the status leaves the right-hand text.
- the journal's mood is the dropdown: ten moods and "no mood" first, each option leading with its emoji,
  which stays the stored value. the trigger shows the pick, and an unlisted value an older entry holds
  is kept when the entry is saved.
- "copy to Markdown" is an item in the journal settings gear's menu, not a button touching the gear.
  focus returns to the gear when its dialog closes.
- the journal's daily prompt is the editor's placeholder, shown only while today's entry is empty;
  other days keep the plain question. the line under the date is gone.
- a failed reflection is one line beside the reflect button ("could not reflect: ... choose reflect to
  retry"), not a bar above the search box. it clears when reflect works, when the entry changes or
  when the day changes. on a phone the line wraps under the buttons.
