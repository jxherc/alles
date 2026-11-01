"""reading a set from how the owner says it ("70x10", "left 60x12 right 70x10", "next 85").

the rules are the owner's (vault skill workout-logging and the notes at the top of workout.md):
- pounds unless a unit is said; dumbbells per hand, plate loaded machines per side.
- a bare weight is a completed set; reps default to 10.
- "next", "i'll try", "i'll start" mean planned, not done.
- "?" is unknown and stays unknown. "10+5" is 10 reps and 5 partials. "~10" is about 10.
- "left 60x12 right 70x10" splits by side; "15 per hand x left 12, right 10" shares the weight.
- the same side twice ("right 10 ... right 12") is a mislabeled side: ask one yes or no question
  instead of guessing.
nothing is converted or corrected: the raw text stays with the parsed values.
"""

import re

DEFAULT_REPS = 10
_NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"
_UNIT = r"(?:lbs?|pounds?|kgs?|kilos?|kilograms?)"
_TIMES = r"\s*(?:x|×|\*)\s*"
_PLANNED = re.compile(
    r"^\s*(?:next|i'?ll\s+(?:try|start|do|go)|i\s+will\s+(?:try|start|do|go)|going\s+to|gonna|try|trying)\b",
    re.IGNORECASE,
)
_SIDE_WORD = {"left": "L", "l": "L", "right": "R", "r": "R"}
_REPS = r"(?P<reps>\?|~?\s*\d+(?:\s*\+\s*\d+)?)"


class Unclear(ValueError):
    """the text can't be read as a set without guessing."""


def _unit(word):
    word = (word or "").lower()
    return "kg" if word.startswith("k") else "lb"


def _number(text):
    value = float(text)
    return int(value) if value == int(value) else value


def _reps(text):
    """ "12" -> {reps: 12}; "10+5" -> partial 5; "~10" -> approx; "?" -> unknown."""
    text = (text or "").replace(" ", "")
    if not text:
        return {"reps": DEFAULT_REPS}
    if text == "?":
        return {"reps": "?"}
    if not re.fullmatch(r"~?\d+(?:\+\d+)?", text):
        raise Unclear(text)
    out = {}
    if text.startswith("~"):
        out["approx"] = True
        text = text[1:]
    whole, _, partial = text.partition("+")
    out["reps"] = int(whole)
    if partial:
        out["partial"] = int(partial)
    return out


def _weight(text):
    if text is None:
        return {}
    text = text.strip()
    if text == "?":
        return {"weight": "?", "unit": "lb"}
    match = re.fullmatch(rf"({_NUM})\s*({_UNIT})?", text, re.IGNORECASE)
    if not match:
        raise Unclear(text)
    return {"weight": _number(match.group(1)), "unit": _unit(match.group(2))}


def _basis(text):
    lowered = text.lower()
    if re.search(r"\bper\s+(?:hand|arm|dumbbell|db)\b|\beach\s+hand\b", lowered):
        return "per_hand"
    if re.search(r"\bper\s+side\b|\beach\s+side\b", lowered):
        return "per_side"
    return None


_STRIP_BASIS = re.compile(r"\s*\b(?:per|each)\s+(?:hand|arm|side|dumbbell|db)\b", re.IGNORECASE)
_SIDE_PART = re.compile(
    rf"\b(?P<side>left|right|l|r)\b\s*(?:did\s+|side\s+)?(?:(?P<weight>{_NUM}\s*{_UNIT}?|\?){_TIMES})?{_REPS}",
    re.IGNORECASE,
)


def _sides(body, shared):
    """'left 60x12, right 70x10' or 'left 12, right 10' after a shared weight."""
    parts = list(_SIDE_PART.finditer(body))
    if not parts:
        return None
    seen = [_SIDE_WORD[part.group("side").lower()] for part in parts]
    if len(seen) != len(set(seen)):
        side = "left" if seen[0] == "R" else "right"
        raise Unclear(f"is that {side}?")
    sets = []
    for part, side in zip(parts, seen):
        one = {"side": side}
        weight = part.group("weight")
        one |= _weight(weight) if weight else dict(shared)
        one |= _reps(part.group("reps"))
        sets.append(one)
    return sets


