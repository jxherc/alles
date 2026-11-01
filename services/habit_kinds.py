"""What a habit's day log can hold, per habit type, and the checks that keep it clean.

every habit has a kind. the six first kinds (check, workout, reading, count, duration, distance)
stay for habits made before the catalog had its own kinds; each catalog habit (run, water,
sleep, ...) now has a kind of its own with the fields from the habit logging spec.

a day log is one json document (v2):

  {"v": 2, "entries": [entry, ...]}
  entry = {id, time ("HH:MM" or null), values: {field key: value}, note, raw, tags, photos,
           slip (a quit habit's slip: the day doesn't count as clean), skip (a planned skip:
           the streak carries over it), import (the import batch that wrote it)}

the old (v1) shape was one small object per kind, for example workout {"rows": [{exercise,
weight, reps, sets, note}]}. m0078 rewrote stored logs to v2 and the old screens still send v1,
so clean_log takes both and legacy_view turns v2 back into v1 for them.

any number, count or time can be "?" (unknown): the owner's notes keep "?" for a value nobody
recorded, and nothing gets guessed. raw keeps the original words exactly as written.

weights follow the owner's notes: pounds unless stated, dumbbells per hand, machines per side.
"""

import json
import math
import re
import secrets

from services import units

UNKNOWN = "?"
MAX_ENTRIES = 50
MAX_ROWS = 50  # v1 workout rows
UNIT_CHARS = 24
NAME_CHARS = 80
NOTE_CHARS = 200
BOOK_CHARS = 120
LONG_CHARS = 4000
RAW_CHARS = 2000
DEFAULT_REPS = 10
READING_UNITS = ("pages", "chapters")
DISTANCE_UNITS = ("km", "mi")

SET_TYPES = ("working", "warmup", "top", "backoff", "drop", "failure")
SET_STATUSES = ("done", "planned", "attempted", "failed", "unfinished")
LOAD_BASES = ("per_hand", "per_side", "stack", "total", "assist", "bodyweight")
SIDES = ("L", "R")
SETUP_KEYS = ("equipment", "grip", "stance", "angle", "seat", "pin", "machine")
PERIODS = ("day", "week", "month", "year")
QUIT_MODES = ("zero", "limit", "rules")
CUSTOM_TYPES = (
    "number",
    "count",
    "minutes",
    "clock",
    "measure",
    "rating",
    "yesno",
    "choice",
    "text",
    "link",
)


class HabitLogError(ValueError):
    """a log or habit type the server won't store; the message reaches the screen."""


def _bad():
    return HabitLogError("these log details don't fit this habit")


# ── the fields of every kind ───────────────────────────────────────────────────


def f(key, type_, on=False, **opts):
    """one field: key, type, shown by default or switched on in the habit's edit dialog."""
    return {"key": key, "type": type_, "on": on, **opts}


def _rating(key, on=False, top=None):
    return f(key, "rating", on, **({"max": top} if top else {}))


MOOD = _rating("mood")
EFFORT = f("effort", "number", min=1, max=10, whole=True)
PEOPLE = f("people", "people")
PLACE = f("place", "text")
WEATHER = f("weather", "text")
COST = f("cost", "number", max=1_000_000)

# every kind can switch these on (E1: "mood or energy if turned on")
COMMON = (_rating("mood"), _rating("energy"))

SET_ROW = "sets"  # the workout set list; pushups, squats and pullups use it too

