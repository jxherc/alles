"""the background jobs live in services.background_jobs; app.py's lifespan starts them."""

import sys
from unittest import mock

from services import background_jobs
from tests._client import ApiTest

app_module = sys.modules["app"]  # the harness imports it under a throwaway data dir


class BackgroundJobsTests(ApiTest):
    def test_app_still_reaches_the_jobs(self):
        for name in ("_fire_due_reminders", "_register_jobs", "_cleanup_empty_sessions"):
            self.assertIs(getattr(app_module, name), getattr(background_jobs, name), name)

    def test_ping_answers_from_the_last_probe(self):
        last = {"Local": {"ok": True, "status": 200}}
        with mock.patch.object(background_jobs, "_last_ping", last):
            self.assertEqual(self.client.get("/api/ping", params={"cached": 1}).json(), last)

    def test_ping_probes_when_nothing_is_cached(self):
        # no endpoint rows in the throwaway database, so the probe has nothing to reach
        with mock.patch.object(background_jobs, "_last_ping", {}):
            self.assertEqual(self.client.get("/api/ping", params={"cached": 1}).json(), {})
        self.assertEqual(background_jobs._last_ping, {})
