# a number shows its unit, a rating names its pick

## context

the lead looked at the sleep logger after S5b part 3 (`.agent/evidence/c.05/logger-sleep-ipad-landscape-dark-after.png`):
latency and awake minutes read "45" with no unit, the quality, wake mood, mood and energy rows had
no end words and no readout, and about 450 field, option and unit names showed in english in every
language. the stepper (0058) had no place for a unit, the day log hid the number row's readout on
purpose, and `habit_loggers.js` fell back to a field's raw key for its name.

## decision

- the stepper takes `unit` ("min", "g", "ml", "bpm", "%", a currency): the unit sits right after the
  value inside the field, muted, and the value is as wide as what's typed so the two stay together
  in the middle. the field's name read by a screen reader carries the unit ("time to fall asleep
  (min)"). the gym steppers keep the unit switch beside "weight" as the owner's screenshots have it.
- `static/js/units.js` names units in the reader's language (`habits.unit_*`) and lists each
  measure's choices with the stored names from `services/units.py` ("glass", not "glasses"; a
  logged height such as elevation or pool length is m or ft). a measure's unit switch renames the
  unit inside its stepper.
- every rating row in a day log shows its end words under the first and last number, on the
  numbers' own grid, and a readout that names the pick ("4, good"). the words come from a scale per
  field (good, energy, calm, focus, how much, mess; effort and severity have 10). a number picked
  from 1 to 10 (effort, severity) is a rating, so it takes the number row too.
- every field, option, scale word and unit name lives in `i18n.js` and the 8 locale files;
  `tests/test_habit_logger_strings.py` fails any the server's kinds or the loggers name without one.

## checked

webkit at desktop, ipad landscape and portrait, and phone, dark and light, every kind seeded with
real looking values: no stepper with a number unit left bare, every end word within 0.5px of its
number's center, no sideways scroll (`.agent/evidence/c.05/logger-*-after.png`).