KIND_FIELDS = {
    "check": (),
    "count": (f("amount", "count", True),),
    "duration": (f("minutes", "minutes", True),),
    "distance": (
        f("distance", "measure", True, measure="distance"),
        f("minutes", "minutes", True),
    ),
    # ── fitness ──
    "workout": (
        f("exercises", "exercises", True),
        f("start", "clock", True),
        f("end", "clock", True),
        f("muscles", "tags", True),
        f("gym", "text"),
        f("body_weight", "measure", measure="weight"),
        f("sleep_hours", "number", max=24),
        f(
            "soreness",
            "rows",
            columns=(f("part", "text"), f("level", "number", min=0, max=10, whole=True)),
            sides=True,
        ),
    ),
    "run": (
        f("distance", "measure", True, measure="distance"),
        f("minutes", "minutes", True),
        dict(EFFORT, on=True),
        f("elevation", "measure", measure="height"),
        f("hr_avg", "count", max=260),
        f("hr_max", "count", max=260),
        f("cadence", "count", max=300),
        f("run_type", "choice", options=("easy", "long", "race", "workout", "tempo", "recovery")),
        f("treadmill", "yesno"),
        f("shoes", "link"),
        f("temperature", "measure", measure="temperature"),
        f(
            "laps",
            "rows",
            columns=(
                f("distance", "measure", measure="distance"),
                f("minutes", "minutes"),
                f("hr_avg", "count", max=260),
            ),
        ),
        f("official_distance", "measure", measure="distance"),
        f("finish_minutes", "minutes"),
        f("goals", "text"),
        f("goal_met", "yesno"),
        f("zones", "rows", columns=(f("zone", "count", max=10), f("minutes", "minutes"))),
    ),
    "walk": (
        f("distance", "measure", True, measure="distance"),
        f("minutes", "minutes", True),
        f("steps", "count"),
        f("shoes", "link"),
        PEOPLE,
        PLACE,
        EFFORT,
        f("commute", "yesno"),
    ),
    "cycle": (
        f("distance", "measure", True, measure="distance"),
        f("minutes", "minutes", True),
        f("bike", "link", True),
        f("elevation", "measure", measure="height"),
        f("power_avg", "count", max=3000),
        f("cadence", "count", max=300),
        f("hr_avg", "count", max=260),
        f("indoor", "yesno"),
        f("commute", "yesno"),
    ),
    "swim": (
        f("lengths", "count", True),
        f("pool_length", "measure", True, measure="height"),
        f("minutes", "minutes", True),
        f("stroke", "choice", options=("free", "back", "breast", "fly", "mixed")),
        f("open_water", "yesno"),
        f(
            "intervals",
            "rows",
            columns=(
                f("reps", "count", max=1000),
                f("distance", "measure", measure="height"),
                f("interval_seconds", "seconds"),
                f("stroke", "choice", options=("free", "back", "breast", "fly", "mixed")),
            ),
        ),
        f("drills", "text"),
        f("water_temp", "measure", measure="temperature"),
    ),
    "hike": (
        f("trail", "text", True),
        f("distance", "measure", True, measure="distance"),
        f("elevation", "measure", True, measure="height"),
        f("minutes", "minutes", True),
        f(
            "difficulty",
            "choice",
            options=("easy", "moderate", "hard", "t1", "t2", "t3", "t4", "t5", "t6"),
        ),
        f("high_point", "measure", measure="height"),
        PEOPLE,
        WEATHER,
        f("pack_weight", "measure", measure="weight"),
    ),
    "stretch": (
        f("minutes", "minutes", True),
        f("areas", "tags", True),
        f(
            "holds",
            "rows",
            columns=(f("name", "text"), f("seconds", "seconds")),
            sides=True,
        ),
        f("range", "measure", measure="body"),
        f("range_state", "choice", options=("warm", "cold")),
        f("tightness", "number", min=0, max=10, whole=True),
    ),
    "yoga": (
        f("minutes", "minutes", True),
        f("style", "text", True),
        _rating("felt", True, 5),
        f("setting", "choice", options=("class", "home")),
        f("teacher", "text"),
        f("level", "text"),
        f("focus", "tags"),
        f("poses", "text"),
    ),
    "pushups": (
        f(SET_ROW, "sets", True),
        f("variation", "text", True),
        f("grip", "text"),
    ),
    "steps": (
        f("steps", "count", True),
        f("goal", "count"),
        f("distance", "measure", measure="distance"),
        f("floors", "count", max=1000),
        f("step_length", "measure", measure="body"),
    ),
    "climb": (
        f(
            "climbs",
            "rows",
            True,
            columns=(
                f("grade", "text"),
                f("outcome", "choice", options=("onsight", "flash", "send", "project", "attempt")),
                f("attempts", "count", max=1000),
                f("name", "text"),
                f("style", "choice", options=("boulder", "lead", "top_rope", "trad")),
                f("angle", "choice", options=("slab", "vertical", "overhang", "roof")),
                f("holds", "tags"),
                f("high_point", "text"),
                f("beta", "text"),
                _rating("rating"),
            ),
        ),
        f("indoor", "yesno"),
        f("area", "text"),
        PEOPLE,
        _rating("fatigue"),
        f("hangboard", "text"),
    ),
    "sport": (
        f("sport", "text", True),
        f("minutes", "minutes", True),
        f("result", "text", True),
        f("session", "choice", options=("match", "practice")),
        f("opponent", "text"),
        PEOPLE,
        f("position", "text"),
        f("venue", "text"),
        f("minutes_played", "minutes"),
        f("stats", "rows", columns=(f("name", "text"), f("value", "number"))),
    ),
    # ── health ──
    "water": (
        f("amount", "measure", True, measure="liquid"),
        f("drink", "text", True),
        f("caffeine_mg", "number", max=2000),
        f("factor", "number", min=0, max=2),
    ),
    "sleep": (
        f("bedtime", "clock", True),
        f("wake", "clock", True),
        _rating("quality", True, 5),
        f("tried", "clock"),
        f("latency", "minutes"),
        f("awakenings", "count", max=100),
        f("awake_minutes", "minutes"),
        f("out_of_bed", "clock"),
        f("naps", "rows", columns=(f("start", "clock"), f("minutes", "minutes"))),
        f("factors", "tags"),
        _rating("wake_mood"),
    ),
    "early_bed": (f("bedtime", "clock"),),
    "vitamins": (
        f("item", "link", True),
        f("taken", "choice", True, options=("taken", "skipped")),
        f("dose", "number", max=10000),
        f("dose_unit", "text"),
        f("as_needed", "yesno"),
        f("brand", "text"),
        f("felt", "text"),
    ),
    "protein": (
        f("grams", "number", True, max=1000, unit="g"),
        f("meal", "choice", True, options=("breakfast", "lunch", "dinner", "snack", "shake")),
        f("source", "text"),
        f("shake", "yesno"),
    ),
    "floss": (
        f("when", "choice", True, options=("morning", "night")),
        f("tool", "choice", options=("string", "picks", "water_flosser")),
        f("steps", "checklist"),
    ),
    "skincare": (
        f("when", "choice", True, options=("am", "pm")),
        f("steps", "checklist", True),
        f("skin_day", "choice", True, options=("good", "ok", "bad")),
        f("products", "tags"),
        f("reaction", "text"),
    ),
    "no_sugar": (
        f("clean", "yesno", True),
        f("sugar_g", "number", max=1000, unit="g"),
        f("source", "text"),
        _rating("craving"),
        f("triggers", "tags"),
    ),
    "no_alcohol": (
        f("dry", "yesno", True),
        f("drinks", "number", True, max=100),
        f("drink_type", "text"),
        f("volume", "measure", measure="liquid"),
        f("abv", "number", max=100),
        COST,
        _rating("craving"),
        f("triggers", "tags"),
        f("blackout", "yesno"),
        f("drove", "yesno"),
        f("missed_work", "yesno"),
    ),
    "veggies": (
        f("veg", "count", True, max=100),
        f("fruit", "count", True, max=100),
        f("greens", "count", max=100),
        f("cruciferous", "count", max=100),
        f("berries", "count", max=100),
        f("beans", "count", max=100),
    ),
    "cold_shower": (
        f("minutes", "minutes", True),
        f("water_temp", "measure", True, measure="temperature"),
        f("type", "choice", options=("shower", "ice_bath", "plunge")),
        f("air_temp", "measure", measure="temperature"),
        _rating("after_feel", top=5),
        f("hr", "count", max=260),
    ),
    "sunlight": (
        f("minutes", "minutes", True),
        f("start", "clock", True),
        f("uv", "number", max=20),
        f("spf", "count", max=100),
        f("morning", "yesno"),
        f("source", "choice", options=("by_hand", "imported")),
    ),
    "symptoms": (
        f("what", "text", True),
        f("severity", "number", True, min=1, max=10, whole=True),
        f("triggers", "tags"),
        f("body_part", "text"),
    ),
    "labs": (
        f("marker", "text", True),
        f("value", "number", True, min=-1_000_000, max=1_000_000),
        f("unit", "text", True),
        f("ref_low", "number", min=-1_000_000, max=1_000_000),
        f("ref_high", "number", min=-1_000_000, max=1_000_000),
        f("lab", "text"),
    ),
    "body_measurements": (
        f(
            "measurements",
            "rows",
            True,
            columns=(f("part", "text"), f("size", "measure", measure="body")),
            sides=True,
        ),
        f("weight", "measure", measure="weight"),
        f("body_fat", "number", max=100),
    ),
    "quit": (
        f("substance", "text", True),
        f("clean", "yesno", True),
        f("amount", "number", max=100_000),
        f("unit", "text"),
        _rating("craving"),
        f("triggers", "tags"),
    ),
    # ── mind ──
    "meditate": (
        f("minutes", "minutes", True),
        f("type", "text", True),
        f("guided", "yesno"),
        f("techniques", "tags"),
        _rating("rating", top=4),
        _rating("mood_before"),
        _rating("mood_after"),
    ),
    "breathe": (
        f("pattern", "text", True),
        f("minutes", "minutes", True),
        f("rounds", "count", True, max=1000),
        f("ratio", "text"),
        f("holds", "rows", columns=(f("seconds", "seconds"),)),
        _rating("calm_before"),
        _rating("calm_after"),
    ),
    "journal": (
        f("words", "count", True),
        dict(MOOD, on=True),
        f("template", "text"),
        f("when", "choice", options=("morning", "evening")),
        WEATHER,
        PLACE,
    ),
    "gratitude": (
        f(
            "items",
            "rows",
            True,
            columns=(f("what", "text"), f("why", "text"), f("person", "link")),
        ),
        f("when", "choice", options=("morning", "evening")),
        f("do_better", "text"),
    ),
    "no_social": (
        f("minutes", "minutes", True),
        f("under_limit", "yesno", True),
        f("apps", "rows", columns=(f("app", "text"), f("minutes", "minutes"))),
        f("pickups", "count", max=10000),
        f("urges_resisted", "count", max=10000),
    ),
    "outside": (
        f("minutes", "minutes", True),
        f("activity", "text", True),
        PLACE,
        WEATHER,
        PEOPLE,
    ),
    # ── learning ──
    "reading": (
        f("book", "link", True),
        f("minutes", "minutes", True),
        f("end_page", "count", True, max=100_000),
        f("start_page", "count", max=100_000),
        f("pages", "count", max=10_000),
        f("chapters", "count", max=10_000),
        f("format", "choice", options=("paper", "ebook", "audio")),
        f("quote", "text"),
    ),
    "language": (
        f("language", "text", True),
        f("minutes", "minutes", True),
        f(
            "activity",
            "choice",
            True,
            options=("input", "speaking", "srs", "reading", "writing", "listening", "class", "app"),
        ),
        f("new_words", "count"),
        f("xp", "count"),
        f("lessons", "count", max=1000),
        f("resource", "text"),
        f("active", "yesno"),
        f("comprehension", "number", max=100),
        f("cefr", "choice", options=("a1", "a2", "b1", "b2", "c1", "c2")),
    ),
    "instrument": (
        f("minutes", "minutes", True),
        f("piece", "text", True),
        _rating("rating", True),
        f("instrument", "text"),
        f("tempo_bpm", "count", max=400),
        f("needs_work", "text"),
        f("recording", "files"),
    ),
    "study": (
        f("subject", "text", True),
        f("minutes", "minutes", True),
        f("task", "link"),
        f("outcome", "choice", options=("done", "abandoned")),
        f("pomodoros", "count", max=100),
        _rating("focus", top=5),
    ),
    "coding": (
        f("minutes", "minutes", True),
        f("project", "text", True),
        f("language", "text"),
        f("category", "choice", options=("building", "debugging", "learning", "review", "other")),
        f("problems_easy", "count", max=1000),
        f("problems_medium", "count", max=1000),
        f("problems_hard", "count", max=1000),
        f("commits", "count", max=10_000),
    ),
    "writing": (
        f("words", "count", True),
        f("minutes", "minutes", True),
        f("project", "link"),
        f("session_goal", "count"),
        MOOD,
    ),
    "flashcards": (
        f("cards", "count", True),
        f("minutes", "minutes", True),
        f("correct_pct", "number", True, max=100),
        f("new_cards", "count"),
        f("again", "count"),
        f("hard", "count"),
        f("good", "count"),
        f("easy", "count"),
        f("deck", "text"),
    ),
    "drawing": (
        f("minutes", "minutes", True),
        f("subject", "text", True),
        f("tools", "text"),
        f("reference", "text"),
        f("win", "text"),
        f("change", "text"),
        f("sketches", "count", max=1000),
    ),
    "podcast": (
        f("show", "text", True),
        f("minutes", "minutes", True),
        f("episode", "text"),
        f("finished", "yesno"),
        f("speed", "number", min=0.25, max=4),
        f("takeaway", "text"),
    ),
    # ── home ──
    "tidy": (
        f("area", "text", True),
        f("minutes", "minutes", True),
        _rating("mess"),
        PEOPLE,
    ),
    "make_bed": (),
    "dishes": (
        f("method", "choice", options=("dishwasher", "by_hand")),
        f("minutes", "minutes"),
    ),
    "laundry": (
        f("loads", "count", True, max=100),
        f("stages", "checklist", True),
        f("type", "text"),
        f("temperature", "choice", options=("cold", "warm", "hot")),
    ),
    "cook": (
        f("dish", "text", True),
        f("meal", "choice", True, options=("breakfast", "lunch", "dinner", "snack")),
        _rating("rating", True),
        f("minutes", "minutes"),
        f("servings", "count", max=1000),
        f("changes", "text"),
        f("recipe", "link"),
        COST,
    ),
    "plants": (
        f("plants", "people", True),
        f(
            "care",
            "choice",
            True,
            options=("water", "fertilize", "repot", "prune", "mist", "clean", "checked", "pests"),
        ),
        f("moisture", "choice", options=("dry", "moist", "wet")),
        f("amount", "measure", measure="liquid"),
        f("product", "text"),
        f("dilution", "text"),
        f("pot_size", "measure", measure="body"),
        f("health", "text"),
        f("recheck", "date"),
    ),
    "dog_walk": (
        f("minutes", "minutes", True),
        f("pee", "count", True, max=100),
        f("poop", "count", True, max=100),
        f("distance", "measure", measure="distance"),
        f("route", "text"),
        f("water", "yesno"),
        f("play", "yesno"),
        MOOD,
        WEATHER,
        f("dog", "text"),
    ),
    # ── money ──
    "budget": (f("left", "number", True, min=-1_000_000_000, max=1_000_000_000),),
    "no_spend": (
        f("kept", "yesno", True),
        f("allowed", "tags"),
        f("exceptions", "text"),
        f("avoided", "number", max=1_000_000),
    ),
    "save": (
        f("amount", "number", True, max=1_000_000_000),
        f("goal", "link", True),
        f("account", "text"),
    ),
    "expenses": (
        f(
            "items",
            "rows",
            True,
            columns=(
                f("what", "text"),
                f("amount", "number", max=1_000_000),
                f("category", "text"),
            ),
        ),
        f("total", "number", max=1_000_000_000),
    ),
    # ── social ──
    "call_family": (
        f("person", "link", True),
        f("minutes", "minutes", True),
        f("mode", "choice", options=("voice", "video")),
        f("follow_up", "text"),
        MOOD,
    ),
    "message_friend": (
        f("person", "link", True),
        f("channel", "text", True),
    ),
    "kindness": (
        f("what", "text", True),
        f("recipient", "link"),
        _rating("felt", top=5),
        f("reaction", "text"),
        f("acts", "count", max=100),
    ),
    "friends": (
        f("people", "people", True),
        f("minutes", "minutes", True),
        f("what", "text", True),
        PLACE,
        COST,
        MOOD,
    ),
}
# same fields, own kind (they share the bodyweight set logger)
KIND_FIELDS["squats"] = KIND_FIELDS["pushups"]
KIND_FIELDS["pullups"] = KIND_FIELDS["pushups"]

