# the time field

## context

U5 asked for one date and time field with three variants: date, time, date and time. `datepick.js`
had date, datetime and due, but no time alone, so the habit loggers drew every time of day (sleep's
bedtime and wake, a run's start, sunlight's start) as a full date and time picker reading
"Nov 1, 2026, 7:30 AM" for a value that is only "07:30". a bedtime also belongs to the night before
the day it's logged on, and nothing said so.

## decision

- `data-type="time"` on a `.date-input`: the value is "HH:MM", the trigger reads it in the owner's
  clock setting (settings, 12 or 24 hours; auto follows the language), lowercase ("11:15 pm"), with
  a clock mark instead of the calendar.
- its panel has no calendar: hour and minute steps and typed fields as in the datetime panel, and on
  a 12 hour clock the hour reads 1 to 12 with one am or pm button; clear and now in the footer. a
  typed hour keeps the half of the day it's in.
- the sleep log's bedtime and tried to sleep say which night beside the field when the time is noon
  or later ("oct 31, the night before"), and the entry counts the time in bed from bedtime and wake.

## checked

`tests/js/habit_loggers.test.mjs` (night before, time in bed, times read on the clock); the sleep,
early bed, sunlight and workout loggers in webkit at 4 sizes, dark and light, no time field showing
a date (`.agent/evidence/c.05/`).
