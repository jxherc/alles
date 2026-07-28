from datetime import UTC, datetime, timedelta
from unittest import mock

from core.database import (
    Habit,
    JarvisDeliveryAttempt,
    JarvisRun,
    JarvisRunPrompt,
    JarvisWorkflow,
    Project,
)
from tests._client import ApiTest


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
