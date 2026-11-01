"""every route that wants a recent owner password is reached from the browser only through the
shared prompt (static/js/recent_owner.js).

how it checks: the routes (path and method) come from the live app: a dependency on
require_recent_owner, or a call to it in the handler. for each one, every place in static/js that
spells its path with that method must

  - live in a file that uses the shared prompt (requestWithRecentOwner, fetchWithRecentOwner,
    openWithRecentOwner, or the settings wrapper over it),
  - not hand the path straight to a bare fetch(...) or to the browser's location.

and no file except recent_owner.js may post the password to /api/auth/reauth. a route that asks
for the password only for some requests is listed in CONDITIONAL with the word that marks the
caller that triggers it. any other route that checks inside its handler is treated as asking every
time. the method of a call is read from its `method:` option (a bare call is a GET, and so are
calls through a helper that hides the method: those are covered by the file rule).
"""

import inspect
import re
import unittest
from pathlib import Path

from fastapi.routing import APIRoute

from app import app
from core.auth import require_recent_owner

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static" / "js"
SHARED = "recent_owner.js"
# bankRequest is finance_plaid.js: the same prompt, with that screen's json handling around it
USES_SHARED = re.compile(r"(?:request|fetch|open|_fetch)WithRecentOwner|bankRequest")

# routes that ask only for some requests, and the word in the browser code that makes one
CONDITIONAL = {
    "/api/chat": "permission_mode",
    "/api/jarvis/handoffs": "permission_mode",
    "/api/settings": "agent_allowed_roots",
    "/api/jarvis/workflows/{workflow_id}": "enabled",
    "/api/jarvis/triggers/{trigger_id}": "enabled",
    "/api/projects": "working_dir",
    "/api/projects/{pid}": "working_dir",
}
# functions a route calls that do the owner check for it
HELPERS = ("create_chat_response",)
# helper names that stand for a method when the call has no `method:` option
HELPER_METHODS = {
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "del": "DELETE",
    "remove": "DELETE",
}


def _walk(routes):
    # fastapi keeps included routers lazy; walk both shapes
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes)


def _dependency_calls(dependant):
    for child in dependant.dependencies:
        yield child.call
        yield from _dependency_calls(child)


def protected_routes() -> dict[str, dict]:
    """path -> {"kind": "strict" | "conditional", "methods": {...}}"""
    found: dict[str, dict] = {}
    for route in _walk(app.routes):
        if require_recent_owner in _dependency_calls(route.dependant):
            kind = "strict"
        else:
            try:
                source = inspect.getsource(route.endpoint)
                # a handler that hands the turn to a helper that checks for it
                for helper in HELPERS:
                    if helper + "(" in source:
                        module = inspect.getmodule(route.endpoint)
                        source += inspect.getsource(getattr(module, helper))
            except (OSError, TypeError):
                continue
            if "require_recent_owner(" not in source and "_require_turn_authority(" not in source:
                continue
            kind = "conditional"
        entry = found.setdefault(route.path, {"kind": kind, "methods": set()})
        entry["methods"] |= set(route.methods or ()) - {"HEAD", "OPTIONS"}
        if kind == "strict":
            entry["kind"] = "strict"
    return found


def _literal(path: str) -> re.Pattern:
    """a js string that spells this route: {param} is a template hole or a plain segment"""
    pieces = re.split(r"\{[^}]+\}", path)
    hole = r"(?:\$\{[^}]*\}|[\w.~-]+)"
    pattern = hole.join(re.escape(piece) for piece in pieces)
    return re.compile(pattern + r"(?=['\"`?$)\s,;]|$)")


