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


def _current_rows():
    rows = []
    for route in _walk_routes(app.routes):
        for method in sorted(route.methods or ()):
            if method not in {"HEAD", "OPTIONS"}:
                rows.append(f"{method} {route.path}")
    return sorted(rows)


# pi replaced the DSH bridge: these went away together and these came in
_DSH_REMOVED = {
    "DELETE /api/aide/coding/connection",
    "GET /api/aide/coding/runs",
    "GET /api/aide/coding/runs/{run_id}",
    "GET /api/aide/coding/runs/{run_id}/events",
    "GET /api/aide/coding/runs/{run_id}/live",
    "GET /api/aide/coding/status",
    "GET /api/aide/coding/workspaces",
    "POST /api/aide/coding/health",
    "POST /api/aide/coding/pair",
    "POST /api/aide/coding/runs",
    "POST /api/aide/coding/runs/{run_id}/cancel",
    "POST /api/aide/coding/runs/{run_id}/continue",
    "POST /api/aide/coding/runs/{run_id}/refresh",
    "POST /api/aide/coding/runs/{run_id}/respond",
    "POST /api/aide/coding/runs/{run_id}/resume",
}
_PI_CODE_ADDITIONS = {
    "DELETE /api/aide/code/projects/{project_id}",
    "DELETE /api/aide/code/projects/{project_id}/chats/{chat_id}",
    "GET /api/aide/code/folders",
    "GET /api/aide/code/projects",
    "GET /api/aide/code/projects/{project_id}/chats",
    "GET /api/aide/code/projects/{project_id}/chats/{chat_id}",
    "GET /api/aide/code/projects/{project_id}/chats/{chat_id}/live",
    "GET /api/aide/code/status",
    "POST /api/aide/code/install",
    "POST /api/aide/code/projects",
    "POST /api/aide/code/projects/{project_id}/chats",
    "POST /api/aide/code/projects/{project_id}/chats/{chat_id}/answer",
    "POST /api/aide/code/projects/{project_id}/chats/{chat_id}/messages",
    "POST /api/aide/code/projects/{project_id}/chats/{chat_id}/model",
    "POST /api/aide/code/projects/{project_id}/chats/{chat_id}/stop",
}


# standing goals, added after pi
_GOAL_ADDITIONS = {
    "DELETE /api/jarvis/aide-goals/{workflow_id}",
    "GET /api/jarvis/aide-goals",
    "PATCH /api/jarvis/aide-goals/{workflow_id}",
    "PATCH /api/jarvis/aide-goals/{workflow_id}/state",
    "POST /api/jarvis/aide-goals",
}


# harness choice, ACP connections and pi's web-tool bridge, added after goals
_HARNESS_ADDITIONS = {
    "GET /api/aide/code/harnesses",
    "POST /api/aide/code/harnesses/{harness_id}/install",
    "PUT /api/aide/code/settings",
    "POST /pi-bridge/fetch",
    "POST /pi-bridge/search",
}


# the imessage line, goal wake-ups and mcp sign-in plus registry search, added after harnesses
_WAKE_AND_CONNECTOR_ADDITIONS = {
    "GET /api/aide/channels/photon",
    "PUT /api/aide/channels/photon",
    "POST /api/jarvis/aide-goals/{workflow_id}/hook",
    "POST /hooks/goal/{workflow_id}",
    "GET /api/mcp/oauth/callback",
    "GET /api/mcp/registry",
    "POST /api/mcp/servers/{sid}/sign-in",
    "POST /api/mcp/servers/{sid}/sign-out",
    "GET /oauth/mcp-client.json",
}


# the owner signing in to sites in Aide's errand browser, added after the connectors
_BROWSER_SIGNIN_ADDITIONS = {
    "DELETE /api/aide/browser/sites",
    "DELETE /api/aide/browser/sites/{site}",
    "GET /api/aide/browser/signin",
    "GET /api/aide/browser/signin/frame",
    "GET /api/aide/browser/sites",
    "POST /api/aide/browser/signin",
    "POST /api/aide/browser/signin/back",
    "POST /api/aide/browser/signin/click",
    "POST /api/aide/browser/signin/done",
    "POST /api/aide/browser/signin/scroll",
    "POST /api/aide/browser/signin/type",
}


def _route_rows():
    """the surface before pi, which the older additive checks below are pinned to."""
    later = (
        _PI_CODE_ADDITIONS
        | _GOAL_ADDITIONS
        | _HARNESS_ADDITIONS
        | _WAKE_AND_CONNECTOR_ADDITIONS
        | _BROWSER_SIGNIN_ADDITIONS
    )
    return sorted((set(_current_rows()) - later) | _DSH_REMOVED)