# one entry a day, replaced not added (steps from a pedometer, one night's sleep)
SINGLE = {
    "steps",
    "sleep",
    "early_bed",
    "budget",
    "make_bed",
    "no_spend",
    "no_sugar",
    "no_alcohol",
    "no_social",
    "quit",
}
# quit habits: a slip keeps total days and the best streak (i am sober, loop habit tracker)
QUIT = {"no_sugar", "no_alcohol", "no_social", "no_spend", "quit"}

LEGACY = ("check", "workout", "reading", "count", "duration", "distance")
# the catalog: 55 habits from static/js/habit_catalog.js plus the five the spec added
CATALOG = (
    "workout", "run", "walk", "cycle", "swim", "hike", "stretch", "yoga", "pushups", "squats",
    "pullups", "steps", "climb", "sport",
    "water", "sleep", "vitamins", "floss", "skincare", "no_sugar", "no_alcohol", "veggies",
    "cold_shower", "early_bed", "sunlight", "protein", "symptoms", "labs", "body_measurements",
    "quit",
    "meditate", "journal", "gratitude", "breathe", "no_social", "outside",
    "reading", "language", "instrument", "study", "coding", "writing", "flashcards", "drawing",
    "podcast",
    "tidy", "make_bed", "cook", "dishes", "laundry", "plants", "dog_walk",
    "budget", "no_spend", "save", "expenses",
    "call_family", "message_friend", "kindness", "friends",
)  # fmt: skip
KINDS = tuple(dict.fromkeys(LEGACY + CATALOG))


