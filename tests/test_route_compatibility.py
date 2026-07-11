import hashlib
import unittest
from collections import Counter
from pathlib import Path

from fastapi.routing import APIRoute

from app import app


def _walk_routes(routes):
    """FastAPI 0.135 keeps included routers lazy; walk both old and new shapes."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk_routes(route.original_router.routes)


def _route_rows():
    rows = []
    for route in _walk_routes(app.routes):
        for method in sorted(route.methods or ()):
            if method not in {"HEAD", "OPTIONS"}:
                rows.append(f"{method} {route.path}")
    return sorted(rows)


class RouteCompatibilityBaselineTest(unittest.TestCase):
    def test_full_method_path_surface_matches_phase_zero_snapshot(self):
        rows = _route_rows()
        digest = hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()
        self.assertEqual(len(rows), 662)
        self.assertEqual(digest, "c8eb72d1c09365f974282a4dd90ad33c6d3df79334d7aa39937d4b086e5bbf11")
        groups = Counter(
            "api"
            if row.split(" ", 1)[1].startswith("/api/")
            else "v1"
            if row.split(" ", 1)[1].startswith("/v1/")
            else "public"
            for row in rows
        )
        self.assertEqual(groups, {"api": 646, "v1": 2, "public": 14})

    def test_public_token_and_status_surface_is_explicit(self):
        public = {
            row for row in _route_rows() if not row.split(" ", 1)[1].startswith(("/api/", "/v1/"))
        }
        self.assertEqual(
            public,
            {
                "GET /",
                "GET /book/{token}",
                "GET /book/{token}/slots",
                "GET /health",
                "GET /manifest.json",
                "GET /rsvp/{token}",
                "GET /s/{token}",
                "GET /s/{token}/{subpath:path}",
                "GET /status",
                "GET /sv/{token}",
                "GET /sv/{token}/data",
                "GET /sw.js",
                "POST /book/{token}",
                "POST /rsvp/{token}",
            },
        )

    def test_current_deep_link_parsers_remain_wired(self):
        root = Path(__file__).parents[1] / "static" / "js"
        expected = {
            "app.js": ("_p.get('app')", "_p.get('view')", "_p.get('ask')", "_p.get('web')"),
            "docs.js": ("location.hash.slice(1)",),
            "files.js": ("get('p')", "sp.get('sort')", "sp.get('order')"),
            "money.js": ("get('m')",),
            "journal.js": ("get('d')",),
            "activity.js": ("p.get('days')", "p.get('hide')", "p.get('q')"),
        }
        for filename, markers in expected.items():
            source = (root / filename).read_text("utf-8")
            for marker in markers:
                self.assertIn(marker, source, f"{filename} lost deep-link marker {marker}")


if __name__ == "__main__":
    unittest.main()