_ASSISTANT_AND_BANK_ADDITIONS = {
    "DELETE /api/aide/coding/connection",
    "GET /api/aide/calls/{call_id}",
    "GET /api/aide/capabilities",
    "GET /api/aide/coding/runs",
    "GET /api/aide/coding/runs/{run_id}",
    "GET /api/aide/coding/runs/{run_id}/events",
    "GET /api/aide/coding/runs/{run_id}/live",
    "GET /api/aide/coding/status",
    "GET /api/aide/coding/workspaces",
    "GET /api/aide/conversation",
    "GET /api/aide/voice/calls/{call_id}/turns/{turn_id}",
    "GET /api/aide/voice/status",
    "POST /api/aide/calls",
    "POST /api/aide/calls/{call_id}/hangup",
    "POST /api/aide/calls/{call_id}/offer",
    "POST /api/aide/calls/{call_id}/transcripts",
    "POST /api/aide/coding/health",
    "POST /api/aide/coding/pair",
    "POST /api/aide/coding/runs",
    "POST /api/aide/coding/runs/{run_id}/cancel",
    "POST /api/aide/coding/runs/{run_id}/continue",
    "POST /api/aide/coding/runs/{run_id}/refresh",
    "POST /api/aide/coding/runs/{run_id}/respond",
    "POST /api/aide/coding/runs/{run_id}/resume",
    "POST /api/aide/voice/calls",
    "POST /api/aide/voice/calls/{call_id}/hangup",
    "POST /api/aide/voice/calls/{call_id}/turns",
    "POST /api/aide/voice/calls/{call_id}/turns/{turn_id}/cancel",
    "POST /api/aide/voice/calls/{call_id}/turns/{turn_id}/speech",
    "POST /api/finance/connections/{connection_id}/plaid/update-complete",
}


_FINANCE_ADDITIONS = {
    "GET /api/money/currencies",
    "GET /api/money/transactions/{tid}/undo",
    "POST /api/money/transactions/{tid}/undo",
}


_ANDROMEDA_WATCH_ADDITIONS = {
    "POST /api/andromeda/saved/{search_id}/watch/seen",
    "PUT /api/andromeda/saved/{search_id}/watch",
}


_ANDROMEDA_ANSWER_ADDITIONS = {"POST /api/andromeda/answer"}


_SEARCH_ENGINE_ADDITIONS = {
    "DELETE /api/search/custom/{engine_id}",
    "GET /api/search/engines",
    "POST /api/search/custom",
    "POST /api/search/test",
    "PUT /api/search/custom/{engine_id}",
}


def _before_finance_additions():
    return [
        row
        for row in _route_rows()
        if row
        not in _FINANCE_ADDITIONS
        | _ASSISTANT_AND_BANK_ADDITIONS
        | _SEARCH_ENGINE_ADDITIONS
        | _ANDROMEDA_WATCH_ADDITIONS
        | _ANDROMEDA_ANSWER_ADDITIONS
    ]


