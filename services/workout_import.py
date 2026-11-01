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
    """ "sets 2-3 completed" -> 2, "sets 1 and 2 planned" -> 2, "3 sets recorded" -> 3, else 1."""
    words = text.lower()
    found = re.search(r"sets?\s+(\d+)\s*(?:-|to|and)\s*(\d+)", words)
    if found:
        return max(1, int(found.group(2)) - int(found.group(1)) + 1)
    found = re.match(r"^(\d+)\s+sets?\b", words.strip())  # "3 sets recorded"
    if found:
        return max(1, int(found.group(1)))
    return 1


_TOKEN = re.compile(
    r"\s*(?:(?P<none>no\s+weights?|bodyweight|bw)\b|(?P<num>\d*\.?\d+)|(?P<q>\?)"
    r"|\((?P<br>[^)]*)\)|(?P<op>[/+,]))",
    re.IGNORECASE,
)
_BARE = object()  # "no weights": a set with reps and no load


def _groups(left):
    """'20 (fail)/15 50 (7)+40 (5) (1)' -> groups of slash parts of drop parts, each
    {"w": weight, "br": [bracket texts]}. a slash is the next set in the same group, a plus
    the same set going on lighter (a drop set). None when the text has another shape."""
    groups, part, pending, at = [], None, None, 0
    while at < len(left):
        match = _TOKEN.match(left, at)
        if not match or match.end() == at:
            return None
        at = match.end()
        if match.group("br") is not None:
            if part is None:
                return None
            part["br"].append(match.group("br").strip())
            continue
        if match.group("op"):
            if part is None or pending:
                return None
            pending = None if match.group("op") == "," else match.group("op")
            continue
        weight = _BARE if match.group("none") else "?" if match.group("q") else match.group("num")
        part = {"w": weight, "br": []}
        if pending == "/":
            groups[-1].append([part])
        elif pending == "+":
            groups[-1][-1].append(part)
        else:
            groups.append([[part]])
        pending = None
    if pending or not groups:
        return None
    for group in groups:
        # a count after a slash group counts every set in it: "55/130 (13)"
        tail = group[-1][-1]["br"]
        if len(group) > 1 and len(tail) == 1 and re.fullmatch(r"\d+", tail[0]):
            for chain in group[:-1]:
                if not any(re.fullmatch(r"\d*\.?\d+", b) for b in chain[-1]["br"]):
                    chain[-1]["br"].append(tail[0])
    return groups


def _brackets(brackets, chained):
    """what one weight's brackets say: {count, reps, status, notes}. the file's own convention:
    a bare number is how many sets ("20 (2)"); a number before another number is the reps
    ("50 (9) (1)"), and so is one inside a drop set ("50 (7)+40 (5)"); "(10+5)" is reps with
    partials; "(8failed)" is 8 reps then failure; words stay as a note."""
    out = {"count": None, "reps": None, "status": None, "notes": []}
    numbers = [b for b in brackets if re.fullmatch(r"\d*\.?\d+", b)]
    for index, text in enumerate(brackets):
        lowered = text.lower()
        later = any(re.fullmatch(r"\d*\.?\d+", b) for b in brackets[index + 1 :])
        if re.fullmatch(r"\d+\s*\+\s*\d+", text):
            out["reps"] = text
        elif failed := re.fullmatch(r"(\d+)fail(?:ed)?", lowered):
            out["reps"], out["status"] = failed.group(1), "failed"
            out["notes"].append(f"({text})")
        elif re.fullmatch(r"\d*\.?\d+", text):
            number = float(text)
            if (later or (chained and len(numbers) == 1)) and number == int(number):
                out["reps"] = text
            elif number == int(number) and number >= 1:
                out["count"] = int(number)
            else:
                out["count"] = 1
                out["notes"].append(f"({text})")  # a part set: kept as written, never rounded
        else:
            lead = re.match(r"^(\d*\.?\d+)\s*(.*)$", text)
            if lead and out["count"] is None:
                number = float(lead.group(1))
                if number == int(number) and number >= 1:
                    out["count"] = int(number)
            out["notes"].append(f"({text})")
            if "unfinished" in lowered:
                out["status"] = "unfinished"
            elif "fail" in lowered or "unsuccessful" in lowered:
                out["status"] = "failed"
            elif "attempt" in lowered and not re.search(r"\d", text):
                out["status"] = "attempted"
    return out


def _recorded(cell):
    """'82.5 (1) 95 (1) 97.5 (1.5 after) 100 (0.5) × 12/10/10/10+5' -> sets, or None. also
    slash sets with reps each ("10/15/20 (fail)/15 × 15/12/10/8"), drop sets
    ("50 (7)+40 (5) (1)"), reps in brackets ("× (12)"), "no weights (3) × 12" and a total
    after a semicolon ("5 (2); 3 sets total × 12": the set nobody wrote down stays "?")."""
    left, sep, right = cell.partition("×")
    if not sep:
        left, sep, right = cell.partition(" x ")
    if not sep:
        return None
    left, _, tail = left.partition(";")
    groups = _groups(left.strip())
    if groups is None:
        return None
    right = right.strip()
    if right.startswith("(") and right.endswith(")"):
        right = right[1:-1]
    reps = [part.strip() for part in right.split("/") if part.strip()] or ["?"]
    flat = sum(len(group) for group in groups)

    def mapped(group_at, slash_at, flat_at, width):
        if len(reps) == 1:
            return reps[0]
        if len(reps) == flat:
            return reps[flat_at]
        if len(reps) == len(groups):
            return reps[group_at]
        if len(reps) == width:
            return reps[slash_at]
        return "?"

    sets, flat_at = [], 0
    for group_at, group in enumerate(groups):
        for slash_at, chain in enumerate(group):
            for link, part in enumerate(chain):
                said = _brackets(part["br"], len(chain) > 1)
                one = {"status": said["status"] or "done"}
                if part["w"] is not _BARE:
                    one |= {"weight": workout_text._number(part["w"]) if part["w"] != "?" else "?",
                            "unit": "lb"}  # fmt: skip
                if link:
                    one["type"] = "drop"
                try:
                    one |= workout_text._reps(
                        said["reps"] or mapped(group_at, slash_at, flat_at, len(group))
                    )
                except workout_text.Unclear:
                    one["reps"] = "?"  # shorthand nobody can read without guessing; raw keeps it
                if (said["count"] or 1) > 1:
                    one["count"] = said["count"]
                if said["notes"]:
                    one["note"] = " ".join(said["notes"])
                sets.append(one)
            flat_at += 1
    tail = tail.strip()
    if tail:
        total = re.fullmatch(r"(\d+)\s+sets?(?:\s+total)?", tail, re.IGNORECASE)
        have = sum(one.get("count", 1) for one in sets if one.get("type") != "drop")
        if total and int(total.group(1)) > have:
            rest = {"weight": "?", "unit": "lb", "status": "done", "note": tail}
            try:
                rest |= workout_text._reps(reps[0] if len(reps) == 1 else "?")
            except workout_text.Unclear:
                rest["reps"] = "?"
            if int(total.group(1)) - have > 1:
                rest["count"] = int(total.group(1)) - have
            sets.append(rest)
        else:
            sets[0]["note"] = "; ".join(filter(None, (sets[0].get("note"), tail)))
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