def check_kind(kind) -> str:
    kind = str(kind or "check").strip().lower()
    if kind not in KINDS:
        raise HabitLogError("that habit type doesn't exist")
    return kind


def check_unit(unit) -> str:
    unit = str(unit or "").strip()
    if len(unit) > UNIT_CHARS:
        raise HabitLogError("these log details don't fit this habit")
    return unit


def _own(kind) -> list:
    """the kind's fields, then the shared ones it doesn't define itself (journal shows mood)."""
    own = list(KIND_FIELDS[kind])
    keys = {field["key"] for field in own}
    return own + [field for field in COMMON if field["key"] not in keys]


def kinds() -> dict:
    """every kind's fields for the screens: what to show, in what order, with what limits."""
    return {
        kind: {
            "fields": [_public(field) for field in _own(kind)],
            "single": kind in SINGLE,
            "quit": kind in QUIT,
        }
        for kind in KINDS
    }


def _public(field):
    out = dict(field)
    if "columns" in out:
        out["columns"] = [_public(column) for column in out["columns"]]
    if "options" in out:
        out["options"] = list(out["options"])
    return out


# ── value checks ───────────────────────────────────────────────────────────────


def _number(value, low, high, *, whole=False, required=True, unknown=False):
    if value is None or value == "":
        if required:
            raise _bad()
        return None
    if unknown and value == UNKNOWN:
        return UNKNOWN
    if isinstance(value, bool):
        raise _bad()
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _bad() from None
    if not math.isfinite(number) or not low <= number <= high:
        raise _bad()
    if whole:
        if number != int(number):
            raise _bad()
        return int(number)
    number = round(number, 2)
    return int(number) if number == int(number) else number


def _text(value, cap):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _bad()
    value = " ".join(value.split())
    if len(value) > cap:
        raise _bad()
    return value


def _raw(value, cap=RAW_CHARS):
    """the owner's words exactly as written: nothing trimmed or folded."""
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > cap:
        raise _bad()
    return value


