"""
first-class skills — reusable procedures the agent can discover + load and the
user can manage. each skill is data/skills/<slug>/SKILL.md with yaml-ish
frontmatter (name / description / when_to_use) + a markdown body, matching the
SKILL.md convention agent_tools already reads. match() scores skills against a
request so the right one surfaces automatically.
"""

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "data" / "skills"

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")

# usage sidecar — kept out of the SKILL.md so loading a skill doesn't rewrite it.
# { slug: {"uses": int, "last_used": epoch, "pinned": bool} }
_USAGE_FILE = "_usage.json"


def _usage_path() -> Path:
    return _dir() / _USAGE_FILE


def _load_usage() -> dict:
    p = _usage_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_usage(d: dict):
    try:
        _usage_path().write_text(json.dumps(d), "utf-8")
    except Exception:
        pass


def usefulness(u: dict) -> float:
    """one number to sort skills by. pinned always wins, then usage, then recency."""
    uses = u.get("uses", 0) or 0
    last = u.get("last_used", 0) or 0
    score = float(uses)
    if last:
        age_days = max(0.0, (time.time() - last) / 86400)
        score += 2.0 / (1 + age_days)  # recency nudge, decays over days
    if u.get("pinned"):
        score += 1e6
    return score


def record_use(slug: str):
    """bump a skill's use count — the real 'this was useful' signal is loading it."""
    try:
        s = _slug(slug)
    except Exception:
        return
    d = _load_usage()
    row = d.get(s) or {}
    row["uses"] = (row.get("uses", 0) or 0) + 1
    row["last_used"] = int(time.time())
    d[s] = row
    _save_usage(d)


def set_pinned(slug: str, pinned: bool) -> bool:
    s = _slug(slug)
    d = _load_usage()
    row = d.get(s) or {}
    row["pinned"] = bool(pinned)
    d[s] = row
    _save_usage(d)
    return row["pinned"]


def _slug(name: str) -> str:
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    if not s or s in (".", ".."):
        raise ValueError("invalid skill name")
    return s


def _dir() -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


def _path(slug: str) -> Path:
    s = _slug(slug)
    root = _dir().resolve()
    p = (root / s / "SKILL.md").resolve()
    if not str(p).startswith(str(root)):
        raise ValueError("path traversal")
    return p


def _parse(text: str) -> dict:
    """split frontmatter (--- … ---) from the body."""
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip("\n").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            body = text[end + 4 :].lstrip("\n")
    return {"meta": meta, "body": body}


def _serialize(name, description, when_to_use, body, source="") -> str:
    fm = [f"name: {name}", f"description: {description}"]
    if when_to_use:
        fm.append(f"when_to_use: {when_to_use}")
    if source:
        fm.append(f"source: {source}")  # 10c — where a git-backed skill came from
    return "---\n" + "\n".join(fm) + "\n---\n\n" + (body or "")


def list_skills() -> list[dict]:
    usage = _load_usage()
    out = []
    for d in sorted(_dir().glob("*/SKILL.md")):
        try:
            parsed = _parse(d.read_text("utf-8", errors="replace"))
            m = parsed["meta"]
            u = usage.get(d.parent.name) or {}
            out.append(
                {
                    "slug": d.parent.name,
                    "name": m.get("name", d.parent.name),
                    "description": m.get("description", ""),
                    "when_to_use": m.get("when_to_use", ""),
                    "source": m.get("source", ""),
                    "size": len(parsed["body"]),
                    "uses": u.get("uses", 0) or 0,
                    "last_used": u.get("last_used", 0) or 0,
                    "pinned": bool(u.get("pinned")),
                    "score": round(usefulness(u), 3),
                }
            )
        except Exception:
            continue
    # most useful first (pinned → used → recent), name as a stable tie-break
    out.sort(key=lambda s: (-s["score"], s["name"].lower()))
    return out


def get_skill(slug: str) -> dict | None:
    p = _path(slug)
    if not p.exists():
        return None
    parsed = _parse(p.read_text("utf-8", errors="replace"))
    m = parsed["meta"]
    u = _load_usage().get(_slug(slug)) or {}
    return {
        "slug": _slug(slug),
        "name": m.get("name", slug),
        "description": m.get("description", ""),
        "when_to_use": m.get("when_to_use", ""),
        "source": m.get("source", ""),
        "body": parsed["body"],
        "uses": u.get("uses", 0) or 0,
        "last_used": u.get("last_used", 0) or 0,
        "pinned": bool(u.get("pinned")),
    }


def upsert_skill(name, description="", when_to_use="", body="", slug=None, source="") -> dict:
    s = _slug(slug or name)
    p = _path(s)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_serialize(name, description, when_to_use, body, source), "utf-8")
    return {"slug": s, "ok": True}


