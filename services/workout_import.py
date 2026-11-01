"""importing a workout log written in markdown (the owner's workout.md) into a workout habit.

the file is only read, never changed. it has muscle group headings (## back), session headings
(### oct 4 2026, or ### sep 8 with no year) and tables in three formats:

  recorded rows   | exercise | recorded | 20 (1) 30 (1) 40 (1) × 12 | notes |
                  weight groups with their set counts in brackets, then the reps (one, or one
                  per group: 12/10/10/10+5)
  set rows        | exercise | set 1 completed | left 60 × 12, right 70 × 10 | notes |
  reps rows       | exercise | 10 | 50 lbs; 1 completed set; ... |

every row keeps its words exactly in raw; "?" stays unknown; qualifiers stay attached (a set
count like "(0.75 unfinished)" stays in the set's raw and marks the set unfinished). a date with
no year is shown for the owner to confirm and never guessed. an import can be undone: every
entry it writes carries its batch id.
"""

import hashlib
import re
import secrets
from datetime import date

from services import workout_text

MAX_TEXT = 1_000_000
MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        1,
    )
    for name in names
}
_HEADING_DATE = re.compile(r"^([a-z]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?$", re.IGNORECASE)
_GROUP = re.compile(r"\s*(\d*\.?\d+)\s*(?:\(([^)]*)\))?")


class WorkoutImportError(ValueError):
    """the file can't be imported as it is; the message reaches the screen."""


def _cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _status(text):
    words = text.lower()
    if "planned" in words:
        return "planned"
    if "not completed" in words or "failed" in words:
        return "failed"
    if "unfinished" in words:
        return "unfinished"
    if "attempt" in words:
        return "attempted"
    return "done"


def _status_count(text):
    """ "sets 2-3 completed" -> 2, "sets 1 and 2 planned" -> 2, anything else 1."""
    words = text.lower()
    found = re.search(r"sets?\s+(\d+)\s*(?:-|to|and)\s*(\d+)", words)
    if found:
        return max(1, int(found.group(2)) - int(found.group(1)) + 1)
    return 1


def _recorded(cell):
    """'82.5 (1) 95 (1) 97.5 (1.5 after) 100 (0.5) × 12/10/10/10+5' -> sets, or None."""
    left, sep, right = cell.partition("×")
    if not sep:
        left, sep, right = cell.partition(" x ")
    if not sep:
        return None
    groups = []
    at = 0
    left = left.strip()
    while at < len(left):
        match = _GROUP.match(left, at)
        if not match or match.end() == at:
            return None
        groups.append((match.group(1), (match.group(2) or "").strip()))
        at = match.end()
    if not groups:
        return None
    reps = [part.strip() for part in right.strip().split("/") if part.strip()]
    if len(reps) not in (1, len(groups)):
        reps = ["?"]
    sets = []
    for index, (weight, qualifier) in enumerate(groups):
        one = {"weight": workout_text._number(weight), "unit": "lb", "status": "done"}
        try:
            one |= workout_text._reps(reps[index] if len(reps) > 1 else reps[0])
        except workout_text.Unclear:
            one["reps"] = "?"  # shorthand nobody can read without guessing; raw keeps it
        count = re.match(r"^(\d*\.?\d+)\s*(.*)$", qualifier)
        number = float(count.group(1)) if count else 1.0
        extra = count.group(2) if count else qualifier
        if number == int(number) and number >= 1:
            if number > 1:
                one["count"] = int(number)
        if extra or number != int(number) or number < 1:
            # a part set or a qualifier ("1.5 after"): kept as written, never rounded
            one["note"] = f"({qualifier})"
        if "unfinished" in extra:
            one["status"] = "unfinished"
        sets.append(one)
    return sets


def _reps_row(reps_cell, rest):
    """the reps format: '10 | 50 lbs; 1 completed set; default 10 reps; ...'"""
    weight = re.search(r"(\d*\.?\d+)\s*(lbs?|kgs?)", rest, re.IGNORECASE)
    one = {"status": _status(rest.split(";")[1] if ";" in rest else rest)}
    if weight:
        one |= {
            "weight": workout_text._number(weight.group(1)),
            "unit": workout_text._unit(weight.group(2)),
        }
    else:
        one |= {"weight": "?", "unit": "lb"}
    one |= workout_text._reps(reps_cell.strip() or "?")
    count = re.search(r"(\d+)\s+completed\s+sets?", rest)
    if count and int(count.group(1)) > 1:
        one["count"] = int(count.group(1))
    return [one]


