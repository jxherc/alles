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
- contacts' four filter pills (favorites, birthdays, groups, duplicates) with no picked state are one
  dropdown, "show", with "all" first; it reads what the list shows, also after a back button or a
  search. a contact row has no "open" button: its avatar and name are one 44px button, next to the
  star and the "..." menu, named by the contact's name and address.
- health logs with nothing in them are one line, "no entries". the "+ entry" button in the header is the
  action, so the heart icon, the title, the paragraph and the second button are gone.
- health's overview, logs and habits share one centered column, 1040px (the dashboard width; at 880px the
  overview's measurement rows left a name no room). the habits list and an opened habit moved from 720px
  to it. the overview's cards take their own content's height instead of the tallest card's.
- a weekly habit past its goal reads "4 this week, goal 1", not "4/1 this week"; the count is the days
  ticked in the last 7 days, so it can pass the goal.
