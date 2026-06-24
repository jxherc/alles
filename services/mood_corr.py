"""4b - explainable mood<->behavior correlations.

builds per-day series (journal mood scored 1..5, habit completion, health metrics) and runs a
tie-corrected Spearman between mood and each behavior. nothing fancy/black-box: rank correlation
+ a plain-language explanation + the overlap count, so the user can judge it. the route enforces
the journal lock, so mood data never leaves the gate.
"""

import re
from datetime import date as _date
from datetime import timedelta

from services.life_stats import spearman  # tie-corrected rank correlation (shared)

# the journal mood picker (static/js/journal.js MOODS) plus common typed/synced words/emoji.
# scale: 5 great .. 1 awful. unknown -> None (that day is skipped, not guessed).
_MOOD = {
    # picker emoji
    "😄": 5, "😍": 5, "🥳": 5, "🙂": 4, "🤔": 3, "😐": 3, "😴": 2, "😕": 2, "😢": 1, "😠": 1,
    # extra emoji that show up via sync / paste
    "😁": 5, "🥰": 5, "🤩": 5, "😆": 5, "😊": 4, "😌": 4, "👍": 4, "😶": 3, "😔": 2, "😟": 2,
    "😞": 2, "😣": 2, "😭": 1, "😡": 1, "😫": 1, "😩": 1,
    # words
    "great": 5, "amazing": 5, "happy": 5, "excellent": 5, "joy": 5, "joyful": 5, "wonderful": 5,
    "ecstatic": 5, "good": 4, "calm": 4, "content": 4, "relaxed": 4, "grateful": 4, "fine": 4,
    "chill": 4, "productive": 4, "hopeful": 4, "ok": 3, "okay": 3, "meh": 3, "neutral": 3,
    "average": 3, "alright": 3, "blah": 3, "tired": 2, "stressed": 2, "anxious": 2, "down": 2,
    "sad": 2, "bored": 2, "worried": 2, "frustrated": 2, "low": 2, "sick": 2, "awful": 1,
    "terrible": 1, "depressed": 1, "angry": 1, "miserable": 1, "exhausted": 1, "horrible": 1,
    "bad": 1,
}


def mood_score(s):
    """freeform mood -> 1..5, or None if nothing recognised. whole string, then tokens, then
    any single emoji char."""
    if not s:
        return None
    t = s.strip().lower()
    if t in _MOOD:
        return _MOOD[t]
    for tok in re.split(r"[\s,/]+", t):
        if tok in _MOOD:
            return _MOOD[tok]
    for ch in s:
        if ch in _MOOD:
            return _MOOD[ch]
    return None


def _explain(label, rho):
    strength = "strong" if abs(rho) >= 0.5 else ("moderate" if abs(rho) >= 0.3 else "slight")
    name = label.split(":", 1)[1] if ":" in label else label
    if label.startswith("habit:"):
        side = "higher" if rho > 0 else "lower"
        return f"{strength} link - your mood runs {side} on days you do {name}"
    better = "better" if rho > 0 else "worse"
    more = "more" if rho > 0 else "less"
    return f"{strength} link - {more} {name} tracks with {better} mood"


def correlations(db, *, days=180, min_overlap=6):
    """mood vs each behavior over the last `days`. returns {ok, correlations:[{label, rho, n,
    explain}], ...}. needs >= min_overlap shared days per pair to report it."""
    from core.database import Habit, HabitLog, HealthEntry, JournalEntry, Task

    since = (_date.today() - timedelta(days=max(1, days))).isoformat()

    mood = {}
    for e in db.query(JournalEntry).filter(JournalEntry.date >= since).all():
        sc = mood_score(e.mood)
        if sc is not None:
            mood[e.date] = sc
    if len(mood) < min_overlap:
        return {
            "ok": False,
            "reason": f"need {min_overlap}+ days with a mood logged (have {len(mood)})",
            "mood_days": len(mood),
            "correlations": [],
        }

    series = {}  # label -> {date: value}

    # habits: 1 if done that day else 0, windowed from the habit's first log (days before you
    # tracked it aren't "missed"). a habit with no logs has no signal, so it's skipped.
    habits = db.query(Habit).filter(Habit.archived == False).all()  # noqa: E712
    done = {}
    for log in db.query(HabitLog).filter(HabitLog.date >= since).all():
        done.setdefault(log.habit_id, set()).add(log.date)
    for h in habits:
        hdates = done.get(h.id, set())
        if not hdates:
            continue
        born = min(hdates)
        s = {d: (1.0 if d in hdates else 0.0) for d in mood if d >= born}
        if s:
            series[f"habit:{h.name}"] = s
    if done:
        series["habits done (total)"] = {
            d: float(sum(1 for ds in done.values() if d in ds)) for d in mood
        }

    # health: per kind (or custom label), the day's value (mean if several that day)
    hv = {}
    for h in db.query(HealthEntry).filter(HealthEntry.date >= since).all():
        key = (h.label or "").strip() if (h.kind == "custom" and (h.label or "").strip()) else h.kind
        if not key:
            continue
        hv.setdefault(key, {}).setdefault(h.date, []).append(h.value or 0.0)
    for key, byday in hv.items():
        series[f"health:{key}"] = {d: sum(v) / len(v) for d, v in byday.items()}

    # task<->life balance: tasks finished per day (by completed_at), counted on journaled days
    finished = {}
    for t in db.query(Task).filter(Task.completed_at != None).all():  # noqa: E711
        if t.completed_at:
            d = t.completed_at.date().isoformat()
            finished[d] = finished.get(d, 0) + 1
    if finished:
        series["tasks completed"] = {d: float(finished.get(d, 0)) for d in mood}

    out = []
    for label, s in series.items():
        common = [d for d in s if d in mood]
        if len(common) < min_overlap:
            continue
        rho = spearman([mood[d] for d in common], [s[d] for d in common])
        if rho is None:
            continue
        out.append({"label": label, "rho": round(rho, 3), "n": len(common), "explain": _explain(label, rho)})
    out.sort(key=lambda x: -abs(x["rho"]))
    return {"ok": True, "days": days, "mood_days": len(mood), "correlations": out}
