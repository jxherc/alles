"""
first-class skills — reusable procedures the agent can discover + load and the
user can manage. each skill is data/skills/<slug>/SKILL.md with yaml-ish
frontmatter (name / description / when_to_use) + a markdown body, matching the
SKILL.md convention agent_tools already reads. match() scores skills against a
request so the right one surfaces automatically.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "data" / "skills"

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


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
            body = text[end + 4:].lstrip("\n")
    return {"meta": meta, "body": body}


def _serialize(name, description, when_to_use, body) -> str:
    fm = [f"name: {name}", f"description: {description}"]
    if when_to_use:
        fm.append(f"when_to_use: {when_to_use}")
    return "---\n" + "\n".join(fm) + "\n---\n\n" + (body or "")


def list_skills() -> list[dict]:
    out = []
    for d in sorted(_dir().glob("*/SKILL.md")):
        try:
            parsed = _parse(d.read_text("utf-8", errors="replace"))
            m = parsed["meta"]
            out.append({
                "slug": d.parent.name,
                "name": m.get("name", d.parent.name),
                "description": m.get("description", ""),
                "when_to_use": m.get("when_to_use", ""),
                "size": len(parsed["body"]),
            })
        except Exception:
            continue
    return out


def get_skill(slug: str) -> dict | None:
    p = _path(slug)
    if not p.exists():
        return None
    parsed = _parse(p.read_text("utf-8", errors="replace"))
    m = parsed["meta"]
    return {
        "slug": _slug(slug), "name": m.get("name", slug),
        "description": m.get("description", ""), "when_to_use": m.get("when_to_use", ""),
        "body": parsed["body"],
    }


def upsert_skill(name, description="", when_to_use="", body="", slug=None) -> dict:
    s = _slug(slug or name)
    p = _path(s)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_serialize(name, description, when_to_use, body), "utf-8")
    return {"slug": s, "ok": True}


def delete_skill(slug: str) -> bool:
    p = _path(slug)
    if not p.exists():
        return False
    p.unlink()
    try:
        p.parent.rmdir()       # drop the now-empty skill folder
    except OSError:
        pass
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
        scored.append((overlap / len(q | hay), s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**s, "score": round(sc, 3)} for sc, s in scored[:top_k]]


def search(q: str) -> list[dict]:
    ql = (q or "").lower()
    if not ql:
        return list_skills()
    return [s for s in list_skills()
            if ql in (s["name"] + s["description"] + s["when_to_use"]).lower()]