def _choice(value, options):
    value = str(value or options[0]).strip().lower()
    if value not in options:
        raise _bad()
    return value


_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


def _clock(value):
    if value == UNKNOWN:
        return UNKNOWN
    if not isinstance(value, str) or not _CLOCK.match(value):
        raise _bad()
    return value


def _date(value):
    from datetime import date

    if not isinstance(value, str) or not _DATE.match(value):
        raise _bad()
    try:
        date.fromisoformat(value)
    except ValueError:
        raise _bad() from None
    return value


def _measure(value, field):
    """{"value": n, "unit": u}: kept as entered, never converted. a number without its unit is
    refused, so nothing gets read in a unit nobody meant (6 glasses is not 6 ml)."""
    kind = units.KIND_OF[field.get("measure")]
    if not isinstance(value, dict) or set(value) - {"value", "unit"}:
        raise _bad()
    amount, unit = value.get("value"), value.get("unit")
    amount = _number(amount, -1000 if kind == "temperature" else 0, 1_000_000, unknown=True)
    found = units.canonical(unit, kind)
    if not found:
        raise _bad()
    return {"value": amount, "unit": found}


def _link(value):
    """a pointer at another app's record, with free text as the fallback."""
    if isinstance(value, str):
        value = {"text": value}
    if not isinstance(value, dict):
        raise _bad()
    out = {"text": _text(value.get("text"), BOOK_CHARS)}
    app, rid = value.get("app"), value.get("id")
    if app or rid:
        app = str(app or "").strip().lower()
        if not _SLUG.match(app) or not isinstance(rid, (str, int)) or len(str(rid)) > 80:
            raise _bad()
        out |= {"app": app, "id": str(rid)}
    if not out["text"] and "id" not in out:
        raise _bad()
    return out


def _list(value, cap):
    if not isinstance(value, list) or len(value) > cap:
        raise _bad()
    return value


def _tags(value):
    out = []
    for tag in _list(value, 30):
        tag = _text(tag, 40)
        if tag and tag.lower() not in {t.lower() for t in out}:
            out.append(tag)
    return out


def _files(value):
    out = []
    for item in _list(value, 20):
        if not isinstance(item, str) or not item.strip() or len(item) > 200:
            raise _bad()
        out.append(item.strip())
    return out


def _checklist(value):
    out = []
    for item in _list(value, 30):
        if isinstance(item, str):
            item = {"item": item}
        if not isinstance(item, dict):
            raise _bad()
        name = _text(item.get("item"), NAME_CHARS)
        if not name:
            raise _bad()
        done = item.get("done", True)
        if not isinstance(done, bool):
            raise _bad()
        out.append({"item": name, "done": done})
    return out


def _side(value):
    if value in (None, ""):
        return None
    side = str(value).strip().upper()[:1]
    if side not in SIDES:
        raise _bad()
    return side


def _rows(value, field, scale):
    out = []
    for row in _list(value, 100):
        if not isinstance(row, dict):
            raise _bad()
        clean = {}
        allowed = {column["key"]: column for column in field["columns"]}
        for key, item in row.items():
            if key == "side" and field.get("sides"):
                side = _side(item)
                if side:
                    clean["side"] = side
                continue
            if key == "note":
                clean["note"] = _text(item, NOTE_CHARS)
                continue
            if key not in allowed:
                raise _bad()
            item = _value(allowed[key], item, scale)
            if item is not None:
                clean[key] = item
        if clean:
            out.append(clean)
    return out


def _value(field, value, scale=5):
    """one field's value in its stored form; None means "not given" and is left out."""
    kind = field["type"]
    if value is None or value == "":
        return None
    if kind in ("number", "count", "minutes", "seconds", "rating"):
        if kind == "count":
            low, high, whole = field.get("min", 0), field.get("max", 1_000_000), True
        elif kind == "minutes":
            low, high, whole = 0, 1440, False
        elif kind == "seconds":
            low, high, whole = 0, 86400, False
        elif kind == "rating":
            low, high, whole = 1, field.get("max", scale), True
        else:
            low, high = field.get("min", 0), field.get("max", 1_000_000)
            whole = field.get("whole", False)
        return _number(value, low, high, whole=whole, unknown=True)
    if kind == "clock":
        return _clock(value)
    if kind == "date":
        return _date(value)
    if kind == "measure":
        return _measure(value, field)
    if kind == "yesno":
        if not isinstance(value, bool):
            raise _bad()
        return value
    if kind == "choice":
        return _choice(value, field["options"])
    if kind == "tags":
        return _tags(value) or None
    if kind == "text":
        return _text(value, NOTE_CHARS) or None
    if kind == "link":
        return _link(value)
    if kind == "people":
        return [_link(item) for item in _list(value, 20)] or None
    if kind == "checklist":
        return _checklist(value) or None
    if kind == "files":
        return _files(value) or None
    if kind == "rows":
        return _rows(value, field, scale) or None
    if kind == "sets":
        return [_set(item) for item in _list(value, 100)] or None
    if kind == "exercises":
        return [_exercise(item) for item in _list(value, 50)] or None
    raise _bad()


# ── the gym logger's shapes ────────────────────────────────────────────────────


def _mass_unit(value, default="lb"):
    unit = units.canonical(value or default, "mass")
    if not unit:
        raise _bad()
    return unit