def _call_around(source: str, start: int, end: int) -> tuple[str, str]:
    """the call the string sits in, as (callee, text up to its closing paren)"""
    depth, i = 0, start
    while i > 0:
        i -= 1
        ch = source[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                break
            depth -= 1
        elif ch == "\n" and source[max(0, i - 200) : i].count("\n") > 6:
            return "", source[start:end]
    callee = re.search(r"([\w$.]+)\s*$", source[:i])
    depth, j = 1, end
    while j < len(source) and depth and j < end + 900:
        depth += (source[j] == "(") - (source[j] == ")")
        j += 1
    return (callee.group(1) if callee else ""), source[i:j]


def _method_of(source: str, hit: re.Match) -> str:
    callee, call = _call_around(source, hit.start(), hit.end())
    option = re.search(r"method:\s*['\"`]([A-Za-z]+)['\"`]", call)
    if option:
        return option.group(1).upper()
    helper = callee.split(".")[-1].lower()
    return HELPER_METHODS.get(helper, "GET")


def js_files():
    return sorted(path for path in JS.rglob("*.js") if "node_modules" not in path.parts)


def find_problems(routes, sources, root=ROOT) -> list[str]:
    problems = []
    for path, entry in sorted(routes.items()):
        marker = CONDITIONAL.get(path)
        pattern = _literal(path)
        for file, source in sources.items():
            if file.name == SHARED or (marker and marker not in source):
                continue
            name = file.relative_to(root).as_posix() if file.is_absolute() else file.as_posix()
            hits = [
                hit
                for hit in pattern.finditer(source)
                if _method_of(source, hit) in entry["methods"]
            ]
            if not hits:
                continue
            if not USES_SHARED.search(source):
                problems.append(f"{name} calls {path} but never uses the shared prompt")
            for hit in hits:
                before = source[max(0, hit.start() - 48) : hit.start()]
                line_start = source.rfind("\n", 0, hit.start()) + 1
                line = source[line_start : source.find("\n", hit.end())]
                raw_fetch = re.search(r"(?<![\w.])(?:fetch|_vfetch)\(\s*[`'\"]$", before)
                raw_open = re.search(
                    r"(?:location(?:\.href)?|\.href|window\.open\()\s*=?\s*\(?\s*[`'\"]$", before
                )
                if (raw_fetch or raw_open) and "WithRecentOwner" not in line:
                    problems.append(
                        f"{name} sends {path} without the shared prompt: {line.strip()[:110]}"
                    )
    return problems


class RecentOwnerRouteScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = protected_routes()
        cls.sources = {path: path.read_text(encoding="utf-8") for path in js_files()}

    def test_the_scan_sees_the_protected_routes(self):
        self.assertGreater(len(self.routes), 100)
        for path in (
            "/api/backup",
            "/api/memories",
            "/api/system/searxng/{action}",
            "/api/jarvis/aide-schedules",
            "/api/storage-locations",
            "/api/journal-migration/plan",
            "/api/agent/permission/{request_id}",
        ):
            self.assertEqual(self.routes.get(path, {}).get("kind"), "strict", path)
        for path in CONDITIONAL:
            self.assertEqual(self.routes.get(path, {}).get("kind"), "conditional", path)

    def test_the_method_reader_knows_a_call_from_its_option(self):
        source = (
            "x = await fetch(`/api/memories`, { method: 'DELETE' });\nawait fetch('/api/memories');"
        )
        hits = list(_literal("/api/memories").finditer(source))
        self.assertEqual([_method_of(source, hit) for hit in hits], ["DELETE", "GET"])
        helper = "await post('/api/backup/s3', { a: 1 });"
        self.assertEqual(_method_of(helper, _literal("/api/backup/s3").search(helper)), "POST")

    def test_callers_of_a_protected_route_use_the_shared_prompt(self):
        self.maxDiff = None
        self.assertEqual(find_problems(self.routes, self.sources), [])

    def test_a_bare_fetch_of_a_protected_route_is_caught(self):
        routes = {
            "/api/memories": {"kind": "strict", "methods": {"DELETE"}},
            "/api/chat": {"kind": "conditional", "methods": {"POST"}},
        }
        bare = Path("static/js/clear.js")
        wrapped = Path("static/js/clear_ok.js")
        other = Path("static/js/chat_other.js")
        sources = {
            bare: "await fetch('/api/memories', { method: 'DELETE' });\n",
            wrapped: "await fetchWithRecentOwner('/api/memories', { method: 'DELETE' });\n",
            other: "await fetch('/api/memories');\nawait fetch('/api/chat', { method: 'POST' });\n",
        }
        problems = find_problems(routes, sources, root=Path("."))
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("clear.js" in item and "/api/memories" in item for item in problems))
        # the same path read with GET is not protected, and a chat file that never mentions
        # permission_mode cannot be asking for full access
        self.assertFalse(any("chat_other.js" in item for item in problems))
        self.assertFalse(any("clear_ok.js" in item for item in problems))

    def test_only_the_shared_prompt_posts_the_password(self):
        users = sorted(
            file.relative_to(ROOT).as_posix()
            for file, source in self.sources.items()
            if "/api/auth/reauth" in source and file.name != SHARED
        )
        self.assertEqual(users, [])


if __name__ == "__main__":
    unittest.main()
