"""curated, browseable skill sources for the library. the bundled catalog is the implicit
first source ('builtin', local, always available); the rest are public github repos scanned
for SKILL.md (reusing skills_github). browse results cache briefly so an 800-skill repo is
one tree fetch, not 800."""
import json
import time
from pathlib import Path

from . import skills_github, skills_store

_FILE = Path(__file__).parent / "skill_sources.json"
_TTL = 600
_cache = {}   # id -> (ts, browse dict)


def _registry() -> list[dict]:
    try:
        d = json.loads(_FILE.read_text("utf-8"))
        return [s for s in d if isinstance(s, dict) and s.get("id") and s.get("url")]
    except Exception:
        return []


def list_sources() -> list[dict]:
    from . import skills_catalog
    out = [{"id": "builtin", "name": "built-in", "kind": "builtin",
            "description": "the bundled skill library", "count": len(skills_catalog.items())}]
    for s in _registry():
        out.append({"id": s["id"], "name": s["name"], "kind": "github",
                    "description": s.get("description", ""), "count": s.get("count", 0)})
    return out


def _get(sid):
    if sid == "builtin":
        return {"id": "builtin", "kind": "builtin"}
    for s in _registry():
        if s["id"] == sid:
            return {**s, "kind": "github"}
    return None


def _blob_url(owner, repo, branch, path):
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"


def _pretty(path):
    folder = skills_github._folder(path) or path
    return folder.replace("-", " ").replace("_", " ").strip()


def _dir(path):
    # parent breadcrumb: everything above the skill's own folder + SKILL.md
    # "a/b/c/SKILL.md" -> "a / b", "foo/SKILL.md" -> "", "SKILL.md" -> ""
    parts = path.split("/")[:-2]   # drop own folder + SKILL.md
    return " / ".join(parts).replace("-", " ").replace("_", " ")


def _owner_repo_branch(src):
    owner, repo, _b, _p, _k = skills_github._parse_url(src["url"])
    branch = src.get("branch") or skills_github._default_branch(owner, repo)
    return owner, repo, branch


def browse(sid) -> dict:
    src = _get(sid)
    if not src:
        raise ValueError("unknown source")
    if src["kind"] == "builtin":
        from . import skills_catalog
        return {"kind": "builtin", "skills": skills_catalog.items()}
    hit = _cache.get(sid)
    if hit and (time.time() - hit[0]) < _TTL:
        return hit[1]
    owner, repo, branch = _owner_repo_branch(src)
    paths = skills_github._skill_paths(owner, repo, branch)
    skills = [{"name": _pretty(p), "path": p, "dir": _dir(p),
               "import_url": _blob_url(owner, repo, branch, p)}
              for p in sorted(paths)]
    data = {"kind": "github", "repo_url": src["url"], "skills": skills}
    _cache[sid] = (time.time(), data)
    return data


def preview(sid, path) -> dict:
    src = _get(sid)
    if not src or src["kind"] != "github":
        raise ValueError("not a github source")
    owner, repo, branch = _owner_repo_branch(src)
    text = skills_github._fetch(owner, repo, branch, path)
    parsed = skills_store._parse(text)
    m = parsed["meta"]
    return {"name": m.get("name", _pretty(path)), "description": m.get("description", ""),
            "when_to_use": m.get("when_to_use", ""), "body": parsed["body"],
            "source_url": _blob_url(owner, repo, branch, path)}