def _set(item):
    """one set, or n identical sets (count). a side set belongs to L or R; sides may differ."""
    if not isinstance(item, dict):
        raise _bad()
    known = {
        "type", "status", "side", "count", "weight", "unit", "reps", "approx", "partial", "bad",
        "rir", "rpe", "assist", "rest", "tempo", "seconds", "distance", "note", "raw",
    }  # fmt: skip
    if set(item) - known:
        raise _bad()
    count = _number(item.get("count"), 1, 100, whole=True, required=False)
    out = {
        "type": _choice(item.get("type"), SET_TYPES),
        "status": _choice(item.get("status"), SET_STATUSES),
        "count": 1 if count is None else count,
    }
    side = _side(item.get("side"))
    if side:
        out["side"] = side
    weight = _number(item.get("weight"), 0, 2000, required=False, unknown=True)
    if weight is not None:
        out["weight"] = weight
        out["unit"] = _mass_unit(item.get("unit"))
    reps = _number(item.get("reps"), 0, 1000, whole=True, required=False, unknown=True)
    if reps is not None:
        out["reps"] = reps
    if item.get("approx") is not None:
        if not isinstance(item["approx"], bool):
            raise _bad()
        if item["approx"]:
            out["approx"] = True
    for key, low, high, whole in (
        ("partial", 0, 1000, True),
        ("bad", 0, 1000, True),
        ("rir", 0, 10, False),
        ("rpe", 1, 10, False),
        ("assist", 0, 2000, False),
        ("rest", 0, 3600, False),
        ("seconds", 0, 86400, False),
    ):
        value = _number(item.get(key), low, high, whole=whole, required=False, unknown=True)
        if value is not None:
            out[key] = value
    if "assist" in out:
        out.setdefault("unit", _mass_unit(item.get("unit")))
    if item.get("distance") not in (None, ""):
        out["distance"] = _measure(item["distance"], {"measure": "distance"})
    tempo = _text(item.get("tempo"), 12)
    if tempo:
        out["tempo"] = tempo
    note = _text(item.get("note"), NOTE_CHARS)
    if note:
        out["note"] = note
    raw = _raw(item.get("raw"))
    if raw:
        out["raw"] = raw
    return out


def _exercise(item):
    if not isinstance(item, dict):
        raise _bad()
    known = {
        "name",
        "setup",
        "unilateral",
        "superset",
        "rest",
        "note",
        "raw",
        "first_time",
        "unit",
        "sets",
    }
    if set(item) - known:
        raise _bad()
    name = _text(item.get("name"), NAME_CHARS)
    if not name:
        raise _bad()
    out = {"name": name}
    setup = item.get("setup") or {}
    if not isinstance(setup, dict) or set(setup) - set(SETUP_KEYS) - {"basis"}:
        raise _bad()
    clean = {key: _text(setup.get(key), 40) for key in SETUP_KEYS if setup.get(key)}
    if setup.get("basis"):
        clean["basis"] = _choice(setup["basis"], LOAD_BASES)
    if clean:
        out["setup"] = clean
    for key in ("unilateral", "first_time"):
        if item.get(key) is not None:
            if not isinstance(item[key], bool):
                raise _bad()
            if item[key]:
                out[key] = True
    superset = _text(item.get("superset"), 8)
    if superset:
        out["superset"] = superset
    rest = _number(item.get("rest"), 0, 3600, required=False)
    if rest is not None:
        out["rest"] = rest
    if item.get("unit"):
        out["unit"] = _mass_unit(item["unit"])
    note = _text(item.get("note"), NOTE_CHARS)
    if note:
        out["note"] = note
    raw = _raw(item.get("raw"), RAW_CHARS)
    if raw:
        out["raw"] = raw
    out["sets"] = [_set(one) for one in _list(item.get("sets") or [], 100)]
    return out


# ── a habit's field setup (habits.fields) ──────────────────────────────────────


def _custom(item, taken):
    if not isinstance(item, dict):
        raise _bad()
    key = str(item.get("key") or "").strip().lower()
    if not key.startswith("c_") or not _SLUG.match(key) or key in taken:
        raise HabitLogError("each custom field needs its own short name")
    kind = str(item.get("type") or "").strip().lower()
    if kind not in CUSTOM_TYPES:
        raise HabitLogError("that field type doesn't exist")
    label = _text(item.get("label"), 40)
    if not label:
        raise HabitLogError("each custom field needs its own short name")
    out = {"key": key, "type": kind, "label": label, "on": True}
    if kind == "measure":
        measure = str(item.get("measure") or "")
        if measure not in units.CHOICES:
            raise _bad()
        out["measure"] = measure
    elif kind in ("number", "count"):
        unit = check_unit(item.get("unit"))
        if unit:
            out["unit"] = unit
    if kind == "choice":
        options = [_text(option, 40).lower() for option in _list(item.get("options"), 30)]
        options = list(dict.fromkeys(option for option in options if option))
        if not options:
            raise _bad()
        out["options"] = tuple(options)
    if kind == "rating" and item.get("max") is not None:
        if item["max"] not in (5, 10):
            raise _bad()
        out["max"] = item["max"]
    return out


def all_fields(kind, config=None) -> list:
    """the kind's fields, the shared ones and this habit's own custom fields."""
    config = config or {}
    return _own(kind) + list(config.get("custom") or [])


