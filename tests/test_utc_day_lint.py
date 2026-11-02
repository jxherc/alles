"""toISOString().slice(0, 10) is the utc day, not the owner's: after 7 or 8 pm in toronto it is
already tomorrow. "today" comes from when.js localDay() (or i18n calendarDateKey). this lint fails
any utc day cut off an instant in static/js, outside the uses listed below, which only do day
arithmetic on a date built at utc midnight or noon (Date.UTC, "T00:00:00Z") or check a date string.
an entry that stops matching fails too, so the list can't rot."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

CUT = re.compile(
    r"toISOString\(\)\s*\.\s*(?:slice\(\s*0\s*,\s*10\s*\)|substring\(\s*0\s*,\s*10\s*\)"
    r"|substr\(\s*0\s*,\s*10\s*\)|split\(\s*['\"]T['\"]\s*\)\s*\[\s*0\s*\])"
)

# (file under static/js, a piece of the line that is unique in that file): why it is fine
ALLOWED = {
    (
        "when.js",
        "return date.toISOString().slice(0, 10);",
    ): "addDays: arithmetic on a utc midnight date",
    ("tasks.js", "function _shift(iso, n)"): "arithmetic on a utc midnight date",
    ("numbers.js", "new Date(Date.UTC(first.getUTCFullYear()"): "a month step built with Date.UTC",
    (
        "specialist_groups.js",
        "return date.toISOString().slice(0, 10);",
    ): "addDateKeyDays: checked utc parts first",
    (
        "habit_loggers.js",
        "new Date(Date.UTC(y, m - 1, n - 1))",
    ): "the day before a key, built with Date.UTC",
    (
        "journal.js",
        "const iso = dt.toISOString().slice(0, 10);",
    ): "the year grid walks utc midnight days",
    (
        "reminders.js",
        "reminderTimeFromWall(`${day.toISOString()",
    ): "day is calendarDateKey() at utc noon",
    (
        "andromeda.js",
        "dateOnly.toISOString().slice(0, 10) !== raw",
    ): "checks a y-m-d string is a real date",
    (
        "health.js",
        "new Date(date).toISOString().slice(0, 10) === date",
    ): "checks a y-m-d string is a real date",
}


def _hits():
    found = []
    for path in sorted(JS.rglob("*.js")):
        rel = path.relative_to(JS).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = [(number, line.strip()) for number, line in enumerate(text.splitlines(), 1)]
        hits = [
            (rel, number, code)
            for number, code in lines
            if CUT.search(code) and not code.startswith(("//", "*", "/*"))
        ]
        comments = sum(
            1 for _, code in lines if CUT.search(code) and code.startswith(("//", "*", "/*"))
        )
        # a cut wrapped over two lines is still a cut: the whole file must not hold more than the lines show
        if len(CUT.findall(text)) > len(hits) + comments:
            hits.append((rel, 0, "a toISOString() day cut wrapped over lines"))
        found += hits
    return found


def _allowed(rel, code):
    return next((key for key in ALLOWED if key[0] == rel and key[1] in code), None)


class UtcDayLintTest(unittest.TestCase):
    def test_no_utc_day_used_as_the_local_day(self):
        bad = [
            f"static/js/{rel}:{number}: {code}"
            for rel, number, code in _hits()
            if not _allowed(rel, code)
        ]
        self.assertEqual(
            bad, [], "use localDay() from when.js for the owner's day:\n" + "\n".join(bad)
        )

    def test_every_allowed_use_still_exists(self):
        used = {_allowed(rel, code) for rel, _, code in _hits()}
        stale = [f"{rel}: {piece}" for rel, piece in ALLOWED if (rel, piece) not in used]
        self.assertEqual(stale, [], "these allow-list entries match nothing now; drop them")

    def test_the_pattern_sees_each_spelling(self):
        for sample in (
            "new Date().toISOString().slice(0, 10)",
            "d.toISOString().slice(0,10)",
            "d.toISOString().substring(0, 10)",
            "d.toISOString().split('T')[0]",
            'd.toISOString().split("T")[0]',
        ):
            self.assertTrue(CUT.search(sample), sample)
        self.assertFalse(CUT.search("new Date().toISOString().slice(0, -1)"))


if __name__ == "__main__":
    unittest.main()