def _row_sets(header, cells):
    """(sets, basis, problem) for one table row."""
    if header == "reps":
        return _reps_row(cells[1], cells[2]), None, None
    status_cell, cell = cells[1], cells[2]
    status = _status(status_cell)
    kind = {"type": "warmup"} if "warm" in status_cell.lower() else {}
    if cell.strip() in ("", "-", "—", "–"):
        return [{"status": status} | kind], None, None  # a row with nothing measured
    if status_cell.strip().lower() == "recorded":
        sets = _recorded(cell)
        if sets is not None:
            return sets, workout_text._basis(cell), None
    try:
        parsed = workout_text.parse(cell)
    except workout_text.Unclear:
        return [{"weight": "?", "reps": "?", "unit": "lb", "status": status}], None, cell
    sets = parsed["sets"]
    count = _status_count(status_cell)
    for one in sets:
        one |= kind
        one["status"] = status if status != "done" or one["status"] != "planned" else "planned"
        if count > 1 and "count" not in one:
            one["count"] = count
    return sets, parsed.get("basis"), None


def _heading_date(text):
    match = _HEADING_DATE.match(text.strip())
    if not match or match.group(1).lower() not in MONTHS:
        return None
    month, day = MONTHS[match.group(1).lower()], int(match.group(2))
    year = int(match.group(3)) if match.group(3) else None
    try:
        date(year or 2024, month, day)  # 2024 is a leap year: feb 29 stays possible
    except ValueError:
        return None
    return year, month, day


def parse(text: str) -> dict:
    """{sessions: [...], problems: [...]} from the markdown. nothing is written."""
    if not isinstance(text, str) or not text.strip():
        raise WorkoutImportError("paste or pick a workout log to import")
    if len(text) > MAX_TEXT:
        raise WorkoutImportError("this workout log is too big to import at once")
    sessions, problems = [], []
    group, session, header = "", None, None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            group, session, header = stripped[3:].strip(), None, None
            continue
        if stripped.startswith("### "):
            heading = stripped[4:].strip()
            when = _heading_date(heading)
            header = None
            if when is None:
                session = None
                problems.append({"line": number, "text": stripped, "why": "not a date"})
                continue
            year, month, day = when
            session = {
                "group": group,
                "heading": heading,
                "year": year,
                "month": month,
                "day": day,
                "notes": [],
                "rows": [],
            }
            sessions.append(session)
            continue
        if session is None:
            continue
        if stripped.startswith("|"):
            cells = _cells(stripped)
            names = [cell.lower() for cell in cells]
            if names and names[0] == "exercise":
                header = "reps" if len(names) > 1 and names[1] == "reps" else "sets"
                continue
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            if header is None or len(cells) < 3:
                problems.append({"line": number, "text": stripped, "why": "a row outside a table"})
                continue
            session["rows"].append((number, line, header, cells))
        elif stripped and not stripped.startswith("#"):
            session["notes"].append(stripped)
    out = [_session(one, problems) for one in sessions if one["rows"] or one["notes"]]
    return {"sessions": out, "problems": problems}


def _session(one, problems):
    exercises = []
    by_name = {}
    for number, line, header, cells in one["rows"]:
        name = cells[0] or "unlabeled entry"
        sets, basis, problem = _row_sets(header, cells)
        if problem:
            problems.append(
                {"line": number, "text": line.strip(), "why": "weight and reps unreadable"}
            )
        notes = cells[3] if header == "sets" and len(cells) > 3 else ""
        lowered = f"{name} {notes}".lower()
        if "assist" in lowered:
            for item in sets:
                if isinstance(item.get("weight"), (int, float)):
                    item["assist"] = item.pop("weight")
        sets[0]["raw"] = line.strip()
        note = "; ".join(part for part in (sets[0].get("note"), notes) if part)
        if note and len(note) <= 200:  # a longer note still sits word for word in raw
            sets[0]["note"] = note
        exercise = by_name.get(name.lower())
        if exercise is None:
            exercise = {"name": name, "sets": []}
            by_name[name.lower()] = exercise
            exercises.append(exercise)
        if basis and not exercise.get("setup"):
            exercise["setup"] = {"basis": basis}
        if "first time" in notes.lower():
            exercise["first_time"] = True
        exercise["sets"].extend(sets)
    source = "\n".join(
        [one["group"], one["heading"], *one["notes"], *(row[1] for row in one["rows"])]
    )
    key = "w" + hashlib.sha1(source.encode()).hexdigest()[:12]
    return {
        "key": key,
        "group": one["group"],
        "heading": one["heading"],
        "date": f"{one['year']:04d}-{one['month']:02d}-{one['day']:02d}" if one["year"] else None,
        "month": one["month"],
        "day": one["day"],
        "needs_year": one["year"] is None,
        "note": "\n".join(one["notes"]),
        "exercises": exercises,
    }


def session_date(session, year=None) -> str:
    if session["date"]:
        return session["date"]
    if year is None:
        raise WorkoutImportError("pick the year for the sessions without one")
    try:
        return date(int(year), session["month"], session["day"]).isoformat()
    except (TypeError, ValueError):
        raise WorkoutImportError("pick the year for the sessions without one") from None


def entry(session, batch) -> dict:
    """the habit log entry for one session."""
    values = {"exercises": session["exercises"]}
    if session["group"]:
        values["muscles"] = [session["group"]]
    out = {"id": session["key"], "values": values, "import": batch}
    if session["note"]:
        out["note"] = session["note"]
    return out


def new_batch() -> str:
    return "imp-" + secrets.token_hex(6)