def check_fields(kind, config) -> dict | None:
    """a habit's field setup: which fields show, defaults, custom fields, targets and more."""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise _bad()
    known = {
        "on", "defaults", "custom", "scale", "targets", "units", "hidden", "sensitive",
        "baseline", "taper", "mode", "rules", "why", "weight_step", "warmups_count",
    }  # fmt: skip
    if set(config) - known:
        raise _bad()
    out = {}
    taken = {field["key"] for field in _own(kind)}
    custom = []
    for item in _list(config.get("custom") or [], 30):
        field = _custom(item, taken)
        taken.add(field["key"])
        custom.append(field)
    if custom:
        out["custom"] = custom
    by_key = {field["key"]: field for field in all_fields(kind, out)}
    if config.get("on") is not None:
        on = [str(key) for key in _list(config["on"], 100)]
        if set(on) - set(by_key):
            raise _bad()
        out["on"] = list(dict.fromkeys(on))
    scale = config.get("scale")
    if scale is not None:
        if scale not in (5, 10):
            raise _bad()
        out["scale"] = scale
    defaults = {}
    for key, value in (config.get("defaults") or {}).items():
        if key not in by_key:
            raise _bad()
        value = _value(by_key[key], value, out.get("scale", 5))
        if value is not None:
            defaults[key] = value
    if defaults:
        out["defaults"] = defaults
    targets = {}
    for key, target in (config.get("targets") or {}).items():
        if key not in by_key or not isinstance(target, dict):
            raise _bad()
        low = _number(target.get("min"), 0, 1_000_000_000, required=False)
        high = _number(target.get("max"), 0, 1_000_000_000, required=False)
        if low is None and high is None or (low is not None and high is not None and low > high):
            raise _bad()
        clean = {"period": _choice(target.get("period"), PERIODS)}
        if low is not None:
            clean["min"] = low
        if high is not None:
            clean["max"] = high
        targets[key] = clean
    if targets:
        out["targets"] = targets
    if config.get("units"):
        try:
            out["units"] = units.check_preferences(config["units"])
        except units.UnitError as error:
            raise HabitLogError(str(error)) from None
    if config.get("hidden"):
        out["hidden"] = _tags(config["hidden"])
    if config.get("sensitive") is not None:
        if not isinstance(config["sensitive"], bool):
            raise _bad()
        out["sensitive"] = config["sensitive"]
    for key in ("baseline", "taper"):
        if config.get(key):
            if not isinstance(config[key], dict) or len(config[key]) > 10:
                raise _bad()
            out[key] = {
                _text(name, 24): _number(value, 0, 1_000_000) for name, value in config[key].items()
            }
    if config.get("mode"):
        out["mode"] = _choice(config["mode"], QUIT_MODES)
    if config.get("rules"):
        out["rules"] = [_text(rule, NOTE_CHARS) for rule in _list(config["rules"], 20)]
    if config.get("why"):
        out["why"] = _text(config["why"], NOTE_CHARS)
    if config.get("weight_step") is not None:
        out["weight_step"] = _number(config["weight_step"], 0.25, 100)
    if config.get("warmups_count") is not None:
        if not isinstance(config["warmups_count"], bool):
            raise _bad()
        out["warmups_count"] = config["warmups_count"]
    return out


# ── a day's log ────────────────────────────────────────────────────────────────


def _entry(kind, item, config):
    if not isinstance(item, dict):
        raise _bad()
    known = {"id", "time", "values", "note", "raw", "tags", "photos", "slip", "skip", "import"}
    if set(item) - known:
        raise _bad()
    entry_id = str(item.get("id") or secrets.token_hex(4))
    if len(entry_id) > 24:
        raise _bad()
    out = {"id": entry_id}
    if item.get("time"):
        out["time"] = _clock(item["time"])
    by_key = {field["key"]: field for field in all_fields(kind, config)}
    values = item.get("values") or {}
    if not isinstance(values, dict):
        raise _bad()
    scale = (config or {}).get("scale", 5)
    clean = {}
    for key, value in values.items():
        if key not in by_key:
            raise _bad()
        value = _value(by_key[key], value, scale)
        if value is not None:
            clean[key] = value
    out["values"] = clean
    note = _text(item.get("note"), LONG_CHARS)
    if note:
        out["note"] = note
    raw = _raw(item.get("raw"))
    if raw:
        out["raw"] = raw
    if item.get("tags"):
        out["tags"] = _tags(item["tags"])
    if item.get("photos"):
        out["photos"] = _files(item["photos"])
    for flag in ("slip", "skip"):
        if item.get(flag) is not None:
            if not isinstance(item[flag], bool):
                raise _bad()
            if item[flag]:
                out[flag] = True
    if out.get("slip") and kind not in QUIT:
        raise _bad()
    if item.get("import"):
        batch = str(item["import"])
        if len(batch) > 40:
            raise _bad()
        out["import"] = batch
    return out


def _v2(kind, data, config):
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise _bad()
    if len(entries) > MAX_ENTRIES:
        raise HabitLogError("a day holds at most 50 entries")
    if kind in SINGLE and len(entries) > 1:
        raise HabitLogError("this habit keeps one entry a day")
    out = [_entry(kind, item, config) for item in entries]
    ids = [entry["id"] for entry in out]
    if len(set(ids)) != len(ids):
        raise _bad()
    if not out:
        return None
    doc = {"v": 2, "entries": out}
    if data.get("created_by"):
        doc["created_by"] = str(data["created_by"])[:40]
    return doc


def _v1(kind, data):
    """the old one-object shapes, still sent by the screens built before v2."""
    if kind == "workout":
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise _bad()
        if len(rows) > MAX_ROWS:
            raise HabitLogError("a workout log holds at most 50 rows")
        out = []
        for row in rows:
            if not isinstance(row, dict):
                raise _bad()
            exercise = _text(row.get("exercise"), NAME_CHARS)
            if not exercise:
                raise _bad()
            reps = _number(row.get("reps"), 1, 1000, whole=True, required=False)
            sets = _number(row.get("sets"), 1, 100, whole=True, required=False)
            out.append(
                {
                    "exercise": exercise,
                    "weight": _number(row.get("weight"), 0, 2000, required=False),
                    "reps": DEFAULT_REPS if reps is None else reps,
                    "sets": 1 if sets is None else sets,
                    "note": _text(row.get("note"), NOTE_CHARS),
                }
            )
        return {"rows": out} if out else None
    if kind == "reading":
        return {
            "amount": _number(data.get("amount"), 0, 10000),
            "unit": _choice(data.get("unit"), READING_UNITS),
            "book": _text(data.get("book"), BOOK_CHARS),
        }
    if kind == "count":
        return {"amount": _number(data.get("amount"), 0, 1_000_000)}
    if kind == "duration":
        return {"minutes": _number(data.get("minutes"), 0, 1440)}
    if kind == "distance":
        return {
            "distance": _number(data.get("distance"), 0, 1000),
            "unit": _choice(data.get("unit"), DISTANCE_UNITS),
            "minutes": _number(data.get("minutes"), 0, 1440, required=False),
        }
    raise _bad()


def is_v2(data) -> bool:
    return isinstance(data, dict) and data.get("v") == 2


