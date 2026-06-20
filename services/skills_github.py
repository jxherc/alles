"""
import skills from github. accepts a whole repo url, a folder (tree) url, or a
direct SKILL.md (blob/raw) url. scans the tree for SKILL.md files and stores each.
public repos only — no token needed, which is plenty for single-user. respects the
outbound_proxy via httpx's trust_env (services/net exports HTTP(S)_PROXY).
"""

import re
import httpx

from . import skills_store

_RAW = "https://raw.githubusercontent.com/"
_API = "https://api.github.com/"
_H = {"accept": "application/vnd.github+json", "user-agent": "alles-skills"}


def _parse_url(url):
    """-> (owner, repo, branch|None, path|None, kind) where kind is file|tree|repo."""
    u = (url or "").strip().rstrip("/")
    m = re.match(r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)", u)
    if m:
        return (*m.groups(), "file")
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", u)
    if m:
        return (*m.groups(), "file")
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/?(.*)", u)
    if m:
        return m.group(1), m.group(2), m.group(3), (m.group(4) or ""), "tree"
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", u)
    if m:
        return m.group(1), m.group(2), None, None, "repo"
    raise ValueError("not a github repo / folder / SKILL.md url")


def _default_branch(owner, repo):
    r = httpx.get(f"{_API}repos/{owner}/{repo}", headers=_H, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.json().get("default_branch", "main")


def _skill_paths(owner, repo, branch, under=""):
    r = httpx.get(
        f"{_API}repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=_H,
        timeout=20,
        follow_redirects=True,
    )
    r.raise_for_status()
    pre = (under + "/") if under else ""
    return [
        x["path"]
        for x in r.json().get("tree", [])
        if x.get("type") == "blob"
        and (x["path"] == "SKILL.md" or x["path"].endswith("/SKILL.md"))
        and x["path"].startswith(pre)
    ]


def _fetch(owner, repo, branch, path):
    r = httpx.get(f"{_RAW}{owner}/{repo}/{branch}/{path}", timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _folder(path):
    # the dir holding SKILL.md → a good fallback name when frontmatter omits one
    return path.rsplit("/", 2)[-2] if "/" in path else None


def import_from_github(url):
    owner, repo, branch, path, kind = _parse_url(url)

    if kind == "file":
        text = _fetch(owner, repo, branch, path)
        # record the source so the skill can be updated later (10c)
        src = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
        s = skills_store.upsert_from_md(text, _folder(path) or repo, source=src)
        return {"imported": [s["slug"]], "failed": 0}

    branch = branch or _default_branch(owner, repo)
    paths = _skill_paths(owner, repo, branch, path or "")
    if not paths:
        raise ValueError("no SKILL.md files found there")

    imported, failed = [], 0
    for p in paths:
        try:
            text = _fetch(owner, repo, branch, p)
            src = f"https://github.com/{owner}/{repo}/blob/{branch}/{p}"
            imported.append(
                skills_store.upsert_from_md(text, _folder(p) or repo, source=src)["slug"]
            )
        except Exception:
            failed += 1
    if not imported:
        raise ValueError("found SKILL.md files but none could be imported")
    return {"imported": imported, "failed": failed}
