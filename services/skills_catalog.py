"""
the built-in skill library you can install with one click. the big catalog lives as
JSON files under services/skill_library/*.json (each a list of skill dicts), so it
can be huge + sourced from many places. a small built-in set is the fallback if the
folder is empty. each skill: name / description / when_to_use / body.
"""

import json
from pathlib import Path

_LIB_DIR = Path(__file__).parent / "skill_library"

# fallback so the app is never empty even before the library folder is populated
_BASE = [
    {
        "name": "Summarize",
        "description": "condense long text into the key points",
        "when_to_use": "when the user wants a tl;dr, recap, or summary of something long",
        "body": "1. read the whole input first.\n2. pull out the 3-5 load-bearing points.\n"
        "3. write them as tight bullets, no filler.\n4. end with a one-line takeaway.",
    },
    {
        "name": "Web Research",
        "description": "research a topic and answer with cited sources",
        "when_to_use": "when asked to look something up, research, or find current info",
        "body": "1. break the question into 2-3 specific sub-queries.\n2. search the web for each.\n"
        "3. read the best sources (not just snippets).\n4. synthesize a direct answer.\n5. cite each claim with its source url.",
    },
    {
        "name": "Code Review",
        "description": "review a change for bugs, then clarity",
        "when_to_use": "when reviewing a diff, PR, or a chunk of code",
        "body": "1. understand what the change is trying to do.\n2. look for correctness bugs first.\n"
        "3. then clarity/naming/dead code.\n4. report findings worst-first; suggest a fix for each.",
    },
]


def _load() -> list[dict]:
    out = []
    if _LIB_DIR.is_dir():
        for f in sorted(_LIB_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text("utf-8"))
                if isinstance(data, list):
                    out.extend(x for x in data if isinstance(x, dict) and x.get("name"))
            except Exception:
                continue
    return out or _BASE


def items() -> list[dict]:
    """catalog rows with a stable slug, de-duped, ready to serve/install."""
    from services.skills_store import _slug

    seen, out = set(), []
    for c in _load():
        try:
            slug = _slug(c["name"])
        except Exception:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        out.append(
            {
                "slug": slug,
                "name": c["name"],
                "description": c.get("description", ""),
                "when_to_use": c.get("when_to_use", ""),
                "body": c.get("body", ""),
            }
        )
    return out


def get(slug: str):
    for it in items():
        if it["slug"] == slug:
            return it
    return None
