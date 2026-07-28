import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from core.database import (
    JarvisConnector,
    JarvisRun,
    JarvisRunEvent,
    JarvisRunPrompt,
    JarvisWorkflow,
    Project,
)
from core.migrations import m0026_jarvis_records
from services import agent_runtime
from services.aide_questions import normalize_request
from services.jarvis_store import (
    append_event,
    create_prompt,
    create_run,
    reconcile_interrupted_runs,
    transition_run,
)
from tests._client import ApiTest


class JarvisRecordApiTest(ApiTest):
    def _workflow(self, **values):
        body = {"name": "morning check", **values}
        response = self.client.post("/api/jarvis/workflows", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_workflow_starts_paused_and_keeps_structured_policy(self):
        workflow = self._workflow(
            purpose="check the inbox",
            capability_ceiling=["mail.read"],
            delivery_policy={"privacy": "title_status"},
        )
        self.assertFalse(workflow["enabled"])
        self.assertEqual(workflow["capability_ceiling"], ["mail.read"])
        self.assertEqual(workflow["delivery_policy"], {"privacy": "title_status"})
        self.assertEqual(self.client.get("/api/jarvis/workflows").json(), [workflow])

    def test_project_context_requires_a_real_project(self):
        missing = self.client.post(
            "/api/jarvis/workflows",
            json={"name": "bad", "context_mode": "project", "project_id": "missing"},
        )
        self.assertEqual(missing.status_code, 404)
        no_project = self.client.post(
            "/api/jarvis/workflows",
            json={"name": "bad", "context_mode": "project"},
        )
        self.assertEqual(no_project.status_code, 400)
        self.assertEqual(no_project.json()["code"], "project_context_required")

        db = self.db()
        project = Project(name="real")
        db.add(project)
        db.commit()
        project_id = project.id
        db.close()
        workflow = self._workflow(context_mode="project", project_id=project_id)
        self.assertEqual(workflow["project_id"], project_id)

        cleared = self.client.patch(
            f"/api/jarvis/workflows/{workflow['id']}",
            json={"project_id": ""},
        )
        self.assertEqual(cleared.status_code, 400, cleared.text)
        self.assertEqual(cleared.json()["code"], "project_context_required")
        unchanged = self.client.get("/api/jarvis/workflows").json()[0]
        self.assertEqual(unchanged["project_id"], project_id)
        self.assertEqual(unchanged["context_mode"], "project")

    def test_trigger_is_separate_and_starts_disabled(self):
        workflow = self._workflow()
        trigger = self.client.post(
            f"/api/jarvis/workflows/{workflow['id']}/triggers",
            json={"kind": "heartbeat", "config": {"every_seconds": 300}},
        ).json()
        self.assertEqual(trigger["workflow_id"], workflow["id"])
        self.assertEqual(trigger["kind"], "heartbeat")
        self.assertEqual(trigger["config"], {"every_seconds": 300})
        self.assertFalse(trigger["enabled"])
        self.assertEqual(
            self.client.get(f"/api/jarvis/workflows/{workflow['id']}/triggers").json(),
            [trigger],
        )

    def test_aide_schedule_creation_is_atomic_and_owner_scoped(self):
        response = self.client.post(
            "/api/jarvis/aide-schedules",
            json={
                "name": "morning plan",
                "prompt": "prepare my day",
                "kind": "schedule",
                "config": {"time": "09:00", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                "timezone": "UTC",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["workflow"]["deterministic_action"], "aide_handoff")
        self.assertTrue(body["workflow"]["enabled"])
        self.assertEqual(body["trigger"]["kind"], "schedule")
        self.assertTrue(body["trigger"]["enabled"])

    def test_invalid_aide_schedule_does_not_leave_a_partial_workflow(self):
        response = self.client.post(
            "/api/jarvis/aide-schedules",
            json={
                "name": "broken",
                "prompt": "should not persist",
                "kind": "schedule",
                "config": {"time": "99:99"},
                "timezone": "UTC",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/jarvis/workflows").json(), [])

    def test_aide_schedule_edit_rejects_other_workflows_and_rolls_back_invalid_timing(self):
        unrelated = self._workflow(deterministic_action="aide_handoff", prompt="keep me")
        trigger = self.client.post(
            f"/api/jarvis/workflows/{unrelated['id']}/triggers",
            json={"kind": "interval", "config": {"every_seconds": 300}},
        )
        self.assertEqual(trigger.status_code, 200, trigger.text)
        refused = self.client.patch(
            f"/api/jarvis/aide-schedules/{unrelated['id']}",
            json={
                "name": "hijacked",
                "prompt": "replace it",
                "kind": "schedule",
                "config": {"time": "09:00", "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                "timezone": "UTC",
            },
        )
        self.assertEqual(refused.status_code, 409, refused.text)

        created = self.client.post(
            "/api/jarvis/aide-schedules",
            json={
                "name": "safe",
                "prompt": "original prompt",
                "kind": "interval",
                "config": {"every_seconds": 300},
                "timezone": "UTC",
            },
        ).json()
        workflow_id = created["workflow"]["id"]
        invalid = self.client.patch(
            f"/api/jarvis/aide-schedules/{workflow_id}",
            json={
                "name": "changed too early",
                "prompt": "changed too early",
                "kind": "interval",
                "config": {"every_seconds": 0},
                "timezone": "UTC",
            },
        )

        self.assertEqual(invalid.status_code, 400, invalid.text)
        saved = next(
            item
            for item in self.client.get("/api/jarvis/workflows").json()
            if item["id"] == workflow_id
        )
        self.assertEqual(saved["name"], "safe")
        self.assertEqual(saved["prompt"], "original prompt")

    def test_paused_workflow_cannot_queue_then_enabled_workflow_gets_run_event(self):
        workflow = self._workflow()
        blocked = self.client.post(f"/api/jarvis/workflows/{workflow['id']}/runs")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["code"], "workflow_paused")
        enabled = self.client.patch(
            f"/api/jarvis/workflows/{workflow['id']}", json={"enabled": True}
        )
        self.assertEqual(enabled.status_code, 200)
        run = self.client.post(f"/api/jarvis/workflows/{workflow['id']}/runs").json()
        self.assertEqual(run["state"], "queued")
        self.assertEqual([item["kind"] for item in run["events"]], ["run_queued"])
        self.assertEqual(self.client.get(f"/api/jarvis/runs/{run['id']}").json(), run)

    def test_runs_can_be_filtered_by_workflow_before_the_limit(self):
        target = self._workflow(name="target")
        other = self._workflow(name="other")
        for workflow in (target, other):
            response = self.client.patch(
                f"/api/jarvis/workflows/{workflow['id']}", json={"enabled": True}
            )
            self.assertEqual(response.status_code, 200, response.text)
        target_run = self.client.post(f"/api/jarvis/workflows/{target['id']}/runs").json()
        self.client.post(f"/api/jarvis/workflows/{other['id']}/runs")

        response = self.client.get(
            "/api/jarvis/runs",
            params={"workflow_id": target["id"], "limit": 1},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row["id"] for row in response.json()], [target_run["id"]])

    def test_connector_secret_is_masked_in_api_and_encrypted_in_raw_database(self):
        secret = "synthetic-jarvis-connector-secret"
        created = self.client.post(
            "/api/jarvis/connectors",
            json={
                "name": "private channel",
                "kind": "test",
                "config": {"address": "local"},
                "secret": secret,
                "allowlist": ["owner"],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        public = created.json()
        self.assertTrue(public["secret_configured"])
        self.assertNotIn("secret", public)
        self.assertNotIn(secret, created.text)
        self.assertEqual(self.client.get("/api/jarvis/connectors").json(), [public])

        with self.eng.connect() as conn:
            raw = conn.execute(
                text("SELECT secret FROM jarvis_connectors WHERE id=:id"),
                {"id": public["id"]},
            ).scalar_one()
        self.assertNotEqual(raw, secret)
        self.assertNotIn(secret, raw)
        db = self.db()
        self.assertEqual(db.get(JarvisConnector, public["id"]).secret, secret)
        db.close()

    def test_json_payloads_are_bounded(self):
        response = self.client.post(
            "/api/jarvis/workflows",
            json={"name": "too large", "delivery_policy": {"x": "z" * 9000}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "json_value_too_large")

    def test_connector_public_config_rejects_secret_fields_and_url_credentials(self):
        cases = [
            {"password": "plaintext"},
            {"nested": {"api_key": "plaintext"}},
            {"url": "https://owner:private@example.test/path"},
        ]
        for config in cases:
            with self.subTest(config=config):
                response = self.client.post(
                    "/api/jarvis/connectors",
                    json={"name": "unsafe", "kind": "test", "config": config},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "connector_secret_in_config")
        self.assertEqual(self.client.get("/api/jarvis/connectors").json(), [])


class JarvisRunStateTest(ApiTest):
    def _run(self):
        db = self.db()
        workflow = JarvisWorkflow(name="durable", enabled=True)
        db.add(workflow)
        db.flush()
        run = create_run(db, workflow)
        db.commit()
        db.refresh(run)
        return db, run

    def test_run_state_and_append_only_events_survive_new_session(self):
        db, run = self._run()
        run_id = run.id
        transition_run(db, run, "running")
        append_event(db, run, "checkpoint_before", tool_name="test", summary="before")
        transition_run(db, run, "succeeded", result_summary="complete")
        db.commit()
        db.close()

        db = self.db()
        saved = db.get(JarvisRun, run_id)
        self.assertEqual(saved.state, "succeeded")
        self.assertEqual(saved.result_summary, "complete")
        events = (
            db.query(JarvisRunEvent)
            .filter_by(run_id=run_id)
            .order_by(JarvisRunEvent.sequence)
            .all()
        )
        self.assertEqual([event.sequence for event in events], [1, 2, 3, 4])
        self.assertEqual(
            [event.kind for event in events],
            ["run_queued", "run_state", "checkpoint_before", "run_state"],
        )
        db.close()

    def test_invalid_terminal_transition_is_rejected(self):
        db, run = self._run()
        transition_run(db, run, "cancelled")
        with self.assertRaisesRegex(ValueError, "invalid_run_transition"):
            transition_run(db, run, "running")
        db.rollback()
        db.close()

    def test_choice_is_durable_and_approval_cannot_use_choice_answer_path(self):
        db, run = self._run()
        run_id = run.id
        transition_run(db, run, "running")
        choice = create_prompt(
            db,
            run,
            kind="choice",
            question="which one?",
            options=["a", "b"],
            expires_at=datetime.now() + timedelta(minutes=5),
        )
        db.commit()
        choice_id = choice.id
        db.close()

        answered = self.client.post(f"/api/jarvis/prompts/{choice_id}/answer", json={"answer": "b"})
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(answered.json()["state"], "answered")
        self.assertEqual(answered.json()["answer"], "b")

        db = self.db()
        run = db.get(JarvisRun, run_id)
        self.assertEqual(run.state, "queued")
        transition_run(db, run, "running")
        approval = create_prompt(
            db,
            run,
            kind="approval",
            question="send it?",
            action="send",
            target="owner",
            capability="message.send",
        )
        db.commit()
        approval_id = approval.id
        db.close()

        blocked = self.client.post(
            f"/api/jarvis/prompts/{approval_id}/answer", json={"answer": "yes"}
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.json()["code"], "approval_requires_exact_gate")

    def test_expired_choice_fails_closed(self):
        db, run = self._run()
        transition_run(db, run, "running")
        prompt = create_prompt(
            db,
            run,
            kind="choice",
            question="late?",
            options=["yes"],
            expires_at=datetime.now() - timedelta(seconds=1),
        )
        db.commit()
        prompt_id = prompt.id
        db.close()
        response = self.client.post(
            f"/api/jarvis/prompts/{prompt_id}/answer", json={"answer": "yes"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "prompt_expired")
        db = self.db()
        self.assertEqual(db.get(JarvisRunPrompt, prompt_id).state, "expired")
        db.close()

    def test_structured_questions_survive_reload_and_validate_every_answer(self):
        db, run = self._run()
        transition_run(db, run, "running")
        prompt = create_prompt(
            db,
            run,
            kind="choice",
            title="Choose the verification",
            questions=[
                {
                    "id": "surface",
                    "prompt": "Which surface?",
                    "choices": [
                        {"id": "files", "label": "Files"},
                        {"id": "aide", "label": "Aide"},
                    ],
                    "allow_free_text": True,
                },
                {
                    "id": "proof",
                    "prompt": "Which proof?",
                    "selection": "multiple",
                    "choices": [
                        {"id": "browser", "label": "browser"},
                        {"id": "tests", "label": "tests"},
                    ],
                },
            ],
        )
        db.commit()
        prompt_id = prompt.id
        run_id = run.id
        db.close()

        loaded = self.client.get(f"/api/jarvis/runs/{run_id}").json()
        saved = next(item for item in loaded["prompts"] if item["id"] == prompt_id)
        self.assertEqual(saved["question_schema"]["questions"][0]["id"], "surface")

        invalid = self.client.post(
            f"/api/jarvis/prompts/{prompt_id}/answer",
            json={
                "answers": {
                    "surface": {"selected": ["unknown"]},
                    "proof": {"selected": ["browser"]},
                }
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["code"], "question_choice_invalid")

        answered = self.client.post(
            f"/api/jarvis/prompts/{prompt_id}/answer",
            json={
                "answers": {
                    "surface": {"selected": ["files"], "free_text": "phone too"},
                    "proof": {"selected": ["browser", "tests"]},
                }
            },
        )
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(
            answered.json()["answer_data"]["answers"]["proof"]["selected"],
            ["browser", "tests"],
        )

    def test_only_one_pending_prompt_is_allowed_per_run(self):
        db, run = self._run()
        transition_run(db, run, "running")
        create_prompt(db, run, kind="choice", question="first?")
        with self.assertRaisesRegex(ValueError, "prompt_already_pending"):
            create_prompt(db, run, kind="choice", question="second?")
        db.rollback()
        db.close()

    def test_live_agent_question_uses_jarvis_record_and_resumes_same_run(self):
        db, run = self._run()
        transition_run(db, run, "running")
        db.commit()
        run_id = run.id
        db.close()
        request = normalize_request(
            {
                "questions": [
                    {
                        "id": "surface",
                        "prompt": "Which surface?",
                        "choices": [
                            {"id": "files", "label": "Files"},
                            {"id": "aide", "label": "Aide"},
                        ],
                    }
                ]
            }
        )
        prompt_id = agent_runtime._create_jarvis_question(
            {"_jarvis_run_id": run_id}, request
        )
        agent_runtime._register_user_question(
            "request-1", "agent-run-1", request, jarvis_prompt_id=prompt_id
        )
        try:
            self.assertTrue(
                agent_runtime.resolve_user_question(
                    "request-1",
                    {"answers": {"surface": {"selected": ["files"]}}},
                )
            )
            db = self.db()
            self.assertEqual(db.get(JarvisRunPrompt, prompt_id).state, "answered")
            self.assertEqual(db.get(JarvisRun, run_id).state, "queued")
            db.close()
            agent_runtime._resume_jarvis_after_question({"_jarvis_run_id": run_id})
            db = self.db()
            self.assertEqual(db.get(JarvisRun, run_id).state, "running")
            db.close()
        finally:
            agent_runtime._pending_questions.pop("request-1", None)

    def test_restart_marks_unconfirmed_side_effect_uncertain_and_other_run_interrupted(self):
        db, uncertain_run = self._run()
        transition_run(db, uncertain_run, "running")
        append_event(
            db,
            uncertain_run,
            "side_effect_started",
            summary="provider call started",
        )
        uncertain_id = uncertain_run.id

        workflow = db.query(JarvisWorkflow).first()
        interrupted_run = create_run(db, workflow)
        transition_run(db, interrupted_run, "running")
        interrupted_id = interrupted_run.id
        db.commit()
        db.close()

        result = reconcile_interrupted_runs()
        self.assertEqual(result, {"interrupted": 1, "uncertain": 1})
        db = self.db()
        self.assertEqual(db.get(JarvisRun, uncertain_id).state, "uncertain")
        self.assertEqual(db.get(JarvisRun, interrupted_id).state, "interrupted")
        db.close()
        self.assertEqual(reconcile_interrupted_runs(), {"interrupted": 0, "uncertain": 0})


class JarvisRecordMigrationTest(unittest.TestCase):
    def test_migration_creates_separate_tables_and_indexes_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="alles-jarvis-schema-") as temp:
            engine = create_engine(f"sqlite:///{Path(temp) / 'old.db'}")
            with engine.begin() as conn:
                m0026_jarvis_records.up(conn)
                m0026_jarvis_records.up(conn)
                tables = {
                    row[0]
                    for row in conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    )
                }
                indexes = {
                    row[0]
                    for row in conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='index'")
                    )
                }
            engine.dispose()
        self.assertTrue(
            {
                "jarvis_workflows",
                "jarvis_triggers",
                "jarvis_runs",
                "jarvis_run_events",
                "jarvis_run_prompts",
                "jarvis_delivery_attempts",
                "jarvis_connectors",
            }.issubset(tables)
        )
        self.assertIn("ux_jarvis_run_events_run_sequence", indexes)
