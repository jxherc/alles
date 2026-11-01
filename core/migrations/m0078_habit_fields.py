"""m0078 - habit logs get every detail: a field setup per habit and one log shape (v2).

habits.fields: json with the habit's field setup (which fields show, defaults, custom fields,
targets, unit overrides). null means the kind's defaults.

habit_logs.data: every old (v1) log becomes {"v": 2, "entries": [...]}: a workout's rows become
exercises with their sets, a reading's pages or chapters, a count's amount, a duration's
minutes, a distance with its unit. nothing is dropped; a value the v1 checks would refuse (an
old row from before the checks) stays exactly as it was stored.

health_entries: a body weight's free text unit gets its real name ("lbs", "pounds" -> "lb",
"kgs" -> "kg"); an empty one is "lb", the owner's rule for every weight. text that isn't a unit
stays as written.

running it again changes nothing: v2 logs and named units are left alone.
"""

import json

from sqlalchemy import text

from core.migrations.runner import add_column

VERSION = 78
NAME = "habit_fields"


def _upgrade(kind, raw):
    from services import habit_kinds

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or habit_kinds.is_v2(data):
        return None
    if (kind or "check") not in habit_kinds.LEGACY or kind == "check":
        return None
    try:
        doc = habit_kinds.clean_log(kind, data)
    except habit_kinds.HabitLogError:
        return None
    return habit_kinds.dump(doc)


def up(conn):
    from services import units

    have = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "habits" in have:
        add_column(conn, "habits", "fields", "TEXT")
    if "habits" in have and "habit_logs" in have:
        rows = conn.execute(
            text(
                "SELECT habit_logs.id, habits.kind, habit_logs.data FROM habit_logs "
                "JOIN habits ON habits.id = habit_logs.habit_id "
                "WHERE habit_logs.data IS NOT NULL AND habit_logs.data != ''"
            )
        ).fetchall()
        for log_id, kind, raw in rows:
            new = _upgrade(kind, raw)
            if new is not None and new != raw:
                conn.execute(
                    text("UPDATE habit_logs SET data = :data WHERE id = :id"),
                    {"data": new, "id": log_id},
                )
    if "health_entries" in have:
        rows = conn.execute(
            text("SELECT id, unit FROM health_entries WHERE kind = 'weight'")
        ).fetchall()
        for entry_id, unit in rows:
            named = units.canonical(unit, "mass") if (unit or "").strip() else "lb"
            if named and named != unit:
                conn.execute(
                    text("UPDATE health_entries SET unit = :unit WHERE id = :id"),
                    {"unit": named, "id": entry_id},
                )
