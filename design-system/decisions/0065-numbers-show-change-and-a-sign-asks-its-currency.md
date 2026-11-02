# numbers show change, and a sign asks which currency it is

## context

the oct 30 ux pass (u.05, u.12). health's overview said "weight 151.2 lb" and not that it went
152.4 to 151.2 this week. the finance overview listed accounts and "no subscriptions yet" under a
panel of Actual ledger plumbing ("writes to Alles · CAD", "Alles active", "show ledger setup")
and never said what was spent this month. an account made with the "$" default read "currency
not set 627.46" everywhere money printed it, next to a currency field that said "$". decision
0040 kept that label as a safety rule.

## decision

- a measurement or a balance shows its change and a quiet line of the last 30 days. a measurement
  compares with the last reading a week or more before its latest ("−1.2 lb this week"); a balance
  with the same day a month earlier ("+$120.00 vs last month"). the change is text with a sign and
  the unit, so it is what a screen reader reads; the line is plain inline svg (`numbers.js`),
  `aria-hidden`, drawn in muted text color. no signal color: weight going down is not bad news.
  a reading with no partner in range shows no change, a balance that never moved says "no change"
  and draws no flat line.
- the finance overview leads with spent this month against last month, then accounts with their
  change, top categories, recent transactions and upcoming renewals. no ledger status, no
  explanatory text, no setup toggle on that page: ledger setup is one plain button that opens the
  setup in a dialog. a ledger in use that is not healthy is the one thing that stays on the page.
- a bare sign is not a currency. "$" is never turned into a code on the side (the currency
  foundation tests pin it), and amounts in an account made with a sign read with that sign
  ("$735.46"). "currency not set" no longer labels an amount that has a sign; with no sign it
  still does. what is unknown is asked, in one line with the currency dropdown right there:
  "which currency is $?". picking saves the code to the account after one confirmation (a code
  can't be taken back once an account holds amounts). this replaces the "kept" line in 0040.
- an account's currency is the dropdown (`custom-select`, type to jump), on its card and in the
  question; a fixed one is a disabled dropdown with the reason beside it.
- two chip walls the lint still listed became dropdowns by the choice rule: health's 4 history
  ranges and money's 4 plan tasks (accounts, budgets, schedules, goals).

## not yet

- the ledger setup has no settings pane to live in (the settings home is S8's); until it exists the
  button opens it in a dialog.
