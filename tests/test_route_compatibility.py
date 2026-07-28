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
    def test_full_method_path_surface_matches_current_snapshot(self):
        rows = _route_rows()
        digest = hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()
        self.assertEqual(len(rows), 888)
        self.assertEqual(digest, "a6c51b746852141e2f0144c1585b0322ece56828dc622fcc5d6f7b5de2a2b1f9")
        groups = Counter(
            "api"
            if row.split(" ", 1)[1].startswith("/api/")
            else "v1"
            if row.split(" ", 1)[1].startswith("/v1/")
            else "public"
            for row in rows
        )
        self.assertEqual(groups, {"api": 871, "v1": 2, "public": 15})

    def test_phase_six_recovery_and_migration_routes_remain_wired(self):
        rows = set(_route_rows())
        expected = {
            "DELETE /api/vault-md/safety/draft",
            "GET /api/journal-migration/plan",
            "GET /api/journal-migration/{operation_id}",
            "GET /api/vault-transfer/pending",
            "GET /api/vault-transfer/{operation_id}",
            "GET /api/vault-md/rename/pending",
            "GET /api/vault-md/safety/conflicts/{conflict_id}",
            "GET /api/vault-md/safety/draft",
            "GET /api/vault-md/safety/revisions",
            "POST /api/journal-migration/prepare",
            "POST /api/journal-migration/{operation_id}/apply",
            "POST /api/journal-migration/{operation_id}/rollback",
            "POST /api/vault-transfer/move",
            "POST /api/vault-transfer/relink",
            "POST /api/vault-transfer/{operation_id}/delete-old",
            "POST /api/vault-transfer/{operation_id}/resume",
            "POST /api/vault-transfer/{operation_id}/rollback",
            "POST /api/vault-md/rename/recover",
            "POST /api/vault-md/safety/compare",
            "POST /api/vault-md/safety/revisions/restore",
            "POST /api/vault-md/safety/save",
            "PUT /api/vault-md/safety/draft",
        }
        self.assertTrue(expected <= rows, sorted(expected - rows))

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
                "POST /s/{token}/unlock",
            },
        )

    def test_current_deep_link_parsers_remain_wired(self):
        root = Path(__file__).parents[1] / "static" / "js"
        expected = {
            "app.js": (
                "_p.get('app')",
                "_p.get('view')",
                "bootParams.get('ask')",
                "bootParams.get('web')",
            ),
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