def parse(text: str) -> dict:
    """{sets: [...], basis, raw} for one reported set (or one per side). raises Unclear with
    the one question to ask when it can't be read without guessing."""
    raw = text
    body = " ".join(str(text or "").split())
    if not body:
        raise Unclear("what weight and reps?")
    status = "planned" if _PLANNED.search(body) else "done"
    body = _PLANNED.sub("", body).strip(" :,-")
    basis = _basis(body)
    body = _STRIP_BASIS.sub("", body)
    # "30 assistance x 8": an assisted machine's number is help, not load
    assisted = bool(re.search(r"\d\s*(?:lbs?|kgs?)?\s*assist(?:ance|ed)?\b", body, re.IGNORECASE))
    body = re.sub(
        r"(\d)\s*((?:lbs?|kgs?)?)\s*assist(?:ance|ed)?\b", r"\1\2", body, flags=re.IGNORECASE
    )
    if assisted:
        basis = "assist"
    # notes in brackets stay in raw only: "left ~10 (last 3 reps bad)"
    body = re.sub(r"\([^)]*\)", " ", body)
    body = " ".join(body.split()).strip(" ,;")

    count = 1
    sets_match = re.search(r"(?:x\s*)?(\d+)\s*sets?\b", body, re.IGNORECASE)
    if sets_match:
        count = int(sets_match.group(1))
        body = (body[: sets_match.start()] + body[sets_match.end() :]).strip(" ,;x×*")

    # "8 reps of 70", "10 reps at 70"
    reps_of = re.fullmatch(
        rf"(\d+)\s*reps?\s*(?:of|at|with|@)\s*({_NUM}\s*{_UNIT}?)", body, re.IGNORECASE
    )
    if reps_of:
        one = _weight(reps_of.group(2)) | {"reps": int(reps_of.group(1))}
        return _done([one], status, count, basis, raw)

    # a shared weight in front: "15 x left 12, right 10", "65; left ~10, right 12", "40 x right 10"
    lead = re.match(
        rf"^(?P<weight>{_NUM}\s*{_UNIT}?|\?)\s*(?:x|×|\*|;|,)?\s*(?=\b(?:left|right|l|r)\b)",
        body,
        re.IGNORECASE,
    )
    if lead:
        shared = _weight(lead.group("weight"))
        sets = _sides(body[lead.end() :], shared)
        if sets:
            return _done(sets, status, count, basis, raw)
    if re.match(r"^(?:left|right)\b", body, re.IGNORECASE):
        sets = _sides(body, {})
        if sets:
            return _done(sets, status, count, basis, raw)

    # "70x10", "70 x 10/10/12", "70kg x 10x3", "85 x ?", "12 both sides"
    plain = re.fullmatch(
        rf"(?P<weight>{_NUM}\s*{_UNIT}?|\?)(?:{_TIMES}(?P<reps>[\d?~+/\s]+?))?(?:{_TIMES}(?P<count>\d+))?(?P<both>\s+both\s+sides)?",
        body,
        re.IGNORECASE,
    )
    if plain:
        weight = _weight(plain.group("weight"))
        if plain.group("count"):
            count = int(plain.group("count"))
        reps = (plain.group("reps") or "").strip()
        parts = [part for part in reps.split("/") if part.strip()] or [""]
        sets = [weight | _reps(part) for part in parts]
        if plain.group("both"):
            sets = [dict(one, side=side) for one in sets for side in ("L", "R")]
        return _done(sets, status, count, basis, raw)
    raise Unclear("what weight and reps?")


def _done(sets, status, count, basis, raw):
    for one in sets:
        one["status"] = status
        if count > 1:
            one["count"] = count
        if basis == "assist" and isinstance(one.get("weight"), (int, float)):
            one["assist"] = one.pop("weight")
    out = {"sets": sets, "raw": raw}
    if basis:
        out["basis"] = basis
    return out


def describe(sets) -> str:
    """the short confirmation the owner wants: "55 lb x 12" or "left 60 lb x 12, right 70 lb x 10"."""
    parts = []
    for one in sets:
        weight = one.get("weight")
        text = "?" if weight == "?" else f"{weight:g}" if isinstance(weight, float) else str(weight)
        reps = one.get("reps", DEFAULT_REPS)
        item = f"{text} {one.get('unit', 'lb')} x {'~' if one.get('approx') else ''}{reps}"
        if one.get("partial"):
            item += f"+{one['partial']}"
        if one.get("count", 1) > 1:
            item += f" x {one['count']} sets"
        if one.get("side"):
            item = f"{'left' if one['side'] == 'L' else 'right'} {item}"
        if one.get("status") == "planned":
            item = f"planned {item}"
        parts.append(item)
    return ", ".join(parts)
