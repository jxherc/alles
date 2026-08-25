# 0011: greeting and empty-state display type

Status: accepted

## decision

The 22-30px display-data cap in FOUNDATIONS applies to data. Two named voice moments
may set larger type:

- the home greeting ("good evening"), up to 48px, weight 400-500;
- a specialist empty-state statement (for example docs' "read here. edit when you
  need to."), up to 46px, weight 560 or less.

These are short sentences, never repeated per screen, and never used for numbers,
labels, or section titles. Everything else in the type scale is unchanged.

## reason

The greeting is the product's one moment of voice; at 30px it reads as a label, not
a greeting. The empty-state statement carries the same job: give an empty workspace
one clear idea instead of a blank panel. Both are deliberate and bounded, and the
rest of the interface keeps the quiet scale.

## consequence

- New display-type uses outside these two moments need their own recorded decision.
- The anti-slop review rule "display type only for data, 22-30px" now reads
  "display type for data, plus the two documented voice moments."
- Empty states still need a real next action below the statement; type alone is not
  an empty state.
