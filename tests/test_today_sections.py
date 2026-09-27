from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import mock

import core.settings as settings
import routes.today as today_route
from core.database import (
    Habit,
    JarvisDeliveryAttempt,
    JarvisRun,
    JarvisRunPrompt,
    JarvisWorkflow,
    Project,
)
from tests._client import ApiTest


class TodayLegacyPreferencesImportTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.settings_dir = TemporaryDirectory(prefix="alles-home-settings-")
        self.settings_path = mock.patch.object(
            settings, "_SETTINGS_FILE", Path(self.settings_dir.name) / "settings.json"
        )
        self.settings_path.start()
        settings._clear_settings_cache()

    def tearDown(self):
        settings._clear_settings_cache()
        self.settings_path.stop()
        self.settings_dir.cleanup()
        super().tearDown()

    def test_first_import_collapses_old_tiles_and_keeps_their_order(self):
        response = self.client.post(
            "/api/today/preferences/import-legacy",
            json={"shortcuts": ["watch", "journal", "photos", "plan", "files", "chat", "wiki"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["imported"])
        self.assertEqual(
            response.json()["preferences"]["shortcuts"], ["system", "wiki", "files", "plan"]
        )
        self.assertEqual(
            self.client.get("/api/today/preferences").json(), response.json()["preferences"]
        )

        repeated = self.client.post(
            "/api/today/preferences/import-legacy", json={"shortcuts": ["finance"]}
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()["imported"])
        self.assertEqual(repeated.json()["preferences"], response.json()["preferences"])

    def test_import_never_replaces_a_saved_current_home_layout(self):
        current = self.client.put(
            "/api/today/preferences", json={"shortcuts": ["vault"], "density": "compact"}
        )
        self.assertEqual(current.status_code, 200)
        imported = self.client.post(
            "/api/today/preferences/import-legacy", json={"shortcuts": ["plan", "wiki"]}
        )
        self.assertEqual(imported.status_code, 200)
        self.assertFalse(imported.json()["imported"])
        self.assertEqual(imported.json()["preferences"], current.json())
        self.assertEqual(self.client.get("/api/today/preferences").json(), current.json())

    def test_invalid_import_does_not_create_a_layout(self):
        invalid = self.client.post(
            "/api/today/preferences/import-legacy", json={"shortcuts": ["plan"] * 21}
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertIsNone(settings.load_settings().get("today_layout"))

    def test_all_hidden_old_tiles_keep_pinned_apps_empty(self):
        imported = self.client.post("/api/today/preferences/import-legacy", json={"shortcuts": []})
        self.assertEqual(imported.status_code, 200)
        self.assertTrue(imported.json()["imported"])
        self.assertEqual(imported.json()["preferences"]["shortcuts"], [])
        self.assertEqual(self.client.get("/api/today/preferences").json()["shortcuts"], [])

    def test_new_save_cannot_interleave_with_first_import(self):
        entered, release, save_started = Event(), Event(), Event()
        original_load = today_route.load_settings

        def paused_load():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("import did not resume")
            return original_load()

        def save_new_layout():
            save_started.set()
            return today_route.update_today_preferences(
                today_route.TodayPreferences(shortcuts=["vault"])
            )

        with mock.patch.object(today_route, "load_settings", side_effect=paused_load):
            with ThreadPoolExecutor(max_workers=2) as executor:
                imported = executor.submit(
                    today_route.import_legacy_home_preferences,
                    today_route.TodayPreferences(shortcuts=["plan"]),
                )
                try:
                    self.assertTrue(entered.wait(2))
                    saved = executor.submit(save_new_layout)
                    self.assertTrue(save_started.wait(2))
                    with self.assertRaises(FutureTimeoutError):
                        saved.result(timeout=0.1)
                finally:
                    release.set()
                self.assertTrue(imported.result(timeout=2)["imported"])
                self.assertEqual(saved.result(timeout=2)["shortcuts"], ["vault"])
        self.assertEqual(self.client.get("/api/today/preferences").json()["shortcuts"], ["vault"])


class TodaySectionsTest(ApiTest):
    @staticmethod
    def now():
        return datetime.now(UTC).replace(tzinfo=None)

    def get_today(self):
        with mock.patch.dict(
            "os.environ",
            {"ALLES_AFTERLIFE_FEATURES": "afterlife_today"},
            clear=False,
        ):
            return self.client.get("/api/today").json()

    def test_sections_are_absent_while_today_flag_is_off(self):
        with mock.patch.dict(
            "os.environ", {"ALLES_AFTERLIFE_FEATURES": "afterlife_shell"}, clear=False
        ):
            self.assertNotIn("sections", self.client.get("/api/today").json())

    def test_empty_sections_keep_the_five_part_shape(self):
        sections = self.get_today()["sections"]
        self.assertEqual(
            list(sections),
            ["needs_you", "today", "in_progress", "briefs", "shortcuts"],
        )
        self.assertEqual(sections["needs_you"], [])
        self.assertEqual(sections["in_progress"], [])
        self.assertEqual(sections["briefs"], [])
        self.assertEqual(sections["shortcuts"], [])
        self.assertIn("events", sections["today"])
        self.assertIn("partial_sources", sections["today"])

    def test_preferences_persist_and_needs_you_cannot_be_hidden(self):
        saved = self.client.put(
            "/api/today/preferences",
            json={
                "order": ["briefs", "today"],
                "visible": ["today"],
                "density": "compact",
                "shortcuts": ["tasks", "wiki", "tasks", "mail", "photos", "watch"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        value = saved.json()
        self.assertEqual(value["order"][:2], ["briefs", "today"])
        self.assertIn("needs_you", value["visible"])
        self.assertEqual(value["density"], "compact")
        self.assertEqual(value["shortcuts"], ["plan", "wiki", "inbox", "files", "system"])
        self.assertEqual(self.client.get("/api/today/preferences").json(), value)

    def test_preferences_preserve_an_intentionally_empty_shortcut_list(self):
        saved = self.client.put(
            "/api/today/preferences",
            json={
                "order": ["needs_you", "today", "in_progress", "briefs", "shortcuts"],
                "visible": ["needs_you", "shortcuts"],
                "density": "comfortable",
                "shortcuts": [],
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["shortcuts"], [])
        self.assertEqual(self.client.get("/api/today/preferences").json()["shortcuts"], [])

    def test_today_includes_unfinished_habits_without_a_model(self):
        db = self.db()
        db.add(Habit(name="stretch", cadence="daily", target=1, archived=False))
        db.commit()
        db.close()
        self.assertEqual(self.client.get("/api/today").json()["habits"][0]["name"], "stretch")

    def test_local_records_fill_attention_progress_and_briefs_without_a_model(self):
        db = self.db()
        project = Project(name="site", working_dir="")
        workflow = JarvisWorkflow(name="morning report", project_id=None, enabled=True)
        db.add_all([project, workflow])
        db.flush()

        waiting = JarvisRun(
            workflow_id=workflow.id,
            project_id=project.id,
            state="waiting_approval",
        )
        uncertain = JarvisRun(
            workflow_id=workflow.id,
            state="uncertain",
            safe_error="outside result could not be confirmed",
        )
        running = JarvisRun(workflow_id=workflow.id, state="running")
        finished = JarvisRun(
            workflow_id=workflow.id,
            state="succeeded",
            result_summary="three changes need review",
            finished_at=self.now(),
        )
        db.add_all([waiting, uncertain, running, finished])
        db.flush()
        db.add(
            JarvisRunPrompt(
                run_id=waiting.id,
                kind="approval",
                question="publish the report?",
                state="pending",
                expires_at=self.now() + timedelta(hours=1),
            )
        )
        waiting_id = waiting.id
        db.add(
            JarvisDeliveryAttempt(
                run_id=finished.id,
                channel="discord",
                state="failed",
                safe_error_class="unavailable",
                idempotency_key="a" * 64,
            )
        )
        db.commit()
        db.close()

        sections = self.get_today()["sections"]
        attention = sections["needs_you"]
        self.assertIn("publish the report?", [item["title"] for item in attention])
        self.assertIn("uncertain", [item["state"] for item in attention])
        self.assertIn("discord delivery", [item["title"] for item in attention])
        self.assertNotIn(waiting_id, [item["id"] for item in attention if item["kind"] == "run"])

        self.assertEqual([item["state"] for item in sections["in_progress"]], ["running"])
        self.assertEqual(sections["in_progress"][0]["title"], "morning report")
        self.assertEqual(sections["in_progress"][0]["project"], "tasks")
        self.assertEqual(sections["briefs"][0]["summary"], "three changes need review")

    def test_orphaned_background_records_use_aide_language(self):
        db = self.db()
        db.add(JarvisRun(workflow_id="missing", state="running"))
        db.commit()
        db.close()

        card = self.get_today()["sections"]["in_progress"][0]
        self.assertEqual(card["title"], "aide work")
        self.assertEqual(card["project"], "tasks")

    def test_expired_prompt_is_not_actionable(self):
        db = self.db()
        workflow = JarvisWorkflow(name="old", enabled=True)
        db.add(workflow)
        db.flush()
        run = JarvisRun(workflow_id=workflow.id, state="waiting_input")
        db.add(run)
        db.flush()
        db.add(
            JarvisRunPrompt(
                run_id=run.id,
                kind="choice",
                question="old question",
                state="pending",
                expires_at=self.now() - timedelta(seconds=1),
            )
        )
        db.commit()
        db.close()

        needs = self.get_today()["sections"]["needs_you"]
        self.assertNotIn("old question", [item["title"] for item in needs])
        self.assertIn("waiting_input", [item["state"] for item in needs])