def from_v1(kind, data):
    """a clean v1 log as a v2 document. nothing is dropped: every v1 value has a v2 place."""
    if data is None:
        return None
    if kind == "workout":
        exercises = []
        for row in data.get("rows") or []:
            one = {"type": "working", "status": "done", "count": row.get("sets") or 1}
            if row.get("weight") is not None:
                one |= {"weight": row["weight"], "unit": "lb"}
            one["reps"] = row.get("reps") or DEFAULT_REPS
            exercise = {"name": row["exercise"], "sets": [one]}
            if row.get("note"):
                exercise["note"] = row["note"]
            exercises.append(exercise)
        values = {"exercises": exercises} if exercises else {}
    elif kind == "reading":
        values = {data.get("unit") or "pages": data.get("amount")}
        if data.get("book"):
            values["book"] = {"text": data["book"]}
    elif kind == "count":
        values = {"amount": data.get("amount")}
    elif kind == "duration":
        values = {"minutes": data.get("minutes")}
    elif kind == "distance":
        values = {"distance": {"value": data.get("distance"), "unit": data.get("unit") or "km"}}
        if data.get("minutes") is not None:
            values["minutes"] = data["minutes"]
    else:
        return None
    values = {key: value for key, value in values.items() if value is not None}
    return {"v": 2, "entries": [{"id": "v1", "values": values}]} if values else None


def clean_log(kind: str, data, config=None):
    """the stored (v2) form of a day's details, or None when there is nothing beyond "done"."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise _bad()
    if is_v2(data):
        return _v2(kind, data, config)
    if kind == "check":
        raise HabitLogError("this habit is a simple check and has no log details")
    if kind not in LEGACY:
        raise _bad()
    return from_v1(kind, _v1(kind, data))


def merge_v1(kind, stored, incoming):
    """a v1 save from an old screen over a stored v2 log. rows the old screen showed unchanged
    keep their full v2 detail (sides, unknowns, raw notes); edited rows take the new values."""
    if not is_v2(stored) or incoming is None:
        return incoming
    if legacy_view(kind, stored) == legacy_view(kind, incoming):
        return stored
    if kind != "workout":
        return incoming
    # the old screen shows one row per set group, so a stored exercise is a run of rows
    old = list(_exercises(stored))
    new = _exercises(incoming)
    rows = [_legacy_rows([exercise]) for exercise in new]
    merged, at = [], 0
    while at < len(new):
        for exercise in old:
            mine = _legacy_rows([exercise])
            if [row for group in rows[at : at + len(mine)] for row in group] == mine:
                merged.append(exercise)
                old.remove(exercise)
                at += len(mine)
                break
        else:
            merged.append(new[at])
            at += 1
    entry = dict(incoming["entries"][0])
    entry["values"] = {"exercises": merged}
    return {"v": 2, "entries": [entry]}


def _exercises(doc):
    out = []
    for entry in (doc or {}).get("entries") or []:
        out += (entry.get("values") or {}).get("exercises") or []
    return out


def _legacy_rows(exercises):
    rows = []
    for exercise in exercises:
        for one in exercise.get("sets") or [{}]:
            weight = one.get("weight")
            reps = one.get("reps")
            rows.append(
                {
                    "exercise": exercise["name"],
                    "weight": weight if isinstance(weight, (int, float)) else None,
                    "reps": reps if isinstance(reps, int) and reps > 0 else DEFAULT_REPS,
                    "sets": one.get("count") or 1,
                    "note": exercise.get("note", ""),
                }
            )
    return rows[:MAX_ROWS]


def _total(doc, key):
    total = None
    for entry in doc.get("entries") or []:
        value = (entry.get("values") or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total = (total or 0) + value
    return total


def legacy_view(kind, doc):
    """a v2 log in the old shape, for screens that still read v1. None when it has no v1 form."""
    if not is_v2(doc):
        return doc
    if kind == "workout":
        rows = _legacy_rows(_exercises(doc))
        return {"rows": rows} if rows else None
    if kind == "reading":
        values = (doc["entries"] or [{}])[0].get("values") or {}
        unit = "chapters" if "chapters" in values and "pages" not in values else "pages"
        amount = _total(doc, unit)
        book = (values.get("book") or {}).get("text", "")
        return None if amount is None else {"amount": amount, "unit": unit, "book": book}
    if kind == "count":
        amount = _total(doc, "amount")
        return None if amount is None else {"amount": amount}
    if kind == "duration":
        minutes = _total(doc, "minutes")
        return None if minutes is None else {"minutes": minutes}
    if kind == "distance":
        first = None
        for entry in doc["entries"]:
            first = first or (entry.get("values") or {}).get("distance")
        if not first or not isinstance(first.get("value"), (int, float)):
            return None
        unit = first["unit"] if first["unit"] in DISTANCE_UNITS else "km"
        total = 0
        for entry in doc["entries"]:
            one = (entry.get("values") or {}).get("distance")
            if one and isinstance(one.get("value"), (int, float)):
                total += units.change(one["value"], one["unit"], unit)
        return {"distance": round(total, 2), "unit": unit, "minutes": _total(doc, "minutes")}
    return None


def day_state(doc) -> str:
    """how a stored day counts: "done", "slip" (recorded, not clean) or "skip" (planned)."""
    entries = doc.get("entries") if is_v2(doc) else None
    if not entries:
        return "done"
    if any(entry.get("slip") for entry in entries):
        return "slip"
    if all(entry.get("skip") for entry in entries):
        return "skip"
    return "done"


def dump(data) -> str | None:
    return None if data is None else json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def load(raw):
    """a stored log's details; an unreadable old value reads as no details."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_fields(raw):
    data = load(raw)
    return data if isinstance(data, dict) else None


def exercise_names(logs) -> list[str]:
    """names used in past workout logs, newest day first, each once (any case)."""
    seen, out = set(), []
    for _day, data in sorted(logs, key=lambda item: item[0], reverse=True):
        if is_v2(data):
            names = [exercise.get("name") for exercise in _exercises(data)]
        else:
            rows = (data or {}).get("rows") or []
            names = (
                [row.get("exercise") for row in rows if isinstance(row, dict)]
                if isinstance(rows, list)
                else []
            )
        for name in names:
            name = str(name or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
    return out[:200]