class RouteCompatibilityBaselineTest(unittest.TestCase):
    def test_search_engine_routes_are_additive_to_previous_surface(self):
        self.assertTrue(_SEARCH_ENGINE_ADDITIONS <= set(_route_rows()))
        rows = [
            row
            for row in _route_rows()
            if row
            not in _SEARCH_ENGINE_ADDITIONS
            | _ANDROMEDA_WATCH_ADDITIONS
            | _ANDROMEDA_ANSWER_ADDITIONS
        ]
        self.assertEqual(len(rows), 947)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "522fe1fb902186f148959593e48b74a15c559784d3f52cfa890ac36d6aa0d8ff",
        )

    def test_andromeda_watch_routes_are_additive_to_previous_surface(self):
        self.assertTrue(_ANDROMEDA_WATCH_ADDITIONS <= set(_route_rows()))
        rows = [
            row
            for row in _route_rows()
            if row not in _ANDROMEDA_WATCH_ADDITIONS | _ANDROMEDA_ANSWER_ADDITIONS
        ]
        self.assertEqual(len(rows), 952)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "2058f25b3e0a8476dc34ea2a1baf3a4c1b3555943706cf0221cda6ba84899957",
        )

    def test_andromeda_answer_route_is_additive_to_previous_surface(self):
        self.assertTrue(_ANDROMEDA_ANSWER_ADDITIONS <= set(_route_rows()))
        rows = [row for row in _route_rows() if row not in _ANDROMEDA_ANSWER_ADDITIONS]
        self.assertEqual(len(rows), 954)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "8c6e25b0c6ec2b599a992ed65c9fd3cfa87fb031e7ebf6ca51cc6e829c972c7c",
        )

    def test_goal_routes_are_additive(self):
        current = set(_current_rows())
        self.assertTrue(_GOAL_ADDITIONS <= current)
        self.assertEqual(
            len(
                current
                - _HARNESS_ADDITIONS
                - _WAKE_AND_CONNECTOR_ADDITIONS
                - _BROWSER_SIGNIN_ADDITIONS
            ),
            960,
        )

    def test_harness_routes_are_additive(self):
        self.assertTrue(_HARNESS_ADDITIONS <= set(_current_rows()))

    def test_wake_and_connector_routes_are_additive(self):
        current = set(_current_rows())
        self.assertTrue(_WAKE_AND_CONNECTOR_ADDITIONS <= current)
        # the only two new routes outside /api: a goal's own webhook and the oauth client document
        public = {
            r for r in _WAKE_AND_CONNECTOR_ADDITIONS if not r.split(" ", 1)[1].startswith("/api/")
        }
        self.assertEqual(public, {"POST /hooks/goal/{workflow_id}", "GET /oauth/mcp-client.json"})

    def test_browser_signin_routes_are_additive_and_private(self):
        self.assertTrue(_BROWSER_SIGNIN_ADDITIONS <= set(_current_rows()))
        self.assertTrue(all(" /api/aide/browser/" in r for r in _BROWSER_SIGNIN_ADDITIONS))

    def test_pi_code_routes_replace_the_dsh_bridge(self):
        current = set(_current_rows())
        self.assertTrue(_PI_CODE_ADDITIONS <= current)
        self.assertFalse(_DSH_REMOVED & current)
        self.assertEqual(len(_route_rows()), 955)

    def test_full_method_path_surface_matches_current_snapshot(self):
        rows = _current_rows()
        digest = hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()
        self.assertEqual(len(rows), 985)
        self.assertEqual(digest, "e13a6577b932a3b65df012b84fd016507556647222097d988ef29b57eb45e3a2")
        groups = Counter(
            "api"
            if row.split(" ", 1)[1].startswith("/api/")
            else "v1"
            if row.split(" ", 1)[1].startswith("/v1/")
            else "public"
            for row in rows
        )
        self.assertEqual(groups, {"api": 964, "v1": 2, "public": 19})
        self.assertIn("POST /api/money/recurring/{rid}/delete", rows)
        self.assertIn("POST /api/money/recurring/{rid}/delete/retry", rows)

    def test_assistant_and_bank_routes_are_additive_to_previous_surface(self):
        self.assertTrue(_ASSISTANT_AND_BANK_ADDITIONS <= set(_route_rows()))
        rows = [
            row
            for row in _route_rows()
            if row
            not in _ASSISTANT_AND_BANK_ADDITIONS
            | _SEARCH_ENGINE_ADDITIONS
            | _ANDROMEDA_WATCH_ADDITIONS
            | _ANDROMEDA_ANSWER_ADDITIONS
        ]
        self.assertEqual(len(rows), 917)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "4f2aec58ae7471a12bf539c5edc571b05a29758b7d2d319000fe094888b25e8b",
        )

    def test_finance_currency_and_undo_are_additive_to_previous_surface(self):
        self.assertTrue(_FINANCE_ADDITIONS <= set(_route_rows()))
        rows = _before_finance_additions()
        self.assertEqual(len(rows), 914)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "d2f1e721abc8247f7833cf9af239ae747b0b4d4c015fee4100172582facec6cd",
        )

    def test_result_save_is_additive_to_previous_surface(self):
        rows = [row for row in _before_finance_additions() if row != "POST /api/read/save-result"]
        self.assertEqual(len(rows), 913)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "9269e264ffab213661c86cf55a687f53313ef3755e20973c02d248da1e37218f",
        )

    def test_saved_search_recovery_is_additive_to_previous_surface(self):
        rows = [
            row
            for row in _before_finance_additions()
            if row
            not in {"GET /api/andromeda/saved/requests/{request_id}", "POST /api/read/save-result"}
        ]
        self.assertEqual(len(rows), 912)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "9eba492fafb69fd51b6dc3a203e25ef0026a61724f00b5d0a35583d7437eaed4",
        )

    def test_saved_text_fetch_is_additive_to_the_previous_http_surface(self):
        rows = [
            row
            for row in _before_finance_additions()
            if row
            not in {
                "POST /api/read/save-result",
                "POST /api/read/{rid}/fetch-text",
                "GET /api/andromeda/saved/requests/{request_id}",
            }
        ]
        self.assertEqual(len(rows), 911)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "bd97565b102f02a2d10353fb71458f981eecc6b9418cede5a80a655febd31716",
        )

    def test_book_recovery_is_additive_to_the_previous_http_surface(self):
        rows = [
            row
            for row in _before_finance_additions()
            if row
            not in {
                "POST /api/read/save-result",
                "GET /api/books/requests/{request_id}",
                "POST /api/read/{rid}/fetch-text",
                "GET /api/andromeda/saved/requests/{request_id}",
            }
        ]
        self.assertEqual(len(rows), 910)
        self.assertEqual(
            hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
            "374cd48bb43a4603172d9dc48acc0251f97d8c1cc6b03d7edb61c08e918bb682",
        )

    def test_phase_six_recovery_and_migration_routes_remain_wired(self):
        rows = set(_route_rows())
        expected = {
            "DELETE /api/vault-md/safety/draft",
            "GET /api/journal-migration/operations",
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
            "filesphase7.js": ("params.get('p')", "params.get('sort')", "params.get('order')"),
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