def upsert_from_md(text: str, fallback_name: str = None, source="") -> dict:
    """take a raw SKILL.md (frontmatter + body) and store it. used by upload + github
    import. the frontmatter name wins; fallback_name (e.g. the source folder) covers
    files that skipped it. source records where a git-backed skill came from (10c)."""
    parsed = _parse(text or "")
    m = parsed["meta"]
    name = (m.get("name") or fallback_name or "").strip()
    if not name:
        raise ValueError("skill has no name (add a frontmatter 'name:' line)")
    return upsert_skill(
        name,
        m.get("description", ""),
        m.get("when_to_use", ""),
        parsed["body"],
        source=source or m.get("source", ""),
    )


def export_md(slug: str) -> str | None:
    """the full SKILL.md text, for sharing/downloading a skill (10c)."""
    p = _path(slug)
    return p.read_text("utf-8", errors="replace") if p.exists() else None


def export_all() -> list[dict]:
    return [{"slug": s["slug"], "md": export_md(s["slug"]) or ""} for s in list_skills()]


def update_from_source(slug: str) -> dict:
    """re-pull a git-backed skill from its recorded source. no-op if it has none (10c)."""
    sk = get_skill(slug)
    if not sk:
        return {"updated": False, "error": "not found"}
    src = sk.get("source", "")
    if not src:
        return {"updated": False}
    from . import skills_github

    skills_github.import_from_github(src)
    return {"updated": True, "source": src}


def delete_skill(slug: str) -> bool:
    p = _path(slug)
    if not p.exists():
        return False
    p.unlink()
    try:
        p.parent.rmdir()  # drop the now-empty skill folder
    except OSError:
        pass
    d = _load_usage()
    if d.pop(_slug(slug), None) is not None:
        _save_usage(d)
    return True


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def match_skills(query: str, top_k: int = 3) -> list[dict]:
    """rank skills against a request by token overlap on name/description/when_to_use."""
    q = _tokens(query)
    if not q:
        return []
    scored = []
    for s in list_skills():
        hay = _tokens(f"{s['name']} {s['description']} {s['when_to_use']}")
        overlap = len(q & hay)
        if not hay or not overlap:
            continue
        base = overlap / len(q | hay)
        # nudge skills the user actually reaches for up the list
        boost = 1.0 + (0.1 if s.get("uses") else 0) + (0.25 if s.get("pinned") else 0)
        scored.append((base * boost, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**s, "score": round(sc, 3)} for sc, s in scored[:top_k]]


def search(q: str) -> list[dict]:
    ql = (q or "").lower()
    if not ql:
        return list_skills()
    return [
        s for s in list_skills() if ql in (s["name"] + s["description"] + s["when_to_use"]).lower()
    ]


# ── starter skills (seeded once on first boot so the app isn't empty) ──────────
_SEED_SENTINEL = ".seeded"
_STARTERS = [
    (
        "Summarize",
        "condense long text into the key points",
        "when the user wants a tl;dr, recap, or summary of something long",
        "1. read the whole input first.\n2. pull out the 3-5 load-bearing points.\n"
        "3. write them as tight bullets, no filler.\n4. end with a one-line takeaway.",
    ),
    (
        "Web Research",
        "research a topic and answer with cited sources",
        "when asked to look something up, research, or find current info",
        "1. break the question into 2-3 specific sub-queries.\n2. search the web for each.\n"
        "3. read the best sources (not just snippets).\n4. synthesize a direct answer.\n"
        "5. cite each claim with its source url.",
    ),
    (
        "Code Review",
        "review a change for bugs, then clarity",
        "when reviewing a diff, PR, or a chunk of code",
        "1. understand what the change is trying to do.\n2. look for correctness bugs first "
        "(edge cases, off-by-one, null/empty, error paths).\n3. then clarity/naming/dead code.\n"
        "4. report findings worst-first; suggest a concrete fix for each.",
    ),
]


def seed_starters() -> int:
    """write the starter skills once. a sentinel file means deleting them sticks."""
    d = _dir()
    sentinel = d / _SEED_SENTINEL
    if sentinel.exists():
        return 0
    n = 0
    for name, desc, when, body in _STARTERS:
        try:
            if not _path(name).exists():
                upsert_skill(name, desc, when, body)
                n += 1
        except Exception:
            pass
    try:
        sentinel.write_text("1")
    except Exception:
        pass
    return n


_LIB_SENTINEL = ".lib_seeded"


def seed_library() -> int:
    """on first boot install the WHOLE bundled catalog, so the app ships full instead
    of empty — no manual adding. runs once (own sentinel), skips anything already there,
    falls back to the 3 starters if the library somehow has nothing."""
    d = _dir()
    sentinel = d / _LIB_SENTINEL
    if sentinel.exists():
        return 0
    from services import skills_catalog

    items = skills_catalog.items()
    n = 0
    if items:
        for it in items:
            try:
                if not _path(it["slug"]).exists():
                    upsert_skill(it["name"], it["description"], it["when_to_use"], it["body"])
                    n += 1
            except Exception:
                pass
    else:
        n = seed_starters()
    try:
        sentinel.write_text("1")
    except Exception:
        pass
    return n
