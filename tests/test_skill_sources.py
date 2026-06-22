"""unit-ish checks for skill_sources that need no network."""
import sys
from services import skill_sources as ss

def main():
    r = {}
    srcs = ss.list_sources()
    ids = [s["id"] for s in srcs]
    r["builtin_first"] = bool(srcs) and srcs[0]["id"] == "builtin" and srcs[0]["kind"] == "builtin"
    r["has_github_sources"] = {"anthropic", "superpowers", "composio", "daymade"}.issubset(set(ids))
    r["builtin_has_count"] = srcs[0]["count"] > 0
    # builtin browse needs no network
    b = ss.browse("builtin")
    r["builtin_browse"] = b["kind"] == "builtin" and len(b["skills"]) > 0 and "body" in b["skills"][0]
    # pure url builder
    r["blob_url"] = ss._blob_url("o", "r", "main", "a/b/SKILL.md") == "https://github.com/o/r/blob/main/a/b/SKILL.md"
    # pure breadcrumb builder (offline coverage for _dir's slicing)
    r["dir_breadcrumb"] = ss._dir("a/b/c/SKILL.md") == "a / b" and ss._dir("foo/SKILL.md") == "" and ss._dir("SKILL.md") == ""
    # unknown source
    try:
        ss.browse("nope"); r["unknown_raises"] = False
    except ValueError:
        r["unknown_raises"] = True
    ok = all(r.values())
    for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
