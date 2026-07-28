"""/health?deep=1 leaks internal readiness details (the data-dir path, installed deps, provider
state). it's a public route (not under /api/), so when auth is ON those details must NOT go to an
anonymous caller."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import app as appmod
from tests._client import ApiTest


class HealthAuthTest(ApiTest):
    def test_basic_health_is_public(self):
        self.assertEqual(self.client.get("/health").json(), {"ok": True})

    def test_deep_health_shown_in_local_mode(self):
        # ApiTest runs with AUTH_ENABLED=false → local single-user, the readiness detail is fine
        r = self.client.get("/health?deep=1")
        self.assertIn("checks", r.json())

    def test_deep_health_hidden_from_anon_when_auth_on(self):
        with mock.patch.object(appmod, "auth_enabled", lambda: True):
            body = self.client.get("/health?deep=1").json()
        self.assertEqual(body, {"ok": True})  # liveness only
        self.assertNotIn("checks", body)  # no data-dir path / dep list leaked

    def test_health_exposes_test_run_only_for_matching_owned_temporary_root(self):
        run_id = "owned-browser-test-run"
        with tempfile.TemporaryDirectory(prefix="alles-browser-health-") as raw:
            root = Path(raw)
            (root / ".alles-test-owner").write_text(run_id, encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ALLES_TEST_DATA": "1",
                        "ALLES_TEST_RUN_ID": run_id,
                    },
                    clear=False,
                ),
                mock.patch("core.settings.data_dir", return_value=root),
            ):
                response = self.client.get("/health")
        self.assertEqual(response.headers.get("X-Alles-Test-Run-ID"), run_id)

    def test_health_omits_test_run_without_server_ownership_proof(self):
        with mock.patch.object(appmod, "_owned_browser_test_run_id", return_value=""):
            response = self.client.get("/health")
        self.assertNotIn("X-Alles-Test-Run-ID", response.headers)
